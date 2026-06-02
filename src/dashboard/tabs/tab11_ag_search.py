# ==============================================================================
#  파일명: src/dashboard/tabs/tab11_ag_search.py  —  Build 3.1
#  탭: ⑤ 관정 검색
# ------------------------------------------------------------------------------
#  Build 3.1 변경사항 (Phase 2):
#   - render() 전체를 단일 @st.fragment 로 (옵션 B, tab7/tab8 와 동일 패턴)
#   - 3개 fragment 분리(_filter/_result/_search_map) → 일반 함수로 격하
#   - 모든 내부 st.rerun() → fragment_rerun() (full rerun 회피로 흰 깜박임 차단)
#   - 마커 클릭 경로의 _bump_table_version() → _last_applied_df_idx=-1 만 리셋
#     (위젯 재마운트 회피 + 같은 행 재클릭 회귀 차단)
#   - 헤더 글자 13px → 15px (사용자 요청)
#
#  Build 3.0 변경사항:
#   - 레이아웃 재배치: 농업용 관정 현황 표 → 지도 → 검색 → 결과 표 순서
#   - 지도 로직을 tab7/tab8 와 동일 패턴으로 정렬 (zoom·center 보존)
#   - 캐시된 Map 객체 폐기 → selected_permit 변경 시 빨간 강조 즉시 반영
#   - 마커 tooltip 형식: '{well_id}|{permit_no}' — 빈 well_id 도 안전하게 식별
#   - 관정 선택 시 지도 height 780 → 430 (1/2) 동적 축소
#   - height 별 별도 key 사용 (st_folium 재마운트 사고 회피)
#   - 상세 필터 expander 제거 (3개 selectbox 한 줄 노출)
#
#  3가지 선택 경로 (모두 즉시 카드 표시):
#   ① 지도 마커 클릭 — tooltip 의 '{well_id}|{permit_no}' 로 자동 식별
#   ② 표 행 클릭 — fragment_rerun 으로 fragment-only update
#   ③ 키워드 입력 후 Enter — 단일 매칭이면 자동 선택, 다중이면 표 필터링
# ==============================================================================

from __future__ import annotations

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from src.analysis import ag_well_loader
from src.dashboard import ag_well_helpers
from src.dashboard.ag_map_builders import persist_zoom_center  # G3 fix 2026-05-30
from src.dashboard.quit_helper import quit_button
from src.dashboard.tabs._ag_well_select_helpers import (
    render_map_header_with_search,
    render_well_selection_bar,
)


# 2026-05-17 사용자 요청: 검색 input 을 지도 위 헤더 라인으로 이동.
_SEARCH_PLACEHOLDER = "관정명 입력 후 Enter (예: 90감산, F-285)"


# 결과 표 컬럼 (관리주체 추가로 13개)
# authority_kor 는 ag_well_loader._normalize_master 가 master.csv 의 원본
# 한글값(제주시/서귀포시/농어촌공사/제주특별자치도) 을 보존한 컬럼.
# 영문 코드 컬럼 authority (jeju/seogwipo) 와 분리 — 둘 다 master 에 있음.
_RESULT_COLUMNS: list[tuple[str, str]] = [
    ("permit_no",              "허가번호"),
    ("well_id",                "관정명"),
    ("well_si",                "시"),
    ("authority_kor",          "관리주체"),
    ("well_eup",               "읍면동"),
    ("well_ri",                "리"),
    ("elevation_m",            "표고(m)"),
    ("drill_depth_m",          "개발심도(m)"),
    ("natural_water_level_m",  "자연수위(m)"),
    ("stable_water_level_m",   "안정수위(m)"),
    ("capacity_m3d",           "양수량(㎥/일)"),
    ("permit_m3m",             "취수허가량(㎥/월)"),
    ("motor_hp",               "수중모터 펌프 마력(HP)"),
]

# session_state 키
_SS_FILTER_ACTIVE  = "ag_search_filter_active"
# Phase 4 — 지도 height 압축 모드 (Phase 4 라운드 A, 옵션 B):
#   "compact": 표 행 클릭 후에만 진입 (지도 1/2 축소).
#   "full"   : 마커 클릭·검색·초기화·기본 — 지도 풀 크기.
#   마커 클릭 시 height props 가 변경되지 않으면 streamlit-folium iframe 의
#   ResizeObserver 가 트리거되지 않아 click 이벤트 race 가 차단됨.
_SS_APPLIED_LOC    = "ag_search_applied_loc"
_SS_APPLIED_KW     = "ag_search_applied_kw"
_SS_LAST_KW        = "ag_search_last_kw_processed"

