# ==============================================================================
#  src/drone/importer.py
#  DJI Terra 산출물 폴더 → data/04_drone 가져오기 파이프라인
# ------------------------------------------------------------------------------
#  사용 흐름:
#    imp = DroneImporter(source_root, dst_root)
#    missions = imp.scan()            # 신규/기존 분류
#    meta = imp.extract_meta(src_dir) # Terra 리포트 자동 추출
#    imp.copy_mission(src, dst, cb)   # 파일 복사 (진행 콜백)
#    imp.register(meta)               # registry.json + master_drone.csv 갱신
# ------------------------------------------------------------------------------
#  ⚠️ bbox 산출 규칙 (2026-05-29 회귀 fix — 절대 변경 금지):
#
#    Mission 의 georeferenced bbox 는 **result.tif 의 실제 georeferencing**
#    을 단일 진실 원천으로 사용합니다. 본 importer 의 extract_meta() 안에서
#    rasterio 로 result.tif 의 bounds 를 읽어 bbox_wgs84 를 산출합니다.
#
#    이전에는 DJI Terra 의 blocks_wgs84.json (비행 영역 의도) 의 첫 번째
#    block 만 사용 → result.tif 의 실제 영역과 어긋남 → Leaflet ImageOverlay
#    가 이미지를 잘못된 영역에 stretch → Tab32 측정 도구의 거리값이 비율
#    만큼 왜곡 (실측: 두 저수조 사이 40m 가 19m 로 표시).
#
#    blocks_wgs84.json 은 result.tif 가 없을 때만 폴백으로 사용하며, 모든
#    blocks 의 polygon_points 를 union 합니다.
#
#    이 규칙을 어기면 tests/test_drone_meta_bbox_consistency.py 가 즉시
#    fail 합니다.  또한 데이터 관리 탭(Section F)의 "메타 bbox 정합성 검사"
#    버튼으로 언제든 진단·자동 보정 가능.
#
#    관련 모듈: src/drone/meta_validator.py (단일 진실 원천 헬퍼)
# ==============================================================================
from __future__ import annotations

import csv
import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional


