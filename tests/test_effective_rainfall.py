# ==============================================================================
#  파일명: tests/test_effective_rainfall.py
#  목적: effective_rainfall 의 월·반월 집계 + 유효강수일 정의 회귀 가드.
#       V4 권장 후속(2026-05-11) — 정의 변경 시 tab2 전체 수치 이동 위험.
# ==============================================================================
import pandas as pd


def setup_function(_fn):
    """각 테스트 시작 전 cache 초기화.

    aggregate_monthly 는 hash_funcs={pd.DataFrame: id} 캐시이므로 테스트 간
    DataFrame 가 GC 된 뒤 ID 재사용으로 stale 결과를 반환할 수 있음. 명시적
    clear 로 결정성 확보 (streamlit bare mode 에서도 동작).
    """
    try:
        from src.analysis.effective_rainfall import aggregate_monthly
        aggregate_monthly.clear()
    except Exception:
        pass


def _make_asos(days, value):
    """단일 지점 'X' 의 days × value 일강수량 ASOS DataFrame."""
    return pd.DataFrame(
        {
            "지점명": ["X"] * len(days),
            "일시": days,
            "일강수량(mm)": [value] * len(days),
            "평균기온(°C)": [10.0] * len(days),
            "최저기온(°C)": [5.0] * len(days),
            "최고기온(°C)": [15.0] * len(days),
        }
    )


def test_aggregate_monthly_empty_returns_empty_schema():
    from src.analysis.effective_rainfall import aggregate_monthly

    out = aggregate_monthly(pd.DataFrame())
    assert out.empty
    # 빈 결과여도 스키마 컬럼은 존재
    assert "월강수량(mm)" in out.columns
    assert "유효강수일수(일)" in out.columns


def test_aggregate_monthly_effective_rainfall_threshold():
    """일강수량 >= 5mm 만 유효강수일로 카운트 (config.EFFECTIVE_RAINFALL_THRESHOLD_MM)."""
    from src.analysis.effective_rainfall import aggregate_monthly

    # 2026년 1월 1~10일 — 5개 5mm, 5개 3mm
    days = pd.date_range("2026-01-01", "2026-01-10")
    values = [5.0, 3.0, 5.0, 3.0, 5.0, 3.0, 5.0, 3.0, 5.0, 3.0]
    df = pd.DataFrame(
        {
            "지점명": ["X"] * 10,
            "일시": days,
            "일강수량(mm)": values,
            "평균기온(°C)": [10.0] * 10,
            "최저기온(°C)": [5.0] * 10,
            "최고기온(°C)": [15.0] * 10,
        }
    )
    out = aggregate_monthly(df)
    assert len(out) == 1
    row = out.iloc[0]
    assert row["연월"] == "2026-01"
    # 5mm × 5 + 3mm × 5 = 40mm
    assert row["월강수량(mm)"] == 40.0
    # 5mm 인 날만 유효 → 5일
    assert int(row["유효강수일수(일)"]) == 5


def test_aggregate_monthly_handles_invalid_date():
    """비표준 일시 행이 섞여 있어도 전체가 죽지 않고 dropna 되어야 한다 (Phase B #13)."""
    from src.analysis.effective_rainfall import aggregate_monthly

    df = pd.DataFrame(
        {
            "지점명": ["X", "X", "X"],
            "일시": ["2026-01-01", "INVALID", "2026-01-02"],
            "일강수량(mm)": [10.0, 99.0, 5.0],
            "평균기온(°C)": [10.0, 10.0, 10.0],
            "최저기온(°C)": [5.0, 5.0, 5.0],
            "최고기온(°C)": [15.0, 15.0, 15.0],
        }
    )
    out = aggregate_monthly(df)
    # 잘못된 행은 제외되고 정상 2일치만 집계
    assert len(out) == 1
    assert out.iloc[0]["월강수량(mm)"] == 15.0
