# ==============================================================================
#  파일명: tests/test_tab10_smoke.py  -  신규 (검증 회귀팀, 2026-05-07)
#  목적: ⑥-2 이용량 세부 분석 탭(tab10) 신규 헬퍼/마스터/그리드 매핑 smoke test.
#       app.py / 기존 탭에는 영향 없음.
# ==============================================================================
import sys
from pathlib import Path

# 프로젝트 루트를 sys.path 에 추가 (`pytest tests/` 직접 실행 호환)
_PROJ_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJ_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJ_ROOT))


def test_helpers_imports():
    from src.dashboard.usage_detail_helpers import (
        DIVERGING_USAGE,
        EUP_GRID_LAYOUT,
        HALLASAN_BLANK,
        load_master,
        load_eup_geometry,
        load_ri_centroids,
        load_hotspots,
    )
    assert len(DIVERGING_USAGE) == 5
    assert all(c.startswith("#") and len(c) == 7 for c in DIVERGING_USAGE)
    assert len(EUP_GRID_LAYOUT) == 12
    assert HALLASAN_BLANK == [(1, 1), (1, 2), (2, 1), (2, 2)]
    # 사용 예방 — 호출만 확인 (load 자체가 throw 하면 fail)
    assert callable(load_master)
    assert callable(load_eup_geometry)
    assert callable(load_ri_centroids)
    assert callable(load_hotspots)


def test_master_load():
    from src.dashboard.usage_detail_helpers import load_master

    df = load_master()
    assert len(df) == 12
    assert {"한림읍", "남원읍", "성산읍"}.issubset(set(df["eup_dong"]))


def test_grid_keys_match_master():
    from src.dashboard.usage_detail_helpers import EUP_GRID_LAYOUT, load_master

    df = load_master()
    assert set(EUP_GRID_LAYOUT.keys()) == set(df["eup_dong"])


# ─────────────────────────────────────────────────────────────────────────────
#  _tab22_helpers.py 실 화면 함수 smoke (D8 — 검증팀9 지적 커버리지 보강)
# ─────────────────────────────────────────────────────────────────────────────
def test_tab22_helpers_import_and_callable():
    """_tab22_helpers 모듈 import + 주요 helper 함수가 callable 인지 확인."""
    from src.dashboard.tabs import _tab22_helpers as h

    for name in (
        "_treemap_color",
        "_cluster_unit_slots",
        "_ri_unit_aggregates",
        # "_global_monthly_per_well_daily_max",  # P3-4 (2026-05-29): dead 제거됨 (DAILY_USAGE_VMAX 절대도메인 사용)
        "_monthly_per_well_daily_range",
        "_build_cluster_ri_treemap",
        "_build_cluster_monthly_treemaps",
        "_render_admin_cluster_detail",
        "_render_unit_detail",
    ):
        assert hasattr(h, name), f"_tab22_helpers.{name} 누락"
        assert callable(getattr(h, name)), f"_tab22_helpers.{name} 가 callable 아님"


def test_treemap_color_scaling():
    """_treemap_color 가 0/1 경계와 중간값에서 HEX/RGB 문자열을 반환."""
    from src.dashboard.tabs._tab22_helpers import _treemap_color

    c0 = _treemap_color(0.0)
    c1 = _treemap_color(1.0)
    c_mid = _treemap_color(0.5)
    for c in (c0, c1, c_mid):
        assert isinstance(c, str)
        # plotly color string — "rgb(…)" 또는 "#…" 둘 다 허용
        assert c.startswith("#") or c.startswith("rgb")


def test_ri_unit_aggregates_signature():
    """_ri_unit_aggregates 가 빈 DataFrame 에서도 정상 동작 — (n_dict, vol_dict) 튜플 반환."""
    import pandas as pd
    from src.dashboard.tabs._tab22_helpers import _ri_unit_aggregates

    empty_m = pd.DataFrame(columns=["permit_no", "unit"])
    empty_u = pd.DataFrame(columns=["permit_no", "year", "month", "volume_m3"])
    n_dict, vol_dict = _ri_unit_aggregates(empty_m, empty_u, active_permits=None)
    assert isinstance(n_dict, dict)
    assert isinstance(vol_dict, dict)
    # 빈 입력이라 dict 도 비어 있어야 함
    assert len(n_dict) == 0
    assert len(vol_dict) == 0
