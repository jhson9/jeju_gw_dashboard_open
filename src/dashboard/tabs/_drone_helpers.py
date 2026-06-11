# ==============================================================================
#  파일명: src/dashboard/tabs/_drone_helpers.py
#  모듈: 드론 영상 탭 (31~34) 공용 헬퍼
# ------------------------------------------------------------------------------
#  2026-05-23 tab31 분할 시 추출 — tab31_drone_overview, tab32_drone_2d,
#  tab33_drone_3d, tab34_drone_diff 4개 탭이 공유.
#
#  의존:
#    - src.drone (DroneRegistry, ImageOverlayProvider, preview)
#    - src.dashboard.pdf_server (드론 자료 정적 서빙 :8766)
#    - src.dashboard.theme (디자인 토큰 — _site_color 폴백)
# ==============================================================================
from __future__ import annotations

import math
import time as _time
import urllib.parse
from pathlib import Path

import streamlit as st

# 모듈 import 시점에 1회 평가 — Streamlit 같은 세션 안에선 동일 값(불필요한 reload
# 방지), 재시작 후엔 새 값. tab33/tab34 의 iframe URL cache-buster 로 사용.
_CACHE_BUSTER = int(_time.time())

import config
from src.dashboard import pdf_server, theme

# 🛡️ (2026-06-11 검증팀 D1) V-World 로컬 타일 host 기본값 — 하드코딩 8501 이
# 실제 서버 포트(config.STREAMLIT_PORT=18501)와 달라 tab34/35 비교뷰어의
# 배경지도 타일 요청이 전부 실패했음. config 동적 참조로 일원화 (SSOT).
_HOST_STREAMLIT = f"http://127.0.0.1:{config.STREAMLIT_PORT}"
from src.drone import (
    DroneRegistry,
    DsmSampler,
    ImageOverlayProvider,
)
from src.drone.preview import get_or_make_preview, preview_path
from src.drone.providers import make_drone_url
from src.drone.registry import Mission

# 정사영상 preview.png 의 HD 해상도 — 2026-05-23 사용자 요청.
# 시설물 관리 목적상 균열·이동·노후 감지가 가능한 해상도 필요. 데스크탑 + GPU 환경 전제
# 라 메모리 부담 수용 가능. preview.py 의 default 2048 은 변경 안 함 (다른 잠재 호출처 격리).
DRONE_PREVIEW_HD_MAX_SIDE = 8192

# CesiumJS 로컬 번들 — 사용자가 별도 다운로드 후 배치 필요 (오프라인 운영).
# tab33_drone_3d 에서 사용.
CESIUM_BUNDLE_DIR = Path(__file__).resolve().parents[1] / "static" / "libs" / "cesium"
CESIUM_JS = CESIUM_BUNDLE_DIR / "Cesium.js"


# ──────────────────────────────────────────────────────────────────
#  레지스트리·프로바이더 (캐시)
# ──────────────────────────────────────────────────────────────────
@st.cache_resource(show_spinner=False)
def get_registry() -> DroneRegistry:
    return DroneRegistry()


@st.cache_resource(show_spinner=False)
def get_sampler(mission_id: str):
    """미션의 DSM 표고 조회기 (DsmSampler) — 미션 단위 캐싱.

    tab32/33 의 좌표·거리 측정 도구가 클릭 지점의 표고(해발 m)를 얻는 데 사용.
    DSM 이 없거나 geo tag 가 없는 미션은 None 반환 → 호출부는 "표고 없음" 처리.
    elevation.py 의 권장 캐싱 패턴 구현체.
    """
    reg = get_registry()
    try:
        m = reg.get(mission_id)
    except Exception:   # noqa: BLE001  (MissionNotFound 포함)
        return None
    return DsmSampler.from_mission(m)


