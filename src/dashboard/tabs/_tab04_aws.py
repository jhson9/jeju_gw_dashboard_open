# ==============================================================================
#  파일명: src/dashboard/tabs/_tab04_aws.py
#  ④ 공간 분석 탭 — AWS (기상관측소) 디테일 렌더
#
#  Source 분리: tab04_map.py 1055줄 → 그룹별 분리 3단계 (2026-05-09).
#    - _render_aws_detail : AWS 마커 클릭 시 12개월 강수량/유효강수일수 +
#                            10년+ 일별/월별 강수 추이 + 농업유효 차트
#
#  외부 사용처: tab04_map.py 내부 전용 (render() 가 호출). underscore prefix.
# ==============================================================================
from __future__ import annotations

from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import config
from src.analysis import effective_rainfall, aws_yearly
from src.dashboard import theme
from src.dashboard.tabs._tab04_helpers import _baseline_footnote
from src.dashboard.tabs._tab04_charts import (
    _render_12month_chart,
    _render_12month_table,
)


# ==============================================================================
#  ■ AWS 상세
# ==============================================================================
def _render_aws_detail(aws_name: str, asos_df: pd.DataFrame, base_date: date):
    aws = next((s for s in config.STATIONS_ASOS if s["name"] == aws_name), None)
    if aws is None:
        st.warning(f"AWS 정보 없음: {aws_name}")
        return
    color = aws["color"]

    st.markdown(
        f'<p style="font-size:15px;color:var(--color-text-secondary);margin:0;letter-spacing:0.06em;">'
        f'AWS 분석</p>'
        f'<h3 style="font-size:18px;font-weight:600;margin:0 0 8px;color:{color};">'
        f'🌧 {aws_name} <span style="font-size:16px;font-weight:400;color:var(--color-text-secondary);">'
        f'(지점코드 {aws["id"]})</span></h3>',
        unsafe_allow_html=True,
    )

    if asos_df is None or asos_df.empty:
        st.info("ASOS 데이터가 없습니다. ⚙️ 데이터 탭에서 수집하세요.")
        return

    n_rain = config.RAINFALL_BASELINE_YEARS  # 5

    # ── 12개월 강수량 ──
    rain_table = aws_yearly.build_12month_table(
        asos_df, aws_name, base_date, metric="월강수량(mm)",
        n_baseline=n_rain)
    st.markdown(
        f'<p class="section-title" style="margin:0 0 4px;">'
        f'월별 강수량 — 직전 12개월 (mm)</p>',
        unsafe_allow_html=True,
    )
    _render_12month_chart(rain_table, "강수량", "mm", color,
                           key=f"t5_aws_rain_{aws_name}", decimals=0,
                           n_baseline=n_rain)

    st.markdown("<div style='height:6px;'></div>", unsafe_allow_html=True)
    st.markdown(
        f'<p class="section-title" style="margin:0 0 4px;">'
        f'강수량 비교표 — 직전 12개월 (mm)</p>',
        unsafe_allow_html=True,
    )
    _render_12month_table(rain_table, unit="mm", decimals=0,
                           metric_label="월강수량", n_baseline=n_rain)
    # 요청 13: 강수량 비교표 각주
    st.markdown(
        f'<p style="font-size:14px;color:var(--color-text-secondary);margin:4px 0 0;">'
        f'{_baseline_footnote(rain_table, n_rain, label="과거 N년 평균")}</p>',
        unsafe_allow_html=True,
    )

    st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)

    # ── 12개월 유효강수일수 (차트만) ──
    # v1.2.09: 비교표는 10년+ 농업유효 차트 바로 위로 이동 (요청 5)
    eff_table = aws_yearly.build_12month_table(
        asos_df, aws_name, base_date, metric="유효강수일수(일)",
        n_baseline=n_rain)
    st.markdown(
        f'<p class="section-title" style="margin:0 0 4px;">'
        f'월별 농업유효 강수일수 — 직전 12개월 (일)</p>'
        f'<p style="font-size:14px;color:var(--color-text-secondary);margin:0 0 4px;">'
        f'기준: 일강수량 {config.EFFECTIVE_RAINFALL_THRESHOLD_MM} mm 이상</p>',
        unsafe_allow_html=True,
    )
    _render_12month_chart(eff_table, "유효강수일수", "일", color,
                           key=f"t5_aws_eff_{aws_name}", decimals=0,
                           n_baseline=n_rain)

    st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)

    # ── 10년+ 범위 섹션: 시작월 드롭다운 (3개 차트 공유) ──
    monthly = effective_rainfall.aggregate_monthly(asos_df)
    df_m = monthly[monthly["지점명"] == aws_name].copy()
    if df_m.empty:
        st.info("지점 월별 자료 없음.")
        return

    df_m = df_m.sort_values("연월").reset_index(drop=True)
    earliest_ym = df_m["연월"].iloc[0]
    latest_ym = df_m["연월"].iloc[-1]
    all_months = df_m["연월"].tolist()
    default_ym = f"{base_date.year - 10}-01"
    default_idx = all_months.index(default_ym) if default_ym in all_months else 0

    h1, h2 = st.columns([2.0, 1.0])
    with h1:
        st.markdown(
            f'<p class="section-title" style="margin:0;'
            f'padding:6px 0;">10년+ 범위 분석 — {aws_name}</p>',
            unsafe_allow_html=True,
        )
    with h2:
        start_ym = st.selectbox(
            "시작월", all_months,
            index=default_idx,
            key=f"t5_aws_10y_start_{aws_name}",
            label_visibility="collapsed",
        )

    plot = df_m[(df_m["연월"] >= start_ym)].copy()
    if plot.empty:
        st.info("선택 범위 내 데이터 없음.")
        return

    # ── ① 일별 강수량 추이 (요청 4: NEW — 월별 차트 위에 위치) ──
    sy, sm = int(start_ym[:4]), int(start_ym[5:7])
    start_dt = pd.Timestamp(year=sy, month=sm, day=1)
    daily = asos_df[(asos_df["지점명"] == aws_name)
                    & (asos_df["일시"] >= start_dt)].copy()
    daily = daily.sort_values("일시")

    st.markdown(
        f'<p class="section-title" style="margin:0 0 4px;">'
        f'일별 강수량 추이 — {aws_name} (10년+ 범위)</p>',
        unsafe_allow_html=True,
    )
    fig_d = go.Figure()
    fig_d.add_trace(go.Bar(
        x=daily["일시"], y=daily["일강수량(mm)"],
        marker=dict(color=theme.hex_alpha(color, 0.95),
                    line=dict(color=color, width=0.05)),
        hovertemplate="%{x|%Y-%m-%d}<br>%{y:.1f} mm<extra></extra>",
    ))
    fig_d.update_layout(
        height=240,
        xaxis_title="", yaxis_title="일강수량 (mm)",
        margin=dict(t=8, b=8, l=50, r=10),
        font=dict(size=14),
        showlegend=False,
        bargap=0,
        yaxis=dict(rangemode="tozero"),
    )
    st.plotly_chart(fig_d, use_container_width=True,
                    key=f"t5_aws_10y_daily_{aws_name}")

    # ── ② 월별 강수량 추이 ──
    st.markdown(
        f'<p class="section-title" style="margin:8px 0 4px;">'
        f'월별 강수량 추이 — {aws_name} (10년+ 범위)</p>',
        unsafe_allow_html=True,
    )
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=plot["연월"], y=plot["월강수량(mm)"],
        marker=dict(color=theme.hex_alpha(color, 0.85),
                    line=dict(color=color, width=0.5)),
        hovertemplate="%{x}<br>%{y:.0f} mm<extra></extra>",
    ))
    fig.update_layout(
        height=300,
        xaxis_title="", yaxis_title="월강수량 (mm)",
        margin=dict(t=8, b=8, l=50, r=10),
        font=dict(size=14),
        showlegend=False,
        bargap=0.1,
    )
    st.plotly_chart(fig, use_container_width=True,
                    key=f"t5_aws_10y_{aws_name}")
    st.markdown(
        f'<p style="font-size:14px;color:var(--color-text-secondary);margin:0;">'
        f'데이터 전체 범위: {earliest_ym} ~ {latest_ym} '
        f'&nbsp;|&nbsp; 총 {len(df_m)}개월 (선택 표시: {len(plot)}개월) '
        f'&nbsp;|&nbsp; 일자료: {len(daily):,}일</p>',
        unsafe_allow_html=True,
    )

    # ── ③ 12개월 유효강수 비교표 (요청 5: 위치 이동 — 10년 유효 차트 직상단) ──
    st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)
    st.markdown(
        f'<p class="section-title" style="margin:0 0 4px;">'
        f'농업유효강수일수 비교표 — 직전 12개월 (일)</p>',
        unsafe_allow_html=True,
    )
    _render_12month_table(eff_table, unit="일", decimals=0,
                           metric_label="유효강수일수", n_baseline=n_rain)
    st.markdown(
        f'<p style="font-size:14px;color:var(--color-text-secondary);margin:4px 0 0;">'
        f'{_baseline_footnote(eff_table, n_rain, label="과거 N년 평균")}</p>',
        unsafe_allow_html=True,
    )

    # ── ④ 월별 농업유효강수일수 추이 (요청 1·2·3: Y축 0~15, 2씩, ≥15 라벨) ──
    st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)
    st.markdown(
        f'<p class="section-title" style="margin:0 0 4px;">'
        f'월별 농업유효강수일수 추이 — {aws_name} (10년+ 범위)</p>'
        f'<p style="font-size:14px;color:var(--color-text-secondary);margin:0 0 4px;">'
        f'기준: 일강수량 {config.EFFECTIVE_RAINFALL_THRESHOLD_MM} mm 이상 / '
        f'시작월은 위 강수량 차트와 공유</p>',
        unsafe_allow_html=True,
    )
    eff_color = theme.COLOR_SUCCESS
    eff_vals = plot["유효강수일수(일)"].fillna(0).tolist()
    # ≥15 인 막대만 텍스트 라벨 표시
    text_vals = [(f"{int(v)}" if (v is not None and v >= 15) else "")
                 for v in eff_vals]

    fig2 = go.Figure()
    fig2.add_trace(go.Bar(
        x=plot["연월"], y=eff_vals,
        marker=dict(color=theme.hex_alpha(eff_color, 0.85),
                    line=dict(color=eff_color, width=0.5)),
        text=text_vals,
        textposition="outside",
        textfont=dict(size=13, color=eff_color, family="Arial Black"),
        cliponaxis=False,
        hovertemplate="%{x}<br>%{y:.0f} 일<extra></extra>",
    ))
    fig2.update_layout(
        height=270,
        xaxis_title="", yaxis_title="유효강수일수 (일)",
        margin=dict(t=14, b=8, l=50, r=10),
        font=dict(size=14),
        showlegend=False,
        bargap=0.1,
        # v1.2.10: 명시적 X 범위 제거 — 위 강수량 차트와 동일한 자동 패딩 적용 →
        #          첫/마지막 막대가 잘리지 않고 같은 폭으로 표시됨.
        # Y축: 0~15, 눈금 0/2/4/.../14, 15 이상은 막대 위 라벨로 표기
        yaxis=dict(
            range=[0, 15],
            tickmode="array",
            tickvals=[0, 2, 4, 6, 8, 10, 12, 14],
            ticktext=["0", "2", "4", "6", "8", "10", "12", "14"],
        ),
    )
    st.plotly_chart(fig2, use_container_width=True,
                    key=f"t5_aws_10y_eff_{aws_name}")
