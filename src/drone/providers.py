"""드론 자료 지도 표시 추상화.

TileProvider Protocol + 구현체. Phase 1 은 ImageOverlay 만 지원, Phase 2 에
XYZTileProvider 추가 시 호출처(tab31) 변경 없이 교체 가능.
"""
from __future__ import annotations

import logging
import urllib.parse
from typing import Callable, Optional, Protocol

import folium

from .registry import DroneRegistry, Mission

_logger = logging.getLogger(__name__)

# Mission → 외부에서 접근 가능한 URL 을 만드는 콜백
# (보통 pdf_server.url_for("drone", f"{m.id}/derived/preview.png") 를 wrapping)
UrlFunc = Callable[[Mission], str]


class TileProvider(Protocol):
    """Folium 지도 위에 드론 자료를 그리는 추상.

    구현체 예:
    - ImageOverlayProvider — preview.png 1장을 BBOX 위에 얹기
    - XYZTileProvider      — gdal2tiles 산출물을 TileLayer 로 (Phase 2)
    """
    def add_layer(self, mission_id: str, m_map: folium.Map,
                  *, name: str = "정사사진",
                  opacity: float = 0.85, show: bool = True) -> None: ...

    def get_fit_bounds(self, mission_id: str
                       ) -> Optional[list[list[float]]]: ...


class ImageOverlayProvider:
    """ImageOverlay 기반 — Phase 1 기본 구현.

    Parameters
    ----------
    registry : DroneRegistry
    url_func : Callable[[Mission], str]
        Mission → preview.png 의 절대 URL. 외부(tab31)가 pdf_server.url_for 등을
        wrapping 해 주입. 패키지 자체는 pdf_server 에 의존하지 않음.
    preview_builder : Callable[[Mission], Path | None] | None
        Mission → 디스크상 preview.png 경로 보장 콜백. 보통 src.drone.preview.
        get_or_make_preview. None 이면 미리 생성된 파일이 있다고 가정.
    """

    def __init__(self,
                 registry: DroneRegistry,
                 url_func: UrlFunc,
                 preview_builder: Optional[Callable[[Mission], object]] = None):
        self.registry = registry
        self.url_func = url_func
        self.preview_builder = preview_builder

    def add_layer(self, mission_id: str, m_map: folium.Map,
                  *, name: str = "정사사진",
                  opacity: float = 0.85, show: bool = True) -> None:
        m = self.registry.get(mission_id)
        bbox = m.bbox_wgs84
        if bbox is None:
            _logger.warning("[drone] %s: bbox 없음 — ImageOverlay 생략", mission_id)
            return

        # preview.png 보장 (lazy build)
        if self.preview_builder is not None:
            try:
                self.preview_builder(m)
            except Exception as e:   # noqa: BLE001
                _logger.warning("[drone] preview build failed (%s): %s", mission_id, e)

        url = self.url_func(m)
        # Folium ImageOverlay 는 [[lat_min,lon_min],[lat_max,lon_max]] 순서
        lon_min, lat_min, lon_max, lat_max = bbox
        folium.raster_layers.ImageOverlay(
            image=url,
            bounds=[[lat_min, lon_min], [lat_max, lon_max]],
            name=name,
            opacity=opacity,
            interactive=True,
            cross_origin=False,
            zindex=400,
            show=show,
        ).add_to(m_map)

    def get_fit_bounds(self, mission_id: str
                       ) -> Optional[list[list[float]]]:
        bbox = self.registry.get_bbox(mission_id)
        if bbox is None:
            return None
        lon_min, lat_min, lon_max, lat_max = bbox
        return [[lat_min, lon_min], [lat_max, lon_max]]


def make_drone_url(base_url: str, mission_id: str, rel_path: str) -> str:
    """드론 자료 URL 빌더 — 한글 mission_id 안전 quote.

    예) make_drone_url("http://localhost:8766/pdfs/drone",
                       "2501_구좌종달저수조", "derived/preview.png")
        → "http://localhost:8766/pdfs/drone/2501_%EA%B5%AC%EC%A2%8C%EC%A2%85.../derived/preview.png"

    safe="/" 를 유지해 rel_path 의 슬래시는 인코딩되지 않게.
    """
    quoted_id = urllib.parse.quote(mission_id, safe="")
    quoted_rel = urllib.parse.quote(rel_path.lstrip("/"), safe="/")
    return f"{base_url.rstrip('/')}/{quoted_id}/{quoted_rel}"