# ──────────────────────────────────────────────────────────────────
#  M1 fix 2026-05-30: check_mission_bbox 캐시 wrapper
#
#  Tab31 진입 시 모든 미션의 result.tif (90MB ~ 1.1GB) 를 rasterio 로 open →
#  bounds + transform_bounds 산출. 매 fragment_rerun 마다 반복하면 수백 ms ~ 수 초.
#  result.tif 의 (mtime_ns, size) 를 캐시 key 에 포함해 사용자가 importer 로
#  메타 수정 시 자동 갱신, 그 외에는 1시간 동안 메모리에서 즉시 반환.
#
#  본체(meta_validator.check_mission_bbox)는 streamlit context 없는 pytest 환경에서
#  호출되므로 데코레이터를 본체에 달면 안 됨 — wrapper 패턴 필수.
# ──────────────────────────────────────────────────────────────────
def _result_tif_signature(mission_dir):
    """캐시 key 용 (mtime_ns, size) 시그니처. 파일 없으면 (0, 0)."""
    try:
        from pathlib import Path
        p = Path(mission_dir) / "result.tif"
        if not p.exists():
            return (0, 0)
        s = p.stat()
        return (s.st_mtime_ns, s.st_size)
    except Exception:  # noqa: BLE001
        return (0, 0)


@st.cache_data(ttl=3600, show_spinner=False, max_entries=64)
def _check_mission_bbox_cached(mission_dir_str: str, sig: tuple):
    """Tab31 전용 캐시 wrapper. sig 가 변하면 자동 무효화 (사용자가 importer
    실행해서 result.tif 가 갱신된 경우).

    🛡️ (2026-06-11 검증팀 D4) 인자명 `_sig` → `sig` — Streamlit 은 `_` 접두
    인자를 캐시 키 해시에서 제외하므로, 기존 `_sig` 는 자동 무효화가 전혀
    동작하지 않았음 (result.tif 갱신 후에도 TTL 1시간 동안 옛 결과 반환).
    """
    from src.drone.meta_validator import check_mission_bbox
    return check_mission_bbox(mission_dir_str)


def check_mission_bbox_fast(mission_dir):
    """Tab31 호출용 외부 인터페이스. 시그니처 → wrapper 호출."""
    return _check_mission_bbox_cached(str(mission_dir), _result_tif_signature(mission_dir))


# ──────────────────────────────────────────────────────────────────
#  [공개판] Streamlit Cloud 환경 감지 + 데이터 URI 이미지 헬퍼
#  - Cloud 에는 pdf_server(:8766) 가 없으므로 URL 대신 repo 에 포함된
#    다운샘플 preview.png 를 base64 데이터 URI 로 직접 임베드한다.
#  - GitHub raw URL 방식(이전 공개판 V1.2.7)과 달리 repo 이름에 의존하지
#    않고 LFS bandwidth 도 전혀 쓰지 않는다.
# ──────────────────────────────────────────────────────────────────
def is_cloud_env() -> bool:
    """Streamlit Community Cloud 실행 여부 감지."""
    import os
    if Path("/mount/src").exists():
        return True
    if os.environ.get("STREAMLIT_RUNTIME_ENV", "").lower() == "cloud":
        return True
    hostname = (os.environ.get("HOSTNAME") or "").lower()
    if "streamlit" in hostname:
        return True
    home = os.environ.get("HOME", "")
    if home in ("/home/appuser", "/home/adminuser") and Path("/mount").exists():
        return True
    return False


_DRONE_STATIC_DIR = Path(__file__).resolve().parents[1] / "static" / "drone"


def _mission_slug(m: Mission) -> str:
    """미션 id 의 ASCII 부분만 추출 (Cloud static 한글 경로 사고 회피).

    예: "2505_구좌덕천저수조" → "2505". 충돌 시 전체 id 폴백.
    """
    slug = "".join(ch for ch in m.id if ch.isascii() and (ch.isalnum() or ch in "-_"))
    return slug.strip("_-") or m.id


def preview_static_url(m: Mission) -> str | None:
    """repo 동봉 static 사본(/app/static/drone/<slug>/preview.png) URL.

    Streamlit enableStaticServing 이 메인 스크립트 옆 static/ 을 서빙하므로
    data URI(수 MB) 대신 가벼운 URL 로 ImageOverlay 가능. 파일 없으면 None.
    """
    slug = _mission_slug(m)
    f = _DRONE_STATIC_DIR / slug / "preview.png"
    if not f.exists():
        return None
    # [V2.1.1] folium 의 image_to_url 은 scheme 없는 "/app/..." 문자열을
    # 로컬 파일 경로로 오인해 서버에서 open() → Cloud 에서 PermissionError.
    # → Host 헤더로 절대 https URL 을 만들어 전달 (folium 이 URL 로 인식).
    #   브라우저에선 Cloud 의 service worker 가 /~/+/ 프록시로 변환해 서빙.
    try:
        host = (st.context.headers.get("Host")
                or st.context.headers.get("host") or "").strip()
    except Exception:
        host = ""
    if host:
        return f"https://{host}/app/static/drone/{slug}/preview.png"
    return None


