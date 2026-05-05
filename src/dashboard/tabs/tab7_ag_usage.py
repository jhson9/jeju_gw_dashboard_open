# ==============================================================================
#  파일명: src/dashboard/tabs/tab7_ag_usage.py  —  Build 2.2
#  탭: ⑥ 이용량 분석 (이용현황 중심)
# ------------------------------------------------------------------------------
#  설계 원칙:
#   - 「사용률(%)」 「허가량 대비 초과」는 부차적 지표로 본 탭에서 제거.
#     이용현황(volume) 자체를 다양한 집계 단위로 보여주는 데 집중.
#   - 상단: 지도(이용량 비례 마커 + 톤) — popup 에 평균 일 사용량 표시.
#   - 컨트롤은 2줄 유지: 1줄 = 분석 옵션 / 2줄 = 지역 cascading 필터.
#   - 하단:
#       · 집계 단위별 하위 그룹 통계 표 (관정수 · 총량 · 월평균 · 일평균 · 관정당 일평균)
#       · 박스 플롯 (그룹별 월별 이용량 분포)
#       · 기초 통계 표 (분석기간 내 최대/최소 사용 연월)
#       · 시계열 + 관정별 그리드
#
#  Build 2.2 (2026-05-02):
#   - render() 전체를 @st.fragment 로 감싸 슬라이더/필터 변경 시 다른 탭으로
#     튕기는 현상 차단 (fragment 내부만 rerun → 전역 DOM 영향 없음).
# ==============================================================================

from __future__ import annotations

import calendar
import re

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_folium import st_folium

import config
from src.analysis import ag_well_loader, ag_well_metrics
from src.collectors import asos_collector
from src.dashboard import ag_well_helpers


# 공용 fragment-only rerun 헬퍼 (컨텍스트 가드 포함).
# 이전 로컬 정의는 컨텍스트 가드가 없어서 fragment 외부에서 호출되면
# 「Couldn't find fragment with id ...」 경고 + full rerun 폴백 → 탭 점프 유발.
# ag_well_helpers.fragment_rerun 을 alias 로 사용.
_fragment_rerun = ag_well_helpers.fragment_rerun


_AGG_LABELS = ["제주도 전역", "시", "읍면동", "리", "유역"]


# ── 집계 단위별 하위 그룹 키 정의
#   key: 집계 단위 라벨
#   group_col: 집계할 컬럼 (merged 에 존재해야 함)
#   group_label: 표 헤더에 보일 한국어 라벨
_LEVEL_TO_GROUP: dict[str, tuple[str, str]] = {
    "제주도 전역": ("authority", "시"),
    "도전역":      ("authority", "시"),   # legacy alias
    "시":          ("well_eup",  "읍/면/동"),
    "읍면동":      ("well_ri",   "리"),
    "리":          ("well_id",   "관정명"),
    "유역":        ("watershed", "유역"),
}


# ──────────────────────────────────────────────────────────────────
#  메인 render — @st.fragment 로 격리해 탭 튕김 차단.
# ──────────────────────────────────────────────────────────────────
def _maybe_recenter_usage_map(loc_sel: dict, df_master_f: pd.DataFrame) -> None:
    """위치 필터(시/읍면동/리)가 변경되면 지도 중심·줌을 그 지역 관정 centroid 로 이동.

    fingerprint(=loc_sel 값 튜플) 가 직전 호출과 다를 때만 갱신.
    줌: 리 14, 읍면동 12, 시 11, 전체 11.
    """
    fp = (loc_sel.get("well_si"), loc_sel.get("well_eup"), loc_sel.get("well_ri"))
    last_fp = st.session_state.get("_usage_loc_fingerprint")
    if fp == last_fp:
        return
    st.session_state["_usage_loc_fingerprint"] = fp

    if df_master_f.empty:
        return
    if "lat" not in df_master_f.columns or "lon" not in df_master_f.columns:
        return
    coords = df_master_f.dropna(subset=["lat", "lon"])
    if coords.empty:
        return

    cy = float(coords["lat"].mean())
    cx = float(coords["lon"].mean())
    st.session_state["usage_map_center"] = (cy, cx)

    if loc_sel.get("well_ri"):
        st.session_state["usage_map_zoom"] = 14
    elif loc_sel.get("well_eup"):
        st.session_state["usage_map_zoom"] = 12
    elif loc_sel.get("well_si"):
        st.session_state["usage_map_zoom"] = 11
    else:
        st.session_state["usage_map_zoom"] = 11


def _normalize_group_values(merged: pd.DataFrame, group_col: str) -> pd.DataFrame:
    """행정구역 동지역 처리 — group_col 값을 일관성 있게 정규화.

    제주시/서귀포시의 동지역(○○동) 처리 규칙:
      - well_eup 그룹: 모든 '○○동' 값을 '동지역' 1개로 통합
      - well_ri 그룹: ri 가 비어있는 동지역 관정은 well_eup 의 동(예: 상효동)으로
                       채워 넣어 「리 단위에서 동을 표시」(사용자 요구) 충족
      - authority/watershed: 변경 없음
    """
    out = merged.copy()
    if group_col == "well_eup":
        eup = out[group_col].astype(str).str.strip().replace(
            {"nan": "", "None": "", "NaN": "", "<NA>": ""}
        )
        out[group_col] = eup.where(~eup.str.endswith("동", na=False), "동지역")
    elif group_col == "well_ri":
        ri = out[group_col].astype(str).str.strip().replace(
            {"nan": "", "None": "", "NaN": "", "<NA>": ""}
        )
        if "well_eup" in out.columns:
            eup = out["well_eup"].astype(str).str.strip().replace(
                {"nan": "", "None": "", "NaN": "", "<NA>": ""}
            )
            # ri 가 있으면 ri 그대로, 없고 eup 이 동이면 그 동을 ri 그룹키로
            fallback = eup.where(eup.str.endswith("동", na=False), "")
            out[group_col] = ri.where(ri != "", fallback)
        else:
            out[group_col] = ri
    return out


def _stats_filter_for_level(level: str, loc_sel: dict) -> dict:
    """집계단위에 따라 cascading filter 를 「한 단계 위」 까지만 적용.

    이유: 집계단위가 「시」이면 표·박스 플롯이 시의 한 단계 아래(읍/면/동) 분포를
          보여줘야 의미가 있다. 사용자가 cascading 에서 읍/면/동 / 리를 선택해
          좁혀도, 통계 표는 시 안의 모든 읍면동을 보여주도록 부분 필터만 적용.

    규칙:
      제주도 전역 → 모두 무시
      시          → well_si 만 적용 (읍/면/동 / 리 무시)
      읍/면/동    → well_si, well_eup 적용 (리 무시)
      리, 유역    → 모든 필터 적용
    """
    if level in ("제주도 전역", "도전역"):
        return {}
    if level == "시":
        return {"well_si": loc_sel.get("well_si")}
    if level == "읍면동":
        return {
            "well_si":  loc_sel.get("well_si"),
            "well_eup": loc_sel.get("well_eup"),
        }
    return dict(loc_sel)


def _yr_label(yr_range: tuple[int, int]) -> str:
    """기간 라벨 — 단일 연도면 'YYYY년', 범위면 'YYYY ~ YYYY년'."""
    if yr_range[0] == yr_range[1]:
        return f"{yr_range[0]}년"
    return f"{yr_range[0]} ~ {yr_range[1]}년"


def _location_label(loc_sel: dict) -> str:
    """cascading filter 결과 → 지역 라벨. 단계가 깊어질수록 ' > ' 로 연결."""
    parts = []
    for k in ("well_si", "well_eup", "well_ri"):
        v = loc_sel.get(k)
        if v:
            parts.append(v)
    return " > ".join(parts) if parts else "제주도 전역"


def _stats_title_scope(level: str, loc_sel: dict) -> str:
    """집계 단위별 통계 표의 제목 — 사용자가 선택한 위치명을 우선 표시.

    예) 집계단위='읍면동' + 사용자가 '대정읍' 선택 → '대정읍'
        집계단위='시'   + 사용자가 '서귀포시' 선택 → '서귀포시'
        선택 없으면 집계단위 라벨 그대로.
    """
    si = loc_sel.get("well_si") or ""
    eup = loc_sel.get("well_eup") or ""
    ri = loc_sel.get("well_ri") or ""
    if level in ("제주도 전역", "도전역"):
        return "제주도 전역"
    if level == "시":
        return si or "제주도 전역 (시 미선택)"
    if level == "읍면동":
        return eup or si or "제주도 전역 (읍면동 미선택)"
    if level == "리":
        return ri or eup or si or "제주도 전역 (리 미선택)"
    if level == "유역":
        return "유역별"
    return level


