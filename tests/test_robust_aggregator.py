# ==============================================================================
#  파일명: tests/test_robust_aggregator.py
#  테스트: 로버스트-베이지안 유역 대표값 모듈 (src/analysis/robust_aggregator.py)
# ------------------------------------------------------------------------------
#  Build: 1.0  (2026-06-11)
#  검증 항목:
#   1. Biweight 위치추정 — 이상치 저항 (조천 N_drop 시나리오 재현)
#   2. anomaly 행렬 — 자기 3년 동월 평균 대비, baseline 부족 시 NaN
#   3. 계층 Gibbs (E·F) — 알려진 θ 복원 + Student-t 이상치 저항 + shrinkage
#   4. compute_methods_for_month — 7개 방식 산출·스키마
#   5. partial_month_biweight — 부분월 관측소 anomaly → Biweight
# ==============================================================================

import numpy as np
import pandas as pd
import pytest

from src.analysis import robust_aggregator as ra


# ──────────────────────────────────────────────────────────────────────────
#  1. Biweight
# ──────────────────────────────────────────────────────────────────────────
def test_biweight_resists_outlier():
    """이상치 1개(−8 m)가 위치 추정을 지배하지 못해야 한다 (REF 의 핵심 문제)."""
    x = np.array([0.10, 0.15, 0.05, 0.12, 0.08, -8.0])
    bw = ra.biweight_location(x)
    assert abs(bw - 0.10) < 0.15, f"Biweight={bw} — 이상치에 끌려감"
    # 단순평균은 끌려가야 함 (대조군)
    assert np.mean(x) < -1.0


def test_biweight_small_sample_median_fallback():
    assert ra.biweight_location(np.array([1.0])) == 1.0
    assert ra.biweight_location(np.array([1.0, 3.0])) == 2.0
    assert np.isnan(ra.biweight_location(np.array([])))


def test_biweight_zero_mad():
    """동일값 표본 (MAD=0) → 중앙값 폴백, 0-division 없어야."""
    x = np.array([2.0, 2.0, 2.0, 2.0])
    assert ra.biweight_location(x) == 2.0


# ──────────────────────────────────────────────────────────────────────────
#  2. anomaly 행렬
# ──────────────────────────────────────────────────────────────────────────
def _toy_matrix():
    """관측소 2개 × 2022~2025 5월 EL. S1 은 표고 높음(50m), S2 낮음(5m)."""
    data = {
        "2022-05": [50.0, 5.0],
        "2023-05": [51.0, 5.5],
        "2024-05": [52.0, 6.0],
        "2025-05": [54.0, 4.5],
    }
    return pd.DataFrame(data, index=["S1", "S2"])


def test_anomaly_matrix_self_baseline():
    mat = _toy_matrix()
    anom = ra.build_anomaly_matrix(mat, n_years=3)
    # S1 2025-05: 54 − mean(50,51,52)=51 → +3.0 (표고와 무관)
    assert anom.loc["S1", "2025-05"] == pytest.approx(3.0)
    # S2 2025-05: 4.5 − mean(5,5.5,6)=5.5 → −1.0
    assert anom.loc["S2", "2025-05"] == pytest.approx(-1.0)
    # 2022-05 는 baseline 없음 → NaN
    assert np.isnan(anom.loc["S1", "2022-05"])


def test_anomaly_matrix_drops_new_station():
    """과거 자료가 전혀 없는 신규 관측소는 NaN (N_drop 왜곡 차단)."""
    mat = _toy_matrix()
    mat.loc["S_new"] = [np.nan, np.nan, np.nan, 7.7]
    anom = ra.build_anomaly_matrix(mat, n_years=3)
    assert np.isnan(anom.loc["S_new", "2025-05"])


# ──────────────────────────────────────────────────────────────────────────
#  3. 계층 Gibbs — E(Normal) · F(Student-t)
# ──────────────────────────────────────────────────────────────────────────
def test_gibbs_recovers_known_theta():
    rng = np.random.default_rng(7)
    groups = {f"W{i}": rng.normal(0.8, 0.2, size=10) for i in range(5)}
    res = ra.fit_hierarchical_gibbs(groups, student_t=False)
    for k, v in res.items():
        assert abs(v["mean"] - 0.8) < 0.3, f"{k}: θ={v['mean']}"
        assert v["lo"] < v["mean"] < v["hi"]


def test_student_t_resists_outlier_station():
    """이상 관측소 1개(−9 m)가 섞여도 F 는 군집 중심 부근 유지."""
    rng = np.random.default_rng(3)
    groups = {f"W{i}": rng.normal(0.5, 0.3, size=8) for i in range(4)}
    contaminated = np.concatenate([rng.normal(0.5, 0.3, size=7), [-9.0]])
    groups["W_bad"] = contaminated
    res_f = ra.fit_hierarchical_gibbs(groups, student_t=True)
    # 오염 표본 평균(약 -0.7)이 아니라 군집 중심(0.5) 부근을 유지해야 함
    contaminated_mean = float(np.mean(contaminated))
    assert abs(res_f["W_bad"]["mean"] - 0.5) < 0.4
    assert abs(res_f["W_bad"]["mean"] - 0.5) < abs(contaminated_mean - 0.5)


