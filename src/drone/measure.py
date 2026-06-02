"""거리·경사 측정 계산 (DJI Terra 식 좌표·거리 도구용).

순수 함수 모듈 — Streamlit/Folium 비의존, 단위테스트 가능.
좌표(Coordinate) 도구는 표고만 필요하므로 elevation.DsmSampler 를 직접 쓰고,
거리(Distance) 도구는 이 모듈의 함수로 4값(수평/직선/수직/경사)을 산출한다.

용어 (DJI Terra 매뉴얼 v5.2.5 p.24):
    수평거리(horizontal) : 두 점 라인의 수평 투영 거리 (측지 거리)
    직선거리(straight)   : 두 점의 공간(3D) 거리. 폴리라인이면 각 구간 합.
    수직거리(vertical)   : 두 점의 고도 차 (끝점 기준)
    경사(slope)          : 라인 세그먼트와 수평면 사이 각도(°)
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

from .geo import geodesic_distance_m

# (lat, lon, height_m|None) — height 가 None 이면 DSM 표고 미확보.
Point = Tuple[float, float, Optional[float]]


@dataclass
class DistanceResult:
    """거리 측정 결과 4값. 표고 미확보 시 vertical/slope 는 None."""
    horizontal_m: float          # 수평거리 (측지 투영 합)
    straight_m: float            # 직선(3D)거리. 표고 없으면 수평거리와 동일.
    vertical_m: Optional[float]  # 수직거리 (끝점 고도차). 표고 없으면 None.
    slope_deg: Optional[float]   # 경사각(°). 표고 없으면 None.
    has_elevation: bool          # 모든 정점에 표고가 있어 3D 값이 유효한지


def horizontal_distance_m(lat1: float, lon1: float,
                          lat2: float, lon2: float) -> float:
    """두 WGS84 점의 수평(측지) 거리(m). pyproj.Geod 기반 정확."""
    return geodesic_distance_m(lat1, lon1, lat2, lon2)


def slope_deg(vertical_m: float, horizontal_m: float) -> float:
    """경사각(°) = atan2(고도차, 수평거리). 수평 0 이면 ±90°."""
    return math.degrees(math.atan2(vertical_m, horizontal_m))


def segment_distance(p1: Point, p2: Point) -> DistanceResult:
    """두 점 사이 거리 4값. 한 점이라도 표고가 None 이면 3D 값 생략."""
    lat1, lon1, h1 = p1
    lat2, lon2, h2 = p2
    horiz = horizontal_distance_m(lat1, lon1, lat2, lon2)

    if h1 is None or h2 is None:
        return DistanceResult(
            horizontal_m=horiz, straight_m=horiz,
            vertical_m=None, slope_deg=None, has_elevation=False,
        )

    dz = h2 - h1
    straight = math.hypot(horiz, dz)
    return DistanceResult(
        horizontal_m=horiz,
        straight_m=straight,
        vertical_m=abs(dz),
        slope_deg=slope_deg(abs(dz), horiz),
        has_elevation=True,
    )


def polyline_distance(points: Sequence[Point]) -> DistanceResult:
    """폴리라인(2점 이상) 거리 4값.

    - 수평거리 : 인접 구간 수평거리의 합
    - 직선거리 : 인접 구간 3D 거리의 합 (표고 모두 있을 때)
    - 수직거리 : 끝점(첫·마지막) 고도 차 (Terra 정의)
    - 경사     : atan2(끝점 고도차, 끝점 수평거리)  ※전체 경로 기준 평균 경사

    표고가 하나라도 없으면 직선=수평, 수직/경사=None.
    """
    if len(points) < 2:
        raise ValueError("polyline_distance 는 점이 2개 이상이어야 합니다.")

    horiz_total = 0.0
    straight_total = 0.0
    all_elev = all(p[2] is not None for p in points)

    for a, b in zip(points[:-1], points[1:]):
        seg = segment_distance(a, b)
        horiz_total += seg.horizontal_m
        straight_total += seg.straight_m

    if not all_elev:
        return DistanceResult(
            horizontal_m=horiz_total, straight_m=horiz_total,
            vertical_m=None, slope_deg=None, has_elevation=False,
        )

    # 끝점 기준 수직거리·경사 (Terra: 두 포인트 간 고도차)
    h_first = points[0][2]
    h_last = points[-1][2]
    dz = (h_last - h_first) if (h_first is not None and h_last is not None) else 0.0
    # 끝점 직선 수평거리 (경사 분모) — 누적 수평합이 아닌 시점→종점 직선
    end_horiz = horizontal_distance_m(
        points[0][0], points[0][1], points[-1][0], points[-1][1]
    )
    return DistanceResult(
        horizontal_m=horiz_total,
        straight_m=straight_total,
        vertical_m=abs(dz),
        slope_deg=slope_deg(abs(dz), end_horiz),
        has_elevation=True,
    )


def polygon_area_m2(points: Sequence[Point]) -> float:
    """폴리곤(위경도 점열)의 측지 투영 면적(m²). DJI Terra 의 'Projection Area' 대응.

    pyproj.Geod.polygon_area_perimeter 로 WGS84 타원체 위 면적을 계산(부호는
    방향에 의존하므로 abs). 점이 3개 미만이면 0. height 는 무시(수평 투영면적).
    points 는 (lat, lon[, height]) 튜플 시퀀스.
    """
    if len(points) < 3:
        return 0.0
    import pyproj
    g = pyproj.Geod(ellps="WGS84")
    lats = [float(p[0]) for p in points]
    lons = [float(p[1]) for p in points]
    area, _perim = g.polygon_area_perimeter(lons, lats)
    return abs(float(area))
