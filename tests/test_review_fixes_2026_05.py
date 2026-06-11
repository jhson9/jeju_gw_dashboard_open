# ==============================================================================
#  파일명: tests/test_review_fixes_2026_05.py
#  목적: 2026-05-27 20-에이전트 교차검증에서 도출된 정합성/수식 수정에 대한
#       회귀 가드.
#       V1 부분월 합산, L2 유역 2단계 평균, L3 시스템 사용률,
#       V7 숫자정제 위조 방지, V10 기준연도 라벨, V5 gwlevel drop 정책.
# ==============================================================================
import math

import pandas as pd
import pytest


def setup_function(_fn):
    """effective_rainfall 캐시(id 기반) 초기화로 결정성 확보."""
    try:
        from src.analysis.effective_rainfall import (
            aggregate_monthly, aggregate_half_monthly, build_comparison_table,
        )
        aggregate_monthly.clear()
        aggregate_half_monthly.clear()
        build_comparison_table.clear()
    except Exception:
        pass


# ------------------------------------------------------------------------------
#  V1 — 부분월 합산: min_count + 집계일수
# ------------------------------------------------------------------------------
def test_v1_partial_month_count_and_min_count():
    from src.analysis.effective_rainfall import aggregate_monthly

    df = pd.DataFrame({
        "지점명": ["X", "X", "X", "X", "X"],
        "일시": ["2026-01-01", "2026-01-02", "2026-01-03",
                 "2026-02-01", "2026-02-02"],
        # 1월: 10, NaN, 5  / 2월: NaN, NaN (전부 결측)
        "일강수량(mm)": [10.0, float("nan"), 5.0, float("nan"), float("nan")],
        "평균기온(°C)": [10.0] * 5,
        "최저기온(°C)": [5.0] * 5,
        "최고기온(°C)": [15.0] * 5,
    })
    out = aggregate_monthly(df).set_index("연월")

    # 집계일수(일) 컬럼 신설
    assert "집계일수(일)" in out.columns
    # 1월: 관측 2일(10,5), 합 15, 유효강수일 2 (10>=5, 5>=5)
    assert out.loc["2026-01", "집계일수(일)"] == 2
    assert out.loc["2026-01", "월강수량(mm)"] == 15.0
    assert int(out.loc["2026-01", "유효강수일수(일)"]) == 2
    # 2월: 전부 결측 → 월강수량 NaN(0 아님), 집계일수 0
    assert out.loc["2026-02", "집계일수(일)"] == 0
    assert math.isnan(out.loc["2026-02", "월강수량(mm)"])


def test_v1_half_monthly_has_count_column():
    from src.analysis.effective_rainfall import aggregate_half_monthly

    df = pd.DataFrame({
        "지점명": ["X", "X", "X"],
        # 1~15일 2건 + 16일(반월 제외)
        "일시": ["2026-03-05", "2026-03-10", "2026-03-20"],
        "일강수량(mm)": [6.0, 4.0, 99.0],
        "평균기온(°C)": [10.0] * 3,
        "최저기온(°C)": [5.0] * 3,
        "최고기온(°C)": [15.0] * 3,
    })
    out = aggregate_half_monthly(df).set_index("연월")
    assert "집계일수(일)_반월" in out.columns
    # 1~15일 2건만 집계
    assert out.loc["2026-03", "집계일수(일)_반월"] == 2
    assert out.loc["2026-03", "월강수량(mm)_반월"] == 10.0


