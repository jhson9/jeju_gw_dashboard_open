# ==============================================================================
#  파일명: tests/test_drone_importer_atomic.py
#  목적: src/drone/importer.py 의 P-fix (C1/C2/C3/C4 + I3) 회귀 보호.
# ------------------------------------------------------------------------------
#  커버리지:
#    1) _atomic_write_text 의 tmp + os.replace 패턴 (부분 쓰기 차단)
#    2) _atomic_write_json 동일 (텍스트 헬퍼 위임 + JSON round-trip)
#    3) _ImportLock 의 PID 기반 stale 검출 + 동시 진입 차단
#    4) _csv_safe (csv_safe_cell 헬퍼 — formula injection prefix 회피)
#    5) register_to_csv 가 flat-dict + nested-dict terra_meta 양쪽 처리
#
#  주의:
#    - 모든 I/O 는 tmp_path (pytest 제공) 안에서만 수행 — 실제 data/ 미변경.
#    - register_to_csv 는 _csv_safe inline 정의를 그대로 사용하므로
#      DroneImporter 인스턴스를 통해 end-to-end 로 확인.
#    - I/O 부수 효과 ↔ private API 의존 트레이드오프: 안정 P-fix 보호가
#      우선이므로 내부 헬퍼(_) 도 직접 검증한다.
# ==============================================================================
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import pytest

# conftest.py 가 sys.path 추가하지만, 명시적으로 보강 (단독 실행 안전).
_PROJ_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJ_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJ_ROOT))

from src.drone import importer as imp  # noqa: E402
from src.utils.csv_safe import csv_safe_cell  # noqa: E402


# ─────────────────────────────────────────────────────────────
# 1) _atomic_write_text — tmp + os.replace 패턴 검증
# ─────────────────────────────────────────────────────────────
def test_atomic_write_text_creates_file_and_no_tmp_residue(tmp_path: Path) -> None:
    """정상 경로: 파일이 생성되고, *.tmp 가 남지 않음."""
    target = tmp_path / "out.txt"
    payload = "안녕하세요\nhello\n"
    imp._atomic_write_text(target, payload)

    # 본 파일 존재 + 내용 일치
    assert target.exists()
    assert target.read_text(encoding="utf-8") == payload

    # tmp 파일 잔여 없음 (헬퍼는 prefix=path.name+".", suffix=".tmp" 사용)
    leftovers = list(tmp_path.glob("out.txt.*.tmp"))
    assert leftovers == [], f"tmp 파일이 남음: {leftovers}"


def test_atomic_write_text_overwrites_existing(tmp_path: Path) -> None:
    """기존 파일이 새 내용으로 atomic 하게 덮어쓰여진다."""
    target = tmp_path / "out.txt"
    target.write_text("old", encoding="utf-8")
    imp._atomic_write_text(target, "new")
    assert target.read_text(encoding="utf-8") == "new"


def test_atomic_write_text_cleans_tmp_on_exception(tmp_path: Path, monkeypatch) -> None:
    """예외 시 tmp 파일을 청소하고 원본은 손상되지 않는다."""
    target = tmp_path / "out.txt"
    target.write_text("original", encoding="utf-8")

    # os.replace 가 실패하도록 패치 → tmp 는 남으면 안 됨, 원본 보존
    def _raise(*a, **kw):
        raise OSError("simulated rename failure")
    monkeypatch.setattr(imp.os, "replace", _raise)

    with pytest.raises(OSError):
        imp._atomic_write_text(target, "new")

    # 원본 보존
    assert target.read_text(encoding="utf-8") == "original"
    # tmp 청소
    leftovers = list(tmp_path.glob("out.txt.*.tmp"))
    assert leftovers == [], f"실패 후 tmp 잔여: {leftovers}"


