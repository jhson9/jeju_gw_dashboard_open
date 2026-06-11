# ==============================================================================
#  파일명: src/dashboard/tile_cache.py
#  V-World 지도 타일 사전 다운로드 — 제주도 bbox × zoom 범위 일괄 캐시.
# ------------------------------------------------------------------------------
#  배경: V-World CDN 에서 매 진입마다 타일 fetch → 첫 페인트 느림 + 흰 깜박임.
#  해결: 제주도 bbox + 자주 쓰는 줌 범위(10~14) 의 타일을 미리 디스크에 받아 두고
#       streamlit 정적 서빙 (.streamlit/config.toml enableStaticServing=true) 로
#       /app/static/map_tiles/{Layer}/{z}/{x}/{y}.{ext} URL 노출.
#
#  외부 호출:
#    - tab99_admin.py 의 "지도 타일 캐시" 섹션 ("지도 오프라인 저장" 버튼)
#    - docs/step2_download_tiles.py (배치 사전 다운로드)
# ==============================================================================
from __future__ import annotations

import math
import os
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable

# bbox: 제주도 본섬 + 마라/우도/추자 포함
LAT_MIN, LAT_MAX = 33.10, 33.60
LON_MIN, LON_MAX = 126.10, 127.00

# 사용자 합의 (2026-05-14): zoom 10~14 까지 캐시.
# 14 가 1218장으로 가장 많지만 사용자가 가끔 확대 시 즉시 표시 위해 포함.
# 15+ 는 max_native_zoom=14 로 14의 타일을 확대 표시 (블러).
DEFAULT_ZOOM_RANGE = [10, 11, 12, 13, 14]

# 1GB 재발 방지 hard cap (2026-05-15, 오류분석 2팀 권장):
# zoom 15 부터는 타일 수가 기하급수적으로 증가 (z=15 약 5000장, z=16 약 2만장).
# 16 만 추가해도 ~340 MB 증가 → src/dashboard/static/ 가 streamlit 1GB hard
# limit 에 빠르게 근접. 사용자가 tab4 UI 에서 임의로 zoom 을 늘릴 수 없도록
# download_jeju_tiles() 가 진입 시 검증.
MAX_CACHED_ZOOM = 14

# streamlit 정적 서빙 디렉토리 = main script (app.py) 부모 / static
PROJECT_ROOT = Path(__file__).resolve().parents[2]
TILE_ROOT = PROJECT_ROOT / "src" / "dashboard" / "static" / "map_tiles"

LAYERS = [
    {"name": "Base",      "ext": "png"},
    {"name": "Satellite", "ext": "jpeg"},
]

RATE_DELAY = 0.25   # 초당 4 요청 — V-World rate limit 안전선
RETRY_MAX = 3
TIMEOUT = 20


# ==============================================================================
#  ■ 지도 엔진(Leaflet 라이브러리) 오프라인 캐시 (2026-06-08)
# ------------------------------------------------------------------------------
#  배경: 타일(이미지)은 위 map_tiles 로 로컬화돼 있으나, 그 타일을 '그리는'
#       Leaflet.js/CSS 등 라이브러리는 folium 이 매번 외부 CDN 에서 불러온다.
#       → 인터넷이 없으면 지도 엔진 자체가 로드되지 않아 ④⑪⑫⑬ 지도가 빈 화면.
#  해결: folium 0.20.0 이 참조하는 CDN 자원 전부를 로컬에 저장하고
#       (/app/static/libs/leaflet_offline/...), map_helpers 가 CDN 대신 이
#       로컬 경로를 보도록 교체 → 타일+엔진 모두 로컬 = 완전 오프라인 지도.
#
#  "name" 은 folium 의 default_js/default_css 항목 이름과 정확히 일치시켜
#  map_helpers 가 이름 기준으로 URL 을 치환할 수 있게 한다.
# ==============================================================================
LIBS_ROOT = PROJECT_ROOT / "src" / "dashboard" / "static" / "libs" / "leaflet_offline"

