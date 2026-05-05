# ==============================================================================
#  파일명: src/dashboard/tabs/tab2_rainfall.py
#  탭: ② 강수량 분석  —  Build 1.0 Final
# ==============================================================================

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

import config
from src.analysis import effective_rainfall
from src.dashboard import theme


def _short(y, m):
    return f"{str(y)[2:]}년 {m}월"


# ==============================================================================
def render(asos_df: pd.DataFrame, periods: dict):
    # 안내 캡션 제거 — 헤더/탭 자체로 의미 전달

    if asos_df.empty:
        st.warning("⚠️ ASOS 데이터 없음. **⚙️ 데이터 관리** 탭에서 수집하세요.")
        return

    monthly = effective_rainfall.aggregate_monthly(asos_df)
    half    = effective_rainfall.aggregate_half_monthly(asos_df)
    ps_keys = ["M-2", "M-1", "M"]
    ps      = [periods[k] for k in ps_keys]
    n_rain  = config.RAINFALL_BASELINE_YEARS
    # 차트 X축 라벨: "11월 (M-2)"
    xlabels = [f"{p['month']}월 ({k})" for k, p in zip(ps_keys, ps)]

    # 하단 캡션용 기간 목록
    recent_months = ", ".join(f"{str(p['year'])[2:]}년 {p['month']}월" for p in ps)
    baseline_rain_str = ", ".join(
        f"{str(p['year']-n_rain)[2:]}~{str(p['year']-1)[2:]}년 {p['month']}월" for p in ps
    )
    # 차트 범례용 baseline 요약(M-2 기간 기준)
    _p0 = ps[0]
    _bl_r0 = list(range(_p0["year"] - n_rain, _p0["year"]))
    yr_r_short = f"{str(_bl_r0[0])[2:]}~{str(_bl_r0[-1])[2:]}"
    lbl_avg_rain = f"과거 {n_rain}년 해당월 평균"
    lbl_act_rain = "최근 강수량"
    lbl_avg_eff  = f"과거 {n_rain}년 해당월 평균"
    lbl_act_eff  = "최근 유효강수(일)"

    # 값 미리 계산
    D = {}
    for s in config.STATIONS_ASOS:
        sn = s["name"]
        D[sn] = {
            "rain_a": [effective_rainfall.get_period_value(monthly, half, p, sn, "월강수량(mm)") for p in ps],
            "rain_v": [effective_rainfall.get_baseline_average(monthly, half, p, sn, "월강수량(mm)", n_years=n_rain)[0] for p in ps],
            "eff_a":  [effective_rainfall.get_period_value(monthly, half, p, sn, "유효강수일수(일)") for p in ps],
            "eff_v":  [effective_rainfall.get_baseline_average(monthly, half, p, sn, "유효강수일수(일)", n_years=n_rain)[0] for p in ps],
        }

    # ── 요약 카드 4개 ────────────────────────────────────
    m_p = periods["M"]
    card_cols = st.columns(4)
    for i, s in enumerate(config.STATIONS_ASOS):
        sn  = s["name"]
        col = s["color"]
        ra  = D[sn]["rain_a"][-1]
        rv  = D[sn]["rain_v"][-1]
        ea  = D[sn]["eff_a"][-1]
        ev  = D[sn]["eff_v"][-1]

        # 강수량 값/편차
        rain_str = f"{ra:.0f} mm" if ra is not None else "–"
        if ra is not None and rv is not None:
            rd = ra - rv
            rc = "#1d9e75" if rd >= 0 else "#e24b4a"
            rs = "+" if rd >= 0 else ""
            rain_diff_html = (
                f'<span style="color:{rc};font-weight:500;">{rs}{rd:.0f}mm</span>'
            )
        else:
            rain_diff_html = "–"
        rv_mm = f"{rv:.0f}mm" if rv is not None else "–"

        # 유효강수 값/편차
        eff_str = f"{int(round(ea))}일" if ea is not None else "–"
        ev_days = f"{ev:.0f}일" if ev is not None else "–"
        if ea is not None and ev is not None:
            ed = ea - ev
            ec = "#1d9e75" if ed >= 0 else "#e24b4a"
            es = "+" if ed >= 0 else ""
            eff_diff_html = (
                f'<span style="color:{ec};font-weight:500;">{es}{ed:.0f}일</span>'
            )
        else:
            eff_diff_html = "–"

        bg_tint   = theme.hex_alpha(col, 0.08)
        bord_tint = theme.hex_alpha(col, 0.25)
        html = (
            f'<div style="background:{bg_tint};border-radius:8px;'
            f'padding:0.75rem 0.875rem;border-left:3px solid {col};margin-bottom:8px;">'
            # 1행: 5년평균 기준 (최상단으로 이동)
            f'<p style="font-size:10px;color:#5f5e5a;margin:0 0 2px;">'
            f'5년평균 기준: {m_p["year"]-n_rain}~{m_p["year"]-1}년</p>'
            # 2행: 지점명 + 기간
            f'<p style="font-size:13px;font-weight:700;color:{col};margin:0 0 4px;">'
            f'{sn} ({s["id"]}) <span style="font-size:11px;font-weight:500;color:#5f5e5a;">· '
            f'{m_p["year"]}년 {m_p["month"]}월</span></p>'
            # 3행: 강수량 값
            f'<p style="font-size:21px;font-weight:600;color:{col};margin:0 0 1px;">{rain_str}</p>'
            # 4행: 과거 5년 평균 | 편차
            f'<p style="font-size:11px;margin:0 0 5px;color:#5f5e5a;">'
            f'과거 5년 평균 {rv_mm} &nbsp;|&nbsp; 편차 {rain_diff_html}</p>'
            # 구분선
            f'<div style="height:0.5px;background:{bord_tint};margin-bottom:5px;"></div>'
            # 5행: 유효강수 | 과거 5년 평균 | 편차 (구분자 양쪽에 여유 공백)
            f'<p style="font-size:11px;color:#5f5e5a;margin:0;">'
            f'유효강수 <span style="font-weight:500;color:#1a1a18;">{eff_str}</span>'
            f'&nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp; 과거 5년 평균 {ev_days}'
            f'&nbsp;&nbsp;&nbsp;|&nbsp;&nbsp;&nbsp; 편차 {eff_diff_html}</p>'
            f'</div>'
        )
        with card_cols[i]:
            st.markdown(html, unsafe_allow_html=True)

    st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

    caption_style = "font-size:10px;color:#5f5e5a;margin:4px 0 0;"

    # ── 강수량 섹션 ───────────────────────────────────────────
    st.markdown(
        f'<p style="font-size:15px;font-weight:600;margin:0 0 4px;">'
        f'월별 강수량 : 4개 AWS (mm)</p>',
        unsafe_allow_html=True
    )
    _render_2x2_charts(xlabels, config.STATIONS_ASOS, D, "rain_a", "rain_v",
                       "mm", lbl_avg_rain, lbl_act_rain,
                       key_prefix="t2_rain", decimals=0)
    st.markdown(
        f'<p style="{caption_style}">'
        f'* 최근 월 강수량 : {recent_months}'
        f' &nbsp;|&nbsp; 과거 {n_rain}년 해당월 : {baseline_rain_str}</p>',
        unsafe_allow_html=True
    )

    st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)

    # ── 강수량 비교표 ─────────────────────────────────────────
    st.markdown(
        f'<p style="font-size:15px;font-weight:600;margin:0 0 4px;">'
        f'강수량 비교표 : 4개 AWS (mm)</p>',
        unsafe_allow_html=True
    )
    _render_mkptbl(ps, ps_keys, D, "rain_a", "rain_v", "mm",
                   decimals=0, metric="강수량")
    st.markdown(
        f'<p style="{caption_style}">'
        f'* 최근 월 강수량 : {recent_months}'
        f' &nbsp;|&nbsp; 과거 {n_rain}년 해당월 : {baseline_rain_str}</p>',
        unsafe_allow_html=True
    )

    st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)

    # ── 농업유효 강수일수 섹션 ──────────────────────────────
    st.markdown(
        f'<p style="font-size:15px;font-weight:600;margin:0 0 4px;">'
        f'월별 농업유효 강수일수 (일)</p>'
        f'<p style="font-size:10px;color:#5f5e5a;margin:0 0 6px;">'
        f'기준: 일강수량 {config.EFFECTIVE_RAINFALL_THRESHOLD_MM} mm 이상</p>',
        unsafe_allow_html=True
    )
    _render_2x2_charts(xlabels, config.STATIONS_ASOS, D, "eff_a", "eff_v",
                       "일", lbl_avg_eff, lbl_act_eff,
                       key_prefix="t2_eff", decimals=0)
    st.markdown(
        f'<p style="{caption_style}">'
        f'* 최근 월 유효강수일수 : {recent_months}'
        f' &nbsp;|&nbsp; 과거 {n_rain}년 해당월 : {baseline_rain_str}</p>',
        unsafe_allow_html=True
    )

    st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)

    # ── 유효강수일수 비교표 ────────────────────────────────────
    st.markdown(
        f'<p style="font-size:15px;font-weight:600;margin:0 0 4px;">'
        f'농업유효강수일수 비교표 : 4개 AWS (일)</p>',
        unsafe_allow_html=True
    )
    _render_mkptbl(ps, ps_keys, D, "eff_a", "eff_v", "일",
                   decimals=0, integer=True, metric="유효강수일수")
    st.markdown(
        f'<p style="font-size:10px;color:#5f5e5a;margin:4px 0 0;">'
        f'* 최근 월 유효강수일수 : {recent_months}'
        f' &nbsp;|&nbsp; 과거 {n_rain}년 해당월 : {baseline_rain_str}</p>',
        unsafe_allow_html=True
    )

    st.markdown("<div style='height:18px;'></div>", unsafe_allow_html=True)

    # ── 연간 강수량 분석 ────────────────────────────────────
    st.markdown(
        f'<p style="font-size:15px;font-weight:600;margin:0 0 4px;">'
        f'연간 강수량 분석 — 5개 차트 (평균·제주·서귀포·성산·고산)</p>'
        f'<p style="{caption_style}">'
        f'* 막대(연 총 강수량, 우 Y축) + 선(월 강수량, 좌 Y축) · '
        f'완전한 12개월 자료가 있는 연도만 막대 표시</p>',
        unsafe_allow_html=True
    )
    _render_annual_rainfall(asos_df)

    st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
    theme.render_note_box(
        f"💡 <strong>분석 메모</strong>: 4개 ASOS 관측소 데이터, "
        f"기준일 {periods['base_date']}의 M-2·M-1·M 기간 집계. "
        f"직전 {n_rain}년 평균은 각 기간 연도 기준으로 독립 계산."
    )


