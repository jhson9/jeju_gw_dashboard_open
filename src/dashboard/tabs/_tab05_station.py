# ==============================================================================
#  파일명: src/dashboard/tabs/_tab05_station.py
#  ④ 공간 분석 탭 — 관측정 디테일 렌더 (지하수위 일자료 분석)
#
#  Source 분리: tab05_map.py 1055줄 → 그룹별 분리 4단계 (마지막) (2026-05-09).
#    - _load_day_cached         : 일자료 CSV 캐시 (관측정 단위)
#    - _render_station_detail   : 마커 클릭 시 정보표 + 일자료 시계열 +
#                                  12개월 EL 평균 + 박스플롯 + 월별 통계
#
#  외부 사용처: tab05_map.py 내부 전용. underscore prefix.
# ==============================================================================
from __future__ import annotations

from datetime import date

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import config
from src.collectors import gwlevel_day_parser
from src.dashboard import theme
from src.dashboard.tabs._tab05_helpers import _baseline_footnote
from src.dashboard.tabs._tab05_charts import (
    _render_12month_chart,
    _render_12month_table,
    _build_station_12month_table,
    _render_monthly_boxplot,
    _render_monthly_stats_table,
)


@st.cache_data(ttl=600)
def _load_day_cached(station: str) -> pd.DataFrame:
    return gwlevel_day_parser.load_station_day(station)


