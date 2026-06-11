# ==============================================================================
#  파일명: src/dashboard/tabs/_tab04_charts.py
#  ④ 공간 분석 탭 — 12개월 차트/표 + 월별 통계 (관측정 디테일 + AWS 디테일 공용)
#
#  Source 분리: tab04_map.py 1055줄 → 그룹별 분리 2단계 (2026-05-09).
#    - _render_12month_chart       : 12개월 막대그래프 (실측 + 과거평균)
#    - _render_12month_table       : 12개월 가로 표 (실측/평균/편차 3행)
#    - _build_station_12month_table: 일자료 EL 을 (연월) 단위 월평균 + baseline
#    - _render_monthly_boxplot     : 최근 12개월 일자료 EL 박스플롯
#    - _render_monthly_stats_table : 월별 기초통계표 (평균/중앙/max/min/std/일수)
#
#  외부 사용처: tab04_map.py 내부 전용. underscore prefix.
# ==============================================================================
from __future__ import annotations

from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.analysis import aws_yearly
from src.dashboard import theme
from src.dashboard.tabs._tab04_helpers import _diff_html, _smart_period_labels


# ==============================================================================
#  ■ 12개월 차트 / 표 공용
# ==============================================================================
def _render_12month_chart(table: pd.DataFrame, metric_label: str, unit: str,
                            color: str, key: str, decimals: int = 1,
                            n_baseline: int = 5):
    if table.empty:
        st.info("12개월 데이터 없음.")
        return
    xs = _smart_period_labels(table)               # 요청 8·12: 연도 변경 칸만 YY 표시
    actual = [v if v is not None else None for v in table["실측"]]
    avg = [v if v is not None else None for v in table["평균"]]

    avg_legend = f"과거 {n_baseline}년 해당월 평균"   # 요청 12

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name=avg_legend, x=xs, y=avg,
        marker=dict(color=theme.hex_alpha(color, 0.18),
                    line=dict(color=color, width=1.5)),
        text=[(f"{v:.{decimals}f}" if v is not None else "") for v in avg],
        textposition="outside",
        textfont=dict(size=13, color=theme.COLOR_TEXT_SECONDARY),
        cliponaxis=False,
        hovertemplate=f"%{{x}}<br>{avg_legend}: %{{y:.{decimals}f}} {unit}<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        name=f"실측 {metric_label}", x=xs, y=actual,
        marker=dict(color=color),
        text=[(f"{v:.{decimals}f}" if v is not None else "") for v in actual],
        textposition="outside",
        textfont=dict(size=13, color=theme.COLOR_TEXT_PRIMARY),
        cliponaxis=False,
        hovertemplate=f"%{{x}}<br>실측: %{{y:.{decimals}f}} {unit}<extra></extra>",
    ))
    fig.update_layout(
        barmode="group", height=260,
        xaxis_title="", yaxis_title=unit,
        xaxis=dict(tickfont=dict(size=14), tickangle=0),
        bargap=0.25, bargroupgap=0.12,
        margin=dict(t=18, b=8, l=44, r=8),
        showlegend=True,
        legend=dict(orientation="h", yanchor="top", y=1.20,
                    xanchor="right", x=1.0, font=dict(size=14)),
        font=dict(size=14),
    )
    st.plotly_chart(fig, use_container_width=True, key=key)


