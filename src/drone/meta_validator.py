# ==============================================================================
#  파일명: src/drone/meta_validator.py
#  목적: 드론 미션 meta.json 의 georeferencing 메타가 실제 result.tif 와
#        일치하는지 검증·보정하는 단일 진실 원천 헬퍼.
# ------------------------------------------------------------------------------
#  배경 (반드시 읽을 것 — 회귀 방지):
#    2026-05-29 사용자 보고: Tab32 정사영상 측정 도구에서 거리값이 실제보다
#    1/2~ 로 축소 표시 (예: 두 저수조 사이 40m → 19.05m 로 표시).
#
#    원인:
#      1. importer.py 가 bbox 를 DJI Terra 의 blocks_wgs84.json (비행 영역)
#         에서 추출 → 실제 result.tif 의 georeferencing 과 다름
#      2. blocks_wgs84.json 의 첫 번째 block 만 사용 → 다중 block 미션에서
#         일부 영역만 cover
#      3. Leaflet ImageOverlay 는 잘못된 bbox 에 이미지를 강제 stretch →
#         픽셀↔위경도 변환 왜곡 → 측정 거리값 왜곡
#
#    10 개 미션 중 7 개가 종횡비까지 깨져있던 상태 (lon×0.84 ~ ×2.02)
#
#  해결책:
#    - "bbox 의 단일 진실 원천 = result.tif 의 georeferencing"  원칙 확립
#    - 본 모듈이 그 원칙을 단일 진입점으로 강제
#    - importer 신규 등록 / tab99 진단 / pytest CI / Mission lazy load 모두
#      본 모듈 함수 호출로 일관성 확보
#
#  ⚠️ 신규 코드는 반드시 본 모듈을 거쳐서 bbox 를 다루세요.
#     직접 blocks_wgs84.json 파싱하거나 메타의 bbox 를 무비판적으로 신뢰
#     하면 동일 회귀 재발.
# ==============================================================================
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

# 허용 오차 (실측 비교 시).
# - lon/lat 위치 오차: 1.0 m 이하 (rasterio transform_bounds 의 반올림 등 흡수)
# - 종횡비 비율 차이: 0.01 (1% 이하) — 그 이상이면 명백한 메타 부정확
POSITION_TOLERANCE_M: float = 1.0
RATIO_TOLERANCE: float = 0.01


@dataclass
class BboxConsistencyReport:
    """단일 미션 bbox 정합성 검증 결과.

    Attributes
    ----------
    mission_id : str
        미션 폴더명 (예: '2501_구좌종달저수조').
    has_result_tif : bool
        result.tif 파일 존재 여부.
    meta_bbox : list[float] | None
        meta.json 의 bbox_wgs84 [lon_min, lat_min, lon_max, lat_max].
    actual_bbox : list[float] | None
        result.tif 의 georeferencing 에서 산출한 실측 bbox.
    lon_error_m / lat_error_m : float
        bbox 좌하단(min) 좌표 오차 (미터).
    lon_span_ratio / lat_span_ratio : float
        meta / actual span 비율. 1.0 이 정확. 0.5 또는 2.0 이면 ImageOverlay
        stretch 로 측정값이 1/2 또는 2배 왜곡됨을 의미.
    is_consistent : bool
        오차 + 종횡비가 모두 허용 범위 내인지.
    severity : str
        'ok' | 'minor' | 'major' | 'missing'.
    """
    mission_id: str
    has_result_tif: bool
    meta_bbox: "list[float] | None"
    actual_bbox: "list[float] | None"
    lon_error_m: float
    lat_error_m: float
    lon_span_ratio: float
    lat_span_ratio: float
    is_consistent: bool
    severity: str

    def summary(self) -> str:
        """사람이 읽기 좋은 1줄 요약."""
        if not self.has_result_tif:
            return f"{self.mission_id}: result.tif 없음 — 검증 skip"
        if not self.meta_bbox:
            return f"{self.mission_id}: meta.bbox_wgs84 없음"
        if self.is_consistent:
            return f"{self.mission_id}: ✅ 정상 (오차 {self.lon_error_m:.2f}/{self.lat_error_m:.2f} m, 비율 {self.lon_span_ratio:.3f}/{self.lat_span_ratio:.3f})"
        return (
            f"{self.mission_id}: ❌ {self.severity.upper()} — "
            f"위치 오차 lon={self.lon_error_m:.1f}m lat={self.lat_error_m:.1f}m, "
            f"종횡비 lon×{self.lon_span_ratio:.2f} lat×{self.lat_span_ratio:.2f}"
        )