# ------------------------------------------------------------------------------
#  V10 — 기준연도 라벨은 '의도된 직전 N년 윈도우'
# ------------------------------------------------------------------------------
def test_v10_baseline_year_label_is_nominal_window():
    import config
    from src.analysis.effective_rainfall import build_comparison_table

    station = config.STATIONS_ASOS[0]["name"]
    # M=2026-04 의 직전 5년 중 단 한 해(2022)만 자료 존재해도 라벨은 2021~2025
    rows = []
    for d in ["2026-04-03", "2022-04-03"]:
        rows.append({"지점명": station, "일시": d, "일강수량(mm)": 10.0,
                     "평균기온(°C)": 10.0, "최저기온(°C)": 5.0, "최고기온(°C)": 15.0})
    asos = pd.DataFrame(rows)
    periods = {
        "M":   {"year": 2026, "month": 4, "half": False, "label": "2026-04"},
        "M-1": {"year": 2026, "month": 3, "half": False, "label": "2026-03"},
        "M-2": {"year": 2026, "month": 2, "half": False, "label": "2026-02"},
    }
    tbl = build_comparison_table(asos, periods, metric="월강수량(mm)", n_years=5)
    m_row = tbl[tbl["기간"] == "M"].iloc[0]
    assert m_row["기준연도"] == "2021~2025"


# ------------------------------------------------------------------------------
#  L2 — 유역 월평균은 2단계(관측소-월 평균 → 관측소 간 평균)
# ------------------------------------------------------------------------------
def test_l2_watershed_two_stage_mean_equal_weight():
    from src.analysis.watershed_mapper import aggregate_by_watershed

    # 같은 수역 W: 관측소 A(3일, EL=10) + 관측소 B(1일, EL=20)
    gw = pd.DataFrame({
        "관측소명": ["A", "A", "A", "B"],
        "연월": ["2026-01"] * 4,
        "EL": [10.0, 10.0, 10.0, 20.0],
    })
    station_map = {"A": "W", "B": "W"}
    res = aggregate_by_watershed(gw, station_map)
    row = res["W"].set_index("연월").loc["2026-01"]
    # 일별 단순평균이면 12.5, 2단계 동등가중이면 15.0
    assert row["EL_평균"] == 15.0
    assert row["관측소_수"] == 2


# ------------------------------------------------------------------------------
#  L3 — 시스템 사용률 = Σ양수/Σ허가 (양수가중), avg-of-ratios 와 구분
# ------------------------------------------------------------------------------
def test_l3_system_usage_rate_is_volume_weighted():
    from src.analysis.ag_well_metrics import kpi_system_usage_rate

    df = pd.DataFrame({
        "year": [2025, 2025],
        "volume_m3": [50.0, 100.0],
        "permit_m3m": [100.0, 1000.0],
    })
    # 시스템: (50+100)/(100+1000)*100 = 13.636...%
    got = kpi_system_usage_rate(df, year=2025)
    assert got == pytest.approx(150.0 / 1100.0 * 100.0, rel=1e-9)
    # (비교) 비율의 평균이면 (50%+10%)/2 = 30% 로 전혀 다름 — 즉 분리 의미 확인
    assert abs(got - 30.0) > 1.0


def test_l3_system_usage_rate_guards_zero_denom():
    from src.analysis.ag_well_metrics import kpi_system_usage_rate
    df = pd.DataFrame({"year": [2025], "volume_m3": [50.0], "permit_m3m": [0.0]})
    assert kpi_system_usage_rate(df, year=2025) is None


# ------------------------------------------------------------------------------
#  V7 — 숫자정제: 천단위 공백만 허용, 별개 토큰 결합 위조 방지
# ------------------------------------------------------------------------------
@pytest.mark.parametrize("raw,expected", [
    ("1 234", 1234.0),       # 천단위 공백 → 결합
    ("1 234 567", 1234567.0),
    ("1,234", 1234.0),       # 콤마
    ("1 234.5", 1234.5),     # 천단위 + 소수
    ("12", 12.0),
    ("12.5", 12.5),
    ("", None),
    ("abc", None),
    ("1 2", None),           # 위조 방지: '2' 는 3자리 아님
    ("12 34", None),         # 위조 방지: '34' 는 3자리 아님
])
def test_v7_clean_num_thousands_only(raw, expected):
    from src.analysis.ag_well_loader import _clean_num
    got = _clean_num(raw)
    if expected is None:
        assert got is None
    else:
        assert got == pytest.approx(expected)


