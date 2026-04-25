# ==============================================================================
#  제주도 지하수위·강수량 분석 대시보드
#  파일명: src/analysis/period_calculator.py
#  모듈: M-2·M-1·M 기간 계산기
# ------------------------------------------------------------------------------
#  Build: 0.5
#  최종 수정일: 2026-04-22
# ------------------------------------------------------------------------------
#  Changelog:
#  - v0.5 (2026-04-22): 최초 생성.
#                       기존 HTML 대시보드(v8)의 기간 계산 로직을 Python으로 이식.
#                       * 기준일 1~15일  → M=전월,   M-1=전전월, M-2=3개월전
#                       * 기준일 16~말일 → M=당월(1~15일 반월), M-1=전월, M-2=전전월
# ------------------------------------------------------------------------------
#  【이 파일의 역할】
#  "오늘을 기준으로 어느 기간을 분석해야 하는지"를 계산합니다.
#  대시보드의 모든 M-2·M-1·M 분석은 이 모듈의 결과를 기반으로 합니다.
#
#  【사용 예】
#  >>> from src.analysis.period_calculator import compute_periods
#  >>> periods = compute_periods()   # 오늘 기준
#  >>> periods["M"]                 # 현재 기간
#  {'year': 2026, 'month': 4, 'half': True, 'label': '2026년 4월(1~15)', ...}
#
#  【원본 HTML 대시보드의 로직】
#  - 기준일 1~15일  → 전월=M,  전전월=M-1, 3개월전=M-2
#  - 기준일 16~말일 → 당월1~15일=M, 전월=M-1, 전전월=M-2
#                     (M 기간의 직전평균에 ×0.5 계수 적용)
#  - 비교 기준연도: 각 기간(M-2·M-1·M)의 연도 기준으로 독립 계산
#    예) M-2 = 2025년 12월 → 직전 5년 기준: 2020~2024년
#        M   = 2026년 2월  → 직전 5년 기준: 2021~2025년
# ==============================================================================

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[2]))

from datetime import date, timedelta
from typing import Optional
import calendar

import config


# ==============================================================================
#  ■ 유틸리티: 월 단위 계산
# ==============================================================================
def _shift_months(year: int, month: int, delta: int) -> tuple[int, int]:
    """
    (year, month)에서 delta 개월만큼 이동한 결과를 반환.
    delta가 음수면 과거로 이동.

    예) _shift_months(2026, 1, -1) → (2025, 12)
       _shift_months(2026, 4, -3) → (2026, 1)
       _shift_months(2025, 11, 3) → (2026, 2)
    """
    total = year * 12 + (month - 1) + delta
    return total // 12, (total % 12) + 1


def _last_day_of_month(year: int, month: int) -> int:
    """해당 월의 말일을 반환 (평년/윤년 자동 처리)"""
    return calendar.monthrange(year, month)[1]


# ==============================================================================
#  ■ 메인 함수: 기간 계산
# ==============================================================================
def compute_periods(base_date: Optional[date] = None) -> dict:
    """
    기준일에 따라 M-2·M-1·M 기간을 계산합니다.

    Parameters
    ----------
    base_date : date, optional
        기준일. 기본값은 오늘.

    Returns
    -------
    dict
        {
          "base_date": date,          # 기준일
          "mode": "full" or "half",   # 전체월 또는 반월
          "M":   {...},               # 현재 기간
          "M-1": {...},               # 한 기간 전
          "M-2": {...},               # 두 기간 전
        }

        각 기간 dict 구조:
        {
          "year": int,           # 연도
          "month": int,          # 월
          "half": bool,          # 반월(1~15일)인가?
          "label": str,          # 예: "2026년 4월", "2026년 4월(1~15)"
          "short_label": str,    # 예: "2026-04", "2026-04(1-15)"
          "start_date": date,    # 기간 시작일
          "end_date": date,      # 기간 종료일
          "coefficient": float,  # 직전평균에 곱할 계수 (반월=0.5, 전체월=1.0)
          "baseline_years": list # 비교 기준 연도 (직전 N년)
        }
    """
    if base_date is None:
        base_date = date.today()

    if base_date.day <= config.HALF_MONTH_BOUNDARY_DAY:
        # === 모드 1: 전월 모드 (기준일 1~15일) ===
        #   M = 전월, M-1 = 전전월, M-2 = 3개월전
        mode = "full"
        m_y, m_m = _shift_months(base_date.year, base_date.month, -1)
        m_is_half = False
    else:
        # === 모드 2: 반월 모드 (기준일 16~말일) ===
        #   M = 당월(1~15일 반월), M-1 = 전월, M-2 = 전전월
        mode = "half"
        m_y, m_m = base_date.year, base_date.month
        m_is_half = True

    # M-1, M-2는 모드와 무관하게 항상 '전체 월' 단위
    m1_y, m1_m = _shift_months(m_y, m_m, -1)
    m2_y, m2_m = _shift_months(m_y, m_m, -2)

    return {
        "base_date": base_date,
        "mode": mode,
        "M":   _build_period_info(m_y,  m_m,  half=m_is_half),
        "M-1": _build_period_info(m1_y, m1_m, half=False),
        "M-2": _build_period_info(m2_y, m2_m, half=False),
    }