# folium 0.20.0 이 CDN 에서 불러오는 자원. (실측: map_helpers.make_map 렌더 결과)
#   critical=True 3종(leaflet.js/css, leaflet-dvf)이 없으면 지도가 아예 안 뜸.
#   나머지는 LayerControl/popup 스타일 등 보조 — 없어도 지도는 뜨나 함께 받아 둠.
MAP_LIB_ASSETS = [
    {"name": "leaflet",      "filename": "leaflet.js",
     "url": "https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.js", "critical": True},
    {"name": "leaflet_css",  "filename": "leaflet.css",
     "url": "https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/leaflet.css", "critical": True},
    {"name": "dvf_js",       "filename": "leaflet-dvf.markers.min.js",
     "url": "https://cdnjs.cloudflare.com/ajax/libs/leaflet-dvf/0.3.0/leaflet-dvf.markers.min.js", "critical": True},
    {"name": "jquery",       "filename": "jquery.min.js",
     "url": "https://code.jquery.com/jquery-3.7.1.min.js", "critical": False},
    {"name": "bootstrap",    "filename": "bootstrap.bundle.min.js",
     "url": "https://cdn.jsdelivr.net/npm/bootstrap@5.2.2/dist/js/bootstrap.bundle.min.js", "critical": False},
    {"name": "bootstrap_css", "filename": "bootstrap.min.css",
     "url": "https://cdn.jsdelivr.net/npm/bootstrap@5.2.2/dist/css/bootstrap.min.css", "critical": False},
    {"name": "glyphicons_css", "filename": "bootstrap-glyphicons.css",
     "url": "https://netdna.bootstrapcdn.com/bootstrap/3.0.0/css/bootstrap-glyphicons.css", "critical": False},
    {"name": "awesome_markers_font_css", "filename": "fontawesome-all.min.css",
     "url": "https://cdn.jsdelivr.net/npm/@fortawesome/fontawesome-free@6.2.0/css/all.min.css", "critical": False},
    {"name": "awesome_markers", "filename": "leaflet.awesome-markers.js",
     "url": "https://cdnjs.cloudflare.com/ajax/libs/Leaflet.awesome-markers/2.0.2/leaflet.awesome-markers.js", "critical": False},
    {"name": "awesome_markers_css", "filename": "leaflet.awesome-markers.css",
     "url": "https://cdnjs.cloudflare.com/ajax/libs/Leaflet.awesome-markers/2.0.2/leaflet.awesome-markers.css", "critical": False},
    {"name": "awesome_rotate_css", "filename": "leaflet.awesome.rotate.min.css",
     "url": "https://cdn.jsdelivr.net/gh/python-visualization/folium/folium/templates/leaflet.awesome.rotate.min.css", "critical": False},
]

# leaflet.css 가 상대경로(images/...)로 참조하는 부속 이미지.
#   leaflet.css 와 같은 폴더의 images/ 하위에 두면 상대경로가 그대로 해소됨.
#   (LayerControl 의 레이어 토글 아이콘 등. 없으면 아이콘만 깨지고 지도는 정상)
MAP_LIB_IMAGES = [
    "https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/images/layers.png",
    "https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/images/layers-2x.png",
    "https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/images/marker-icon.png",
    "https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/images/marker-icon-2x.png",
    "https://cdn.jsdelivr.net/npm/leaflet@1.9.3/dist/images/marker-shadow.png",
]


def _lon_to_xtile(lon: float, z: int) -> int:
    return int((lon + 180.0) / 360.0 * (1 << z))