# ─────────────────────────────────────────────────────────────
# 2) _atomic_write_json — 텍스트 헬퍼 위임 + JSON round-trip
# ─────────────────────────────────────────────────────────────
def test_atomic_write_json_roundtrip(tmp_path: Path) -> None:
    target = tmp_path / "data.json"
    payload = {"한글": "값", "list": [1, 2, 3], "nested": {"a": True}}
    imp._atomic_write_json(target, payload, indent=2)

    assert target.exists()
    loaded = json.loads(target.read_text(encoding="utf-8"))
    assert loaded == payload

    # tmp 잔여 없음
    leftovers = list(tmp_path.glob("data.json.*.tmp"))
    assert leftovers == []


def test_atomic_write_json_uses_text_helper(tmp_path: Path, monkeypatch) -> None:
    """JSON 헬퍼는 내부적으로 _atomic_write_text 를 호출한다."""
    calls = []

    def _spy(path, content, *, encoding="utf-8"):
        calls.append((Path(path), content, encoding))
        Path(path).write_text(content, encoding=encoding)

    monkeypatch.setattr(imp, "_atomic_write_text", _spy)
    target = tmp_path / "data.json"
    imp._atomic_write_json(target, {"k": "v"})
    assert len(calls) == 1
    assert calls[0][0] == target
    assert json.loads(calls[0][1]) == {"k": "v"}


# ─────────────────────────────────────────────────────────────
# 3) _ImportLock — PID 기반 stale 검출 + 동시 진입 차단
# ─────────────────────────────────────────────────────────────
def test_import_lock_acquire_release(tmp_path: Path) -> None:
    """정상 acquire → release. 락 파일은 종료 시 삭제됨."""
    lock_path = tmp_path / ".import.lock"
    with imp._ImportLock(lock_path) as lk:
        assert lock_path.exists()
        info = json.loads(lock_path.read_text(encoding="utf-8"))
        assert info["pid"] == os.getpid()
        assert lk.acquired is True
    # __exit__ 후 락 파일 제거
    assert not lock_path.exists()


def test_import_lock_blocks_when_alive_pid(tmp_path: Path) -> None:
    """살아있는 PID 의 락 파일이 있으면 ImportLockError 발생."""
    lock_path = tmp_path / ".import.lock"
    # 현재 프로세스 PID 로 락 선점
    lock_path.write_text(
        json.dumps({"pid": os.getpid(), "ts": time.time()}),
        encoding="utf-8",
    )
    with pytest.raises(imp.ImportLockError):
        with imp._ImportLock(lock_path):
            pass
    # 락 파일은 그대로 남아 있어야 함 (다른 import 가 들고 있는 것이므로)
    assert lock_path.exists()


def test_import_lock_clears_stale_dead_pid(tmp_path: Path) -> None:
    """PID 가 죽었으면 stale 로 보고 청소 후 진입 가능해야 한다."""
    lock_path = tmp_path / ".import.lock"
    # 실재하지 않을 PID — 0/음수는 _pid_alive 가 False 반환
    lock_path.write_text(
        json.dumps({"pid": 0, "ts": time.time()}),
        encoding="utf-8",
    )
    with imp._ImportLock(lock_path) as lk:
        assert lk.acquired is True
        # 새 PID 로 덮어쓰여졌어야 함
        info = json.loads(lock_path.read_text(encoding="utf-8"))
        assert info["pid"] == os.getpid()


def test_import_lock_clears_stale_old_timestamp(tmp_path: Path) -> None:
    """STALE_AFTER_SEC 초과 시 PID 가 살아있어도 청소된다."""
    lock_path = tmp_path / ".import.lock"
    # 2시간 전 timestamp (STALE_AFTER_SEC = 3600)
    lock_path.write_text(
        json.dumps({"pid": os.getpid(), "ts": time.time() - 7200}),
        encoding="utf-8",
    )
    with imp._ImportLock(lock_path) as lk:
        assert lk.acquired is True