@st.fragment
def render() -> None:
    st.markdown(
        '<h2 style="font-size:22px;font-weight:500;margin:0 0 6px;padding:0;'
        'color:#1a1a18;line-height:1.2;">'
        '⑥ 이용량 분석 — 농업용 공공관정</h2>',
        unsafe_allow_html=True,
    )

    df_master = ag_well_loader.load_master(active_only=True)
    df_usage = ag_well_loader.load_usage_long()

    if df_usage.empty:
        st.warning("이용량 자료를 찾을 수 없습니다 (usage/usage_montly_*.csv).")
        return

    # ── 첫 진입 시 default 값 세팅 (위젯 인스턴스화 전이라 직접 할당 안전)
    if "usage_level" not in st.session_state:
        st.session_state["usage_level"] = "시"
    if "usage_loc_si" not in st.session_state:
        st.session_state["usage_loc_si"] = "전체"

    # ── 컨트롤 두 줄(집계단위/연도 → 시구분/읍면동/리) 사이 공백 ~8~10mm 안전 압축.
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
        margin-top: -2.0rem !important;
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

    # ── ① 컨트롤 1줄: 집계 단위 / 분석 연도
    #   (시계열 단위는 항상 '월별'로 고정 — selectbox 제거)
    c1, c2 = st.columns([1.5, 4])
    with c1:
        level = st.selectbox(
            "집계 단위", _AGG_LABELS, key="usage_level",
        )
    with c2:
        yr_min = int(df_usage["year"].min())
        yr_max = int(df_usage["year"].max())
        yr_range = ag_well_helpers.year_slider(
            yr_min, yr_max, key="usage_year_range"
        )

    # ── ② 컨트롤 2줄: 시 구분 → 읍면동 → 리 (cascading)
    #     marker — 위 CSS 가 다음 horizontal block 을 위로 끌어올림
    st.markdown(
        '<div class="row-pair-tight"></div>',
        unsafe_allow_html=True,
    )
    loc_sel = ag_well_helpers.cascading_location_filters(
        df_master, key_prefix="usage_loc", si_label="시 구분",
    )
    df_master_f = ag_well_helpers.apply_cascading_filters(df_master, loc_sel)

    if df_master_f.empty:
        st.info("선택한 지역 조건에 해당하는 관정이 없습니다.")
        return

    # 사용자 요청 #9: 시/읍면동/리 변경 시 지도 중심을 그 지역 관정 centroid 로 이동.
    _maybe_recenter_usage_map(loc_sel, df_master_f)

    # ── usage × master join + 연도 필터
    keep_cols = ["permit_no"] + [
        c for c in ("authority", "well_eup", "well_ri", "watershed", "well_si")
        if c in df_master_f.columns
    ]
    merged = df_usage.merge(
        df_master_f[keep_cols].drop_duplicates("permit_no"),
        on="permit_no", how="inner",
    )
    merged = merged[
        (merged["year"] >= yr_range[0]) & (merged["year"] <= yr_range[1])
    ].copy()

    if merged.empty:
        st.info("선택 조건에 해당하는 이용량 자료가 없습니다.")
        return

    # ── 분석 기간 일수·월수 (KPI/통계 계산용)
    n_days_in_period = sum(
        366 if calendar.isleap(y) else 365
        for y in range(yr_range[0], yr_range[1] + 1)
    )
    n_months_in_period = (yr_range[1] - yr_range[0] + 1) * 12

    # ── KPI 카드 (이용현황 중심)
    n_wells = merged["permit_no"].nunique()
    total_vol = float(merged["volume_m3"].sum(skipna=True))
    avg_monthly = total_vol / n_months_in_period if n_months_in_period else 0.0
    avg_daily = total_vol / n_days_in_period if n_days_in_period else 0.0
    avg_per_well_daily = avg_daily / n_wells if n_wells else 0.0

    # 통합 라인: 지역 + 선택 기간 (KPI 들이 어떤 범위의 결과인지 한 줄로 명시)
    region_label = _location_label(loc_sel)
    n_yr = yr_range[1] - yr_range[0] + 1
    period_label = (
        f"{yr_range[0]}-01 ~ {yr_range[1]}-12 (총 {n_yr}년)"
        if n_yr > 1 else
        f"{yr_range[0]}-01 ~ {yr_range[0]}-12 (1년)"
    )
    # cascading filter row 와 정보 박스 사이는 Streamlit 기본 gap 을 유지해
    # 라벨("리")이 정보박스 윗변에 닿지 않도록 한다.
    # (이전 row-pair-tight 마커는 라벨 겹침을 유발해 제거.)
    st.markdown(
        f'<div style="margin:0 0 6px;padding:8px 14px;'
        f'background:#f5f5f3;border-left:3px solid #185fa5;'
        f'border-radius:4px;font-size:13px;color:#1a1a18;">'
        f'<b style="color:#185fa5;">지역</b>&nbsp;: '
        f'<span style="font-weight:600;">{region_label}</span>'
        f'&nbsp;&nbsp;|&nbsp;&nbsp;'
        f'<b style="color:#185fa5;">선택 기간</b>&nbsp;: '
        f'<span style="font-weight:600;">{period_label}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    # ── KPI 박스 5개 — Tab8 동일 스타일로 통일 (사용자 호소 #2)
    #   값 글자크기 22px = h2 헤더 사이즈 (호소 #3)
    #   안전 가드: st.columns(5) 안에서 각 col 별 st.markdown 으로 렌더 →
    #              stHorizontalBlock 으로 감싸져 row-pair-tight 셀렉터 매치 안 됨.
    cards = [
        ("관정 수",        f"{n_wells:,}공",                  "활성 관정"),
        ("총 이용량",      f"{total_vol:,.0f} ㎥",            "분석기간 합계"),
        ("월평균",         f"{avg_monthly:,.0f} ㎥/월",       "월별 평균"),
        ("일평균",         f"{avg_daily:,.0f} ㎥/일",         "일별 평균"),
        ("관정당 일평균",  f"{avg_per_well_daily:,.1f} ㎥/일", f"{n_wells:,}공 평균"),
    ]
    accent_colors = ["#185fa5", "#185fa5", "#305496", "#305496", "#C00000"]
    cols = st.columns(5)
    for i, (col, (title, big, sub)) in enumerate(zip(cols, cards)):
        accent = accent_colors[i]
        with col:
            st.markdown(
                f'<div style="background:#f5f5f3;border-radius:8px;'
                f'padding:10px 14px;border-left:3px solid {accent};'
                f'margin-bottom:6px;min-height:92px;">'
                f'<div style="font-size:14px;font-weight:600;color:#5f5e5a;'
                f'line-height:1.25;">{title}</div>'
                f'<div style="font-size:22px;font-weight:500;color:{accent};'
                f'line-height:1.2;margin-top:4px;white-space:nowrap;'
                f'overflow:hidden;text-overflow:ellipsis;">{big}</div>'
                f'<div style="font-size:12px;color:#5f5e5a;'
                f'line-height:1.35;margin-top:3px;">{sub}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    # ── ③ 지도 (이용량 비례 마커 + 톤)
    st.markdown(
        '<hr style="margin:10px 0;border:none;'
        'border-top:0.5px solid rgba(26,26,24,0.15);">',
        unsafe_allow_html=True,
    )
    st.markdown(
        f'<div style="font-size:13px;font-weight:600;color:#185fa5;'
        f'margin-top:6px;margin-bottom:6px;">관정 위치 · 이용량 분포 — '
        f'마커 크기 · 톤은 {yr_range[0]}~{yr_range[1]} 합계에 비례'
        f'<span title="제주시 자료는 분기별 자료로 역산된 자료들이 있으므로 '
        f'분석시 주의 요망" style="margin-left:6px;color:#e6a700;'
        f'cursor:help;font-size:14px;">⚠️</span>'
        f'<span style="margin-left:6px;font-size:11px;font-weight:500;'
        f'color:#9a7b00;">'
        f'제주시 자료는 분기별 자료로 역산된 자료들이 있으므로 분석시 주의 요망'
        f'</span>'
        f'</div>',
        unsafe_allow_html=True,
    )
    _render_usage_map(df_master_f, merged, n_days_in_period)

    # ── 선택 관정 헤더 + 검색 — 상시 표시 (지도 클릭 외에 직접 검색으로도 선택).
    sel_permit = st.session_state.get("usage_selected_permit")
    _render_well_selection_bar(df_master, sel_permit)
    # 선택된 관정이 있을 때만 상세 데이터 (월별 표·허가량 표·강수량 그래프) 렌더.
    # 단일 관정 분석은 슬라이더 무시 — 그 관정의 가용 자료 전체를 표시.
    if sel_permit:
        _render_well_detail(sel_permit, df_master_f)

    yr_label = _yr_label(yr_range)

    # ── 통계 표·박스 플롯용 merged_stats: 집계단위에 따라 한 단계 위 필터까지만 적용
    #   (예: 집계단위='시' + cascading '서귀포시 > 표선면' → 통계는 서귀포시 전체로
    #         확장하여 안의 읍/면/동 분포를 보여줌)
    stats_loc = _stats_filter_for_level(level, loc_sel)
    df_master_stats = ag_well_helpers.apply_cascading_filters(df_master, stats_loc)
    merged_stats = df_usage.merge(
        df_master_stats[keep_cols].drop_duplicates("permit_no"),
        on="permit_no", how="inner",
    )
    merged_stats = merged_stats[
        (merged_stats["year"] >= yr_range[0])
        & (merged_stats["year"] <= yr_range[1])
    ].copy()

    # ── ④ 집계 단위별 하위 그룹 통계 표
    scope_label = _stats_title_scope(level, loc_sel)
    st.markdown(
        f'<div style="font-size:13px;font-weight:600;color:#185fa5;'
        f'margin-top:14px;">{scope_label} 이용량 통계 ({yr_label})</div>',
        unsafe_allow_html=True,
    )
    _render_group_stats(
        merged_stats, level, n_days_in_period, n_months_in_period, yr_range,
    )

    # ── ⑤ 박스 플롯 — 그룹별 이용량 분포
    st.markdown(
        f'<div style="font-size:13px;font-weight:600;color:#185fa5;'
        f'margin-top:14px;">{scope_label} 지역별 이용량 분포 ({yr_label})</div>',
        unsafe_allow_html=True,
    )
    _render_monthly_box(merged_stats, level)

    # ── ⑥ 박스 플롯 — 1월~12월 월별 이용량 분포 (전 분석기간 통합)
    st.markdown(
        f'<div style="font-size:13px;font-weight:600;color:#185fa5;'
        f'margin-top:14px;">{scope_label} 월별 이용량 분포 (Box Plot) '
        f'({yr_label})</div>',
        unsafe_allow_html=True,
    )
    _render_month_box(merged)

    # ── ⑦ AWS 월별 강수량 + 지역 월별 이용량 (이중축)
    aws_name = _select_aws_for_region(df_master_f)
    aws_label = aws_name or "(선택 지역에 해당하는 AWS 없음)"
    st.markdown(
        f'<div style="font-size:13px;font-weight:600;color:#185fa5;'
        f'margin-top:14px;">{scope_label} 월별 강수량 · 이용량 비교 '
        f'(적용 AWS: <span style="color:#C00000;">{aws_label}</span>) '
        f'({yr_label})</div>',
        unsafe_allow_html=True,
    )
    _render_aws_rainfall(aws_name, yr_range, merged)

    # ── ⑦ 집계단위별 하위그룹 「월별 강수량 · 이용량 비교」 — 1개 통합 차트.
    #   시 → 읍면동, 읍면동 → 리, 리 → 관정 단위로 한 단계 분해, 다중 라인.
    _render_subgroup_rainfall_combined(level, loc_sel, aws_name, yr_range, merged)

    # ── 다운로드
    with st.expander("📥 데이터 내보내기 (CSV)"):
        st.download_button(
            "필터링된 long format 내려받기",
            data=merged.to_csv(index=False).encode("utf-8-sig"),
            file_name=f"ag_usage_{yr_range[0]}_{yr_range[1]}.csv",
            mime="text/csv",
            # MediaFileStorageError 방지 — 위젯 ID 안정화 (호소 #7)
            key="tab7_ag_usage_csv",
        )


# ------------------------------------------------------------------------------
_DEFAULT_MAP_ZOOM = 11
_DEFAULT_MAP_CENTER = (33.38, 126.55)


def _render_well_selection_bar(
    df_master: pd.DataFrame, selected_permit: str | None,
) -> None:
    """상시 표시되는 「선택 관정 + 검색 + 선택 해제」 바.

    레이아웃 (3열):
      ① 좌측  : 「선택 관정: X (주소 · permit_no)」 — 미선택 시 안내 텍스트
      ② 중앙  : 관정명 검색 입력 (Enter → 즉시 선택 + 지도 중심 이동)
      ③ 우측  : 「선택 해제」 버튼 — 선택 상태일 때만 활성
    """
    h_left, h_search, h_right = st.columns([4, 2.2, 1])

    with h_left:
        if selected_permit:
            info = ag_well_loader.get_well_info(selected_permit)
            well_id = (info.get("well_id") if info else selected_permit) or selected_permit
            addr_parts: list[str] = []
            for k in ("well_si", "well_eup", "well_ri", "well_bunji"):
                v = info.get(k) if info else None
                if v is None or (isinstance(v, float) and pd.isna(v)):
                    continue
                s = str(v).strip()
                if s and s.lower() not in ("nan", "none"):
                    addr_parts.append(s)
            addr = " ".join(addr_parts) if addr_parts else "주소 미상"
            inner = (
                f'선택 관정: {well_id} '
                f'<span style="font-weight:400;color:#5f5e5a;font-size:12px;">'
                f'({addr} · {selected_permit})</span>'
            )
        else:
            inner = (
                '선택 관정: '
                '<span style="font-weight:400;color:#7a7a76;font-size:12px;">'
                '(미선택 — 지도 마커 클릭 또는 우측 검색창에 관정명 입력)</span>'
            )
        st.markdown(
            f'<div style="font-size:14px;font-weight:600;color:#185fa5;'
            f'padding:10px 0 4px;border-top:1px solid rgba(26,26,24,0.15);'
            f'margin-top:10px;">{inner}</div>',
            unsafe_allow_html=True,
        )

    with h_search:
        # 라벨 라인 높이를 좌측 헤더와 맞추기 위한 spacer
        st.markdown('<div style="margin-top:10px;"></div>', unsafe_allow_html=True)
        _render_well_search_input(df_master)

    with h_right:
        st.markdown('<div style="margin-top:14px;"></div>', unsafe_allow_html=True)
        if selected_permit and st.button(
            "선택 해제", key="usage_clear_sel", use_container_width=True,
        ):
            st.session_state.pop("usage_selected_permit", None)
            _fragment_rerun()


def _render_well_search_input(df_master: pd.DataFrame) -> None:
    """관정명 직접 검색 입력 — Enter 시 매칭 관정을 선택하고 지도 중심 이동.

    매칭 우선순위:
      ① well_id 정확 일치 (대소문자 무시) → 즉시 선택
      ② well_id 부분 일치 1건 → 선택
      ③ 부분 일치 다수 → 안내 메시지 (사용자가 더 정확히 입력)
      ④ 일치 없음 → 경고
    """
    keyword = st.text_input(
        "관정명 검색",
        value="",
        key="usage_well_search",
        placeholder="관정명 입력 후 Enter (예: F-430, 90감산)",
        label_visibility="collapsed",
    )

    # 같은 키워드로 rerun 마다 재처리 방지
    last_kw = st.session_state.get("_usage_well_search_last", "")
    if keyword == last_kw:
        return
    st.session_state["_usage_well_search_last"] = keyword

    if not keyword.strip():
        return
    if df_master.empty or "well_id" not in df_master.columns:
        st.warning("관정 자료를 찾을 수 없습니다.")
        return

    kw = keyword.strip().lower()
    well_ids = df_master["well_id"].astype(str)

    exact = df_master[well_ids.str.lower() == kw]
    if not exact.empty:
        match = exact.iloc[0]
    else:
        partial = df_master[well_ids.str.lower().str.contains(kw, na=False)]
        if partial.empty:
            st.warning(f"'{keyword}' 와(과) 일치하는 관정이 없습니다.")
            return
        if len(partial) > 1:
            ids = ", ".join(partial["well_id"].astype(str).head(5).tolist())
            tail = " ..." if len(partial) > 5 else ""
            st.info(
                f"매칭 관정 {len(partial)}개: {ids}{tail}. 더 정확한 이름을 입력하세요."
            )
            return
        match = partial.iloc[0]

    permit_no = match.get("permit_no")
    if not permit_no:
        st.warning("관정 정보를 찾을 수 없습니다.")
        return

    st.session_state["usage_selected_permit"] = permit_no
    # zoom·center 는 maybe_recenter_to_selected_well 이 다음 build 직전에
    # fingerprint 패턴으로 zoom 12 + 그 관정 중심으로 처리. 검색 경로에서
    # 별도 zoom 14 를 set 하지 않아 마커 클릭과 일관된 동작.
    _fragment_rerun()


def _render_usage_map(
    df_master_f: pd.DataFrame,
    merged: pd.DataFrame,
    n_days_in_period: int,
) -> None:
    """필터링된 관정 마커 — 이용량 합계에 마커 크기·톤 비례.

    동작:
      - 줌·중심 보존: st_folium 의 'zoom' / 'center' 반환값을 session_state 에
        저장 → 다음 rerun 에서 그 값으로 마운트. 마커 클릭·필터 변경 등의
        rerun 후에도 사용자가 보던 줌 위치 유지.
      - 마커 클릭 즉시 반영: session_state 갱신 직후 fragment-only rerun 으로
        새 sel 을 그림 → 빨간 강조 원과 아래 분석표가 동시에 갱신.
    """
    by_well = (
        merged.groupby("permit_no", dropna=False)["volume_m3"]
              .sum().reset_index()
    )
    by_well["daily_avg"] = (
        by_well["volume_m3"] / n_days_in_period if n_days_in_period else 0
    )

    sel = st.session_state.get("usage_selected_permit")

    # 관정 선택 시 그 관정 중심으로 zoom 12 (읍/면/동 사이즈) — fingerprint 패턴.
    # 마커 클릭·텍스트 검색 어느 경로든 sel 이 갱신되면 1회 발동.
    ag_well_helpers.maybe_recenter_to_selected_well(
        sel, df_master_f,
        fingerprint_key="_usage_centered_permit",
        center_key="usage_map_center",
        zoom_key="usage_map_zoom",
    )

    saved_zoom = st.session_state.get("usage_map_zoom", _DEFAULT_MAP_ZOOM)
    saved_center = st.session_state.get("usage_map_center", _DEFAULT_MAP_CENTER)

    m = ag_well_helpers.build_usage_map(
        df_master_f, by_well, selected_permit=sel,
        zoom=saved_zoom, center=tuple(saved_center),
    )
    # 관정 선택 시 height 1/2 축소 — 단일 key 유지하며 height props 만 변경.
    # (height 별 별도 key 는 streamlit-folium 의 unmount/mount 를 발생시켜
    #  첫 클릭 이벤트 소실 + zoom 리셋 위험 → 단일 key 가 안전.)
    map_h = 430 if sel else 780
    click = st_folium(
        m, width=None, height=map_h,
        returned_objects=[
            "last_object_clicked_tooltip",
            "last_object_clicked_popup",
            "zoom",
            "center",
        ],
        key="usage_map",
    )

    if click:
        # ── 줌·중심 보존 (rerun 안 일으킴 — 사용자 줌 동작은 그대로)
        z = click.get("zoom")
        c = click.get("center")
        if z is not None:
            try:
                st.session_state["usage_map_zoom"] = int(z)
            except (TypeError, ValueError):
                pass
        if isinstance(c, dict) and "lat" in c and "lng" in c:
            try:
                st.session_state["usage_map_center"] = (
                    float(c["lat"]), float(c["lng"])
                )
            except (TypeError, ValueError):
                pass

        # ── 마커 click → 관정 선택
        clicked_permit = ag_well_helpers.lookup_permit_by_well_id(
            click.get("last_object_clicked_tooltip"), df_master_f
        )
        if not clicked_permit:
            clicked_permit = ag_well_helpers.parse_clicked_popup(
                click.get("last_object_clicked_popup")
            )
        if clicked_permit and clicked_permit != sel:
            # session_state 만 갱신하면 build_usage_map 이 옛 sel 로 이미 그려진
            # 상태라 한 단계 lag 가 발생 (사용자 클릭이 한 번씩 밀려 보임).
            # 즉시 fragment rerun 으로 새 sel 을 반영해 빨간 원 + 분석표가 함께 갱신.
            st.session_state["usage_selected_permit"] = clicked_permit
            _fragment_rerun()


def _render_well_detail(
    permit_no: str,
    df_master_f: pd.DataFrame,
) -> None:
    """단일 관정 상세 — 월별 표 + 연도별 허가량 표 + AWS dual-axis 그래프.

    헤더(관정명·주소·선택 해제·검색)는 _render_well_selection_bar 가 담당.
    슬라이더 연도와 무관하게 그 관정의 자료가 존재하는 전체 기간을 표시.
    """
    info = ag_well_loader.get_well_info(permit_no)
    well_id = (info.get("well_id") if info else permit_no) or permit_no

    # ── 단일 관정의 가용 자료 전체 로드 (슬라이더 무시)
    df_usage_all = ag_well_loader.load_usage_long()
    sub = df_usage_all[df_usage_all["permit_no"] == permit_no].copy()

    if sub.empty:
        st.caption("선택된 관정의 이용량 자료가 없습니다.")
        return

    well_yr_range = (int(sub["year"].min()), int(sub["year"].max()))

    # ── 월별 이용량 표 (year × month pivot)
    _render_well_monthly_table(sub)

    # ── 연도별 취수허가량 변화표 (보유한 모든 연도 · 최신값=흰색, 다른 값=같은 값끼리 같은 톤)
    _render_yearly_permit_table(permit_no, sub)

    # ── Dual-axis 그래프: AWS 강수량 + 해당 관정 월 이용량
    aws_name = _select_aws_for_region(df_master_f)
    aws_label = aws_name or "(매핑 AWS 없음)"
    yr_label = _yr_label(well_yr_range)
    st.markdown(
        f'<div style="font-size:13px;font-weight:600;color:#185fa5;'
        f'margin-top:10px;">{well_id} 월별 강수량 · 이용량 비교 '
        f'(적용 AWS: <span style="color:#C00000;">{aws_label}</span>) '
        f'({yr_label})</div>',
        unsafe_allow_html=True,
    )
    # 단일 관정 — 우측 Y축 0~2000 고정 (8 grid, 250 단위), 강수량과 보조선 정렬.
    # 연도별 「취수허가량 ÷ 30(㎥/일)」을 점선으로 함께 표시 → 일일 허가량 한도선.
    daily_permit_by_year = {
        y: v / 30.0 for y, v in _yearly_permit_for_well(permit_no, sub).items()
    }
    _render_aws_rainfall(
        aws_name, well_yr_range, sub,
        usage_y_max=2000,
        daily_permit_by_year=daily_permit_by_year,
    )


# 연도별 취수허가량 변동 색 팔레트 — 가장 최근 값(=현재 기준)은 흰색,
# 그와 다른 과거 값들은 unique 값별로 pastel tone 을 순환 부여 → 같은 값은 같은 색.
_PERMIT_PALETTE = (
    "#C8E6C9", "#FFE082", "#90CAF9", "#FFAB91",
    "#CE93D8", "#A5D6A7", "#F8BBD0", "#80DEEA",
)


def _yearly_permit_for_well(
    permit_no: str, sub: pd.DataFrame
) -> dict[int, float]:
    """관정의 연도별 permit_m3m 사전.

    데이터 소스(양쪽 union — 보유한 「모든 연도」 망라):
      - sub  : 이용량 long format (연도별 permit_m3m)
      - master_yearly/master_YYYY.csv : 이용량이 없는 연도까지 보강
    """
    yr_to_pm: dict[int, float] = {}

    if not sub.empty and "permit_m3m" in sub.columns and "year" in sub.columns:
        for yr, grp in sub.dropna(subset=["permit_m3m"]).groupby("year"):
            try:
                yr_to_pm[int(yr)] = float(grp["permit_m3m"].iloc[0])
            except (TypeError, ValueError):
                continue

    if permit_no:
        df_my = ag_well_loader.load_master_yearly_all()
        if not df_my.empty and "permit_no" in df_my.columns:
            my_sub = df_my[df_my["permit_no"] == permit_no]
            if not my_sub.empty and "permit_m3m" in my_sub.columns:
                for yr, grp in my_sub.dropna(subset=["permit_m3m"]).groupby("year"):
                    y = int(yr)
                    if y not in yr_to_pm:
                        try:
                            yr_to_pm[y] = float(grp["permit_m3m"].iloc[0])
                        except (TypeError, ValueError):
                            continue
    return yr_to_pm


def _render_yearly_permit_table(permit_no: str, sub: pd.DataFrame) -> None:
    """관정의 연도별 취수허가량(permit_m3m)을 2행 표로 렌더.

    상단 행: 연도, 하단 행: 취수허가량(㎥/월).
    표 폭은 컨테이너 100% 로 월별 이용량 표와 동일 길이.

    색 규칙:
      - 가장 최근 연도의 값(=현재 기준) → 흰색 배경
      - 그와 다른 값은 unique 값별로 pastel tone 부여, 같은 값은 같은 색
      - 직전 연도 대비 값이 바뀐 해는 ▲ 마크
    """
    yr_to_pm = _yearly_permit_for_well(permit_no, sub)

    if not yr_to_pm:
        st.caption("연도별 취수허가량 자료가 없습니다.")
        return

    # 정수 반올림으로 정규화 (소수 노이즈 흡수)
    yr_to_pm_int: dict[int, int] = {y: int(round(v)) for y, v in yr_to_pm.items()}

    sorted_years = sorted(yr_to_pm_int.keys())
    latest_val = yr_to_pm_int[sorted_years[-1]]

    # 색 매핑 — 최신값=흰색, 그 외 unique 값은 팔레트 순환
    other_unique = sorted({v for v in yr_to_pm_int.values() if v != latest_val})
    color_map: dict[int, str] = {latest_val: "#ffffff"}
    for i, v in enumerate(other_unique):
        color_map[v] = _PERMIT_PALETTE[i % len(_PERMIT_PALETTE)]

    # 셀 빌드
    year_cells: list[str] = []
    permit_cells: list[str] = []
    prev_v: int | None = None
    for y in sorted_years:
        v = yr_to_pm_int[y]
        bg = color_map[v]
        change_mark = ""
        if prev_v is not None and v != prev_v:
            change_mark = ' <span style="color:#C00000;font-weight:700;">▲</span>'
        year_cells.append(f'<td>{y}</td>')
        permit_cells.append(
            f'<td style="background:{bg};">{v:,}{change_mark}</td>'
        )
        prev_v = v

    table_html = (
        '<table class="permit-history">'
        '<tbody>'
        f'<tr class="row-year"><th>연도</th>{"".join(year_cells)}</tr>'
        f'<tr class="row-permit"><th>취수허가량 (㎥/월)</th>{"".join(permit_cells)}</tr>'
        '</tbody></table>'
    )

    css = """
    <style>
    .permit-history {
        width: 100%;
        border-collapse: collapse;
        font-size: 11.5px; color: #1a1a18;
        border: 0.5px solid rgba(26,26,24,0.18);
        margin: 6px 0 8px;
        table-layout: fixed;
    }
    .permit-history th, .permit-history td {
        padding: 5px 4px;
        border: 0.5px solid rgba(26,26,24,0.10);
        text-align: center;
        font-variant-numeric: tabular-nums;
        white-space: nowrap;
    }
    .permit-history th {
        background: #185fa5; color: #ffffff;
        font-weight: 600;
    }
    .permit-history tr.row-year td {
        background: #e6f1fb;
        color: #185fa5;
        font-weight: 700;
    }
    .permit-history tr.row-permit td {
        font-weight: 600;
    }
    </style>
    """
    st.markdown(css + table_html, unsafe_allow_html=True)


def _render_well_monthly_table(sub: pd.DataFrame) -> None:
    """단일 관정의 연도×월 표 — HTML 직접 렌더.

    각 연도마다 두 행:
      ① 월 합계 (㎥)         — 그달의 이용량 총량
      ② 일 평균 (㎥/일)      — 월 합계 ÷ 그달의 실제 일수 (윤년 자동 처리)
    우측 끝 「연 합계」 컬럼은 12개월 합계 / 365(366) 기준.

    모든 셀 중앙정렬 + 천단위 콤마.
    """
    if sub.empty:
        st.caption("선택된 관정의 이용량 자료가 없습니다.")
        return

    pv = sub.pivot_table(
        index="year", columns="month", values="volume_m3", aggfunc="sum",
    )
    if pv.empty:
        st.caption("선택된 관정의 월별 이용량 자료가 없습니다.")
        return

    # 1~12월 모두 컬럼 보장
    for m in range(1, 13):
        if m not in pv.columns:
            pv[m] = pd.NA
    pv = pv[sorted([c for c in pv.columns if isinstance(c, (int, float))])]

    # ── 일평균 셀의 분위수 기반 배경색 (heat-map 스타일, 6 단계)
    #   분석기간의 「모든 (연도 × 1~12월)」 일평균 값을 한 풀에 모아
    #   P10 / P25 / P50 / P75 / P90 산출 → 6 구간 색상.
    #   동일 풀 기준이라 모든 연도의 셀이 같은 기준으로 색상 결정.
    daily_pool: list[float] = []
    for year in pv.index:
        for m in range(1, 13):
            v = pv.loc[year, m]
            if pd.notna(v):
                days = calendar.monthrange(int(year), m)[1]
                daily_pool.append(float(v) / days)

    p10 = p25 = p50 = p75 = p90 = mean_val = None
    if len(daily_pool) >= 6:
        s = pd.Series(daily_pool)
        p10 = float(s.quantile(0.10))
        p25 = float(s.quantile(0.25))
        p50 = float(s.quantile(0.50))
        p75 = float(s.quantile(0.75))
        p90 = float(s.quantile(0.90))
        mean_val = float(s.mean())

    # ── 취수허가량 라벨 — 가장 최근 연도의 permit_m3m 을 단일 기준으로 사용.
    #   설계: 연도별로 허가량이 변경되었더라도 「현재 기준」으로 일관되게 색상 판정.
    #   데이터 소스: usage + master_yearly union (가용한 가장 최근 연도 채택).
    latest_year_permit: int | None = None
    latest_permit_value: float | None = None
    permit_label = "-"
    permit_no_in_sub: str | None = None
    if "permit_no" in sub.columns:
        nz = sub["permit_no"].dropna()
        if not nz.empty:
            permit_no_in_sub = str(nz.iloc[0])
    if permit_no_in_sub:
        yr_to_pm = _yearly_permit_for_well(permit_no_in_sub, sub)
        if yr_to_pm:
            latest_year_permit = max(yr_to_pm.keys())
            latest_permit_value = float(yr_to_pm[latest_year_permit])
            permit_label = (
                f"{latest_permit_value:,.0f} ㎥/월 "
                f'<span style="color:#7a7a76;font-weight:400;">'
                f"(기준년도: {latest_year_permit}년)</span>"
            )

    # ── Legend (표 위) — 2 섹션 수평 배치
    #   ① 일 평균 이용량 색상 기준 (6분위)
    #   ② 월 이용량 색상 기준 (취수허가량 초과 → 빨강)
    if p10 is not None:
        n_years = len(pv.index)
        legend_html = f"""
        <div style="margin:4px 0 6px;padding:8px 12px;
                    background:#f5f5f3;border-radius:6px;
                    border-left:3px solid #185fa5;
                    font-size:11px;color:#1a1a18;">
          <div style="display:flex;gap:20px;flex-wrap:wrap;align-items:flex-start;">

            <!-- 섹션 ① 일 평균 이용량 -->
            <div style="flex:2 1 600px;min-width:480px;">
              <div style="margin-bottom:5px;color:#5f5e5a;">
                <b style="color:#185fa5;">일 평균 이용량 색상 기준</b>
                · {n_years}년 전체 6분위 (모든 연도 동일):
                평균 <b>{mean_val:,.0f}</b> ·
                P10 <b>{p10:,.0f}</b> ·
                P25 <b>{p25:,.0f}</b> ·
                중위 <b>{p50:,.0f}</b> ·
                P75 <b>{p75:,.0f}</b> ·
                P90 <b>{p90:,.0f}</b> ㎥/일
              </div>
              <div style="display:flex;gap:3px;align-items:center;flex-wrap:wrap;">
                <span style="background:#C8E6C9;padding:2px 7px;border-radius:3px;">하위 10% (≤ {p10:,.0f})</span>
                <span style="background:#DCEDC8;padding:2px 7px;border-radius:3px;">~ {p25:,.0f}</span>
                <span style="background:#FFF59D;padding:2px 7px;border-radius:3px;">~ {p50:,.0f}</span>
                <span style="background:#FFE082;padding:2px 7px;border-radius:3px;">~ {p75:,.0f}</span>
                <span style="background:#FFAB91;padding:2px 7px;border-radius:3px;">~ {p90:,.0f}</span>
                <span style="background:#EF9A9A;padding:2px 7px;border-radius:3px;font-weight:700;">상위 10% (> {p90:,.0f})</span>
              </div>
            </div>

            <!-- 섹션 ② 월 이용량 -->
            <div style="flex:1 1 240px;min-width:240px;
                        border-left:1px dashed rgba(0,0,0,0.15);padding-left:14px;">
              <div style="margin-bottom:5px;color:#5f5e5a;">
                <b style="color:#185fa5;">월 이용량 색상 기준</b>
                · 취수허가량 <b>{permit_label}</b>
              </div>
              <div style="display:flex;gap:4px;align-items:center;flex-wrap:wrap;">
                <span style="padding:2px 7px;border-radius:3px;border:0.5px solid rgba(0,0,0,0.18);background:#ffffff;">정상</span>
                <span style="background:#F4978E;padding:2px 7px;border-radius:3px;font-weight:700;">취수허가량 초과</span>
              </div>
            </div>

          </div>
        </div>
        """
        # Streamlit markdown 의 「indented code block」 인식(4+ spaces) 회피.
        # 멀티라인 f-string 의 leading whitespace 가 그대로 들어가면 HTML 이
        # raw 텍스트로 렌더되므로 모든 공백을 single space 로 압축.
        legend_html = re.sub(r"\s+", " ", legend_html).strip()
        st.markdown(legend_html, unsafe_allow_html=True)

    # 6단계 색상 — 옅은 녹색 → 연두 → 옅은 노랑 → 진노랑 → 연주황 → 빨강.
    # 상위 10% (P90 초과) 는 빨강 + 굵게로 한눈에 식별.
    _common = "color:#1a1a18;font-style:normal;"
    def _heat_style(v: float) -> str:
        if p10 is None or v is None or pd.isna(v):
            return ""
        if v > p90:
            return f"background:#EF9A9A;font-weight:700;{_common}"  # 상위 10%
        if v > p75:
            return f"background:#FFAB91;{_common}"                  # P75 ~ P90
        if v > p50:
            return f"background:#FFE082;{_common}"                  # P50 ~ P75
        if v > p25:
            return f"background:#FFF59D;{_common}"                  # P25 ~ P50
        if v > p10:
            return f"background:#DCEDC8;{_common}"                  # P10 ~ P25
        return f"background:#C8E6C9;{_common}"                      # 하위 10%

    css = """
    <style>
    .well-monthly {
        width: 100%; border-collapse: collapse;
        font-size: 11.5px; color: #1a1a18;
        border: 0.5px solid rgba(26,26,24,0.18);
        margin: 6px 0 8px;
    }
    .well-monthly th, .well-monthly td {
        padding: 6px 4px;
        border: 0.5px solid rgba(26,26,24,0.10);
        text-align: center;
        font-variant-numeric: tabular-nums;
        white-space: nowrap;
    }
    .well-monthly thead th {
        background: #185fa5; color: #ffffff;
        font-weight: 600;
    }
    /* 연도 컬럼 (rowspan=2 로 두 행 묶음) — 짙은 파랑 + 흰 글자 */
    .well-monthly td.year-col {
        background: #185fa5; color: #ffffff;
        font-weight: 700; font-size: 12px;
        vertical-align: middle;
    }
    /* 구분 컬럼 (월 이용량 / 일 평균) */
    .well-monthly td.kind-col {
        background: #e6f1fb; color: #185fa5;
        font-weight: 600;
    }
    /* 일 평균 행 — 옅은 배경 (heat-map 셀은 inline style 이 우선) */
    .well-monthly tbody tr.daily-row td {
        background: #fafaf8;
        color: #5f5e5a;
        font-style: italic;
    }
    .well-monthly tbody tr.daily-row td.kind-col {
        background: #d7e6f5;
        color: #185fa5;
        font-style: normal;
    }
    .well-monthly td.total-col {
        background: #d7e6f5; font-weight: 700; color: #185fa5;
        font-style: normal;
    }
    /* 취수허가량 초과 — 빨강 강조 */
    .well-monthly td.over-permit {
        background: #F4978E !important;
        color: #1a1a18; font-weight: 700;
        font-style: normal;
    }
    </style>
    """

    def _fmt(v) -> str:
        if v is None or pd.isna(v):
            return "-"
        try:
            return f"{int(round(float(v))):,}"
        except (TypeError, ValueError):
            return "-"

    # ── 취수허가량 초과 판정 — 연도별 변경과 무관하게 「최근 기준값」하나로 비교.
    def _is_over_permit(yr: int, mo: int, vol: float) -> bool:
        if latest_permit_value is None or latest_permit_value <= 0:
            return False
        return vol > latest_permit_value

    body_rows = []
    for year, row_data in pv.iterrows():
        yr = int(year)
        # 연 합계 산출 (NaN 제외)
        year_total = float(row_data.sum(skipna=True))
        year_days = 366 if calendar.isleap(yr) else 365

        # ── ① 월 이용량 행 — 연도 셀은 rowspan=2 로 다음 행과 묶음
        cells = [
            f'<td class="year-col" rowspan="2">{yr}</td>',
            '<td class="kind-col">월 이용량 (㎥)</td>',
        ]
        for m in range(1, 13):
            v = row_data[m]
            if pd.isna(v):
                cells.append('<td>-</td>')
            else:
                if _is_over_permit(yr, m, float(v)):
                    cells.append(
                        f'<td class="over-permit">{_fmt(v)}</td>'
                    )
                else:
                    cells.append(f'<td>{_fmt(v)}</td>')
        cells.append(f'<td class="total-col">{_fmt(year_total)}</td>')
        body_rows.append('<tr class="total-row">' + "".join(cells) + "</tr>")

        # ── ② 일 평균 이용량 행 — heat-map 색상 (분위수 기반)
        cells = ['<td class="kind-col">일 평균 이용량 (㎥/일)</td>']
        for m in range(1, 13):
            v = row_data[m]
            if pd.isna(v):
                cells.append('<td>-</td>')
            else:
                days = calendar.monthrange(yr, m)[1]
                daily = float(v) / days if days else 0
                style = _heat_style(daily)
                style_attr = f' style="{style}"' if style else ""
                cells.append(f'<td{style_attr}>{_fmt(daily)}</td>')
        # 연 일평균 = 연 합계 / 365(366)
        if year_total > 0:
            cells.append(
                f'<td class="total-col">{_fmt(year_total / year_days)}</td>'
            )
        else:
            cells.append('<td class="total-col">-</td>')
        body_rows.append('<tr class="daily-row">' + "".join(cells) + "</tr>")

    headers = (
        "<thead><tr>"
        '<th>연도</th>'
        '<th>구분</th>'
        + "".join(f"<th>{m}월</th>" for m in range(1, 13))
        + '<th>연 합계</th>'
        + "</tr></thead>"
    )

    html = (
        css
        + '<table class="well-monthly">'
        + headers
        + "<tbody>" + "".join(body_rows) + "</tbody>"
        + "</table>"
    )
    st.markdown(html, unsafe_allow_html=True)


# ------------------------------------------------------------------------------
def _render_group_stats(
    merged: pd.DataFrame,
    level: str,
    n_days: int,
    n_months: int,
    yr_range: tuple[int, int],
) -> None:
    """집계 단위에 따라 하위 그룹별 통계 표를 렌더.

    도전체 → 제주시 / 서귀포시 단위 (authority)
    시      → 선택된 시의 읍면 단위 (well_eup)
    읍면동  → 선택된 읍면의 리 단위 (well_ri)
    리      → 선택된 리의 관정 단위 (well_id)
    유역    → 유역 단위 (watershed)

    각 그룹별 9 컬럼:
      관정 수 / 총 이용량 / 월평균 / 일평균 / 관정당 일평균
      + 최대사용월 / 최대월 사용량 / 최대월 일평균 / 최대월 관정당 일평균

    모든 수치는 정수로 반올림해서 표시.
    """
    grp_info = _LEVEL_TO_GROUP.get(level)
    if grp_info is None:
        return
    group_col, group_label = grp_info

    if group_col not in merged.columns:
        st.caption(f"'{group_col}' 컬럼이 없어 표를 생성할 수 없습니다.")
        return

    # 동지역 처리 — well_eup 의 '○○동' → '동지역', well_ri NaN 은 동으로 fallback
    sub = _normalize_group_values(merged, group_col)
    sub = sub[sub[group_col].notna()]
    sub[group_col] = sub[group_col].astype(str).str.strip()
    sub = sub[sub[group_col] != ""]

    if sub.empty:
        st.caption("표시할 자료가 없습니다.")
        return

    # ── 그룹별 기본 집계 (관정수 / 총 이용량)
    agg = sub.groupby(group_col, dropna=False).agg(
        n_wells=("permit_no", "nunique"),
        volume=("volume_m3", "sum"),
    ).reset_index()

    # ── 그룹별 (year, month) 합계 → 그룹별 최대/최소 사용월 추출
    monthly = (
        sub.groupby([group_col, "year", "month"], dropna=False)["volume_m3"]
           .sum().reset_index()
    )
    monthly = monthly[monthly["volume_m3"] > 0]
    if not monthly.empty:
        max_idx = monthly.groupby(group_col)["volume_m3"].idxmax()
        min_idx = monthly.groupby(group_col)["volume_m3"].idxmin()
        max_df = monthly.loc[max_idx, [group_col, "year", "month", "volume_m3"]].rename(
            columns={"year": "max_year", "month": "max_month", "volume_m3": "max_volume"}
        )
        min_df = monthly.loc[min_idx, [group_col, "year", "month", "volume_m3"]].rename(
            columns={"year": "min_year", "month": "min_month", "volume_m3": "min_volume"}
        )
    else:
        max_df = pd.DataFrame(columns=[group_col, "max_year", "max_month", "max_volume"])
        min_df = pd.DataFrame(columns=[group_col, "min_year", "min_month", "min_volume"])

    # authority 영문 코드 → 한국어 (3개 DataFrame 모두)
    if group_col == "authority":
        agg[group_col] = agg[group_col].map(ag_well_metrics.AUTHORITY_KOR).fillna(agg[group_col])
        if not max_df.empty:
            max_df[group_col] = max_df[group_col].map(ag_well_metrics.AUTHORITY_KOR).fillna(max_df[group_col])
        if not min_df.empty:
            min_df[group_col] = min_df[group_col].map(ag_well_metrics.AUTHORITY_KOR).fillna(min_df[group_col])

    agg = agg.merge(max_df, on=group_col, how="left")
    agg = agg.merge(min_df, on=group_col, how="left")

    agg = agg[agg["volume"] > 0]
    if agg.empty:
        st.caption("표시할 자료가 없습니다.")
        return

    # ── 분석기간 평균
    agg["월평균"] = agg["volume"] / n_months if n_months else 0
    agg["일평균"] = agg["volume"] / n_days if n_days else 0
    agg["관정당일평균"] = agg["일평균"] / agg["n_wells"].replace(0, pd.NA)

    # ── 최대/최소 사용월 파생값
    def _days_in(yr, mo):
        if pd.isna(yr) or pd.isna(mo):
            return None
        return calendar.monthrange(int(yr), int(mo))[1]

    def _label(yr, mo):
        if pd.isna(yr) or pd.isna(mo):
            return "-"
        return f"{int(yr)}-{int(mo):02d}"

    agg["max_days"] = agg.apply(lambda r: _days_in(r["max_year"], r["max_month"]), axis=1)
    agg["max_label"] = agg.apply(lambda r: _label(r["max_year"], r["max_month"]), axis=1)
    agg["max_daily"] = agg["max_volume"] / agg["max_days"].replace(0, pd.NA)
    agg["max_per_well_daily"] = agg["max_daily"] / agg["n_wells"].replace(0, pd.NA)

    agg["min_days"] = agg.apply(lambda r: _days_in(r["min_year"], r["min_month"]), axis=1)
    agg["min_label"] = agg.apply(lambda r: _label(r["min_year"], r["min_month"]), axis=1)
    agg["min_daily"] = agg["min_volume"] / agg["min_days"].replace(0, pd.NA)
    agg["min_per_well_daily"] = agg["min_daily"] / agg["n_wells"].replace(0, pd.NA)

    agg = agg.sort_values("volume", ascending=False).reset_index(drop=True)

    # ── 합계 행
    #   pd.concat 으로 「all-NA 컬럼이 포함된 DataFrame」을 합치면 pandas 2.2+
    #   FutureWarning 이 나오므로, agg.loc 으로 한 행 추가하는 방식 사용.
    #   dict 에 없는 컬럼(max/min 의 수치들)은 pandas 가 NaN 으로 자동 채움 —
    #   기존 컬럼 dtype 이 보존되어 경고 없음.
    total_wells = int(agg["n_wells"].sum())
    total_vol = float(agg["volume"].sum())
    agg.loc[len(agg)] = {
        group_col: "합계",
        "n_wells": total_wells,
        "volume": total_vol,
        "월평균": total_vol / n_months if n_months else 0,
        "일평균": total_vol / n_days if n_days else 0,
        "관정당일평균": (total_vol / n_days / total_wells) if (n_days and total_wells) else 0,
        "max_label": "-",
        "min_label": "-",
    }

    # ── HTML 테이블 렌더 (multi-level header + 콤마 + 우측 정렬)
    st.markdown(
        _build_stats_table_html(agg, group_col, group_label, yr_range),
        unsafe_allow_html=True,
    )


def _fmt_int(v) -> str:
    """수치 → 콤마 정수 문자열 (NaN/None → '-')."""
    if v is None or (isinstance(v, float) and pd.isna(v)) or pd.isna(v):
        return "-"
    try:
        return f"{int(round(float(v))):,}"
    except (TypeError, ValueError):
        return str(v)


def _build_stats_table_html(
    agg: pd.DataFrame,
    group_col: str,
    group_label: str,
    yr_range: tuple[int, int],
) -> str:
    """집계 통계 표 — 2단 헤더 (평균 · 최대 · 최소) HTML 테이블.

    스타일:
      - 첫 행 카테고리: 평균/최대/최소 (분석기간 포함)
      - 둘째 행: 단축 컬럼명
      - 그룹 라벨 컬럼·관정 수: 중앙정렬
      - 수치 컬럼: 콤마 + 우측 정렬
    """
    yr_label = _yr_label(yr_range)

    css = """
    <style>
    .ag-stats {
        width: 100%; border-collapse: collapse;
        font-size: 11.5px; color: #1a1a18;
        border: 0.5px solid rgba(26,26,24,0.18);
        margin: 4px 0 8px;
    }
    .ag-stats th, .ag-stats td {
        padding: 5px 8px;
        border: 0.5px solid rgba(26,26,24,0.10);
        white-space: nowrap;
    }
    .ag-stats thead tr.cat-row th {
        background: #185fa5; color: #ffffff;
        font-weight: 600; font-size: 12px;
        text-align: center;
    }
    .ag-stats thead tr.col-row th {
        background: #e6f1fb; color: #185fa5;
        font-weight: 600; text-align: center;
    }
    .ag-stats td.num {
        text-align: right;
        font-variant-numeric: tabular-nums;
    }
    .ag-stats td.cnt {
        /* 관정 수 — 중앙정렬 */
        text-align: center;
        font-variant-numeric: tabular-nums;
    }
    .ag-stats td.lbl {
        text-align: center;
    }
    .ag-stats td.grp {
        /* 리/읍면 등 그룹 이름 — 중앙정렬 */
        text-align: center;
        font-weight: 500;
    }
    .ag-stats tbody tr:nth-child(even) { background: #fafaf8; }
    .ag-stats tbody tr.total-row {
        background: #d7e6f5 !important;
        font-weight: 700; color: #185fa5;
    }
    .ag-stats tbody tr.total-row td.num,
    .ag-stats tbody tr.total-row td.cnt { color: #185fa5; }
    /* 카테고리 경계선 강조 */
    .ag-stats th.sep, .ag-stats td.sep {
        border-left: 2px solid #185fa5 !important;
    }
    </style>
    """

    body_rows = []
    for _, r in agg.iterrows():
        is_total = (str(r.get(group_col, "")) == "합계")
        cls = "total-row" if is_total else ""
        body_rows.append(f'<tr class="{cls}">')
        # 그룹 라벨 — 중앙정렬
        body_rows.append(f'<td class="grp">{r.get(group_col, "")}</td>')
        # 관정 수 — 중앙정렬
        body_rows.append(f'<td class="cnt">{_fmt_int(r.get("n_wells"))}</td>')
        # ── 평균 4컬럼 — 우측정렬
        body_rows.append(f'<td class="num sep">{_fmt_int(r.get("volume"))}</td>')
        body_rows.append(f'<td class="num">{_fmt_int(r.get("월평균"))}</td>')
        body_rows.append(f'<td class="num">{_fmt_int(r.get("일평균"))}</td>')
        body_rows.append(f'<td class="num">{_fmt_int(r.get("관정당일평균"))}</td>')
        # ── 최대 4컬럼
        body_rows.append(f'<td class="lbl sep">{r.get("max_label", "-")}</td>')
        body_rows.append(f'<td class="num">{_fmt_int(r.get("max_volume"))}</td>')
        body_rows.append(f'<td class="num">{_fmt_int(r.get("max_daily"))}</td>')
        body_rows.append(f'<td class="num">{_fmt_int(r.get("max_per_well_daily"))}</td>')
        # ── 최소 4컬럼
        body_rows.append(f'<td class="lbl sep">{r.get("min_label", "-")}</td>')
        body_rows.append(f'<td class="num">{_fmt_int(r.get("min_volume"))}</td>')
        body_rows.append(f'<td class="num">{_fmt_int(r.get("min_daily"))}</td>')
        body_rows.append(f'<td class="num">{_fmt_int(r.get("min_per_well_daily"))}</td>')
        body_rows.append("</tr>")

    table = (
        css
        + '<table class="ag-stats">'
        + "<thead>"
        # 1행: 카테고리 (rowspan=2 셀: 그룹라벨, 관정 수) + 기간 포함
        + '<tr class="cat-row">'
        + f'<th rowspan="2" style="vertical-align:middle;background:#0a316e;">{group_label}</th>'
        + '<th rowspan="2" style="vertical-align:middle;background:#0a316e;">관정 수</th>'
        + f'<th colspan="4" class="sep">평균 ({yr_label})</th>'
        + f'<th colspan="4" class="sep">최대 사용월 ({yr_label})</th>'
        + f'<th colspan="4" class="sep">최소 사용월 ({yr_label})</th>'
        + "</tr>"
        # 2행: 단축 컬럼명
        + '<tr class="col-row">'
        + '<th class="sep">총량 (㎥)</th>'
        + '<th>월평균 (㎥)</th>'
        + '<th>일평균 (㎥)</th>'
        + '<th>관정당 (㎥)</th>'
        + '<th class="sep">월</th>'
        + '<th>사용량 (㎥)</th>'
        + '<th>일평균 (㎥)</th>'
        + '<th>관정당 (㎥)</th>'
        + '<th class="sep">월</th>'
        + '<th>사용량 (㎥)</th>'
        + '<th>일평균 (㎥)</th>'
        + '<th>관정당 (㎥)</th>'
        + "</tr>"
        + "</thead>"
        + "<tbody>" + "".join(body_rows) + "</tbody>"
        + "</table>"
    )
    return table


# ------------------------------------------------------------------------------
def _render_monthly_box(merged: pd.DataFrame, level: str) -> None:
    """그룹별 월별 이용량 분포 박스 플롯.

    각 박스: (그룹) × (분석기간의 모든 월). y = volume_m3.
    """
    grp_info = _LEVEL_TO_GROUP.get(level)
    if grp_info is None:
        return
    group_col, group_label = grp_info

    if group_col not in merged.columns:
        return

    # 동지역 처리 — well_eup 그룹은 '동지역', well_ri 는 동으로 fallback
    sub = _normalize_group_values(merged, group_col)
    sub = sub[sub["volume_m3"].notna() & (sub["volume_m3"] > 0)]
    sub = sub[sub[group_col].notna()]
    sub[group_col] = sub[group_col].astype(str).str.strip()
    sub = sub[sub[group_col] != ""]
    if group_col == "authority":
        sub[group_col] = (
            sub[group_col].map(ag_well_metrics.AUTHORITY_KOR).fillna(sub[group_col])
        )
    if sub.empty:
        st.caption("박스 플롯에 표시할 자료가 없습니다.")
        return

    # 그룹 정렬: 이용량 합 내림차순 (상위 30 만 표시 — 그룹 너무 많으면 가독성 ↓)
    order = (
        sub.groupby(group_col)["volume_m3"].sum()
           .sort_values(ascending=False)
           .head(30).index.tolist()
    )
    sub = sub[sub[group_col].isin(order)]

    fig = go.Figure()
    for grp_val in order:
        g = sub[sub[group_col] == grp_val]
        fig.add_trace(go.Box(
            y=g["volume_m3"],
            name=str(grp_val),
            boxpoints="outliers",
            marker=dict(size=4),
            line=dict(width=1.2),
        ))
    fig.update_layout(
        height=320,
        margin=dict(l=10, r=10, t=20, b=80),
        plot_bgcolor="white",
        showlegend=False,
    )
    fig.update_xaxes(title=group_label, tickfont=dict(size=10), tickangle=-30)
    fig.update_yaxes(title="월별 이용량 (㎥)", tickfont=dict(size=9))
    st.plotly_chart(fig, use_container_width=True)


# ------------------------------------------------------------------------------
def _render_month_box(df: pd.DataFrame) -> None:
    """1월~12월 월별 이용량 분포 박스 플롯.

    각 박스: 그 월(예: 7월)에 대한 (관정 × 연도) 합집합의 volume 분포.
    분석기간 동안 계절성 패턴을 한눈에 확인.
    """
    if df.empty:
        return
    sub = df[df["volume_m3"].notna() & (df["volume_m3"] > 0)].copy()
    sub = sub[sub["month"].between(1, 12)]
    if sub.empty:
        st.caption("월별 분포에 표시할 자료가 없습니다.")
        return

    fig = go.Figure()
    for m in range(1, 13):
        gm = sub[sub["month"] == m]
        if gm.empty:
            continue
        fig.add_trace(go.Box(
            y=gm["volume_m3"],
            name=f"{m}월",
            boxpoints="outliers",
            marker=dict(size=4, color="#305496"),
            line=dict(width=1.2, color="#305496"),
            fillcolor="#9DC3E6",
        ))
    # 좌우 모두 같은 이용량(㎥) 스케일 표시 — 아래 dual-axis 그래프와 plot 영역 폭 정렬
    fig.update_layout(
        height=320,
        margin=dict(l=10, r=10, t=10, b=40),
        plot_bgcolor="white",
        showlegend=False,
        yaxis=dict(
            title=dict(text="이용량 (㎥)", font=dict(size=11)),
            tickfont=dict(size=9),
            side="left", rangemode="tozero",
        ),
        yaxis2=dict(
            title=dict(text="이용량 (㎥)", font=dict(size=11)),
            tickfont=dict(size=9),
            side="right", overlaying="y", matches="y",
            showgrid=False,
        ),
    )
    fig.update_xaxes(title=None, tickfont=dict(size=10))
    st.plotly_chart(fig, use_container_width=True)


def _select_aws_for_region(df_master_f: pd.DataFrame) -> str | None:
    """선택된 지역(관정 집합)에 가장 적합한 AWS 1개 결정.

    매핑 규칙: 관정 → watershed → AWS (config.WATERSHED_AWS_MAP).
    여러 watershed 가 섞여 있으면 빈도 가장 높은 watershed 의 AWS 선택.

    데이터의 watershed 표기는 "대정수역" 처럼 '수역' 접미사가 붙어 있을 수 있어
    config 의 키 ("대정") 와 맞지 않을 수 있다 → '수역' 제거 후에도 매칭 시도.
    """
    if df_master_f.empty or "watershed" not in df_master_f.columns:
        return None
    ws_counts = df_master_f["watershed"].dropna().value_counts()
    if ws_counts.empty:
        return None

    aws_tally: dict[str, int] = {}
    for ws, cnt in ws_counts.items():
        raw = str(ws).strip()
        # 1차: raw 매칭, 2차: '수역' 접미사 제거 후 매칭
        candidates = [raw]
        if raw.endswith("수역"):
            candidates.append(raw[:-2])
        elif not raw.endswith("수역"):
            candidates.append(raw + "수역")
        aws_name = None
        for cand in candidates:
            aws_name = config.WATERSHED_AWS_MAP.get(cand)
            if aws_name:
                break
        if aws_name:
            aws_tally[aws_name] = aws_tally.get(aws_name, 0) + int(cnt)

    if not aws_tally:
        return None
    return max(aws_tally.items(), key=lambda kv: kv[1])[0]


def _render_aws_rainfall(
    aws_name: str | None,
    yr_range: tuple[int, int],
    merged: pd.DataFrame,
    usage_y_max: float | None = None,
    daily_permit_by_year: dict[int, float] | None = None,
) -> None:
    """이중 그래프: AWS 월강수량(막대) + 선택 지역 일평균 이용량(선).

    Build 2.7 (2026-05-02):
      - 좌측 강수량 Y축: 0 ~ 200 mm 고정, **dtick=25 → 8칸**
      - 우측 일평균 이용량 Y축:
          · usage_y_max 지정 시 → 그 값을 max 로 + dtick = max/8 (8칸)
          · 미지정 시 → 데이터 max × 1.05 를 max 로, 동일하게 8칸
        둘 다 8 등분이라 좌우 보조선 위치가 일치 (gridline 정렬).
      - 우측 line: 일평균(㎥/일) — 그달 실제 일수로 나눔
      - 막대 두께 약 1/3 (bargap=0.7), 높이 ↑
      - X축 한글 라벨: 연도 변경시 'YY년 M월', 그 외 'M월'
    """
    if not aws_name:
        st.caption("선택 지역에 매핑되는 AWS 가 없어 강수량을 표시할 수 없습니다.")
        return

    asos_df = asos_collector.load_asos_data()
    if asos_df is None or asos_df.empty:
        st.caption("ASOS 강수량 자료를 찾을 수 없습니다.")
        return

    sub = asos_df[asos_df["지점명"] == aws_name].copy()
    if sub.empty:
        st.caption(f"{aws_name} AWS 자료가 없습니다.")
        return

    sub["일시"] = pd.to_datetime(sub["일시"], errors="coerce")
    sub = sub.dropna(subset=["일시"]).copy()
    sub = sub[
        (sub["일시"].dt.year >= yr_range[0])
        & (sub["일시"].dt.year <= yr_range[1])
    ]
    if sub.empty:
        st.caption(f"{aws_name} AWS — 선택 기간 자료가 없습니다.")
        return

    # ── 1) 강수량 월별 합계 (AWS)
    sub["_year"] = sub["일시"].dt.year
    sub["_month"] = sub["일시"].dt.month
    rain = (
        sub.groupby(["_year", "_month"])["일강수량(mm)"]
           .sum().reset_index()
    )
    rain.columns = ["year", "month", "rainfall"]
    rain["period"] = pd.to_datetime(
        rain["year"].astype(str) + "-"
        + rain["month"].astype(str).str.zfill(2) + "-01",
        errors="coerce",
    )
    rain = rain.sort_values("period")

    # ── 2) 이용량 월별 합계 → 일평균(㎥/일) 환산 (그달 실제 일수)
    use = (
        merged.groupby(["year", "month"], dropna=False)["volume_m3"]
              .sum().reset_index()
    )
    use["period"] = pd.to_datetime(
        use["year"].astype(str) + "-"
        + use["month"].astype(str).str.zfill(2) + "-01",
        errors="coerce",
    )
    use["days"] = use.apply(
        lambda r: calendar.monthrange(int(r["year"]), int(r["month"]))[1]
        if pd.notna(r["year"]) and pd.notna(r["month"]) else None,
        axis=1,
    )
    use["daily_avg"] = use["volume_m3"] / use["days"]
    use = use.sort_values("period")

    # ── 3) 한글 X축 tick — 연도 변경 시에만 'YY년 M월'
    all_periods = sorted(set(rain["period"]).union(use["period"]))
    tick_vals = list(all_periods)
    tick_text: list[str] = []
    prev_year = None
    for p in tick_vals:
        yr = p.year
        mo = p.month
        if yr != prev_year:
            tick_text.append(f"{yr % 100}년 {mo}월")
            prev_year = yr
        else:
            tick_text.append(f"{mo}월")

    # 강수량 막대는 AWS 지점 색 무관하게 푸른 계열로 통일 (대시보드 톤 일관성)
    aws_color = "#5B9BD5"
    use_color = "#C00000"

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=rain["period"], y=rain["rainfall"],
        marker_color=aws_color,
        name=f"{aws_name} 월강수량 (mm)",
        yaxis="y",
        text=[f"{v:.0f}" for v in rain["rainfall"]],
        textposition="outside", textfont=dict(size=8),
    ))
    fig.add_trace(go.Scatter(
        x=use["period"], y=use["daily_avg"],
        mode="lines+markers",
        name="일평균 이용량 (㎥/일)",
        line=dict(color=use_color, width=2.5),
        marker=dict(size=6, color=use_color),
        yaxis="y2",
    ))

    # ── 연도별 「취수허가량 ÷ 30(㎥/일)」 점선 — 단일 관정 호출 시에만 인자 제공.
    #   각 연도마다 1/1 ~ 12/31 구간을 가로 점선으로, 자료가 없는 연도는 NaN 으로
    #   끊어서(connectgaps=False) 「자료 없음 → 점선 없음」을 보장.
    if daily_permit_by_year:
        permit_x: list = []
        permit_y: list = []
        for y in sorted(daily_permit_by_year.keys()):
            v = daily_permit_by_year[y]
            if v is None or pd.isna(v):
                continue
            try:
                yi = int(y)
            except (TypeError, ValueError):
                continue
            if yi < yr_range[0] or yi > yr_range[1]:
                continue
            permit_x.extend([
                pd.Timestamp(year=yi, month=1, day=1),
                pd.Timestamp(year=yi, month=12, day=31),
                None,
            ])
            permit_y.extend([float(v), float(v), None])

        if permit_x:
            fig.add_trace(go.Scatter(
                x=permit_x, y=permit_y,
                mode="lines",
                name="취수허가량 ÷ 30 (㎥/일)",
                line=dict(color="#7f7f7f", width=1.5, dash="dot"),
                yaxis="y2",
                connectgaps=False,
                hovertemplate="허가량/30: %{y:,.0f} ㎥/일<extra></extra>",
            ))

    # ── y축 (강수량) — 0 ~ 200 mm 고정, dtick=25 → 8칸
    yaxis_kwargs = dict(
        title=dict(text="월강수량 (mm)", font=dict(color=aws_color, size=11)),
        tickfont=dict(color=aws_color, size=9),
        range=[0, 200], dtick=25,
    )

    # ── y2축 (이용량 일평균) — 항상 8칸으로 분할되도록 dtick 산출
    #   → 좌우 Y축 보조선이 같은 픽셀 위치에 그려져 그래프가 깔끔.
    if usage_y_max is None:
        # 데이터 max 기반 자동 산출 (5% 여유) — dtick 을 'nice number' 로 round-up
        import math as _math
        data_max = float(use["daily_avg"].max()) if not use.empty else 1000.0
        if not data_max or pd.isna(data_max):
            data_max = 1000.0
        target = data_max * 1.05
        step_raw = target / 8.0
        if step_raw > 0:
            # 1, 2, 5, 10 × 10^n 중 step_raw 보다 큰 가장 가까운 값
            exp = _math.floor(_math.log10(step_raw))
            base = 10 ** exp
            f = step_raw / base
            if f <= 1: nice = 1
            elif f <= 2: nice = 2
            elif f <= 2.5: nice = 2.5
            elif f <= 5: nice = 5
            else: nice = 10
            step = nice * base
        else:
            step = 1
        usage_y_max_eff = step * 8
    else:
        usage_y_max_eff = float(usage_y_max)

    yaxis2_kwargs = dict(
        title=dict(text="일평균 이용량 (㎥/일)",
                   font=dict(color=use_color, size=11)),
        tickfont=dict(color=use_color, size=9),
        overlaying="y", side="right",
        range=[0, usage_y_max_eff],
        dtick=usage_y_max_eff / 8,
    )

    fig.update_layout(
        height=420,
        margin=dict(l=10, r=10, t=10, b=70),
        plot_bgcolor="white",
        bargap=0.7,
        legend=dict(
            font=dict(size=10), orientation="h",
            yanchor="bottom", y=1.0, xanchor="right", x=1.0,
        ),
        yaxis=yaxis_kwargs,
        yaxis2=yaxis2_kwargs,
    )
    # ── X축 좌·우 여백 최소화: 첫/마지막 막대가 plot 영역 가장자리에 가깝게 붙도록
    #   범위를 첫 period 의 약 ½ 막대 앞 ~ 마지막 period 의 약 ½ 막대 뒤로 명시.
    #   (plotly 기본 auto-range 는 5~10% 의 양쪽 padding 을 자동으로 추가함)
    x_pad = pd.Timedelta(days=12)
    x_range = [all_periods[0] - x_pad, all_periods[-1] + x_pad]

    fig.update_xaxes(
        tickvals=tick_vals,
        ticktext=tick_text,
        tickangle=-45,
        tickfont=dict(size=9),
        title=None,
        range=x_range,
    )
    st.plotly_chart(fig, use_container_width=True)


