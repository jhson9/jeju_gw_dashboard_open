# ==============================================================================
#  파일명: src/dashboard/tabs/tab05_map.py
#  탭: ④ 공간 분석 (관측정/AWS) — Build 1.2.02
# ------------------------------------------------------------------------------
#  v1.2.02 변경:
#   - 레이아웃: 지도 1줄 전체 폭 + 그 아래 상세(전체 폭) (요청 1·2)
#   - 모드 라디오 크기 확대 (요청 5)
#   - 기간 라벨: 첫 칸/연도 변경 행만 'YY년 M월', 그 외 'M월' (요청 8·12)
#   - 그래프 범례: '과거 평균' → '과거 N년 해당월 평균' (요청 12)
#   - 각주: 동적 baseline 연도 그룹 표시 (요청 9·13)
#   - 관측정 baseline = 직전 3년 (요청 7·10)
# ==============================================================================

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

import config
from src.collectors import gwlevel_day_parser
from src.dashboard import map_helpers, ag_well_helpers
from src.dashboard.tabs._tab05_helpers import (
    _diff_html,
    _smart_period_labels,
    _baseline_footnote,
)
from src.dashboard.tabs._tab05_aws import _render_aws_detail
from src.dashboard.tabs._tab05_station import _render_station_detail


# ==============================================================================
#  ■ 캐시
# ==============================================================================
@st.cache_data(ttl=600)
def _load_meta_cached() -> pd.DataFrame:
    return map_helpers.load_station_meta()


@st.cache_data(ttl=600)
def _list_day_stations_cached() -> list[str]:
    return gwlevel_day_parser.list_day_stations()


# ==============================================================================
#  ■ 색상/포맷 헬퍼 — _tab05_helpers.py 로 분리 (2026-05-09).
#  _diff_html, _smart_period_labels, _baseline_footnote 는 위 import 에서 가져옴.
# ==============================================================================


