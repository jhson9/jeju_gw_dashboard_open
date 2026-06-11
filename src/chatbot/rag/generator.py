"""답변 생성 — Ollama 로컬 LLM (스트리밍, 완전 오프라인)."""
from __future__ import annotations

from collections.abc import Iterator

from ..config import (LLM_MODEL, MAX_CONTEXT_CHARS, NUM_CTX, OLLAMA_HOST,
                      SYSTEM_PROMPT, TEMPERATURE)
from .retriever import Hit


def _client():
    import ollama
    return ollama.Client(host=OLLAMA_HOST)


def ollama_ready(model: str = LLM_MODEL) -> tuple[bool, str]:
    """Ollama 서버·모델 가용성 점검 → (가능여부, 안내메시지)."""
    try:
        models = [m.model for m in _client().list().models]
    except Exception:
        return False, ("Ollama 서버에 연결할 수 없습니다. "
                       "Ollama를 설치·실행한 뒤 다시 시도하세요. (ollama.com)")
    if not any(model.split(":")[0] in m for m in models):
        return False, (f"모델 '{model}'이 없습니다. 인터넷 연결 상태에서 "
                       f"`ollama pull {model}` 실행 후 다시 시도하세요.")
    return True, ""


def build_prompt(question: str, hits: list[Hit]) -> str:
    """검색 청크를 근거 블록으로 조립."""
    blocks, used = [], 0
    for i, h in enumerate(hits, 1):
        body = h.text[: MAX_CONTEXT_CHARS - used]
        used += len(body)
        blocks.append(f"[근거 {i}] {h.label} (p.{h.page}"
                      f"{', 시행 ' + h.eff_date if h.eff_date else ''})\n{body}")
        if used >= MAX_CONTEXT_CHARS:
            break
    context = "\n\n".join(blocks)
    return (f"다음은 검색된 법령·자료 근거입니다.\n\n{context}\n\n"
            f"위 근거만 사용하여 질문에 답하십시오.\n질문: {question}")


def generate_stream(question: str, hits: list[Hit],
                    model: str = LLM_MODEL) -> Iterator[str]:
    """스트리밍 답변 생성 (토큰 단위 yield)."""
    stream = _client().chat(
        model=model,
        messages=[{"role": "system", "content": SYSTEM_PROMPT},
                  {"role": "user", "content": build_prompt(question, hits)}],
        options={"temperature": TEMPERATURE, "num_ctx": NUM_CTX},
        stream=True)
    for part in stream:
        yield part["message"]["content"]


def generate(question: str, hits: list[Hit], model: str = LLM_MODEL) -> str:
    return "".join(generate_stream(question, hits, model))
