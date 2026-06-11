# ==============================================================================
#  파일명: src/dashboard/map_helpers.py
#  Build 1.2.05 — 지도(V-World) 헬퍼 + 관측정/AWS 좌표 정규화
# ------------------------------------------------------------------------------
#  주요 기능:
#  1) 0_JD관측망_정보.xlsx 로드 → 위도/경도(WGS84) 정규화 (DMS·TM 혼재 대응)
#  2) Folium 지도 생성: V-World 타일 (키 있을 때) + OSM/위성 폴백
#     - 마우스 휠 줌 비활성, +/- 버튼만 사용 (요청 1)
#     - 미터 전용 스케일 바 + 3배 확대 (요청 5)
#  3) 관측정/AWS 마커: 영구 라벨 표시 + AWS는 사각형 2배 (요청 2·3·4)
# ==============================================================================

from __future__ import annotations

import re
from functools import lru_cache
from pathlib import Path

import pandas as pd
import folium
import streamlit as st
from branca.element import MacroElement
from jinja2 import Template

import config


# ==============================================================================
#  ■ 0. 오프라인 지도 엔진 — folium 의 CDN 자원을 로컬로 교체 (2026-06-08)
# ------------------------------------------------------------------------------
#  folium 0.20.0 은 leaflet.js/css·leaflet-dvf 등을 매번 외부 CDN 에서 불러온다.
#  인터넷이 없으면 타일(로컬)은 있어도 지도 엔진이 로드되지 않아 빈 화면이 됨.
#  데이터 관리 → "지도 오프라인 저장" 으로 tile_cache.download_map_libs() 가
#  이 자원들을 /app/static/libs/leaflet_offline/ 에 받아두면, 아래 함수가
#  folium 의 default_js/default_css 를 그 로컬 경로로 교체한다.
#  로컬 파일이 없으면(아직 안 받음) 원래 CDN 그대로 사용 — 자동 폴백.
# ==============================================================================
_LOCAL_LIBS_BASE = "/app/static/libs/leaflet_offline"

# folium 기본 CDN 자원 원본 보존 (최초 import 시 1회).
_ORIG_MAP_JS = list(folium.Map.default_js)
_ORIG_MAP_CSS = list(folium.Map.default_css)
_ORIG_DVF_JS = list(folium.RegularPolygonMarker.default_js)


def _apply_offline_map_libs() -> bool:
    """로컬 Leaflet 엔진이 준비됐으면 folium 자원 URL 을 로컬로, 아니면 CDN 으로.

    make_map() 진입 시마다 호출 — 다운로드 직후(같은 세션)에도 즉시 반영되며,
    매번 원본 기준으로 재구성하므로 중복/누적 교체가 없다.
    반환: 오프라인(로컬) 적용 여부.
    """
    try:
        from src.dashboard import tile_cache
        ready = tile_cache.map_libs_ready()
        name_to_file = {a["name"]: a["filename"] for a in tile_cache.MAP_LIB_ASSETS}
    except Exception:
        ready = False
        name_to_file = {}

    def _swap(orig: list) -> list:
        out = []
        for name, url in orig:
            if name in name_to_file:
                out.append((name, f"{_LOCAL_LIBS_BASE}/{name_to_file[name]}"))
            else:
                out.append((name, url))
        return out

    if ready:
        folium.Map.default_js = _swap(_ORIG_MAP_JS)
        folium.Map.default_css = _swap(_ORIG_MAP_CSS)
        folium.RegularPolygonMarker.default_js = _swap(_ORIG_DVF_JS)
    else:
        # 원복 (로컬 미준비 — CDN 사용)
        folium.Map.default_js = list(_ORIG_MAP_JS)
        folium.Map.default_css = list(_ORIG_MAP_CSS)
        folium.RegularPolygonMarker.default_js = list(_ORIG_DVF_JS)
    return ready


# ==============================================================================
#  ■ 1. AWS 좌표 (기상청 ASOS 공개 좌표)
# ==============================================================================
AWS_COORDS = {
    # 지점명: (위도, 경도)
    "제주":   (33.5141, 126.5297),   # 184
    "서귀포": (33.2461, 126.5653),   # 189
    "성산":   (33.3868, 126.8801),   # 188
    "고산":   (33.2937, 126.1626),   # 185
}


