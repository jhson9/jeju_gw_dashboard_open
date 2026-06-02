# ==============================================================================
#  제주도 지하수위·강수량 분석 대시보드
#  파일명: src/analysis/effective_rainfall.py
#  모듈: 농업유효강수일수 + 직전 N년 평균 비교
# ------------------------------------------------------------------------------
#  Build: 0.7
#  최종 수정일: 2026-04-22
# ------------------------------------------------------------------------------
#  Changelog:
#  - v0.7 (2026-04-22): 최초 생성.
#                       기존 HTML 대시보드(v8)의 강수량·유효강수일수
#                       분석 로직을 Python으로 이식.
#                       * 농업유효강수일수: 일강수량 >= 5mm 인 날의 수
#                       * 월 강수량 합계
#                       * 반월(1~15일) 처리: 16일 이후 기준일의 M 기간 대응
#                       * 직전 N년 동월 평균 계산
# ------------------------------------------------------------------------------
#  【이 파일의 역할】
#  일별 ASOS 데이터를 월 단위로 집계하고, M-2·M-1·M 기간의 값과
#  직전 N년 동기간 평균을 비교하여 대시보드에 표시할 데이터를 만듭니다.
#
#  【핵심 함수】
#   - aggregate_monthly()       : 일 데이터 → 월 데이터 변환 (지점별)
#   - aggregate_half_monthly()  : 반월(1~15일) 집계
#   - get_period_value()        : 특정 기간·지점의 실측값 조회
#   - get_baseline_average()    : 직전 N년 동월 평균 계산
#   - build_comparison_table()  : M-2·M-1·M 비교표 전체 데이터 생성
# ==============================================================================

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[2]))

import logging

import pandas as pd
import numpy as np
import streamlit as st

import config

# P5-4 (2026-05-29): 모듈 표준 logger. print() 대체용으로 점진적 전환 권장.
logger = logging.getLogger(__name__)


# ==============================================================================
#  ■ 1. 월별 집계
# ==============================================================================
#  hash_funcs={pd.DataFrame: id} — asos_df 통째로 hash 하면 매번 캐시 미스.
#  asos_collector.load_asos_data() 가 cache 적용된 함수라 같은 객체 반환 →
#  id(asos_df) 가 5분간 같은 값 → 이 함수도 cache hit. 호출처 13곳 시그니처
#  변경 없이 캐시 효율만 끌어올림 (사용자 요청 2026-05-09).
@st.cache_data(ttl=600, show_spinner=False, max_entries=8, hash_funcs={pd.DataFrame: id})
def aggregate_monthly(asos_df: pd.DataFrame) -> pd.DataFrame:
    """
    일별 ASOS 데이터를 '지점 × 연월' 단위로 집계.

    집계 항목:
    - 월 강수량 합계 (mm)
    - 농업유효강수일수 (일강수량 >= 5mm 인 날의 수)
    - 월 평균기온 / 최고기온 / 최저기온

    Parameters
    ----------
    asos_df : pd.DataFrame
        asos_collector.load_asos_data() 결과
        (컬럼: 지점명, 일시, 일강수량(mm), 평균기온(°C), 최저기온(°C), 최고기온(°C))

    Returns
    -------
    pd.DataFrame
        컬럼: 지점명, 연월(str), 월강수량(mm), 유효강수일수(일),
              평균기온(°C), 최저기온(°C), 최고기온(°C)
    """
    if asos_df.empty:
        return pd.DataFrame(columns=["지점명", "연월", "월강수량(mm)",
                                     "유효강수일수(일)", "집계일수(일)",
                                     "평균기온(°C)",
                                     "최저기온(°C)", "최고기온(°C)"])

    df = asos_df.copy()
    df["일시"] = pd.to_datetime(df["일시"], errors="coerce")
    df = df.dropna(subset=["일시"])
    df["연월"] = df["일시"].dt.strftime("%Y-%m")

    # 유효강수일 플래그 (일강수량 >= 5mm)
    threshold = config.EFFECTIVE_RAINFALL_THRESHOLD_MM
    df["유효강수일"] = (df["일강수량(mm)"] >= threshold).astype(int)

    # 집계
    #  - 월강수량 sum 에 min_count=1 적용 → 해당 월에 강수 관측치가 하나도
    #    없으면(전부 NaN) 0 이 아니라 NaN 반환. (V1 수정 2026-05-27)
    #  - "집계일수(일)": 강수량 관측치가 존재한 일수. 진행 중인 당월(M)처럼
    #    부분월인지 호출부가 판별할 수 있도록 추가. (예: 4월 1~15일만 수집된
    #    경우 집계일수=15 → "부분월" 로 표기/제외 가능)
    monthly = df.groupby(["지점명", "연월"]).agg(
        **{
            "월강수량(mm)":     ("일강수량(mm)", lambda s: s.sum(min_count=1)),
            "유효강수일수(일)": ("유효강수일", "sum"),
            "집계일수(일)":     ("일강수량(mm)", "count"),
            "평균기온(°C)":     ("평균기온(°C)", "mean"),
            "최저기온(°C)":     ("최저기온(°C)", "min"),
            "최고기온(°C)":     ("최고기온(°C)", "max"),
        }
    ).reset_index()

    # 소수점 정리
    monthly["월강수량(mm)"] = monthly["월강수량(mm)"].round(1)
    for col in ["평균기온(°C)", "최저기온(°C)", "최고기온(°C)"]:
        monthly[col] = monthly[col].round(1)

    return monthly


