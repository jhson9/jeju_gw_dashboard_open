# ==============================================================================
#  파일명: tests/test_ag_well_loader_normalize.py
#  목적: Phase B #14 의 permit_no/well_id 정규화 (string dtype + strip) 회귀 가드.
#       _normalize_master / load_usage_long / load_quality_* 끝부분에서 ID 컬럼을
#       astype("string").str.strip() 처리. 이 정책이 깨지면 CSV 에 숫자 한 행이라도
#       섞일 때 `==` 비교가 silent False 가 되어 데이터 missing 발생.
# ==============================================================================
import pandas as pd


def test_normalize_master_strips_permit_no_and_well_id():
    """master 정규화 후 permit_no/well_id 가 string dtype + strip 처리."""
    from src.analysis.ag_well_loader import _normalize_master

    raw = pd.DataFrame({
        "permit_no": ["  P1  ", "P2", "  P3"],     # 공백 패딩
        "well_id":   [" W1", "W2 ", " W3 "],
        "well_si":   ["제주시", "제주시", "서귀포시"],
        "well_eup":  ["애월읍", "한림읍", "남원읍"],
    })
    out = _normalize_master(raw)

    # strip 적용 확인
    assert list(out["permit_no"]) == ["P1", "P2", "P3"]
    assert list(out["well_id"]) == ["W1", "W2", "W3"]
    # dtype 이 pandas string (object 아님)
    assert str(out["permit_no"].dtype) == "string"
    assert str(out["well_id"].dtype) == "string"


def test_normalize_master_handles_numeric_permit():
    """CSV 에 숫자로 들어온 permit_no 도 string 으로 통일 → `==` 비교 안전."""
    from src.analysis.ag_well_loader import _normalize_master

    raw = pd.DataFrame({
        "permit_no": ["P1", 12345, "P3"],          # 두 번째가 int
        "well_id":   ["W1", "W2", "W3"],
        "well_si":   ["제주시"] * 3,
        "well_eup":  ["애월읍"] * 3,
    })
    out = _normalize_master(raw)
    # 숫자 → 문자열 변환
    assert out["permit_no"].iloc[1] == "12345"
    # 등호 비교가 dtype 흔들림 없이 작동
    assert (out["permit_no"] == "12345").sum() == 1
    assert (out["permit_no"] == "P1").sum() == 1


def test_normalize_master_preserves_other_columns():
    """ID 정규화가 다른 컬럼(예: lat/lon, address_full)에 영향 없음."""
    from src.analysis.ag_well_loader import _normalize_master

    raw = pd.DataFrame({
        "permit_no": ["P1"],
        "well_id":   ["W1"],
        "well_si":   ["제주시"],
        "well_eup":  ["애월읍"],
        "well_ri":   ["애월리"],
        "well_bunji": ["123"],
    })
    out = _normalize_master(raw)

    # address_full 생성 확인
    assert "address_full" in out.columns
    assert out["address_full"].iloc[0] == "제주시 애월읍 애월리 123"

    # search_text 생성 확인 (소문자 변환 + 결합)
    assert "search_text" in out.columns
    assert "p1" in out["search_text"].iloc[0]
    assert "w1" in out["search_text"].iloc[0]
