"""리·동 Dual-Zone (그림 24·25·26·27) — Plotly 인터랙티브 차트.

레이아웃(layout.py)·메트릭(metrics.py)·렌더러(renderer.py) 3계층으로 분리.
admin_dual_zone 의 패턴을 답습하되, 클러스터 슬롯 안에 5공 이상 리·동을
squarify 패킹한다.

  • render_ri: 그림 24(기본 색) / 그림 26(메타 라벨 4줄)
  • render_compare: 그림 25 — 좌·우 비교 (전체 / 200m 이하)
  • render_monthly: 그림 27 — 월별 12장 (monthly.py)
"""
from .metrics import RI_METRICS, MetricSpec
from .renderer import render_compare, render_ri

__all__ = ["render_ri", "render_compare", "RI_METRICS", "MetricSpec"]