# ==============================================================================
#  ■ 2. 좌표 변환 유틸
# ==============================================================================
def _parse_dms(text: str) -> float | None:
    """'126 32 43.688' → 126.5454 (decimal degrees)."""
    if not isinstance(text, str):
        return None
    m = re.match(r"^\s*(\d+)\s+(\d+)\s+([\d\.]+)\s*$", text)
    if not m:
        return None
    deg, mn, sec = float(m.group(1)), float(m.group(2)), float(m.group(3))
    return deg + mn / 60.0 + sec / 3600.0


def _tm_to_wgs84(x: float, y: float) -> tuple[float | None, float | None]:
    """EPSG:5186(중부원점 TM, false_easting=200000, false_northing=600000)
    → WGS84 (lat, lon). 실패 시 (None,None).

    ⚠️ 좌표계 변경 금지 — 실측 검증 완료 (2026-05-28):
       master.csv 의 D199510018(제주시 오등동, x=156398.508 y=95756.1791) 가
       EPSG:5186 변환 시 lat=33.454, lon=126.531 (실제 오등동 위치 일치),
       EPSG:5187 로는 lon=128.5 (일본 영해) 로 오변환됨.
       제주가 중부원점(127°E)에서 멀어 X 가 false_easting 200000 보다 작고
       (200000 - 약 44km = 156000), Y 가 false_northing 600000 보다 한참 작은
       (600000 - 약 504km = 96000) 것은 정상.
    """
    try:
        from pyproj import Transformer  # noqa: F401  (import 확인용)
        tr = _get_tm_transformer()
        lon, lat = tr.transform(x, y)
        return float(lat), float(lon)
    except Exception:
        return None, None


@lru_cache(maxsize=1)
def _get_tm_transformer():
    from pyproj import Transformer
    return Transformer.from_crs("EPSG:5186", "EPSG:4326", always_xy=True)


# ==============================================================================
#  ■ 3. 관측정 메타 로드 (위도·경도 정규화 포함)
# ==============================================================================
@st.cache_data(ttl=600, show_spinner=False)
def load_station_meta() -> pd.DataFrame:
    """
    0_JD관측망_정보.xlsx 를 로드하고 'lat', 'lon' 컬럼(WGS84 십진수)을 추가.

    원본 컬럼:
      관측소명, 허가번호, 표고 TOC(m), 표고 BOC(m), 케이싱 구경, 관정심도(m),
      운영현황, 공개수준, 지하수 용도, 유역구분, 유역명, X, Y, 위도, 경도, 위치

    원본 파일의 '위도' 컬럼에는 longitude DMS("126 32 43.688") 가,
    '경도' 컬럼에는 latitude DMS("33 29 35.815") 가 들어있는 경우가 다수.
    일부 행은 X·Y 와 동일한 TM 수치가 위도·경도에 들어있기도 함.
    아래 로직이 두 케이스 모두 처리.
    """
    p = config.find_jd_network_file()
    if p is None:
        return pd.DataFrame()

    df = pd.read_excel(p)
    if "관측소명" not in df.columns:
        return pd.DataFrame()

    lats, lons = [], []
    for _, row in df.iterrows():
        v_wido = row.get("위도")
        v_gyeong = row.get("경도")
        x_tm = row.get("X")
        y_tm = row.get("Y")

        lat = lon = None

        # ① DMS 문자열 케이스: 위도 컬럼에 longitude, 경도 컬럼에 latitude
        wido_dms = _parse_dms(str(v_wido)) if isinstance(v_wido, str) else None
        gy_dms   = _parse_dms(str(v_gyeong)) if isinstance(v_gyeong, str) else None
        if wido_dms is not None and gy_dms is not None:
            # 한국 위도는 33~38, 경도는 124~132
            if 124 <= wido_dms <= 132 and 33 <= gy_dms <= 38:
                lon, lat = wido_dms, gy_dms
            elif 33 <= wido_dms <= 38 and 124 <= gy_dms <= 132:
                lat, lon = wido_dms, gy_dms

        # ② TM 수치 케이스: X/Y → WGS84
        if (lat is None or lon is None) and pd.notna(x_tm) and pd.notna(y_tm):
            try:
                xv, yv = float(x_tm), float(y_tm)
                if 100000 < xv < 250000 and 50000 < yv < 150000:
                    lat, lon = _tm_to_wgs84(xv, yv)
            except (ValueError, TypeError):
                pass

        lats.append(lat); lons.append(lon)

    df["lat"] = lats
    df["lon"] = lons
    return df