def _lat_to_ytile(lat: float, z: int) -> int:
    return int((1.0 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2.0 * (1 << z))


def estimate_tiles(zoom_range: list[int] | None = None) -> dict:
    """캐시 대상 타일 수와 예상 디스크 크기 계산. 다운로드 안 함."""
    zr = zoom_range or DEFAULT_ZOOM_RANGE
    total = 0
    per_zoom: list[tuple[int, int]] = []
    for z in zr:
        x_min = _lon_to_xtile(LON_MIN, z)
        x_max = _lon_to_xtile(LON_MAX, z)
        y_min = _lat_to_ytile(LAT_MAX, z)
        y_max = _lat_to_ytile(LAT_MIN, z)
        n = (x_max - x_min + 1) * (y_max - y_min + 1)
        per_zoom.append((z, n))
        total += n
    # Base(PNG, ~17.8KB) + Satellite(JPEG, ~15.0KB) ≈ 32.8 KB/장 평균
    est_bytes = total * len(LAYERS) * 16 * 1024
    return {
        "per_zoom": per_zoom,
        "total_per_layer": total,
        "total_all_layers": total * len(LAYERS),
        "est_disk_bytes": est_bytes,
    }


def _download_one(url: str, dst: Path) -> int:
    """단일 타일 다운로드. 반환: bytes (성공) 또는 -1 (실패)."""
    req = urllib.request.Request(
        url, headers={"User-Agent": "jeju-dashboard-tile-cache/1.0"}
    )
    for attempt in range(RETRY_MAX):
        try:
            with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
                data = resp.read()
            if len(data) < 100:
                # V-World 가 가끔 빈 응답을 200 으로 보냄
                return -1
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(data)
            return len(data)
        except urllib.error.HTTPError as e:
            if e.code in (429, 503):
                time.sleep(2.0 + attempt)
                continue
            return -1
        except (urllib.error.URLError, TimeoutError, OSError):
            time.sleep(1.0 + attempt)
            continue
    return -1


def download_jeju_tiles(
    zoom_range: list[int] | None = None,
    progress_cb: Callable[[dict], None] | None = None,
    force: bool = False,
) -> dict:
    """V-World 타일 사전 다운로드.

    Parameters
    ----------
    zoom_range : list[int] | None
        다운로드할 줌 레벨 목록. None 이면 DEFAULT_ZOOM_RANGE (10~14).
    progress_cb : Callable[[dict], None] | None
        매 타일 처리마다 호출되는 콜백. dict 인자:
          - "layer": "Base"/"Satellite"
          - "z", "x", "y"
          - "done_total": 지금까지 처리한 누적 (성공+skip+실패)
          - "target_total": 전체 처리 대상
          - "new", "skipped", "failed": 각 카운트
    force : bool
        True 면 이미 존재하는 파일도 다시 다운로드.

    Returns
    -------
    dict — 최종 결과 ({"new", "skipped", "failed", "bytes", "elapsed_sec",
                        "failure_list"})
    """
    zr = zoom_range or DEFAULT_ZOOM_RANGE

    # 1GB 재발 방지 — zoom 15+ 는 거부 (사용자 호출이든 UI 호출이든)
    over = [z for z in zr if z > MAX_CACHED_ZOOM]
    if over:
        return {
            "new": 0, "skipped": 0, "failed": 0, "bytes": 0,
            "elapsed_sec": 0.0, "failure_list": [],
            "error": (
                f"zoom {over} 는 캐시 한도(MAX_CACHED_ZOOM={MAX_CACHED_ZOOM}) 를 "
                f"초과합니다. zoom 15+ 는 streamlit static folder 의 1GB 한도를 "
                f"빠르게 소진해 모든 정적 서빙이 비활성화됩니다. "
                f"더 깊은 확대가 필요하면 pdf_server 패턴으로 별도 서빙하세요."
            ),
        }

    key = os.getenv("VWORLD_API_KEY", "").strip()
    if not key:
        return {
            "new": 0, "skipped": 0, "failed": 0, "bytes": 0,
            "elapsed_sec": 0.0, "failure_list": [],
            "error": "VWORLD_API_KEY 환경변수 누락 (.env 확인)",
        }

    # 대상 타일 총 개수
    target = 0
    for z in zr:
        x_min = _lon_to_xtile(LON_MIN, z)
        x_max = _lon_to_xtile(LON_MAX, z)
        y_min = _lat_to_ytile(LAT_MAX, z)
        y_max = _lat_to_ytile(LAT_MIN, z)
        target += (x_max - x_min + 1) * (y_max - y_min + 1)
    target *= len(LAYERS)

    new_count = 0
    skipped = 0
    failed = 0
    total_bytes = 0
    failures: list[tuple[str, int, int, int]] = []
    t_start = time.time()
    done = 0

    for layer in LAYERS:
        name, ext = layer["name"], layer["ext"]
        for z in zr:
            x_min = _lon_to_xtile(LON_MIN, z)
            x_max = _lon_to_xtile(LON_MAX, z)
            y_min = _lat_to_ytile(LAT_MAX, z)
            y_max = _lat_to_ytile(LAT_MIN, z)
            for x in range(x_min, x_max + 1):
                for y in range(y_min, y_max + 1):
                    dst = TILE_ROOT / name / str(z) / str(x) / f"{y}.{ext}"
                    if not force and dst.exists() and dst.stat().st_size > 100:
                        skipped += 1
                        done += 1
                    else:
                        url = (
                            f"https://api.vworld.kr/req/wmts/1.0.0/"
                            f"{key}/{name}/{z}/{y}/{x}.{ext}"
                        )
                        size = _download_one(url, dst)
                        if size > 0:
                            new_count += 1
                            total_bytes += size
                        else:
                            failed += 1
                            failures.append((name, z, x, y))
                        done += 1
                        time.sleep(RATE_DELAY)
                    if progress_cb is not None:
                        progress_cb({
                            "layer": name, "z": z, "x": x, "y": y,
                            "done_total": done, "target_total": target,
                            "new": new_count, "skipped": skipped, "failed": failed,
                        })

    return {
        "new": new_count,
        "skipped": skipped,
        "failed": failed,
        "bytes": total_bytes,
        "elapsed_sec": time.time() - t_start,
        "failure_list": failures,
    }


def current_cache_summary() -> dict:
    """현재 디스크에 저장된 타일 통계 — UI 에서 "현재 캐시" 표시용."""
    if not TILE_ROOT.exists():
        return {"layers": {}, "total_files": 0, "total_bytes": 0}

    layers: dict[str, dict] = {}
    total_files = 0
    total_bytes = 0
    for layer in LAYERS:
        name = layer["name"]
        layer_dir = TILE_ROOT / name
        if not layer_dir.exists():
            layers[name] = {"files": 0, "bytes": 0}
            continue
        files = 0
        bytes_sum = 0
        for p in layer_dir.rglob("*"):
            if p.is_file():
                files += 1
                bytes_sum += p.stat().st_size
        layers[name] = {"files": files, "bytes": bytes_sum}
        total_files += files
        total_bytes += bytes_sum
    return {
        "layers": layers,
        "total_files": total_files,
        "total_bytes": total_bytes,
    }


# ==============================================================================
#  ■ 지도 엔진(Leaflet 라이브러리) 다운로드 / 상태
# ==============================================================================
def download_map_libs(
    progress_cb: Callable[[dict], None] | None = None,
    force: bool = False,
) -> dict:
    """folium 이 CDN 에서 불러오는 Leaflet 라이브러리 자원을 로컬에 저장.

    타일(이미지)과 별개의 '지도 엔진' 부분. 인터넷이 연결된 상태에서 한 번
    받아 두면 이후 오프라인에서도 ④⑪⑫⑬ 지도가 정상 표시된다. 공개 CDN
    이라 VWORLD_API_KEY 불필요.

    progress_cb dict: {"done_total", "target_total", "new", "skipped",
                       "failed", "name"}
    """
    LIBS_ROOT.mkdir(parents=True, exist_ok=True)
    (LIBS_ROOT / "images").mkdir(parents=True, exist_ok=True)

    items: list[tuple[str, str]] = [
        (a["filename"], a["url"]) for a in MAP_LIB_ASSETS
    ]
    items += [
        (f"images/{u.rsplit('/', 1)[1]}", u) for u in MAP_LIB_IMAGES
    ]

    target = len(items)
    new_count = skipped = failed = 0
    total_bytes = 0
    failures: list[tuple[str, str]] = []
    t_start = time.time()

    for i, (fname, url) in enumerate(items, start=1):
        dst = LIBS_ROOT / fname
        if not force and dst.exists() and dst.stat().st_size > 100:
            skipped += 1
        else:
            size = _download_one(url, dst)
            if size > 0:
                new_count += 1
                total_bytes += size
            else:
                failed += 1
                failures.append((fname, url))
            time.sleep(RATE_DELAY)
        if progress_cb is not None:
            progress_cb({
                "done_total": i, "target_total": target,
                "new": new_count, "skipped": skipped, "failed": failed,
                "name": fname,
            })

    return {
        "new": new_count,
        "skipped": skipped,
        "failed": failed,
        "bytes": total_bytes,
        "elapsed_sec": time.time() - t_start,
        "failure_list": failures,
    }


def map_libs_ready() -> bool:
    """오프라인 지도 엔진 준비 여부 — critical 3종이 모두 정상 저장됐는지.

    map_helpers 가 이 값을 보고 CDN/로컬 중 무엇을 쓸지 결정한다.
    """
    for a in MAP_LIB_ASSETS:
        if not a.get("critical"):
            continue
        p = LIBS_ROOT / a["filename"]
        if not (p.exists() and p.stat().st_size > 100):
            return False
    return True


def current_libs_summary() -> dict:
    """현재 로컬에 저장된 지도 엔진 자원 통계 — UI 표시용."""
    files = 0
    total_bytes = 0
    if LIBS_ROOT.exists():
        for p in LIBS_ROOT.rglob("*"):
            if p.is_file():
                files += 1
                total_bytes += p.stat().st_size
    return {
        "files": files,
        "bytes": total_bytes,
        "ready": map_libs_ready(),
        "n_assets": len(MAP_LIB_ASSETS) + len(MAP_LIB_IMAGES),
    }
