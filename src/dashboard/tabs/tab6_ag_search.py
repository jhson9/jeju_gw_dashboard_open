# ==============================================================================
#  파일명: src/dashboard/tabs/tab6_ag_search.py  —  Build 3.1
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


# 결과 표 12 개 컬럼
_RESULT_COLUMNS: list[tuple[str, str]] = [
    ("permit_no",              "허가번호"),
    ("well_id",                "관정명"),
    ("well_si",                "시"),
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
_SS_HEIGHT_MODE = "ag_search_height_mode"
_SS_APPLIED_LOC    = "ag_search_applied_loc"
_SS_APPLIED_KW     = "ag_search_applied_kw"
_SS_LAST_KW        = "ag_search_last_kw_processed"

# 지도 zoom·center 보존 키
_SS_MAP_ZOOM       = "search_map_zoom"
_SS_MAP_CENTER     = "search_map_center"
_DEFAULT_MAP_ZOOM   = 11
_DEFAULT_MAP_CENTER = (33.38, 126.55)

# 지도 높이 — 관정 선택 시 1/2 축소
_MAP_H_FULL    = 780
_MAP_H_COMPACT = 430


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
    keyword = st.text_input(
        "관정명 검색", value="", key="search_keyword",
        placeholder="관정명 입력 후 Enter (예: 90감산, F-285)",
        label_visibility="collapsed",
    )

    # 상세 필터 — expander 제거, 3개 selectbox 를 그대로 노출
    # tab7/tab8 와 라벨 통일 (si_label="시 구분")
    loc_sel = ag_well_helpers.cascading_location_filters(
        df, key_prefix="loc", si_label="시 구분",
    )

    btn_search, btn_reset, _ = st.columns([1, 1, 4])
    with btn_search:
        do_search = st.button(
            "🔍 검색", type="primary",
            use_container_width=True, key="ag_search_btn",
        )
    with btn_reset:
        do_reset = st.button(
            "초기화", use_container_width=True, key="ag_reset_btn",
        )

    last_kw = st.session_state.get(_SS_LAST_KW, "")
    kw_entered = (keyword != last_kw)

    if do_reset:
        for k in (
            "search_keyword", "selected_permit",
            "loc_si", "loc_eup", "loc_ri",
            _SS_FILTER_ACTIVE, _SS_APPLIED_LOC, _SS_APPLIED_KW, _SS_LAST_KW,
            _SS_MAP_ZOOM, _SS_MAP_CENTER,
            "_search_centered_permit",
            "_df_key_v", "_last_applied_df_idx",
            _SS_HEIGHT_MODE,
        ):
            st.session_state.pop(k, None)
        # fragment 안에서 호출 — fragment_rerun 이 컨텍스트 가드로 안전 처리
        ag_well_helpers.fragment_rerun()

    if do_search or kw_entered:
        st.session_state[_SS_FILTER_ACTIVE] = True
        st.session_state[_SS_APPLIED_LOC]   = loc_sel
        st.session_state[_SS_APPLIED_KW]    = keyword
        st.session_state[_SS_LAST_KW]       = keyword
        # 필터 변경으로 표의 행 인덱스가 바뀜 → 새 위젯 키로 교체
        _bump_table_version()

        # 단일 매칭이면 자동 선택. render() 전체가 단일 fragment 라
        # fragment_rerun 만으로 지도·결과·헤더 모두 갱신됨 (옵션 B).
        filtered = _filter_df(df, loc_sel, keyword)
        single_match = (len(filtered) == 1)
        if single_match:
            st.session_state["selected_permit"] = filtered.iloc[0]["permit_no"]
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

    cur_permit = st.session_state.get("selected_permit")

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
                st.session_state["selected_permit"] = cur_permit
                permit_changed_via_table = True
        st.session_state["_last_applied_df_idx"] = df_idx

    # 표 행 클릭으로 selected_permit 가 바뀌었다면 fragment_rerun — 단일
    # fragment 안이라 지도 zoom-in (zoom 12) 과 height 1/2 모두 자연 반영.
    # Phase 4 옵션 B: 표 행 클릭은 "사용자가 검색 결과를 보고 결정한 후" 의 의도가
    # 명확하므로 이때만 compact 모드로 진입 (지도 축소). 마커 클릭 경로는
    # height 변경 없이 즉시 반영되어 iframe race 가 차단됨.
    if permit_changed_via_table:
        st.session_state[_SS_HEIGHT_MODE] = "compact"
        ag_well_helpers.fragment_rerun()

    if cur_permit:
        ag_well_helpers.render_well_card(cur_permit, last_n_years=5)
    else:
        st.caption(
            "지도의 마커를 클릭하거나, 결과 표의 행을 선택하거나, "
            "관정명을 검색하면 현황 카드가 여기에 표시됩니다."
        )


# ─────────────────────────────────────────────────────────────────────
#  ▼ 지도 영역 — render() 의 단일 fragment 안에서 호출됨.
# ─────────────────────────────────────────────────────────────────────
def _render_search_map(df: pd.DataFrame) -> None:
    sel_permit = st.session_state.get("selected_permit")

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

    # Phase 4 옵션 B — height 토글이 마커 클릭 race 의 직접 원인:
    #   height props 변경 → iframe ResizeObserver → Leaflet invalidateSize() →
    #   click 이벤트 큐 비움 → 다음 클릭 무반응 (random failure).
    # 해결: 표 행 클릭 시에만 _SS_HEIGHT_MODE="compact" 로 전환. 마커 클릭은
    # height 유지 → race 차단. 사용자가 명시적으로 "결정 후 축소" 의도일
    # 때만 컴팩트 모드 → UX 자연스러움.
    height_mode = st.session_state.get(_SS_HEIGHT_MODE, "full")
    map_h = _MAP_H_COMPACT if (sel_permit and height_mode == "compact") else _MAP_H_FULL

    m = ag_well_helpers.build_search_map(
        df, selected_permit=sel_permit,
        zoom=saved_zoom, center=tuple(saved_center),
    )
    click = st_folium(
        m, width=None, height=map_h,
        returned_objects=[
            "last_object_clicked_tooltip",
            "last_object_clicked_popup",
            "zoom",
            "center",
        ],
        key="search_map",
    )

    if click:
        # ── 줌·중심 보존 (Phase 4 — 부동소수점 quantization)
        # zoom 은 정수, center 는 소수점 4자리(약 11m 분해능)로 round 하여
        # 미세 변동(예: 33.38231… vs 33.38231042) 으로 인한 props identity 변경
        # → React 가 props 변경으로 판정 → iframe 재렌더 → click race 트리거
        # 를 차단. 사용자 줌·중심 보존은 11m 정밀도면 충분.
        z = click.get("zoom")
        c = click.get("center")
        if z is not None:
            try:
                st.session_state[_SS_MAP_ZOOM] = int(round(float(z)))
            except (TypeError, ValueError):
                pass
        if isinstance(c, dict) and "lat" in c and "lng" in c:
            try:
                st.session_state[_SS_MAP_CENTER] = (
                    round(float(c["lat"]), 4), round(float(c["lng"]), 4)
                )
            except (TypeError, ValueError):
                pass

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
            st.session_state["selected_permit"] = clicked_permit
            # 마커 클릭 시 "검색 키워드"만 비움 (사용자 호소 #1, 옵션 B):
            # - search_keyword 위젯 + _SS_APPLIED_KW + _SS_LAST_KW 만 pop
            # - 시/읍면동/리 location filter 는 사용자가 명시 좁힌 의도라 보존
            # - _SS_FILTER_ACTIVE 도 location 만으로 필터 유지하도록 보존
            for _stale_k in (
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
    # 결과 표 selection 하이라이트 약화 CSS 는 Phase 3 P2 에서 theme.py 의
    # GLOBAL_CSS 로 이전됨 (apply_theme() 으로 1회 주입, fragment_rerun 마다
    # 중복 누적 차단).
    st.markdown(
        '<h2 style="font-size:22px;font-weight:500;margin:0 0 6px;padding:0;'
        'color:#1a1a18;line-height:1.2;">'
        '⑤ 관정 검색 — 농업용 공공관정</h2>',
        unsafe_allow_html=True,
    )

    df = ag_well_loader.load_master(active_only=True)
    if df.empty:
        st.warning("관정 마스터 자료를 찾을 수 없습니다 (master.csv).")
        return

    n_total = len(df)
    sel_permit = st.session_state.get("selected_permit")

    # 선택된 관정의 well_id (헤더 표시용)
    sel_well_id = ""
    if sel_permit:
        info = ag_well_loader.get_well_info(sel_permit)
        if info:
            wid = (info.get("well_id") or "").strip()
            sel_well_id = wid or sel_permit

    # ── ① 농업용 관정 현황 표 — 제목 삭제 (사용자 요청), 표만 노출
    ag_well_helpers.render_well_count_table(df)

    # ── ② 지도 (단일 fragment 안)
    _render_search_map(df)

    # ── ③ 검색·필터
    st.markdown(
        '<hr style="margin:14px 0 10px;border:none;'
        'border-top:0.5px solid rgba(26,26,24,0.15);">',
        unsafe_allow_html=True,
    )
    # 헤더 — 관정 선택 시 well_id 표기
    if sel_well_id:
        header_text = f"관정 검색 / 선택 : {sel_well_id}"
    else:
        header_text = "관정 검색 / 선택"
    st.markdown(
        f'<div style="font-size:15px;font-weight:600;color:#185fa5;'
        f'margin-bottom:6px;">{header_text}</div>',
        unsafe_allow_html=True,
    )
    _render_filter(df)

    # ── ④ 결과 표 + 카드
    _render_results(df, n_total)