# ==============================================================================
#  ■ 4. Folium 지도 생성
# ==============================================================================
class _MetricScale(MacroElement):
    """미터 단위 전용, 더 넓게 보이는 maxWidth 의 스케일 바."""
    _template = Template("""
        {% macro script(this, kwargs) %}
            L.control.scale({
                imperial: false,
                metric: true,
                maxWidth: 280,
                position: 'bottomleft',
                updateWhenIdle: true
            }).addTo({{ this._parent.get_name() }});
        {% endmacro %}
    """)


# 지도/마커/스케일 일괄 CSS — Folium 의 <head> 에 주입.
_MAP_CSS = """
<style>
/* (요청 5) 스케일 바 ~3배 확대 + 미터 단위만 */
.leaflet-control-scale-line {
    font-size: 16px !important;
    line-height: 22px !important;
    height: 26px !important;
    border-width: 3px !important;
    padding: 2px 12px !important;
    box-sizing: border-box !important;
    background: rgba(255,255,255,0.85) !important;
    color: var(--color-text-primary) !important;
    font-weight: 600 !important;
}
.leaflet-control-scale {
    margin: 8px 12px !important;
}

/* (요청 2·3) 영구 라벨 - 관측정 */
.leaflet-tooltip.jeju-st-label {
    background: rgba(255,255,255,0.85);
    border: 0.5px solid rgba(24,95,165,0.45);
    border-radius: 3px;
    color: var(--color-text-info);
    font-size: 10px;
    font-weight: 600;
    padding: 1px 4px;
    box-shadow: 0 1px 1px rgba(0,0,0,0.10);
    white-space: nowrap;
}
.leaflet-tooltip.jeju-st-label-sel {
    background: var(--color-danger);
    border: 1px solid #e24b4a;
    color: var(--color-bg-primary);
    font-size: 11px;
    font-weight: 700;
    padding: 2px 6px;
    border-radius: 4px;
    box-shadow: 0 1px 2px rgba(0,0,0,0.20);
}
/* (요청 3) 영구 라벨 - AWS */
.leaflet-tooltip.jeju-aws-label {
    background: rgba(255,166,74,0.95);
    border: 0.8px solid #BA7517;
    color: var(--color-bg-primary);
    font-size: 12px;
    font-weight: 700;
    padding: 2px 6px;
    border-radius: 4px;
    box-shadow: 0 1px 2px rgba(0,0,0,0.18);
}
.leaflet-tooltip.jeju-aws-label-sel {
    background: var(--color-danger);
    border: 1.5px solid #e24b4a;
    color: var(--color-bg-primary);
    font-size: 13px;
    font-weight: 800;
    padding: 3px 8px;
    border-radius: 5px;
    box-shadow: 0 2px 3px rgba(0,0,0,0.22);
}
/* 화살표 색은 라벨 배경에 맞춰 자연스럽게 */
.leaflet-tooltip.jeju-aws-label::before,
.leaflet-tooltip.jeju-aws-label-sel::before { display: none; }
.leaflet-tooltip.jeju-st-label::before,
.leaflet-tooltip.jeju-st-label-sel::before { display: none; }
</style>
"""