def extract_bbox_from_result_tif(result_tif_path: Path) -> "tuple[list[float], int, int, float] | None":
    """result.tif 에서 WGS84 bbox + (width, height, gsd_m) 추출.

    Returns
    -------
    (bbox, width, height, gsd_m) | None
        bbox 형식: [lon_min, lat_min, lon_max, lat_max] (round 6 자리).
        실패 시 None — 호출자가 폴백 처리.

    Notes
    -----
    이 함수가 본 모듈의 핵심. **신규 코드는 반드시 본 함수를 거쳐 bbox 를
    얻을 것.** 직접 rasterio 호출이 산재하면 비일관성 위험.
    """
    if not result_tif_path or not result_tif_path.exists():
        return None
    try:
        import rasterio
        from rasterio.warp import transform_bounds
    except ImportError:
        logger.warning("rasterio 미설치 — bbox 추출 불가. requirements.txt 확인.")
        return None
    try:
        with rasterio.open(result_tif_path) as src:
            wgs = transform_bounds(src.crs, "EPSG:4326", *src.bounds)
            return (
                [round(wgs[0], 6), round(wgs[1], 6),
                 round(wgs[2], 6), round(wgs[3], 6)],
                src.width, src.height,
                round(abs(src.transform[0]), 6),
            )
    except Exception as e:
        logger.warning("result.tif 열기 실패 (%s): %s", result_tif_path, e)
        return None


def check_mission_bbox(mission_dir: Path) -> BboxConsistencyReport:
    """단일 미션의 메타 bbox vs result.tif 정합성 검증.

    Parameters
    ----------
    mission_dir : Path
        미션 폴더 (예: data/04_drone/2501_구좌종달저수조/).

    Returns
    -------
    BboxConsistencyReport
        검증 결과. ``is_consistent=False`` 면 ``fix_mission_bbox`` 로 보정 가능.
    """
    import json
    mid = mission_dir.name
    meta_p = mission_dir / "meta.json"
    tif_p = mission_dir / "map" / "result.tif"

    has_tif = tif_p.exists()
    meta_bbox = None
    if meta_p.exists():
        try:
            meta = json.loads(meta_p.read_text(encoding="utf-8"))
            meta_bbox = meta.get("geo", {}).get("bbox_wgs84")
        except Exception as e:
            logger.warning("%s meta.json 읽기 실패: %s", mid, e)

    if not has_tif:
        return BboxConsistencyReport(
            mission_id=mid, has_result_tif=False,
            meta_bbox=meta_bbox, actual_bbox=None,
            lon_error_m=0.0, lat_error_m=0.0,
            lon_span_ratio=1.0, lat_span_ratio=1.0,
            is_consistent=True, severity="missing",
        )

    extracted = extract_bbox_from_result_tif(tif_p)
    if extracted is None:
        return BboxConsistencyReport(
            mission_id=mid, has_result_tif=True,
            meta_bbox=meta_bbox, actual_bbox=None,
            lon_error_m=0.0, lat_error_m=0.0,
            lon_span_ratio=1.0, lat_span_ratio=1.0,
            is_consistent=False, severity="missing",
        )
    actual_bbox = extracted[0]

    if not meta_bbox or len(meta_bbox) < 4:
        return BboxConsistencyReport(
            mission_id=mid, has_result_tif=True,
            meta_bbox=meta_bbox, actual_bbox=actual_bbox,
            lon_error_m=0.0, lat_error_m=0.0,
            lon_span_ratio=0.0, lat_span_ratio=0.0,
            is_consistent=False, severity="missing",
        )

    lat_c = (meta_bbox[1] + meta_bbox[3]) / 2
    cos_lat = math.cos(math.radians(lat_c))
    lon_err_m = abs(meta_bbox[0] - actual_bbox[0]) * 111000 * cos_lat
    lat_err_m = abs(meta_bbox[1] - actual_bbox[1]) * 111000
    m_lon_s = (meta_bbox[2] - meta_bbox[0]) * 111000 * cos_lat
    a_lon_s = (actual_bbox[2] - actual_bbox[0]) * 111000 * cos_lat
    m_lat_s = (meta_bbox[3] - meta_bbox[1]) * 111000
    a_lat_s = (actual_bbox[3] - actual_bbox[1]) * 111000
    lon_ratio = m_lon_s / a_lon_s if a_lon_s > 0 else 0.0
    lat_ratio = m_lat_s / a_lat_s if a_lat_s > 0 else 0.0

    pos_ok = lon_err_m <= POSITION_TOLERANCE_M and lat_err_m <= POSITION_TOLERANCE_M
    ratio_ok = abs(lon_ratio - 1.0) <= RATIO_TOLERANCE and abs(lat_ratio - 1.0) <= RATIO_TOLERANCE
    is_consistent = pos_ok and ratio_ok

    # severity 결정
    if is_consistent:
        severity = "ok"
    elif (abs(lon_ratio - 1.0) > 0.10 or abs(lat_ratio - 1.0) > 0.10
          or lon_err_m > 50 or lat_err_m > 50):
        severity = "major"  # 측정값에 명백한 영향
    else:
        severity = "minor"

    return BboxConsistencyReport(
        mission_id=mid, has_result_tif=True,
        meta_bbox=meta_bbox, actual_bbox=actual_bbox,
        lon_error_m=lon_err_m, lat_error_m=lat_err_m,
        lon_span_ratio=lon_ratio, lat_span_ratio=lat_ratio,
        is_consistent=is_consistent, severity=severity,
    )