@st.cache_data(show_spinner=False, max_entries=8)
def _png_data_uri(path_str: str, mtime: float) -> str:
    """로컬 PNG → data URI (브라우저 직접 임베드). mtime 은 캐시 무효화 키."""
    import base64
    data = Path(path_str).read_bytes()
    return "data:image/png;base64," + base64.b64encode(data).decode("ascii")


def preview_data_uri(m: Mission) -> str | None:
    """미션 preview.png 의 data URI. 파일 없으면 None."""
    pp = preview_path(m)
    if not pp.exists():
        return None
    return _png_data_uri(str(pp), pp.stat().st_mtime)


def drone_url_base() -> str:
    """pdf_server :8766 의 drone 화이트리스트 URL base."""
    src = pdf_server.DATA_SOURCES.get("drone")
    if src is None:
        return ""
    return f"{pdf_server.PDF_SERVER_URL_BASE}{src.url_prefix}".rstrip("/")


def cesium_lib_url_base() -> str:
    """pdf_server :8766 의 cesium_lib 화이트리스트 URL base.

    Streamlit static (/app/static/) 이 .js/.css 를 강제로 text/plain 으로
    응답하여 CesiumJS 가 로드 안 되는 문제를 우회. pdf_server 는 우리가
    직접 만든 핸들러라 .js → application/javascript 정확히 응답함.
    """
    src = pdf_server.DATA_SOURCES.get("cesium_lib")
    if src is None:
        return ""
    return f"{pdf_server.PDF_SERVER_URL_BASE}{src.url_prefix}".rstrip("/")


def url_for_diff_viewer(left: Mission, right: Mission,
                        *, vworld_key: str = "",
                        host_8501: str = _HOST_STREAMLIT) -> str:
    """tab34 시계열 비교 — 좌·우 분할 동기화 뷰어 URL.

    구조: `…/diff_viewer.html?l=<l_id>&r=<r_id>#left_img=…&left_bounds=…&…`
      - query (`?l=…&r=…`): 미션 ID — Streamlit 이 src 차이로 iframe 재생성
      - hash (`#…`): 정사영상 URL, BBOX, 라벨, V-World 키, host 정보
        (pdf_server 에는 전송 안 되므로 strict URL 검사·DENY 토큰 무관)

    Mission.bbox_wgs84 = (lon_min, lat_min, lon_max, lat_max).
    Leaflet bounds 는 [[lat_min, lon_min], [lat_max, lon_max]] 형식 →
    여기선 hash 에 평탄화해서 "lat_min,lon_min,lat_max,lon_max" 로 전달.

    Args:
        left, right: 좌·우에 표시할 미션 (시뮬레이션 시 같은 객체 OK)
        vworld_key:  config.VWORLD_API_KEY (V-World API HD 타일용, 빈 문자열 OK)
        host_8501:   Streamlit static 의 V-World 로컬 캐시 URL base
                     (브라우저가 cross-origin image 로 fetch — CORS 무관)
    """
    src = pdf_server.DATA_SOURCES.get("drone_viewer")
    if src is None:
        return ""
    base = f"{pdf_server.PDF_SERVER_URL_BASE}{src.url_prefix}diff_viewer.html"

    def bounds_str(m: Mission) -> str:
        bb = m.bbox_wgs84   # [lon_min, lat_min, lon_max, lat_max]
        if bb is None:
            # bbox 없으면 center ± 0.005° 로 폴백
            c = m.center_wgs84
            if c is None:
                raise ValueError(f"Mission {m.id}: bbox_wgs84 와 center_wgs84 모두 없음")
            lat, lon = c[0], c[1]
            return f"{lat-0.005},{lon-0.005},{lat+0.005},{lon+0.005}"
        # Leaflet 순서: lat_min, lon_min, lat_max, lon_max
        return f"{bb[1]},{bb[0]},{bb[3]},{bb[2]}"

    # cache-buster — Streamlit import-time 의 module load 마다 새 timestamp.
    # diff_viewer.html 코드 업데이트 후 사용자가 본 게 이전 캐시 HTML 이라
    # 새 TileLayer 코드가 안 보이는 문제 우회. import 시점 1회 평가라 같은
    # 세션 안에선 동일 (불필요 reload 방지), 재시작 후엔 다른 값.
    qs = urllib.parse.urlencode({"l": left.id, "r": right.id, "_v": _CACHE_BUSTER})
    frag = urllib.parse.urlencode({
        "left_img":      url_for_preview(left),
        "left_tiles":    tile_url_template_for(left),    # XYZ 슬리피맵 (zoom 12~23)
        "left_bounds":   bounds_str(left),
        "left_label":    f"{left.name} · {left.flight_date}",
        "right_img":     url_for_preview(right),
        "right_tiles":   tile_url_template_for(right),
        "right_bounds":  bounds_str(right),
        "right_label":   f"{right.name} · {right.flight_date}",
        "vworld_key":    vworld_key,
        "host_8501":     host_8501,
    })
    return f"{base}?{qs}#{frag}"