# ==============================================================================
#  ■ 연간 강수량 분석 — 막대(연 총합) + 선(월별), 이중 Y축
# ==============================================================================
def _render_annual_rainfall(asos_df: pd.DataFrame):
    df = asos_df.copy()
    df["일시"] = pd.to_datetime(df["일시"])
    df["연도"] = df["일시"].dt.year
    df["월"]   = df["일시"].dt.month

    # 지점×연-월 월합계
    monthly = (
        df.groupby(["지점명", "연도", "월"])["일강수량(mm)"]
          .sum().reset_index()
          .rename(columns={"일강수량(mm)": "월강수량"})
    )
    # 4개 지점 평균 (월별)
    avg_monthly = (
        monthly.groupby(["연도", "월"])["월강수량"]
               .mean().reset_index()
    )
    avg_monthly["지점명"] = "평균"
    monthly_all = pd.concat(
        [monthly[["지점명", "연도", "월", "월강수량"]],
         avg_monthly[["지점명", "연도", "월", "월강수량"]]],
        ignore_index=True,
    )

    chart_list = [
        {"name": "평균",   "color": "#5f5e5a", "id": ""},
        {"name": "제주",   "color": "#378ADD", "id": "184"},
        {"name": "서귀포", "color": "#1D9E75", "id": "189"},
        {"name": "성산",   "color": "#E24B4A", "id": "188"},
        {"name": "고산",   "color": "#BA7517", "id": "185"},
    ]

    for chart in chart_list:
        sn  = chart["name"]
        col = chart["color"]
        sub = monthly_all[monthly_all["지점명"] == sn].copy()
        if sub.empty:
            continue
        sub = sub.sort_values(["연도", "월"]).reset_index(drop=True)
        sub["dt"] = pd.to_datetime(
            sub["연도"].astype(str) + "-"
            + sub["월"].astype(str).str.zfill(2) + "-15"
        )

        # 12개월 자료가 모두 있는 연도만 연 총합 계산
        cnt_per_year = sub.groupby("연도")["월"].nunique()
        full_years = cnt_per_year[cnt_per_year == 12].index.tolist()
        annual = (
            sub[sub["연도"].isin(full_years)]
              .groupby("연도")["월강수량"].sum()
              .reset_index().rename(columns={"월강수량": "연강수량"})
        )
        annual["dt"] = pd.to_datetime(annual["연도"].astype(str) + "-07-01")

        title_id = (
            f' <span style="font-size:11px;font-weight:500;color:#5f5e5a;">'
            f'({chart["id"]})</span>' if chart["id"] else ""
        )
        st.markdown(
            f'<p style="font-size:14px;font-weight:600;margin:10px 0 0;color:{col};">'
            f'{sn}{title_id}</p>',
            unsafe_allow_html=True
        )

        # 막대 폭: ~340일 (mid-year 위치라 양쪽으로 ~5.5개월씩)
        bar_width_ms = 340 * 24 * 3600 * 1000
        # Y축 상한 — 이중축이라 따로 계산해 막대 라벨이 위 외부에 보이도록 여유
        y2_max = (annual["연강수량"].max() * 1.18) if not annual.empty else 1
        y1_max = (sub["월강수량"].max() * 1.20) if not sub.empty else 1

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=annual["dt"], y=annual["연강수량"],
            name="연 총 강수량",
            marker=dict(color=theme.hex_alpha(col, 0.30),
                        line=dict(color=col, width=1)),
            text=[f"{v:,.0f}" for v in annual["연강수량"]],
            textposition="outside",
            textfont=dict(size=10, color=col),
            cliponaxis=False,
            width=bar_width_ms,
            yaxis="y2",
            hovertemplate="%{x|%Y}<br>연 총 강수량: %{y:.0f} mm<extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=sub["dt"], y=sub["월강수량"],
            mode="lines+markers",
            name="월 강수량",
            line=dict(color=col, width=1.6),
            marker=dict(size=4, color=col),
            yaxis="y",
            hovertemplate="%{x|%Y-%m}<br>월 강수량: %{y:.0f} mm<extra></extra>",
        ))
        fig.update_layout(
            height=300,
            xaxis=dict(
                tickformat="%Y",
                dtick="M12",
                tickfont=dict(size=10),
                showgrid=True, gridcolor="rgba(0,0,0,0.06)",
            ),
            yaxis=dict(
                title=dict(text="월 강수량 (mm)", font=dict(size=10)),
                side="left",
                range=[0, y1_max],
                tickfont=dict(size=9),
            ),
            yaxis2=dict(
                title=dict(text="연 총 강수량 (mm)", font=dict(size=10)),
                overlaying="y", side="right",
                showgrid=False,
                range=[0, y2_max],
                tickfont=dict(size=9),
            ),
            margin=dict(t=10, b=18, l=50, r=55),
            showlegend=True,
            legend=dict(
                orientation="h", yanchor="bottom", y=1.0,
                xanchor="right", x=1,
                font=dict(size=10),
                bgcolor="rgba(255,255,255,0.5)",
            ),
            font=dict(size=10),
            bargap=0.0,
            plot_bgcolor="white",
        )
        st.plotly_chart(fig, use_container_width=True,
                        key=f"t2_annual_{sn}")