# ==============================================================================
#  ■ 2. 반월(1~15일) 집계
#     기존 HTML 대시보드 v8의 로직과 일치:
#     오늘이 16일 이후이면 M 기간 = 당월 1~15일 (반월)
# ==============================================================================
# aggregate_monthly 와 동일 이유로 hash_funcs={pd.DataFrame: id} 적용.
@st.cache_data(ttl=600, show_spinner=False, max_entries=8, hash_funcs={pd.DataFrame: id})
def aggregate_half_monthly(asos_df: pd.DataFrame) -> pd.DataFrame:
    """
    매월 1~15일 데이터만 집계.

    Returns
    -------
    pd.DataFrame
        컬럼: 지점명, 연월(str), 월강수량(mm)_반월, 유효강수일수(일)_반월
        (연월은 해당 월 전체를 나타내며, 값은 1~15일만 합산된 값)
    """
    if asos_df.empty:
        return pd.DataFrame(columns=["지점명", "연월",
                                     "월강수량(mm)_반월",
                                     "유효강수일수(일)_반월"])

    df = asos_df.copy()
    df["일시"] = pd.to_datetime(df["일시"], errors="coerce")
    df = df.dropna(subset=["일시"])

    # 1~15일만 필터링
    df = df[df["일시"].dt.day <= config.HALF_MONTH_BOUNDARY_DAY].copy()
    if df.empty:
        return pd.DataFrame(columns=["지점명", "연월",
                                     "월강수량(mm)_반월",
                                     "유효강수일수(일)_반월"])

    df["연월"] = df["일시"].dt.strftime("%Y-%m")
    threshold = config.EFFECTIVE_RAINFALL_THRESHOLD_MM
    df["유효강수일"] = (df["일강수량(mm)"] >= threshold).astype(int)

    half = df.groupby(["지점명", "연월"]).agg(
        **{
            "월강수량(mm)_반월":   ("일강수량(mm)", lambda s: s.sum(min_count=1)),
            "유효강수일수(일)_반월": ("유효강수일", "sum"),
            "집계일수(일)_반월":   ("일강수량(mm)", "count"),
        }
    ).reset_index()
    half["월강수량(mm)_반월"] = half["월강수량(mm)_반월"].round(1)
    return half


# ==============================================================================
#  ■ 3. 특정 기간·지점의 실측값 조회
# ==============================================================================
def get_period_value(monthly_df: pd.DataFrame, half_df: pd.DataFrame,
                     period: dict, station: str,
                     metric: str = "월강수량(mm)") -> float | None:
    """
    기간 정보 dict 에 해당하는 실측값을 조회.

    Parameters
    ----------
    monthly_df : pd.DataFrame
        aggregate_monthly() 결과
    half_df : pd.DataFrame
        aggregate_half_monthly() 결과
    period : dict
        period_calculator.compute_periods() 의 한 기간 정보
        (keys: year, month, half, label 등)
    station : str
        지점명 (예: "제주")
    metric : str
        "월강수량(mm)" 또는 "유효강수일수(일)"

    Returns
    -------
    float | None : 값이 없으면 None
    """
    year = period["year"]
    month = period["month"]
    is_half = period.get("half", False)
    ym_str = f"{year}-{month:02d}"

    if is_half:
        # 반월 집계에서 조회
        col = f"{metric}_반월"
        row = half_df[(half_df["지점명"] == station)
                      & (half_df["연월"] == ym_str)]
    else:
        col = metric
        row = monthly_df[(monthly_df["지점명"] == station)
                         & (monthly_df["연월"] == ym_str)]

    if row.empty or col not in row.columns:
        return None

    value = row[col].iloc[0]
    if pd.isna(value):
        return None
    return float(value)