def url_for_diff_viewer_dod(left: Mission, right: Mission,
                            *, vworld_key: str = "",
                            host_8501: str = _HOST_STREAMLIT,
                            dod_png_url: str = "",
                            dod_bounds: str = "",
                            dod_opacity: float = 0.65,
                            dod_visible: bool = True,
                            hs_img: str = "",
                            hs_bounds: str = "",
                            hs_opacity: float = 0.35) -> str:
    """tab36 (2D + DoD) 전용 — diff_viewer_dod.html 의 URL.

    tab34 의 `url_for_diff_viewer` 와 동일 파라미터 + DoD 색상 오버레이용 추가 hash.
    diff_viewer.html 원본 보존, 신규 `diff_viewer_dod.html` 가 DoD layer 를 추가 표시.

    추가 hash 파라미터:
        dod_img:     DoD 컬러 PNG URL (없으면 빈 문자열 — JS 가 자동 비활성)
        dod_opacity: 0.0~1.0 (기본 0.65)
        dod_visible: '1' | '0' (기본 '1')
        hs_img:      🆕 (2026-06-11 Q4) hillshade 회색 PNG URL
                     (빈 문자열 = 비활성 — 하위 호환 기본값)
        hs_bounds:   hillshade bbox "latMin,lonMin,latMax,lonMax"
        hs_opacity:  hillshade 불투명도 (기본 0.35) — DoD 레이어 아래 표시
    """
    src = pdf_server.DATA_SOURCES.get("drone_viewer")
    if src is None:
        return ""
    base = f"{pdf_server.PDF_SERVER_URL_BASE}{src.url_prefix}diff_viewer_dod.html"

    def bounds_str(m: Mission) -> str:
        bb = m.bbox_wgs84
        if bb is None:
            c = m.center_wgs84
            if c is None:
                raise ValueError(f"Mission {m.id}: bbox_wgs84 와 center_wgs84 모두 없음")
            lat, lon = c[0], c[1]
            return f"{lat-0.005},{lon-0.005},{lat+0.005},{lon+0.005}"
        return f"{bb[1]},{bb[0]},{bb[3]},{bb[2]}"

    qs = urllib.parse.urlencode({"l": left.id, "r": right.id, "_v": _CACHE_BUSTER})
    frag = urllib.parse.urlencode({
        "left_img":      url_for_preview(left),
        "left_tiles":    tile_url_template_for(left),
        "left_bounds":   bounds_str(left),
        "left_label":    f"{left.name} · {left.flight_date}",
        "right_img":     url_for_preview(right),
        "right_tiles":   tile_url_template_for(right),
        "right_bounds":  bounds_str(right),
        "right_label":   f"{right.name} · {right.flight_date}",
        "vworld_key":    vworld_key,
        "host_8501":     host_8501,
        "dod_img":       dod_png_url or "",
        "dod_bounds":    dod_bounds or "",
        "dod_opacity":   f"{float(dod_opacity):.3f}",
        "dod_visible":   "1" if dod_visible else "0",
        # 🆕 (2026-06-11 Q4) hillshade — DoD 아래 음영기복 overlay
        "hs_img":        hs_img or "",
        "hs_bounds":     hs_bounds or "",
        "hs_opacity":    f"{float(hs_opacity):.3f}",
    })
    return f"{base}?{qs}#{frag}"


