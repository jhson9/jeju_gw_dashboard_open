# ==============================================================================
#  파일명: tests/test_drone_meta_bbox_consistency.py
#  목적: 모든 드론 미션 meta.json 의 bbox/center 가 실제 result.tif 의
#        georeferencing 과 일치하는지 자동 검증 — CI 회귀 안전망.
#
#  배경 (2026-05-29 회귀):
#    Tab32 측정값이 1/2~ 로 잘못 표시되는 문제 발생 (예: 19.05m vs 정상 40-60m).
#    원인은 meta.json 의 bbox_wgs84 가 result.tif 의 실제 georeferencing 과
#    어긋난 채로 저장되어 있어, ImageOverlay 가 이미지를 잘못된 영역에 stretch
#    한 결과 픽셀↔위경도 변환이 왜곡된 것.
#
#  본 테스트가 CI 단계에서 같은 회귀를 즉시 검출하도록 보호.
#  새 미션 import 후 또는 메타 수동 편집 시 본 테스트가 깨지면 그 자체로
#  데이터 손상 신호.
# ==============================================================================
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

DRONE_ROOT = PROJECT_ROOT / "data" / "04_drone"


def _list_mission_dirs() -> list[Path]:
    """data/04_drone 의 미션 폴더 목록 (result.tif 있는 것만)."""
    if not DRONE_ROOT.exists():
        return []
    return sorted(
        d for d in DRONE_ROOT.iterdir()
        if d.is_dir() and (d / "map" / "result.tif").exists()
    )


def _mission_ids() -> list[str]:
    return [d.name for d in _list_mission_dirs()]


@pytest.mark.skipif(not DRONE_ROOT.exists(), reason="data/04_drone 폴더 없음")
def test_meta_validator_module_importable():
    """meta_validator 모듈 import 검증."""
    from src.drone.meta_validator import check_mission_bbox, fix_mission_bbox
    assert callable(check_mission_bbox)
    assert callable(fix_mission_bbox)


@pytest.mark.skipif(
    not _list_mission_dirs(),
    reason="result.tif 가 있는 드론 미션 없음"
)
@pytest.mark.parametrize("mission_id", _mission_ids(), ids=lambda x: x)
def test_mission_bbox_matches_result_tif(mission_id: str):
    """각 미션의 meta.bbox_wgs84 가 result.tif georeferencing 과 일치해야 함.

    회귀 시나리오:
      - importer 가 잘못된 source 에서 bbox 추출
      - 사용자가 meta.json 수동 편집 실수
      - DJI Terra 재처리 후 result.tif 갱신했으나 메타 미동기화

    측정 도구(Tab32) 의 거리값 정확성이 본 검증에 직접 의존.
    """
    try:
        import rasterio  # noqa: F401
    except ImportError:
        pytest.skip("rasterio 미설치 (테스트 환경 의존성)")

    from src.drone.meta_validator import check_mission_bbox

    mission_dir = DRONE_ROOT / mission_id
    report = check_mission_bbox(mission_dir)

    assert report.has_result_tif, f"{mission_id}: result.tif 없음"
    assert report.meta_bbox is not None, (
        f"{mission_id}: meta.json 에 bbox_wgs84 없음 → "
        f"신규 import 시 src/drone/importer.py 가 자동 생성해야 함"
    )

    # 위치 오차 1m 이하
    assert report.lon_error_m < 1.0, (
        f"{mission_id}: lon_min 오차 {report.lon_error_m:.2f}m > 1m. "
        f"메타 bbox 가 result.tif 와 다름 — Tab32 측정값 왜곡 가능. "
        f"src.drone.meta_validator.fix_mission_bbox() 로 자동 보정."
    )
    assert report.lat_error_m < 1.0, (
        f"{mission_id}: lat_min 오차 {report.lat_error_m:.2f}m > 1m"
    )

    # 종횡비 1% 이내 — 가장 중요. 이게 깨지면 측정값이 비율만큼 왜곡됨
    # (예: lon_span_ratio=2.0 → 가로 측정 거리가 실제의 2배로 표시)
    assert abs(report.lon_span_ratio - 1.0) < 0.01, (
        f"{mission_id}: lon span 비율 {report.lon_span_ratio:.3f} ≠ 1.0. "
        f"ImageOverlay 가 이미지를 가로 ×{report.lon_span_ratio:.2f} 로 "
        f"stretch → 측정 거리값이 같은 비율로 왜곡됨. "
        f"메타 자동 보정 필요."
    )
    assert abs(report.lat_span_ratio - 1.0) < 0.01, (
        f"{mission_id}: lat span 비율 {report.lat_span_ratio:.3f} ≠ 1.0"
    )


@pytest.mark.skipif(
    not _list_mission_dirs(),
    reason="result.tif 가 있는 드론 미션 없음"
)
def test_all_missions_consistent_summary():
    """전체 미션 일괄 — 종합 카운트. 개별 테스트 fail 시 추가 컨텍스트."""
    try:
        import rasterio  # noqa: F401
    except ImportError:
        pytest.skip("rasterio 미설치")

    from src.drone.meta_validator import check_all_missions

    reports = check_all_missions(DRONE_ROOT)
    inconsistent = [r for r in reports if not r.is_consistent]
    if inconsistent:
        details = "\n".join(f"  - {r.summary()}" for r in inconsistent)
        pytest.fail(
            f"{len(inconsistent)}/{len(reports)} 미션의 메타 bbox 가 "
            f"result.tif 와 불일치:\n{details}\n\n"
            f"→ 데이터 관리 탭의 '메타 bbox 정합성 검사' 실행 또는 "
            f"src.drone.meta_validator.fix_mission_bbox() 호출로 보정."
        )
