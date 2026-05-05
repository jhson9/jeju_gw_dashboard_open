# ==============================================================================
#  파일명: src/dashboard/tabs/tab9_ag_stats.py  —  Build 2.2
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


PERIOD_YEAR  = "년단위"
PERIOD_MONTH = "월단위"

_AG_PALETTE_FALLBACK = {
    "seogwipo": "#C65911",
    "jeju":     "#305496",
}
PALETTE = getattr(config, "AG_PALETTE", _AG_PALETTE_FALLBACK)
CITY_COLOR = {
    "제주시":   PALETTE.get("jeju", _AG_PALETTE_FALLBACK["jeju"]),
    "서귀포시": PALETTE.get("seogwipo", _AG_PALETTE_FALLBACK["seogwipo"]),
}
AUTH_TO_CITY = {"jeju": "제주시", "seogwipo": "서귀포시"}

RAIN_LINE_COLOR = "#185fa5"   # 강수량 라인 색상 (제주시 톤)
CARD_ACCENT     = PALETTE.get("jeju", _AG_PALETTE_FALLBACK["jeju"])   # #305496 — 농업용 관정 컨텍스트의 대표 색

# 수질 항목 단축명 (수질 부적합 카드 캡션용 — config.kor 보다 짧고 직관적)
QUALITY_SHORT_NAMES = {
    "ammonia_n": "암모니아",
    "nitrate_n": "질산",
    "pH":        "pH",
    "chloride":  "염소",
    "EC":        "EC",
}


