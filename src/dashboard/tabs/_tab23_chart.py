# ==============================================================================
#  파일명: src/dashboard/tabs/_tab23_chart.py
#  ⑧-2 이용량 지도분석 — 월별 12개 막대 차트 (관정당 일 사용량)
#
#  설계:
#    - render_monthly_chart : plotly bar (㎥/관정/일)
#    - hover: "n월: v ㎥/관정/일 (분모 N_pop공 · 그 월 실가동 n_active공)"
#    - 색상: config.AG_PALETTE["agriculture"] (#548235)
#    - NaN/None 값(분석기간 그 월 부재) 은 막대 0 + hover '자료 없음'
#
#  외부 사용처: tab23_ag_usage_map.py 전용.
# ==============================================================================
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

import config
from src.dashboard import theme


_MONTH_LABELS = ["1월", "2월", "3월", "4월", "5월", "6월",
                 "7월", "8월", "9월", "10월", "11월", "12월"]


def render_monthly_chart(chart_data: dict, period_label: str) -> None:
    """월별 12개 막대 차트 렌더.

    Parameters
    ----------
    chart_data : dict (chart_monthly_per_well 반환)
      - x: list[int] 1~12
      - y: list[float|None] (㎥/관정/일)
      - n_active: list[int] 12 (hover 보조)
      - n_pop: int
      - days_per_month: list[float] 12
    period_label : 분석기간 라벨 (caption 표시용)
    """
    y_raw = chart_data.get("y", [None] * 12)
    n_act = chart_data.get("n_active", [0] * 12)
    n_pop = int(chart_data.get("n_pop", 0))

    # None → 0 (표시), 단 hover 에서 '자료 없음' 안내
    y_plot = [0.0 if v is None else float(v) for v in y_raw]
    hover_texts = []
    for i, v in enumerate(y_raw):
        m = i + 1
        if v is None:
            hover_texts.append(
                f"<b>{m}월</b><br>자료 없음 (분석기간에 이 월 자료 없음)<extra></extra>"
            )
        else:
            hover_texts.append(
                f"<b>{m}월</b><br>"
                f"<b>{v:.2f}</b> ㎥/공/일<br>"
                f"분모(모집단) {n_pop}공<br>"
                f"그 월 실가동 {n_act[i]}공<extra></extra>"
            )

    bar_color = config.AG_PALETTE.get("agriculture", "#548235")
    # 자료 없음 막대는 회색
    colors = [bar_color if v is not None else "#BFC6CB" for v in y_raw]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=_MONTH_LABELS,
        y=y_plot,
        marker_color=colors,
        hovertemplate=hover_texts,
        text=[f"{v:.1f}" if v is not None and v > 0 else "" for v in y_raw],
        textposition="outside",
        cliponaxis=False,
    ))
    # theme.standard_layout 이 이미 (height, margin, font, plot_bgcolor,
    # paper_bgcolor, showlegend) 6키를 반환 — 같은 key 를 우리 update_layout
    # kwargs 에 또 전달하면 TypeError("got multiple values"). 차트 전용 override
    # 는 standard_layout 의 keyword 인자로 일원화.
    layout = theme.standard_layout(
        height=320,
        margin_t=30, margin_b=40, margin_l=40, margin_r=20,
        showlegend=False,
    )
    fig.update_layout(
        **layout,
        xaxis=dict(title="", tickfont=dict(size=13)),
        yaxis=dict(title="㎥ / 관정 / 일", tickfont=dict(size=12),
                   gridcolor="rgba(0,0,0,0.06)"),
        bargap=0.25,
    )
    st.markdown(
        f'<div style="font-size:13px;color:var(--color-text-secondary);'
        f'margin-bottom:4px;">분석기간: <b style="color:var(--color-text-info);">'
        f'{period_label}</b> · 분모(모집단) {n_pop}공 고정</div>',
        unsafe_allow_html=True,
    )
    st.plotly_chart(fig, use_container_width=True,
                    config={"displayModeBar": False})