def diff_viewer_dod_inline_html(left: Mission, right: Mission,
                                *, vworld_key: str = "",
                                dod_png_url: str = "",
                                dod_bounds: str = "",
                                dod_opacity: float = 0.65,
                                dod_visible: bool = True,
                                hs_img: str = "",
                                hs_bounds: str = "",
                                hs_opacity: float = 0.35) -> str | None:
    """[공개판] diff_viewer_dod.html 을 **인라인 HTML** 로 반환 (Cloud 용).

    Cloud 에는 pdf_server 가 없어 iframe URL 방식이 불가하므로,
    ① viewer html 파일을 직접 읽고 ② 파라미터를 window.__PARAMS__ 로 주입하며
    ③ 정사영상은 repo 동봉 preview.png 의 data URI 로 임베드한다.
    HD XYZ 타일(left_tiles/right_tiles)은 Cloud 에 없으므로 빈 문자열 —
    viewer JS 가 PNG fallback 을 자동 활성한다.
    """
    html_path = (Path(__file__).resolve().parents[1]
                 / "static" / "drone_viewer" / "diff_viewer_dod.html")
    if not html_path.exists():
        return None
    left_img = preview_static_url(left) or preview_data_uri(left)
    right_img = preview_static_url(right) or preview_data_uri(right)
    if not left_img or not right_img:
        return None

    def _bounds_str(m: Mission) -> str:
        bb = m.bbox_wgs84
        if bb is None:
            c = m.center_wgs84
            if c is None:
                raise ValueError(f"Mission {m.id}: bbox/center 모두 없음")
            lat, lon = c[0], c[1]
            return f"{lat-0.005},{lon-0.005},{lat+0.005},{lon+0.005}"
        return f"{bb[1]},{bb[0]},{bb[3]},{bb[2]}"

    frag = urllib.parse.urlencode({
        "left_img":      left_img,
        "left_tiles":    "",
        "left_bounds":   _bounds_str(left),
        "left_label":    f"{left.name} · {left.flight_date}",
        "right_img":     right_img,
        "right_tiles":   "",
        "right_bounds":  _bounds_str(right),
        "right_label":   f"{right.name} · {right.flight_date}",
        "vworld_key":    vworld_key,
        "host_8501":     "",
        "dod_img":       dod_png_url or "",
        "dod_bounds":    dod_bounds or "",
        "dod_opacity":   f"{float(dod_opacity):.3f}",
        "dod_visible":   "1" if dod_visible else "0",
        "hs_img":        hs_img or "",
        "hs_bounds":     hs_bounds or "",
        "hs_opacity":    f"{float(hs_opacity):.3f}",
    })
    html = html_path.read_text(encoding="utf-8")
    import json as _json
    inject = f"<script>window.__PARAMS__ = {_json.dumps(frag)};</script>"
    # 첫 <script> 직전에 주입 — 메인 스크립트가 읽기 전에 전역 정의 보장.
    idx = html.find("<script>")
    if idx < 0:
        return None
    return html[:idx] + inject + "\n" + html[idx:]


