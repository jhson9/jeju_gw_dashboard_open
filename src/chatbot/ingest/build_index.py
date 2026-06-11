"""인덱스 구축 CLI — PDF → 청크 → BGE-M3 임베딩 → ChromaDB + UMAP 3D.

실행 (프로젝트 루트에서):
    python -m src.chatbot.ingest.build_index            # 전체 구축
    python -m src.chatbot.ingest.build_index --no-umap  # 3D 좌표 생략

최초 1회는 임베딩 모델 다운로드(~2.3GB)를 위해 인터넷 필요.
이후 재구축은 완전 오프라인 가능.
"""
from __future__ import annotations

import argparse
import pickle
import sys
import time
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

import pandas as pd

from src.chatbot.config import (CHROMA_DIR, CHUNKS_PARQUET, COORDS_PARQUET,
                                EMBEDDING_MODEL, INDEX_DIR, PDF_DIR,
                                UMAP_REDUCER_PKL)
from src.chatbot.ingest.chunker import Chunk, chunk_pdf

COLLECTION = "jeju_groundwater_law"


def collect_chunks() -> list[Chunk]:
    pdfs = sorted(PDF_DIR.glob("*.pdf"))
    if not pdfs:
        sys.exit(f"PDF가 없습니다: {PDF_DIR}")
    all_chunks: list[Chunk] = []
    for pdf in pdfs:
        cks = chunk_pdf(pdf)
        all_chunks.extend(cks)
        print(f"  {len(cks):4d}개  {pdf.name}")
    # 동일 법령 복수 버전(예: 물환경보전법 현행+시행예정) 구분 표시
    by_doc = defaultdict(set)
    for c in all_chunks:
        by_doc[c.doc_name].add(c.source_file)
    for c in all_chunks:
        if len(by_doc[c.doc_name]) > 1 and c.eff_date:
            c.doc_name = f"{c.doc_name}({c.eff_date} 시행)"
    return all_chunks


def embed_chunks(chunks: list[Chunk]):
    from sentence_transformers import SentenceTransformer
    print(f"\n임베딩 모델 로딩: {EMBEDDING_MODEL} (최초 실행 시 다운로드)")
    model = SentenceTransformer(EMBEDDING_MODEL)
    texts = [f"{c.label}\n{c.text}" for c in chunks]  # 라벨 포함 → 검색력 향상
    t0 = time.time()
    emb = model.encode(texts, batch_size=16, show_progress_bar=True,
                       normalize_embeddings=True)
    print(f"임베딩 완료: {len(texts)}개, {time.time()-t0:.0f}초")
    return emb


def save_chroma(chunks: list[Chunk], embeddings) -> None:
    import chromadb
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    try:
        client.delete_collection(COLLECTION)
    except Exception:
        pass
    col = client.create_collection(COLLECTION, metadata={"hnsw:space": "cosine"})
    B = 500
    for i in range(0, len(chunks), B):
        part = chunks[i:i + B]
        col.add(
            ids=[c.chunk_id for c in part],
            embeddings=[e.tolist() for e in embeddings[i:i + B]],
            documents=[c.text for c in part],
            metadatas=[{"doc_name": c.doc_name, "category": c.category,
                        "article": c.article, "page": c.page,
                        "eff_date": c.eff_date, "source_file": c.source_file}
                       for c in part])
    print(f"ChromaDB 저장 완료: {col.count()}개 → {CHROMA_DIR}")


def save_umap(chunks: list[Chunk], embeddings) -> None:
    import umap
    print("\nUMAP 3D 좌표 계산 중 (수 분 소요)...")
    reducer = umap.UMAP(n_components=3, n_neighbors=15, min_dist=0.1,
                        metric="cosine", random_state=42)
    coords = reducer.fit_transform(embeddings)
    df = pd.DataFrame({
        "chunk_id": [c.chunk_id for c in chunks],
        "doc_name": [c.doc_name for c in chunks],
        "category": [c.category for c in chunks],
        "article": [c.article for c in chunks],
        "x": coords[:, 0], "y": coords[:, 1], "z": coords[:, 2]})
    df.to_parquet(COORDS_PARQUET, index=False)
    with open(UMAP_REDUCER_PKL, "wb") as f:
        pickle.dump(reducer, f)
    print(f"3D 좌표 저장: {COORDS_PARQUET}")