# ──────────────────────────────────────────────────────────────────
#  P-fix C2 (2026-05-29): atomic write 헬퍼.
#  배경: registry.json / master_drone.csv 가 open(...,"w") + json.dump 직접
#  쓰기 → 인터럽트/디스크 부족 시 부분 쓰기로 JSON 깨짐 → 다음 read 의
#  try/except 가 silent 빈 dict 로 폴백 → 기존 미션 전부 소실 가능.
#  본 헬퍼는 tmp 파일 작성 후 os.replace 로 atomic rename (POSIX·Windows
#  모두 same-filesystem 한정 atomic 보장).
# ──────────────────────────────────────────────────────────────────
def _atomic_write_text(path: Path, content: str, *, encoding: str = "utf-8") -> None:
    """텍스트를 atomic 하게 쓴다. tmp + os.replace 패턴.

    부분 쓰기 위험 차단 — 시스템 크래시/사용자 강제 종료 시에도 path 는
    "이전 완전 버전" 또는 "새 완전 버전" 둘 중 하나로만 존재.
    같은 디렉토리 내 tmp 사용 (rename 이 atomic 하려면 same filesystem 필수).
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # delete=False: tmp 핸들을 닫고 직접 rename — Windows 호환
    fd, tmp_str = tempfile.mkstemp(
        prefix=path.name + ".",
        suffix=".tmp",
        dir=str(path.parent),
    )
    try:
        with os.fdopen(fd, "w", encoding=encoding, newline="") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())   # 디스크에 강제 flush
        os.replace(tmp_str, path)  # atomic rename
    except Exception:
        try:
            os.unlink(tmp_str)
        except OSError:
            pass
        raise


def _atomic_write_json(path: Path, data, *, indent: int = 2,
                        ensure_ascii: bool = False) -> None:
    """JSON 을 atomic 하게 쓴다. _atomic_write_text 래퍼."""
    content = json.dumps(data, indent=indent, ensure_ascii=ensure_ascii)
    _atomic_write_text(path, content, encoding="utf-8")


# ──────────────────────────────────────────────────────────────────
#  P-fix C4 (2026-05-29): 프로세스 간 import 락 (다중 탭/세션 차단).
#  배경: drone_import_running session_state 플래그는 같은 브라우저 세션
#  에서만 작동 → 다른 브라우저/시크릿 창에서 동시 import 시 두 스레드가
#  같은 dst 디렉터리에 write → 데이터 손상.
#  본 락은 data/04_drone/.import.lock 파일의 존재 + PID + timestamp 로
#  cross-session 직렬화. 외부 라이브러리(filelock) 의존 없이 stdlib 만 사용.
# ──────────────────────────────────────────────────────────────────
class ImportLockError(RuntimeError):
    """다른 import 가 이미 진행 중일 때."""


class _ImportLock:
    """간단한 advisory file lock.

    Usage:
        with _ImportLock(lock_path) as lk:
            ... 안전한 import 작업 ...

    동시 import 차단:
      - 진입 시 lock_path 존재 + 살아있는 PID 면 ImportLockError 발생
      - stale (PID 죽음 or > 1시간 경과) 면 자동 청소 후 진입
      - 정상 종료 시 lock_path 삭제
    """
    STALE_AFTER_SEC = 3600   # 1시간 후엔 stale 로 간주

    def __init__(self, lock_path: Path):
        self.lock_path = Path(lock_path)
        self.acquired = False

    def __enter__(self):
        import time
        if self.lock_path.exists():
            try:
                info = json.loads(self.lock_path.read_text(encoding="utf-8"))
                pid = int(info.get("pid", 0))
                ts = float(info.get("ts", 0))
                age = time.time() - ts
                # stale 검사: 시간 초과 또는 PID 사망
                is_stale = (age > self.STALE_AFTER_SEC) or (not self._pid_alive(pid))
                if not is_stale:
                    raise ImportLockError(
                        f"다른 import 가 이미 진행 중입니다 "
                        f"(PID {pid}, 시작 {int(age)}초 전). "
                        f"수동 해제: {self.lock_path} 삭제."
                    )
                # stale 락 자동 청소
                try:
                    self.lock_path.unlink()
                except OSError:
                    pass
            except (json.JSONDecodeError, ValueError, KeyError):
                # 파손된 락 파일 — 청소 후 재시도
                try:
                    self.lock_path.unlink()
                except OSError:
                    pass

        # 락 획득
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        _atomic_write_json(self.lock_path, {
            "pid": os.getpid(),
            "ts":  time.time(),
        })
        self.acquired = True
        return self

    def __exit__(self, *exc_info):
        if self.acquired and self.lock_path.exists():
            try:
                self.lock_path.unlink()
            except OSError:
                pass
        self.acquired = False
        return False  # 예외 전파

    @staticmethod
    def _pid_alive(pid: int) -> bool:
        """PID 가 살아있는지 — Windows·POSIX 양쪽 지원."""
        if pid <= 0:
            return False
        try:
            if os.name == "nt":
                # Windows: signal 0 미지원, OpenProcess 로 검사
                import ctypes
                PROCESS_QUERY_INFORMATION = 0x0400
                handle = ctypes.windll.kernel32.OpenProcess(
                    PROCESS_QUERY_INFORMATION, False, pid
                )
                if handle:
                    ctypes.windll.kernel32.CloseHandle(handle)
                    return True
                return False
            else:
                # POSIX: signal 0 으로 권한 검사
                os.kill(pid, 0)
                return True
        except (OSError, ProcessLookupError, PermissionError):
            return False


# ──────────────────────────────────────────────────────────────────
#  데이터 클래스
# ──────────────────────────────────────────────────────────────────
@dataclass
class MissionScanResult:
    """소스 폴더 스캔 한 건 결과."""
    folder_name: str        # 폴더명 (예: 2605_송당저수조)
    src_dir: Path
    dst_dir: Path
    status: str             # "new" | "exists" | "partial"
    has_result_tif: bool = False
    has_dsm_tif: bool = False
    has_xyz_tiles: bool = False
    has_3d: bool = False
    has_ply: bool = False
    dst_has_result_tif: bool = False
    dst_has_3d: bool = False
    terra_meta: dict = field(default_factory=dict)  # extract_meta() 결과


@dataclass
class ImportProgress:
    """copy_mission() 진행 상태. 콜백으로 전달."""
    mission_id: str = ""
    phase: str = ""         # "map_tif" | "xyz_tiles" | "3d_tiles" | "done"
    current_file: str = ""
    files_done: int = 0
    files_total: int = 0
    bytes_done: int = 0
    bytes_total: int = 0
    error: str = ""


# ──────────────────────────────────────────────────────────────────
#  메인 클래스
# ──────────────────────────────────────────────────────────────────
class DroneImporter:
    """DJI Terra 결과물 → data/04_drone 가져오기."""

    SITE_TYPES = ["저수조", "저수지", "관정", "수원지", "기타"]

    def __init__(self, source_root: Path, dst_root: Path):
        self.source_root = Path(source_root)
        self.dst_root = Path(dst_root)
        self.registry_file = dst_root / "registry.json"
        self.master_csv = dst_root / "master_drone.csv"

    # ── 스캔 ──────────────────────────────────────────────────────
    def scan(self) -> list[MissionScanResult]:
        """소스 폴더의 각 미션 폴더를 스캔, 신규/기존/일부 분류."""
        if not self.source_root.exists():
            return []

        results: list[MissionScanResult] = []
        for d in sorted(self.source_root.iterdir()):
            if not d.is_dir():
                continue
            if not self._looks_like_terra(d):
                continue

            dst = self.dst_root / d.name
            r = MissionScanResult(
                folder_name=d.name,
                src_dir=d,
                dst_dir=dst,
                status="new",
            )

            # 소스 내용물
            r.has_result_tif = (d / "map" / "result.tif").exists()
            r.has_dsm_tif = (d / "map" / "dsm.tif").exists()
            r.has_xyz_tiles = any(
                (d / "map" / str(z)).exists() for z in range(12, 23)
            )
            b3dm = d / "models" / "pc" / "0" / "terra_b3dms" / "tileset.json"
            r.has_3d = b3dm.exists()
            ply_dir = d / "models" / "pc" / "0" / "terra_ply"
            r.has_ply = ply_dir.exists() and any(ply_dir.rglob("*.ply"))

            # 목적지 현황
            r.dst_has_result_tif = (dst / "map" / "result.tif").exists()
            r.dst_has_3d = (
                dst / "models" / "pc" / "0" / "terra_b3dms" / "tileset.json"
            ).exists()

            # 상태 분류
            if not dst.exists() or not (dst / "meta.json").exists():
                r.status = "new"
            elif r.dst_has_result_tif and r.dst_has_3d:
                r.status = "exists"
            else:
                r.status = "partial"

            # Terra 메타 자동 추출
            r.terra_meta = self.extract_meta(d)
            results.append(r)

        return results

    @staticmethod
    def _looks_like_terra(d: Path) -> bool:
        """Terra 출력 폴더인지 간단히 판별."""
        return (d / "map").exists() or (d / "models").exists() or (d / "AT").exists()

    # ── 메타 추출 ─────────────────────────────────────────────────
    def extract_meta(self, src_dir: Path) -> dict:
        """DJI Terra 리포트 파일들을 파싱해 메타데이터 dict 반환."""
        meta: dict = {}

        # sfm_report.json
        sfm = self._find_sfm_report(src_dir)
        if sfm:
            try:
                d = json.loads(sfm.read_text(encoding="utf-8"))
                meta["image_count"] = d.get("images number")
                meta["calibrated_count"] = d.get("images reconstructed")
                meta["rmse_m"] = round(d.get("georeferencing rmse", 0), 3)
                meta["gsd_m"] = round(d.get("average ground sampling distance(GSD)", 0), 4)
                meta["gsd_cm"] = round(meta["gsd_m"] * 100, 2)
                meta["flying_altitude_m"] = round(d.get("flying altitude", 0), 1)
                meta["coverage_km2"] = round(d.get("coverage area", 0), 4)
                rtk = d.get("rtk flag") or {}
                fix = rtk.get("NARROW_INT", 0)
                total = sum(rtk.values()) if rtk else 0
                if total and fix == total:
                    meta["rtk_mode"] = "Fix 100%"
                elif total and fix > 0:
                    meta["rtk_mode"] = f"Fix {fix}/{total}"
                else:
                    meta["rtk_mode"] = "Single"
                cam_list = d.get("cameras") or []
                if cam_list:
                    meta["camera_model"] = cam_list[0].get("camera model", "DJI Mavic 3E")
            except Exception:
                pass

        # sfm_geo_desc.json → 해발고도
        geo_desc = self._find_json(src_dir, "sfm_geo_desc.json")
        if geo_desc:
            try:
                d = json.loads(geo_desc.read_text(encoding="utf-8"))
                ref = d.get("ref_GPS") or {}
                if ref.get("altitude"):
                    meta["altitude_m"] = round(ref["altitude"], 1)
                if ref.get("latitude"):
                    meta["ref_lat"] = ref["latitude"]
                if ref.get("longitude"):
                    meta["ref_lon"] = ref["longitude"]
            except Exception:
                pass

        # bbox/center — 단일 진실 원천: result.tif 의 georeferencing.
        # (모듈 상단 docstring 의 "⚠️ bbox 산출 규칙" 참조)
        # meta_validator.extract_bbox_from_result_tif() 가 rasterio 로 직접
        # 추출. blocks_wgs84.json 폴백은 result.tif 가 없을 때만.
        result_tif = src_dir / "map" / "result.tif"
        bbox_from_tif = False
        try:
            from src.drone.meta_validator import extract_bbox_from_result_tif
            _ext = extract_bbox_from_result_tif(result_tif) if result_tif.exists() else None
        except ImportError:
            _ext = None
        if _ext is not None:
            _bbox, _w, _h, _gsd = _ext
            meta["bbox_wgs84"] = _bbox
            meta["center_lat"] = round((_bbox[1] + _bbox[3]) / 2, 6)
            meta["center_lon"] = round((_bbox[0] + _bbox[2]) / 2, 6)
            meta.setdefault("_result_tif_meta", {})
            meta["_result_tif_meta"]["size"] = [_w, _h]
            meta["_result_tif_meta"]["gsd_m"] = _gsd
            bbox_from_tif = True

        if not bbox_from_tif:
            # 폴백: blocks_wgs84.json — 모든 blocks 의 polygon_points union
            bwgs = self._find_json(src_dir, "blocks_wgs84.json")
            if bwgs:
                try:
                    d = json.loads(bwgs.read_text(encoding="utf-8"))
                    blocks = d.get("blocks") or []
                    all_lats: list = []
                    all_lons: list = []
                    for b in blocks:
                        pts = b.get("polytope", {}).get("polygon_points", [])
                        # polygon_points 형식: [lat, lon] 순서 (실측 확인 2026-05-29)
                        for p in pts:
                            if len(p) >= 2:
                                all_lats.append(p[0])
                                all_lons.append(p[1])
                    if all_lats and all_lons:
                        meta["bbox_wgs84"] = [
                            round(min(all_lons), 6), round(min(all_lats), 6),
                            round(max(all_lons), 6), round(max(all_lats), 6),
                        ]
                        meta["center_lat"] = round((min(all_lats) + max(all_lats)) / 2, 6)
                        meta["center_lon"] = round((min(all_lons) + max(all_lons)) / 2, 6)
                except Exception:
                    pass

        # tileset.json → ECEF center
        tileset = src_dir / "models" / "pc" / "0" / "terra_b3dms" / "tileset.json"
        if tileset.exists():
            try:
                d = json.loads(tileset.read_text(encoding="utf-8"))
                bv = d.get("root", {}).get("boundingVolume", {}).get("box", [])
                if len(bv) >= 3:
                    meta["ecef_center"] = [bv[0], bv[1], bv[2]]
            except Exception:
                pass

        # result.tif 줌 범위
        zoom_min, zoom_max = self._detect_zoom_range(src_dir)
        if zoom_min:
            meta["zoom_min"] = zoom_min
            meta["zoom_max"] = zoom_max

        # terra version from report.md
        rmd = self._find_file(src_dir, "report.md")
        if rmd:
            text = rmd.read_text(encoding="utf-8", errors="ignore")[:500]
            for line in text.splitlines():
                if "Terra" in line and "." in line:
                    import re
                    m = re.search(r"Terra\s+([\d.]+)", line)
                    if m:
                        meta["terra_version"] = m.group(1)
                        break

        return meta

    @staticmethod
    def _find_sfm_report(src_dir: Path) -> Optional[Path]:
        for p in src_dir.rglob("sfm_report.json"):
            if ".temp" not in str(p):
                return p
        return None

    @staticmethod
    def _find_json(src_dir: Path, name: str) -> Optional[Path]:
        for p in src_dir.rglob(name):
            if ".temp" not in str(p):
                return p
        return None

    @staticmethod
    def _find_file(src_dir: Path, name: str) -> Optional[Path]:
        for p in src_dir.rglob(name):
            return p
        return None

    @staticmethod
    def _detect_zoom_range(src_dir: Path) -> tuple[Optional[int], Optional[int]]:
        map_dir = src_dir / "map"
        if not map_dir.exists():
            return None, None
        zooms = [int(d.name) for d in map_dir.iterdir()
                 if d.is_dir() and d.name.isdigit()]
        if not zooms:
            return None, None
        return min(zooms), max(zooms)

    # ── 복사 ──────────────────────────────────────────────────────
    def copy_mission(
        self,
        scan_result: MissionScanResult,
        progress: ImportProgress,
        cb: Optional[Callable[[ImportProgress], None]] = None,
    ) -> bool:
        """src → dst 파일 복사. 이미 있는 파일은 건너뜀.

        P-fix N1 (2026-05-29): 사전 스캔으로 files_total/bytes_total 합산 →
        진행률 % UI 표시 가능.

        P-fix I1 (2026-05-29): per-file atomic write (.part + os.replace) +
        예외 시 partial 파일 cleanup. 1.7GB result.tif 복사 도중 인터럽트 시
        잘린 파일이 dst 에 남아 다음 import 에서 skip 되는 회귀 차단.
        """
        src = scan_result.src_dir
        dst = scan_result.dst_dir
        progress.mission_id = scan_result.folder_name

        # P-fix N1: 사전 스캔 — 복사 대상 파일 총수·총바이트 계산
        plan: list[tuple[Path, Path, str]] = []  # (src_path, dst_path, phase)
        try:
            # 1) result/DSM + sidecar
            for fname in ("result.tif", "dsm.tif", "result.prj", "result.tfw",
                          "dsm.prj", "dsm.tfw"):
                s = src / "map" / fname
                d = dst / "map" / fname
                if s.exists() and not d.exists():
                    plan.append((s, d, "map_tif"))
            # 2) XYZ PNG 타일
            map_src = src / "map"
            if map_src.exists():
                for zoom_dir in sorted(map_src.iterdir()):
                    if not (zoom_dir.is_dir() and zoom_dir.name.isdigit()):
                        continue
                    for tile in zoom_dir.rglob("*.png"):
                        rel = tile.relative_to(map_src)
                        target = dst / "map" / rel
                        if not target.exists():
                            plan.append((tile, target, "xyz_tiles"))
            # 3) 3D Tiles
            b3dm_src = src / "models" / "pc" / "0" / "terra_b3dms"
            if b3dm_src.exists():
                for item in b3dm_src.rglob("*"):
                    if item.is_file():
                        rel = item.relative_to(b3dm_src)
                        target = dst / "models" / "pc" / "0" / "terra_b3dms" / rel
                        if not target.exists():
                            plan.append((item, target, "3d_tiles"))
            # 4) PLY
            ply_src = src / "models" / "pc" / "0" / "terra_ply"
            if ply_src.exists():
                for item in ply_src.rglob("*"):
                    if item.is_file():
                        rel = item.relative_to(ply_src)
                        target = dst / "models" / "pc" / "0" / "terra_ply" / rel
                        if not target.exists():
                            plan.append((item, target, "ply"))

            progress.files_total = len(plan)
            progress.bytes_total = sum(s.stat().st_size for s, _, _ in plan)
            if cb:
                cb(progress)
        except Exception as e:
            progress.error = f"사전 스캔 실패: {e}"
            if cb:
                cb(progress)
            return False

        # 실제 복사 — per-file atomic (.part + os.replace) + 인터럽트 시 cleanup
        in_flight: Path | None = None
        try:
            for src_p, dst_p, phase in plan:
                progress.phase = phase
                progress.current_file = src_p.name
                if cb:
                    cb(progress)
                dst_p.parent.mkdir(parents=True, exist_ok=True)
                tmp = dst_p.with_suffix(dst_p.suffix + ".part")
                in_flight = tmp
                shutil.copy2(src_p, tmp)
                os.replace(tmp, dst_p)
                in_flight = None
                progress.files_done += 1
                progress.bytes_done += src_p.stat().st_size
                # 50 파일마다 (또는 큰 파일 1개마다) 콜백
                if cb and (progress.files_done % 50 == 0 or src_p.stat().st_size > 10*1024*1024):
                    cb(progress)

            progress.phase = "done"
            progress.current_file = ""
            if cb:
                cb(progress)
            return True

        except Exception as e:
            progress.error = str(e)
            # P-fix I1: in-flight 임시 파일 cleanup — 잘린 .part 파일이 남으면
            # 다음 import 시 skip 으로 영구 잔존 → 명시 삭제
            if in_flight is not None and in_flight.exists():
                try:
                    in_flight.unlink()
                except OSError:
                    pass
            if cb:
                cb(progress)
            return False

    # ── 메타 파일 생성 ────────────────────────────────────────────
    def write_meta_json(
        self,
        dst_dir: Path,
        mission_id: str,
        name: str,
        terra_meta: dict,
        user_meta: dict,          # UI 입력값 (site_type, eup_myeon_dong 등)
    ) -> None:
        """data/04_drone/{mission_id}/meta.json 생성."""
        survey = {
            "rtk_mode":          terra_meta.get("rtk_mode", "Single"),
            "image_count":       terra_meta.get("image_count"),
            "calibrated_count":  terra_meta.get("calibrated_count"),
            "rmse_m":            terra_meta.get("rmse_m"),
            "camera":            terra_meta.get("camera_model", "DJI Mavic 3E"),
            "terra_version":     terra_meta.get("terra_version"),
            "flight_date":       user_meta.get("flight_date", ""),
            "flying_altitude_m": terra_meta.get("flying_altitude_m"),
            "coverage_km2":      terra_meta.get("coverage_km2"),
        }
        # None 값 제거
        survey = {k: v for k, v in survey.items() if v is not None}

        geo: dict = {
            "epsg_2d":       32652,
            "epsg_2d_label": "WGS 84 / UTM zone 52N",
        }
        if terra_meta.get("bbox_wgs84"):
            geo["bbox_wgs84"] = terra_meta["bbox_wgs84"]
        if terra_meta.get("center_lat"):
            geo["center_wgs84"] = [terra_meta["center_lat"], terra_meta["center_lon"]]
        if terra_meta.get("ecef_center"):
            geo["ecef_center"] = terra_meta["ecef_center"]
        if terra_meta.get("altitude_m"):
            geo["altitude_m"] = terra_meta["altitude_m"]

        # 출력 파일 크기 추정 (result.tif)
        result_tif = dst_dir / "map" / "result.tif"
        dsm_tif = dst_dir / "map" / "dsm.tif"
        gsd = terra_meta.get("gsd_m", 0)

        outputs: dict = {}
        if result_tif.exists():
            outputs["result_tif"] = {"path": "map/result.tif", "gsd_m": gsd}
        if dsm_tif.exists():
            outputs["dsm_tif"] = {"path": "map/dsm.tif", "gsd_m": round(gsd * 2, 4)}

        tileset = dst_dir / "models" / "pc" / "0" / "terra_b3dms" / "tileset.json"
        if tileset.exists():
            outputs["tileset_3d"] = {
                "path": "models/pc/0/terra_b3dms/tileset.json",
                "kind": "3d-tiles",
                "coord_system": "ECEF",
                "available": True,
            }

        ply_files = list((dst_dir / "models" / "pc" / "0" / "terra_ply").rglob("*.ply")) \
            if (dst_dir / "models" / "pc" / "0" / "terra_ply").exists() else []
        if ply_files:
            sz = sum(p.stat().st_size for p in ply_files) // (1024 * 1024)
            outputs["pointcloud_ply"] = {
                "path": str(ply_files[0].relative_to(dst_dir)).replace("\\", "/"),
                "available": True,
                "size_mb": sz,
            }

        if terra_meta.get("zoom_min"):
            outputs["zoom_min"] = terra_meta["zoom_min"]
            outputs["zoom_max"] = terra_meta["zoom_max"]

        rtk = terra_meta.get("rtk_mode", "")
        notes = (
            f"DJI Terra {terra_meta.get('terra_version','?')}. "
            f"RTK {rtk}, RMSE {terra_meta.get('rmse_m','?')}m."
        )

        doc = {
            "id":          mission_id,
            "name":        name,
            "survey_info": survey,
            "geo":         geo,
            "outputs":     outputs,
            "notes":       notes,
        }

        # P-fix I2 (2026-05-29): 기존 meta.json 의 사용자 커스텀 필드 보존 +
        # 자동 백업. 이전엔 매 import 마다 doc 통째 덮어쓰기 → Phase 1 fix 마커
        # ("[데이터정합성 fix 2026-05-29]"), survey_info.z_trusted 사용자 override,
        # 사용자 메모 등이 무조건 소실. 신정책:
        #   1) 기존 파일 있으면 .bak_import_<ts> 자동 백업
        #   2) 기존 survey_info.z_trusted (override) 보존
        #   3) 기존 notes 의 "[데이터정합성 fix ..." 라인 보존 (덧붙임)
        #   4) 기존 doc 의 알려지지 않은 키 (사용자 추가 필드) 보존
        meta_p = dst_dir / "meta.json"
        dst_dir.mkdir(parents=True, exist_ok=True)
        if meta_p.exists():
            try:
                from datetime import datetime
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                bak_p = meta_p.with_suffix(f".json.bak_import_{ts}")
                shutil.copy2(meta_p, bak_p)

                old_doc = json.loads(meta_p.read_text(encoding="utf-8"))
                # (2) z_trusted override 보존
                old_si = old_doc.get("survey_info") or {}
                if "z_trusted" in old_si and "z_trusted" not in doc["survey_info"]:
                    doc["survey_info"]["z_trusted"] = old_si["z_trusted"]
                # (3) 기존 notes 의 fix 마커 라인 보존
                old_notes = old_doc.get("notes") or ""
                if "[데이터정합성 fix" in old_notes:
                    # 기존 notes 중 fix 마커 라인만 추출
                    keep_lines = [ln for ln in old_notes.splitlines()
                                  if "[데이터정합성 fix" in ln or "[데이터정합성 보정" in ln]
                    if keep_lines:
                        doc["notes"] = (doc["notes"] + " " + " ".join(keep_lines)).strip()
                # (4) 알려지지 않은 사용자 추가 키 보존 (top-level)
                known = {"id", "name", "survey_info", "geo", "outputs", "notes"}
                for k, v in old_doc.items():
                    if k not in known and k not in doc:
                        doc[k] = v
            except Exception:
                # 백업/병합 실패 시 새 doc 으로 진행 (안전 fallback)
                pass

        # P-fix C2: atomic write 로 부분 쓰기 방지
        _atomic_write_json(meta_p, doc, indent=4)

    # ── registry.json 등록 ────────────────────────────────────────
    def register_to_registry(
        self,
        mission_id: str,
        name: str,
        site_id: str,
        site_type: str,
        site_category: str,
        eup_myeon_dong: str,
        flight_date: str,
        terra_meta: dict,
    ) -> None:
        """registry.json에 미션 항목 추가 (중복 시 업데이트)."""
        reg: dict = {"version": "1.2", "missions": [], "sites": {}}
        if self.registry_file.exists():
            try:
                reg = json.loads(self.registry_file.read_text(encoding="utf-8"))
            except Exception:
                pass

        # sites에 신규 site_id 추가
        if site_id and site_id not in reg.get("sites", {}):
            reg.setdefault("sites", {})[site_id] = {
                "name": name,
                "site_type": site_type,
            }

        # site_types 목록 갱신
        types = reg.get("site_types", ["저수조", "저수지", "관정", "수원지", "기타"])
        if site_type not in types:
            types.append(site_type)
        reg["site_types"] = types

        # 출력 가용성 플래그
        dst_dir = self.dst_root / mission_id
        tileset = dst_dir / "models" / "pc" / "0" / "terra_b3dms" / "tileset.json"
        ply_ok = (dst_dir / "models" / "pc" / "0" / "terra_ply").exists()

        outputs = {
            "tiles_2d": {
                "available": (dst_dir / "map" / "result.tif").exists()
                             or any((dst_dir / "map").glob("[0-9]*")),
                "kind": "image_overlay",
                "source": "map/result.tif",
            },
            "tiles_3d": {
                "available": tileset.exists(),
                "tileset": "models/pc/0/terra_b3dms/tileset.json",
            },
            "dsm": {
                "available": (dst_dir / "map" / "dsm.tif").exists(),
                "source": "map/dsm.tif",
            },
            "pointcloud_ply": {"available": ply_ok},
        }

        entry = {
            "id":             mission_id,
            "site_id":        site_id,
            "name":           name,
            "site_type":      site_type,
            "site_category":  site_category,
            "eup_myeon_dong": eup_myeon_dong,
            "flight_date":    flight_date,
            "data_dir":       mission_id,
            "outputs":        outputs,
        }

        # 중복 제거 후 추가
        missions = [m for m in reg.get("missions", []) if m.get("id") != mission_id]
        missions.append(entry)
        # flight_date 기준 정렬
        missions.sort(key=lambda m: m.get("flight_date", ""))
        reg["missions"] = missions
        reg["updated"] = __import__("datetime").date.today().isoformat()

        # P-fix C2: atomic write 로 부분 쓰기 방지 (registry.json 손상 시
        # 기존 미션 전부 silent 소실 위험 차단).
        _atomic_write_json(self.registry_file, reg, indent=4)

    # ── master_drone.csv 등록 ─────────────────────────────────────
    def register_to_csv(
        self,
        mission_id: str,
        name: str,
        site_type: str,
        eup_myeon_dong: str,
        flight_date: str,
        terra_meta: dict,
    ) -> None:
        """master_drone.csv에 행 추가 (중복 시 업데이트)."""
        COLS = [
            "site_id", "site_name", "site_type", "eup_myeon_dong",
            "lon", "lat", "mission_id", "flight_date",
            "rtk_mode", "image_count", "rmse_m",
            "has_2d", "has_3d", "has_dsm", "has_ply",
            "gsd_cm", "memo",
        ]

        rows: list[dict] = []
        if self.master_csv.exists():
            try:
                with open(self.master_csv, "r", encoding="utf-8-sig") as f:
                    rows = list(csv.DictReader(f))
            except Exception:
                rows = []

        # P-fix C1 (2026-05-29): terra_meta 가 두 가지 형태로 호출됨 —
        #   (a) extract_meta() 산출 평탄 dict: {bbox_wgs84, rtk_mode, image_count, gsd_m, ...}
        #   (b) write_meta_json() 산출 nested doc: {survey_info:{...}, geo:{bbox_wgs84:...}, outputs:{...}}
        # 이전 코드는 (b) 만 가정 → tab99 가 (a) 를 전달하면 모든 컬럼이 빈 값으로 기록.
        # 두 경로 모두 안전 처리하도록 fallback chain 정비.
        if not isinstance(terra_meta, dict):
            terra_meta = {}

        def _t(key, default=""):
            """terra_meta 의 평탄 키 → survey_info.{key} → default."""
            if key in terra_meta and terra_meta[key] not in (None, ""):
                return terra_meta[key]
            si = terra_meta.get("survey_info") or {}
            v = si.get(key)
            return v if v not in (None, "") else default

        outputs = terra_meta.get("outputs") or {}
        dst_dir = self.dst_root / mission_id
        fb_paths = {
            "result_tif":     dst_dir / "map" / "result.tif",
            "tileset_3d":     dst_dir / "models" / "pc" / "0" / "terra_b3dms" / "tileset.json",
            "dsm_tif":        dst_dir / "map" / "dsm.tif",
            "pointcloud_ply": dst_dir / "models" / "pc" / "0" / "terra_ply",
        }

        def _has(key, fallback_path=None):
            v = outputs.get(key)
            if isinstance(v, dict):
                return "Y" if v.get("available") else "N"
            if v:
                return "Y"
            if fallback_path is not None and fallback_path.exists():
                if fallback_path.is_dir():
                    return "Y" if any(fallback_path.rglob("*.ply")) else "N"
                return "Y"
            return "N"

        gsd_m = None
        rt = outputs.get("result_tif") or {}
        if isinstance(rt, dict) and rt.get("gsd_m"):
            gsd_m = rt["gsd_m"]
        elif terra_meta.get("gsd_m"):
            gsd_m = terra_meta["gsd_m"]
        try:
            gsd_cm = round(float(gsd_m) * 100, 2) if gsd_m else ""
        except (TypeError, ValueError):
            gsd_cm = ""

        bbox = (terra_meta.get("geo") or {}).get("bbox_wgs84") or terra_meta.get("bbox_wgs84")
        center_lat = center_lon = ""
        if bbox and len(bbox) >= 4:
            center_lat = round((bbox[1] + bbox[3]) / 2, 6)
            center_lon = round((bbox[0] + bbox[2]) / 2, 6)
        else:
            cl_nested = (terra_meta.get("geo") or {}).get("center_wgs84")
            if cl_nested and len(cl_nested) >= 2:
                center_lat = round(float(cl_nested[0]), 6)
                center_lon = round(float(cl_nested[1]), 6)

        # P-fix I3 (2026-05-29): CSV Formula Injection 방어.
        # Excel 이 셀의 첫 문자가 =/+/-/@/\t/\r 일 때 수식으로 해석 →
        # 사용자 입력에 '=cmd|...'!A1' 등 삽입 시 Excel 열 때 명령 실행 위험.
        # 위험 prefix 면 single quote 로 회피.
        def _csv_safe(s):
            if not s:
                return s
            s = str(s)
            if s and s[0] in ("=", "+", "-", "@", "\t", "\r"):
                return "'" + s
            return s

        # P-fix C3 (2026-05-29): site_id 산출 일원화.
        # 이전: register_to_csv 는 mission_id.split("_",1)[0] 사용,
        #       register_to_registry 는 사용자 입력 site_id 사용 → 두 파일 mismatch.
        # 신규: registry.json 에 이미 등록된 site_id 를 우선 사용 → 두 파일 항상 일치.
        site_id_resolved = mission_id.split("_", 1)[0] if "_" in mission_id else mission_id
        try:
            if self.registry_file.exists():
                with open(self.registry_file, "r", encoding="utf-8") as f:
                    _reg = json.load(f)
                for _e in _reg.get("missions", []):
                    if _e.get("id") == mission_id and _e.get("site_id"):
                        site_id_resolved = _e["site_id"]
                        break
        except Exception:
            pass

        new_row = {
            "site_id":        site_id_resolved,
            "site_name":      _csv_safe(name),
            "site_type":      _csv_safe(site_type),
            "eup_myeon_dong": _csv_safe(eup_myeon_dong),
            "lon":            center_lon,
            "lat":            center_lat,
            "mission_id":     mission_id,
            "flight_date":    flight_date,
            "rtk_mode":       _t("rtk_mode"),
            "image_count":    _t("image_count"),
            "rmse_m":         _t("rmse_m"),
            "has_2d":         _has("result_tif",     fb_paths["result_tif"]),
            "has_3d":         _has("tileset_3d",     fb_paths["tileset_3d"]),
            "has_dsm":        _has("dsm_tif",        fb_paths["dsm_tif"]),
            "has_ply":        _has("pointcloud_ply", fb_paths["pointcloud_ply"]),
            "gsd_cm":         gsd_cm,
            "memo":           "",
        }

        updated = False
        for i, r in enumerate(rows):
            if r.get("mission_id") == mission_id:
                rows[i] = {**r, **{k: v for k, v in new_row.items() if v != ""}}
                updated = True
                break
        if not updated:
            rows.append(new_row)

        # P-fix C2: CSV 도 atomic write (BOM + DictWriter → 메모리 빌드 → 1회 디스크 쓰기).
        import io
        _buf = io.StringIO()
        _buf.write("\ufeff")
        writer = csv.DictWriter(_buf, fieldnames=COLS, lineterminator="\r\n")
        writer.writeheader()
        for r in rows:
            writer.writerow({k: r.get(k, "") for k in COLS})
        _atomic_write_text(self.master_csv, _buf.getvalue(), encoding="utf-8")
