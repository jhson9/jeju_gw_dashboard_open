# ==============================================================================
#  파일명: src/dashboard/tabs/tab13_ag_quality.py  —  Build 2.5
#  탭: ⑦ 수질 분석 (반기 5항목)
# ------------------------------------------------------------------------------
#  설계 (이용량 분석 탭과 일관된 구조):
#   - 1줄: 수질 항목(드롭다운) · 집계 단위 · 분석 기간(반기 슬라이더 — int 기반)
#   - 2줄: 시 구분 → 읍/면/동 → 리 (cascading)
#   - KPI 카드 5개 · 지도(6단계 색상 + 6단계 크기) · 관정 클릭 시 상세
#  Build 2.5 변경:
#   - 슬라이더: select_slider(tuple options) → st.slider(int) — BaseWeb 슬라이더의
#     null current 에러를 원천 차단.
#   - 관정 선택바에 검색 입력 추가 (이용량 탭과 동일 UX).
#   - 관정 상세: 선택 항목 단일 막대(라벨·시기 표시·Y=기준×1.5) + 강수량(½ 높이,
#     Y=200) + 5항목 표 (시기 포함 6컬럼).
#   - 지도 마커 크기: 색상과 동일 6단계 (1/3, 2/3, 1, 4/3, 5/3, 2).
# ==============================================================================

from __future__ import annotations

import json

import folium
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as _components
from plotly.subplots import make_subplots
from streamlit_folium import st_folium

import config
from src.analysis import ag_well_loader
from src.collectors import asos_collector
from src.dashboard import ag_well_helpers, theme
from src.dashboard.map_helpers import make_map
from src.dashboard.quit_helper import quit_button


# 공용 fragment-only rerun 헬퍼 (컨텍스트 가드 포함). ag_well_helpers 참조.
_fragment_rerun = ag_well_helpers.fragment_rerun


# ==============================================================================
#  ■ 헬퍼 + 상수 + 캐시 — _tab13_helpers.py 로 분리 (2026-05-09).
# ==============================================================================
from src.dashboard.tabs._tab13_helpers import (   # noqa: E402
    QUALITY_ITEM_ORDER,
    _ITEM_DECIMALS,
    _QUALITY_PALETTE,
    _NO_DATA_COLOR,
    _SIZE_MULTIPLIERS,
    _BASE_RADIUS,
    _AGG_LABELS,
    _LEVEL_TO_LOC_COL,
    _cached_asos_data,
    _fmt_item,
    _hex_to_rgba,
    _clean_no_data_rows,
    _yh_idx,
    _yh_idx_series,
    _yh_label,
    _yh_to_date,
    _build_filtered_qf_cached,
    _fmt_val,
    _color_score,
    _bin_index,
    _color_from_score,
    _radius_from_score,
    _std_label,
)
from src.dashboard.tabs._tab13_widgets import _half_year_slider   # noqa: E402
from src.dashboard.tabs._tab13_map import (   # noqa: E402
    _maybe_recenter_map,
    _location_label,
    _yh_period_label,
    _render_kpi_cards,
    _render_map,
    _build_color_legend,
)
from src.dashboard.tabs._tab13_well_detail import (   # noqa: E402
    _render_well_selection_bar,
    _render_well_search_input,
    _select_aws_for_well,
    _render_well_detail,
    _bar_color,
    _render_quality_bar,
    _render_rainfall_bar,
    _render_quality_table,
    _BAR_COLOR_HALF,
    _BAR_COLOR_EXCEED_HALF,
    _BAR_COLOR_EXCEED,
    _RAIN_COLOR_HALF,
)
from src.dashboard.tabs._tab13_group import (   # noqa: E402
    _region_label_short,
    _render_group_section,
    _render_group_box_latest,
    _render_half_box,
    _render_group_timeseries_table,
)


# ==============================================================================
#  반기 슬라이더 — _tab13_widgets.py 로 분리 (위 import 참조)
# ==============================================================================

# ==============================================================================
#  ■ 위치 헬퍼 (_maybe_recenter_map / _location_label / _yh_period_label)
#    → _tab13_map.py 로 분리 (위 import 참조).
# ==============================================================================


