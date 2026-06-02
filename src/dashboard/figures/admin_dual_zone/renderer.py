"""행정 구역 Dual-Zone Plotly Figure 빌더.

레이아웃(layout.build_layout)과 메트릭(metrics.METRICS)을 결합해
인터랙티브 plotly.graph_objects.Figure 를 생성한다.

설계:
  • 박스는 go.Scatter (mode='lines', fill='toself') 로 그려 — 면적 전체가 호버 가능
  • 각 박스 trace 의 customdata = [[cluster]]*5 → on_select 클릭 이벤트로
    클러스터 식별 가능
  • selected_cluster 인자로 강조 박스(굵은 테두리) 지정
  • 텍스트는 별도 mode='text' trace 3종 (이름 / 면적·관정수 / 메트릭 값)
  • 컬러바는 별도 더미 marker scatter trace
  • y 축은 scaleanchor 미사용 — 컨테이너 height 가 박스 높이 결정
  • 차트 타이틀은 plotly 가 아닌 streamlit 헤더가 담당 (시각 통일)
"""
from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd
import plotly.graph_objects as go

from .._dual_zone_common.color import (
    normalize_values,
    short_name,
    slot_color,
)
from .constants import ADMIN_AGRI_HA, CLUSTER_ASOS
from .data import aggregate_clusters, normalize_admin
from src.dashboard import theme
from .layout import Layout, Slot, build_layout
from .metrics import METRICS, MetricSpec


# 단위 텍스트 색상 — 본 값보다 시각적 강조 낮은 보조 라벨 (theme 토큰화 정책)
_UNIT_TEXT_COLOR = theme.COLOR_TEXT_SECONDARY


# ──────────────────────────────────────────────────────────────────
#  내부 유틸 — 색상화·정규화는 _dual_zone_common.color 에서 import
#  (분석팀 권고 2026-05-09, 1순위 DRY 통합)
# ──────────────────────────────────────────────────────────────────
def _wells_per_cluster(master: pd.DataFrame) -> pd.Series:
    return master.groupby("cluster").size()


