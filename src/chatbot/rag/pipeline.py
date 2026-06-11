"""RAG 파이프라인 — 질문 → 검색 → 생성 → (답변, 근거, 질문임베딩)."""
from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field

from ..config import LLM_MODEL, TOP_K
from .generator import generate_stream, ollama_ready
from .retriever import Hit, index_ready, search


@dataclass
class RagResult:
    question: str
    hits: list[Hit] = field(default_factory=list)
    q_embedding: object = None  # 3D 시각화용


def ask_stream(question: str, top_k: int = TOP_K,
               model: str = LLM_MODEL,
               category: str | None = None) -> tuple[RagResult, Iterator[str]]:
    """검색 후 (메타결과, 답변 스트림) 반환. UI에서 스트림 소비."""
    hits, q_emb = search(question, top_k=top_k, category=category)
    result = RagResult(question=question, hits=hits, q_embedding=q_emb)
    if not hits:
        def _empty():
            yield "제공된 자료에서 관련 근거를 찾을 수 없습니다."
        return result, _empty()
    return result, generate_stream(question, hits, model=model)


def health_check(model: str = LLM_MODEL) -> tuple[bool, str]:
    """인덱스·LLM 가용성 종합 점검."""
    if not index_ready():
        return False, ("벡터 인덱스가 없습니다. 먼저 인덱스를 구축하세요:\n"
                       "`python -m src.chatbot.ingest.build_index`")
    ok, msg = ollama_ready(model)
    return ok, msg