def test_import_lock_recovers_from_corrupt_file(tmp_path: Path) -> None:
    """파손된 JSON 락 파일도 청소 후 정상 acquire."""
    lock_path = tmp_path / ".import.lock"
    lock_path.write_text("not json {{{", encoding="utf-8")
    with imp._ImportLock(lock_path) as lk:
        assert lk.acquired is True
        info = json.loads(lock_path.read_text(encoding="utf-8"))
        assert info["pid"] == os.getpid()


# ─────────────────────────────────────────────────────────────
# 4) _csv_safe (csv_safe_cell) — formula injection prefix 회피
# ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("raw, expected_prefix", [
    ("=SUM(A1:A2)", "'"),
    ("+1+1",       "'"),
    ("-cmd",       "'"),
    ("@import",    "'"),
    ("\tTabStart", "'"),
    ("\rCRStart",  "'"),
])
def test_csv_safe_prefixes_dangerous_chars(raw, expected_prefix) -> None:
    """위험 prefix 6종 모두 single quote 로 escape 된다."""
    out = csv_safe_cell(raw)
    assert isinstance(out, str)
    assert out.startswith(expected_prefix)
    # 원본 값은 보존
    assert out[len(expected_prefix):] == raw


@pytest.mark.parametrize("raw", [
    "normal text",
    "한글 텍스트",
    "site_name_01",
    "12345",
])
def test_csv_safe_passes_through_safe_values(raw) -> None:
    """안전한 값은 그대로 통과."""
    out = csv_safe_cell(raw)
    # 문자열 형태 유지 (앞에 추가 prefix 없어야 함)
    assert str(out) == raw
    assert not str(out).startswith("'")


def test_csv_safe_handles_none_and_empty() -> None:
    """None / 빈 문자열은 변경 없이 그대로 반환."""
    assert csv_safe_cell(None) is None
    assert csv_safe_cell("") == ""


# importer.py 내부의 inline _csv_safe 도 동일 동작 검증
def test_inline_csv_safe_in_importer_matches_helper(tmp_path: Path) -> None:
    """register_to_csv 내부 _csv_safe 가 동일 prefix 회피를 수행하는지
    end-to-end 로 확인 (register_to_csv 한 번 호출 → CSV 셀 검사)."""
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    importer = imp.DroneImporter(src, dst)
    importer.register_to_csv(
        mission_id="2605_test",
        name="=EVIL()",            # 위험 prefix
        site_type="저수조",
        eup_myeon_dong="조천읍",
        flight_date="2026-05-29",
        terra_meta={},
    )
    assert importer.master_csv.exists()
    import csv as _csv
    with open(importer.master_csv, encoding="utf-8-sig") as f:
        rows = list(_csv.DictReader(f))
    assert len(rows) == 1
    # site_name 셀이 single quote 로 시작해야 함 (수식 차단)
    assert rows[0]["site_name"].startswith("'=EVIL()")


# ─────────────────────────────────────────────────────────────
# 5) register_to_csv — flat-dict + nested-dict terra_meta 양쪽
# ─────────────────────────────────────────────────────────────
def test_register_to_csv_with_flat_terra_meta(tmp_path: Path) -> None:
    """extract_meta() 산출 형태 (평탄 dict) 가 정확히 매핑된다."""
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    importer = imp.DroneImporter(src, dst)

    flat_meta = {
        "bbox_wgs84": [126.5, 33.4, 126.6, 33.5],   # [minLon, minLat, maxLon, maxLat]
        "rtk_mode":   "RTK_FIX",
        "image_count": 250,
        "rmse_m":     0.03,
        "gsd_m":      0.015,
    }
    importer.register_to_csv(
        mission_id="2605_flat",
        name="송당저수조",
        site_type="저수조",
        eup_myeon_dong="조천읍",
        flight_date="2026-05-29",
        terra_meta=flat_meta,
    )

    import csv as _csv
    with open(importer.master_csv, encoding="utf-8-sig") as f:
        rows = list(_csv.DictReader(f))
    assert len(rows) == 1
    r = rows[0]
    assert r["mission_id"] == "2605_flat"
    assert r["site_name"] == "송당저수조"
    # bbox 중심 계산: lon=(126.5+126.6)/2=126.55, lat=(33.4+33.5)/2=33.45
    assert float(r["lon"]) == pytest.approx(126.55, abs=1e-6)
    assert float(r["lat"]) == pytest.approx(33.45,  abs=1e-6)
    assert r["rtk_mode"] == "RTK_FIX"
    assert r["image_count"] == "250"
    # gsd_cm = gsd_m * 100 = 1.5
    assert float(r["gsd_cm"]) == pytest.approx(1.5, abs=1e-6)