# 지도 zoom·center 보존 키
_SS_MAP_ZOOM       = "search_map_zoom"
_SS_MAP_CENTER     = "search_map_center"
_DEFAULT_MAP_ZOOM   = 11  # 사용자 요청 2026-05-09: 한 단계 더 축소 (tab7 화면과 동일 사이즈)
_DEFAULT_MAP_CENTER = (33.39, 126.55)  # 사용자 요청 2026-05-09: v6(33.45) 의 2배 만큼 내림

# 지도 높이 — 사용자 요청 2026-05-09 화면의 80% 수준
# (_MAP_H_COMPACT 토글은 Phase #1 에서 흰 깜박임 race 원인으로 제거됨)
_MAP_H_FULL    = 800


def _filter_df(df: pd.DataFrame,
               applied_loc: dict | None,
               applied_kw: str | None) -> pd.DataFrame:
    """현재 적용된 필터로 master DataFrame 을 좁힘."""
    out = ag_well_helpers.apply_cascading_filters(df, applied_loc or {})
    if applied_kw and applied_kw.strip():
        kw = applied_kw.lower().strip()
        out = out[
            out["well_id"].astype(str).str.lower().str.contains(kw, na=False)
        ]
    return out


def _bump_table_version() -> None:
    """결과 표 위젯을 「새 버전 키」로 강제 교체.

    Streamlit 은 selection 위젯의 session_state 에 외부 값 할당을 금지함
    (StreamlitValueAssignmentNotAllowedError). 따라서 표의 stale selection
    을 직접 비울 수 없음. 대신 dataframe 의 key 를 새로 만들어 위젯 자체를
    신선하게 다시 마운트 — selection 이 자연스럽게 비워짐.
    """
    cur = st.session_state.get("_df_key_v", 0)
    st.session_state["_df_key_v"] = cur + 1
    st.session_state["_last_applied_df_idx"] = -1


# ─────────────────────────────────────────────────────────────────────
#  ▼ 필터 영역 — render() 의 단일 fragment 안에서 호출됨.
# ─────────────────────────────────────────────────────────────────────
def _render_filter(df: pd.DataFrame) -> None:
    """검색 필터 UI — 이용량/수질 탭의 공용 헬퍼 패턴으로 통일.

    사용자 요청 (2026-05-16): tab5/6/7 의 검색 UI 일관성. 이용량 분석 탭의
    `render_well_selection_bar` (선택 관정 + 검색 input + 선택 해제) 가 표준.
    위치 필터(시/읍면동/리) 는 결과 표 좁히기용으로 expander 안 보존.

    2026-05-17 사용자 요청: 검색 input 은 지도 위 헤더 라인으로 이동.
    본 함수는 「선택 관정 + 선택 해제」만 노출 (include_search=False).
    """
    # ── 공용 헬퍼: 선택 관정 + 선택 해제 (검색 input 제외) ──────────────
    # 검색 input 은 render() 의 _render_search_map 위쪽 헤더 라인으로 이동.
    # 마커 클릭 시 search_selected_permit 갱신 + 검색 input 자동 클리어 동작은 유지.
    sel_permit = st.session_state.get("search_selected_permit")
    render_well_selection_bar(
        df, sel_permit,
        key_prefix="search",
        search_placeholder=_SEARCH_PLACEHOLDER,
        include_search=False,
    )

    # ── 위치 필터 + 초기화 (expander) ─────────────────────────────────────
    # tab5 의 핵심 기능 — 시/읍면동/리 cascading 으로 결과 표 좁히기.
    # 사용자 명시 요청대로 결과 표 320px 는 보존. 키워드 필터는 헬퍼가 대체.
    with st.expander("📍 위치 필터 (시 · 읍/면/동 · 리) + 초기화", expanded=False):
        loc_sel = ag_well_helpers.cascading_location_filters(
            df, key_prefix="loc", si_label="시 구분",
        )
        c1, c2 = st.columns([1, 1])
        with c1:
            do_apply = st.button(
                "✓ 필터 적용", type="primary",
                use_container_width=True, key="ag_filter_apply",
            )
        with c2:
            do_reset = st.button(
                "🔄 모두 초기화",
                use_container_width=True, key="ag_filter_reset",
            )

    if do_reset:
        for k in (
            "search_well_search", "_search_well_search_last",
            "search_selected_permit",
            "loc_si", "loc_eup", "loc_ri",
            _SS_FILTER_ACTIVE, _SS_APPLIED_LOC, _SS_APPLIED_KW, _SS_LAST_KW,
            _SS_MAP_ZOOM, _SS_MAP_CENTER,
            "_search_centered_permit",
            "_df_key_v", "_last_applied_df_idx",
        ):
            st.session_state.pop(k, None)
        ag_well_helpers.fragment_rerun()

    if do_apply:
        st.session_state[_SS_FILTER_ACTIVE] = True
        st.session_state[_SS_APPLIED_LOC]   = loc_sel
        # 키워드 필터는 폐기 — 헬퍼가 단일 매칭 자동 선택으로 대체.
        st.session_state[_SS_APPLIED_KW]    = ""
        st.session_state[_SS_LAST_KW]       = ""
        _bump_table_version()
        ag_well_helpers.fragment_rerun()


