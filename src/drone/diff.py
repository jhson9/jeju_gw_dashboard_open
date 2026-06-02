"""시계열 미션 비교 — 같은 장소(site_id)의 다른 시기 2건을 align·차분.

**현재 상태: Phase 2 구현 대기 (골격만 정의).**
4개 미션이 모두 다른 장소라 시계열 비교 가능한 site 가 없는 상태.
2026-06-23 경 송당저수조 재촬영 → "songdang_reservoir" site 에 2건이 모이면
이 모듈의 실제 구현을 채워서 활성화.

설계 방향:
- MissionPair (before, after) 데이터 클래스
- DsmDiffAnalyzer: 두 DSM 의 BBOX 교집합 → 동일 해상도로 resample → Δ raster
- 2D 비교: 두 정사사진을 같은 BBOX 로 swipe/blend (Leaflet sidebyside 플러그인)
- 3D 비교: CesiumJS 의 두 tileset 토글
- 결과: 차분 heatmap (RdBu colormap, 음수 파랑·양수 빨강), Δ표고 통계

외부에서 사용:
    from src.drone import DroneRegistry, MissionPair, DsmDiffAnalyzer
    reg = DroneRegistry()
    sites = reg.list_comparable_sites()   # 미션 2건+ 인 site 만
    for site in sites:
        pair = MissionPair.latest_two(site["missions"])
        analyzer = DsmDiffAnalyzer(pair)
        # result = analyzer.compute_diff()   # Phase 2 구현 예정
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from .registry import Mission

_logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class MissionPair:
    """시계열 비교용 미션 쌍 — 같은 site_id 의 두 미션 (before/after).

    `before.flight_date < after.flight_date` 보장 (생성자가 정렬).
    """
    site_id: str
    before: Mission
    after: Mission

    @classmethod
    def from_two(cls, m1: Mission, m2: Mission) -> "MissionPair":
        """두 미션을 시간 순서로 정렬해 MissionPair 생성."""
        if (m1.site_id or m1.id) != (m2.site_id or m2.id):
            raise ValueError(
                f"다른 site_id 의 미션을 비교할 수 없습니다: "
                f"{m1.id}({m1.site_id}) vs {m2.id}({m2.site_id})"
            )
        if m1.flight_date <= m2.flight_date:
            before, after = m1, m2
        else:
            before, after = m2, m1
        return cls(site_id=(m1.site_id or m1.id), before=before, after=after)

    @classmethod
    def latest_two(cls, missions: Sequence[Mission]) -> Optional["MissionPair"]:
        """미션 리스트에서 가장 최근 두 건으로 pair 구성. 2건 미만이면 None."""
        if len(missions) < 2:
            return None
        sorted_ms = sorted(missions, key=lambda m: m.flight_date)
        return cls.from_two(sorted_ms[-2], sorted_ms[-1])

    @property
    def label(self) -> str:
        return f"{self.before.flight_date} → {self.after.flight_date}"

    @property
    def days_between(self) -> Optional[int]:
        """두 촬영일 사이 일수. 파싱 실패 시 None."""
        from datetime import datetime
        try:
            d1 = datetime.strptime(self.before.flight_date, "%Y-%m")
            d2 = datetime.strptime(self.after.flight_date, "%Y-%m")
            return (d2 - d1).days
        except (ValueError, TypeError):
            return None


@dataclass(frozen=True)
class DsmDiffResult:
    """DSM 차분 결과 — Phase 2 에서 채움.

    필드 예시 (구현 시):
      diff_raster_path : Path  — Δz 색상 매핑 PNG
      bbox_wgs84       : tuple — 교집합 BBOX
      stats            : dict  — {mean, std, min, max, p05, p95, pixel_count}
      sign_split       : dict  — {positive_m3, negative_m3, net_m3} (체적)
    """
    pair: MissionPair
    diff_raster_path: Optional[Path] = None
    bbox_wgs84: Optional[tuple[float, float, float, float]] = None
    stats: Optional[dict] = None


class DsmDiffAnalyzer:
    """두 미션의 DSM 을 align·차분해 변화 raster + 통계 산출.

    **Phase 2 미구현** — 현재는 인터페이스만 정의. 송당저수조 재촬영 후 활성화.

    구현 계획:
    1. before/after DSM 의 EPSG·BBOX·해상도 추출
    2. BBOX 교집합 계산 (lon_min, lat_min, lon_max, lat_max)
    3. 두 raster 를 같은 해상도(GSD 더 큰 쪽 기준)·격자로 resample
       - 옵션: scipy.interpolate.RegularGridInterpolator
    4. Δz = after - before (numpy)
    5. 통계: 평균/표준편차/사분위/유효픽셀 수
    6. RdBu colormap 으로 heatmap PNG 저장 → derived/diff_{site_id}_{ts}.png
    7. (옵션) 면적 가중 체적 합 (m³)

    제약 (DJI Terra 전문가 시각):
    - 두 미션의 RTK 모드가 다르면 절대 z 편향이 다를 수 있어 글로벌 offset 보정 필요
    - 안정 영역(예: 도로·바위) 의 Δz 평균을 0 으로 만드는 plane fitting 권장
    - 식생 계절 변화(여름 무성·겨울 잎 없음)는 DSM 차이로 잘못 잡힐 수 있음
    - 같은 site 라도 BBOX 가 일부 비대칭일 수 있어 교집합 영역만 산출
    """

    def __init__(self, pair: MissionPair):
        self.pair = pair

    def is_feasible(self) -> tuple[bool, str]:
        """차분 가능 여부 + 사유 메시지.

        - before/after 모두 DSM 보유 + BBOX 메타 존재
        - BBOX 교집합 면적 > 0
        """
        if not self.pair.before.has("dsm"):
            return False, f"before 미션 {self.pair.before.id} 에 DSM 없음"
        if not self.pair.after.has("dsm"):
            return False, f"after 미션 {self.pair.after.id} 에 DSM 없음"
        b1 = self.pair.before.bbox_wgs84
        b2 = self.pair.after.bbox_wgs84
        if b1 is None or b2 is None:
            return False, "BBOX 메타 누락 (meta.json geo.bbox_wgs84 확인)"
        # 교집합 검사
        ix_lon_min = max(b1[0], b2[0])
        ix_lat_min = max(b1[1], b2[1])
        ix_lon_max = min(b1[2], b2[2])
        ix_lat_max = min(b1[3], b2[3])
        if ix_lon_min >= ix_lon_max or ix_lat_min >= ix_lat_max:
            return False, "두 미션 BBOX 교집합이 없음 — 같은 장소가 아닐 가능성"
        return True, "차분 가능"

    def intersection_bbox(self) -> Optional[tuple[float, float, float, float]]:
        """두 미션 BBOX 의 교집합 (lon_min, lat_min, lon_max, lat_max). 없으면 None."""
        b1 = self.pair.before.bbox_wgs84
        b2 = self.pair.after.bbox_wgs84
        if not b1 or not b2:
            return None
        ix = (
            max(b1[0], b2[0]), max(b1[1], b2[1]),
            min(b1[2], b2[2]), min(b1[3], b2[3]),
        )
        if ix[0] >= ix[2] or ix[1] >= ix[3]:
            return None
        return ix

    def compute_diff(self) -> DsmDiffResult:
        """Δ raster + 통계 산출. **Phase 2 미구현 — 골격만 반환.**"""
        ok, msg = self.is_feasible()
        if not ok:
            _logger.warning("DsmDiffAnalyzer.compute_diff infeasible: %s", msg)
        return DsmDiffResult(
            pair=self.pair,
            bbox_wgs84=self.intersection_bbox(),
            stats=None,
            diff_raster_path=None,
        )
