# ==============================================================================
#  파일명: tests/test_permit_lookup.py
#  목적: 지도 클릭 → permit_no 추출 헬퍼 회귀 가드.
#       3 분기(well_id 매칭 → PERMIT 정규식 → `|` split) 우선순위 보호.
#       메모리 규칙 보호: 농업용 마커 tooltip 형식 = well_id 단독.
# ==============================================================================
import pandas as pd
import pytest


@pytest.fixture(autouse=True)
def _isolated_permit_cache(monkeypatch):
    """permit_lookup dict cache 격리 — 단위 테스트가 가짜 df 인자를 우선하도록.

    _well_id_lookup_data() 는 ag_well_loader.load_master(active_only=False) 로
    실 master.csv 를 로드해 dict 를 채우므로, 격리 없이는 단위 테스트의 가짜
    well_id → permit_no 매핑이 실 데이터에 의해 무효화된다 (예: 'F-430' →
    가짜 'W001' 기대였으나 실데이터 'D200040042' 가 반환).
    """
    from src.dashboard import permit_lookup
    monkeypatch.setattr(
        permit_lookup, "_well_id_lookup_data",
        lambda: ({}, frozenset()),
    )
    monkeypatch.setattr(
        permit_lookup, "_well_id_to_permit_map",
        lambda: {},
    )


# ──────────────────────────────────────────────────────────────────
#  parse_clicked_popup (폴백 경로)
# ──────────────────────────────────────────────────────────────────
def test_parse_clicked_popup_extracts_permit():
    from src.dashboard.permit_lookup import parse_clicked_popup

    html = '<div>well: F-430</div><span style="display:none">W200810008</span>'
    assert parse_clicked_popup(html) == "W200810008"


def test_parse_clicked_popup_none_input():
    from src.dashboard.permit_lookup import parse_clicked_popup

    assert parse_clicked_popup(None) is None
    assert parse_clicked_popup("") is None


def test_parse_clicked_popup_no_match():
    from src.dashboard.permit_lookup import parse_clicked_popup

    # 영문 + 숫자 6+ 자리 패턴이 없으면 None
    assert parse_clicked_popup("just some text without permit") is None


# ──────────────────────────────────────────────────────────────────
#  lookup_permit_by_well_id (1순위 경로 — tooltip = well_id 단독)
# ──────────────────────────────────────────────────────────────────
def _master(well_ids, permits):
    return pd.DataFrame({"well_id": well_ids, "permit_no": permits})


def test_lookup_by_well_id_exact_match():
    """현재 tooltip 형식 — well_id 단독."""
    from src.dashboard.permit_lookup import lookup_permit_by_well_id

    df = _master(["F-430", "F-273", "F-285"], ["W001", "W002", "W003"])
    assert lookup_permit_by_well_id("F-430", df) == "W001"
    assert lookup_permit_by_well_id("F-273", df) == "W002"


def test_lookup_by_well_id_with_padding():
    """tooltip 에 공백 패딩 있어도 strip 후 매칭."""
    from src.dashboard.permit_lookup import lookup_permit_by_well_id

    df = _master(["F-430"], ["W001"])
    assert lookup_permit_by_well_id("  F-430  ", df) == "W001"


def test_lookup_legacy_pipe_format():
    """구 형식 '{well_id}|{permit_no}' 호환성."""
    from src.dashboard.permit_lookup import lookup_permit_by_well_id

    df = _master(["F-430"], ["W001"])
    # `|` 앞 well_id 로 매칭
    assert lookup_permit_by_well_id("F-430|W001", df) == "W001"


def test_lookup_regex_fallback_when_no_well_id_column():
    """df 가 None 또는 well_id 컬럼 없음 → PERMIT 정규식 fallback."""
    from src.dashboard.permit_lookup import lookup_permit_by_well_id

    # df=None
    assert lookup_permit_by_well_id("W200810008", None) == "W200810008"
    # well_id 컬럼 없는 df
    df_bad = pd.DataFrame({"other": ["x"]})
    assert lookup_permit_by_well_id("D199840059", df_bad) == "D199840059"


def test_lookup_none_input():
    from src.dashboard.permit_lookup import lookup_permit_by_well_id

    df = _master(["F-430"], ["W001"])
    assert lookup_permit_by_well_id(None, df) is None
    assert lookup_permit_by_well_id("", df) is None
    assert lookup_permit_by_well_id("   ", df) is None


def test_lookup_no_match_returns_none():
    """매칭 안 되고 PERMIT 정규식도 안 잡히면 None."""
    from src.dashboard.permit_lookup import lookup_permit_by_well_id

    df = _master(["F-430"], ["W001"])
    assert lookup_permit_by_well_id("UNKNOWN_ID", df) is None
