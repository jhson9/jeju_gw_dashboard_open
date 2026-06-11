# ==============================================================================
#  파일명: tests/test_ag_well_loader_clean.py
#  목적: ag_well_loader 의 토큰/숫자 클리닝 순수함수 회귀 가드.
#       V4 권장(2026-05-11) — _clean_num / _parse_quality 임계 정책 보호.
# ==============================================================================
import math

import pytest


@pytest.mark.parametrize(
    "raw, expected",
    [
        (None, None),
        ("", None),
        ("nan", None),
        ("None", None),
        (" ", None),
        ("1234", 1234.0),
        ("1,234", 1234.0),
        (" 1, 234 ", 1234.0),
        ("0", 0.0),
        ("3.14", 3.14),
        (42, 42.0),
        (3.5, 3.5),
        ("abc", None),
    ],
)
def test_clean_num_tokens(raw, expected):
    from src.analysis.ag_well_loader import _clean_num

    got = _clean_num(raw)
    if expected is None:
        assert got is None
    else:
        assert got == pytest.approx(expected)


def test_clean_num_nan_input():
    from src.analysis.ag_well_loader import _clean_num

    # NaN float → None
    assert _clean_num(float("nan")) is None


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("불검출", 0.0),    # 적합 → 0 으로 카운트
        ("누락", None),      # 분석 제외
        ("", None),
        (None, None),
        ("0.5", 0.5),
        ("0", 0.0),
        ("1,234.56", 1234.56),
    ],
)
def test_parse_quality_tokens(raw, expected):
    from src.analysis.ag_well_loader import _parse_quality

    got = _parse_quality(raw)
    if expected is None:
        assert got is None
    else:
        assert got == pytest.approx(expected)