# ==============================================================================
#  ■ 관측정 상세
# ==============================================================================
def _render_station_detail(station: str, meta: pd.DataFrame,
                            asos_df: pd.DataFrame, base_date: date,
                            periods: dict):
    row = meta[meta["관측소명"] == station]
    if row.empty:
        st.warning(f"메타정보 없음: {station}")
        return
    info = row.iloc[0]

    # 인접 AWS 결정 (유역명 → 인접 AWS)
    ws_name = str(info.get("유역명", "")).replace("유역", "")
    aws_name = config.WATERSHED_AWS_MAP.get(ws_name, "제주")
    aws_color = config.AWS_COLOR_MAP.get(aws_name, theme.COLOR_TEXT_INFO)

    # ── 헤더 (요청 6: 작은 글자 '관측정 분석' 제거 / 요청 7: '관측정 : XXX') ──
    st.markdown(
        f'<p class="section-title">'
        f'<span class="emoji">🌊</span>관측정 : {station} '
        f'<span style="font-size:16px;font-weight:400;color:var(--color-text-secondary);">'
        f'· {ws_name}유역 · 인접 AWS: {aws_name}</span></p>',
        unsafe_allow_html=True,
    )

    # ── 정보표 ──
    fields = [
        ("허가번호", info.get("허가번호", "-")),
        ("유역구분", info.get("유역구분", "-")),
        ("유역명", info.get("유역명", "-")),
        ("표고 TOC(m)", info.get("표고 TOC(m)", "-")),
        ("표고 BOC(m)", info.get("표고 BOC(m)", "-")),
        ("케이싱 구경", info.get("케이싱 구경", "-")),
        ("관정심도(m)", info.get("관정심도(m)", "-")),
        ("운영현황", info.get("운영현황", "-")),
        ("지하수 용도", info.get("지하수 용도", "-")),
        ("위치", info.get("위치", "-")),
    ]
    th = ('padding:5px 8px;background:var(--color-bg-secondary);font-size:15px;color:var(--color-text-secondary);'
          'border-bottom:0.5px solid #ddd;text-align:left;font-weight:500;width:110px;')
    td = ('padding:5px 8px;border-bottom:0.5px solid #eee;font-size:16px;'
          'color:var(--color-text-primary);')
    rows_html = ""
    for i in range(0, len(fields), 2):
        left = fields[i]
        right = fields[i + 1] if (i + 1) < len(fields) else ("", "")
        rows_html += (
            f'<tr><th style="{th}">{left[0]}</th>'
            f'<td style="{td}">{left[1]}</td>'
            f'<th style="{th}">{right[0]}</th>'
            f'<td style="{td}">{right[1]}</td></tr>'
        )
    st.markdown(
        f'<table style="width:100%;border-collapse:collapse;table-layout:fixed;">'
        f'{rows_html}</table>',
        unsafe_allow_html=True,
    )

    st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)

    # ── 일자료 시계열 (10년 + 시작월 드롭다운) ──
    day_df = _load_day_cached(station)
    if day_df.empty:
        st.info(f"{station} 일자료 CSV 가 비어있습니다.")
        return

    # 시작월 후보: 가장 이른 월부터 base_date 의 9년 전까지 (사용자가 더 길게 보고 싶다면 선택)
    earliest = day_df["날짜"].min().date()
    latest = day_df["날짜"].max().date()
    default_start = max(earliest, date(base_date.year - 10, base_date.month, 1))
    # 월 옵션 만들기 (earliest의 1일 ~ latest)
    month_opts = []
    cur = date(earliest.year, earliest.month, 1)
    end_opt = date(latest.year, latest.month, 1)
    while cur <= end_opt:
        month_opts.append(cur)
        if cur.month == 12:
            cur = date(cur.year + 1, 1, 1)
        else:
            cur = date(cur.year, cur.month + 1, 1)
    default_idx = max(
        0, next((i for i, d in enumerate(month_opts)
                 if d.year == default_start.year and d.month == default_start.month), 0)
    )

    # 요청 8·9: 제목 변경 + "시작월 :" 라벨 + 드롭다운 폭 1/2
    h1, h_lbl, h_dd, h_pad = st.columns([3.0, 0.4, 0.7, 0.9])
    with h1:
        st.markdown(
            '<p class="section-title" style="padding:6px 0;">'
            '지하수위(EL) 일평균 변화</p>',
            unsafe_allow_html=True,
        )
    with h_lbl:
        st.markdown(
            '<p style="font-size:16px;color:var(--color-text-primary);margin:0;padding:10px 0;'
            'text-align:right;font-weight:500;">시작월 :</p>',
            unsafe_allow_html=True,
        )
    with h_dd:
        start_pick = st.selectbox(
            "시작월", month_opts,
            index=default_idx,
            format_func=lambda d: f"{d.year}-{d.month:02d}",
            key=f"t5_st_start_{station}",
            label_visibility="collapsed",
        )

    plot_df = day_df[day_df["날짜"] >= pd.Timestamp(start_pick)].copy()
    if plot_df.empty:
        st.info("선택 시작월 이후 데이터 없음.")
    else:
        # v1.2.04: 상단 EL 라인 + 하단 인접 AWS 일강수량 바 (X축 공유)
        fig = make_subplots(
            rows=2, cols=1,
            shared_xaxes=True,
            vertical_spacing=0.04,
            row_heights=[0.70, 0.30],
        )

        # 상단: EL 일평균 라인
        fig.add_trace(go.Scatter(
            x=plot_df["날짜"], y=plot_df["EL"],
            mode="lines",
            line=dict(color=theme.COLOR_TEXT_INFO, width=1.4),
            hovertemplate="%{x|%Y-%m-%d}<br>EL: %{y:.2f} m<extra></extra>",
            name="EL",
            showlegend=False,
        ), row=1, col=1)

        # 하단: 인접 AWS 일강수량 바
        rain_n = 0
        if asos_df is not None and not asos_df.empty:
            rain = asos_df[
                (asos_df["지점명"] == aws_name)
                & (asos_df["일시"] >= pd.Timestamp(start_pick))
            ].copy()
            rain = rain.sort_values("일시")
            rain_n = len(rain)
            if rain_n > 0:
                fig.add_trace(go.Bar(
                    x=rain["일시"], y=rain["일강수량(mm)"],
                    marker=dict(color="#1f6fd8",
                                line=dict(color="#103a78", width=0.2)),
                    hovertemplate=(
                        f"<b>{aws_name} 일강수량</b><br>"
                        "%{x|%Y-%m-%d}<br>%{y:.1f} mm<extra></extra>"
                    ),
                    name=f"{aws_name} 일강수량",
                    showlegend=False,
                ), row=2, col=1)

        # 축 정리
        fig.update_yaxes(title_text="EL (m)", row=1, col=1,
                         tickfont=dict(size=13))
        fig.update_yaxes(title_text=f"일강수량 ({aws_name}AWS, mm)",
                         row=2, col=1, tickfont=dict(size=13),
                         rangemode="tozero")
        fig.update_xaxes(tickfont=dict(size=13), row=2, col=1)

        # X축 범위 동기화
        x_min = plot_df["날짜"].min()
        x_max = plot_df["날짜"].max()
        fig.update_xaxes(range=[x_min, x_max], row=1, col=1)
        fig.update_xaxes(range=[x_min, x_max], row=2, col=1)

        fig.update_layout(
            height=440,
            margin=dict(t=10, b=8, l=55, r=10),
            font=dict(size=14),
            bargap=0.05,
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True,
                        key=f"t5_st_ts_{station}")

        st.markdown(
            f'<p style="font-size:14px;color:var(--color-text-secondary);margin:0;">'
            f'데이터 범위: {earliest} ~ {latest} '
            f'&nbsp;|&nbsp; 총 {len(day_df):,}일 (선택 표시: {len(plot_df):,}일) '
            f'&nbsp;|&nbsp; {aws_name}AWS 일강수량: {rain_n:,}일</p>',
            unsafe_allow_html=True,
        )

    st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)

    # ── 12개월 분석 (월평균 EL + 직전 N년 동월 평균) ──
    # 요청 10: 제목 / 요청 13·14: 월평균 사용 / 요청 11: 범례 '최근 월평균'
    n_gw = config.GWLEVEL_BASELINE_YEARS  # 3
    st.markdown(
        f'<p class="section-title" style="margin:0 0 4px;">'
        f'지하수위(EL) 12개월 월평균과 과거 {n_gw}년 월평균</p>',
        unsafe_allow_html=True,
    )
    month_table = _build_station_12month_table(day_df, base_date, n_gw)
    _render_12month_chart(month_table, "최근 월평균", "m", theme.COLOR_TEXT_INFO,
                           key=f"t5_st_12mo_chart_{station}", decimals=2,
                           n_baseline=n_gw)
    _render_12month_table(month_table, unit="m", decimals=2,
                           metric_label="월평균(EL)", n_baseline=n_gw)
    # 동적 baseline 각주
    st.markdown(
        f'<p style="font-size:14px;color:var(--color-text-secondary);margin:4px 0 0;">'
        f'{_baseline_footnote(month_table, n_gw, label="과거 N년 평균")}</p>',
        unsafe_allow_html=True,
    )

    st.markdown("<div style='height:18px;'></div>", unsafe_allow_html=True)

    # ── (요청 15) 최근 12개월 박스플롯: 일평균 EL 분포 ──
    st.markdown(
        f'<p class="section-title" style="margin:0 0 4px;">'
        f'최근 12개월 월별 지하수위(EL) 일자료 분포 — 박스플롯</p>',
        unsafe_allow_html=True,
    )
    _render_monthly_boxplot(day_df, base_date, station_color=theme.COLOR_TEXT_INFO,
                             key=f"t5_st_box_{station}")

    st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)

    # ── (요청 16) 최근 12개월 월별 기초통계표 ──
    st.markdown(
        f'<p class="section-title" style="margin:0 0 4px;">'
        f'최근 12개월 월별 일자료 기초통계 (m)</p>',
        unsafe_allow_html=True,
    )
    _render_monthly_stats_table(day_df, base_date)
    st.markdown(
        f'<p style="font-size:14px;color:var(--color-text-secondary);margin:4px 0 0;">'
        f'* 각 월의 일자료(EL) 기준 — 산술평균 / 중앙값 / 최대 / 최소 / 표준편차 / 일수.'
        f'</p>',
        unsafe_allow_html=True,
    )