# ==============================================================================
#  ■ 공통 헬퍼
# ==============================================================================
def _legend_row(color, avg_label, act_label):
    def _box(col, outline):
        if outline:
            return f'<span style="width:10px;height:10px;border-radius:2px;border:1.5px solid {col};display:inline-block;"></span>'
        return f'<span style="width:10px;height:10px;border-radius:2px;background:{col};display:inline-block;"></span>'
    return st.markdown(
        f'<span style="font-size:10px;color:#5f5e5a;">'
        f'{_box(color, True)} {avg_label}&nbsp;&nbsp;'
        f'{_box(color, False)} {act_label}</span>',
        unsafe_allow_html=True
    )


def _render_2x2_charts(xlabels, stations, D, act_key, avg_key,
                        unit, avg_name, act_name, key_prefix, decimals=1):
    """4개 지점 차트를 1×4 (한 줄)로 나란히 배치.
    모든 지점 차트의 Y축 범위를 통일 — 지점 간 비교가 가능하도록."""
    def _fmt(v):
        return "" if v is None else f"{v:.{decimals}f}"

    # 전체 지점 값에서 공용 y_max 계산 (약간의 여유 공간 포함)
    all_vals = []
    for s in stations:
        for v in D[s["name"]][act_key] + D[s["name"]][avg_key]:
            if v is not None:
                all_vals.append(v)
    y_max = (max(all_vals) * 1.20) if all_vals else 1

    row = st.columns(len(stations))
    for i, s in enumerate(stations):
        sn  = s["name"]
        col = s["color"]
        target = row[i]
        with target:
            # 제목 15px bold + 1줄 범례
            st.markdown(
                f'<p style="font-size:15px;font-weight:600;margin:0 0 2px;color:{col};">'
                f'{sn} <span style="font-size:11px;font-weight:500;color:#5f5e5a;">({s["id"]})</span></p>'
                f'<div style="font-size:11px;color:#5f5e5a;margin:0 0 4px;">'
                f'<span style="display:inline-flex;align-items:center;gap:4px;margin-right:12px;">'
                f'<span style="width:10px;height:10px;border-radius:2px;border:1.5px solid {col};display:inline-block;"></span>'
                f'{avg_name}</span>'
                f'<span style="display:inline-flex;align-items:center;gap:4px;">'
                f'<span style="width:10px;height:10px;border-radius:2px;background:{col};display:inline-block;"></span>'
                f'{act_name}</span>'
                f'</div>',
                unsafe_allow_html=True
            )
            fig = go.Figure()
            fig.add_trace(go.Bar(
                name=avg_name, x=xlabels, y=D[sn][avg_key],
                marker=dict(color=theme.hex_alpha(col, 0.18), line=dict(color=col, width=1.5)),
                text=[_fmt(v) for v in D[sn][avg_key]],
                textposition="outside",
                textfont=dict(size=10, color="#5f5e5a"),
                cliponaxis=False,
                hovertemplate=f"%{{x}}<br>{avg_name}: %{{y:.1f}} {unit}<extra></extra>",
            ))
            fig.add_trace(go.Bar(
                name=act_name, x=xlabels, y=D[sn][act_key],
                marker=dict(color=col),
                text=[_fmt(v) for v in D[sn][act_key]],
                textposition="outside",
                textfont=dict(size=10, color="#1a1a18"),
                cliponaxis=False,
                hovertemplate=f"%{{x}}<br>{act_name}: %{{y:.1f}} {unit}<extra></extra>",
            ))
            fig.update_layout(
                barmode="group", height=220,
                xaxis_title="", yaxis_title=unit,
                xaxis=dict(tickfont=dict(size=11)),
                yaxis=dict(range=[0, y_max]),   # 4개 지점 Y축 공용 범위
                bargap=0.3, bargroupgap=0.15,
                margin=dict(t=14, b=4, l=30, r=4),
                showlegend=False, font=dict(size=10),
            )
            st.plotly_chart(fig, use_container_width=True, key=f"{key_prefix}_{sn}")


