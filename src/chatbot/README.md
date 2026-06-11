# Tab51 지하수 법령 챗봇 (src/chatbot)

법령·조례·지침 PDF 24건(data/07_chatbot) 기반 오프라인 RAG 챗봇.
상세 설계: `docs/spec_tab51_chatbot_개발계획.md`

## 1회 설치 (인터넷 필요)

프로젝트 루트에서 `setup_chatbot.bat` 더블클릭. 순서대로:

1. 파이썬 패키지 설치 (ollama, chromadb, sentence-transformers, pymupdf, umap-learn)
2. Ollama 미설치 시 다운로드 페이지 안내 → 설치 후 재실행
3. EXAONE 3.5 2.4B 모델 다운로드 (~1.6GB)
4. 법령 인덱스 구축 (BGE-M3 ~2.3GB 다운로드 포함, CPU 20~40분)

## 실행 (오프라인 가능)

```bat
streamlit run src/chatbot/standalone_app.py
```

## 구조

| 파일 | 역할 |
|---|---|
| `config.py` | 경로·모델·프롬프트 설정 |
| `ingest/pdf_loader.py` | PDF 추출 + 국가법령정보센터 머리글 제거 |
| `ingest/chunker.py` | 조문(제N조) 단위 분할, 보고서는 길이 기반 |
| `ingest/build_index.py` | 임베딩→ChromaDB→UMAP 3D (CLI) |
| `rag/retriever.py` | 질문 임베딩 → top-k 검색 |
| `rag/generator.py` | Ollama 스트리밍 생성 (환각 억제 프롬프트) |
| `rag/pipeline.py` | 검색+생성 통합, health_check |
| `viz/embedding_3d.py` | 입체 단어구조(3D 임베딩 지도) |
| `render.py` | 챗봇 화면 본체 (standalone과 Tab51 공유) |
| `standalone_app.py` | 단독 실행 진입점 |

## 법령 개정 시 갱신

새 PDF를 `data/07_chatbot/`에 넣고(구버전 제거)
`python -m src.chatbot.ingest.build_index` 재실행 — 오프라인 가능.

## Tab51 통합 (예정)

`src/dashboard/tabs/tab51_chatbot.py`에서 `from src.chatbot.render import
render_chatbot` 호출만 하면 됨. 단독 검증 후 진행.