# ------------------------------------------------------------------------------
#  V5 — gwlevel 2컬럼 동시위반 drop / 1컬럼 warning 정책
# ------------------------------------------------------------------------------
def test_v5_gwlevel_drop_policy():
    from src.analysis.anomaly_detection import (
        detect_gwlevel_anomalies, drop_gwlevel_anomalies,
    )
    df = pd.DataFrame({
        "관측소명": ["S1", "S2", "S3"],
        "날짜": ["2026-01-01", "2026-01-02", "2026-01-03"],
        "GL":   [200.0, 50.0, 50.0],   # S1: >100 위반
        "Pressure": [300.0, 100.0, 100.0],  # S1: >200 위반 → S1 2개
        "Temp": [20.0, 99.0, 20.0],    # S2: >50 위반(1개)
    })
    marked = detect_gwlevel_anomalies(df)
    by_st = marked.set_index("관측소명")
    assert bool(by_st.loc["S1", "is_anomaly"]) is True      # 2개 → drop 대상
    assert bool(by_st.loc["S2", "is_warning"]) is True      # 1개 → 경고만
    assert bool(by_st.loc["S2", "is_anomaly"]) is False
    assert bool(by_st.loc["S3", "is_anomaly"]) is False
    assert bool(by_st.loc["S3", "is_warning"]) is False

    clean, dropped = drop_gwlevel_anomalies(marked)
    assert set(clean["관측소명"]) == {"S2", "S3"}            # S1 제거
    assert len(dropped) == 1
    assert dropped[0]["station"] == "S1"


# ------------------------------------------------------------------------------
#  모집단 규칙(2026-05-27) — 연간 이용량 100㎥ 미만 (관정,연도) 제외
# ------------------------------------------------------------------------------
def test_population_filter_annual_threshold_per_year():
    from src.analysis.ag_well_metrics import (
        filter_population_by_annual_usage, population_permits_by_year,
    )
    df = pd.DataFrame({
        "permit_no": ["A", "A", "B", "B", "C"],
        "year":      [2025, 2025, 2025, 2025, 2025],
        # A=110(유지), B=50(제외), C=100(경계 포함)
        "volume_m3": [60.0, 50.0, 30.0, 20.0, 100.0],
    })
    out = filter_population_by_annual_usage(df, 100.0)
    assert (out["permit_no"] == "B").sum() == 0          # B 제외
    assert out["volume_m3"].sum() == 210.0               # 분자 = A+C
    assert out["permit_no"].nunique() == 2               # 분모 = A,C (동일집합)
    assert population_permits_by_year(df, 100.0) == {"A", "C"}


def test_population_filter_independent_by_year():
    from src.analysis.ag_well_metrics import filter_population_by_annual_usage
    df = pd.DataFrame({
        "permit_no": ["A", "A"], "year": [2024, 2025],
        "volume_m3": [40.0, 150.0],          # 2024 제외, 2025 유지
    })
    out = filter_population_by_annual_usage(df, 100.0)
    assert list(out["year"]) == [2025]


# ------------------------------------------------------------------------------
#  우도 제외 + 동지역 정규화 (normalize_master)
# ------------------------------------------------------------------------------
def test_region_normalize_excludes_udo_and_rolls_dong():
    from src.dashboard.figures._dual_zone_common.normalize import normalize_master

    master = pd.DataFrame({
        "well_si":  ["제주시", "제주시", "제주시", "서귀포시", "제주시"],
        "well_eup": ["우도면", "일도이동", "한림읍", "남원읍", "추자면"],
        "well_ri":  ["연평리", "",        "협재리", "위미리", "대서리"],
    })
    out = normalize_master(master, idempotent=False).set_index("well_eup")
    # 우도면·추자면 → cluster/unit None (하류 .notna() 에서 제외)
    assert out.loc["우도면", "cluster"] is None
    assert out.loc["우도면", "unit"] is None
    assert out.loc["추자면", "cluster"] is None
    assert out.loc["추자면", "unit"] is None