def test_register_to_csv_with_nested_terra_meta(tmp_path: Path) -> None:
    """write_meta_json() 산출 형태 (nested doc) 가 정확히 매핑된다."""
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    importer = imp.DroneImporter(src, dst)

    nested_meta = {
        "geo": {
            "bbox_wgs84": [126.7, 33.2, 126.8, 33.3],
        },
        "survey_info": {
            "rtk_mode":    "RTK_FLOAT",
            "image_count": 180,
            "rmse_m":      0.05,
        },
        "outputs": {
            "result_tif": {"available": True, "gsd_m": 0.02},
            "tileset_3d": {"available": False},
            "dsm_tif":    {"available": True},
            "pointcloud_ply": {"available": False},
        },
    }
    importer.register_to_csv(
        mission_id="2511_nested",
        name="대정관정",
        site_type="관정",
        eup_myeon_dong="대정읍",
        flight_date="2025-11-15",
        terra_meta=nested_meta,
    )

    import csv as _csv
    with open(importer.master_csv, encoding="utf-8-sig") as f:
        rows = list(_csv.DictReader(f))
    assert len(rows) == 1
    r = rows[0]
    assert r["mission_id"] == "2511_nested"
    # bbox 중심: lon=126.75, lat=33.25
    assert float(r["lon"]) == pytest.approx(126.75, abs=1e-6)
    assert float(r["lat"]) == pytest.approx(33.25,  abs=1e-6)
    # survey_info 에서 가져옴
    assert r["rtk_mode"] == "RTK_FLOAT"
    assert r["image_count"] == "180"
    # outputs.result_tif.available → has_2d=Y, tileset_3d → has_3d=N
    assert r["has_2d"] == "Y"
    assert r["has_3d"] == "N"
    assert r["has_dsm"] == "Y"
    assert r["has_ply"] == "N"
    # gsd_cm = 0.02 * 100 = 2.0
    assert float(r["gsd_cm"]) == pytest.approx(2.0, abs=1e-6)


def test_register_to_csv_updates_existing_row(tmp_path: Path) -> None:
    """같은 mission_id 재등록 시 행이 추가되지 않고 덮어쓰여진다."""
    src = tmp_path / "src"
    dst = tmp_path / "dst"
    src.mkdir()
    dst.mkdir()
    importer = imp.DroneImporter(src, dst)

    # 1차 등록
    importer.register_to_csv(
        mission_id="2605_dup",
        name="원본이름",
        site_type="저수조",
        eup_myeon_dong="조천읍",
        flight_date="2026-05-29",
        terra_meta={"bbox_wgs84": [126.5, 33.4, 126.6, 33.5]},
    )
    # 2차 등록 (이름·읍면동 변경)
    importer.register_to_csv(
        mission_id="2605_dup",
        name="새이름",
        site_type="저수조",
        eup_myeon_dong="애월읍",
        flight_date="2026-05-29",
        terra_meta={"bbox_wgs84": [126.5, 33.4, 126.6, 33.5]},
    )

    import csv as _csv
    with open(importer.master_csv, encoding="utf-8-sig") as f:
        rows = list(_csv.DictReader(f))
    assert len(rows) == 1, "중복 mission_id 는 1행만 유지되어야 함"
    assert rows[0]["site_name"] == "새이름"
    assert rows[0]["eup_myeon_dong"] == "애월읍"
