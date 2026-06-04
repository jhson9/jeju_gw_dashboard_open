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

from src.dashboard import pdf_server, theme
from src.drone import (
    DroneRegistry,
    DsmSampler,
    ImageOverlayProvider,
)

# ──────────────────────────────────────────────────────────────────
#  folium monkey-patch — `/app/static/...` 절대 경로 URL 인정 (2026-06-02 v4)
# ------------------------------------------------------------------
#  folium.utilities._is_url() 은 scheme 가 http/https/ftp/data 인 경우만 URL
#  로 인정 → `/app/static/drone_assets/...` 같은 same-origin 절대 경로는
#  파일 시스템 경로로 오해되어 ImageOverlay 가 open(image,"rb") 시도 →
#  PermissionError [Errno 13]. Cloud 환경 `/app/static/` 은 브라우저에서만
#  유효한 same-origin URL 이므로 Python 단에선 file open 시도 자체를 막아야 함.
#  → `/` 로 시작하면 URL 로 취급하도록 패치.
# ──────────────────────────────────────────────────────────────────
try:
    import folium.utilities as _folium_utils
    _orig_is_url = _folium_utils._is_url

    def _patched_is_url(url):
        if isinstance(url, str) and url.startswith("/"):
            return True   # same-origin absolute path → URL 로 취급
        return _orig_is_url(url)

    if getattr(_folium_utils._is_url, "__name__", "") != "_patched_is_url":
        _folium_utils._is_url = _patched_is_url
        # folium.raster_layers 등 다른 모듈도 import-time 에 별칭으로 보유 가능 →
        # 명시적 재바인딩.
        try:
            import folium.raster_layers as _folium_raster
            if hasattr(_folium_raster, "_is_url"):
                _folium_raster._is_url = _patched_is_url
        except ImportError:
            pass
except ImportError:
    pass

from src.drone.preview import get_or_make_preview, preview_path
from src.drone.providers import make_drone_url
from src.drone.registry import Mission

# 정사영상 preview.png 의 HD 해상도 — 2026-05-23 사용자 요청.
# 시설물 관리 목적상 균열·이동·노후 감지가 가능한 해상도 필요. 데스크탑 + GPU 환경 전제
# 라 메모리 부담 수용 가능. preview.py 의 default 2048 은 변경 안 함 (다른 잠재 호출처 격리).
DRONE_PREVIEW_HD_MAX_SIDE = 8192


# ──────────────────────────────────────────────────────────────────
#  Cloud 환경 감지 — pdf_server (:8766 localhost) 미접근 가드 (2026-06-02)
# ------------------------------------------------------------------
#  pdf_server 는 PDF_SERVER_HOST="127.0.0.1" 로 listen — Streamlit Cloud
#  같은 외부 호스팅 환경에서는 브라우저(원격 사용자)가 127.0.0.1 로 접속 시
#  본인 PC 의 8766 을 보러 가므로 "연결을 거부했습니다" 오류 발생.
#  tab33/34/35 의 Cesium iframe 은 본질적으로 localhost same-origin 전제이므로
#  Cloud 환경에서는 iframe 렌더 대신 안내 메시지로 대체.
#
#  감지 전략 (우선순위):
#    1) 환경 변수 STREAMLIT_RUNTIME_ENV=cloud (사용자 명시 override)
#    2) Streamlit Cloud 가 자동 설정하는 환경 변수들:
#       - HOSTNAME 에 'streamlit' 또는 'streamlit-cloud' 포함
#       - HOME=/home/appuser 같은 컨테이너 흔적 + /mount/src 존재
#    3) 그 외 → 로컬로 간주.
# ──────────────────────────────────────────────────────────────────
def is_cloud_env() -> bool:
    """Streamlit Cloud (또는 유사 원격 호스팅) 환경 여부.

    pdf_server 가 127.0.0.1:8766 에 묶여 있어 외부 사용자가 접근 불가능한
    환경(=Cloud 배포) 에서 True. tab33/34/35 가 iframe 렌더 대신 안내문 출력.

    2026-06-02 fix: 이전 가드는 HOME=/home/appuser AND /mount/src 였으나
    실제 Streamlit Cloud 컨테이너는 HOME=/home/adminuser. 더 robust 한
    감지로 교체:
      1) /mount/src/ 존재 단독 — Cloud 컨테이너 고유 마운트 (가장 확실)
      2) STREAMLIT_SERVER_PORT 환경변수 — Cloud entrypoint가 설정
      3) /home/{adminuser,appuser} 패턴 + /mount 존재
    """
    import os
    # 1) /mount/src/ 존재 (Streamlit Cloud 고유) — 가장 확실
    if Path("/mount/src").exists():
        return True
    # 2) STREAMLIT_RUNTIME_ENV 명시 환경
    if os.environ.get("STREAMLIT_RUNTIME_ENV", "").lower() == "cloud":
        return True
    # 3) HOSTNAME 패턴
    hostname = (os.environ.get("HOSTNAME") or "").lower()
    if "streamlit" in hostname:
        return True
    # 4) 컨테이너 HOME 패턴 + 마운트
    home = os.environ.get("HOME", "")
    if home in ("/home/appuser", "/home/adminuser") and Path("/mount").exists():
        return True
    return False