def url_for_diff_viewer_dod_3d(left: Mission, right: Mission, *, sse: int = 4,
                               dod_png_url: str = "",
                               dod_opacity: float = 0.55,
                               dod_visible: bool = True,
                               dod_bounds: str = "",
                               mesh_alpha: float = 1.0,
                               alt_offset: float = 1.0,
                               max_lat: float | None = None,
                               max_lon: float | None = None,
                               min_lat: float | None = None,
                               min_lon: float | None = None,
                               master_side: str = "right") -> str:
    """tab37 (3D + DoD) 전용 — diff_viewer_dod_3d.html 의 URL.

    tab35 의 `url_for_diff_viewer_3d` 와 동일 파라미터 + 3D 위 DoD raster overlay.
    """
    src = pdf_server.DATA_SOURCES.get("drone_viewer")
    if src is None:
        return ""
    base = f"{pdf_server.PDF_SERVER_URL_BASE}{src.url_prefix}diff_viewer_dod_3d.html"

    def _info(m: Mission) -> dict:
        center = m.center_wgs84 or (0.0, 0.0)  # 좌표 누락 시 안전 폴백 (None 역참조 방지)
        return {
            "tileset": _tileset_url_for_mission(m),
            "lat":     float(center[0]),
            "lon":     float(center[1]),
            "alt":     float((m.meta.get("geo") or {}).get("altitude_m") or 200.0),
            "label":   f"{m.name} · {m.flight_date}",
        }

    L, R = _info(left), _info(right)
    # DoD bbox 가 명시 안 됐으면 right.bbox 사용 (left/right 합집합/교집합 중 시각화엔 right 권장)
    if not dod_bounds:
        bb = right.bbox_wgs84 or left.bbox_wgs84
        if bb is not None:
            dod_bounds = f"{bb[1]},{bb[0]},{bb[3]},{bb[2]}"

    qs = urllib.parse.urlencode({"l": left.id, "r": right.id, "_v": _CACHE_BUSTER})
    frag = urllib.parse.urlencode({
        "left_tileset":  L["tileset"], "left_lat":  L["lat"],
        "left_lon":      L["lon"],     "left_alt":  L["alt"],
        "left_label":    L["label"],
        "right_tileset": R["tileset"], "right_lat": R["lat"],
        "right_lon":     R["lon"],     "right_alt": R["alt"],
        "right_label":   R["label"],
        "sse":           sse,
        "dod_img":       dod_png_url or "",
        "dod_bounds":    dod_bounds,
        "dod_opacity":   f"{float(dod_opacity):.3f}",
        "dod_visible":   "1" if dod_visible else "0",
        "mesh_alpha":    f"{float(mesh_alpha):.3f}",
        "alt_offset":    f"{float(alt_offset):.2f}",
        # Build 1.8: 최대 증가/감소 지점 좌표 + master 측 (좌/우 swap)
        "max_lat":       f"{float(max_lat):.6f}" if max_lat is not None else "",
        "max_lon":       f"{float(max_lon):.6f}" if max_lon is not None else "",
        "min_lat":       f"{float(min_lat):.6f}" if min_lat is not None else "",
        "min_lon":       f"{float(min_lon):.6f}" if min_lon is not None else "",
        "master_side":   master_side if master_side in ("left", "right") else "right",
    })
    return f"{base}?{qs}#{frag}"


def url_for_diff_viewer_3d(left: Mission, right: Mission, *, sse: int = 8) -> str:
    """tab35 시계열 비교(3D) — 좌·우 분할 두 Cesium Viewer (master-slave 패턴).

    구조: `…/diff_viewer_3d.html?l=<l_id>&r=<r_id>&_v=<cb>#left_tileset=…&…`
      - query (l, r, _v): Streamlit iframe 재생성 + 캐시 무효화
      - hash: 두 미션의 tileset URL, lat/lon/alt, 라벨, SSE
        (pdf_server 미전송 → DENY 토큰 충돌 없음)

    Build 3.0 (2026-05-25) master-slave 패턴:
      - 우측 = master (사용자 조작), 좌측 = slave (마우스 입력 차단, 자동 동기화)
      - LOD 일치: dynamicSSE/skipLOD/foveatedSSE/progressive/cullMoving 모두 OFF
      - adaptive SSE 4/32 가 master.moveStart/moveEnd 에서 양쪽 tileset 동시 적용
      - WebGL context lost·renderError 자가 복원, 카메라 ping-pong 원천 차단
      - 자세한 원인·해결: diff_viewer_3d.html 상단 종합 주석 참조
      - 관련 메모리: [[project-drone-dual-viewer-sync]]

    Args:
        left, right: 좌·우 표시 미션 (시뮬레이션 시 같은 객체 OK — disk cache 활용)
        sse:         maximumScreenSpaceError 정지 시 값 (DJI Terra 권장 4~8).
                     이동 중엔 viewer 안에서 32 로 자동 전환.
    """
    src = pdf_server.DATA_SOURCES.get("drone_viewer")
    if src is None:
        return ""
    base = f"{pdf_server.PDF_SERVER_URL_BASE}{src.url_prefix}diff_viewer_3d.html"

    def _info(m: Mission) -> dict:
        center = m.center_wgs84 or (0.0, 0.0)   # (lat, lon), 좌표 누락 시 안전 폴백
        return {
            "tileset": _tileset_url_for_mission(m),
            "lat":     float(center[0]),
            "lon":     float(center[1]),
            "alt":     float((m.meta.get("geo") or {}).get("altitude_m") or 200.0),
            "label":   f"{m.name} · {m.flight_date}",
        }

    L, R = _info(left), _info(right)
    qs = urllib.parse.urlencode({"l": left.id, "r": right.id, "_v": _CACHE_BUSTER})
    frag = urllib.parse.urlencode({
        "left_tileset":  L["tileset"], "left_lat":  L["lat"],
        "left_lon":      L["lon"],     "left_alt":  L["alt"],
        "left_label":    L["label"],
        "right_tileset": R["tileset"], "right_lat": R["lat"],
        "right_lon":     R["lon"],     "right_alt": R["alt"],
        "right_label":   R["label"],
        "sse":           sse,
    })
    return f"{base}?{qs}#{frag}"