def make_map(center: tuple[float, float] = (33.42, 126.55),
             zoom: float = 11.5) -> folium.Map:
    """
    제주 중심의 Folium 지도 + 베이스맵 레이어.

    v1.2.05:
    - 마우스 휠/더블클릭 줌 비활성화, +/- 버튼만 (요청 1)
    - 드래그(panning)는 유지
    - 미터 전용 스케일 바, 3배 확대 (요청 5)

    v1.2.10 (사용자 요청 2026-05-09):
    - center (33.38→33.42) 북상 — 본섬만 보이고 마라도는 화면 밖
    - zoom 11→11.5 + zoomSnap=0.5 (Leaflet fractional 줌 활성)
      → 본섬을 약 1.2배 확대해 화면을 꽉 채움

    v1.2.20 (2026-06-08):
    - 오프라인 지도 엔진 지원 — 로컬에 Leaflet 자원이 받아져 있으면 CDN 대신
      /app/static/libs/leaflet_offline/ 사용 (인터넷 없이도 지도 표시).
    """
    _apply_offline_map_libs()

    m = folium.Map(
        location=list(center), zoom_start=zoom,
        tiles=None,                      # 직접 레이어 추가
        control_scale=False,             # 기본 스케일 끄고 커스텀 사용
        # 줌 인터랙션 (요청 1)
        scrollWheelZoom=False,
        doubleClickZoom=False,
        touchZoom=False,
        boxZoom=False,
        zoomControl=True,                # +/- 버튼은 유지
        dragging=True,                   # 드래그 패닝은 유지
        # fractional zoom 활성 — zoom_start=11.5 같은 0.5 단위 적용 가능
        zoomSnap=0.5,
    )

    # 커스텀 스케일 + 마커/스케일 CSS 일괄 주입
    m.get_root().header.add_child(folium.Element(_MAP_CSS))
    m.add_child(_MetricScale())

    # ── 로컬 캐시 타일 (Step 2 사전 다운로드, 2026-05-14) ─────────────────
    # src/dashboard/static/map_tiles/{Layer}/{z}/{x}/{y}.{ext} — 제주 bbox
    # zoom 10~14 캐시. zoom 15+ 는 max_native_zoom 으로 14 의 타일을 확대 표시(블러).
    # 사용자 합의 (2026-05-14): LayerControl 메뉴는 V-World 일반 + 위성 2개만.
    #   - default = 일반 (사용자 평소 워크플로우)
    #   - 캐시 갱신: "데이터 관리" 탭의 "🗺️ 지도 타일 캐시" 섹션에서 버튼으로 재다운로드
    #   - CDN 폴백 / Esri / OSM / 하이브리드 / 흑백 layer 는 제거 (혼란만 가중)
    #   - V-World API key 없으면 OSM 단일 폴백 (이 환경은 사실상 .env 에 키 있음)
    local_attr = "ⓒ V-World (로컬 캐시)"
    # default = V-World 일반.
    # 두 base layer 모두 show=True 면 Leaflet LayerControl 이 "마지막 추가된 base"
    # 를 활성화한다 (add_to 순서 무관). 일반을 default 로 강제하기 위해 위성에
    # show=False 를 명시. 사용자가 LayerControl 에서 위성으로 토글 시 즉시 전환.
    folium.TileLayer(
        tiles="/app/static/map_tiles/Base/{z}/{x}/{y}.png",
        attr=local_attr, name="V-World 일반", overlay=False, control=True,
        min_zoom=8, max_zoom=19,
        min_native_zoom=10, max_native_zoom=14,
        show=True,
    ).add_to(m)
    folium.TileLayer(
        tiles="/app/static/map_tiles/Satellite/{z}/{x}/{y}.jpeg",
        attr=local_attr, name="V-World 위성", overlay=False, control=True,
        min_zoom=8, max_zoom=19,
        min_native_zoom=10, max_native_zoom=14,
        show=False,
    ).add_to(m)

    # V-World API key 미설정 환경의 최소 안전망 — 캐시 디렉토리가 비었거나
    # 신규 배포 직후 사용자가 캐시 다운로드 전이라도 일단 지도가 뜨도록 OSM 추가.
    # 정상 환경에서는 위 두 로컬 layer 만 노출되고 OSM 은 LayerControl 에서 보이지만
    # default 가 V-World 일반이라 사용자가 의식적으로 전환하지 않으면 활성화 안 됨.
    key = (config.VWORLD_API_KEY or "").strip()
    if not key:
        folium.TileLayer(
            "OpenStreetMap", name="일반지도 (OSM)",
            overlay=False, control=True
        ).add_to(m)

    # 요청 3: 위·아래 펼쳐지지 않고 접힌 상태로 유지 → 클릭 시에만 목록 노출
    folium.LayerControl(collapsed=True, position="topright").add_to(m)
    return m