# ──────────────────────────────────────────────────────────────────
#  공개 API
# ──────────────────────────────────────────────────────────────────
def render(master: pd.DataFrame, usage: pd.DataFrame, *,
           metric_key: str = "total_period",
           period_label: str | None = None,
           asos_annual: pd.Series | None = None,
           selected_cluster: str | None = None,
           height: int = 560,
           color_vmin: "float | None" = None,
           color_vmax: "float | None" = None,
           active_permits: "set[str] | None" = None,
           ) -> go.Figure:
    """행정 구역 Dual-Zone Plotly Figure 생성.

    Parameters
    ----------
    master, usage : DataFrame
        원본 또는 normalize_admin 결과 (cluster 컬럼 자동 보정).
    metric_key : str
        metrics.METRICS 의 키 (기본: total_period).
    period_label : str | None
        "2024년" 또는 "2018~2025년 합계" 같은 표기 — 메트릭에 따라 자동 노출.
    asos_annual : pd.Series | None
        관측소별 연평균 강수 mm (옵션, 호버에 표시).
    selected_cluster : str | None
        강조 표시할 클러스터(클릭으로 선택된 박스). 굵은 테두리로 시각화.
    height : int
        Plotly Figure 높이 (px).
    """
    if "cluster" not in master.columns or "cluster" not in usage.columns:
        master, usage = normalize_admin(master, usage)

    if metric_key not in METRICS:
        raise KeyError(f"unknown metric: {metric_key}")
    metric: MetricSpec = METRICS[metric_key]

    cluster_df = aggregate_clusters(master, usage,
                                    active_permits=active_permits)
    # 사용자 요청 2026-05-19: 박스 hover 의 N 도 사용 보고 관정 기준.
    if active_permits is not None:
        _m_for_n = master[master["permit_no"].astype(str).isin(active_permits)]
    else:
        _m_for_n = master
    well_n = _wells_per_cluster(_m_for_n)

    layout = build_layout()
    slots: tuple[Slot, ...] = layout.slots

    # ── 메트릭 값 추출 ────────────────────────────────────────────
    if metric.column not in cluster_df.columns:
        raise KeyError(
            f"metric column '{metric.column}' not in aggregate_clusters output: "
            f"{list(cluster_df.columns)}"
        )
    metric_series = cluster_df[metric.column]
    raw_values = [float(metric_series.get(s.cluster, np.nan)) for s in slots]
    norm_t, computed_vmin, computed_vmax = normalize_values(raw_values)
    # 우선순위: 외부 주입(color_vmin/vmax) > metric.absolute_* > computed.
    # per_well_daily 처럼 metric 정의에 absolute_* 가 명시된 경우 모든 호출처
    # 에서 자동으로 절대 도메인이 강제됨 (예: 800=navy 임계 유지).
    eff_vmin = color_vmin if color_vmin is not None else metric.absolute_vmin
    eff_vmax = color_vmax if color_vmax is not None else metric.absolute_vmax
    if eff_vmin is not None and eff_vmax is not None:
        vmin, vmax = float(eff_vmin), float(eff_vmax)
        # 외부/절대 vmin/vmax 가 결정되면 norm_t 도 새 범위 기준으로 재계산
        span = vmax - vmin
        if span > 0:
            norm_t = [
                max(0.0, min(1.0, (float(v) - vmin) / span))
                if not np.isnan(v) else 0.0
                for v in raw_values
            ]
        else:
            norm_t = [0.5 for _ in raw_values]
    else:
        vmin, vmax = computed_vmin, computed_vmax
    colors = [slot_color(t, metric.colorscale) for t in norm_t]

    fig = go.Figure()

    # 1) 박스 trace — 면 전체가 호버 가능 + customdata 로 클러스터 식별
    for slot, value, color in zip(slots, raw_values, colors):
        rain_part = ""
        if asos_annual is not None:
            asos_st = CLUSTER_ASOS.get(slot.cluster)
            if asos_st and asos_st in asos_annual.index:
                rain_part = (
                    f"<br>강수: {asos_st} "
                    f"{float(asos_annual[asos_st]):,.0f} mm/년"
                )
        hover = (
            f"<b>{slot.cluster}</b><br>"
            f"농지: {ADMIN_AGRI_HA[slot.cluster]:,} ha · "
            f"관정: {int(well_n.get(slot.cluster, 0)):,} 공<br>"
            f"{metric.label}: {metric.display(value)}"
            f"{rain_part}"
            f"<br><i>클릭하면 세부 분석이 표시됩니다</i>"
            f"<extra></extra>"
        )
        is_selected = (selected_cluster is not None
                       and selected_cluster == slot.cluster)
        line_color = theme.COLOR_TEXT_INFO if is_selected else "rgba(20,20,20,0.85)"
        line_width = 3.0 if is_selected else 0.7
        fig.add_trace(go.Scatter(
            x=[slot.x, slot.x1, slot.x1, slot.x, slot.x],
            y=[slot.y, slot.y, slot.y1, slot.y1, slot.y],
            mode="lines",
            fill="toself",
            fillcolor=color,
            line=dict(color=line_color, width=line_width),
            hoveron="fills",
            hovertemplate=hover,
            customdata=[[slot.cluster]] * 5,
            showlegend=False,
            name=slot.cluster,
        ))

    # 1.5) Click target trace — 박스 fill 영역 안쪽 클릭이 잡히도록 보강.
    # plotly Scatter mode="lines"+fill="toself" 는 line 위 5개 점에서만
    # selection 이벤트가 발생하고, fill 내부 클릭은 hover 만 동작한다.
    # 사용자가 박스 가운데를 클릭해도 detail 이 표시되도록 박스마다 4×4 그리드
    # = 16 개 invisible 마커를 깔아 어느 위치를 클릭해도 가까운 마커가 selection
    # 으로 잡히게 한다 (사용자 보고 2026-05-10: 박스 클릭 무반응).
    click_xs: list[float] = []
    click_ys: list[float] = []
    click_cd: list[list[str]] = []
    for slot in slots:
        for i in range(4):
            for j in range(4):
                click_xs.append(slot.x + slot.width * (i + 0.5) / 4.0)
                click_ys.append(slot.y + slot.height * (j + 0.5) / 4.0)
                click_cd.append([slot.cluster])
    fig.add_trace(go.Scatter(
        x=click_xs, y=click_ys,
        mode="markers",
        marker=dict(size=22, color="rgba(0,0,0,0)", opacity=0,
                    line=dict(width=0)),
        customdata=click_cd,
        hoverinfo="skip",
        showlegend=False,
        name="_click_targets",
    ))

    # 2) 텍스트 trace 3종 — 한 trace 당 12개 포인트 (값은 숫자<br>단위 두 줄)
    cx = [s.cx for s in slots]
    name_y = [s.y1 - s.height * 0.16 for s in slots]
    mid_y = [s.cy + s.height * 0.05 for s in slots]
    val_y = [s.y + s.height * 0.22 for s in slots]

    fig.add_trace(go.Scatter(
        x=cx, y=name_y,
        text=[f"<b>{short_name(s.cluster)}</b>" for s in slots],
        mode="text",
        textfont=dict(size=17, color=theme.COLOR_TEXT_PRIMARY,
                      family="Arial Black, sans-serif"),
        hoverinfo="skip", showlegend=False,
    ))
    fig.add_trace(go.Scatter(
        x=cx, y=mid_y,
        text=[f"{ADMIN_AGRI_HA[s.cluster]:,} ha · "
              f"{int(well_n.get(s.cluster, 0))} 공" for s in slots],
        mode="text",
        textfont=dict(size=13, color=theme.COLOR_TEXT_PRIMARY),
        hoverinfo="skip", showlegend=False,
    ))
    val_texts = []
    for v in raw_values:
        num_part, unit_part = metric.display_parts(v)
        val_texts.append(
            f"{num_part}<br>"
            f"<span style='font-size:10px;color:{_UNIT_TEXT_COLOR}'>{unit_part}</span>"
        )
    fig.add_trace(go.Scatter(
        x=cx, y=val_y,
        text=val_texts,
        mode="text",
        textfont=dict(size=12.5, color=theme.COLOR_TEXT_PRIMARY),
        hoverinfo="skip", showlegend=False,
    ))

    # 3) 시 라벨
    fig.add_annotation(x=layout.x_max / 2, y=layout.j_y1 + 0.35,
                       text="<b>제주시</b>", showarrow=False,
                       font=dict(size=20, color=theme.COLOR_ACCENT_NAVY),
                       xanchor="center", yanchor="bottom")
    fig.add_annotation(x=layout.x_max / 2, y=layout.s_y0 - 0.35,
                       text="<b>서귀포시</b>", showarrow=False,
                       font=dict(size=20, color=theme.COLOR_ACCENT_NAVY),
                       xanchor="center", yanchor="top")

    # 4) 컬러바 — 데이터 없는 더미 marker scatter
    fig.add_trace(go.Scatter(
        x=[None], y=[None],
        mode="markers",
        marker=dict(
            colorscale=metric.colorscale,
            cmin=vmin, cmax=vmax,
            color=[vmin],
            size=0.0001,
            colorbar=dict(
                title=dict(text=metric.colorbar_title(period_label),
                           side="right"),
                thickness=14, len=0.78, x=1.02,
            ),
        ),
        hoverinfo="skip", showlegend=False,
    ))

    # 5) 축·레이아웃 — scaleanchor 미사용 (height 가 박스 높이 결정)
    # 사용자 요청 2026-05-10: '제주시'/'서귀포시' annotation 위·아래 빈공간
    # 최소화. yaxis 여백 1.2 → 0.65 (annotation +0.35 위치 + size=20 폰트
    # line-height 클립 방지 0.30), figure margin t/b 20 → 4.
    fig.update_xaxes(range=[layout.x_min - 1, layout.x_max + 1],
                     visible=False, fixedrange=True)
    fig.update_yaxes(range=[layout.s_y0 - 0.65, layout.j_y1 + 0.65],
                     visible=False, fixedrange=True)

    fig.update_layout(
        title=dict(text=""),
        height=height,
        margin=dict(l=10, r=130, t=4, b=4),
        plot_bgcolor="white",
        paper_bgcolor="white",
        hoverlabel=dict(bgcolor="white", font_size=15,
                        bordercolor="rgba(26,26,24,0.30)"),
        font=dict(family="-apple-system, BlinkMacSystemFont, 'Segoe UI', "
                         "Roboto, sans-serif",
                  color=theme.COLOR_TEXT_PRIMARY),
    )
    return fig
