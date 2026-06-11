# ==============================================================================
#  파일명: tests/test_period_calculator.py
#  목적: M-2 · M-1 · M 기간 계산 결정성 보호.
#       V4 권장(2026-05-11) — 달력 경계/반월 분기 회귀 가드.
# ==============================================================================
from datetime import date


def test_full_mode_early_month():
    """기준일 1~15일 → M=전월, M-1=전전월, M-2=3개월전."""
    from src.analysis.period_calculator import compute_periods

    p = compute_periods(base_date=date(2026, 2, 5))
    assert p["mode"] == "full"
    assert (p["M"]["year"], p["M"]["month"], p["M"]["half"]) == (2026, 1, False)
    assert (p["M-1"]["year"], p["M-1"]["month"]) == (2025, 12)
    assert (p["M-2"]["year"], p["M-2"]["month"]) == (2025, 11)


def test_half_mode_late_month():
    """기준일 16~말일 → M=당월 반월(1~15), M-1=전월, M-2=전전월."""
    from src.analysis.period_calculator import compute_periods

    p = compute_periods(base_date=date(2026, 2, 20))
    assert p["mode"] == "half"
    assert (p["M"]["year"], p["M"]["month"], p["M"]["half"]) == (2026, 2, True)
    assert (p["M-1"]["year"], p["M-1"]["month"]) == (2026, 1)
    assert (p["M-2"]["year"], p["M-2"]["month"]) == (2025, 12)


def test_january_boundary():
    """1월 5일 → M=전년 12월, M-2=전년 10월. 연도 경계 회귀."""
    from src.analysis.period_calculator import compute_periods

    p = compute_periods(base_date=date(2026, 1, 5))
    assert (p["M"]["year"], p["M"]["month"]) == (2025, 12)
    assert (p["M-2"]["year"], p["M-2"]["month"]) == (2025, 10)


def test_shift_months_helper():
    from src.analysis.period_calculator import _shift_months

    assert _shift_months(2026, 1, -1) == (2025, 12)
    assert _shift_months(2026, 1, -3) == (2025, 10)
    assert _shift_months(2025, 11, 3) == (2026, 2)
    assert _shift_months(2026, 12, 1) == (2027, 1)
