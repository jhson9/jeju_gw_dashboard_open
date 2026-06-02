"""제주 지하수 대시보드 드론 영상 모듈.

DJI Terra 산출물(2D 정사사진·DSM·3D Tiles·PLY)을 등록·조회·표시하는
독립 패키지. 대시보드(tab31)뿐 아니라 외부 스크립트에서도 재사용 가능.

전형적 사용:
    from src.drone import DroneRegistry, ImageOverlayProvider
    reg = DroneRegistry()                 # data_drone/registry.json 자동 로드
    for m in reg.list_missions():
        print(m.id, m.name, reg.get_bbox(m.id))

확장 포인트:
- 신규 미션 등록: data_drone/registry.json 의 missions 배열에 한 항목 추가
  + data_drone/{id}/meta.json 작성. 코드 변경 0건.
- 신규 TileProvider 추가: src/drone/providers.py 에 클래스 추가.

D1 fix 2026-05-30: PEP 562 `__getattr__` lazy re-export 패턴.
  이전: 7개 sub-module 모두 eager import → import src.drone 한 줄로 pyproj/PIL/
       folium/numpy/matplotlib 전부 transitive 로드 (geo.py 의 pyproj 28s 가 가장 큼).
  변경: 24개 심볼을 _LAZY dict 에 (심볼→sub-module) 매핑, 실제 접근 시 importlib.
       drone 안 보는 사용자(외부 스크립트, 단위 테스트)는 pyproj/PIL 회피.
  안전성: `__all__` 유지 (정적 도구·IDE 호환), `__dir__()` 추가 (tab completion),
       `from __future__ import annotations` 가 호출처에 있어 타입 힌트는 string lazy.
       `from src.drone import *` 0건, `isinstance(x, Mission|...)` 0건 (전수 grep 검증).
"""
from __future__ import annotations

import importlib

# 심볼 → sub-module 매핑. 동일 모듈에 여러 심볼은 같은 모듈명 반복.
_LAZY: dict[str, str] = {
    # registry.py — json/dataclass/config 만 (가벼움)
    "DroneRegistry": "registry",
    "Mission": "registry",
    "MissionNotFound": "registry",
    # providers.py — folium top-level
    "TileProvider": "providers",
    "ImageOverlayProvider": "providers",
    # geo.py — **pyproj 의존 (28s, lazy 효과 최대)**
    "extract_geotiff_bbox": "geo",
    "ecef_to_wgs84": "geo",
    "wgs84_to_ecef": "geo",
    "geodesic_distance_m": "geo",
    # preview.py — PIL/numpy/matplotlib 모두 함수 내 lazy
    "get_or_make_preview": "preview",
    "get_or_make_dsm_heatmap": "preview",
    "load_dsm_meta": "preview",
    "dsm_heatmap_path": "preview",
    # elevation.py — geo 재사용 (pyproj 연쇄)
    "DsmSampler": "elevation",
    "ElevationResult": "elevation",
    # measure.py — geo 재사용
    "DistanceResult": "measure",
    "horizontal_distance_m": "measure",
    "segment_distance": "measure",
    "polyline_distance": "measure",
    "polygon_area_m2": "measure",
    "slope_deg": "measure",
    # diff.py — numpy/rasterio 함수 내 lazy
    "MissionPair": "diff",
    "DsmDiffAnalyzer": "diff",
    "DsmDiffResult": "diff",
}

__all__ = sorted(_LAZY.keys())

__version__ = "0.1.0"


def __getattr__(name: str):
    """PEP 562 — module-level __getattr__. 정의되지 않은 심볼 접근 시 호출.

    _LAZY 에 매핑된 심볼은 해당 sub-module 을 lazy import 후 반환.
    매핑 외 심볼은 AttributeError raise → 표준 Python 동작 (typo 등 정상 검출).
    """
    if name in _LAZY:
        mod = importlib.import_module(f".{_LAZY[name]}", __name__)
        attr = getattr(mod, name)
        # 한 번 resolve 후 module-level 에 캐시 → 두 번째 접근부터 __getattr__ 우회.
        globals()[name] = attr
        return attr
    raise AttributeError(f"module 'src.drone' has no attribute {name!r}")


def __dir__() -> list[str]:
    """IDE/tab-completion 지원 — __all__ + 모듈 자체 심볼."""
    return sorted(set(__all__) | set(globals().keys()))