def _render_mkptbl(ps, ps_keys, D, act_key, avg_key, unit, decimals=1, integer=False,
                   metric="강수량"):
    """각 지점을 3개 하위 열(최근/과거 N년 평균/편차)로 분리해 표기.
    metric: '강수량' 또는 '유효강수일수' 등 — 하위 열 레이블 접두사."""
    stations = config.STATIONS_ASOS
    n_rain   = config.RAINFALL_BASELINE_YEARS

    if metric == "강수량":
        sub_cols = [
            f"최근 강수량 ({unit})",
            f"과거 {n_rain}년 평균 ({unit})",
            f"강수량 편차 ({unit})",
        ]
    elif metric == "유효강수일수":
        # 표 제목에 (일) 이 이미 있으므로 하위 열에서는 단위 생략
        sub_cols = [
            "금년 유효강수",
            f"과거 {n_rain}년 유효강수",
            "유효강수일수 편차",
        ]
    else:
        sub_cols = [f"최근 ({unit})", f"과거 {n_rain}년 평균 ({unit})", f"편차 ({unit})"]

    # 헤더: 2단(지점 colspan=3 / 하위열)
    head = (
        '<table style="width:100%;border-collapse:collapse;font-size:14px;">'
        '<thead>'
        '<tr style="background:#f5f5f3;">'
        '<th rowspan="2" style="padding:6px 8px;border-bottom:1.5px solid #ccc;'
        'text-align:center;vertical-align:middle;min-width:90px;">기간</th>'
    )
    for s in stations:
        head += (
            f'<th colspan="3" style="padding:6px 8px;border-bottom:1px solid #ddd;'
            f'text-align:center;color:{s["color"]};font-size:14px;">'
            f'{s["name"]} <span style="font-size:12px;font-weight:400;color:#5f5e5a;">'
            f'({s["id"]})</span></th>'
        )
    head += '</tr>'
    head += '<tr style="background:#f5f5f3;">'
    for _s in stations:
        for sc in sub_cols:
            head += (
                f'<th style="padding:4px 6px;border-bottom:1.5px solid #ccc;'
                f'text-align:center;font-size:11px;font-weight:500;color:#5f5e5a;">'
                f'{sc}</th>'
            )
    head += '</tr></thead><tbody>'

    body = ""
    for i, (pk, p) in enumerate(zip(ps_keys, ps)):
        period_td = (
            f'<td style="padding:6px 8px;border-bottom:0.5px solid #eee;text-align:center;">'
            f'<div style="font-size:14px;font-weight:500;">{p["month"]}월</div>'
            f'<div style="font-size:12px;color:#5f5e5a;">({pk})</div>'
            f'</td>'
        )
        row = "<tr>" + period_td
        for s in stations:
            sn  = s["name"]
            a   = D[sn][act_key][i]
            v   = D[sn][avg_key][i]
            a_s = f"{int(round(a))}" if (integer and a is not None) else (f"{a:.{decimals}f}" if a is not None else "–")
            v_s = f"{int(round(v))}" if (integer and v is not None) else (f"{v:.{decimals}f}" if v is not None else "–")
            if a is not None and v is not None:
                d = a - v
                c = "#1d9e75" if d >= 0 else "#e24b4a"; sg = "+" if d >= 0 else ""
                d_s = f'<span style="color:{c};font-weight:500;">{sg}{d:.{decimals}f}</span>'
            else:
                d_s = "–"
            # 세 개 하위 셀
            row += (
                f'<td style="padding:6px 6px;border-bottom:0.5px solid #eee;text-align:center;'
                f'font-size:14px;font-weight:500;">{a_s}</td>'
                f'<td style="padding:6px 6px;border-bottom:0.5px solid #eee;text-align:center;'
                f'font-size:13px;color:#5f5e5a;">{v_s}</td>'
                f'<td style="padding:6px 6px;border-bottom:0.5px solid #eee;text-align:center;'
                f'font-size:13px;">{d_s}</td>'
            )
        row += "</tr>"
        body += row

    st.markdown(head + body + "</tbody></table>", unsafe_allow_html=True)