def _render_12month_table(table: pd.DataFrame, unit: str = "mm",
                           decimals: int = 0, metric_label: str = "월강수량",
                           n_baseline: int = 5):
    """12개월 가로 표: 행=[실측/과거평균/편차], 열=12개월

    n_baseline : '과거 N년 평균' 행 라벨에 사용 (요청 7·11)
    """
    if table.empty:
        return
    th_pd = ('padding:5px 6px;background:var(--color-bg-secondary);text-align:center;'
             'border-bottom:1.5px solid #ccc;font-size:15px;font-weight:500;'
             'color:var(--color-text-secondary);')
    # 요청 12: 기간 헤더 셀(좌측 라벨 + 12개 월 라벨) 모두 중앙 정렬
    th_lbl = ('padding:5px 8px;background:var(--color-bg-secondary);text-align:center;'
              'border-bottom:1.5px solid #ccc;font-size:16px;font-weight:600;'
              'color:var(--color-text-primary);')

    period_labels = _smart_period_labels(table)

    head = (
        '<table style="width:100%;border-collapse:collapse;font-size:16px;table-layout:fixed;">'
        '<colgroup>'
        '<col style="width:160px;">'
        + ('<col>' * len(table))
        + '</colgroup>'
        '<thead><tr>'
        f'<th style="{th_lbl};text-align:center;">기간</th>'
    )
    for lbl in period_labels:
        head += f'<th style="{th_pd}">{lbl}</th>'
    head += '</tr></thead><tbody>'

    base_td = ('padding:5px 6px;border-bottom:0.5px solid #eee;text-align:center;'
               'font-size:16px;')
    label_td = ('padding:5px 8px;border-bottom:0.5px solid #eee;text-align:left;'
                'font-size:16px;color:var(--color-text-secondary);')

    def _fmt(v):
        return ("–" if v is None
                else (f"{int(round(v))}" if decimals == 0
                      else f"{v:.{decimals}f}"))

    # 행 1: 실측
    body = f'<tr><td style="{label_td};font-weight:500;color:var(--color-text-primary);">실측 {metric_label} ({unit})</td>'
    for _, r in table.iterrows():
        v = r["실측"]
        body += f'<td style="{base_td};font-weight:600;">{_fmt(v)}</td>'
    body += "</tr>"
    # 행 2: 과거 평균 (n_baseline 동적)
    body += (f'<tr><td style="{label_td};">'
             f'과거 {n_baseline}년 평균 ({unit})</td>')
    for _, r in table.iterrows():
        v = r["평균"]
        body += f'<td style="{base_td};color:var(--color-text-secondary);">{_fmt(v)}</td>'
    body += "</tr>"
    # 행 3: 편차
    body += f'<tr><td style="{label_td};">편차 ({unit})</td>'
    for _, r in table.iterrows():
        v = r["편차"]
        body += f'<td style="{base_td};">{_diff_html(v, unit="", decimals=decimals)}</td>'
    body += "</tr>"

    st.markdown(head + body + "</tbody></table>", unsafe_allow_html=True)


# ==============================================================================
#  ■ 관측정 12개월 표 (월말 EL + 직전 N년 동월 평균)
# ==============================================================================
def _build_station_12month_table(day_df: pd.DataFrame, base_date: date,
                                   n_baseline: int) -> pd.DataFrame:
    """
    일자료(EL)를 (연-월) 단위 **월평균** 으로 집계하고,
    각 (yr, mo)에 대해 직전 n_baseline 년 동월의 **월평균** 평균을 계산해 비교.

    v1.2.03: 월말EL fallback 제거 — 일자료의 산술평균만 사용 (요청 14).
    """
    if day_df.empty:
        return pd.DataFrame()

    df = day_df.copy()
    df["연월"] = df["날짜"].dt.strftime("%Y-%m")

    # 월별 산술평균 (일자료 EL 의 mean)
    monthly_mean = (df.groupby("연월")["EL"].mean()
                      .round(3).to_dict())

    rows = []
    for y, m in aws_yearly.last_12_months(base_date):
        ym = f"{y}-{m:02d}"
        actual = monthly_mean.get(ym)

        vals = []
        for by in range(y - n_baseline, y):
            v = monthly_mean.get(f"{by}-{m:02d}")
            if v is not None and pd.notna(v):
                vals.append(float(v))
        avg = float(sum(vals) / len(vals)) if vals else None
        diff = (actual - avg) if (actual is not None and avg is not None) else None
        rows.append({
            "연월": ym,
            "라벨": f"{m}월",
            "라벨_긴": f"{str(y)[2:]}년 {m}월",
            "실측": round(actual, 2) if actual is not None else None,
            "평균": round(avg, 2) if avg is not None else None,
            "편차": round(diff, 2) if diff is not None else None,
        })
    return pd.DataFrame(rows)


