"""챗봇 UI 렌더러 — standalone_app과 Tab51이 공유하는 화면 본체.

디자인: 대시보드 theme.py(CSS 변수·subsection-title) 체계를 따른다.
배치: 설정(상단) → 질문 입력(상단 고정) → [대화(최신순) | 3D 임베딩 공간].
"""
from __future__ import annotations

import streamlit as st

from .config import LLM_MODEL, LLM_MODEL_HQ, TOP_K

_SS = "chatbot51_"  # session_state 키 접두어 (대시보드 충돌 방지)

_SAMPLE_QUESTIONS = [
    "지하수 개발·이용 허가는 누구에게 받아야 하나요?",
    "제주도에서 먹는샘물 제조·판매용 지하수 허가가 가능한가요?",
    "지하수이용부담금은 어떤 근거로 부과되나요?",
    "지하수 수질검사는 얼마나 자주 받아야 하나요?",
]

# 대시보드 theme.py와 동일 토큰 (단독 실행 시 폴백용 최소 CSS)
_CHATBOT_CSS = """
<style>
  :root {
    --color-text-info: #185fa5;
    --color-bg-info: #e6f1fb;
    --color-border-info: #85b7eb;
    --color-bg-secondary: #f5f5f3;
    --color-text-secondary: #5f5e5a;
  }
  /* 질문 입력창 — tab11 관정명 입력과 유사한 높이·스타일 */
  .st-key-chatbot51_qinput input {
    height: 50px !important;
    font-size: 15px !important;
    border: 1px solid var(--color-border-info) !important;
    border-radius: 10px !important;
    background: #ffffff !important;
  }
  /* 질문 버튼 — 빨간 사각형 + 흰 화살표 (클로드 스타일)
     (2026-06-11 v3) st.form 은 st-key 클래스가 안 붙어 기존 셀렉터 미적용
     → 범용 셀렉터 병기 (본 탭에만 form 존재 — 영향 범위 확인됨). */
  .st-key-chatbot51_form [data-testid="stFormSubmitButton"] button,
  div[data-testid="stFormSubmitButton"] button {
    height: 50px !important;
    width: 56px !important;
    min-width: 56px !important;
    font-size: 22px !important;
    font-weight: 700 !important;
    border-radius: 12px !important;
    background: #e24b4a !important;   /* --color-danger */
    color: #ffffff !important;
    border: none !important;
    margin-left: auto !important;
  }
  .st-key-chatbot51_form [data-testid="stFormSubmitButton"] button:hover,
  div[data-testid="stFormSubmitButton"] button:hover {
    background: #c93a39 !important;
  }
  div[data-testid="stFormSubmitButton"] button p {
    color: #ffffff !important;
    font-size: 22px !important;
    font-weight: 700 !important;
  }
  .chatbot51-title {
    font-size: 17px; font-weight: 700; color: var(--color-text-info);
    margin: 2px 0 2px 0;
  }
  .chatbot51-disclaimer {
    text-align: center;
    font-size: 12px; color: var(--color-text-secondary);
    margin: 2px 0 12px 0;
  }
</style>
"""


def _init_state() -> None:
    st.session_state.setdefault(_SS + "history", [])   # [{q, a, hits}] 최신이 [0]
    st.session_state.setdefault(_SS + "last_hits", [])
    st.session_state.setdefault(_SS + "last_qemb", None)


def _render_sources(hits: list) -> None:
    for i, h in enumerate(hits, 1):
        head = f"근거 {i} │ {h['label']} (p.{h['page']}, 유사도 {h['score']:.2f})"
        with st.expander(head):
            if h.get("eff_date"):
                st.caption(f"시행일자: {h['eff_date']} │ 출처: {h['source_file']}")
            if "〔표〕" in h["label"]:  # 표 청크는 마크다운 표로 표시
                st.markdown(h["text"])
            else:
                st.text(h["text"])


def _render_pair(pair: dict) -> None:
    with st.chat_message("user"):
        st.markdown(pair["q"])
    with st.chat_message("assistant"):
        st.markdown(pair["a"])
        if pair.get("hits"):
            _render_sources(pair["hits"])


