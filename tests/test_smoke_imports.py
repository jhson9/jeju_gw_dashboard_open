# ==============================================================================
#  파일명: tests/test_smoke_imports.py
#  목적: 모든 핵심 모듈이 import 가능한지 smoke 검증.
#       V4 권장(2026-05-11) — feedback_split_module_verify_runtime 정책 실행:
#       import 자체는 OK 지만 함수 실행 시 NameError 사고 방지.
# ==============================================================================
import importlib
import warnings

import pytest


@pytest.mark.parametrize(
    "module_path",
    [
        # 분석 계층
        "src.analysis.ag_well_loader",
        "src.analysis.ag_well_metrics",
        "src.analysis.anomaly_detection",
        "src.analysis.period_calculator",
        "src.analysis.effective_rainfall",
        "src.analysis.watershed_mapper",
        # 수집 계층
        "src.collectors.asos_collector",
        "src.collectors.gwlevel_parser",
        "src.collectors.gwlevel_day_parser",
        # 대시보드 공용
        "src.dashboard.theme",
        "src.dashboard.map_helpers",
        "src.dashboard.ag_well_helpers",
        "src.dashboard.ag_filters",
        "src.dashboard.permit_lookup",
        "src.dashboard.usage_detail_helpers",
        # figures
        "src.dashboard.figures.admin_dual_zone.renderer",
        "src.dashboard.figures.ri_dual_zone.renderer",
        "src.dashboard.figures.ri_dual_zone.monthly",
    ],
)
def test_module_importable(module_path: str):
    # streamlit "No runtime found" 경고는 bare mode 정상 출력 — 무시
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        mod = importlib.import_module(module_path)
    assert mod is not None