# ==============================================================================
#  메인 render
# ==============================================================================
@st.fragment
def render() -> None:
    # (2026-06-11 v2) 탭 제목 제거 — 하위탭 pill 문구와 중복 (사용자 요청)

    df_master = ag_well_loader.load_master(active_only=False)
    df_qual   = ag_well_loader.load_quality_semiannual()

    if df_qual.empty:
        st.warning(
            "수질 자료를 찾을 수 없습니다 (water_quality_semiannual.csv)."
        )
        return

    available_items = [
        k for k in QUALITY_ITEM_ORDER
        if k in config.WATER_QUALITY_STANDARDS and k in df_qual.columns
    ]
    if not available_items:
        st.warning("수질 자료에 표시 가능한 항목이 없습니다.")
        return

    # 첫 진입 default — 이용량 탭과 동일 (시 / 서귀포시).
    if "qty_level" not in st.session_state:
        st.session_state["qty_level"] = "시"
    if "qty_loc_si" not in st.session_state:
        st.session_state["qty_loc_si"] = "전체"
    cur_item = st.session_state.get("qty_item")
    if cur_item not in available_items:
        st.session_state["qty_item"] = (
            "nitrate_n" if "nitrate_n" in available_items else available_items[0]
        )

    # ── 컨트롤 두 줄(수질항목/집계단위/연도 → 시구분/읍면동/리) 사이 공백 ~8~10mm 안전 압축.
    #     두 row 사이 공백 ~100px 의 구성:
    #       (a) row 1 slider 자체 padding-bottom (≈28px)
    #       (b) Streamlit vertical block flex gap (≈16px)
    #       (c) row 2 selectbox stWidgetLabel padding-top (≈8px)
    #     세 요소를 동시 압축. -2.0rem(-32px) 은 row 1 의 시각 끝(tick label "2014")
    #     과 row 2 라벨("시 구분") 사이 안전 거리 ≈ 12mm 를 보장하는 한계점.
    #     -2.5rem 이상부터 라벨 겹침 위험.
    st.markdown("""
    <style>
    /* (1) marker stMarkdown / stElementContainer 자체 0 압축 + slider padding 흡수 */
    [data-testid="stMarkdown"]:has(.row-pair-tight),
    [data-testid="stElementContainer"]:has(.row-pair-tight) {
        height: 0 !important;
        min-height: 0 !important;
        max-height: 0 !important;
        margin: -0.8rem 0 0 0 !important;
        padding: 0 !important;
        line-height: 0 !important;
        overflow: hidden !important;
    }
    /* (2) marker 다음 element 의 margin-top 음수 — flex gap 상쇄 + 추가 압축
         marker 가 두 위치(컨트롤 row 사이 / 정보박스 위)에 같은 클래스로 재사용되므로
         다음 element 가 stHorizontalBlock(컨트롤 row) 또는 stMarkdown(정보박스) 모두 매치 */
    [data-testid="stMarkdown"]:has(.row-pair-tight) + [data-testid="stHorizontalBlock"],
    [data-testid="stMarkdown"]:has(.row-pair-tight) + [data-testid="stMarkdown"],
    [data-testid="stElementContainer"]:has(.row-pair-tight) + [data-testid="stHorizontalBlock"],
    [data-testid="stElementContainer"]:has(.row-pair-tight) + [data-testid="stElementContainer"],
    [data-testid="stElementContainer"]:has(.row-pair-tight) + [data-testid="stMarkdown"] {
        margin-top: -0.5rem !important;
    }
    /* (3) row 2 의 selectbox 라벨 위 패딩 0 — (c) 요소 제거 */
    [data-testid="stMarkdown"]:has(.row-pair-tight) + [data-testid="stHorizontalBlock"] [data-testid="stWidgetLabel"],
    [data-testid="stElementContainer"]:has(.row-pair-tight) + [data-testid="stHorizontalBlock"] [data-testid="stWidgetLabel"],
    [data-testid="stElementContainer"]:has(.row-pair-tight) + [data-testid="stElementContainer"] [data-testid="stWidgetLabel"],
    [data-testid="stMarkdown"]:has(.row-pair-tight) ~ [data-testid="stHorizontalBlock"]:first-of-type [data-testid="stWidgetLabel"] {
        margin-top: 0 !important;
        padding-top: 0 !important;
    }
    </style>
    """, unsafe_allow_html=True)

    # ── 컨트롤 1줄
    c1, c2, c3 = st.columns([1.4, 1.2, 4.0])
    with c1:
        item = st.selectbox(
            "수질 항목",
            options=available_items,
            format_func=lambda k: (
                f"{config.WATER_QUALITY_STANDARDS[k]['kor']} ({k})"
            ),
            key="qty_item",
        )
    with c2:
        level = st.selectbox(
            "집계 단위", _AGG_LABELS, key="qty_level",
        )
    with c3:
        yr_min = (
            int(df_qual["year"].dropna().min())
            if df_qual["year"].notna().any() else 2015
        )
        yr_max = (
            int(df_qual["year"].dropna().max())
            if df_qual["year"].notna().any() else 2025
        )
        if yr_min > yr_max:
            yr_min = yr_max
        # ⚠ key 변경 — 이전 select_slider 의 stale 위젯 상태와 충돌 회피.
        yh_lo, yh_hi = _half_year_slider(yr_min, yr_max, key="qty_yh_range_int")

    # ── 컨트롤 2줄: 시 → 읍면동 → 리
    #     marker — 위 CSS 가 다음 horizontal block 을 위로 끌어올림
    st.markdown(
        '<div class="row-pair-tight"></div>',
        unsafe_allow_html=True,
    )
    loc_sel = ag_well_helpers.cascading_location_filters(
        df_master, key_prefix="qty_loc", si_label="시 구분",
    )
    # cache wrapper — (loc_sel, yh range) 키로 5분 캐시. df_master_f + qf 두
    # DataFrame 을 한 번에 반환. 같은 입력으로 재진입 시 즉시 반환.
    df_master_f, qf = _build_filtered_qf_cached(
        loc_sel.get("well_si"),
        loc_sel.get("well_eup"),
        loc_sel.get("well_ri"),
        yh_lo,
        yh_hi,
    )

    if df_master_f.empty:
        st.info("선택한 지역 조건에 해당하는 관정이 없습니다.")
        return

    # 사용자 요청 #5: 시/읍면동/리 선택 변경 시 지도 중심을 그 지역 관정 중심으로 이동.
    # fingerprint 가 바뀐 첫 rerun 에만 적용 → 마커 클릭 후 줌 변경한 사용자의 뷰는 보존.
    _maybe_recenter_map(loc_sel, df_master_f)

    region_label = _location_label(loc_sel)
    period_label = _yh_period_label(yh_lo, yh_hi)
    # cascading filter row 와 정보 박스 사이는 Streamlit 기본 gap 을 유지해
    # 라벨("리")이 정보박스 윗변에 닿지 않도록 한다.
    # (이전 row-pair-tight 마커는 라벨 겹침을 유발해 제거.)
    st.markdown(
        f'<div style="margin:0 0 6px;padding:8px 14px;'
        f'background:var(--color-bg-secondary);border-left:3px solid var(--color-text-info);'
        f'border-radius:4px;font-size:16px;color:var(--color-text-primary);">'
        f'<b style="color:var(--color-text-info);">지역</b>&nbsp;: '
        f'<span style="font-weight:600;">{region_label}</span>'
        f'&nbsp;&nbsp;|&nbsp;&nbsp;'
        f'<b style="color:var(--color-text-info);">선택 기간</b>&nbsp;: '
        f'<span style="font-weight:600;">{period_label}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    if qf.empty or item not in qf.columns:
        st.info("선택 조건에 해당하는 수질 측정 자료가 없습니다.")
        return

    _render_kpi_cards(qf, item, level)

    st.markdown(
        '<hr style="margin:10px 0;border:none;'
        'border-top:0.5px solid rgba(26,26,24,0.15);">',
        unsafe_allow_html=True,
    )
    _render_map(qf, df_master_f, item, available_items)

    # ── 사용자 요청 #5·#6·#7: 그룹별 박스 플롯 + 시계열 표
    st.markdown(
        '<hr style="margin:14px 0;border:none;'
        'border-top:0.5px solid rgba(26,26,24,0.15);">',
        unsafe_allow_html=True,
    )
    _render_group_section(qf, item, level, loc_sel, yh_lo, yh_hi)


# ==============================================================================
#  KPI 카드 5개
# ==============================================================================


# ==============================================================================
#  지도 + 관정 클릭 → 상세
# ==============================================================================


