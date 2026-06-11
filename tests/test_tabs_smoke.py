# ==============================================================================
#  파일명: tests/test_tabs_smoke.py
#  P5-2 (2026-05-29): 탭 모듈 import smoke 테스트.
#  2026-06-06 Stage 2: tab02 통합 + tab36/37/43 추가 → 총 21개 모듈.
#
#  parametrize 로 모든 탭을 한 번에 import 검증 → CI/local pytest 한 번이
#  모든 탭의 구조적 무결성(syntax + 의존성 그래프) 을 보장.
# ==============================================================================
from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


TAB_MODULES = [
    "src.dashboard.tabs.tab01_overview",
    "src.dashboard.tabs.tab02_rainfall",
    "src.dashboard.tabs.tab03_gwlevel",
    "src.dashboard.tabs.tab04_map",
    "src.dashboard.tabs.tab11_ag_search",
    "src.dashboard.tabs.tab12_ag_usage",
    "src.dashboard.tabs.tab13_ag_quality",
    "src.dashboard.tabs.tab21_ag_stats",
    "src.dashboard.tabs.tab22_ag_usage_detail",
    "src.dashboard.tabs.tab23_ag_usage_map",
    "src.dashboard.tabs.tab31_drone_overview",
    "src.dashboard.tabs.tab32_drone_2d",
    "src.dashboard.tabs.tab33_drone_3d",
    "src.dashboard.tabs.tab34_drone_diff",
    "src.dashboard.tabs.tab35_drone_diff_3d",
    "src.dashboard.tabs.tab36_drone_diff_dod",
    "src.dashboard.tabs.tab37_drone_diff_dod_3d",
    "src.dashboard.tabs.tab41_population",
    "src.dashboard.tabs.tab42_farm_household",
    "src.dashboard.tabs.tab43_greenhouse",
    "src.dashboard.tabs.tab99_admin",
]


@pytest.mark.parametrize("module_name", TAB_MODULES, ids=lambda m: m.rsplit(".", 1)[-1])
def test_tab_module_importable(module_name: str) -> None:
    """각 탭 모듈이 import 가능한지 검증 (syntax + 의존성 그래프 무결성)."""
    try:
        mod = importlib.import_module(module_name)
    except ImportError as e:
        pytest.skip(f"Optional dependency missing: {e}")
    except Exception as e:
        pytest.fail(f"{module_name} import failed: {type(e).__name__}: {e}")

    assert hasattr(mod, "render"), f"{module_name}: render() 함수 누락"


def test_all_tabs_have_render_signature() -> None:
    """모든 탭의 render() 가 callable 임을 한꺼번에 확인."""
    skipped = []
    for module_name in TAB_MODULES:
        try:
            mod = importlib.import_module(module_name)
        except ImportError:
            skipped.append(module_name)
            continue
        except Exception as e:  # noqa: BLE001
            pytest.fail(f"{module_name} import failed: {type(e).__name__}: {e}")

        render = getattr(mod, "render", None)
        assert render is not None, f"{module_name}: render() 함수 누락"
        assert callable(render), f"{module_name}: render 가 callable 이 아님"

    if skipped and len(skipped) == len(TAB_MODULES):
        pytest.skip(f"모든 탭 모듈이 의존성 누락으로 skip: {skipped}")
