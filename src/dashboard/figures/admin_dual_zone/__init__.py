"""행정 구역 Dual-Zone (그림 23) — Plotly 인터랙티브 차트.

레이아웃(layout.py)·메트릭(metrics.py)·렌더러(renderer.py) 3계층으로 분리.
"""
from .metrics import METRICS, MetricSpec
from .renderer import render

__all__ = ["METRICS", "MetricSpec", "render"]