def test_shrinkage_small_group_toward_island_mean():
    """관측소 2개 소표본 유역은 섬 평균 쪽으로 수축 (중서귀 3정 시나리오)."""
    rng = np.random.default_rng(11)
    groups = {f"W{i}": rng.normal(0.0, 0.2, size=12) for i in range(6)}
    # 소표본 + 극단값 유역
    groups["W_small"] = np.array([-3.0, -2.8])
    res = ra.fit_hierarchical_gibbs(groups, student_t=True)
    # 원시 평균(−2.9)보다 0 쪽으로 수축되어야 함
    assert res["W_small"]["mean"] > -2.9
    assert res["W_small"]["n"] == 2


def test_gibbs_reproducible_with_seed():
    rng = np.random.default_rng(1)
    groups = {f"W{i}": rng.normal(0.3, 0.2, size=6) for i in range(3)}
    r1 = ra.fit_hierarchical_gibbs(groups, student_t=True)
    r2 = ra.fit_hierarchical_gibbs(groups, student_t=True)
    for k in groups:
        assert r1[k]["mean"] == pytest.approx(r2[k]["mean"])


# ──────────────────────────────────────────────────────────────────────────
#  4. compute_methods_for_month — 스키마·산출
# ──────────────────────────────────────────────────────────────────────────
def test_compute_methods_for_month_schema():
    """toy 데이터로 7개 방식 산출 스키마 검증 (config.WATERSHEDS 의 실제 유역명 사용)."""
    import config
    ws1 = config.WATERSHEDS[0]["name"]
    ws2 = config.WATERSHEDS[1]["name"]
    rng = np.random.default_rng(5)
    stations = [f"JD{i:02d}" for i in range(8)]
    station_map = {s: (ws1 if i < 4 else ws2) for i, s in enumerate(stations)}
    cols = [f"{y}-05" for y in (2022, 2023, 2024, 2025)]
    mat = pd.DataFrame(
        rng.normal(20, 1, size=(8, 4)), index=stations, columns=cols)
    anom = ra.build_anomaly_matrix(mat, n_years=3)
    df = ra.compute_methods_for_month(mat, anom, station_map, 2025, 5,
                                      n_years=3, ws_data_all=None)
    assert set(df.columns) == {"유역", "연월", "방법", "편차",
                               "ci_low", "ci_high", "n_station"}
    assert set(df["유역"].unique()) <= {ws1, ws2}
    # REF 는 ws_data_all=None 이라 없어야, A~F 는 있어야
    methods = set(df["방법"].unique())
    assert "REF" not in methods
    assert {"A", "D", "E", "F"} <= methods
    # F 는 CI 보유
    f_rows = df[df["방법"] == "F"]
    assert f_rows["ci_low"].notna().all()


# ──────────────────────────────────────────────────────────────────────────
#  5. partial_month_biweight — 부분월 잠정치
# ──────────────────────────────────────────────────────────────────────────
def test_partial_month_biweight_basic():
    from datetime import date
    rng = np.random.default_rng(9)
    rows = []
    # 관측소 4개 × 2023~2026년 6월 1~9일 일자료. 2026 년에 +0.5 m 상승 신호.
    for st_i in range(4):
        base = 10.0 + st_i * 30.0   # 표고 이질성
        for y in (2023, 2024, 2025, 2026):
            lift = 0.5 if y == 2026 else 0.0
            for d in range(1, 10):
                rows.append({
                    "관측소명": f"JD{st_i}",
                    "날짜": pd.Timestamp(year=y, month=6, day=d),
                    "EL": base + lift + rng.normal(0, 0.05),
                })
    daily = pd.DataFrame(rows)
    smap = {f"JD{i}": "구좌" for i in range(4)}
    out = ra.partial_month_biweight(daily, smap, date(2026, 6, 10), n_years=3)
    assert "구좌" in out
    assert out["구좌"]["n"] == 4
    assert out["구좌"]["dev"] == pytest.approx(0.5, abs=0.15)


def test_partial_month_biweight_day1_empty():
    """기준일이 1일이면 부분월 의미 없음 → 빈 dict."""
    from datetime import date
    daily = pd.DataFrame({"관측소명": ["A"], "날짜": [pd.Timestamp("2026-06-01")],
                          "EL": [1.0]})
    out = ra.partial_month_biweight(daily, {"A": "구좌"}, date(2026, 6, 1), 3)
    assert out == {}
