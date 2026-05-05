# ==============================================================================
#  파일명: src/analysis/aws_yearly.py
#  Build 1.2.01 — AWS 12개월/10년 분석 헬퍼 (지도 분석 탭용)
# ------------------------------------------------------------------------------
#  effective_rainfall.aggregate_monthly() 결과를 베이스로,
#   - 직전 12개월 윈도우 (월별 실측 + 직전 5년 평균 + 편차)
#   - 10년치 월별 강수량 (라인/바 차트용)
#  생성용 헬퍼 함수.
# ==============================================================================

from __future__ import annotations

from datetime import date
from dateutil.relativedelta import relativedelta

import pandas as pd
import numpy as np

import config
from src.analysis import effective_rainfall


# ==============================================================================
#  ■ 직전 12개월 윈도우
# ==============================================================================
def last_12_months(base_date: date) -> list[tuple[int, int]]:
    """
    base_date 의 직전 12개월(과거 → base 월) [(year, month), ...] 반환.
    base_date 가 2026-04-22 이면 [(2025-05), ..., (2026-04)] (12개).
    """
    out = []
    for i in range(11, -1, -1):
        d = (date(base_date.year, base_date.month, 1) - relativedelta(months=i))
        out.append((d.year, d.month))
    return out


def build_12month_table(asos_df: pd.DataFrame, station: str, base_date: date,
                        metric: str = "월강수량(mm)",
                        n_baseline: int | None = None) -> pd.DataFrame:
    """
    한 AWS 지점의 직전 12개월 [실측, 직전 N년 평균, 편차] 표를 만든다.

    Returns
    -------
    DataFrame: 연월(str), 라벨(str), 실측(float|None), 평균(float|None), 편차(float|None)
    """
    if n_baseline is None:
        n_baseline = config.RAINFALL_BASELINE_YEARS

    monthly = effective_rainfall.aggregate_monthly(asos_df)
    rows = []
    for y, m in last_12_months(base_date):
        ym = f"{y}-{m:02d}"
        row = monthly[(monthly["지점명"] == station) & (monthly["연월"] == ym)]
        actual = float(row[metric].iloc[0]) if not row.empty and pd.notna(row[metric].iloc[0]) else None

        # 직전 N년 동월 평균
        baseline_years = list(range(y - n_baseline, y))
        vals = []
        for by in baseline_years:
            bym = f"{by}-{m:02d}"
            br = monthly[(monthly["지점명"] == station) & (monthly["연월"] == bym)]
            if not br.empty and pd.notna(br[metric].iloc[0]):
                vals.append(float(br[metric].iloc[0]))
        avg = float(np.mean(vals)) if vals else None
        diff = (actual - avg) if (actual is not None and avg is not None) else None

        rows.append({
            "연월": ym,
            "라벨": f"{m}월",            # 차트 X축용 짧은 라벨
            "라벨_긴": f"{str(y)[2:]}년 {m}월",
            "실측": round(actual, 1) if actual is not None else None,
            "평균": round(avg, 1) if avg is not None else None,
            "편차": round(diff, 1) if diff is not None else None,
        })
    return pd.DataFrame(rows)


# ==============================================================================
#  ■ 10년치 월별 강수량 (또는 임의 metric)
# ==============================================================================
def get_10year_monthly(asos_df: pd.DataFrame, station: str,
                       end_year: int,
                       metric: str = "월강수량(mm)",
                       years: int = 10) -> pd.DataFrame:
    """
    end_year 까지의 직전 N년 월별 데이터 (정렬됨). 차트 X축 시작월 드롭다운에서
    실제로 표시할 범위를 추가로 슬라이싱하면 됨.

    Returns
    -------
    DataFrame: 연월(str), 값(float)
    """
    monthly = effective_rainfall.aggregate_monthly(asos_df)
    if monthly.empty:
        return pd.DataFrame(columns=["연월", "값"])

    df = monthly[monthly["지점명"] == station].copy()
    if df.empty:
        return pd.DataFrame(columns=["연월", "값"])

    df = df[["연월", metric]].rename(columns={metric: "값"}).sort_values("연월")
    # end_year 직전 10년치만
    start_ym = f"{end_year - years + 1}-01"
    end_ym = f"{end_year}-12"
    return df[(df["연월"] >= start_ym) & (df["연월"] <= end_ym)].reset_index(drop=True)


# ==============================================================================
#  ■ 일자료 10년치 (관측정용)
# ==============================================================================
def get_10year_daily(day_df: pd.DataFrame, end_date: date,
                     years: int = 10) -> pd.DataFrame:
    """
    관측정 일자료에서 end_date 의 직전 'years'년 범위만 잘라 반환.
    """
    if day_df.empty:
        return day_df
    start = pd.Timestamp(end_date) - pd.DateOffset(years=years)
    end = pd.Timestamp(end_date)
    df = day_df[(day_df["날짜"] >= start) & (day_df["날짜"] <= end)].copy()
    return df.reset_index(drop=True)