def _rgba_hex(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


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
    """기간 내 '관정별 사용률(%) = sum(이용량)/sum(취수허가량)*100' 시리즈."""
    if sub_u.empty:
        return pd.Series(dtype=float)
    g = sub_u.groupby("permit_no").agg(
        vol=("volume_m3", "sum"),
        perm=("permit_m3m", "sum"),
    )
    mask = (g["perm"] > 0) & g["vol"].notna()
    rate = pd.Series(index=g.index, dtype=float)
    rate.loc[mask] = g.loc[mask, "vol"] / g.loc[mask, "perm"] * 100
    return rate.dropna()


def _per_well_daily_usage(sub_u: pd.DataFrame, days: int) -> pd.Series:
    """기간 내 '관정별 일이용량 = sum(이용량)/days' 시리즈."""
    if sub_u.empty:
        return pd.Series(dtype=float)
    per_well = sub_u.groupby("permit_no")["volume_m3"].sum()
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

    total_vol    = float(sub_u["volume_m3"].sum(skipna=True)) if not sub_u.empty else 0.0
    total_permit = float(sub_u["permit_m3m"].sum(skipna=True)) if not sub_u.empty else 0.0

    # 관정 수: 해당 기간에 이용량 기록이 있는 고유 관정
    if not sub_u.empty:
        n_wells = int(sub_u.loc[sub_u["volume_m3"].notna(), "permit_no"].nunique())
    else:
        n_wells = 0

    daily_avg = (total_vol / n_wells / days) if n_wells > 0 else None
    daily_per_well = _per_well_daily_usage(sub_u, days)
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
#  ■ 4개 AWS 평균 강수량 (연·월)
# ------------------------------------------------------------------------------
@st.cache_data(ttl=300, show_spinner=False)
def _yearly_avg_rainfall(asos_df: pd.DataFrame) -> pd.DataFrame:
    """연도별 4개 AWS 산술평균 강수량 (mm) — 각 지점 연합 → 지점간 평균."""
    if asos_df is None or asos_df.empty:
        return pd.DataFrame(columns=["year", "rainfall"])
    monthly = effective_rainfall.aggregate_monthly(asos_df)
    if monthly.empty:
        return pd.DataFrame(columns=["year", "rainfall"])
    monthly = monthly.copy()
    monthly["year"] = pd.to_datetime(monthly["연월"]).dt.year
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


@st.cache_data(ttl=300, show_spinner=False)
def _monthly_avg_rainfall(asos_df: pd.DataFrame, year: int) -> pd.DataFrame:
    """선택연도의 월별 4개 AWS 산술평균 강수량 (mm)."""
    if asos_df is None or asos_df.empty:
        return pd.DataFrame(columns=["month", "rainfall"])
    monthly = effective_rainfall.aggregate_monthly(asos_df)
    if monthly.empty:
        return pd.DataFrame(columns=["month", "rainfall"])
    m = monthly.copy()
    dt = pd.to_datetime(m["연월"])
    m["year"]  = dt.dt.year
    m["month"] = dt.dt.month
    sub = m[m["year"] == year]
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
def render(
    ag_master_df: pd.DataFrame | None = None,
    ag_usage_df: pd.DataFrame | None = None,
    ag_wq_df: pd.DataFrame | None = None,
    periods: dict | None = None,
    asos_df: pd.DataFrame | None = None,
) -> None:
    st.markdown(
        '<h2 style="font-size:22px;font-weight:500;margin:0 0 6px;padding:0;'
        'color:#1a1a18;line-height:1.2;">'
        '⑧ 통계·요약 — 거버넌스 KPI 보드</h2>',
        unsafe_allow_html=True,
    )

    df_master_all = ag_master_df if ag_master_df is not None else ag_well_loader.load_master(active_only=False)
    df_master_act = ag_master_df if ag_master_df is not None else ag_well_loader.load_master(active_only=True)
    df_usage      = ag_usage_df if ag_usage_df is not None else ag_well_loader.load_usage_long()
    df_qual       = ag_wq_df if ag_wq_df is not None else ag_well_loader.load_quality_semiannual()

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
            f'color:#1a1a18;font-weight:500;line-height:1.15;'
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
            f'font-size:22px;color:#5f5e5a;font-weight:500;">'
            f'<span style="color:#185fa5;font-weight:600;">관정 현황</span> &nbsp;'
            f'활성 <b style="color:#1a1a18;">{active:,}공</b>{inactive_tag}'
            f'  ·  '
            f'제주 <b style="color:{PALETTE.get("jeju", _AG_PALETTE_FALLBACK["jeju"])};">{n_jeju:,}공</b>'
            f'  ·  '
            f'서귀포 <b style="color:{PALETTE.get("seogwipo", _AG_PALETTE_FALLBACK["seogwipo"])};">{n_seogwipo:,}공</b>'
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
    kpis = [_compute_period_kpis(df_usage, df_qual, *p) for p in periods]

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
            '<div style="font-size:13px;font-weight:600;color:#185fa5;">'
            '연도별 총 이용량 (시별 누적) / 평균 강수량 (4개 AWS)</div>',
            unsafe_allow_html=True,
        )
        _render_yearly_trend_stacked(df_usage, df_master_act, asos_df)
    with R:
        st.markdown(
            f'<div style="font-size:13px;font-weight:600;color:#185fa5;">'
            f'{target_year}년 월별 이용량 (시별 누적) / 평균 강수량 (4개 AWS)</div>',
            unsafe_allow_html=True,
        )
        _render_monthly_trend_stacked(df_usage, df_master_act, asos_df, target_year)

    # ── 시별 읍·면·동 도넛 (기준 기간)
    st.markdown(
        f'<div style="font-size:13px;font-weight:600;margin-top:12px;color:#185fa5;">'
        f'행정구역(읍·면·동)별 이용량 비중 — {period_labels[0]}</div>',
        unsafe_allow_html=True,
    )
    D1, D2 = st.columns(2)
    with D1:
        _render_eup_donut(
            df_usage, df_master_act, target_year, target_month,
            city_kor="제주시", city_key="jeju",
        )
    with D2:
        _render_eup_donut(
            df_usage, df_master_act, target_year, target_month,
            city_kor="서귀포시", city_key="seogwipo",
        )

    # ── 수질 부적합 추이 (연 × 항목) — 기존 유지
    st.markdown(
        '<div style="font-size:13px;font-weight:600;margin-top:12px;color:#185fa5;">'
        '수질 부적합 추이 (연 × 항목)</div>',
        unsafe_allow_html=True,
    )
    _render_quality_heatmap(df_qual)


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
    bg_tint    = _rgba_hex(accent, 0.08 if is_base else 0.04)
    bord_tint  = _rgba_hex(accent, 0.25)
    title_col  = accent if is_base else "#5f5e5a"
    val_col    = accent
    sub_col    = "#5f5e5a"
    label_col  = "#1a1a18"

    # ── 그룹 공통 스타일 (대시보드 요약 탭과 같은 톤 — 메인 18px)
    GROUP_OPEN  = (
        f'<div style="padding:6px 0 4px;border-top:0.5px dashed {bord_tint};">'
    )
    LABEL = (
        f'<div style="font-size:14px;color:{label_col};font-weight:600;'
        f'line-height:1.15;margin:0;">{{0}}</div>'
    )
    VALUE = (
        f'<div style="font-size:18px;font-weight:700;color:{val_col};'
        f'line-height:1.15;margin:2px 0 0;">{{0}}</div>'
    )
    SUB = (
        f'<div style="font-size:12px;color:{sub_col};font-weight:500;'
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
        f'<div style="font-size:14px;color:{label_col};font-weight:600;'
        f'line-height:1.2;margin:0;white-space:nowrap;">'
        f'관정별 평균 사용률'
        f'<span style="font-size:11px;color:{sub_col};font-weight:400;"> '
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
        legend=dict(orientation="h", y=1.05, font=dict(size=10)),
    )
    fig.update_xaxes(tickfont=dict(size=10), tickvals=years)
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
        legend=dict(orientation="h", y=1.05, font=dict(size=10)),
    )
    fig.update_xaxes(
        tickmode="array", tickvals=months,
        ticktext=[f"{m}월" for m in months], tickfont=dict(size=10),
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
    city_key: str,
) -> None:
    sub = _filter_usage(df_usage, year, month)
    if sub.empty or df_master.empty:
        st.caption(f"{city_kor} 자료 없음")
        return
    if "authority" not in df_master.columns or "well_eup" not in df_master.columns:
        st.caption("master 컬럼 부족")
        return

    city_master = df_master[df_master["authority"] == city_key]
    merged = sub.merge(
        city_master[["permit_no", "well_eup"]].drop_duplicates("permit_no"),
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

    title_color = CITY_COLOR.get(city_kor, "#185fa5")
    fig = go.Figure(go.Pie(
        labels=by_eup["well_eup"],
        values=by_eup["volume_m3"],
        hole=0.45,
        textinfo="label+percent",
        textfont=dict(size=10),
        sort=False,
    ))
    fig.update_layout(
        height=320, margin=dict(l=10, r=10, t=40, b=10),
        showlegend=False,
        title=dict(
            text=f"{city_kor} ({len(by_eup)}개 읍·면·동)",
            font=dict(size=13, color=title_color),
            x=0.5, xanchor="center",
        ),
    )
    st.plotly_chart(fig, use_container_width=True)


# ------------------------------------------------------------------------------
#  ■ 수질 부적합 히트맵 — 기존 유지
# ------------------------------------------------------------------------------
def _render_quality_heatmap(df_qual: pd.DataFrame) -> None:
    if df_qual.empty:
        st.caption("수질 자료 없음")
        return

    items = list(config.WATER_QUALITY_STANDARDS.keys())
    flag_cols = [f"{i}_exceed" for i in items if f"{i}_exceed" in df_qual.columns]
    if not flag_cols:
        st.caption("부적합 플래그를 계산할 수 없습니다.")
        return

    long = df_qual.melt(
        id_vars=["year"], value_vars=flag_cols,
        var_name="item_flag", value_name="is_exceed",
    )
    long["item"] = long["item_flag"].str.replace("_exceed", "", regex=False)
    long["item_kor"] = long["item"].map(
        lambda k: config.WATER_QUALITY_STANDARDS.get(k, {}).get("kor", k)
    )
    pv = long.pivot_table(
        index="item_kor", columns="year",
        values="is_exceed", aggfunc="sum", fill_value=0,
    )
    if pv.empty:
        st.caption("표시할 자료 없음")
        return

    # ── HTML 표 — 헤더 row 에 모든 연도 표시, 셀 배경은 Reds 그라디언트
    years = [int(y) for y in pv.columns.tolist()]
    years.sort()
    pv = pv.reindex(columns=years)

    # 사용자 지정 항목 순서: 질산성질소 → 수소이온농도 → 염소이온 → 암모니아성질소 → 전기전도도
    ITEM_ORDER_KOR = ["질산성질소", "수소이온농도", "염소이온", "암모니아성질소", "전기전도도"]
    ordered = [k for k in ITEM_ORDER_KOR if k in pv.index]
    extras  = [k for k in pv.index if k not in ITEM_ORDER_KOR]
    pv = pv.reindex(index=ordered + extras)

    z_max = float(pv.values.max()) if pv.size else 0.0

    # Reds colorscale stops (matplotlib Reds 계열 근사)
    _STOPS = [
        (0.00, (255, 245, 240)),
        (0.20, (254, 224, 210)),
        (0.40, (252, 187, 161)),
        (0.60, (252, 146, 114)),
        (0.80, (239,  59,  44)),
        (1.00, (103,   0,  13)),
    ]

    def _interp_color(t: float) -> tuple[int, int, int]:
        t = max(0.0, min(1.0, t))
        for i in range(len(_STOPS) - 1):
            t0, c0 = _STOPS[i]
            t1, c1 = _STOPS[i + 1]
            if t <= t1:
                k = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
                return tuple(int(c0[j] + (c1[j] - c0[j]) * k) for j in range(3))
        return _STOPS[-1][1]

    def _text_color(rgb: tuple[int, int, int]) -> str:
        # 상대 휘도 (sRGB) — 0.5 미만이면 흰 글자
        r, g, b = (c / 255.0 for c in rgb)
        lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
        return "#FFFFFF" if lum < 0.55 else "#000000"

    # 헤더
    head = (
        '<table style="width:100%;border-collapse:collapse;font-size:13px;'
        'table-layout:fixed;border:0.5px solid rgba(0,0,0,0.18);">'
        '<thead><tr style="background:#f5f5f3;">'
        '<th style="padding:6px 8px;text-align:center;font-weight:700;'
        'color:#000;border:0.5px solid rgba(0,0,0,0.18);min-width:110px;'
        'font-size:13px;">수질 항목</th>'
    )
    for y in years:
        head += (
            f'<th style="padding:6px 4px;text-align:center;font-weight:700;'
            f'color:#000;border:0.5px solid rgba(0,0,0,0.18);font-size:13px;">'
            f'{y}</th>'
        )
    head += '</tr></thead><tbody>'

    body = ""
    for item in pv.index.tolist():
        row = (
            f'<tr><td style="padding:6px 8px;font-weight:700;color:#000;'
            f'background:#fafaf8;border:0.5px solid rgba(0,0,0,0.18);'
            f'font-size:13px;">{item}</td>'
        )
        for y in years:
            v = pv.loc[item, y]
            try:
                vi = int(v)
            except (TypeError, ValueError):
                vi = 0
            t = (vi / z_max) if z_max > 0 else 0.0
            rgb = _interp_color(t)
            bg  = f"rgb({rgb[0]},{rgb[1]},{rgb[2]})"
            txt = _text_color(rgb)
            row += (
                f'<td style="padding:6px 4px;text-align:center;'
                f'background:{bg};color:{txt};font-weight:700;'
                f'border:0.5px solid rgba(0,0,0,0.18);font-size:14px;">'
                f'{vi}</td>'
            )
        row += "</tr>"
        body += row

    st.markdown(head + body + "</tbody></table>", unsafe_allow_html=True)

    # ── 색상 범례 (gradient bar + 0 / 중간값 / max 라벨)
    if z_max > 0:
        n_steps = 24
        gradient = "".join(
            (lambda rgb: f'<span style="display:inline-block;width:{100/n_steps:.4f}%;'
                          f'height:14px;background:rgb({rgb[0]},{rgb[1]},{rgb[2]});"></span>'
            )(_interp_color(i / (n_steps - 1)))
            for i in range(n_steps)
        )
        mid = int(round(z_max / 2))
        legend_html = (
            '<div style="margin:10px 0 4px;display:flex;align-items:center;'
            'justify-content:flex-end;gap:10px;font-size:11.5px;color:#5f5e5a;">'
            '<span style="font-weight:600;color:#1a1a18;">부적합 건수</span>'
            '<div style="display:flex;flex-direction:column;align-items:stretch;'
            'min-width:240px;">'
            f'<div style="display:flex;width:100%;border:0.5px solid rgba(0,0,0,0.18);'
            f'line-height:0;font-size:0;">{gradient}</div>'
            f'<div style="display:flex;justify-content:space-between;'
            f'margin-top:2px;font-size:10.5px;">'
            f'<span>0 (적음)</span><span>{mid:,}</span>'
            f'<span>{int(z_max):,} (많음)</span>'
            '</div>'
            '</div>'
            '</div>'
        )
        st.markdown(legend_html, unsafe_allow_html=True)


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