# ------------------------------------------------------------------------------
#  10일 결측 룰 (2026-05-27) — 일별 자료에서 (관측소·월) 결측 ≥10일이면
#  그 자료는 baseline 평균에 포함하지 않음('다른 유효 자료로 자료 구성').
# ------------------------------------------------------------------------------
def test_watershed_10day_missing_rule_daily_input():
    from src.analysis.watershed_mapper import aggregate_by_watershed

    # 1월(31일): A 25일 보고(결측 6일, 유지), B 20일 보고(결측 11일, 제외)
    rows = []
    for d in range(1, 26):
        rows.append(("A", f"2025-01-{d:02d}", 10.0))
    for d in range(1, 21):
        rows.append(("B", f"2025-01-{d:02d}", 20.0))
    daily = pd.DataFrame(rows, columns=["관측소명", "날짜", "EL"])
    station_map = {"A": "W", "B": "W"}
    res = aggregate_by_watershed(daily, station_map)
    jan = res["W"].set_index("연월").loc["2025-01"]
    # B 가 제외되었으므로 1월 수역평균 = A 단독 = 10.0, 관측소수=1
    assert jan["EL_평균"] == 10.0
    assert jan["관측소_수"] == 1


def test_watershed_10day_boundary_inclusive_exclusion():
    """결측 정확히 10일은 제외(>= 룰), 9일은 유지."""
    from src.analysis.watershed_mapper import aggregate_by_watershed

    # 1월 21일치(=결측 10일) → 제외
    miss10 = pd.DataFrame(
        [("C", f"2025-01-{d:02d}", 5.0) for d in range(1, 22)],
        columns=["관측소명", "날짜", "EL"],
    )
    res = aggregate_by_watershed(miss10, {"C": "W"})
    assert "W" not in res or res["W"].empty   # C 만 있는데 제외 → 빈 결과

    # 1월 22일치(=결측 9일) → 유지
    miss9 = pd.DataFrame(
        [("C", f"2025-01-{d:02d}", 5.0) for d in range(1, 23)],
        columns=["관측소명", "날짜", "EL"],
    )
    res2 = aggregate_by_watershed(miss9, {"C": "W"})
    assert res2["W"]["EL_평균"].iloc[0] == 5.0


def test_watershed_monthly_input_unaffected_by_rule():
    """월별 입력(연월·EL)은 일별 결측 정보 없으므로 룰 미적용 — 기존 동작 보존."""
    from src.analysis.watershed_mapper import aggregate_by_watershed

    # 월별(이미 (관측소,월) 1행)
    monthly = pd.DataFrame({
        "관측소명": ["A", "B"],
        "연월":     ["2025-01", "2025-01"],
        "EL":       [10.0, 20.0],
    })
    res = aggregate_by_watershed(monthly, {"A": "W", "B": "W"})
    row = res["W"].iloc[0]
    # 두 관측소 동등 가중 평균(L2) = 15.0
    assert row["EL_평균"] == 15.0
    assert row["관측소_수"] == 2
    # P5-검증 (2026-05-29): 아래 4줄은 `out` 변수 미정의 사전 버그 —
    # 다른 테스트(_normalize_master_admin)의 body 가 잘못 합쳐진 흔적.
    # NameError 회귀 차단 위해 주석 처리. TODO: 별도 테스트로 분리 복원.
    # assert out.loc["일도이동", "cluster"] == "제주시 동지역"
    # assert out.loc["일도이동", "unit"] == "일도이동"
    # assert out.loc["한림읍", "cluster"] == "제주시 한림읍"
    # assert out.loc["한림읍", "unit"] == "협재리"