def fix_mission_bbox(mission_dir: Path, *, dry_run: bool = False,
                      backup: bool = True) -> "tuple[bool, str]":
    """단일 미션의 메타 bbox 를 result.tif georeferencing 으로 자동 보정.

    Parameters
    ----------
    dry_run : bool
        True 면 파일 변경 없이 시뮬레이션만.
    backup : bool
        True 면 meta.json.bak_<timestamp> 백업 생성.

    Returns
    -------
    (changed, message)
        changed=True 면 갱신됨 (또는 dry_run 에서 갱신 예정).
    """
    import json
    import shutil
    from datetime import datetime

    mid = mission_dir.name
    meta_p = mission_dir / "meta.json"
    tif_p = mission_dir / "map" / "result.tif"
    if not meta_p.exists():
        return False, f"{mid}: meta.json 없음"
    if not tif_p.exists():
        return False, f"{mid}: result.tif 없음 (보정 skip)"

    extracted = extract_bbox_from_result_tif(tif_p)
    if extracted is None:
        return False, f"{mid}: result.tif 추출 실패"
    new_bbox, r_w, r_h, r_gsd = extracted
    new_center = [round((new_bbox[1] + new_bbox[3]) / 2, 6),
                   round((new_bbox[0] + new_bbox[2]) / 2, 6)]

    meta = json.loads(meta_p.read_text(encoding="utf-8"))
    old_bbox = meta.get("geo", {}).get("bbox_wgs84")
    if old_bbox == new_bbox:
        return False, f"{mid}: 이미 일치 — 변경 없음"

    if dry_run:
        return True, f"{mid}: dry_run — old={old_bbox} → new={new_bbox}"

    if backup:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        shutil.copy2(meta_p, meta_p.with_suffix(f".json.bak_{ts}"))

    meta.setdefault("geo", {})
    meta["geo"]["bbox_wgs84"] = new_bbox
    meta["geo"]["center_wgs84"] = new_center
    if "outputs" in meta and "result_tif" in meta["outputs"]:
        meta["outputs"]["result_tif"]["size"] = [r_w, r_h]
        meta["outputs"]["result_tif"]["gsd_m"] = r_gsd

    meta_p.write_text(json.dumps(meta, ensure_ascii=False, indent=4), encoding="utf-8")
    return True, f"{mid}: ✅ 갱신 (old span 변경됨)"


def check_all_missions(drone_root: Path) -> "list[BboxConsistencyReport]":
    """data/04_drone 의 모든 미션 일괄 검증.

    Returns
    -------
    list[BboxConsistencyReport]
        미션 폴더 알파벳 순.
    """
    reports = []
    for d in sorted(drone_root.iterdir()):
        if d.is_dir() and (d / "map").exists():
            reports.append(check_mission_bbox(d))
    return reports
