"""리·동 Dual-Zone 메트릭 카탈로그.

`aggregate_units` 결과의 컬럼을 색·텍스트로 매핑한다.

MetricSpec 클래스 자체는 _dual_zone_common.metrics 와 공용 (3순위 DRY 통합,
2026-05-09) — 이전엔 admin 과 거의 동일한 클래스를 두 곳에 정의했으나 이제
공용 모듈에서 import. ri 의 메트릭 정의에서는 `pct_clip=(5, 95)` 필드를
명시해 fig24·26 의 vmin/vmax 가 5/95% 분위수 클립을 사용하도록 한다 (admin
은 pct_clip 미지정으로 단순 min/max 사용).

호환성: 이 모듈에서 MetricSpec 을 re-export — ri_dual_zone.renderer 의
`from .metrics import MetricSpec` import 가 깨지지 않음.
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


# ──────────────────────────────────────────────────────────────────
#  카탈로그
# ──────────────────────────────────────────────────────────────────
RI_METRICS: dict[str, MetricSpec] = {
    "total_period": MetricSpec(
        key="total_period",
        label="이용량 합계",
        unit="㎥",
        description="선택 기간 동안 리·동 전체에서 양수된 누적 지하수량.",
        column="total_period",
        scale=1e6,
        scale_suffix="백만",
        fmt="{:,.2f}",
        colorscale="RdYlBu_r",
        period_aware=True,
        pct_clip=(5, 95),
    ),
    "annual": MetricSpec(
        key="annual",
        label="연 평균 이용량 합계",
        unit="㎥/년",
        description="선택 기간의 연평균 지하수 이용량 — 기간 합계 ÷ 기간(년).",
        column="annual",
        scale=1e6,
        scale_suffix="백만",
        fmt="{:,.2f}",
        colorscale="RdYlBu_r",
        period_aware=False,
        pct_clip=(5, 95),
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
        pct_clip=(5, 95),
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
        # 강제 → 일/월 단위 두 시각화가 동일 색 계조 공유. fig24/fig26 등.
        colorscale=DAILY_USAGE_COLORSCALE,
        period_aware=False,
        pct_clip=(5, 95),
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
        # admin_dual_zone/metrics.py 의 per_well_daily 와 단일 진실 원천 공유.
        colorscale=DAILY_USAGE_COLORSCALE,
        period_aware=False,
        pct_clip=(5, 95),
        absolute_vmin=DAILY_USAGE_VMIN,
        absolute_vmax=DAILY_USAGE_VMAX,
    ),
    "intensity_ha": MetricSpec(
        key="intensity_ha",
        # admin (클러스터 전체 농지로 나눔) 과 분모 정의가 다르므로 라벨에
        # "(안분)" 명시 — ri 는 ADMIN_AGRI_HA × 관정수비율 로 추정 면적 사용.
        label="단위 면적 강도 (안분)",
        unit="㎥/ha·년",
        description=(
            "단위 면적 강도 = 연평균 이용량 ÷ 추정 농지면적(ha) — "
            "농지 1ha당 연간 지하수 사용량. 추정 면적은 클러스터 전체 농지를 "
            "관정 수 비율로 리·동에 안분한 값이라, 같은 행정구역의 admin "
            "지표와 정의가 다름."
        ),
        column="intensity_ha",
        scale=1.0,
        fmt="{:,.0f}",
        # 사용자 요청 (2026-05-16): per_well_daily 와 같은 톤.
        colorscale=DAILY_USAGE_COLORSCALE,
        period_aware=False,
        pct_clip=(5, 95),
    ),
    "n": MetricSpec(
        key="n",
        label="관정 수",
        unit="공",
        description="리·동 내 활성 농업용 관정 수.",
        column="n",
        scale=1.0,
        fmt="{:,.0f}",
        colorscale="RdYlBu_r",
        period_aware=False,
        pct_clip=None,    # 정수 카운트 — outlier 클립 불필요
    ),
}


def get(key: str) -> MetricSpec:
    if key not in RI_METRICS:
        raise KeyError(f"unknown metric: {key} (available: {list(RI_METRICS)})")
    return RI_METRICS[key]


def labels() -> dict[str, str]:
    return {k: m.label for k, m in RI_METRICS.items()}


__all__ = ["MetricSpec", "RI_METRICS", "get", "labels"]
