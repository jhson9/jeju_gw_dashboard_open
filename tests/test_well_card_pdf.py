# ==============================================================================
#  파일명: tests/test_well_card_pdf.py
#  목적: well_card_pdf 에서 data_drilling_log PDF 조회 로직이 올바르게 작동하는지 검증.
# ==============================================================================
from __future__ import annotations

from pathlib import Path

from src.dashboard import well_card_pdf


def test_filename_contains_token_matches_exact_token() -> None:
    assert well_card_pdf._filename_contains_token("D-001.pdf", "D-001")
    assert well_card_pdf._filename_contains_token("D-001_수질.pdf", "D-001")
    assert not well_card_pdf._filename_contains_token("D-0010.pdf", "D-001")
    assert well_card_pdf._filename_contains_token("93이호_양수시험.pdf", "93이호")


def test_available_drilling_pdfs_matches_permit_and_well_id(tmp_path: Path, monkeypatch) -> None:
    drilling_dir = tmp_path / "data_drilling_log"
    drilling_dir.mkdir()
    (drilling_dir / "D-001_양수시험.pdf").write_bytes(b"%PDF-1.4")
    (drilling_dir / "93이호_양수시험.pdf").write_bytes(b"%PDF-1.4")
    (drilling_dir / "D-002_양수시험.pdf").write_bytes(b"%PDF-1.4")

    monkeypatch.setattr(well_card_pdf, "DRILLING_PDF_DIR", drilling_dir)
    monkeypatch.setattr(well_card_pdf, "lookup_permit_by_well_id", lambda well_id, df=None: "D-001")

    results = well_card_pdf.available_drilling_pdfs("대정1")
    assert results == [("D-001_양수시험.pdf", "D-001_양수시험.pdf")]

    monkeypatch.setattr(well_card_pdf, "lookup_permit_by_well_id", lambda well_id, df=None: None)
    results = well_card_pdf.available_drilling_pdfs("93이호")
    assert results == [("93이호_양수시험.pdf", "93이호_양수시험.pdf")]
