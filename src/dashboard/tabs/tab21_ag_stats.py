# ==============================================================================
#  파일명: src/dashboard/tabs/tab21_ag_stats.py  —  Build 2.2
#  탭: ⑧ 통계·요약 (KPI 보드)
# ------------------------------------------------------------------------------
#  Build 2.2 (2026-05-04):
#    1) 상단 관정현황: '수역 수' 제거 → 3셀(활성/제주시/서귀포시).
#    2) 기준/직전 2칸 → 3개년(기준·기준-1·기준-2) 3칸 비교, 세로 스택 KPI.
#    3) 각 연도 칸 KPI 4종:
#       · 총 이용량                (caption: 총 취수허가량)
#       · 관정별 평균 일이용량     (caption: 중앙값)
#       · 평균 사용률 (관정별 산술평균)  (caption: 중앙값)
#       · 수질 부적합
#       → 취수허가 초과 셀은 제거.
#    4) 추이 그래프(연/월)의 라인을 '평균 사용률' → '4개 AWS 평균 강수량(mm)'
#       으로 변경. 우측 y축은 강수량(mm).
# ==============================================================================

from __future__ import annotations

import calendar

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import config
from src.analysis import ag_well_loader, ag_well_metrics, effective_rainfall
from src.dashboard import theme
from src.dashboard.quit_helper import quit_button


PERIOD_YEAR  = "년단위"
PERIOD_MONTH = "월단위"

CITY_COLOR = {
    "제주시":   config.AG_PALETTE["jeju"],
    "서귀포시": config.AG_PALETTE["seogwipo"],
}
AUTH_TO_CITY = {"jeju": "제주시", "seogwipo": "서귀포시"}

RAIN_LINE_COLOR = theme.COLOR_TEXT_INFO   # 강수량 라인 색상 (제주시 톤)
CARD_ACCENT     = config.AG_PALETTE["jeju"]   # #305496 — 농업용 관정 컨텍스트의 대표 색

# 수질 항목 단축명 (수질 부적합 카드 캡션용 — config.kor 보다 짧고 직관적)
QUALITY_SHORT_NAMES = {
    "ammonia_n": "암모니아",
    "nitrate_n": "질산",
    "pH":        "pH",
    "chloride":  "염소",
    "EC":        "EC",
}


# 로컬 _rgba_hex 헬퍼는 theme.hex_alpha 와 동일 → 제거 (2026-05-09 디자인 시스템 정리).


# ------------------------------------------------------------------------------
#  ■ 시별 자료 균형 필터
#  -------------------------------------------------------------------
#  연(또는 월) 단위로 (제주시, 서귀포시) 두 도시의 합계를 비교해 한쪽이
#  비어 있거나 30% 이하일 때 해당 기간을 누락 자료로 간주하고 제외한다.
#  Why: 제주시 옛 자료가 일부 연도에서 누락 또는 분기단위 역산만으로 채워져
#  비교 그래프에 큰 왜곡을 만든다. 임계 30% 는 사용자 협의 기준.
# ------------------------------------------------------------------------------
CITY_RATIO_MIN = 0.30


def _filter_balanced_periods(
    pivot: pd.DataFrame,
    city_a: str = "제주시",
    city_b: str = "서귀포시",
    ratio_min: float = CITY_RATIO_MIN,
) -> list:
    """pivot.index 중 (city_a, city_b) 합계가 한쪽이라도 0 이거나
    min/max ≤ ratio_min 인 것은 제외한 인덱스 리스트 반환."""
    valid = []
    for idx in pivot.index:
        a = float(pivot.at[idx, city_a]) if city_a in pivot.columns else 0.0
        b = float(pivot.at[idx, city_b]) if city_b in pivot.columns else 0.0
        if a <= 0 or b <= 0:
            continue
        if min(a, b) / max(a, b) <= ratio_min:
            continue
        valid.append(idx)
    return valid