def render_chatbot(default_model: str = LLM_MODEL,
                   hq_model: str = LLM_MODEL_HQ, top_k: int = TOP_K,
                   show_title: bool = True) -> None:
    _init_state()
    st.markdown(_CHATBOT_CSS, unsafe_allow_html=True)

    # ── 제목 ─────────────────────────────────────────────────────
    if show_title:
        st.markdown('<p class="chatbot51-title">💧 51. 지하수 챗봇 — 법령·지침 질의응답 (오프라인)</p>',
                    unsafe_allow_html=True)

    # ── 설정 (상단 1줄 상시 노출) ────────────────────────────────
    c1, c2, c3, c4 = st.columns([2.6, 2.4, 1.5, 1.2])
    model = c1.radio("LLM 모델", [default_model, hq_model], index=0,
                     horizontal=True, help="7.8B는 고품질·저속 (별도 설치 필요)")
    k = c2.slider("검색 근거 수 (top-k)", 3, 10, top_k)
    # (2026-06-11 v2 성능) 기본 OFF — 진입 시 3D 산점도(수천 점) 렌더 생략
    show_3d = c3.toggle("입체 단어구조(3D)", value=False)
    c4.markdown("<div style='height:26px'></div>", unsafe_allow_html=True)
    if c4.button("대화 초기화", use_container_width=True):
        for key in ("history", "last_hits", "last_qemb"):
            st.session_state[_SS + key] = [] if key != "last_qemb" else None
        st.rerun()

    # ── 준비 상태 점검 ───────────────────────────────────────────
    # 🛡️ (2026-06-11 검증팀 G3) ttl=60 추가 — 기존엔 실패 결과(False)도
    # 영구 캐시(cache_resource 는 F5 로 안 지워짐)되어, setup_chatbot.bat
    # 실행 후 새로고침해도 서버 재시작 전까지 "설치 안내"만 표시됐음.
    @st.cache_resource(show_spinner="챗봇 구성요소 점검 중...", ttl=60)
    def _health(m: str):
        from .rag.pipeline import health_check
        return health_check(m)

    # (2026-06-11 v2 성능) 세션 내 1회 성공하면 재점검 생략 — 그룹 전환마다
    # chromadb 컬렉션 count + ollama HTTP 점검(수 초)이 반복되던 것 차단.
    # 실패 상태에서는 기존 ttl=60 재점검 동작 유지.
    _ok_key = _SS + f"health_ok_{model}"
    if st.session_state.get(_ok_key):
        ok, msg = True, ""
    else:
        ok, msg = _health(model)
        if ok:
            st.session_state[_ok_key] = True
    if not ok:
        st.warning(msg)
        st.info("설치 안내: 프로젝트 루트의 `setup_chatbot.bat` 실행 후 "
                "아래 버튼 또는 새로고침으로 다시 점검하세요. "
                "(자동 재점검: 60초 주기)")
        if st.button("🔄 다시 점검", key=_SS + "health_retry"):
            _health.clear()
            st.rerun()
        return

    # ── 질문 입력 (상단 고정) ────────────────────────────────────
    with st.form(_SS + "form", clear_on_submit=True):
        ci, cb = st.columns([8, 0.9])
        with ci:
            question = st.text_input(
                "질문", key="chatbot51_qinput", label_visibility="collapsed",
                placeholder="법령에 대해 질문하세요 — 지하수법·먹는물관리법·물환경보전법·온천법·제주특별법·도 조례 등 24건 법령·지침 근거 (예: 지하수 개발·이용 허가 절차는?)")
        with cb:
            # (2026-06-11 v3 사용자 요청) 흰색 아래방향 화살표
            submitted = st.form_submit_button("↓")
    st.markdown('<div class="chatbot51-disclaimer">챗봇은 AI이며 실수할 수 있습니다. '
                '답변의 근거(조문 원문)를 다시 한번 확인해 주세요.</div>',
                unsafe_allow_html=True)

    # 예시 질문 (첫 화면)
    pending_key = _SS + "pending"
    if not st.session_state[_SS + "history"]:
        # (2026-06-11 v2) 법령 목록 안내문은 입력창 placeholder 로 이동 (공간 절약)
        cols = st.columns(2)
        for i, q in enumerate(_SAMPLE_QUESTIONS):
            if cols[i % 2].button(q, key=f"{_SS}sample{i}", use_container_width=True):
                st.session_state[pending_key] = q
                st.rerun()
    if not (submitted and question.strip()) and pending_key in st.session_state:
        question, submitted = st.session_state.pop(pending_key), True

    # ── 본문: 대화(최신순) | 3D ──────────────────────────────────
    col_chat, col_viz = st.columns([5, 4]) if show_3d else (st.container(), None)

    with col_chat:
        new_pair_done = False
        if submitted and question and question.strip():
            q = question.strip()
            with st.chat_message("user"):
                st.markdown(q)
            with st.chat_message("assistant"):
                from .rag.pipeline import ask_stream
                with st.spinner("법령 검색 중..."):
                    result, stream = ask_stream(q, top_k=k, model=model)
                answer = st.write_stream(stream)
                hits = [{"label": h.label, "page": h.page, "score": h.score,
                         "eff_date": h.eff_date, "source_file": h.source_file,
                         "text": h.text, "chunk_id": h.chunk_id}
                        for h in result.hits]
                _render_sources(hits)
            st.session_state[_SS + "history"].insert(
                0, {"q": q, "a": answer, "hits": hits})
            st.session_state[_SS + "last_hits"] = [h["chunk_id"] for h in hits]
            st.session_state[_SS + "last_qemb"] = result.q_embedding
            new_pair_done = True

        # 과거 대화 — 최신이 위 (방금 답변한 쌍은 위에서 이미 렌더됨)
        start = 1 if new_pair_done else 0
        for pair in st.session_state[_SS + "history"][start:]:
            _render_pair(pair)

    if show_3d and col_viz is not None:
        with col_viz:
            st.markdown('<p class="subsection-title" style="margin:4px 0;">'
                        '🧊 법령 임베딩 공간 (입체 단어구조)</p>',
                        unsafe_allow_html=True)
            try:
                from .viz.embedding_3d import coords_available, make_figure
                if coords_available():
                    fig = make_figure(
                        hit_ids=st.session_state[_SS + "last_hits"],
                        q_embedding=st.session_state[_SS + "last_qemb"])
                    st.plotly_chart(fig, use_container_width=True, key=_SS + "viz3d")
                    st.caption("점 1개 = 조문/문단 1개 · 질문하면 ★(질문)과 ◆(검색된 근거)가 표시됩니다.")
                else:
                    st.info("3D 좌표가 없습니다. `python -m src.chatbot.ingest.build_index --umap-only` 실행 후 새로고침하세요.")
            except Exception as e:  # 3D 실패가 챗봇 본체를 막지 않도록
                st.warning(f"3D 시각화를 표시할 수 없습니다: {e}")
