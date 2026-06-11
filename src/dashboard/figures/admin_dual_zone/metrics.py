"""행정 구역 Dual-Zone 색·텍스트 매핑 메트릭 카탈로그.

Layout(외부 박스)은 그대로 유지하면서 색에 비추는 값을 자유롭게 교체.
새 지표 추가 시 METRICS dict에 MetricSpec 항목을 한 줄 추가하면 끝.

MetricSpec 클래스 자체는 _dual_zone_common.metrics 와 공용 (3순위 DRY 통합,
2026-05-09). 호환성을 위해 이 모듈에서 re-export — admin_dual_zone.renderer
의 `from .metrics import MetricSpec` import 가 깨지지 않음.
"""
from __future__ import annotations

import pandas as pd

from .._dual_zone_common.color import (
    DAILY_USAGE_COLORSCALE,
    DAILY_USAGE_VMAX,
    DAILY_USAGE_VMAX_MONTHLY,
    DAILY_USAGE_VMIN,
)
from .._dual_zone_common.metrics import MetricSpec  # re-export
from .constants import ADMIN_AGRI_HA


METRICS: dict[str, MetricSpec] = {
    "total_period": MetricSpec(
        key="total_period",
        label="이용량 합계",
        unit="㎥",
        description="선택 기간 동안 행정구역 전체에서 양수된 누적 지하수량.",
        column="total_period",
        scale=1e6,
        scale_suffix="백만",
        fmt="{:,.1f}",
        colorscale="RdYlBu_r",
        period_aware=True,
    ),
    "annual": MetricSpec(
        key="annual",
        label="연 평균 이용량 합계",
        unit="㎥/년",
        description="선택 기간의 연평균 지하수 이용량 — 기간 합계 ÷ 기간(년).",
        column="annual",
        scale=1e6,
        scale_suffix="백만",
        fmt="{:,.1f}",
        colorscale="RdYlBu_r",
        period_aware=False,
    ),
    "per_well_annual": MetricSpec(
        key="per_well_annual",
        label="관정당 연 이용량",
        unit="㎥/공·년",
        description="기간 합계 ÷ 관정수 ÷ 기간(년) — 관정 1개의 연간 이용량.",
        column="per_well_annual",
        scale=1.0,
        fmt="{:,.0f}",
        colorscale="RdYlBu_r",
        period_aware=False,
    ),
    "per_well_monthly": MetricSpec(
        key="per_well_monthly",
        label="관정당 월 이용량",
        unit="㎥/공·월",
        description="기간 합계 ÷ 관정수 ÷ 기간(월) — 관정 1개의 월간 이용량.",
        column="per_well_monthly",
        scale=1.0,
        fmt="{:,.0f}",
        # 사용자 정책 (2026-05-22): per_well_daily × 30 = 48000 절대 도메인
        # 강제 → 일/월 단위 두 시각화가 동일 색 계조 공유.
        colorscale=DAILY_USAGE_COLORSCALE,
        period_aware=False,
        absolute_vmin=DAILY_USAGE_VMIN,
        absolute_vmax=DAILY_USAGE_VMAX_MONTHLY,
    ),
    "per_well_daily": MetricSpec(
        key="per_well_daily",
        label="관정당 일 이용량",
        unit="㎥/공·일",
        description="기간 합계 ÷ 관정수 ÷ 기간(일) — 관정 1개의 일간 이용량.",
        column="per_well_daily",
        scale=1.0,
        fmt="{:,.1f}",
        # 사용자 요청 (2026-05-15): 0=하늘, 800=남색, 1200=노랑, 1600+=빨강.
        # cmin=0/cmax=1600 절대값 고정과 함께 사용 (_dual_zone_common.color 의
        # DAILY_USAGE_VMIN/VMAX 가 단일 진실 원천).
        colorscale=DAILY_USAGE_COLORSCALE,
        period_aware=False,
        absolute_vmin=DAILY_USAGE_VMIN,
        absolute_vmax=DAILY_USAGE_VMAX,
    ),
    "intensity_ha": MetricSpec(
        key="intensity_ha",
        label="단위 면적 강도",
        unit="㎥/ha·년",
        description=(
            "단위 면적 강도 = 연평균 이용량 ÷ 농지면적(ha) — "
            "농지 1ha당 연간 지하수 사용량. 강도가 높을수록 단위 농지가 "
            "더 많은 지하수에 의존."
        ),
        column="intensity_ha",
        scale=1.0,
        fmt="{:,.0f}",
        # 사용자 요청 (2026-05-16): per_well_daily 와 같은 톤. fig25 도 동일.
        colorscale=DAILY_USAGE_COLORSCALE,
        period_aware=False,
    ),
    "n_wells": MetricSpec(
        key="n_wells",
        label="관정 수",
        unit="공",
        description="행정구역 내 활성 농업용 관정 수.",
        column="n",
        scale=1.0,
        fmt="{:,.0f}",
        colorscale="RdYlBu_r",
        period_aware=False,
    ),
}


# ──────────────────────────────────────────────────────────────────
#  헬퍼
# ──────────────────────────────────────────────────────────────────
def get(key: str) -> MetricSpec:
    if key not in METRICS:
        raise KeyError(f"unknown metric: {key} (available: {list(METRICS)})")
    return METRICS[key]


def labels() -> dict[str, str]:
    """selectbox용 {key: label} 매핑."""
    return {k: m.label for k, m in METRICS.items()}
