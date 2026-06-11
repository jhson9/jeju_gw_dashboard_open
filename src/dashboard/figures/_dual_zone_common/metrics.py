# ==============================================================================
#  파일명: src/dashboard/figures/_dual_zone_common/metrics.py
#  공용: admin/ri MetricSpec 데이터 클래스 (3순위 DRY 통합)
# ------------------------------------------------------------------------------
#  추출 출처:
#    - admin_dual_zone/metrics.py L16-46  MetricSpec (11개 필드)
#    - ri_dual_zone/metrics.py    L17-53  MetricSpec (11개 필드 + pct_clip)
#
#  통합 동작:
#    - 공용 MetricSpec 에 pct_clip 옵션 필드 추가 (default=None).
#    - admin 카탈로그는 pct_clip 미사용 → admin renderer 가 normalize_values()
#      를 pct_clip 인자 없이 호출하므로 영향 없음.
#    - ri 카탈로그는 pct_clip=(5, 95) 명시 → ri renderer 가 vmin_vmax(metric.pct_clip)
#      호출 시 그대로 적용.
# ==============================================================================
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class MetricSpec:
    """1개 지표 정의 — admin·ri 양쪽 공용."""
    key: str                                  # 식별자
    label: str                                # 사용자 노출 한글 라벨
    unit: str                                 # 단위 표기 (㎥, ㎥/공, …)
    description: str                          # selectbox 도움말
    column: str                               # aggregate 결과의 컬럼명
    scale: float = 1.0                        # 표시 스케일 (1e6 → 백만 단위)
    scale_suffix: str = ""                    # 스케일 적용 시 단위 prefix (예: "백만")
    fmt: str = "{:,.1f}"                      # 표시 포맷 (스케일 적용 후 값)
    colorscale: str = "RdYlBu_r"              # plotly colorscale
    period_aware: bool = False                # period_label 을 라벨에 포함할지
    pct_clip: "tuple[int, int] | None" = None # outlier 클립 분위수 (ri 전용)
    # 절대 도메인 강제 — None 이면 renderer 가 raw_values 분포로 자동 정규화.
    # per_well_daily 처럼 색·임계가 절대값 의미(예: navy=800)인 metric 만 지정.
    absolute_vmin: "float | None" = None
    absolute_vmax: "float | None" = None

    def display(self, value: float) -> str:
        if pd.isna(value):
            return "—"
        v = value / self.scale if self.scale != 1.0 else value
        return f"{self.fmt.format(v)}{self.scale_suffix}{self.unit}"

    def display_parts(self, value: float) -> tuple:
        """숫자부·단위부 분리 — 박스 두 줄 표기용.

        예) (12.3 ㎥/공·년) → ("12.3", "㎥/공·년")
            (1.2백만㎥)     → ("1.2백만", "㎥")
        """
        if pd.isna(value):
            return ("—", "")
        v = value / self.scale if self.scale != 1.0 else value
        num = f"{self.fmt.format(v)}{self.scale_suffix}"
        return (num, self.unit)

    def colorbar_title(self, period_label: "str | None") -> str:
        head = f"{period_label} " if (self.period_aware and period_label) else ""
        unit = (
            f"({self.scale_suffix}{self.unit})"
            if (self.unit or self.scale_suffix)
            else ""
        )
        return f"{head}{self.label} {unit}".strip()
