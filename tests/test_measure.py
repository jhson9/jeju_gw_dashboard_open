# ==============================================================================
#  파일명: tests/test_measure.py
#  목적: src/drone/measure.py 의 거리·경사 계산 회귀 가드.
#        DJI Terra 식 좌표·거리 도구(tab32/33)의 4값 산출 정확성 보호.
#        수평거리(측지)·직선거리(3D)·수직거리(고도차)·경사(°).
# ==============================================================================
import math

import pytest

from src.drone.measure import (
    DistanceResult,
    horizontal_distance_m,
    segment_distance,
    polyline_distance,
    polygon_area_m2,
    slope_deg,
)


def test_horizontal_distance_known_pair():
    # 제주시청 부근(33.4996, 126.5312) → 약 1km 동쪽으로 이동한 점.
    # 경도 1도 ≈ 111320*cos(lat) m. lat 33.5 에서 0.01도 ≈ 928 m 근방.
    d = horizontal_distance_m(33.5, 126.50, 33.5, 126.51)
    assert 900 < d < 950   # 측지 거리 대략 928m


def test_slope_deg_basic():
    # 고도차 = 수평거리 → 45도
    assert slope_deg(10.0, 10.0) == pytest.approx(45.0, abs=1e-6)
    # 고도차 0 → 0도
    assert slope_deg(0.0, 100.0) == pytest.approx(0.0, abs=1e-6)


def test_segment_with_elevation():
    # 두 점 수평 30m(근사), 고도차 40m → 직선 50m(3-4-5), 경사 atan2(40,30)
    p1 = (33.5000, 126.5000, 100.0)
    # 동쪽으로 약 30m 이동: 0.01도≈928m → 30m ≈ 0.000323도
    p2 = (33.5000, 126.5000 + 30 / (111320 * math.cos(math.radians(33.5))), 140.0)
    r = segment_distance(p1, p2)
    assert r.has_elevation is True
    assert r.horizontal_m == pytest.approx(30.0, abs=1.0)
    assert r.vertical_m == pytest.approx(40.0, abs=1e-6)
    assert r.straight_m == pytest.approx(math.hypot(r.horizontal_m, 40.0), abs=1e-6)
    assert r.slope_deg == pytest.approx(math.degrees(math.atan2(40.0, r.horizontal_m)), abs=1e-6)


def test_segment_without_elevation():
    # 한 점 표고 None → 3D 값 생략, 직선=수평
    p1 = (33.5, 126.5, None)
    p2 = (33.5, 126.51, 120.0)
    r = segment_distance(p1, p2)
    assert r.has_elevation is False
    assert r.vertical_m is None
    assert r.slope_deg is None
    assert r.straight_m == pytest.approx(r.horizontal_m, abs=1e-9)


def test_polyline_sums_segments():
    # 3점 직선 동진: 수평거리 = 두 구간 합.
    base_lon = 126.5
    step = 30 / (111320 * math.cos(math.radians(33.5)))
    pts = [
        (33.5, base_lon, 100.0),
        (33.5, base_lon + step, 110.0),
        (33.5, base_lon + 2 * step, 130.0),
    ]
    r = polyline_distance(pts)
    assert r.has_elevation is True
    assert r.horizontal_m == pytest.approx(60.0, abs=1.5)
    # 수직거리 = 끝점 고도차 (130-100=30)
    assert r.vertical_m == pytest.approx(30.0, abs=1e-6)
    # 직선거리 = 구간별 3D 합 (각 30m 수평)
    seg = math.hypot(30.0, 10.0) + math.hypot(30.0, 20.0)
    assert r.straight_m == pytest.approx(seg, abs=1.5)


def test_polyline_requires_two_points():
    with pytest.raises(ValueError):
        polyline_distance([(33.5, 126.5, 100.0)])


def test_polyline_missing_elevation_degrades():
    pts = [(33.5, 126.5, 100.0), (33.5, 126.51, None)]
    r = polyline_distance(pts)
    assert r.has_elevation is False
    assert r.vertical_m is None
    assert r.straight_m == pytest.approx(r.horizontal_m, abs=1e-9)


def test_polygon_area_square():
    # 위도 33.5 부근에서 한 변 100m 사각형. 동쪽 100m, 북쪽 100m.
    lat0, lon0 = 33.5, 126.5
    dlat = 100.0 / 110540.0
    dlon = 100.0 / (111320.0 * math.cos(math.radians(lat0)))
    sq = [
        (lat0, lon0, None),
        (lat0, lon0 + dlon, None),
        (lat0 + dlat, lon0 + dlon, None),
        (lat0 + dlat, lon0, None),
    ]
    area = polygon_area_m2(sq)
    assert area == pytest.approx(10000.0, rel=0.02)   # 100m × 100m ≈ 1만 m²


def test_polygon_area_orientation_independent():
    lat0, lon0 = 33.5, 126.5
    d = 0.001
    cw = [(lat0, lon0, None), (lat0, lon0 + d, None), (lat0 + d, lon0 + d, None)]
    ccw = list(reversed(cw))
    assert polygon_area_m2(cw) == pytest.approx(polygon_area_m2(ccw), rel=1e-9)


def test_polygon_area_too_few_points():
    assert polygon_area_m2([(33.5, 126.5, None), (33.5, 126.51, None)]) == 0.0