def umap_only() -> None:
    """벡터DB에 저장된 임베딩으로 UMAP 3D만 재계산 (재임베딩 불필요, 수 분)."""
    import chromadb
    import numpy as np
    col = chromadb.PersistentClient(path=str(CHROMA_DIR)).get_collection(COLLECTION)
    n = col.count()
    print(f"벡터DB에서 임베딩 로드: {n}개")
    ids, embs, metas = [], [], []
    B = 500
    for off in range(0, n, B):
        r = col.get(limit=B, offset=off, include=["embeddings", "metadatas"])
        ids += r["ids"]; metas += r["metadatas"]; embs.extend(r["embeddings"])
    embs = np.asarray(embs)

    class _C:  # save_umap이 기대하는 최소 속성
        def __init__(self, cid, m):
            self.chunk_id = cid
            self.doc_name = m["doc_name"]; self.category = m["category"]
            self.article = m["article"]
    save_umap([_C(c, m) for c, m in zip(ids, metas)], embs)


def add_tables() -> None:
    """표 청크만 추출·임베딩해 기존 벡터DB에 증분 추가 (수 분, 재임베딩 불필요)."""
    import chromadb
    from src.chatbot.ingest.chunker import table_chunks
    all_t = []
    for pdf in sorted(PDF_DIR.glob("*.pdf")):
        cks = table_chunks(pdf)
        all_t.extend(cks)
        print(f"  표 {len(cks):3d}개  {pdf.name}")
    print(f"총 표 청크: {len(all_t)}개")
    if not all_t:
        return

    emb = embed_chunks(all_t)

    col = chromadb.PersistentClient(path=str(CHROMA_DIR)).get_collection(COLLECTION)
    # 기존 표 청크 제거 (재실행 안전)
    n, old_ids, B = col.count(), [], 500
    for off in range(0, n, B):
        r = col.get(limit=B, offset=off, include=[])
        old_ids += [i for i in r["ids"] if "::table" in i]
    if old_ids:
        col.delete(ids=old_ids)
        print(f"기존 표 청크 {len(old_ids)}개 교체")
    for i in range(0, len(all_t), B):
        part = all_t[i:i + B]
        col.add(
            ids=[c.chunk_id for c in part],
            embeddings=[e.tolist() for e in emb[i:i + B]],
            documents=[c.text for c in part],
            metadatas=[{"doc_name": c.doc_name, "category": c.category,
                        "article": c.article, "page": c.page,
                        "eff_date": c.eff_date, "source_file": c.source_file}
                       for c in part])
    print(f"벡터DB 갱신 완료: 총 {col.count()}개")

    # chunks.parquet 갱신
    if CHUNKS_PARQUET.exists():
        df = pd.read_parquet(CHUNKS_PARQUET)
        df = df[~df["chunk_id"].str.contains("::table", regex=False)]
        new_df = pd.DataFrame([{
            "chunk_id": c.chunk_id, "doc_name": c.doc_name,
            "category": c.category, "article": c.article, "page": c.page,
            "eff_date": c.eff_date, "source_file": c.source_file,
            "text": c.text} for c in all_t])
        pd.concat([df, new_df], ignore_index=True).to_parquet(
            CHUNKS_PARQUET, index=False)
    print("\n다음으로 3D 좌표를 갱신하세요: "
          "python -m src.chatbot.ingest.build_index --umap-only")


def main() -> None:
    ap = argparse.ArgumentParser(description="지하수 법령 챗봇 인덱스 구축")
    ap.add_argument("--no-umap", action="store_true", help="UMAP 3D 계산 생략")
    ap.add_argument("--umap-only", action="store_true",
                    help="기존 벡터DB 임베딩으로 3D 좌표만 재계산")
    ap.add_argument("--add-tables", action="store_true",
                    help="표(별표) 청크만 추출해 기존 인덱스에 증분 추가")
    args = ap.parse_args()

    if args.add_tables:
        add_tables()
        print("\n✅ 표 청크 증분 추가 완료.")
        return

    if args.umap_only:
        umap_only()
        print("\n✅ 3D 좌표 재계산 완료.")
        return

    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    print(f"1) PDF 청크 분할: {PDF_DIR}")
    chunks = collect_chunks()
    print(f"   총 {len(chunks)}개 청크")

    pd.DataFrame([{
        "chunk_id": c.chunk_id, "doc_name": c.doc_name, "category": c.category,
        "article": c.article, "page": c.page, "eff_date": c.eff_date,
        "source_file": c.source_file, "text": c.text} for c in chunks]
    ).to_parquet(CHUNKS_PARQUET, index=False)

    print("\n2) 임베딩")
    emb = embed_chunks(chunks)

    print("\n3) 벡터DB 저장")
    save_chroma(chunks, emb)

    if not args.no_umap:
        save_umap(chunks, emb)

    print("\n✅ 인덱스 구축 완료. 이제 완전 오프라인으로 질의응답이 가능합니다.")


if __name__ == "__main__":
    main()
