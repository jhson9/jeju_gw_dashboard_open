# ==============================================================================
#  파일명: src/dashboard/tabs/tab12_ag_usage.py  —  Build 2.2
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
from src.analysis import ag_well_loader, ag_well_metrics, anomaly_detection
from src.collectors import asos_collector
from src.dashboard import ag_well_helpers, theme
from src.dashboard.quit_helper import quit_button
from src.utils.csv_safe import sanitize_dataframe


# 공용 fragment-only rerun 헬퍼 (컨텍스트 가드 포함). ag_well_helpers 참조.
_fragment_rerun = ag_well_helpers.fragment_rerun


# ==============================================================================
#  ■ 헬퍼 + 상수 + 캐시 — _tab12_helpers.py 로 분리 (2026-05-09).
# ==============================================================================
from src.dashboard.tabs._tab12_helpers import (   # noqa: E402
    _AGG_LABELS,
    _LEVEL_TO_GROUP,
    _LEVEL_TO_SUBGROUP_COL,
    _DEFAULT_MAP_ZOOM,
    _DEFAULT_MAP_CENTER,
    _PERMIT_PALETTE,
    _SUBGROUP_LINE_PALETTE,
    _cached_asos_data,
    _maybe_recenter_usage_map,
    _normalize_group_values,
    _stats_filter_for_level,
    _yr_label,
    _location_label,
    _stats_title_scope,
    _yearly_permit_for_well,
    _fmt_int,
    _nice_y_max,
)

from src.dashboard.tabs._tab12_well_select import (   # noqa: E402
    _render_well_selection_bar,
    _render_well_search_input,
    _render_map_header_with_search,
)

from src.dashboard.tabs._tab12_map import (   # noqa: E402
    _render_usage_map,
    _render_monthly_usage_map,
)

from src.dashboard.tabs._tab12_well_detail import (   # noqa: E402
    _render_well_detail,
    _render_yearly_permit_table,
    _render_well_monthly_table,
)

from src.dashboard.tabs._tab12_group_stats import (   # noqa: E402
    _render_group_stats,
    _build_stats_table_html,
    _render_monthly_box,
    _render_month_box,
)

from src.dashboard.tabs._tab12_aws import (   # noqa: E402
    _select_aws_for_region,
    _render_aws_rainfall,
    _render_subgroup_rainfall_combined,
)