def _nice_y_max(data_max: float, n_ticks: int = 8) -> float:
    """data_max 보다 큰 「nice number」(1·2·2.5·5 × 10^n) × n_ticks 를 반환.

    여러 차트의 y2 축을 같은 nice max 로 정렬해 시각적 비교를 쉽게 하기 위함.
    """
    if (
        data_max is None or data_max <= 0
        or (isinstance(data_max, float) and pd.isna(data_max))
    ):
        return 0.0
    import math as _math
    target = float(data_max) * 1.05
    step_raw = target / n_ticks
    if step_raw <= 0:
        return 0.0
    exp = _math.floor(_math.log10(step_raw))
    base = 10 ** exp
    f = step_raw / base
    if f <= 1:    nice = 1
    elif f <= 2:  nice = 2
    elif f <= 2.5: nice = 2.5
    elif f <= 5:  nice = 5
    else:         nice = 10
    return nice * base * n_ticks


# 집계단위별 하위 그룹 컬럼: 한 단계 아래로 분해.
#   - 시 단위        → 읍/면/동 (well_eup, 동→'동지역')
#   - 읍/면/동 단위  → 리/동   (well_ri,  ri 가 비고 eup 이 동이면 그 동을 키로)
#   - 리 단위        → 개별 관정 (permit_no)
#   - 제주도 전역    → 시 (well_si) — 옵션
#   - 유역           → watershed — 옵션
_LEVEL_TO_SUBGROUP_COL: dict[str, str] = {
    "제주도 전역": "well_si",
    "도전역":      "well_si",
    "시":          "well_eup",
    "읍면동":      "well_ri",
    "리":          "permit_no",
    "유역":        "watershed",
}