# ─────────────────────────────────────────────────────────────────────
#  ▼ 결과 영역 — render() 의 단일 fragment 안에서 호출됨.
#    dataframe on_select="rerun" 은 fragment 컨텍스트에서 자동으로
#    fragment-only rerun 을 트리거함 (Streamlit 1.36+).
# ─────────────────────────────────────────────────────────────────────
def _render_results(df: pd.DataFrame, n_total: int) -> None:
    # ── 적용된 필터로 결과 산출
    filter_active = st.session_state.get(_SS_FILTER_ACTIVE, False)
    if filter_active:
        applied_loc = st.session_state.get(_SS_APPLIED_LOC) or {}
        applied_kw  = st.session_state.get(_SS_APPLIED_KW, "") or ""
        filtered = _filter_df(df, applied_loc, applied_kw)
        bits = []
        for col, lbl in (("well_si", "시"), ("well_eup", "읍/면/동"),
                         ("well_ri", "리")):
            v = applied_loc.get(col)
            if v:
                bits.append(f"{lbl}: {v}")
        if applied_kw.strip():
            bits.append(f"관정명: {applied_kw}")
        st.caption(
            f"검색 결과 {len(filtered):,}공 / 전체 활성 {n_total:,}공"
            + (f"  —  {' · '.join(bits)}" if bits else "")
        )
    else:
        filtered = df.copy()
        st.caption(
            f"전체 활성 {n_total:,}공 표시 중 — 위에서 조건 선택 후 [검색] 또는 Enter."
        )

    # ── 표 컬럼 매핑
    src_cols = [c for c, _ in _RESULT_COLUMNS if c in filtered.columns]
    rename = {c: kor for c, kor in _RESULT_COLUMNS if c in filtered.columns}
    view = (
        filtered[src_cols].copy()
        .rename(columns=rename)
        .reset_index(drop=True)
    )

    cur_permit = st.session_state.get("search_selected_permit")

    df_v = st.session_state.get("_df_key_v", 0)
    df_key = f"search_list_v{df_v}"

    event = st.dataframe(
        view, use_container_width=True, hide_index=True, height=320,
        on_select="rerun", selection_mode="single-row",
        key=df_key,
    )

    sel_rows = (event.selection.rows
                if hasattr(event, "selection") and event.selection else [])
    df_idx = sel_rows[0] if sel_rows else -1

    last_applied = st.session_state.get("_last_applied_df_idx", -1)
    permit_changed_via_table = False
    if df_idx != last_applied:
        if 0 <= df_idx < len(filtered):
            new_permit = filtered.iloc[df_idx]["permit_no"]
            if new_permit != cur_permit:
                cur_permit = new_permit
                st.session_state["search_selected_permit"] = cur_permit
                permit_changed_via_table = True
        st.session_state["_last_applied_df_idx"] = df_idx

    # 표 행 클릭으로 selected_permit 가 바뀌었다면 fragment_rerun — 단일
    # fragment 안이라 지도 zoom-in (zoom 12) 가 자연 반영.
    # (height compact 토글은 Phase #1 에서 iframe race 원인으로 제거됨)
    if permit_changed_via_table:
        ag_well_helpers.fragment_rerun()

    # 관정 카드는 사용자 요청 2026-05-10 으로 지도 바로 아래로 이동.
    # 결과 표 영역에서는 더 이상 카드를 호출하지 않는다.


