"""Tab51 지하수 법령 챗봇 — 설정.

이 모듈은 대시보드와 독립적으로 동작한다 (src.chatbot 단독 import 가능).
"""
from __future__ import annotations

from pathlib import Path

# ── 경로 ─────────────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).resolve().parents[2]          # 프로젝트 루트
PDF_DIR = ROOT_DIR / "data" / "07_chatbot"              # 원본 법령 PDF
INDEX_DIR = PDF_DIR / "index"                           # 산출물 (벡터DB 등)
CHROMA_DIR = INDEX_DIR / "chroma"
CHUNKS_PARQUET = INDEX_DIR / "chunks.parquet"           # 청크 원문+메타
COORDS_PARQUET = INDEX_DIR / "embeddings_3d.parquet"    # UMAP 3D 좌표
UMAP_REDUCER_PKL = INDEX_DIR / "umap_reducer.pkl"       # 질문 투영용

# ── 모델 ─────────────────────────────────────────────────────────────
EMBEDDING_MODEL = "BAAI/bge-m3"          # 한국어 포함 다국어 임베딩 (1024차원)
LLM_MODEL = "exaone3.5:2.4b"             # Ollama 모델명 (기본, CPU 쾌적)
LLM_MODEL_HQ = "exaone3.5:7.8b"          # 고품질 (선택 설치)
OLLAMA_HOST = "http://localhost:11434"

# ── 청크 분할 ────────────────────────────────────────────────────────
ARTICLE_MIN_COUNT = 10      # 조문이 이 수 이상 검출되면 '법령형' 분할 적용
REPORT_CHUNK_CHARS = 900    # 보고서형 청크 길이(자)
REPORT_CHUNK_OVERLAP = 150  # 보고서형 오버랩(자)
ARTICLE_MAX_CHARS = 1800    # 조문이 너무 길면 항(①②) 단위 재분할

# ── 검색/생성 ────────────────────────────────────────────────────────
TOP_K = 5                   # 검색 청크 수
MAX_CONTEXT_CHARS = 6000    # LLM에 넣을 컨텍스트 상한
NUM_CTX = 8192              # Ollama context window
TEMPERATURE = 0.1           # 법령 답변 → 낮게 (환각 억제)

SYSTEM_PROMPT = """당신은 제주도 지하수 업무를 지원하는 법령 전문 도우미입니다.

규칙:
1. 반드시 아래 제공된 [근거] 내용만 사용해 한국어로 답하십시오.
2. 근거에 없는 내용은 절대 지어내지 말고 "제공된 자료에서 찾을 수 없습니다"라고 답하십시오.
3. 답변에 사용한 근거는 (근거 1), (근거 2)처럼 번호로 인용하십시오.
4. 조문 번호, 수치, 기한은 근거 원문 그대로 정확히 옮기십시오.
5. 답변은 결론부터, 간결하고 구조적으로 작성하십시오.
6. 근거가 마크다운 표(|...|)이면 답변도 해당 부분을 마크다운 표로 작성하고,
   용도 구분(생활용수/농·어업용수/공업용수 등) 열을 혼동하지 마십시오."""