def render_cloud_unavailable_notice(tab_label: str, *, missing_feature: str) -> None:
    """Cloud 환경에서 pdf_server 의존 탭의 대체 안내문."""
    st.info(
        f"### {tab_label} — 클라우드 환경 미지원\n\n"
        f"**{missing_feature}** 기능은 데스크탑 환경(로컬 PC 의 pdf_server :8766) "
        f"에서만 사용 가능합니다. 이 탭은 대용량 3D 모델 / 같은-origin Cesium "
        f"Worker 가 필요해 Streamlit Cloud 같은 원격 호스팅에서는 표시할 수 없습니다.\n\n"
        f"**대안:**\n"
        f"- 31번 탭: 미션 메타 + 정사영상 미리보기 (Cloud 가능)\n"
        f"- 32번 탭: 정사영상 위에 V-World 배경 (Cloud 가능)\n"
        f"- 로컬 PC 에서 `streamlit run src/dashboard/app.py` 실행 시 자동 활성"
    )

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
def _check_mission_bbox_cached(mission_dir_str: str, _sig: tuple):
    """Tab31 전용 캐시 wrapper. _sig 가 변하면 자동 무효화 (사용자가 importer
    실행해서 result.tif 가 갱신된 경우)."""
    from src.drone.meta_validator import check_mission_bbox
    return check_mission_bbox(mission_dir_str)


def check_mission_bbox_fast(mission_dir):
    """Tab31 호출용 외부 인터페이스. 시그니처 → wrapper 호출."""
    return _check_mission_bbox_cached(str(mission_dir), _result_tif_signature(mission_dir))


def drone_url_base() -> str:
    """드론 자료 URL base.

    - 로컬 dev: pdf_server :8766 의 drone 화이트리스트
    - Streamlit Cloud (2026-06-02 v3 fix): /app/static/drone_assets (same-origin).
      pre-rendered preview.png / dsm_heatmap.png 가 src/dashboard/static/drone_assets/
      안에 있음 (일반 git 파일, LFS 미적용 — 100MB 제한 안).
      GitHub LFS raw URL 은 anonymous fetch 시 403 (allowlist) 차단되어 사용 불가.
    """
    if is_cloud_env():
        return "/app/static/drone_assets"
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
                        host_8501: str = "http://127.0.0.1:8501") -> str:
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
    # 2026-06-02 v3 fix: Cloud 환경에서는 Streamlit static 의 drone_viewer/ 사용.
    # diff_viewer.html 안 정사영상 URL 은 hash 에 담겨 자동으로 drone_url_base()
    # 분기를 따라 /app/static/drone_assets/... same-origin URL 이 됨.
    if is_cloud_env():
        base = "/app/static/drone_viewer/diff_viewer.html"
    else:
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
        center = m.center_wgs84   # (lat, lon)
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
