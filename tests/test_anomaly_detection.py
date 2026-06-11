# ==============================================================================
#  파일명: tests/test_anomaly_detection.py
#  목적: usage 이상값 절대 임계 정책 회귀 가드.
#       V4 권장(2026-05-11) — 음수 / 1e8 초과 / 미래연도 카운트.
# ==============================================================================
import pandas as pd


def test_detect_usage_anomalies_three_classes():
    from src.analysis.anomaly_detection import (
        USAGE_VOLUME_HARD_MAX,
        detect_usage_anomalies,
    )

    df = pd.DataFrame(
        {
            "permit_no": ["A", "B", "C", "D"],
            "year":      [2024, 2024, 2024, 2099],   # D 는 미래
            "month":     [1, 2, 3, 4],
            "volume_m3": [100.0, -50.0, USAGE_VOLUME_HARD_MAX + 1, 200.0],
        }
    )

    out = detect_usage_anomalies(df, current_year=2026)

    assert list(out["is_anomaly"]) == [False, True, True, True]
    assert out.loc[1, "anomaly_reason"] == "음수"
    assert "초과" in out.loc[2, "anomaly_reason"]
    assert "미래" in out.loc[3, "anomaly_reason"]


def test_detect_usage_anomalies_empty_df():
    from src.analysis.anomaly_detection import detect_usage_anomalies

    empty = pd.DataFrame(columns=["volume_m3", "year"])
    out = detect_usage_anomalies(empty)
    # 빈 DF 그대로 반환 — KeyError/IndexError 없음
    assert len(out) == 0


def test_detect_usage_anomalies_does_not_mutate_input():
    from src.analysis.anomaly_detection import detect_usage_anomalies

    df = pd.DataFrame({"volume_m3": [1.0, 2.0], "year": [2024, 2024]})
    original = df.copy()
    _ = detect_usage_anomalies(df, current_year=2026)
    pd.testing.assert_frame_equal(df, original)
