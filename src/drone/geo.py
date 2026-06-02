"""드론 자료 지오레퍼런스 유틸.

- GeoTIFF 메타데이터 추출 (PIL TIFF tag 기반 — rasterio/gdal 무의존)
- WGS84 ↔ ECEF 변환 (pyproj)
- UTM ↔ WGS84 변환 (pyproj)

DJI Terra 산출물의 2D GeoTIFF 는 WGS 84 / UTM zone 52N(EPSG:32652) 고정.
3D Tiles 의 boundingVolume 은 ECEF(EPSG:4978) 좌표.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pyproj

# ── EPSG 상수 ────────────────────────────────────────────────────────────────
EPSG_WGS84 = 4326   # 위경도 + 타원체 고도
EPSG_ECEF  = 4978   # 지구중심 직교좌표 (CesiumJS 3D Tiles)
EPSG_UTM52N = 32652 # DJI Terra 한국 영역 기본 출력

# pyproj Transformer 캐시 (모듈 레벨 1회 생성 — 매번 만들면 200ms 오버헤드)
_TFM_CACHE: dict[tuple[int, int], pyproj.Transformer] = {}


def _get_transformer(src_epsg: int, dst_epsg: int) -> pyproj.Transformer:
    key = (src_epsg, dst_epsg)
    if key not in _TFM_CACHE:
        _TFM_CACHE[key] = pyproj.Transformer.from_crs(
            f"EPSG:{src_epsg}", f"EPSG:{dst_epsg}", always_xy=True
        )
    return _TFM_CACHE[key]


def ecef_to_wgs84(x: float, y: float, z: float) -> tuple[float, float, float]:
    """ECEF(EPSG:4978) → WGS84 lon/lat/alt(m)."""
    tfm = _get_transformer(EPSG_ECEF, EPSG_WGS84)
    lon, lat, alt = tfm.transform(x, y, z)
    return lon, lat, alt


def wgs84_to_ecef(lon: float, lat: float, alt: float = 0.0) -> tuple[float, float, float]:
    """WGS84 lon/lat/alt → ECEF(EPSG:4978) x/y/z."""
    tfm = _get_transformer(EPSG_WGS84, EPSG_ECEF)
    x, y, z = tfm.transform(lon, lat, alt)
    return x, y, z


def utm_to_wgs84(easting: float, northing: float, utm_epsg: int = EPSG_UTM52N
                 ) -> tuple[float, float]:
    """UTM (EPSG:32652 등) → WGS84 lon/lat."""
    tfm = _get_transformer(utm_epsg, EPSG_WGS84)
    lon, lat = tfm.transform(easting, northing)
    return lon, lat


def geodesic_distance_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """WGS84 타원체 위 두 점 사이의 측지 거리(m). pyproj.Geod 정확.

    같은 미션 내 두 점 클릭 시 관로 길이·면적 등 상대 측정에 사용.
    """
    g = pyproj.Geod(ellps="WGS84")
    _, _, dist = g.inv(lon1, lat1, lon2, lat2)
    return float(dist)


@dataclass(frozen=True)
class GeoTiffMeta:
    """GeoTIFF 메타데이터 (PIL TIFF tag 기반 추출 결과)."""
    width: int
    height: int
    epsg: int
    epsg_label: str
    gsd_m: float
    bbox_native: tuple[float, float, float, float]   # (x_min, y_min, x_max, y_max) 원본 좌표계
    bbox_wgs84: tuple[float, float, float, float]    # (lon_min, lat_min, lon_max, lat_max)
    center_wgs84: tuple[float, float]                # (lat, lon)


def extract_geotiff_bbox(path: Path, *, max_pixels: Optional[int] = None
                         ) -> Optional[GeoTiffMeta]:
    """GeoTIFF 파일에서 BBOX·해상도·좌표계 추출.

    rasterio·gdal 없이 PIL 의 TIFF tag 만으로 동작. 큰 GeoTIFF(2억 픽셀 이상)
    도 헤더만 읽으므로 메모리 부담 없음 (decompression bomb 가드는 자동 해제).

    Parameters
    ----------
    path : Path
        GeoTIFF 파일 경로.
    max_pixels : int | None
        PIL.Image.MAX_IMAGE_PIXELS 임시 오버라이드. None 이면 무제한.

    Returns
    -------
    GeoTiffMeta | None
        파일이 없거나 geo tag 가 없으면 None.
    """
    if not path.exists():
        return None

    # 늦은 import — PIL 미설치 환경 보호
    from PIL import Image
    prev_limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = max_pixels   # None = 무제한
    try:
        with Image.open(path) as img:
            tags = img.tag_v2
            w, h = img.size
            tie = tags.get(33922)   # ModelTiepoint
            scl = tags.get(33550)   # ModelPixelScale
            geoasc = tags.get(34737, "")
            if not (tie and scl):
                return None
            x0, y0 = float(tie[3]), float(tie[4])
            sx, sy = float(scl[0]), float(scl[1])
            x1 = x0 + w * sx
            y1 = y0 - h * sy

            # EPSG 추출 — GeoAsciiParams 의 라벨에서 추론. UTM 52N 패턴 매칭.
            label = (geoasc or "").strip()
            if "UTM zone 52" in label:
                epsg = EPSG_UTM52N
            elif "UTM zone 51" in label:
                epsg = 32651
            elif "WGS 84" in label and "UTM" not in label:
                epsg = EPSG_WGS84
            else:
                # 보수적으로 UTM52N 가정 (DJI Terra 한국 영역 기본).
                epsg = EPSG_UTM52N

            if epsg == EPSG_WGS84:
                bbox_w = (x0, y1, x1, y0)
            else:
                lon_min, lat_min = utm_to_wgs84(x0, y1, epsg)
                lon_max, lat_max = utm_to_wgs84(x1, y0, epsg)
                bbox_w = (lon_min, lat_min, lon_max, lat_max)

            return GeoTiffMeta(
                width=w, height=h,
                epsg=epsg, epsg_label=label,
                gsd_m=sx,
                bbox_native=(x0, y1, x1, y0),
                bbox_wgs84=bbox_w,
                center_wgs84=((bbox_w[1] + bbox_w[3]) / 2, (bbox_w[0] + bbox_w[2]) / 2),
            )
    finally:
        Image.MAX_IMAGE_PIXELS = prev_limit