# 다중 라인용 색상 팔레트 (Plotly D3 + 확장 — 12색까지 명확히 구분).
_SUBGROUP_LINE_PALETTE = (
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
    "#aec7e8", "#ffbb78",
)


def _render_subgroup_rainfall_combined(
    level: str,
    loc_sel: dict,
    aws_name: str | None,
    yr_range: tuple[int, int],
    merged: pd.DataFrame,
) -> None:
    """집계단위별 하위그룹 「월별 강수량 · 이용량 비교」 — 1개 통합 차트.

    좌Y축: AWS 월강수량 막대 (0~500mm 고정).
    우Y축: 하위그룹별 일평균 이용량 라인 (그룹 = 다른 색).

    레벨별 분해 규칙:
      - 시:       선택된 시 안의 모든 읍/면/동 (동→'동지역' 통합)
      - 읍면동:   선택된 읍 안의 모든 리/동
      - 리:       선택된 리 안의 모든 관정 (12공 초과 시 상위 12공)
      - 제주도:   전체 시 (제주시·서귀포시)
      - 유역:     전체 watershed
    """
    if merged.empty or level not in _LEVEL_TO_SUBGROUP_COL:
        return
    group_col = _LEVEL_TO_SUBGROUP_COL[level]
    if group_col not in merged.columns:
        return

    # 동지역 정규화 (well_eup / well_ri 케이스)
    work = _normalize_group_values(merged, group_col)

    # 그룹 목록 — 빈/None 제외, 이용량 합 내림차순
    grp_totals = (
        work.groupby(group_col, dropna=False)["volume_m3"]
            .sum().reset_index()
    )
    grp_totals = grp_totals[grp_totals[group_col].notna()]
    grp_totals = grp_totals[grp_totals[group_col].astype(str).str.strip() != ""]
    grp_totals = grp_totals.sort_values("volume_m3", ascending=False)
    if grp_totals.empty:
        return

    truncated = False
    if level == "리" and len(grp_totals) > 12:
        grp_totals = grp_totals.head(12)
        truncated = True

    groups = grp_totals[group_col].tolist()

    # ── 제목 빌드
    si = loc_sel.get("well_si") or ""
    eup = loc_sel.get("well_eup") or ""
    ri = loc_sel.get("well_ri") or ""
    yr_label = _yr_label(yr_range)
    aws_label = aws_name or "(매핑 AWS 없음)"

    if level == "시":
        title_prefix = si if si else "제주도 전역"
        title_suffix = "읍면동"
    elif level == "읍면동":
        title_prefix = " ".join(p for p in (si, eup) if p) or "제주도 전역"
        title_suffix = "리별"
    elif level == "리":
        title_prefix = " ".join(p for p in (si, eup, ri) if p) or "제주도 전역"
        title_suffix = "관정별"
    elif level in ("제주도 전역", "도전역"):
        title_prefix, title_suffix = "제주도 전역", "시별"
    elif level == "유역":
        title_prefix, title_suffix = "제주도 전역", "유역별"
    else:
        title_prefix, title_suffix = "", level

    extra_note = ' <span style="font-size:11px;color:#7a7a76;">(상위 12공)</span>' if truncated else ""
    st.markdown(
        f'<div style="font-size:13px;font-weight:600;color:#185fa5;'
        f'margin-top:14px;">{title_prefix} {title_suffix} 월별 강수량 · 이용량 비교 '
        f'(적용 AWS: <span style="color:#C00000;">{aws_label}</span>) '
        f'({yr_label}){extra_note}</div>',
        unsafe_allow_html=True,
    )

    # ── 강수량 (AWS) 데이터
    if not aws_name:
        st.caption("선택 지역에 매핑되는 AWS 가 없어 강수량을 표시할 수 없습니다.")
        return
    asos_df = asos_collector.load_asos_data()
    if asos_df is None or asos_df.empty:
        st.caption("ASOS 강수량 자료를 찾을 수 없습니다.")
        return
    ras = asos_df[asos_df["지점명"] == aws_name].copy()
    ras["일시"] = pd.to_datetime(ras["일시"], errors="coerce")
    ras = ras.dropna(subset=["일시"])
    ras = ras[
        (ras["일시"].dt.year >= yr_range[0])
        & (ras["일시"].dt.year <= yr_range[1])
    ]
    if ras.empty:
        st.caption(f"{aws_name} AWS — 선택 기간 자료가 없습니다.")
        return
    ras["_year"] = ras["일시"].dt.year
    ras["_month"] = ras["일시"].dt.month
    rain = (
        ras.groupby(["_year", "_month"])["일강수량(mm)"]
           .sum().reset_index()
    )
    rain.columns = ["year", "month", "rainfall"]
    rain["period"] = pd.to_datetime(
        rain["year"].astype(str) + "-"
        + rain["month"].astype(str).str.zfill(2) + "-01",
        errors="coerce",
    )
    rain = rain.sort_values("period")

    # ── 그룹별 일평균 이용량 시계열 빌드
    label_map: dict = {}
    eup_map: dict = {}
    if level == "리":
        if "well_id" in work.columns:
            label_map = (
                work.drop_duplicates("permit_no")
                    .set_index("permit_no")["well_id"].to_dict()
            )
        if "well_eup" in work.columns:
            eup_map = (
                work.drop_duplicates("permit_no")
                    .set_index("permit_no")["well_eup"].to_dict()
            )

    use_traces: list[tuple[str, str, pd.DataFrame]] = []
    use_max = 0.0
    for i, g in enumerate(groups):
        sub_g = work[work[group_col] == g]
        use_g = (
            sub_g.groupby(["year", "month"], dropna=False)["volume_m3"]
                 .sum().reset_index()
        )
        if use_g.empty:
            continue
        use_g["days"] = use_g.apply(
            lambda r: calendar.monthrange(int(r["year"]), int(r["month"]))[1]
            if pd.notna(r["year"]) and pd.notna(r["month"]) else None,
            axis=1,
        )
        use_g["daily_avg"] = use_g["volume_m3"] / use_g["days"]
        use_g["period"] = pd.to_datetime(
            use_g["year"].astype(str) + "-"
            + use_g["month"].astype(str).str.zfill(2) + "-01",
            errors="coerce",
        )
        use_g = use_g.sort_values("period")

        if use_g["daily_avg"].notna().any():
            use_max = max(use_max, float(use_g["daily_avg"].max()))

        if level == "리":
            display_label = label_map.get(g, str(g))
        else:
            display_label = str(g)
        color = _SUBGROUP_LINE_PALETTE[i % len(_SUBGROUP_LINE_PALETTE)]
        use_traces.append((display_label, color, use_g))

    if not use_traces:
        st.caption("표시할 하위 그룹 이용량 자료가 없습니다.")
        return

    # ── X축 tick (한글) — 모든 기간 union
    all_periods_set: set = set(rain["period"])
    for _, _c, ug in use_traces:
        all_periods_set.update(ug["period"])
    all_periods = sorted(p for p in all_periods_set if pd.notna(p))
    tick_text: list[str] = []
    prev_year: int | None = None
    for p in all_periods:
        yr, mo = p.year, p.month
        if yr != prev_year:
            tick_text.append(f"{yr % 100}년 {mo}월")
            prev_year = yr
        else:
            tick_text.append(f"{mo}월")

    aws_color = "#5B9BD5"

    # ── Plotly 차트 빌드
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=rain["period"], y=rain["rainfall"],
        marker_color=aws_color,
        name=f"{aws_name} 월강수량 (mm)",
        yaxis="y",
    ))
    for label, color, ug in use_traces:
        fig.add_trace(go.Scatter(
            x=ug["period"], y=ug["daily_avg"],
            mode="lines+markers",
            name=label,
            line=dict(color=color, width=1.6),
            marker=dict(size=4, color=color),
            yaxis="y2",
            hovertemplate=f"<b>{label}</b><br>%{{x|%Y-%m}}: %{{y:,.0f}} ㎥/일<extra></extra>",
        ))

    # ── y축 (강수량) — 0 ~ 500 mm 고정, dtick=50 → 10 ticks
    yaxis_kwargs = dict(
        title=dict(text="월강수량 (mm)", font=dict(color=aws_color, size=11)),
        tickfont=dict(color=aws_color, size=9),
        range=[0, 500], dtick=50,
    )

    # ── y2축 (이용량) — 데이터 max 기반 nice scale, 10 ticks 정렬
    nice_max = _nice_y_max(use_max, n_ticks=10) if use_max > 0 else 100.0
    yaxis2_kwargs = dict(
        title=dict(text="일평균 이용량 (㎥/일)",
                   font=dict(color="#1a1a18", size=11)),
        tickfont=dict(color="#1a1a18", size=9),
        overlaying="y", side="right",
        range=[0, nice_max],
        dtick=nice_max / 10,
    )

    fig.update_layout(
        height=620,
        margin=dict(l=10, r=10, t=10, b=80),
        plot_bgcolor="white",
        bargap=0.7,
        legend=dict(
            font=dict(size=10), orientation="h",
            yanchor="bottom", y=1.0, xanchor="left", x=0.0,
        ),
        yaxis=yaxis_kwargs,
        yaxis2=yaxis2_kwargs,
        hovermode="x unified",
    )

    x_pad = pd.Timedelta(days=12)
    x_range = [all_periods[0] - x_pad, all_periods[-1] + x_pad]
    fig.update_xaxes(
        tickvals=all_periods,
        ticktext=tick_text,
        tickangle=-45,
        tickfont=dict(size=9),
        title=None,
        range=x_range,
    )
    st.plotly_chart(fig, use_container_width=True)


