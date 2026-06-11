"""DSM 표고(EL) 조회.

지도 클릭(WGS84 lat/lon) → DSM 픽셀 인덱스 → 표고값(m) 반환.
PIL 의 lazy decode 를 이용해 큰 GeoTIFF 도 첫 호출 시에만 헤더 로드.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from .geo import _get_transformer, EPSG_WGS84, EPSG_UTM52N
from .registry import Mission

_logger = logging.getLogger(__name__)


# DSM NoData 후보값 (DJI Terra 가 사용하는 sentinel 값들)
_NODATA_THRESHOLDS = (-1e30, -9999.0, -10000.0)


def _is_nodata(value: float) -> bool:
    if value is None:
        return True
    if math.isnan(value) or math.isinf(value):
        return True
    if value <= -1000.0:   # 한국 해발 -1000m 이하는 정상값일 수 없음
        return True
    return False


@dataclass
class ElevationResult:
    el_m: float           # 해발고도 (m)
    lat: float
    lon: float
    pixel_xy: tuple[int, int]


class DsmSampler:
    """미션 1개의 DSM TIFF 에 대한 표고 조회기.

    Streamlit 에서 `@st.cache_resource` 로 미션 단위 캐싱 권장:
        @st.cache_resource(show_spinner=False)
        def get_sampler(mission_id: str) -> DsmSampler | None:
            m = reg.get(mission_id)
            return DsmSampler.from_mission(m)
    """

    def __init__(self,
                 dsm_path: Path,
                 epsg: int,
                 origin_xy: tuple[float, float],   # 좌상단 (easting, northing)
                 pixel_size_m: tuple[float, float],
                 size_px: tuple[int, int]):
        self.dsm_path = dsm_path
        self.epsg = epsg
        self.origin_x, self.origin_y = origin_xy
        self.px_w, self.px_h = pixel_size_m
        self.width, self.height = size_px
        self._img = None   # lazy

    @classmethod
    def from_mission(cls, mission: Mission) -> Optional["DsmSampler"]:
        """meta.json 기반으로 미션에서 sampler 생성. 실패 시 None."""
        dsm_path = mission.output_path("dsm")
        if not dsm_path or not dsm_path.exists():
            return None

        # DSM 의 EPSG·GeoTransform 을 PIL TIFF tag 로 직접 읽기 — meta.json
        # 에 cache 된 값보다 raw 헤더가 권위적 (혹시 사용자가 새 미션 추가하면
        # meta.json 없이도 동작).
        from PIL import Image
        prev_limit = Image.MAX_IMAGE_PIXELS
        Image.MAX_IMAGE_PIXELS = None
        try:
            img = Image.open(dsm_path)
            tags = img.tag_v2
            w, h = img.size
            tie = tags.get(33922)
            scl = tags.get(33550)
            geoasc = tags.get(34737, "")
            if not (tie and scl):
                _logger.warning("DSM 에 geo tag 없음: %s", dsm_path)
                img.close()
                return None
            origin = (float(tie[3]), float(tie[4]))
            px_size = (float(scl[0]), float(scl[1]))
            label = (geoasc or "").strip()
            epsg = EPSG_UTM52N if "UTM zone 52" in label else EPSG_UTM52N
            instance = cls(dsm_path=dsm_path, epsg=epsg, origin_xy=origin,
                           pixel_size_m=px_size, size_px=(w, h))
            instance._img = img   # 열어둠 — lazy decode 유지
            return instance
        finally:
            Image.MAX_IMAGE_PIXELS = prev_limit

    def close(self) -> None:
        if self._img is not None:
            try:
                self._img.close()
            except Exception:   # noqa: BLE001
                pass
            self._img = None

    def sample(self, lat: float, lon: float) -> Optional[ElevationResult]:
        """WGS84 (lat, lon) 의 표고. BBOX 밖이거나 NoData 면 None."""
        # WGS84 → UTM52N
        tfm = _get_transformer(EPSG_WGS84, self.epsg)
        x, y = tfm.transform(lon, lat)
        # UTM → 픽셀 인덱스 (좌상단 기준, y 축 음수 방향)
        col = int(math.floor((x - self.origin_x) / self.px_w))
        row = int(math.floor((self.origin_y - y) / self.px_h))
        if not (0 <= col < self.width and 0 <= row < self.height):
            return None

        if self._img is None:
            # close() 후 다시 호출되면 재open
            from PIL import Image
            Image.MAX_IMAGE_PIXELS = None
            self._img = Image.open(self.dsm_path)

        try:
            value = self._img.getpixel((col, row))
        except Exception as e:   # noqa: BLE001
            _logger.warning("DSM getpixel 실패 (%d,%d): %s", col, row, e)
            return None

        # mode='F' 는 float, getpixel 이 단일 float 반환. RGB tile 이면 tuple.
        if isinstance(value, (tuple, list)):
            value = value[0]
        value = float(value)
        if _is_nodata(value):
            return None
        return ElevationResult(el_m=value, lat=lat, lon=lon, pixel_xy=(col, row))