# ------------------------------------------------------------------------------
#  ■ 기간 헬퍼
# ------------------------------------------------------------------------------
def _shift_period(year: int, month: int | None, steps: int) -> tuple[int, int | None]:
    """기준에서 -steps 이동한 (연·월). steps>0 이면 과거로."""
    if month is None:
        return (year - steps, None)
    idx = year * 12 + (month - 1) - steps
    return (idx // 12, (idx % 12) + 1)


def _period_label(year: int, month: int | None) -> str:
    return f"{year}년" if month is None else f"{year}년 {month}월"


def _quality_period_label(year: int, month: int | None) -> str:
    if month is None:
        return f"{year}년"
    half = "상반기" if month <= 6 else "하반기"
    return f"{year}년 {half}"


def _days_in_period(year: int, month: int | None) -> int:
    if month is None:
        return 366 if calendar.isleap(year) else 365
    return calendar.monthrange(year, month)[1]


def _filter_usage(df_usage: pd.DataFrame, year: int, month: int | None) -> pd.DataFrame:
    if df_usage.empty:
        return df_usage
    sub = df_usage[df_usage["year"] == year]
    if month is not None:
        sub = sub[sub["month"] == month]
    return sub


def _filter_quality(df_qual: pd.DataFrame, year: int, month: int | None) -> pd.DataFrame:
    """수질은 반기 단위. month 1~6 → '상', 7~12 → '하'."""
    if df_qual.empty:
        return df_qual
    sub = df_qual[df_qual["year"] == year]
    if month is not None and "half" in sub.columns:
        target_half = "상" if month <= 6 else "하"
        sub = sub[sub["half"] == target_half]
    return sub


# ------------------------------------------------------------------------------
#  ■ 관정별 사용률·일이용량 통계
# ------------------------------------------------------------------------------
def _per_well_usage_rate(sub_u: pd.DataFrame) -> pd.Series:
    """기간 내 '관정별 사용률(%) = sum(이용량)/sum(취수허가량)*100' 시리즈.

    사용자 요청 2026-05-19: 이용량 합계=0 관정은 시리즈에서 제외 → median/mean
    분모에 미포함.
    """
    if sub_u.empty:
        return pd.Series(dtype=float)
    g = sub_u.groupby("permit_no").agg(
        vol=("volume_m3", "sum"),
        perm=("permit_m3m", "sum"),
    )
    mask = (g["perm"] > 0) & g["vol"].notna() & (g["vol"] > 0)
    rate = pd.Series(index=g.index, dtype=float)
    rate.loc[mask] = g.loc[mask, "vol"] / g.loc[mask, "perm"] * 100
    return rate.dropna()


def _per_well_daily_usage(sub_u: pd.DataFrame, days: int) -> pd.Series:
    """기간 내 '관정별 일이용량 = sum(이용량)/days' 시리즈.

    사용자 요청 2026-05-19: 이용량 합계=0 관정 제외.
    """
    if sub_u.empty:
        return pd.Series(dtype=float)
    per_well = sub_u.groupby("permit_no")["volume_m3"].sum()
    per_well = per_well[per_well > 0]
    return (per_well / days).dropna()


def _compute_period_kpis(
    df_usage: pd.DataFrame,
    df_qual: pd.DataFrame,
    year: int,
    month: int | None,
) -> dict:
    """기간(연 또는 연·월)별 KPI."""
    sub_u = _filter_usage(df_usage, year, month)
    days  = _days_in_period(year, month)

    # 2026-05-28 P2-1: 모집단 정책 100㎥/year 적용 — Tab23 KPI/지도와 일치.
    # filter_population_by_annual_usage 가 (permit, year) 단위로 100㎥ 미만 행을
    # 사전 제거하므로, total_vol/n_wells 모두 같은 집합에서 산출되어 분모·분자가
    # 자동 일치한다.
    from src.analysis import ag_well_metrics as _agm
    sub_u_pop = _agm.filter_population_by_annual_usage(sub_u)

    total_vol    = float(sub_u_pop["volume_m3"].sum(skipna=True)) if not sub_u_pop.empty else 0.0
    total_permit = float(sub_u_pop["permit_m3m"].sum(skipna=True)) if not sub_u_pop.empty else 0.0

    # 관정 수: 모집단 정책을 통과한 (permit, year) 의 unique permit_no
    if not sub_u_pop.empty:
        n_wells = int(sub_u_pop["permit_no"].astype(str).nunique())
    else:
        n_wells = 0

    daily_avg = (total_vol / n_wells / days) if n_wells > 0 else None
    daily_per_well = _per_well_daily_usage(sub_u_pop, days)
    daily_median = float(daily_per_well.median()) if not daily_per_well.empty else None

    rate_per_well = _per_well_usage_rate(sub_u)
    rate_mean   = float(rate_per_well.mean())   if not rate_per_well.empty else None
    rate_median = float(rate_per_well.median()) if not rate_per_well.empty else None

    sub_q = _filter_quality(df_qual, year, month)
    flag_cols = [c for c in sub_q.columns if c.endswith("_exceed")]
    qual_exceed = (
        int(sub_q[flag_cols].fillna(False).any(axis=1).sum())
        if (not sub_q.empty and flag_cols) else 0
    )

    # 항목별 부적합 건수 (단축명 → 건수). 기준 없는 EC 등은 자동 제외.
    qual_item_counts: list[tuple[str, int]] = []
    if not sub_q.empty and flag_cols:
        for item, std in config.WATER_QUALITY_STANDARDS.items():
            col = f"{item}_exceed"
            if col not in sub_q.columns:
                continue
            cnt = int(sub_q[col].fillna(False).sum())
            if cnt > 0:
                short = QUALITY_SHORT_NAMES.get(item, std.get("kor", item))
                qual_item_counts.append((short, cnt))

    return {
        "total_vol":    total_vol,
        "total_permit": total_permit,
        "n_wells":      n_wells,
        "daily_avg":    daily_avg,
        "daily_median": daily_median,
        "rate_mean":    rate_mean,
        "rate_median":  rate_median,
        "qual_exceed":  qual_exceed,
        "qual_item_counts": qual_item_counts,
    }


# ------------------------------------------------------------------------------
#  캐시 적용 wrapper — (year, month) 키로만 캐시.
#  DataFrame 을 인자로 받으면 streamlit cache 가 매번 hash 하느라 캐시 효과
#  사라짐. 그래서 wrapper 가 (year, month) 만 받고 내부에서 ag_well_loader
#  의 cache 된 loader 를 호출. ttl=600 (10분) — 같은 기간을 다시 요청하면
#  즉시 반환되어 ⑧ 통계 탭 진입 시 KPI 12개 (3개년 × 4 KPI) 가 빠르게 표시.
# ------------------------------------------------------------------------------
@st.cache_data(ttl=600, show_spinner=False)
def _compute_period_kpis_cached(year: int, month: int | None) -> dict:
    df_usage = ag_well_loader.load_usage_long()
    df_qual = ag_well_loader.load_quality_semiannual()
    return _compute_period_kpis(df_usage, df_qual, year, month)


# ------------------------------------------------------------------------------
#  ■ 4개 AWS 평균 강수량 (연·월)
# ------------------------------------------------------------------------------
@st.cache_data(ttl=600, show_spinner=False)
def _yearly_avg_rainfall(asos_df: pd.DataFrame) -> pd.DataFrame:
    """연도별 4개 AWS 산술평균 강수량 (mm) — 각 지점 연합 → 지점간 평균."""
    if asos_df is None or asos_df.empty:
        return pd.DataFrame(columns=["year", "rainfall"])
    monthly = effective_rainfall.aggregate_monthly(asos_df)
    if monthly.empty:
        return pd.DataFrame(columns=["year", "rainfall"])
    monthly = monthly.copy()
    monthly["year"] = pd.to_datetime(monthly["연월"], errors="coerce").dt.year
    monthly = monthly.dropna(subset=["year"])
    monthly["year"] = monthly["year"].astype(int)
    per_year_st = (
        monthly.groupby(["year", "지점명"])["월강수량(mm)"]
        .sum().reset_index()
    )
    yearly = (
        per_year_st.groupby("year")["월강수량(mm)"]
        .mean().reset_index()
        .rename(columns={"월강수량(mm)": "rainfall"})
    )
    return yearly


@st.cache_data(ttl=600, show_spinner=False)
def _monthly_avg_rainfall(asos_df: pd.DataFrame, year: int) -> pd.DataFrame:
    """선택연도의 월별 4개 AWS 산술평균 강수량 (mm)."""
    if asos_df is None or asos_df.empty:
        return pd.DataFrame(columns=["month", "rainfall"])
    monthly = effective_rainfall.aggregate_monthly(asos_df)
    if monthly.empty:
        return pd.DataFrame(columns=["month", "rainfall"])
    m = monthly.copy()
    dt = pd.to_datetime(m["연월"], errors="coerce")
    m["year"]  = dt.dt.year
    m["month"] = dt.dt.month
    m = m.dropna(subset=["year", "month"])
    sub = m[m["year"].astype(int) == year]
    by_month = (
        sub.groupby("month")["월강수량(mm)"]
        .mean().reset_index()
        .rename(columns={"월강수량(mm)": "rainfall"})
        .sort_values("month")
    )
    return by_month


# ------------------------------------------------------------------------------
#  ■ render
# ------------------------------------------------------------------------------
@st.fragment  # 21차 Step4: 위젯 변경 시 다른 탭 튕김 방지 (AGENT_GUIDE §6)
def render(asos_df: pd.DataFrame | None = None) -> None:
    # (2026-06-11 v2) 탭 제목 제거 — 하위탭 pill 문구와 중복 (사용자 요청)

    df_master_all = ag_well_loader.load_master(active_only=False)
    df_master_act = ag_well_loader.load_master(active_only=True)
    df_usage      = ag_well_loader.load_usage_long()
    df_qual       = ag_well_loader.load_quality_semiannual()

    if df_master_all.empty:
        st.warning("관정 마스터 자료를 찾을 수 없습니다.")
        return

    # ── 관정현황 (주기 무관) — 컨트롤 우측 인라인 텍스트로 표시
    active, inactive = ag_well_metrics.kpi_active_count(df_master_all)
    n_jeju = (
        int((df_master_act["authority"] == "jeju").sum())
        if "authority" in df_master_act.columns else 0
    )
    n_seogwipo = (
        int((df_master_act["authority"] == "seogwipo").sum())
        if "authority" in df_master_act.columns else 0
    )

    # ── 기준(연도/주기/월) + 관정현황 한 줄 통합
    available_years = (
        sorted(df_usage["year"].dropna().unique().astype(int))[::-1]
        if not df_usage.empty else [2025]
    )
    # 모드/월 session_state 선제 등록 (Streamlit 버전 따라 미렌더 위젯 키
    # 자동 정리 이슈 방어 + cols[0] 라벨 텍스트가 cols[3] radio 보다 먼저 결정되도록)
    st.session_state.setdefault("stats_period", PERIOD_YEAR)
    st.session_state.setdefault("stats_month", 1)
    period_mode_pre = st.session_state["stats_period"]
    is_month_mode = (period_mode_pre == PERIOD_MONTH)

    period_label_text = "기준 연월 :" if is_month_mode else "기준 연도 :"

    # 5칸 — 라벨 22px 로 키우면서 cols[0] 비율 0.8 → 1.3 으로 확장
    sel_cols = st.columns([1.3, 0.9, 0.6, 1.5, 3.7])

    # cols[0] — 라벨 (대시보드 제목과 동일 22px 크기, baseline 정렬)
    with sel_cols[0]:
        st.markdown(
            f'<div style="padding-top:4px;text-align:right;font-size:22px;'
            f'color:var(--color-text-primary);font-weight:500;line-height:1.15;'
            f'white-space:nowrap;">'
            f'{period_label_text}</div>',
            unsafe_allow_html=True,
        )

    # cols[1] — 기준 연도 selectbox (라벨 collapsed)
    with sel_cols[1]:
        target_year = st.selectbox(
            "기준 연도", options=available_years, index=0,
            key="stats_year", label_visibility="collapsed",
            format_func=lambda y: f"{y}년",
        )

    # cols[2] — 월단위면 월 selectbox, 아니면 빈 자리(공백)
    with sel_cols[2]:
        if is_month_mode:
            target_month = st.selectbox(
                "기준 월", options=list(range(1, 13)), index=0,
                key="stats_month", label_visibility="collapsed",
                format_func=lambda m: f"{m}월",
            )
        else:
            target_month = None
            st.markdown("&nbsp;", unsafe_allow_html=True)

    # cols[3] — 주기 radio (라벨 collapsed, horizontal)
    with sel_cols[3]:
        period_mode = st.radio(
            "주기", options=[PERIOD_YEAR, PERIOD_MONTH],
            horizontal=True, key="stats_period",
            label_visibility="collapsed",
        )

    # cols[4] — 관정현황 인라인 (대시보드 제목과 동일 22px 크기)
    #   가용 폭(약 380px) 보다 22px 텍스트 폭이 클 수 있어 wrap 허용.
    with sel_cols[4]:
        inactive_tag = (
            f' <span style="color:#1d9e75;font-weight:500;">'
            f'(비활성 {inactive}공)</span>'
            if inactive else ""
        )
        st.markdown(
            f'<div style="padding-top:4px;text-align:right;line-height:1.25;'
            f'font-size:22px;color:var(--color-text-secondary);font-weight:500;">'
            f'<span style="color:var(--color-text-info);font-weight:600;">관정 현황</span> &nbsp;'
            f'활성 <b style="color:var(--color-text-primary);">{active:,}공</b>{inactive_tag}'
            f'  ·  '
            f'제주 <b style="color:{config.AG_PALETTE["jeju"]};">{n_jeju:,}공</b>'
            f'  ·  '
            f'서귀포 <b style="color:{config.AG_PALETTE["seogwipo"]};">{n_seogwipo:,}공</b>'
            f'</div>',
            unsafe_allow_html=True,
        )

    st.markdown(
        '<hr style="margin:10px 0 8px;border:none;border-top:0.5px solid rgba(26,26,24,0.15);">',
        unsafe_allow_html=True,
    )

    # ── 3개년(또는 3개월) 세로 KPI
    periods = [_shift_period(target_year, target_month, k) for k in (0, 1, 2)]
    period_labels = [_period_label(*p) for p in periods]
    quality_labels = [_quality_period_label(*p) for p in periods]
    # cache 적용 wrapper 사용 — (year, month) 만 키로 ttl=600 캐시.
    # df_usage/df_qual 은 wrapper 내부의 cache 된 loader 에서 가져옴.
    kpis = [_compute_period_kpis_cached(*p) for p in periods]

    yr_cols = st.columns(3)
    for i, col in enumerate(yr_cols):
        with col:
            _render_year_card(
                kpi=kpis[i],
                year_label=period_labels[i],
                quality_label=quality_labels[i],
                is_base=(i == 0),
            )

    st.markdown(
        '<hr style="margin:14px 0;border:none;border-top:0.5px solid rgba(26,26,24,0.15);">',
        unsafe_allow_html=True,
    )

    # ── 좌(연도별) / 우(선택연도 월별) 추이 — 라인은 평균 강수량(mm)
    L, R = st.columns(2)
    with L:
        st.markdown(
            '<p class="subsection-title">'
            '연도별 총 이용량 (시별 누적) / 평균 강수량 (4개 AWS)</p>',
            unsafe_allow_html=True,
        )
        _render_yearly_trend_stacked(df_usage, df_master_act, asos_df)
    with R:
        st.markdown(
            f'<p class="subsection-title">'
            f'{target_year}년 월별 이용량 (시별 누적) / 평균 강수량 (4개 AWS)</p>',
            unsafe_allow_html=True,
        )
        _render_monthly_trend_stacked(df_usage, df_master_act, asos_df, target_year)

    # ── 시별 읍·면·동 도넛 (기준 기간) — 1줄 3개
    st.markdown(
        f'<p class="subsection-title" style="margin-top:12px;">'
        f'행정구역(읍·면·동)별 이용량 비중 — {period_labels[0]}</p>',
        unsafe_allow_html=True,
    )
    D1, D2, D3 = st.columns(3)
    with D1:
        _render_eup_donut(
            df_usage, df_master_act, target_year, target_month,
            city_kor="제주도 전체", city_key=None,
        )
    with D2:
        _render_eup_donut(
            df_usage, df_master_act, target_year, target_month,
            city_kor="제주시", city_key="jeju",
        )
    with D3:
        _render_eup_donut(
            df_usage, df_master_act, target_year, target_month,
            city_kor="서귀포시", city_key="seogwipo",
        )

    # ── 연도별 수질 검사 통계 — 항목별 표 5개 (최근 5년)
    st.markdown(
        '<p class="subsection-title" style="margin-top:12px;">'
        '연도별 수질 검사 통계 (항목별, 최근 5년)</p>',
        unsafe_allow_html=True,
    )
    _render_quality_summary_table(df_qual)


# ------------------------------------------------------------------------------
#  ■ 단일 연도 KPI 카드 (overview 스타일·HTML, 그룹 내 줄간격 좁힘)
# ------------------------------------------------------------------------------
def _fmt_or_dash(v: float | None, fmt: str) -> str:
    return fmt.format(v) if v is not None else "-"


def _render_year_card(
    kpi: dict,
    year_label: str,
    quality_label: str,
    is_base: bool,
) -> None:
    """한 연도(또는 연·월) 칸의 4개 KPI 그룹을 카드형 HTML로 표시."""
    accent     = CARD_ACCENT
    bg_tint    = theme.hex_alpha(accent, 0.08 if is_base else 0.04)
    bord_tint  = theme.hex_alpha(accent, 0.25)
    title_col  = accent if is_base else theme.COLOR_TEXT_SECONDARY
    val_col    = accent
    sub_col    = theme.COLOR_TEXT_SECONDARY
    label_col  = theme.COLOR_TEXT_PRIMARY

    # ── 그룹 공통 스타일 (대시보드 요약 탭과 같은 톤 — 메인 18px)
    GROUP_OPEN  = (
        f'<div style="padding:6px 0 4px;border-top:0.5px dashed {bord_tint};">'
    )
    LABEL = (
        f'<div style="font-size:17px;color:{label_col};font-weight:600;'
        f'line-height:1.15;margin:0;">{{0}}</div>'
    )
    VALUE = (
        f'<div style="font-size:18px;font-weight:700;color:{val_col};'
        f'line-height:1.15;margin:2px 0 0;">{{0}}</div>'
    )
    SUB = (
        f'<div style="font-size:16px;color:{sub_col};font-weight:500;'
        f'line-height:1.3;margin:1px 0 0;">{{0}}</div>'
    )
    GROUP_CLOSE = '</div>'

    # ① 총 이용량 + 총 취수허가량
    grp_total = (
        GROUP_OPEN
        + LABEL.format("총 이용량")
        + VALUE.format(f"{kpi['total_vol']:,.0f} ㎥")
        + SUB.format(f"총 취수허가량 {kpi['total_permit']:,.0f} ㎥")
        + GROUP_CLOSE
    )

    # ② 관정별 평균 일이용량 + 중앙값 + 공수
    daily_avg_str = _fmt_or_dash(kpi["daily_avg"], "{:,.1f}")
    daily_med_str = _fmt_or_dash(kpi["daily_median"], "{:,.1f}")
    well_tail = f"  ·  {kpi['n_wells']:,}공" if kpi["n_wells"] else ""
    grp_daily = (
        GROUP_OPEN
        + LABEL.format("관정별 평균 일이용량")
        + VALUE.format(f"{daily_avg_str} ㎥/일")
        + SUB.format(f"관정별 중앙값 {daily_med_str} ㎥/일{well_tail}")
        + GROUP_CLOSE
    )

    # ③ 관정별 평균 사용률 (이용량/취수허가량) + 중앙값
    rate_mean_str = _fmt_or_dash(kpi["rate_mean"], "{:.1f}")
    rate_med_str  = _fmt_or_dash(kpi["rate_median"], "{:.1f}")
    # 같은 줄에 메인 라벨 + 작은 캡션 (현재 카드폭 약 290px 안에 한 줄 표시)
    rate_label_html = (
        f'<div style="font-size:17px;color:{label_col};font-weight:600;'
        f'line-height:1.2;margin:0;white-space:nowrap;">'
        f'관정별 평균 사용률'
        f'<span style="font-size:15px;color:{sub_col};font-weight:400;"> '
        f'(이용량/취수허가량)</span>'
        f'</div>'
    )
    grp_rate = (
        GROUP_OPEN
        + rate_label_html
        + VALUE.format(f"{rate_mean_str}%")
        + SUB.format(f"관정별 중앙값 {rate_med_str}%")
        + GROUP_CLOSE
    )

    # ④ 수질 부적합 + 항목별 초과 건수
    item_counts = kpi.get("qual_item_counts") or []
    if item_counts:
        qual_caption = "  ·  ".join(f"{name} {cnt:,}건" for name, cnt in item_counts)
    elif kpi["qual_exceed"]:
        qual_caption = "5항목 중 1+ 초과"
    else:
        qual_caption = "기준 부적합 없음"
    grp_qual = (
        GROUP_OPEN
        + LABEL.format("수질 부적합")
        + VALUE.format(f"{kpi['qual_exceed']:,}건")
        + SUB.format(qual_caption)
        + GROUP_CLOSE
    )

    # 카드 헤더 — 마커 제거, 연도(혹은 연·월)만 표기 (헤더 색 강약으로 기준/직전 구분)
    title_html = (
        f'<div style="font-size:16px;font-weight:700;color:{title_col};'
        f'padding:2px 0 4px;line-height:1.2;">'
        f'{year_label}'
        f'</div>'
    )

    card_html = (
        f'<div style="background:{bg_tint};border-radius:8px;'
        f'padding:0.55rem 0.9rem 0.7rem;border-left:3px solid {accent};'
        f'margin-bottom:8px;">'
        f'{title_html}{grp_total}{grp_daily}{grp_rate}{grp_qual}'
        f'</div>'
    )
    st.markdown(card_html, unsafe_allow_html=True)


# ------------------------------------------------------------------------------
#  ■ 연도별 추이 — 시별 누적 막대 + 평균 강수량 라인
# ------------------------------------------------------------------------------
def _render_yearly_trend_stacked(
    df_usage: pd.DataFrame,
    df_master: pd.DataFrame,
    asos_df: pd.DataFrame | None,
) -> None:
    if df_usage.empty:
        st.caption("자료 없음")
        return

    merged = _merge_city(df_usage, df_master)
    if merged.empty:
        st.caption("자료 없음")
        return

    yearly_city = (
        merged.groupby(["year", "city"], dropna=False)["volume_m3"]
        .sum().reset_index()
    )
    # ── 시별 균형 필터: 한쪽이 0 이거나 30% 이하인 연도는 통째로 제외
    pivot_yr = yearly_city.pivot_table(
        index="year", columns="city",
        values="volume_m3", aggfunc="sum", fill_value=0,
    )
    years = sorted(int(y) for y in _filter_balanced_periods(pivot_yr))
    if not years:
        st.caption("자료 없음")
        return
    yearly_city = yearly_city[yearly_city["year"].isin(years)]

    rain_yr = _yearly_avg_rainfall(asos_df) if asos_df is not None else pd.DataFrame()
    if not rain_yr.empty:
        rain_yr = rain_yr[rain_yr["year"].isin(years)]

    fig = go.Figure()
    for city in ("서귀포시", "제주시"):  # 서귀포 먼저 → 아래
        d = (
            yearly_city[yearly_city["city"] == city]
            .set_index("year").reindex(years, fill_value=0).reset_index()
        )
        fig.add_trace(go.Bar(
            x=d["year"], y=d["volume_m3"],
            name=city, marker_color=CITY_COLOR[city],
            yaxis="y1",
        ))
    if not rain_yr.empty:
        fig.add_trace(go.Scatter(
            x=rain_yr["year"], y=rain_yr["rainfall"],
            name="평균 강수량 (mm)", mode="lines+markers",
            line=dict(color=RAIN_LINE_COLOR, width=2.5),
            yaxis="y2",
        ))
    fig.update_layout(
        barmode="stack",
        height=320, margin=dict(l=10, r=10, t=20, b=30),
        plot_bgcolor="white",
        yaxis=dict(title="이용량 (㎥)", side="left"),
        yaxis2=dict(title="강수량 (mm)", overlaying="y", side="right"),
        legend=dict(orientation="h", y=1.05, font=dict(size=14)),
    )
    fig.update_xaxes(tickfont=dict(size=13), tickvals=years)
    st.plotly_chart(fig, use_container_width=True)


# ------------------------------------------------------------------------------
#  ■ 선택연도 월별 추이 — 시별 누적 막대 + 평균 강수량 라인
# ------------------------------------------------------------------------------
def _render_monthly_trend_stacked(
    df_usage: pd.DataFrame,
    df_master: pd.DataFrame,
    asos_df: pd.DataFrame | None,
    year: int,
) -> None:
    if df_usage.empty:
        st.caption("자료 없음")
        return

    sub = df_usage[df_usage["year"] == year]
    if sub.empty:
        st.caption(f"{year}년 자료 없음")
        return

    merged = _merge_city(sub, df_master)
    if merged.empty:
        st.caption(f"{year}년 자료 없음")
        return

    monthly_city = (
        merged.groupby(["month", "city"], dropna=False)["volume_m3"]
        .sum().reset_index()
    )
    # ── 시별 균형 필터: 한쪽이 0 이거나 30% 이하인 월은 통째로 제외
    pivot_m = monthly_city.pivot_table(
        index="month", columns="city",
        values="volume_m3", aggfunc="sum", fill_value=0,
    )
    months = sorted(int(m) for m in _filter_balanced_periods(pivot_m))
    if not months:
        st.caption(f"{year}년 자료 없음")
        return
    monthly_city = monthly_city[monthly_city["month"].isin(months)]

    rain_m = _monthly_avg_rainfall(asos_df, year) if asos_df is not None else pd.DataFrame()
    if not rain_m.empty:
        rain_m = rain_m[rain_m["month"].isin(months)]

    fig = go.Figure()
    for city in ("서귀포시", "제주시"):
        d = (
            monthly_city[monthly_city["city"] == city]
            .set_index("month").reindex(months, fill_value=0).reset_index()
        )
        fig.add_trace(go.Bar(
            x=d["month"], y=d["volume_m3"],
            name=city, marker_color=CITY_COLOR[city],
            yaxis="y1",
        ))
    if not rain_m.empty:
        fig.add_trace(go.Scatter(
            x=rain_m["month"], y=rain_m["rainfall"],
            name="평균 강수량 (mm)", mode="lines+markers",
            line=dict(color=RAIN_LINE_COLOR, width=2.5),
            yaxis="y2",
        ))
    fig.update_layout(
        barmode="stack",
        height=320, margin=dict(l=10, r=10, t=20, b=30),
        plot_bgcolor="white",
        yaxis=dict(title="이용량 (㎥)", side="left"),
        yaxis2=dict(title="강수량 (mm)", overlaying="y", side="right"),
        legend=dict(orientation="h", y=1.05, font=dict(size=14)),
    )
    fig.update_xaxes(
        tickmode="array", tickvals=months,
        ticktext=[f"{m}월" for m in months], tickfont=dict(size=13),
    )
    st.plotly_chart(fig, use_container_width=True)


# ------------------------------------------------------------------------------
#  ■ 시별 읍·면·동 도넛
# ------------------------------------------------------------------------------
def _render_eup_donut(
    df_usage: pd.DataFrame,
    df_master: pd.DataFrame,
    year: int,
    month: int | None,
    city_kor: str,
    city_key: str | None,
) -> None:
    """행정구역(읍·면·동)별 이용량 도넛.

    city_key=None 이면 authority 필터 없이 제주도 전체.
    """
    sub = _filter_usage(df_usage, year, month)
    if sub.empty or df_master.empty:
        st.caption(f"{city_kor} 자료 없음")
        return
    if "well_eup" not in df_master.columns:
        st.caption("master 컬럼 부족")
        return
    if city_key is None:
        master_subset = df_master
    else:
        if "authority" not in df_master.columns:
            st.caption("master 컬럼 부족")
            return
        master_subset = df_master[df_master["authority"] == city_key]

    merged = sub.merge(
        master_subset[["permit_no", "well_eup"]].drop_duplicates("permit_no"),
        on="permit_no", how="inner",
    )
    by_eup = (
        merged.groupby("well_eup", dropna=False)["volume_m3"]
        .sum().reset_index()
    )
    by_eup["well_eup"] = by_eup["well_eup"].fillna("(미분류)")
    by_eup = by_eup[by_eup["volume_m3"] > 0].sort_values("volume_m3", ascending=False)
    if by_eup.empty:
        st.caption(f"{city_kor} 자료 없음")
        return

    if city_key is None:
        title_color = theme.COLOR_TEXT_PRIMARY
    else:
        title_color = CITY_COLOR.get(city_kor, theme.COLOR_TEXT_INFO)

    total_vol = float(by_eup["volume_m3"].sum())

    fig = go.Figure(go.Pie(
        labels=by_eup["well_eup"],
        values=by_eup["volume_m3"],
        hole=0.45,
        # texttemplate 만 사용 (textinfo 와 동시 지정은 redundant) — 슬라이스에
        # 라벨 + % + 이용량(㎥). textposition="inside" 로 강제하면 작은 슬라이스
        # 는 자동 hide 되어 hover 로 fallback (외부로 튀어나와 옆 컬럼 도넛과
        # 충돌하는 사고 방지).
        texttemplate="%{label}<br>%{percent}<br>%{value:,.0f} ㎥",
        textposition="inside",
        insidetextorientation="auto",
        textfont=dict(size=14),
        sort=False,
        hovertemplate="%{label}<br>%{value:,.0f} ㎥ (%{percent})<extra></extra>",
    ))
    # ── 도넛 가운데(hole) 합계 표시
    fig.add_annotation(
        text=f"<b>합계</b><br>{total_vol:,.0f} ㎥",
        showarrow=False,
        x=0.5, y=0.5, xref="paper", yref="paper",
        font=dict(size=16, color=theme.COLOR_TEXT_PRIMARY),
        align="center",
    )
    # ── 1.5배 확대 (320 → 480), 마진은 유지
    fig.update_layout(
        height=480, margin=dict(l=10, r=10, t=40, b=10),
        showlegend=False,
        title=dict(
            text=f"{city_kor} ({len(by_eup)}개 읍·면·동)",
            font=dict(size=13, color=title_color),
            x=0.5, xanchor="center",
        ),
    )
    st.plotly_chart(fig, use_container_width=True)




# ------------------------------------------------------------------------------
#  ■ 수질 검사 통계 — 항목별 표 5개 (행=연도, 열=검사횟수·평균·중앙값·최대·최소·초과율)
# ------------------------------------------------------------------------------
# 항목 순서: 기존 heatmap 과 동일하게 사용자 지정 순.
_QUALITY_ITEM_ORDER = ["nitrate_n", "pH", "chloride", "ammonia_n", "EC"]


def _quality_num_fmt(item: str) -> str:
    """항목별 수치 포맷 (pH 는 2 자리, EC 는 정수, 기타 2 자리)."""
    if item == "EC":
        return "{:,.0f}"
    return "{:.2f}"


def _quality_threshold_text(std: dict, unit: str) -> str:
    """기준치 텍스트 — '기준 ≤ 20.0 mg/L' 또는 '기준 6.0~8.5'."""
    if not std:
        return "기준 없음 (참고치)"
    has_min = "min" in std
    has_max = "max" in std
    if not (has_min or has_max):
        return "기준 없음 (참고치)"
    unit_tail = f" {unit}" if (unit and unit != "-") else ""
    if has_min and has_max:
        return f"기준 {std['min']}~{std['max']}{unit_tail}"
    if has_max:
        return f"기준 ≤ {std['max']}{unit_tail}"
    return f"기준 ≥ {std['min']}{unit_tail}"


def _render_quality_summary_table(df_qual: pd.DataFrame) -> None:
    if df_qual.empty:
        st.caption("수질 자료 없음")
        return
    if "year" not in df_qual.columns:
        st.caption("표시할 자료 없음")
        return

    years_all = sorted({int(y) for y in df_qual["year"].dropna().unique()})
    if not years_all:
        st.caption("표시할 자료 없음")
        return
    # 사용자 요청 2026-05-10: 자료 최신 연도 기준 -4 년 = 최근 5 년만 표시
    years = years_all[-5:]

    items_in_df = [k for k in _QUALITY_ITEM_ORDER if k in df_qual.columns]
    if not items_in_df:
        st.caption("표시할 자료 없음")
        return

    for item in items_in_df:
        std = config.WATER_QUALITY_STANDARDS.get(item, {})
        kor = std.get("kor", item)
        unit = std.get("unit", "")
        flag_col = f"{item}_exceed"
        has_threshold = (flag_col in df_qual.columns)
        num_fmt = _quality_num_fmt(item)
        unit_text = f" ({unit})" if (unit and unit != "-") else ""
        thr_text = _quality_threshold_text(std, unit)

        # ── 항목 헤더 — 좌측에 항목명·단위, 우측에 기준치 캡션
        st.markdown(
            f'<div style="display:flex;align-items:baseline;justify-content:space-between;'
            f'margin:10px 0 4px;">'
            f'<span style="font-size:16px;font-weight:700;color:var(--color-text-primary);">'
            f'■ {kor}{unit_text}</span>'
            f'<span style="font-size:15px;color:var(--color-text-secondary);font-weight:500;">'
            f'{thr_text}</span>'
            f'</div>',
            unsafe_allow_html=True,
        )

        # ── 표 헤더
        TH = (
            'padding:6px 4px;text-align:center;font-weight:700;color:#000;'
            'border:0.5px solid rgba(0,0,0,0.18);font-size:16px;'
        )
        head = (
            '<table style="width:100%;border-collapse:collapse;font-size:16px;'
            'table-layout:fixed;border:0.5px solid rgba(0,0,0,0.18);'
            'margin-bottom:6px;">'
            '<thead><tr style="background:var(--color-bg-secondary);">'
            f'<th style="{TH}width:14%;">연도</th>'
            f'<th style="{TH}width:14%;">검사횟수</th>'
            f'<th style="{TH}width:14%;">산술평균</th>'
            f'<th style="{TH}width:14%;">중앙값</th>'
            f'<th style="{TH}width:14%;">최댓값</th>'
            f'<th style="{TH}width:14%;">최솟값</th>'
            f'<th style="{TH}width:16%;">초과율</th>'
            '</tr></thead><tbody>'
        )

        body_parts: list[str] = []
        for y in years:
            sub_y = df_qual[(df_qual["year"] == y) & df_qual[item].notna()]
            count = int(len(sub_y))
            if count == 0:
                body_parts.append(_quality_row_html(y, 0, None, None, None, None, None, num_fmt))
                continue
            vals = sub_y[item]
            mean_v = float(vals.mean())
            med_v  = float(vals.median())
            max_v  = float(vals.max())
            min_v  = float(vals.min())
            if has_threshold:
                exceed_n = int(sub_y[flag_col].fillna(False).sum())
                exceed_rate = exceed_n / count * 100
            else:
                exceed_rate = None
            body_parts.append(
                _quality_row_html(y, count, mean_v, med_v, max_v, min_v,
                                  exceed_rate, num_fmt)
            )

        st.markdown(
            head + "".join(body_parts) + "</tbody></table>",
            unsafe_allow_html=True,
        )


def _quality_row_html(
    year: int,
    count: int,
    mean_v: float | None,
    med_v: float | None,
    max_v: float | None,
    min_v: float | None,
    exceed_rate: float | None,
    num_fmt: str,
) -> str:
    """항목 표의 한 행 HTML (연도 + 6 컬럼)."""
    TD = (
        'padding:6px 4px;text-align:center;'
        'border:0.5px solid rgba(0,0,0,0.18);font-size:16px;'
    )
    DASH = f'<td style="{TD}color:var(--color-text-secondary);">-</td>'

    head_cell = (
        f'<td style="{TD}font-weight:700;background:#fafaf8;color:#000;">'
        f'{year}</td>'
    )

    if count == 0:
        return f'<tr>{head_cell}{DASH * 6}</tr>'

    cnt_cell = f'<td style="{TD}color:var(--color-text-primary);">{count:,}</td>'

    def _val_cell(v: float | None) -> str:
        if v is None:
            return DASH
        return (
            f'<td style="{TD}color:var(--color-text-primary);">'
            f'{num_fmt.format(v)}</td>'
        )

    if exceed_rate is None:
        rate_cell = DASH
    else:
        if exceed_rate <= 0:
            rate_color = "var(--color-success)"
        elif exceed_rate < 5:
            rate_color = "var(--color-text-primary)"
        else:
            rate_color = "var(--color-danger)"
        rate_cell = (
            f'<td style="{TD}color:{rate_color};font-weight:600;">'
            f'{exceed_rate:.1f}%</td>'
        )

    return (
        f'<tr>{head_cell}{cnt_cell}'
        f'{_val_cell(mean_v)}{_val_cell(med_v)}'
        f'{_val_cell(max_v)}{_val_cell(min_v)}'
        f'{rate_cell}</tr>'
    )


# ------------------------------------------------------------------------------
#  ■ 내부 헬퍼: usage × master(authority) → city 컬럼 부착
# ------------------------------------------------------------------------------
def _merge_city(df_usage: pd.DataFrame, df_master: pd.DataFrame) -> pd.DataFrame:
    if df_usage.empty or df_master.empty or "authority" not in df_master.columns:
        return df_usage.iloc[0:0].copy()
    merged = df_usage.merge(
        df_master[["permit_no", "authority"]].drop_duplicates("permit_no"),
        on="permit_no", how="left",
    )
    merged["city"] = merged["authority"].map(AUTH_TO_CITY)
    merged = merged[merged["city"].isin(("제주시", "서귀포시"))]
    return merged