# ──────────────────────────────────────────────────────────────────
#  메인 render — @st.fragment 로 격리해 탭 튕김 차단.
# ──────────────────────────────────────────────────────────────────
@st.fragment
def render() -> None:
    _t, _q = st.columns([10, 1])
    with _t:
        st.markdown(
            '<p class="tab-title" style="margin:0;">12.이용량 분석</p>',
            unsafe_allow_html=True,
        )
    with _q:
        quit_button("quit_in_tab7")

    # tab6 검색·선택한 관정을 tab7 이용량 분석으로 자동 전달 — 워크플로우 연결.
    # tab7 에서 별도 선택이 없을 때만 1회 동기화 (이후 tab7 자체 선택은 보존).
    if (not st.session_state.get("usage_selected_permit")
            and st.session_state.get("search_selected_permit")):
        st.session_state["usage_selected_permit"] = (
            st.session_state["search_selected_permit"]
        )

    df_master = ag_well_loader.load_master(active_only=True)
    df_usage = ag_well_loader.load_usage_long()

    if df_usage.empty:
        st.warning("이용량 자료를 찾을 수 없습니다 (usage/usage_montly_*.csv).")
        return

    # ── 이상 의심 데이터 카운트 (수동 검토 안내) — 집계는 그대로 진행
    _anom = anomaly_detection.summarize_usage_anomalies(df_usage)
    if _anom["anomaly_rows"] > 0:
        _reason_str = " · ".join(
            f"{r}({c})" for r, c in _anom["by_reason"].items()
        )
        st.caption(
            f"⚠ 이상 의심 {_anom['anomaly_rows']:,}건 / "
            f"{_anom['total_rows']:,}건 (관정 {_anom['affected_permits']}곳) "
            f"— {_reason_str}. 표기만 (집계는 그대로 포함)."
        )

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
    # 사용자 요청 2026-05-19: 분모 N 을 "선택 기간 내 이용량 합계>0 관정"
    # 으로 한정 — ag_well_metrics.active_user_permits 와 동일 정책.
    n_registered = merged["permit_no"].nunique()

    # 농업용관정 수 (사용자 요청 2026-05-27): '사용(이용량>0)' 이 아니라
    # 폐공되지 않고 살아있는(active=운영중) 관정을 마지막연도 기준으로 전부
    # 포함 — 이용량 유무와 무관. 제주 본도 외 도서(우도·추자)는 제외.
    from src.dashboard.figures._dual_zone_common.normalize import (
        EXCLUDED_ISLAND_EUP,
    )
    _alive = df_master_f
    if "active" in _alive.columns:
        _alive = _alive[_alive["active"]]
    if "well_eup" in _alive.columns:
        _alive = _alive[~_alive["well_eup"].astype(str).str.strip()
                        .isin(EXCLUDED_ISLAND_EUP)]
    n_ag_wells = int(_alive["permit_no"].nunique())

    total_vol = float(merged["volume_m3"].sum(skipna=True))
    avg_monthly = total_vol / n_months_in_period if n_months_in_period else 0.0
    avg_daily = total_vol / n_days_in_period if n_days_in_period else 0.0
    avg_per_well_daily = avg_daily / n_ag_wells if n_ag_wells else 0.0

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

    # ── KPI 박스 5개 — ⑧ 통계 요약 헬퍼로 통일 (사용자 결정, 2026-05-08)
    #   render_period_kpi_card 단일 그룹 모드 (title="" → 헤더 영역 생략).
    #   안전 가드: st.columns(5) 안에서 각 col 별 렌더 → stHorizontalBlock
    #              으로 감싸져 row-pair-tight 셀렉터 매치 안 됨.
    cards = [
        ("농업용관정",    f"{n_ag_wells:,}공",               "폐공 제외 · 운영중"),
        ("총 이용량",      f"{total_vol:,.0f} ㎥",            "분석기간 합계"),
        ("월평균",         f"{avg_monthly:,.0f} ㎥/월",       "월별 평균"),
        ("일평균",         f"{avg_daily:,.0f} ㎥/일",         "일별 평균"),
        ("관정당 일평균",  f"{avg_per_well_daily:,.1f} ㎥/일", f"{n_ag_wells:,}공 평균"),
    ]
    accent_colors = [
        theme.COLOR_TEXT_INFO,           # 1) 관정 수 — 정보 파랑
        theme.COLOR_TEXT_INFO,           # 2) 총 이용량 — 정보 파랑
        theme.PALETTE_ACCENT[3],         # 3) 월평균 — 보조 파랑 (#305496)
        theme.PALETTE_ACCENT[3],         # 4) 일평균 — 보조 파랑
        theme.PALETTE_ACCENT[4],         # 5) 관정당 일평균 — 다크레드 (#C00000)
    ]
    cols = st.columns(5)
    for i, (col, (title, big, sub)) in enumerate(zip(cols, cards)):
        theme.render_period_kpi_card(
            title="",
            groups=[(title, big, sub)],
            accent=accent_colors[i],
            is_base=True,
            container=col,
        )

    # ── ③ 지도 (이용량 비례 마커 + 톤)
    st.markdown(
        '<hr style="margin:10px 0;border:none;'
        'border-top:0.5px solid rgba(26,26,24,0.15);">',
        unsafe_allow_html=True,
    )
    # 2026-05-17 사용자 요청: 검색 input 을 지도 헤더 라인 오른쪽 끝으로 이동.
    # 헤더 좌측은 기존 subsection-title, 우측은 placeholder 가 있는 검색창.
    _header_html = (
        f'<p class="subsection-title" style="margin:6px 0;">'
        f'관정 위치 · 이용량 분포 — '
        f'마커 크기 · 톤은 {yr_range[0]}~{yr_range[1]} 합계에 비례'
        f'</p>'
    )
    _render_map_header_with_search(df_master, title_html=_header_html)
    _render_usage_map(df_master_f, merged, n_days_in_period)

    # ── 선택 관정 헤더 + 선택 해제 — 검색 input 은 위 헤더 라인으로 이동.
    sel_permit = st.session_state.get("usage_selected_permit")
    _render_well_selection_bar(df_master, sel_permit, include_search=False)
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
        f'<div class="subsection-title" style="color:var(--color-text-info);'
        f'margin-top:14px;">{scope_label} 이용량 통계 ({yr_label})</div>',
        unsafe_allow_html=True,
    )
    _render_group_stats(
        merged_stats, level, n_days_in_period, n_months_in_period, yr_range,
    )

    # ── ⑤ 박스 플롯 — 그룹별 이용량 분포
    st.markdown(
        f'<div class="subsection-title" style="color:var(--color-text-info);'
        f'margin-top:14px;">{scope_label} 지역별 이용량 분포 ({yr_label})</div>',
        unsafe_allow_html=True,
    )
    _render_monthly_box(merged_stats, level)

    # ── ⑥ 박스 플롯 — 1월~12월 월별 이용량 분포 (전 분석기간 통합)
    st.markdown(
        f'<div class="subsection-title" style="color:var(--color-text-info);'
        f'margin-top:14px;">{scope_label} 월별 이용량 분포 (Box Plot) '
        f'({yr_label})</div>',
        unsafe_allow_html=True,
    )
    _render_month_box(merged)

    # ── ⑦ AWS 월별 강수량 + 지역 월별 이용량 (이중축)
    aws_name = _select_aws_for_region(df_master_f)
    aws_label = aws_name or "(선택 지역에 해당하는 AWS 없음)"
    st.markdown(
        f'<div class="subsection-title" style="color:var(--color-text-info);'
        f'margin-top:14px;">{scope_label} 월별 강수량 · 이용량 비교 '
        f'(적용 AWS: <span style="color:var(--color-accent-darkred);">{aws_label}</span>) '
        f'({yr_label})</div>',
        unsafe_allow_html=True,
    )
    _render_aws_rainfall(aws_name, yr_range, merged)

    # ── ⑦ 집계단위별 하위그룹 「월별 강수량 · 이용량 비교」 — 1개 통합 차트.
    #   시 → 읍면동, 읍면동 → 리, 리 → 관정 단위로 한 단계 분해, 다중 라인.
    _render_subgroup_rainfall_combined(level, loc_sel, aws_name, yr_range, merged)

    # ── ⑧ 월별 일평균 이용량 지도 — 연·월 슬라이더로 시간변화 탐색.
    #   사용자가 줌인한 위치를 고정한 채 슬라이더만 움직이면 주변 관정의
    #   월별 일평균 사용량 변화를 직관적으로 비교할 수 있다.
    st.markdown(
        f'<div class="subsection-title" style="color:var(--color-text-info);'
        f'margin-top:14px;">월별 일평균 이용량 지도 — '
        f'연·월 슬라이더로 관정별 일평균 변화 탐색'
        f'<span style="margin-left:6px;font-size:15px;font-weight:500;'
        f'color:var(--color-text-secondary);">(지도 줌·중심 유지 · 위 지도와 별도)</span>'
        f'</div>',
        unsafe_allow_html=True,
    )
    _render_monthly_usage_map(df_master_f, df_usage, yr_min, yr_max)

    # ── 다운로드
    # P-fix (2026-05-29): CSV Formula Injection 방어 — 문자열 컬럼 sanitize.
    # `=cmd|...`, `+@...` 등으로 시작하는 셀은 single quote 로 회피하여
    # Excel 이 수식으로 해석하지 못하도록 한다. 숫자/날짜 컬럼은 건드리지 않음.
    with st.expander("📥 데이터 내보내기 (CSV)"):
        st.download_button(
            "필터링된 long format 내려받기",
            data=sanitize_dataframe(merged).to_csv(index=False).encode("utf-8-sig"),
            file_name=f"ag_usage_{yr_range[0]}_{yr_range[1]}.csv",
            mime="text/csv",
            # MediaFileStorageError 방지 — 위젯 ID 안정화 (호소 #7)
            key="tab12_ag_usage_csv",
        )

        # 이상 의심 데이터 별도 다운로드 — 헤더 캡션의 ⚠ 카운트와 동일 출처.
        # 수동 검토용. yr_range 필터 적용 안 함 (전 기간 이상값을 한 번에).
        if "is_anomaly" in df_usage.columns:
            _anom_df = df_usage[df_usage["is_anomaly"]]
            if not _anom_df.empty:
                st.download_button(
                    f"⚠ 이상 의심 {len(_anom_df):,}건 내려받기 "
                    f"(전 기간 · 수동 검토용)",
                    data=sanitize_dataframe(_anom_df).to_csv(index=False).encode("utf-8-sig"),
                    file_name="ag_usage_anomalies_all.csv",
                    mime="text/csv",
                    key="tab12_ag_usage_anomalies_csv",
                    help=(
                        "헤더의 ⚠ 카운트와 동일한 행을 CSV 로 내보냄. "
                        "음수 이용량 / 월 1억㎥ 초과 / 미래 연도 (anomaly_reason "
                        "컬럼에 사유 표기). 집계에는 그대로 포함된 상태."
                    ),
                )


# P3-4 (2026-05-29): _LEVEL_TO_SUBGROUP_COL 중복 정의 제거.
# 단일 진실 원천은 _tab12_helpers._LEVEL_TO_SUBGROUP_COL — 본 모듈은 L48 에서 import.