# ==============================================================================
#  ■ 4. 직전 N년 동월 평균
# ==============================================================================
def get_baseline_average(monthly_df: pd.DataFrame, half_df: pd.DataFrame,
                         period: dict, station: str,
                         metric: str = "월강수량(mm)",
                         n_years: int = None) -> tuple[float | None, list[int]]:
    """
    지정 기간의 '직전 N년 동월' 평균을 계산.

    예) M = 2026-04,  N=5 → 2021~2025년 4월 평균
       M-1 = 2026-03, N=5 → 2021~2025년 3월 평균

    반월(M=당월 1~15일) 기간인 경우, '반월 직전평균'(prior years 의 1~15일
    집계, half_df)을 그대로 반환합니다. 실측도 반월이라 동일 단위 비교이므로
    ×0.5 계수는 적용하지 않습니다(적용 시 이중 할인 → 오류). 자세한 배경은
    period_calculator 상단 'L1' 주석 참고.

    Parameters
    ----------
    n_years : int, optional
        기본값: 강수량은 5년, 지하수위는 3년 (config에서 선택)
        여기선 기본 5년 (강수량 분석용)

    Returns
    -------
    tuple (average, years_list)
        average : 평균값 (None이면 데이터 부족)
        years_list : 실제로 평균에 사용된 연도 리스트
    """
    if n_years is None:
        n_years = config.RAINFALL_BASELINE_YEARS

    year = period["year"]
    month = period["month"]
    is_half = period.get("half", False)

    # 직전 N년
    baseline_years = list(range(year - n_years, year))

    values = []
    used_years = []

    for y in baseline_years:
        ym = f"{y}-{month:02d}"
        if is_half:
            col = f"{metric}_반월"
            row = half_df[(half_df["지점명"] == station)
                          & (half_df["연월"] == ym)]
        else:
            col = metric
            row = monthly_df[(monthly_df["지점명"] == station)
                             & (monthly_df["연월"] == ym)]

        if row.empty or col not in row.columns:
            continue

        val = row[col].iloc[0]
        if pd.isna(val):
            continue
        values.append(float(val))
        used_years.append(y)

    if not values:
        return None, []

    return float(np.mean(values)), used_years


# ==============================================================================
#  ■ 5. M-2 / M-1 / M 비교표 생성
# ==============================================================================
# 사용자 요청 2026-05-09: app.py 가 매 rerun 마다 두 번 호출 (강수량 + 유효강수)
# → 캐시 없이는 매 탭 변경 시 재계산. asos_df 는 id 기반, periods·n_years 는
# 기본 hash. inner aggregate_monthly 가 이미 캐시되어 있어도, build_comparison_table
# 자체의 melt + groupby 비용이 추가로 누적되어 캐싱 가치 있음.
@st.cache_data(ttl=600, show_spinner=False, max_entries=8, hash_funcs={pd.DataFrame: id})
def build_comparison_table(asos_df: pd.DataFrame, periods: dict,
                           metric: str = "월강수량(mm)",
                           n_years: int = None) -> pd.DataFrame:
    """
    대시보드의 비교표를 위한 전체 데이터를 생성.

    출력 형태 (예시):
        기간     | 기준연도       | 제주_실측 | 제주_평균 | 서귀포_실측 | ...
        M-2     | 2020~2024     | 82.1      | 65.3     | 90.5       | ...
        M-1     | 2021~2025     | 120.5     | 88.7     | 135.2      | ...
        M       | 2021~2025     | 12.3      | 52.1     | ...         | ...

    Parameters
    ----------
    asos_df : pd.DataFrame
        원본 일별 데이터
    periods : dict
        period_calculator.compute_periods() 결과
        (keys: "M-2", "M-1", "M", "baseline_date")
    metric : str
        "월강수량(mm)" 또는 "유효강수일수(일)"
    n_years : int, optional
        기본 5년 (강수량), config.RAINFALL_BASELINE_YEARS

    Returns
    -------
    pd.DataFrame
    """
    if n_years is None:
        n_years = config.RAINFALL_BASELINE_YEARS

    # 집계 (한 번만)
    monthly = aggregate_monthly(asos_df)
    half = aggregate_half_monthly(asos_df)

    rows = []
    stations = [s["name"] for s in config.STATIONS_ASOS]

    for period_key in ["M-2", "M-1", "M"]:
        if period_key not in periods:
            continue
        p = periods[period_key]

        row = {
            "기간": period_key,
            "연월": p.get("label", f"{p['year']}-{p['month']:02d}"),
        }

        # 직전 N년 기준연도 범위 — '의도된' 윈도우(p.year-n_years ~ p.year-1)로
        # 표기. (V10 수정 2026-05-27) 기존엔 '첫 지점의 used_years' 로 잡혀,
        # 그 지점에 결측 연도가 있으면 표시 범위가 실제와 달라지고 지점마다
        # 다른 연도집합으로 평균이 계산됐는데도 단일 라벨로 보였음. 이제 라벨은
        # 항상 요청한 N년 윈도우를 명확히 나타낸다.
        if n_years >= 1:
            row["기준연도"] = f"{p['year'] - n_years}~{p['year'] - 1}"
        else:
            row["기준연도"] = "-"

        # 각 지점별 실측 & 평균
        for station in stations:
            actual = get_period_value(monthly, half, p, station, metric=metric)
            avg, _used_years = get_baseline_average(
                monthly, half, p, station, metric=metric, n_years=n_years
            )

            row[f"{station}_실측"] = actual
            row[f"{station}_평균"] = round(avg, 1) if avg is not None else None

        rows.append(row)

    df = pd.DataFrame(rows)

    # 컬럼 순서 재정렬: 기간, 연월, 기준연도, 지점별...
    cols = ["기간", "연월", "기준연도"]
    for station in stations:
        cols.extend([f"{station}_실측", f"{station}_평균"])
    df = df.reindex(columns=[c for c in cols if c in df.columns])

    return df