# ==============================================================================
#  ■ 메인 렌더 — render() 전체를 단일 @st.fragment 로 (Phase 3 P1).
#    tab6/7/8 와 동일 패턴. 마커 클릭·selectbox·radio 변경 시 fragment-only
#    rerun 으로 처리되어 흰 깜박임·탭 점프 차단.
#    ※ st_folium 의 동적 key (`tab05_map_{mode}`) 는 mode 변경 시 iframe 을
#      재마운트하지만 fragment 안에서도 동일 동작 — 위험 없음.
# ==============================================================================
@st.fragment
def render(asos_df: pd.DataFrame, periods: dict, base_date: date):
    # 사용자 요청 2026-05-09 — v6(33.45)에서 너무 위 → 직전 +0.03 의 2배만큼 내림.
    # lat 33.45 → 33.39 (실질 33.42 기준 -0.03, 약 3km 남쪽). v7 마이그레이션.
    _MIGRATION_KEY = "_tab5_zoom_migrated_v7"
    if not st.session_state.get(_MIGRATION_KEY):
        st.session_state.pop("tab05_map_zoom", None)
        st.session_state.pop("tab05_map_center", None)
        st.session_state[_MIGRATION_KEY] = True

    meta = _load_meta_cached()
    day_stations = _list_day_stations_cached()

    if meta.empty:
        st.warning("⚠️ 관측망 정보 파일을 찾을 수 없습니다. data/0_JD관측망_정보.xlsx 확인.")
        return

    # 일자료 CSV 가 있는 관측정만 드롭다운 후보
    avail_stations = [s for s in meta["관측소명"].tolist() if s in day_stations]
    if not avail_stations:
        st.warning("⚠️ data/GWlevel/by_station_day/ 에 일자료 CSV 가 없습니다. "
                   "process_gwlevel_day.py 또는 ⚙️ 데이터 탭에서 파싱을 실행하세요.")
        return

    # ── 세션 상태 (위젯 key 와 동일하게 사용해 양방향 동기화 보장) ──
    aws_names_all = [s["name"] for s in config.STATIONS_ASOS]
    if "tab5_mode" not in st.session_state:
        st.session_state["tab5_mode"] = "관측정"
    if "tab5_station_sel" not in st.session_state:
        st.session_state["tab5_station_sel"] = avail_stations[0]
    if "tab5_aws_sel" not in st.session_state:
        st.session_state["tab5_aws_sel"] = aws_names_all[0]
    # 선택된 관측정이 avail 목록에 없으면(새 데이터 추가 등) 첫 항목으로 보정
    if st.session_state["tab5_station_sel"] not in avail_stations:
        st.session_state["tab5_station_sel"] = avail_stations[0]

    # ── v1.2.06: 직전 실행의 지도 클릭으로 보류된 선택 적용 (위젯 인스턴스화 전!) ──
    # Streamlit 제약: 위젯 key 와 동일한 session_state 는 위젯 렌더 후엔 수정 불가.
    # 따라서 클릭 핸들러는 'tab5_pending' 에만 적어두고 rerun → 다음 실행 최상단에서 적용.
    _pending = st.session_state.pop("tab5_pending", None)
    if _pending:
        p_mode = _pending.get("mode")
        p_val = _pending.get("value")
        if p_mode == "관측정" and p_val in avail_stations:
            st.session_state["tab5_mode"] = "관측정"
            st.session_state["tab5_station_sel"] = p_val
        elif p_mode == "AWS" and p_val in aws_names_all:
            st.session_state["tab5_mode"] = "AWS"
            st.session_state["tab5_aws_sel"] = p_val

    # ── 상단 컨트롤: 모드(폭 2배) + 드롭다운(폭 1/2) + V-World 상태 ──
    # v1.2.03: 라디오 가로 padding 50px → 버튼 폭 ~2배 (요청 3)
    st.markdown("""
    <style>
    div[data-testid="stRadio"][aria-label="모드_t5"] > div[role="radiogroup"] {
        gap: 8px !important;
    }
    div[data-testid="stRadio"][aria-label="모드_t5"] label {
        font-size: 17px !important;
        padding: 8px 50px !important;
        border: 1px solid rgba(26,26,24,0.18) !important;
        border-radius: 6px !important;
        background: var(--color-bg-primary) !important;
        cursor: pointer;
        margin-right: 0 !important;
    }
    div[data-testid="stRadio"][aria-label="모드_t5"] label:has(input:checked) {
        background: var(--color-text-info) !important;
        color: var(--color-bg-primary) !important;
        border-color: var(--color-text-info) !important;
    }
    div[data-testid="stRadio"][aria-label="모드_t5"] label:has(input:checked) p {
        color: var(--color-bg-primary) !important;
    }
    </style>
    """, unsafe_allow_html=True)

    # 컬럼 분할: [라디오 1.4] [좌pad 0.5] [드롭다운 1.0] [우pad 1.5] [VW상태 1.0]
    # → 드롭다운 너비가 c2 컬럼의 1/2 정도가 되도록 좌·우 padding 컬럼으로 좁힘 (요청 4)
    c1, cp1, c2, cp2, c3 = st.columns([1.4, 0.4, 1.2, 1.4, 1.0])
    with c1:
        mode = st.radio(
            "모드_t5", ["관측정", "AWS"],
            horizontal=True,
            key="tab5_mode",
            label_visibility="collapsed",
        )
    with c2:
        if mode == "관측정":
            st.selectbox(
                "관측정 선택", avail_stations,
                key="tab5_station_sel",
                label_visibility="collapsed",
            )
        else:
            st.selectbox(
                "AWS 선택", aws_names_all,
                key="tab5_aws_sel",
                label_visibility="collapsed",
            )
    with c3:
        st.markdown(
            '<div style="font-size:15px;color:var(--color-text-secondary);padding:10px 0;text-align:right;">'
            f'V-World API: <b>{"활성" if config.VWORLD_API_KEY else "비활성 (OSM 폴백)"}</b>'
            "</div>",
            unsafe_allow_html=True,
        )

    # ── 지도: 화면 전체 폭, 높이 1.5배 (요청 5: 520 → 780) ──
    cur_station = (st.session_state["tab5_station_sel"]
                   if mode == "관측정" else None)
    cur_aws = st.session_state["tab5_aws_sel"] if mode == "AWS" else None

    # 줌/중심 보존 — 사용자가 마커 클릭하려고 줌인한 후 fragment_rerun 이
    # 일어나도 같은 줌/중심 유지되어야 마커 선택 작업이 끊기지 않음.
    # quantization (zoom→int, lat/lng→round 4) 으로 React props identity 가
    # 안정되어 streamlit-folium iframe 재렌더 차단.
    _saved_center = st.session_state.get("tab05_map_center", (33.39, 126.55))
    _saved_zoom = st.session_state.get("tab05_map_zoom", 11)

    m = map_helpers.make_map(center=_saved_center, zoom=_saved_zoom)
    map_helpers.add_station_markers(m, meta, selected=cur_station)
    map_helpers.add_aws_markers(m, selected=cur_aws)
    # key 고정 — mode 변경(관측정/AWS) 마다 key 가 바뀌면 iframe 강제 재마운트
    # → 타일 재요청 동안 흰 화면. 모드 전환은 marker rebuild 만으로 충분.
    st_data = st_folium(
        m, width=None, height=800,
        # 사용자 요청 (2026-05-16 v15): zoom/center 제거 — 흰색 깜빡임 차단.
        returned_objects=["last_object_clicked_tooltip"],
        key="tab05_map",
    )

    # 사용자가 줌/이동한 결과를 session_state 에 보존 (quantization)
    if st_data:
        _z = st_data.get("zoom")
        _c = st_data.get("center")
        if _z is not None:
            try:
                st.session_state["tab05_map_zoom"] = round(float(_z) * 2) / 2
            except (TypeError, ValueError):
                pass
        if isinstance(_c, dict) and "lat" in _c and "lng" in _c:
            try:
                st.session_state["tab05_map_center"] = (
                    round(float(_c["lat"]), 4),
                    round(float(_c["lng"]), 4),
                )
            except (TypeError, ValueError):
                pass

    # 마커 클릭 → 드롭다운/모드 동기화 (양방향 연동)
    # v1.2.06: 위젯 인스턴스화 후이므로 직접 수정 불가. 'tab5_pending' 에만 적고 rerun.
    clicked_tip = (st_data or {}).get("last_object_clicked_tooltip")
    if clicked_tip:
        tip = str(clicked_tip).replace("★ ", "").replace(" (선택됨)", "").strip()
        if tip.endswith(" AWS"):
            aws_nm = tip[:-4].strip()
            if aws_nm in aws_names_all:
                if (st.session_state.get("tab5_mode") != "AWS"
                        or st.session_state.get("tab5_aws_sel") != aws_nm):
                    st.session_state["tab5_pending"] = {
                        "mode": "AWS", "value": aws_nm
                    }
                    ag_well_helpers.fragment_rerun()
        elif tip in avail_stations:
            if (st.session_state.get("tab5_mode") != "관측정"
                    or st.session_state.get("tab5_station_sel") != tip):
                st.session_state["tab5_pending"] = {
                    "mode": "관측정", "value": tip
                }
                ag_well_helpers.fragment_rerun()

    st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)

    # ── 상세: 화면 전체 폭, 지도 아래 (요청 2) ──
    if mode == "관측정":
        _render_station_detail(st.session_state["tab5_station_sel"], meta,
                                asos_df, base_date, periods)
    else:
        _render_aws_detail(st.session_state["tab5_aws_sel"], asos_df, base_date)


# ==============================================================================
#  ■ 디테일 렌더 — _tab05_station.py / _tab05_aws.py 로 분리 (2026-05-09).
#  ■ 12개월 차트/표 + 월별 통계 — _tab05_charts.py 로 분리.
# ==============================================================================
