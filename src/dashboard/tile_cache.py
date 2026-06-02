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