def add_station_markers(m: folium.Map, station_df: pd.DataFrame,
                        selected: str | None = None) -> None:
    """관측정 마커(파랑 ●). selected 일치 시 빨간 ★ 강조.

    v1.2.05: 모든 관측정 이름을 영구 라벨로 표시 (요청 2).
    """
    for _, r in station_df.iterrows():
        if pd.isna(r.get("lat")) or pd.isna(r.get("lon")):
            continue
        name = r["관측소명"]
        is_sel = (name == selected)
        ws = r.get("유역명", "")
        popup = (
            f'<div style="font-size:12px;line-height:1.4;">'
            f'<b style="font-size:13px;">{name}</b><br>'
            f'유역: {ws}<br>'
            f'표고 TOC: {r.get("표고 TOC(m)", "-")} m<br>'
            f'관정심도: {r.get("관정심도(m)", "-")} m<br>'
            f'운영현황: {r.get("운영현황", "-")}'
            f'</div>'
        )
        # 영구 라벨 (요청 2): direction=right 로 마커 우측에 노출
        if is_sel:
            label = folium.Tooltip(
                f"★ {name}", permanent=True, direction="right",
                offset=(10, 0), sticky=False,
                class_name="jeju-st-label-sel",
            )
            # 선택 halo — pointer-events:none (sel-halo) 으로 클릭 안전.
            folium.CircleMarker(
                location=[r["lat"], r["lon"]],
                radius=20,
                color="transparent", weight=0,
                fill=True, fill_color="#e24b4a", fill_opacity=0.18,
                class_name="sel-halo",
            ).add_to(m)
            folium.CircleMarker(
                location=[r["lat"], r["lon"]],
                # 호소 #4 — hit-area 개선: 선택 10→12.
                radius=12, color="#e24b4a", weight=3,
                fill=True, fill_color="#ffd1d0", fill_opacity=0.9,
                tooltip=label,
                popup=folium.Popup(popup, max_width=240),
            ).add_to(m)
        else:
            label = folium.Tooltip(
                name, permanent=True, direction="right",
                offset=(7, 0), sticky=False,
                class_name="jeju-st-label",
            )
            folium.CircleMarker(
                location=[r["lat"], r["lon"]],
                # 호소 #4 — hit-area 개선: 비선택 5→7, weight 1.5→2.
                radius=7, color="#185fa5", weight=2,
                fill=True, fill_color="#378ADD", fill_opacity=0.85,
                tooltip=label,
                popup=folium.Popup(popup, max_width=240),
            ).add_to(m)


def add_aws_markers(m: folium.Map, selected: str | None = None) -> None:
    """AWS 4개 마커.

    v1.2.05:
    - (요청 4) 사각형 (number_of_sides=4, rotation=45) 으로 변경, 크기 ~2배
    - (요청 3) 지점명 영구 라벨 노출
    """
    for s in config.STATIONS_ASOS:
        nm = s["name"]
        coord = AWS_COORDS.get(nm)
        if not coord:
            continue
        is_sel = (nm == selected)
        popup = (
            f'<div style="font-size:12px;line-height:1.4;">'
            f'<b style="font-size:13px;color:{s["color"]};">{nm} AWS</b><br>'
            f'지점코드: {s["id"]}<br>'
            f'위도: {coord[0]:.4f}, 경도: {coord[1]:.4f}'
            f'</div>'
        )
        # 사각형 (rotation=45 → 축 정렬). 크기 2배: 7→14 / 12→24
        radius = 24 if is_sel else 14
        weight = 3 if is_sel else 1.8
        edge   = "#e24b4a" if is_sel else "#BA7517"
        # 라벨: tooltip click-sync 와의 호환을 위해 텍스트는 'XXX AWS' 유지
        label_class = "jeju-aws-label-sel" if is_sel else "jeju-aws-label"
        label = folium.Tooltip(
            f"{'★ ' if is_sel else ''}{nm} AWS",
            permanent=True, direction="right",
            offset=(radius + 4, 0), sticky=False,
            class_name=label_class,
        )
        folium.RegularPolygonMarker(
            location=list(coord),
            number_of_sides=4, rotation=45,
            radius=radius, color=edge, weight=weight,
            fill=True, fill_color="#FFA64A", fill_opacity=0.92,
            tooltip=label,
            popup=folium.Popup(popup, max_width=220),
        ).add_to(m)