# ==============================================================================
#  ■ (요청 15) 최근 12개월 박스플롯
# ==============================================================================
def _render_monthly_boxplot(day_df: pd.DataFrame, base_date: date,
                              station_color: str, key: str) -> None:
    """직전 12개월의 월별 일자료 EL 분포를 박스플롯으로."""
    if day_df.empty:
        st.info("일자료 없음.")
        return
    df = day_df.copy()
    df["연월"] = df["날짜"].dt.strftime("%Y-%m")

    months = aws_yearly.last_12_months(base_date)
    yms = [f"{y}-{m:02d}" for y, m in months]
    sub = df[df["연월"].isin(yms)].copy()
    if sub.empty:
        st.info("최근 12개월 일자료 없음.")
        return

    # 라벨 매핑 (요청 8 형식)
    tmp = pd.DataFrame({"연월": yms})
    smart_labels = _smart_period_labels(tmp)
    label_map = dict(zip(yms, smart_labels))
    sub["라벨"] = sub["연월"].map(label_map)

    fig = go.Figure()
    fig.add_trace(go.Box(
        y=sub["EL"], x=sub["라벨"],
        marker=dict(color=station_color, size=3,
                    line=dict(width=0.5, color="#0e3a73")),
        line=dict(color="#0e3a73", width=1.2),
        fillcolor=theme.hex_alpha(station_color, 0.30),
        boxmean=True,           # 평균선 표시
        boxpoints="outliers",   # 이상치만 점으로
        hovertemplate="%{x}<br>EL: %{y:.2f} m<extra></extra>",
        name="EL",
    ))
    fig.update_layout(
        height=300,
        xaxis_title="", yaxis_title="EL (m)",
        xaxis=dict(categoryorder="array", categoryarray=smart_labels,
                   tickfont=dict(size=14)),
        yaxis=dict(tickfont=dict(size=13)),
        margin=dict(t=10, b=8, l=50, r=8),
        font=dict(size=14),
        showlegend=False,
    )
    st.plotly_chart(fig, use_container_width=True, key=key)


# ==============================================================================
#  ■ (요청 16) 최근 12개월 월별 기초통계표
# ==============================================================================
def _render_monthly_stats_table(day_df: pd.DataFrame, base_date: date) -> None:
    """일자료 기준 월별 (산술평균/중앙값/최대/최소/표준편차/일수) 표."""
    if day_df.empty:
        return
    df = day_df.copy()
    df["연월"] = df["날짜"].dt.strftime("%Y-%m")

    months = aws_yearly.last_12_months(base_date)
    yms = [f"{y}-{m:02d}" for y, m in months]

    stats_rows = []
    for ym in yms:
        sub = df[df["연월"] == ym]["EL"]
        if sub.empty:
            stats_rows.append((ym, None, None, None, None, None, 0))
        else:
            stats_rows.append((
                ym,
                round(float(sub.mean()), 2),
                round(float(sub.median()), 2),
                round(float(sub.max()), 2),
                round(float(sub.min()), 2),
                round(float(sub.std()), 3) if len(sub) > 1 else 0.0,
                int(len(sub)),
            ))

    tmp = pd.DataFrame({"연월": yms})
    smart_labels = _smart_period_labels(tmp)

    th = ('padding:6px 8px;background:var(--color-bg-secondary);text-align:center;'
          'border-bottom:1.5px solid #ccc;font-size:16px;font-weight:600;'
          'color:var(--color-text-primary);')
    td = ('padding:5px 6px;border-bottom:0.5px solid #eee;text-align:center;'
          'font-size:16px;')
    label_td = ('padding:5px 8px;border-bottom:0.5px solid #eee;text-align:center;'
                'font-size:16px;color:var(--color-text-secondary);')

    head = (
        '<table style="width:100%;border-collapse:collapse;font-size:16px;table-layout:fixed;">'
        '<colgroup><col style="width:160px;">'
        + ('<col>' * len(yms)) + '</colgroup>'
        '<thead><tr>'
        f'<th style="{th}">통계</th>'
    )
    for lbl in smart_labels:
        head += f'<th style="{th}">{lbl}</th>'
    head += '</tr></thead><tbody>'

    def _fmt(v, decimals=2):
        return "–" if v is None else f"{v:.{decimals}f}"

    metrics = [
        ("산술평균 (m)",   1),
        ("중앙값 (m)",     2),
        ("최대값 (m)",     3),
        ("최소값 (m)",     4),
        ("표준편차 (m)",   5),
        ("일수 (일)",      6),
    ]

    body = ""
    for label, idx in metrics:
        body += f'<tr><td style="{label_td};font-weight:500;color:var(--color-text-primary);">{label}</td>'
        for r in stats_rows:
            v = r[idx]
            if idx == 6:                 # 일수는 정수
                cell = "0" if v is None else f"{int(v)}"
            elif idx == 5:               # 표준편차 3자리
                cell = _fmt(v, 3)
            else:
                cell = _fmt(v, 2)
            body += f'<td style="{td};">{cell}</td>'
        body += "</tr>"

    st.markdown(head + body + "</tbody></table>", unsafe_allow_html=True)