def _tileset_url_for_mission(m: Mission) -> str:
    """미션의 3D Tileset.json 절대 URL — url_for_tileset() 의 wrapper.

    drone_url_base() 가 pdf_server :8766 의 drone 소스 base 반환,
    그 위에 미션 ID 와 tileset 경로 (registry.json 의 outputs.tiles_3d.tileset)
    를 quote 해서 절대 URL 생성.
    """
    return url_for_tileset(m)


def url_for_3d_viewer(tileset_url: str, lat: float, lon: float,
                      *, sse: int = 4, mission_id: str = "") -> str:
    """8766 같은 origin 의 viewer3d.html URL 을 만든다.

    핵심 설계 (2026-05-24, [[project-drone-purpose]] 참조):
      - 뷰어 HTML·Cesium 번들·3D Tiles 가 모두 같은 origin (127.0.0.1:8766)
      - → Web Worker same-origin → Draco 디코딩 worker 정상 작동
      - → tab33 의 srcdoc/cross-origin 문제 (importScripts URL invalid) 완전 해결

    URL 구조: `…/viewer3d.html?m=<mission_id>#tileset=…&lat=…&lon=…&sse=…`
      - mission_id 는 **query string** — Streamlit 이 src 차이로 iframe 재생성.
        (hash 만 바뀌면 same-document navigation 으로 reload 안 됨)
      - 뷰어 파라미터는 **URL 해시(#)** — pdf_server 에는 전송 안 되므로 strict
        URL 검사/DENY 토큰(`:`, `..`)과 충돌 없음.
      - tileset_url 은 이미 한글 quote 된 절대 URL.

    Args:
        tileset_url: 3D Tiles tileset.json 의 절대 URL
        lat, lon:    미션 중심 좌표 (fallback 카메라 위치용 보존)
        sse:         maximumScreenSpaceError (DJI Terra 권장 4~8, 작을수록 정밀
                     · 메모리 부담 ↑). 기본 4 — 데스크탑 + GPU 환경 가정.
        mission_id:  src 변경용 식별자 — 미션 전환 시 iframe 재생성 트리거.
    """
    src = pdf_server.DATA_SOURCES.get("drone_viewer")
    if src is None:
        return ""
    base = f"{pdf_server.PDF_SERVER_URL_BASE}{src.url_prefix}viewer3d.html"
    # _v 캐시버스터 — viewer3d.html 코드 갱신(예: 측정 도구 추가) 후 브라우저가 옛
    # 캐시 HTML 을 쓰지 않도록. import 시점 1회 평가라 같은 세션 내 동일, 재시작 후 새 값.
    qs_params = {"_v": _CACHE_BUSTER}
    if mission_id:
        qs_params["m"] = mission_id
    qs = urllib.parse.urlencode(qs_params)
    frag = urllib.parse.urlencode({
        "tileset": tileset_url,
        "lat": lat,
        "lon": lon,
        "sse": sse,
    })
    return f"{base}?{qs}#{frag}"


def url_for_preview(m: Mission) -> str:
    # [공개판] Cloud: ① /app/static URL (가볍고 안정) ② data URI 폴백.
    if is_cloud_env():
        url = preview_static_url(m)
        if url:
            return url
        uri = preview_data_uri(m)
        if uri:
            return uri
    return make_drone_url(drone_url_base(), m.id, "derived/preview.png")


def url_for_dsm_heatmap(m: Mission) -> str:
    return make_drone_url(drone_url_base(), m.id, "derived/dsm_heatmap.png")