# ==============================================================================
#  ■ 6. 대시보드 간편 조회용 샘플 요약
# ==============================================================================
def summary_for_station(asos_df: pd.DataFrame, station: str,
                        periods: dict) -> dict:
    """
    특정 지점의 M-2·M-1·M 기간별 강수량/유효강수일수 요약을 dict로 반환.
    카드형 메트릭 위젯에 사용.
    """
    monthly = aggregate_monthly(asos_df)
    half = aggregate_half_monthly(asos_df)

    result = {}
    for key in ["M-2", "M-1", "M"]:
        if key not in periods:
            continue
        p = periods[key]
        result[key] = {
            "label":        p.get("label", f"{p['year']}-{p['month']:02d}"),
            "rainfall":     get_period_value(monthly, half, p, station,
                                             "월강수량(mm)"),
            "effective":    get_period_value(monthly, half, p, station,
                                             "유효강수일수(일)"),
            "rainfall_avg": get_baseline_average(monthly, half, p, station,
                                                 "월강수량(mm)")[0],
            "effective_avg": get_baseline_average(monthly, half, p, station,
                                                  "유효강수일수(일)")[0],
        }
    return result


# ==============================================================================
#  ■ 직접 실행 테스트
# ==============================================================================
if __name__ == "__main__":
    # 저장된 ASOS 데이터를 불러와 기본 분석 샘플 출력
    from src.collectors import asos_collector
    from src.analysis import period_calculator

    print("=" * 70)
    print("  📊 유효강수 분석 모듈 테스트 (Build 0.7)")
    print("=" * 70)

    asos = asos_collector.load_asos_data()
    if asos.empty:
        print("❌ ASOS 데이터가 없습니다. 먼저 수집부터:")
        print("   python src/collectors/asos_collector.py --mode latest")
        sys.exit(0)

    print(f"\n📂 ASOS 데이터: {len(asos):,}개")

    periods = period_calculator.compute_periods()
    print(f"\n📅 분석 기간:")
    for k in ["M-2", "M-1", "M"]:
        if k in periods:
            print(f"   {k}: {periods[k].get('label')}")

    # 월별 집계
    monthly = aggregate_monthly(asos)
    print(f"\n📊 월별 집계: {len(monthly)}개 레코드")
    print(monthly.tail(8).to_string(index=False))

    # 비교표
    print(f"\n📋 강수량 비교표 (직전 5년):")
    table = build_comparison_table(asos, periods, metric="월강수량(mm)")
    print(table.to_string(index=False))

    print(f"\n📋 유효강수일수 비교표 (직전 5년, 5mm 기준):")
    table2 = build_comparison_table(asos, periods, metric="유효강수일수(일)")
    print(table2.to_string(index=False))
