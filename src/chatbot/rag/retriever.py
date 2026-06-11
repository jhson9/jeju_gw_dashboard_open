"""벡터 검색 — 질문 임베딩 → ChromaDB 유사 청크 top-k."""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from ..config import CHROMA_DIR, EMBEDDING_MODEL, TOP_K

COLLECTION = "jeju_groundwater_law"


@dataclass
class Hit:
    chunk_id: str
    doc_name: str
    category: str
    article: str
    page: int
    eff_date: str
    source_file: str
    text: str
    score: float  # 유사도 (1 - cosine distance)

    @property
    def label(self) -> str:
        return f"{self.doc_name} {self.article}"


@lru_cache(maxsize=1)
def _embedder():
    from sentence_transformers import SentenceTransformer
    return SentenceTransformer(EMBEDDING_MODEL)


@lru_cache(maxsize=1)
def _collection():
    import chromadb
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return client.get_collection(COLLECTION)


def embed_query(question: str):
    return _embedder().encode([question], normalize_embeddings=True)[0]


def search(question: str, top_k: int = TOP_K,
           category: str | None = None) -> tuple[list[Hit], "object"]:
    """질문 → (검색 결과, 질문 임베딩). 임베딩은 3D 시각화 재사용."""
    q_emb = embed_query(question)
    where = {"category": category} if category else None
    res = _collection().query(
        query_embeddings=[q_emb.tolist()], n_results=top_k, where=where,
        include=["documents", "metadatas", "distances"])
    hits: list[Hit] = []
    for cid, doc, meta, dist in zip(res["ids"][0], res["documents"][0],
                                    res["metadatas"][0], res["distances"][0]):
        hits.append(Hit(chunk_id=cid, text=doc, score=1.0 - dist,
                        doc_name=meta["doc_name"], category=meta["category"],
                        article=meta["article"], page=int(meta["page"]),
                        eff_date=meta.get("eff_date", ""),
                        source_file=meta["source_file"]))
    return hits, q_emb


def index_ready() -> bool:
    try:
        return _collection().count() > 0
    except Exception:
        return False