def tile_url_template_for(m: Mission) -> str:
    """DJI Terra 가 export 한 XYZ 슬리피맵 타일의 Leaflet 용 URL template.

    DJI Terra 5.x 가 `map/{z}/{x}/{y}.png` 표준 OSM/Leaflet XYZ 구조로 zoom
    12~23 까지 export. ImageOverlay (단일 8192px PNG) 대신 이걸 TileLayer 로
    사용하면 줌인해도 픽셀 없이 cm 단위 디테일까지 표시 (DJI Terra GSD ≈ 2cm).

    Leaflet 의 `{z}/{x}/{y}` placeholder 는 보존 — Leaflet 이 런타임에 치환.
    """
    base = drone_url_base()
    # mission.id 의 한글은 make_drone_url 안에서 URL quote 됨.
    # 그 뒤 /map/{z}/{x}/{y}.png 는 placeholder 라 quote 안 함.
    encoded_base = make_drone_url(base, m.id, "map")
    return f"{encoded_base}/{{z}}/{{x}}/{{y}}.png"


def url_for_tileset(m: Mission) -> str:
    rel = (m.outputs.get("tiles_3d") or {}).get("tileset") or "models/pc/0/terra_b3dms/tileset.json"
    return make_drone_url(drone_url_base(), m.id, rel)


def zoom_for_bbox(bbox: tuple[float, float, float, float]) -> int:
    # 미션 BBOX → 적절한 초기 zoom. streamlit_folium 1st render 가
    # fit_bounds 적용 전에 노출되는 케이스 대비 — zoom_start 자체를 정확히 설정.
    lon_min, lat_min, lon_max, lat_max = bbox
    lat_m = (lat_max - lat_min) * 111000
    lon_m = (lon_max - lon_min) * 111000 * math.cos(math.radians((lat_min + lat_max) / 2))
    span = max(lat_m, lon_m)
    if span < 100:   return 19
    if span < 200:   return 18
    if span < 400:   return 17
    if span < 800:   return 16
    if span < 1600:  return 15
    return 14


def _hd_preview_builder(m: Mission):
    """HD preview.png 빌더 — 기존 PNG 가 HD 사이즈 미달이면 강제 재생성.

    `get_or_make_preview` 의 `_needs_rebuild` 는 src.tif mtime 만 비교하므로,
    옛 2048px PNG 가 캐시에 있으면 max_side=8192 인자를 줘도 재생성 안 됨.
    PIL 로 기존 PNG 사이즈를 확인해서 미달 시 `force=True` 로 재생성.
    """
    existing = preview_path(m)
    # [공개판] Cloud: result.tif 원본이 없어 재생성 불가 — 동봉된 PNG 그대로 사용.
    if is_cloud_env():
        return existing if existing.exists() else None
    if existing.exists():
        try:
            from PIL import Image
            with Image.open(existing) as img:
                if max(img.size) < DRONE_PREVIEW_HD_MAX_SIDE - 100:
                    return get_or_make_preview(
                        m, max_side=DRONE_PREVIEW_HD_MAX_SIDE, force=True,
                    )
        except Exception:   # noqa: BLE001
            pass   # 손상된 캐시 — get_or_make_preview 가 재생성
    return get_or_make_preview(m, max_side=DRONE_PREVIEW_HD_MAX_SIDE)


@st.cache_resource(show_spinner=False)
def get_image_provider() -> ImageOverlayProvider:
    return ImageOverlayProvider(
        registry=get_registry(),
        url_func=url_for_preview,
        preview_builder=_hd_preview_builder,
    )


# ──────────────────────────────────────────────────────────────────
#  공용 표시 헬퍼
# ──────────────────────────────────────────────────────────────────
def mission_label(m: Mission) -> str:
    return f"{m.name} ({m.flight_date}) — {m.site_type}"


def gsd_cm_str(m: Mission, key: str = "result_tif") -> str:
    out = (m.meta.get("outputs") or {}).get(key) or {}
    gsd = out.get("gsd_m")
    return f"{gsd*100:.2f}" if isinstance(gsd, (int, float)) else "—"


def site_color(site_type: str) -> str:
    from config import DRONE_SITE_TYPE_COLORS
    return DRONE_SITE_TYPE_COLORS.get(site_type, theme.COLOR_TEXT_SECONDARY)