# ─────────────────────────────────────────────────────────────────────
#  ▼ 지도 영역 — render() 의 단일 fragment 안에서 호출됨.
# ─────────────────────────────────────────────────────────────────────
def _render_search_map(df: pd.DataFrame) -> None:
    sel_permit = st.session_state.get("search_selected_permit")

    # 관정 선택 시 그 관정 중심으로 zoom 12 (읍/면/동 사이즈) — fingerprint
    # 패턴으로 한 번만 발동. 사용자 줌 조작 후 같은 관정 재클릭은 강제 X.
    ag_well_helpers.maybe_recenter_to_selected_well(
        sel_permit, df,
        fingerprint_key="_search_centered_permit",
        center_key=_SS_MAP_CENTER,
        zoom_key=_SS_MAP_ZOOM,
    )

    saved_zoom = st.session_state.get(_SS_MAP_ZOOM, _DEFAULT_MAP_ZOOM)
    saved_center = st.session_state.get(_SS_MAP_CENTER, _DEFAULT_MAP_CENTER)

    # height 고정 — tab7/8 과 동일 정책. 토글이 iframe ResizeObserver →
    # Leaflet invalidateSize() → click 큐 비움 → 흰 깜박임/클릭 무반응의
    # 잔여 race 원인이었음.
    map_h = _MAP_H_FULL

    m = ag_well_helpers.build_search_map(
        df, selected_permit=sel_permit,
        zoom=saved_zoom, center=tuple(saved_center),
    )
    click = st_folium(
        m, width=None, height=map_h,
        # 사용자 요청 (2026-05-16 v15): zoom/center 제거 — 지도 이동/줌만으로
        # fragment_rerun 자동 트리거 → 흰색 깜빡임 발생을 차단. 마커 클릭만
        # fragment_rerun. 사용자 zoom 위치 복원 기능은 폐기 (UX trade-off).
        returned_objects=[
            "last_object_clicked_tooltip",
            "last_object_clicked_popup",
        ],
        key="search_map",
    )

    if click:
        # G3 fix 2026-05-30: quantization → ag_map_builders.persist_zoom_center (4곳→1곳 통합).
        persist_zoom_center(click, zoom_key=_SS_MAP_ZOOM, center_key=_SS_MAP_CENTER)

        # ── 마커 click → 관정 선택
        # tooltip 이 새 형식 '{well_id}|{permit_no}' → lookup 이 직접 permit 추출
        clicked_permit = ag_well_helpers.lookup_permit_by_well_id(
            click.get("last_object_clicked_tooltip"), df
        )
        # 폴백: popup HTML 정규식 (tooltip 이 빈 케이스)
        if not clicked_permit:
            clicked_permit = ag_well_helpers.parse_clicked_popup(
                click.get("last_object_clicked_popup")
            )
        if clicked_permit and clicked_permit != sel_permit:
            st.session_state["search_selected_permit"] = clicked_permit
            # 사용자 요청 (2026-05-16): 마커 클릭 시 검색 input 자동 클리어.
            # 공용 헬퍼의 widget key (search_well_search) + 재처리 가드
            # (_search_well_search_last) + 옛 key (search_keyword) + applied
            # state 모두 pop. 다음 rerun 에서 검색 input 이 빈 값으로 재렌더.
            # 시/읍면동/리 location filter 는 사용자가 명시 좁힌 의도라 보존.
            for _stale_k in (
                "search_well_search", "_search_well_search_last",
                "search_keyword",
                _SS_APPLIED_KW, _SS_LAST_KW,
            ):
                st.session_state.pop(_stale_k, None)
            # _bump_table_version() 대신 _last_applied_df_idx 만 -1 로 리셋:
            # - 위젯 재마운트(_df_key_v++)는 흰 깜박임을 유발하므로 회피
            # - last_applied=-1 이면 같은 행 재클릭도 분기 진입 → 회귀 차단
            # - render() 전체가 단일 fragment 라 fragment_rerun 만으로 결과 표·
            #   카드·헤더 모두 자연 갱신됨 (옵션 B + 옵션 C).
            st.session_state["_last_applied_df_idx"] = -1
            ag_well_helpers.fragment_rerun()