def _build_period_info(year: int, month: int, half: bool) -> dict:
    """단일 기간 정보 빌더 (내부 헬퍼)"""
    if half:
        start = date(year, month, 1)
        end = date(year, month, 15)
        label = f"{year}년 {month}월(1~15)"
        short = f"{year}-{month:02d}(1-15)"
        coefficient = config.HALF_MONTH_M_COEFFICIENT  # 반월=0.5
    else:
        start = date(year, month, 1)
        end = date(year, month, _last_day_of_month(year, month))
        label = f"{year}년 {month}월"
        short = f"{year}-{month:02d}"
        coefficient = 1.0

    # 비교 기준 연도: 해당 기간의 연도에서 직전 N년
    # 예) 2026년 2월의 직전 5년 = [2021, 2022, 2023, 2024, 2025]
    baseline_years_rain = list(range(
        year - config.RAINFALL_BASELINE_YEARS, year
    ))  # 강수량: 직전 5년
    baseline_years_gw = list(range(
        year - config.GWLEVEL_BASELINE_YEARS, year
    ))  # 지하수위: 직전 3년

    return {
        "year": year,
        "month": month,
        "half": half,
        "label": label,
        "short_label": short,
        "start_date": start,
        "end_date": end,
        "coefficient": coefficient,
        "baseline_years_rainfall": baseline_years_rain,
        "baseline_years_gwlevel": baseline_years_gw,
    }


# ==============================================================================
#  ■ 보조 함수: 기간에 해당하는 데이터 필터링
# ==============================================================================
def filter_period_data(df, date_column: str, period: dict):
    """
    DataFrame에서 특정 기간의 데이터만 추출합니다.

    Parameters
    ----------
    df : pd.DataFrame
        일자 컬럼을 포함한 DataFrame
    date_column : str
        일자 컬럼명 (예: "일시")
    period : dict
        compute_periods() 결과의 한 항목

    Returns
    -------
    pd.DataFrame
        해당 기간에 속하는 행들
    """
    import pandas as pd
    if df.empty:
        return df

    dt_col = pd.to_datetime(df[date_column])
    mask = (dt_col >= pd.Timestamp(period["start_date"])) & \
           (dt_col <= pd.Timestamp(period["end_date"]))
    return df[mask].copy()


def filter_baseline_period(df, date_column: str, period: dict,
                            year: int, for_gwlevel: bool = False):
    """
    직전 N년 비교를 위해 '특정 연도의 같은 월' 데이터를 추출합니다.

    예) period={2026년 2월}, year=2023 → 2023년 2월 데이터

    Parameters
    ----------
    df : pd.DataFrame
    date_column : str
    period : dict
        현재 기간 정보 (month, half를 사용)
    year : int
        대상 연도
    for_gwlevel : bool
        False이면 강수량용(5년), True이면 지하수위용(3년)
        (필터링 결과 자체에는 영향 없음, 기록용)

    Returns
    -------
    pd.DataFrame
    """
    import pandas as pd
    if df.empty:
        return df

    month = period["month"]
    dt_col = pd.to_datetime(df[date_column])

    if period["half"]:
        start = date(year, month, 1)
        end = date(year, month, 15)
    else:
        start = date(year, month, 1)
        end = date(year, month, _last_day_of_month(year, month))

    mask = (dt_col >= pd.Timestamp(start)) & (dt_col <= pd.Timestamp(end))
    return df[mask].copy()


# ==============================================================================
#  ■ 직접 실행 시 (테스트/데모)
# ==============================================================================
if __name__ == "__main__":
    print("=" * 70)
    print("  📅 M-2·M-1·M 기간 계산기 테스트")
    print("=" * 70)

    # 테스트 케이스들
    test_cases = [
        ("오늘 (실제)",     None),
        ("2026-04-22",     date(2026, 4, 22)),   # 22일 → 반월 모드
        ("2026-04-10",     date(2026, 4, 10)),   # 10일 → 전월 모드
        ("2026-04-15",     date(2026, 4, 15)),   # 15일 경계 → 전월 모드
        ("2026-04-16",     date(2026, 4, 16)),   # 16일 경계 → 반월 모드
        ("2026-01-20",     date(2026, 1, 20)),   # 연초 반월 (전년도 넘어감)
        ("2026-01-05",     date(2026, 1, 5)),    # 연초 전월 (전년도 넘어감)
    ]

    for name, d in test_cases:
        print(f"\n▶ {name}")
        periods = compute_periods(d)
        print(f"  기준일: {periods['base_date']} (요일: {periods['base_date'].strftime('%A')})")
        print(f"  모드  : {periods['mode']}")
        for key in ["M-2", "M-1", "M"]:
            p = periods[key]
            print(f"  {key}: {p['label']:20s}"
                  f"  [{p['start_date']} ~ {p['end_date']}]"
                  f"  계수={p['coefficient']}"
                  f"  기준년(강수량)={p['baseline_years_rainfall']}")
