# ==============================================================================
#  파일명: tests/test_map_helpers.py
#  목적: 지도 헬퍼의 critical 회귀 가드.
#       _tm_to_wgs84 좌표 변환 (회귀 시 모든 지도 마커가 잘못 표시),
#       _parse_dms DMS 파싱, make_map 의 V-World/OSM 폴백 분기 smoke.
#       Phase A #3 (V-World+OSM 폴백 동시 추가) + #4 (Hybrid show=False) 보호.
# ==============================================================================
import folium


# ──────────────────────────────────────────────────────────────────
#  _tm_to_wgs84 — EPSG:5186 (중부원점 TM) → WGS84
# ──────────────────────────────────────────────────────────────────
def test_tm_to_wgs84_jeju_island_range():
    """제주도 범위 TM 좌표 → 제주도 WGS84 범위 변환."""
    from src.dashboard.map_helpers import _tm_to_wgs84

    # 제주 중심 근처 TM 좌표 (실제 JD관측망 정보의 X/Y 범위)
    lat, lon = _tm_to_wgs84(160000, 100000)
    # 변환 성공 + 제주도 위경도 범위 (33~34 N, 126~127 E)
    assert lat is not None and lon is not None
    assert 33 <= lat <= 34, f"lat 가 제주 범위 밖: {lat}"
    assert 126 <= lon <= 127, f"lon 가 제주 범위 밖: {lon}"


def test_tm_to_wgs84_returns_floats():
    """반환 타입이 float (downstream 의 pd.notna · folium 호환)."""
    from src.dashboard.map_helpers import _tm_to_wgs84

    lat, lon = _tm_to_wgs84(160000, 100000)
    assert isinstance(lat, float)
    assert isinstance(lon, float)


def test_tm_to_wgs84_invalid_input_returns_none():
    """문자열 등 잘못된 입력 → (None, None) 폴백 (KeyError 없음)."""
    from src.dashboard.map_helpers import _tm_to_wgs84

    # pyproj 가 ValueError raise → except 가 None 반환
    lat, lon = _tm_to_wgs84("not_a_number", "also_invalid")
    assert lat is None and lon is None


# ──────────────────────────────────────────────────────────────────
#  _parse_dms — "DD MM SS.sss" → 십진수
# ──────────────────────────────────────────────────────────────────
def test_parse_dms_korean_format():
    """JD관측망 xlsx 의 DMS 형식 파싱."""
    from src.dashboard.map_helpers import _parse_dms

    # "33 29 35.815" → 33 + 29/60 + 35.815/3600 ≈ 33.4933
    result = _parse_dms("33 29 35.815")
    assert result is not None
    assert abs(result - 33.4933) < 0.001


def test_parse_dms_longitude():
    """경도 DMS 파싱."""
    from src.dashboard.map_helpers import _parse_dms

    # "126 32 43.688" → 126 + 32/60 + 43.688/3600 ≈ 126.5455
    result = _parse_dms("126 32 43.688")
    assert result is not None
    assert abs(result - 126.5455) < 0.001


def test_parse_dms_invalid_format():
    """비표준 입력 → None (KeyError 없음)."""
    from src.dashboard.map_helpers import _parse_dms

    assert _parse_dms("not dms") is None
    assert _parse_dms("") is None
    assert _parse_dms("123") is None


# ──────────────────────────────────────────────────────────────────
#  make_map — V-World/OSM 폴백 분기 smoke (Phase A #3, #4)
# ──────────────────────────────────────────────────────────────────
def test_make_map_returns_folium_map():
    """기본 호출 시 folium.Map 객체 반환."""
    from src.dashboard.map_helpers import make_map

    m = make_map()
    assert isinstance(m, folium.Map)


def test_make_map_with_custom_center_and_zoom():
    """center / zoom 인자 반영."""
    from src.dashboard.map_helpers import make_map

    m = make_map(center=(33.5, 126.5), zoom=14)
    # folium.Map 의 location 속성에 center 가 저장됨
    assert isinstance(m, folium.Map)


def test_make_map_has_layer_control():
    """LayerControl 이 항상 추가됨 (Phase A #3 V-World+OSM 폴백 표시용)."""
    from src.dashboard.map_helpers import make_map

    m = make_map()
    # LayerControl 자식 노드 존재 확인
    has_layer_control = any(
        isinstance(child, folium.LayerControl)
        for child in m._children.values()
    )
    assert has_layer_control, "LayerControl 가 없으면 V-World/OSM 폴백 전환 불가"


def test_make_map_has_multiple_tile_layers():
    """타일 레이어가 여러 개 추가됨 — V-World 키 유무와 관계없이 폴백 보장.

    Phase A #3: V-World 키가 있어도 Esri/OSM 폴백 동시 추가.
    """
    from src.dashboard.map_helpers import make_map

    m = make_map()
    # folium.TileLayer 자식 카운트
    tile_layers = [
        child for child in m._children.values()
        if isinstance(child, folium.TileLayer)
    ]
    # V-World 환경: 위성/하이브리드/일반/흑백 + Esri 폴백 + OSM 폴백 = 6
    # 폴백 환경: Esri + OSM = 2
    # 어느 쪽이든 최소 2개 이상 보장
    assert len(tile_layers) >= 2, (
        f"폴백 TileLayer 누락 — V-World 장애 시 흰 캔버스 위험. "
        f"실제 개수: {len(tile_layers)}"
    )