# ─────────────────────────────────────────────────────────────────────
#  메인 render — 전체를 단일 @st.fragment 로 감쌈 (옵션 B, tab7/tab8 동일).
#  - 마커 클릭·표 행 클릭·필터 변경·키워드 단일 매칭 모두 fragment-only
#    rerun 으로 처리되어 탭 컨테이너·iframe 재마운트·sessionStorage JS
#    재주입이 발생하지 않음 → 흰 깜박임·탭 점프 원천 차단.
# ─────────────────────────────────────────────────────────────────────
@st.fragment
def render() -> None:
    # 사용자 요청 2026-05-09 — v6(33.45) 너무 위 → 2배 만큼 내림 (33.39).
    # zoom 11 유지. v7 마이그레이션.
    _MIGRATION_KEY = "_tab6_zoom_migrated_v7"
    if not st.session_state.get(_MIGRATION_KEY):
        st.session_state.pop(_SS_MAP_ZOOM, None)
        st.session_state.pop(_SS_MAP_CENTER, None)
        st.session_state[_MIGRATION_KEY] = True

    # 결과 표 selection 하이라이트 약화 CSS 는 Phase 3 P2 에서 theme.py 의
    # GLOBAL_CSS 로 이전됨 (apply_theme() 으로 1회 주입, fragment_rerun 마다
    # 중복 누적 차단).
    _t, _q = st.columns([10, 1])
    with _t:
        st.markdown(
            '<p class="tab-title" style="margin:0;">11.관정 관리</p>',
            unsafe_allow_html=True,
        )
    with _q:
        quit_button("quit_in_tab6")

    df = ag_well_loader.load_master(active_only=True)
    if df.empty:
        st.warning("관정 마스터 자료를 찾을 수 없습니다 (master.csv).")
        return

    n_total = len(df)
    sel_permit = st.session_state.get("search_selected_permit")

    # 선택된 관정의 well_id (헤더 표시용)
    sel_well_id = ""
    if sel_permit:
        info = ag_well_loader.get_well_info(sel_permit)
        if info:
            wid = (info.get("well_id") or "").strip()
            sel_well_id = wid or sel_permit

    # ── ① 농업용 관정 현황 표 — 제목 삭제 (사용자 요청), 표만 노출
    ag_well_helpers.render_well_count_table(df)

    # ── ② 지도 헤더 라인 — [관정 검색 / 선택] + [검색 input] 한 줄
    # 2026-05-17 사용자 요청: 검색창을 지도 위로 이동, tab7/9 와 동일 패턴.
    # 헤더는 subsection-title 스타일(tab7 의 "관정 위치 · 이용량 분포" 와 동일).
    if sel_well_id:
        header_text = f"관정 검색 / 선택 : {sel_well_id}"
    else:
        header_text = "관정 검색 / 선택"
    header_html = (
        f'<p class="subsection-title" style="margin:6px 0;">{header_text}</p>'
    )
    render_map_header_with_search(
        df, key_prefix="search",
        search_placeholder=_SEARCH_PLACEHOLDER,
        title_html=header_html,
    )

    # ── ③ 지도 (단일 fragment 안)
    _render_search_map(df)

    # ── ④ 관정 카드 (지도 바로 아래) — 사용자 요청 2026-05-10.
    #   기존엔 결과 표 아래에 있어 검색·필터·표를 모두 지나야 보였음. 검색
    #   해도 지도에 마커가 그대로 보이고 카드가 지도 바로 밑에 표시되도록 이동.
    # 2026-05-17: 미선택 안내 캡션은 사용자 요청으로 삭제 (헤더의 "관정 검색 /
    # 선택" 라벨 + 검색창 placeholder 가 이미 가이드 역할).
    cur_permit = st.session_state.get("search_selected_permit")
    if cur_permit:
        ag_well_helpers.render_well_card(cur_permit, last_n_years=5)
        # ── 관정카드 PDF 박스 — 사용자 요청 2026-05-12.
        # 차트(연 이용량·월별 이용량·수질) 바로 아래 풀폭 한 줄에 chip 들을
        # 가로 나열. <a target="_blank"> 링크라 클릭 시 streamlit rerun 0회.
        # well_id 는 cur_permit 기준 재계산 — render() 진입 시점의 sel_well_id
        # 와 cur_permit 이 다른 fragment 내 transition(예: _render_search_map
        # 에서 selected_permit 갱신 직후) 에서 stale 박스 표시를 차단.
        cur_info = ag_well_loader.get_well_info(cur_permit)
        cur_well_id = str((cur_info or {}).get("well_id") or "").strip()
        ag_well_helpers.render_well_card_pdf_box(cur_well_id)

    # ── ⑤ 선택 관정 + 선택 해제 (검색 input 은 위 헤더로 이동) + 위치 필터
    # 2026-05-17: 검색 input 이 위로 이동했으므로 별도 섹션 헤더와 hr 삭제.
    # render_well_selection_bar 의 자체 border-top 이 시각 분리 역할.
    _render_filter(df)

    # ── ⑥ 결과 표 + 카드
    _render_results(df, n_total)
