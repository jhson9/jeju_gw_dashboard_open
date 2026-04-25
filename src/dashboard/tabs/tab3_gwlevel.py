# ==============================================================================
#  파일명: src/dashboard/tabs/tab3_gwlevel.py
#  탭: ③ 지하수위 분석  —  Build 1.0 Final
# ==============================================================================

import re
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

import config
from src.analysis import watershed_mapper, effective_rainfall
from src.collectors import gwlevel_parser
from src.dashboard import theme
from plotly.subplots import make_subplots


def _hex_alpha(hex_col: str, alpha: float) -> str:
    h = hex_col.lstrip("#")
    r, g, b = int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)
    return f"rgba({r},{g},{b},{alpha})"

def _short(y, m): return f"{str(y)[2:]}년 {m}월"


@st.cache_data(ttl=300)
def _load_station_data_cached():
    """개별 관측정 CSV 전체를 로드 후 연월 컬럼으로 정리."""
    df = gwlevel_parser.load_all_station_data()
    if df.empty or "연월" not in df.columns:
        return pd.DataFrame()
    return df


@st.cache_data(ttl=600)
def _load_ws_to_stations_cached():
    try:
        return watershed_mapper.get_watershed_to_stations_map()
    except Exception:
        return {}


# 관측정별 색상 팔레트 (qualitative, 모두 #hex 형식) —
# 바 차트와 추이 차트에서 동일한 매핑을 사용해 시각적 일관성 유지.
_STATION_PALETTE = (
    px.colors.qualitative.Plotly + px.colors.qualitative.Dark24
)


# ==============================================================================
def render(ws_data_all: dict, periods: dict, asos_df=None):
    if not ws_data_all:
        st.warning("⚠️ 지하수위 데이터 없음. **⚙️ 데이터 관리** 탭에서 처리하세요.")
        return

    # ── (최상단) 유역별 편차 3-패널: M-2 · M-1 · M ───────────
    _render_diff_bar_row(ws_data_all, periods)

    st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

    # ── 유역 선택 (st.radio horizontal — deselect/탭 튕김 이슈 없음) ─
    ws_names = [w["name"] for w in config.WATERSHEDS]
    ws_color = {w["name"]: w["color"] for w in config.WATERSHEDS}

    if "tab3_ws_radio" not in st.session_state:
        st.session_state["tab3_ws_radio"] = ws_names[0]

    sel = st.radio(
        "유역 선택",
        options=ws_names,
        horizontal=True,
        key="tab3_ws_radio",
        label_visibility="collapsed",
    )
    st.session_state["tab3_ws"] = sel
    ws_col = ws_color.get(sel, "#185fa5")
    ws_df  = ws_data_all.get(sel, pd.DataFrame())
    n_gw   = config.GWLEVEL_BASELINE_YEARS

    ps_keys = ["M-2", "M-1", "M"]
    ps      = [periods[k] for k in ps_keys]
    # X축 라벨 축약
    xlabels = [f"{p['month']}월 ({k})" for k, p in zip(ps_keys, ps)]
    # 하단 캡션용 기간 목록
    recent_months = ", ".join(f"{str(p['year'])[2:]}년 {p['month']}월" for p in ps)
    baseline_gw_str = ", ".join(
        f"{str(p['year']-n_gw)[2:]}~{str(p['year']-1)[2:]}년 {p['month']}월" for p in ps
    )
    # 차트 범례용 (M-2 baseline 기준)
    _p0 = ps[0]
    _bl0 = list(range(_p0["year"] - n_gw, _p0["year"]))
    yr_g_short = f"{str(_bl0[0])[2:]}~{str(_bl0[-1])[2:]}"

    # ── M-2·M-1·M 요약 카드 (기존 HTML .card) ────────────────
    card_cols = st.columns(3)
    rows_data = []
    for i, (pk, p) in enumerate(zip(ps_keys, ps)):
        ym = f"{p['year']}-{p['month']:02d}"
        bl = list(range(p["year"] - n_gw, p["year"]))
        actual = avg = None
        if not ws_df.empty:
            ra = ws_df[ws_df["연월"] == ym]
            actual = float(ra["EL_평균"].iloc[0]) if not ra.empty else None
            bv = [float(ws_df[ws_df["연월"] == f"{y}-{p['month']:02d}"]["EL_평균"].iloc[0])
                  for y in bl
                  if not ws_df[ws_df["연월"] == f"{y}-{p['month']:02d}"].empty]
            avg = sum(bv)/len(bv) if bv else None
        diff = round(actual - avg, 2) if (actual is not None and avg is not None) else None
        pct  = round(diff/avg*100)    if (diff is not None and avg) else None
        rows_data.append({"pk": pk, "p": p, "actual": actual, "avg": avg,
                           "diff": diff, "pct": pct, "bl": bl})

        is_m = (pk == "M")
        bg   = "#e6f1fb" if is_m else "#f5f5f3"
        bd   = "2px" if is_m else "1px"
        bd_c = ws_col if is_m else ws_col + "80"
        date_col = ws_col if is_m else "#1a1a18"

        # 짧은 연도
        yy_m     = str(p["year"])[2:]
        yr_gw_s  = f"{str(bl[0])[2:]}~{str(bl[-1])[2:]}"

        gw_str = f"{actual:.2f} m" if actual is not None else "–"
        gv_str = f"{avg:.2f} m"    if avg    is not None else "–"
        if diff is not None:
            c = "#1d9e75" if diff >= 0 else "#e24b4a"
            sg = "+" if diff >= 0 else ""
            diff_html = f'<span style="color:{c};font-weight:500;">{sg}{diff:.2f}m</span>'
        else:
            diff_html = '<span style="color:#999;">-</span>'

        html = (
            f'<div style="background:{bg};border:0.5px solid {ws_col}40;'
            f'border-left:{bd} solid {bd_c};border-radius:8px;padding:10px 12px;">'
            # 기간 헤더 — "2025년 10월 (M-2)" 중앙
            f'<p style="margin:0 0 6px;text-align:center;">'
            f'<span style="font-size:15px;font-weight:600;color:{date_col};">'
            f'{p["year"]}년 {p["month"]}월</span>'
            f'&nbsp;&nbsp;<span style="font-size:11px;color:#5f5e5a;">({pk})</span>'
            f'</p>'
            # 섹션 레이블
            f'<p style="font-size:12px;color:#5f5e5a;margin:0 0 2px;">지하수위 ({sel})</p>'
            # 실측 + 월 레이블
            f'<p style="margin:0;">'
            f'<span style="font-size:18px;font-weight:500;">{gw_str}</span>'
            f'&nbsp;<span style="font-size:10px;color:#5f5e5a;">{yy_m}년 {p["month"]}월 평균</span>'
            f'</p>'
            # 과거 평균 + 기간 레이블 + 편차
            f'<p style="margin:2px 0 0;">'
            f'<span style="font-size:15px;font-weight:500;color:#5f5e5a;">{gv_str}</span>'
            f'&nbsp;<span style="font-size:10px;color:#5f5e5a;">{yr_gw_s}년 {p["month"]}월 평균</span>'
            f'&nbsp;<span style="font-size:10px;color:#5f5e5a;">|</span>'
            f'&nbsp;<span style="font-size:10px;">{diff_html}</span>'
            f'</p>'
            f'</div>'
        )
        with card_cols[i]:
            st.markdown(html, unsafe_allow_html=True)

    st.markdown("<div style='height:12px;'></div>", unsafe_allow_html=True)

    # ── M-2·M-1·M 막대 차트 (유역별 현황 탭과 동일 포맷) ────
    lbl_avg = f"과거 {n_gw}년 해당월 평균"
    lbl_act = "최근 지하수위"
    st.markdown(
        f'<p style="font-size:15px;font-weight:600;margin:0 0 4px;">지하수위(EL)</p>'
        f'<div style="font-size:11px;color:#5f5e5a;margin:0 0 4px;">'
        f'<span style="display:inline-flex;align-items:center;gap:4px;margin-right:14px;">'
        f'<span style="width:10px;height:10px;border-radius:2px;border:1.5px solid {ws_col};display:inline-block;"></span>'
        f'{lbl_avg}</span>'
        f'<span style="display:inline-flex;align-items:center;gap:4px;">'
        f'<span style="width:10px;height:10px;border-radius:2px;background:{ws_col};display:inline-block;"></span>'
        f'{lbl_act}</span>'
        f'</div>',
        unsafe_allow_html=True
    )
    act_v = [r["actual"] for r in rows_data]
    avg_v = [r["avg"]    for r in rows_data]
    all_v = [v for v in act_v + avg_v if v is not None]
    y_min = min(all_v) * 0.96 if all_v else 0

    def _fmt2(v):
        return "" if v is None else f"{v:.2f}"

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name=lbl_avg, x=xlabels, y=avg_v,
        marker=dict(color=_hex_alpha(ws_col, 0.18), line=dict(color=ws_col, width=1.5)),
        text=[_fmt2(v) for v in avg_v],
        textposition="outside",
        textfont=dict(size=10, color="#5f5e5a"),
        cliponaxis=False,
        hovertemplate=f"%{{x}}<br>{lbl_avg}: %{{y:.2f}} m<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        name=lbl_act, x=xlabels, y=act_v,
        marker=dict(color=ws_col),
        text=[_fmt2(v) for v in act_v],
        textposition="outside",
        textfont=dict(size=10, color="#1a1a18"),
        cliponaxis=False,
        hovertemplate=f"%{{x}}<br>{lbl_act}: %{{y:.2f}} m<extra></extra>",
    ))
    # tab1 의 _grouped_bar 와 동일한 layout (height=220, margin l=38)
    fig.update_layout(
        barmode="group", height=220,
        xaxis_title="", yaxis_title="m",
        xaxis=dict(tickfont=dict(size=12)),
        yaxis=dict(range=[y_min, None]),
        bargap=0.35, bargroupgap=0.18,
        margin=dict(t=14, b=4, l=38, r=8),
        showlegend=False, font=dict(size=11),
    )
    st.plotly_chart(fig, use_container_width=True, key=f"t3_bar_{sel}")

    st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

    # ── 상세 비교표 (유역별 현황 탭의 '지하수위(EL) 현황' 표와 동일 포맷) ─
    st.markdown(
        f'<p style="font-size:15px;font-weight:600;margin:0;">'
        f'지하수위(EL) 현황 : {sel}유역</p>',
        unsafe_allow_html=True
    )
    st.markdown("<div style='height:4px;'></div>", unsafe_allow_html=True)
    _render_detail_table(rows_data)
    st.markdown(
        f'<p style="font-size:10px;color:#5f5e5a;margin:4px 0 0;">'
        f'* 최근 월 수위 : {recent_months}'
        f' &nbsp;|&nbsp; 과거 {n_gw}년 해당월 : {baseline_gw_str}</p>',
        unsafe_allow_html=True
    )

    st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)

    # ── 유역 지하수위 추이 차트 (월별, 상세표 이후) ──────────
    st.markdown(
        f'<p style="font-size:15px;font-weight:600;margin:0 0 4px;">'
        f'지하수위(EL) 추이 : {sel} 유역</p>',
        unsafe_allow_html=True
    )
    if not ws_df.empty:
        plot_df = ws_df.copy()
        if len(plot_df) > 60:
            plot_df = plot_df.tail(60)
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(
            x=plot_df["연월"], y=plot_df["EL_평균"],
            mode="lines+markers",
            line=dict(color=ws_col, width=2),
            marker=dict(size=4),
            hovertemplate="%{x}<br>EL: %{y:.2f} m<extra></extra>",
        ))
        m_ym = f"{periods['M']['year']}-{periods['M']['month']:02d}"
        m_row = plot_df[plot_df["연월"] == m_ym]
        if not m_row.empty:
            fig2.add_trace(go.Scatter(
                x=m_row["연월"], y=m_row["EL_평균"],
                mode="markers+text",
                marker=dict(color="#e24b4a", size=10, line=dict(color="white", width=2)),
                text=["M"], textposition="top center",
                textfont=dict(color="#e24b4a", size=11),
                showlegend=False,
                hovertemplate="M 기간<br>%{x}<br>EL: %{y:.2f} m<extra></extra>",
            ))
        fig2.update_layout(
            height=280, xaxis_title="", yaxis_title="지하수위 EL (m)",
            margin=dict(t=8, b=8, l=50, r=10),
            showlegend=False, font=dict(size=11),
        )
        st.plotly_chart(fig2, use_container_width=True, key=f"t3_trend_{sel}")

    st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)

    # ── 유역 내 관측정별 지하수위 (차트 + 표) ────────────────
    _render_stations_section(sel, ws_col, periods, ps_keys, ps, n_gw, asos_df,
                              recent_months, baseline_gw_str)


# ==============================================================================
#  ■ 상세 비교표
# ==============================================================================
def _render_detail_table(rows_data):
    """유역별 현황 탭의 _render_gw_table 과 동일한 포맷 (table-layout:fixed,
    13px 글자, 기간 colwidth=360px, colgroup 균등 분배)."""
    n = config.GWLEVEL_BASELINE_YEARS

    colgroup = (
        '<colgroup>'
        '<col style="width:360px;">'
        '<col><col><col>'
        '</colgroup>'
    )
    th_base = (
        'padding:6px 8px;background:#f5f5f3;text-align:center;'
        'border-bottom:1.5px solid #ccc;'
    )

    head = (
        '<table style="width:100%;border-collapse:collapse;'
        'table-layout:fixed;font-size:13px;">'
        + colgroup
        + '<thead><tr>'
        + f'<th style="{th_base}">기간</th>'
        + f'<th style="{th_base}">최근 월 수위 (m)</th>'
        + f'<th style="{th_base}">과거 {n}년 해당월 평균 (m)</th>'
        + f'<th style="{th_base}">지하수위 편차 (m)</th>'
        + '</tr></thead><tbody>'
    )
    body = ""
    for r in rows_data:
        a = r["actual"]; v = r["avg"]; d = r["diff"]
        a_s = (f'<span style="font-size:14px;font-weight:600;">{a:.2f}</span>'
               if a is not None else "–")
        v_s = f"{v:.2f}" if v is not None else "–"
        def _dc(val):
            if val is None: return "–"
            c = "#1d9e75" if val >= 0 else "#e24b4a"
            sg = "+" if val >= 0 else ""
            return f'<span style="color:{c};font-weight:500;">{sg}{val}</span>'
        body += (
            '<tr>'
            f'<td style="padding:6px 8px;border-bottom:0.5px solid #eee;text-align:center;">'
            f'<div style="font-size:13px;font-weight:500;">{r["p"]["month"]}월</div>'
            f'<div style="font-size:11px;color:#5f5e5a;">({r["pk"]})</div>'
            f'</td>'
            f'<td style="padding:6px 8px;border-bottom:0.5px solid #eee;text-align:center;">{a_s}</td>'
            f'<td style="padding:6px 8px;border-bottom:0.5px solid #eee;text-align:center;">{v_s}</td>'
            f'<td style="padding:6px 8px;border-bottom:0.5px solid #eee;text-align:center;">{_dc(d)}</td>'
            '</tr>'
        )
    st.markdown(head + body + "</tbody></table>", unsafe_allow_html=True)


# ==============================================================================
#  ■ 전체 유역 요약표 (기존 HTML gwAllTbl 이식)
# ==============================================================================
def _render_all_table(ws_data_all, periods, ps_keys):
    n = config.GWLEVEL_BASELINE_YEARS
    ps = [periods[k] for k in ps_keys]

    head = '<table style="width:100%;border-collapse:collapse;font-size:12px;"><thead>'
    head += '<tr style="background:#f5f5f3;">'
    head += '<th style="padding:6px 8px;border-bottom:1.5px solid #ccc;text-align:center;min-width:60px;">유역</th>'
    head += '<th style="padding:6px 8px;border-bottom:1.5px solid #ccc;text-align:center;min-width:48px;">AWS</th>'
    for pk, p in zip(ps_keys, ps):
        head += (
            f'<th style="padding:6px 8px;border-bottom:1.5px solid #ccc;text-align:center;">'
            f'{p["month"]}월<br>'
            f'<span style="font-size:11px;font-weight:400;color:#5f5e5a;">({pk})</span>'
            f'</th>'
        )
    head += '</tr></thead><tbody>'

    body = ""
    ws_aws = {w["name"]: w["aws"] for w in config.WATERSHEDS}
    ws_col = {w["name"]: w["color"] for w in config.WATERSHEDS}

    for w in config.WATERSHEDS:
        wn   = w["name"]
        col  = ws_col[wn]
        df_w = ws_data_all.get(wn, pd.DataFrame())
        row  = (
            f'<tr>'
            f'<td style="padding:6px 8px;border-bottom:0.5px solid #eee;text-align:center;'
            f'color:{col};font-weight:500;">{wn}</td>'
            f'<td style="padding:6px 8px;border-bottom:0.5px solid #eee;text-align:center;'
            f'font-size:11px;color:#5f5e5a;">{ws_aws.get(wn, "")}</td>'
        )
        for pk, p in zip(ps_keys, ps):
            ym = f"{p['year']}-{p['month']:02d}"
            bl = list(range(p["year"] - n, p["year"]))
            actual = avg = None
            if not df_w.empty:
                ra = df_w[df_w["연월"] == ym]
                actual = float(ra["EL_평균"].iloc[0]) if not ra.empty else None
                bv = [float(df_w[df_w["연월"] == f"{y}-{p['month']:02d}"]["EL_평균"].iloc[0])
                      for y in bl
                      if not df_w[df_w["연월"] == f"{y}-{p['month']:02d}"].empty]
                avg = sum(bv)/len(bv) if bv else None
            diff = round(actual - avg, 2) if (actual is not None and avg is not None) else None
            a_s  = f"{actual:.2f}" if actual is not None else "–"
            v_s  = f"({avg:.2f})"  if avg    is not None else ""
            if diff is not None:
                c = "#1d9e75" if diff >= 0 else "#e24b4a"; sg = "+" if diff >= 0 else ""
                d_s = f'<div style="font-size:11px;color:{c};font-weight:500;">{sg}{diff}</div>'
            else: d_s = ""
            row += (
                f'<td style="padding:6px 8px;border-bottom:0.5px solid #eee;text-align:center;">'
                f'<div style="font-size:12px;font-weight:500;">{a_s}</div>'
                f'<div style="font-size:11px;color:#5f5e5a;">{v_s}</div>'
                f'{d_s}</td>'
            )
        row += "</tr>"
        body += row

    st.markdown(head + body + "</tbody></table>", unsafe_allow_html=True)


# ==============================================================================
#  ■ 편차 막대 차트 — 3-패널 한 줄 (M-2 / M-1 / M)
# ==============================================================================
def _render_diff_bar_row(ws_data_all, periods):
    """M-2, M-1, M 세 기간의 유역별 편차 차트를 한 줄에 3개 패널로 렌더링.
    각 바에 편차 숫자 라벨을 부호에 따라 + 는 위쪽 / - 는 아래쪽에 표시."""
    n = config.GWLEVEL_BASELINE_YEARS
    ps_keys = ["M-2", "M-1", "M"]
    ps_list = [periods[k] for k in ps_keys]
    ws_col_map = {w["name"]: w["color"] for w in config.WATERSHEDS}

    st.markdown(
        f'<p style="font-size:15px;font-weight:600;margin:0 0 4px;">'
        f'유역별 지하수위(EL) 변동 — 최근 3개월 (과거 {n}년 동일월 평균 대비)</p>',
        unsafe_allow_html=True
    )

    cols = st.columns(3)
    for col_idx, (pk, p) in enumerate(zip(ps_keys, ps_list)):
        ym = f"{p['year']}-{p['month']:02d}"
        bl = list(range(p["year"] - n, p["year"]))
        names, diffs, colors = [], [], []
        for w in config.WATERSHEDS:
            wn = w["name"]
            df_w = ws_data_all.get(wn, pd.DataFrame())
            if df_w.empty:
                continue
            ra = df_w[df_w["연월"] == ym]
            if ra.empty:
                continue
            actual = float(ra["EL_평균"].iloc[0])
            bv = [float(df_w[df_w["연월"] == f"{y}-{p['month']:02d}"]["EL_평균"].iloc[0])
                  for y in bl
                  if not df_w[df_w["연월"] == f"{y}-{p['month']:02d}"].empty]
            if not bv:
                continue
            avg = sum(bv) / len(bv)
            names.append(wn)
            diffs.append(round(actual - avg, 2))
            colors.append(ws_col_map.get(wn, "#888"))

        with cols[col_idx]:
            short_m  = f"{str(p['year'])[2:]}년 {p['month']}월"
            bl_short = f"{str(bl[0])[2:]}~{str(bl[-1])[2:]}"
            sub_title = f"{pk} · {short_m}  (기준 {bl_short}년)"
            st.markdown(
                f'<p style="font-size:12px;font-weight:500;color:#1a1a18;margin:0 0 2px;">'
                f'{sub_title}</p>',
                unsafe_allow_html=True
            )
            if not names:
                st.info("데이터 부족")
                continue

            # 편차 라벨: 부호에 따라 위/아래 위치 자동 배치
            text_vals = [f"{'+' if v > 0 else ''}{v:.2f}" for v in diffs]
            # 양수 바는 '상단(outside)' = 위쪽, 음수 바는 'outside' = 아래쪽 — Plotly 기본 동작
            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=names, y=diffs,
                marker=dict(color=colors, line=dict(color="rgba(255,255,255,1)", width=1)),
                text=text_vals,
                textposition="outside",          # + 위, - 아래 자동
                textfont=dict(size=9, color="#1a1a18"),
                cliponaxis=False,
                hovertemplate="%{x}<br>편차: %{y:.2f} m<extra></extra>",
            ))
            fig.add_hline(y=0, line_dash="dash", line_color="rgba(26,26,24,0.3)", line_width=1)
            fig.update_layout(
                height=280,
                xaxis_title="",
                xaxis=dict(categoryorder="array", categoryarray=names,
                           tickfont=dict(size=10)),
                yaxis_title="편차 (m)",
                yaxis=dict(range=[-5, 5], zeroline=True),
                margin=dict(t=6, b=20, l=40, r=6),
                showlegend=False,
                font=dict(size=10),
            )
            st.plotly_chart(fig, use_container_width=True,
                            key=f"t3_diff_row_{pk}")


# ==============================================================================
#  ■ (legacy) 편차 막대 차트 1-패널 버전 — 참조용, 현재 미사용
# ==============================================================================
def _render_diff_bar(ws_data_all, periods):
    m_p = periods["M"]
    ym  = f"{m_p['year']}-{m_p['month']:02d}"
    n   = config.GWLEVEL_BASELINE_YEARS
    bl  = list(range(m_p["year"] - n, m_p["year"]))

    # 유역 순서대로 (config.WATERSHEDS 순)
    ws_col = {w["name"]: w["color"] for w in config.WATERSHEDS}
    names = []; diffs = []; colors = []
    for w in config.WATERSHEDS:
        wn   = w["name"]
        df_w = ws_data_all.get(wn, pd.DataFrame())
        if df_w.empty: continue
        ra = df_w[df_w["연월"] == ym]
        if ra.empty: continue
        actual = float(ra["EL_평균"].iloc[0])
        bv = [float(df_w[df_w["연월"] == f"{y}-{m_p['month']:02d}"]["EL_평균"].iloc[0])
              for y in bl
              if not df_w[df_w["연월"] == f"{y}-{m_p['month']:02d}"].empty]
        if not bv: continue
        avg = sum(bv)/len(bv)
        names.append(wn)
        diffs.append(round(actual - avg, 2))
        colors.append(ws_col.get(wn, "#888"))

    if not names:
        st.info("편차 계산 데이터 부족")
        return

    short_m  = f"{str(m_p['year'])[2:]}년 {m_p['month']}월"
    bl_short = f"{str(bl[0])[2:]}~{str(bl[-1])[2:]}"

    chart_title = (
        f"유역별 지하수위(EL) 변동 "
        f"(과거{n}년({bl_short}년) {m_p['month']}월 평균 - {short_m})"
    )
    yaxis_title = f"과거 {n}년 대비 {m_p['month']}월 지하수위 현황"

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=names, y=diffs,
        marker=dict(color=colors),
        hovertemplate="%{x}<br>편차: %{y:.2f} m<extra></extra>",
    ))
    fig.add_hline(y=0, line_dash="dash", line_color="rgba(26,26,24,0.3)", line_width=1)
    fig.update_layout(
        title=dict(
            text=chart_title,
            font=dict(size=12), x=0.01
        ),
        height=300,
        xaxis_title="",
        xaxis=dict(categoryorder="array", categoryarray=names),
        yaxis_title=yaxis_title,
        yaxis=dict(range=[-5, 5], zeroline=True),
        margin=dict(t=30, b=20, l=60, r=10),
        showlegend=False,
        font=dict(size=11),
    )
    st.plotly_chart(fig, use_container_width=True, key="t3_diff_bar")


# ==============================================================================
#  ■ NEW: 유역 내 관측정별 지하수위 (차트 + 표)
# ==============================================================================
def _render_stations_section(sel, ws_col, periods, ps_keys, ps, n_gw, asos_df,
                              recent_months, baseline_gw_str):
    """선택된 유역에 속한 관측정들의 M-2·M-1·M EL 값을 시각화/표 렌더링.

    - 차트: 대시보드 요약의 '유역별 지하수위(EL) 변동' 과 동일한 패턴으로
            관측정별 3개 막대(기간별 톤)를 그린다. Y축은 절대 EL 값.
    - 표:  관측정 × (M-2, M-1, M, 과거 N년 평균(M기준), 편차) 형식.
    """
    station_df = _load_station_data_cached()
    ws_to_stations = _load_ws_to_stations_cached()
    stations_all = ws_to_stations.get(sel, [])

    # station_df 가 비었거나 매핑이 없으면 안내만 표시
    if station_df.empty or not stations_all:
        st.markdown(
            f'<p style="font-size:15px;font-weight:600;margin:0 0 4px;">'
            f'관측정별 지하수위 : {sel} 유역</p>'
            f'<p style="font-size:11px;color:#5f5e5a;margin:0;">'
            f'관측정 데이터가 없습니다. 관측망 정보 파일(0_JD관측망_정보.xlsx)과 '
            f'관측정별 CSV(data/GWlevel/by_station/) 를 확인하세요.</p>',
            unsafe_allow_html=True
        )
        return

    # 이 유역에 실제 데이터가 존재하는 관측정만 추림
    stations = [s for s in stations_all
                if s in station_df["관측소명"].unique().tolist()]
    if not stations:
        st.markdown(
            f'<p style="font-size:15px;font-weight:600;margin:0 0 4px;">'
            f'관측정별 지하수위 : {sel} 유역</p>'
            f'<p style="font-size:11px;color:#5f5e5a;margin:0;">'
            f'{sel} 유역에 매핑된 관측정이 있으나 월별 데이터가 로드되지 않았습니다.</p>',
            unsafe_allow_html=True
        )
        return

    # 관측정별 기간값 / baseline 계산
    # stn_data[station][pk] = {"actual":.., "avg":..}
    stn_data = {}
    for stn in stations:
        df_s = station_df[station_df["관측소명"] == stn]
        per_period = {}
        for pk, p in zip(ps_keys, ps):
            ym = f"{p['year']}-{p['month']:02d}"
            bl_years = list(range(p["year"] - n_gw, p["year"]))
            ra = df_s[df_s["연월"] == ym]
            actual = float(ra["EL"].iloc[0]) if not ra.empty else None
            base_vals = []
            for y in bl_years:
                ymb = f"{y}-{p['month']:02d}"
                rb = df_s[df_s["연월"] == ymb]
                if not rb.empty:
                    v = float(rb["EL"].iloc[0])
                    if pd.notna(v):
                        base_vals.append(v)
            avg = sum(base_vals)/len(base_vals) if base_vals else None
            per_period[pk] = {"actual": actual, "avg": avg}
        stn_data[stn] = per_period

    # ── 관측정별 공용 색상 팔레트 (추이 차트와 동일) ─────
    # 두 차트가 같은 관측정에 동일 색을 쓰도록 한 곳에서 정의.
    palette = _STATION_PALETTE
    station_colors = {stn: palette[i % len(palette)] for i, stn in enumerate(stations)}

    # ── 차트 헤더 ────────────────────────────────────────
    st.markdown(
        f'<p style="font-size:15px;font-weight:600;margin:0 0 4px;">'
        f'관측정별 지하수위(EL) : {sel} 유역 ({len(stations)}개 관측정)</p>',
        unsafe_allow_html=True
    )
    # 범례 — 관측정 색상 리스트 (추이 차트와 매칭). 기간 톤 안내 문구는
    # 차트 아래쪽에 별도로 배치(요청 3).
    period_alpha = {"M-2": 0.35, "M-1": 0.65, "M": 1.0}
    station_legend = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:5px;'
        f'margin-right:16px;margin-bottom:2px;">'
        f'<span style="width:12px;height:12px;border-radius:2px;'
        f'background:{station_colors[stn]};'
        f'border:0.5px solid rgba(26,26,24,0.2);"></span>'
        f'<span style="font-size:12px;color:#1a1a18;">{stn}</span>'
        f'</span>'
        for stn in stations
    )
    st.markdown(
        f'<div style="margin:0 0 6px;line-height:2.0;">'
        f'<span style="font-size:12px;color:#5f5e5a;margin-right:8px;">관측정</span>'
        f'{station_legend}</div>',
        unsafe_allow_html=True
    )

    # ── 그래프 ───────────────────────────────────────────
    fig = go.Figure()
    for pk in ps_keys:
        ys = []
        txt = []
        colors = []
        for stn in stations:
            v = stn_data[stn][pk]["actual"]
            ys.append(v)
            txt.append(f"{v:.2f}" if v is not None else "")
            colors.append(_hex_alpha(station_colors[stn], period_alpha[pk]))
        fig.add_trace(go.Bar(
            name=pk,
            x=stations, y=ys,
            marker=dict(color=colors,
                        line=dict(color="rgba(255,255,255,1)", width=1)),
            text=txt,
            textposition="outside",
            textfont=dict(size=9, color="#1a1a18"),
            cliponaxis=False,
            width=0.22,
            hovertemplate=f"{pk}<br>%{{x}}<br>EL: %{{y:.2f}} m<extra></extra>",
            showlegend=False,
        ))
    # Y축 범위: 관측정 EL 값의 min/max 기준 여유 공간 포함
    all_vals = [stn_data[s][pk]["actual"] for s in stations for pk in ps_keys
                if stn_data[s][pk]["actual"] is not None]
    if all_vals:
        y_min = min(all_vals)
        y_max = max(all_vals)
        pad = max((y_max - y_min) * 0.12, 0.5)
        y_range = [y_min - pad, y_max + pad]
    else:
        y_range = None
    fig.update_layout(
        height=360,
        barmode="group",
        bargap=0.25,
        bargroupgap=0.18,
        xaxis_title="",
        yaxis_title="EL (m)",
        xaxis=dict(categoryorder="array", categoryarray=stations,
                   tickfont=dict(size=11)),
        yaxis=dict(range=y_range) if y_range else dict(),
        showlegend=False,
        margin=dict(t=10, b=20, l=50, r=20),
        font=dict(size=11),
    )
    st.plotly_chart(fig, use_container_width=True, key=f"t3_stn_bar_{sel}")

    # 차트 아래쪽 안내 문구 (요청 3) — 동적 월
    st.markdown(
        f'<p style="font-size:11px;color:#5f5e5a;margin:2px 0 0;">'
        f'* 각 그래프는 각각 최근 {ps[0]["month"]}월(M-2), '
        f'최근 {ps[1]["month"]}월(M-1), 최근 {ps[2]["month"]}월(M)로 '
        f'각 관측정 별로 표시 됨</p>',
        unsafe_allow_html=True
    )

    # ── 표 ───────────────────────────────────────────────
    st.markdown(
        f'<p style="font-size:15px;font-weight:600;margin:10px 0 4px;">'
        f'관측정별 상세 : {sel} 유역</p>',
        unsafe_allow_html=True
    )
    _render_stations_table(stations, stn_data, ps_keys, ps, n_gw)
    st.markdown(
        f'<p style="font-size:10px;color:#5f5e5a;margin:4px 0 0;">'
        f'* 최근 월 수위 : {recent_months}'
        f' &nbsp;|&nbsp; 과거 {n_gw}년 해당월 : {baseline_gw_str}</p>',
        unsafe_allow_html=True
    )

    # ── 관측정별 시계열 추이 차트 + 인근 AWS 강수량 막대 ──
    st.markdown("<div style='height:12px;'></div>", unsafe_allow_html=True)
    _render_stations_trend(stations, station_df, sel, ws_col, periods, asos_df)


def _render_stations_trend(stations, station_df, sel, ws_col, periods, asos_df=None):
    """유역 내 모든 관측정의 EL 시계열(line)을 상단에, 인접 AWS 월강수량(bar)을
    하단에 공유 X축으로 쌓은 2-row subplot 렌더링."""
    # 인접 AWS 조회
    ws_aws_map = {w["name"]: w["aws"] for w in config.WATERSHEDS}
    nearby = ws_aws_map.get(sel, "제주")
    aws_code = config.AWS_CODE_MAP.get(nearby, "")
    aws_col  = config.AWS_COLOR_MAP.get(nearby, "#378ADD")

    # 헤더 — AWS 정보 포함 제목 (sub-title 제거)
    aws_label = f"{nearby}AWS({aws_code})" if aws_code else f"{nearby}AWS"
    st.markdown(
        f'<p style="font-size:15px;font-weight:600;margin:0 0 4px;">'
        f'지하수위(EL) 추이 : {sel} 유역 관측정별 + {aws_label} 월강수량</p>',
        unsafe_allow_html=True
    )

    palette = _STATION_PALETTE

    # 관측정 중 가장 긴 기간을 가진 것(= 가장 이른 시작 연월)을 X축 범위 기준으로 사용.
    # 모든 관측정과 강수량을 이 범위에 맞춰 정렬해 시각 비교가 가능하도록 필터링.
    all_months = set()
    well_ranges = {}
    for stn in stations:
        df_s = station_df[station_df["관측소명"] == stn]
        if df_s.empty:
            continue
        months = df_s["연월"].dropna().tolist()
        if not months:
            continue
        well_ranges[stn] = (min(months), max(months), len(months))
        all_months.update(months)
    if all_months:
        x_min = min(all_months)
        x_max = max(all_months)
    else:
        x_min = x_max = None
    # X축 기준 기간 산출 (가장 긴 기간 관측정 — 내부 사용 only, 헤더에 노출 X)

    # 2-row 서브플롯: 상단 line, 하단 bar, X축 공유.
    # EL 영역은 v1.0.26 기준의 1.5배(346→519px), 강수량은 그대로(134px).
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        row_heights=[0.80, 0.20],
    )

    # 상단: 관측정별 EL 라인
    for i, stn in enumerate(stations):
        df_s = station_df[station_df["관측소명"] == stn].sort_values("연월")
        if df_s.empty:
            continue
        color = palette[i % len(palette)]
        fig.add_trace(
            go.Scatter(
                x=df_s["연월"], y=df_s["EL"],
                name=stn,
                mode="lines+markers",
                line=dict(color=color, width=1.5),
                marker=dict(size=3, color=color),
                hovertemplate=(
                    f"<b>{stn}</b><br>%{{x}}<br>EL: %{{y:.2f}} m<extra></extra>"
                ),
            ),
            row=1, col=1
        )

    # 하단: 인접 AWS 월강수량 막대 (관측정 기간에 맞춰 필터)
    if asos_df is not None and not asos_df.empty and x_min is not None:
        monthly = effective_rainfall.aggregate_monthly(asos_df)
        rain_df = monthly[monthly["지점명"] == nearby].sort_values("연월")
        # 관측정 기간 범위로 제한
        rain_df = rain_df[(rain_df["연월"] >= x_min) & (rain_df["연월"] <= x_max)]
        if not rain_df.empty:
            # 강우 = 진한 블루 톤 (AWS 색상 대신 통일된 비/물 느낌)
            rain_fill = "#1f6fd8"     # deep blue
            rain_edge = "#103a78"     # darker outline
            fig.add_trace(
                go.Bar(
                    x=rain_df["연월"], y=rain_df["월강수량(mm)"],
                    name=f"월강수량 ({nearby})",
                    marker=dict(color=rain_fill,
                                line=dict(color=rain_edge, width=0.5)),
                    showlegend=False,      # 관측정 범례와 분리 — 별도 색상 표시만
                    hovertemplate=(
                        f"<b>{nearby} 강수량</b><br>%{{x}}<br>"
                        f"%{{y:.0f}} mm<extra></extra>"
                    ),
                ),
                row=2, col=1
            )

    # M 기간 세로선 — 두 subplot 에 각각 추가 (paper y ref 는 subplot 경계 때문에 불안정)
    m_p = periods["M"]
    m_ym = f"{m_p['year']}-{m_p['month']:02d}"
    for r, xref, yref in [(1, "x", "y domain"), (2, "x2", "y2 domain")]:
        fig.add_shape(
            type="line", xref=xref, yref=yref,
            x0=m_ym, x1=m_ym, y0=0, y1=1,
            line=dict(dash="dash", color="rgba(26,26,24,0.35)", width=1),
            row=r, col=1,
        )
    fig.add_annotation(
        x=m_ym, xref="x", yref="y domain", y=1.0, yanchor="bottom",
        text=f"M ({m_p['year']}년 {m_p['month']}월)",
        showarrow=False,
        font=dict(size=10, color="#5f5e5a"),
        row=1, col=1,
    )

    # 축 제목 (요청 4·5)
    fig.update_yaxes(title_text="지하수위(EL) (m)", row=1, col=1,
                     tickfont=dict(size=10))
    fig.update_yaxes(title_text="월강수량(mm)", row=2, col=1,
                     tickfont=dict(size=10))
    # X축: 영문 월명("Jan") 대신 숫자 포맷("2021-01") 사용
    fig.update_xaxes(tickfont=dict(size=10), tickformat="%Y-%m",
                     row=2, col=1)
    # X축 범위를 관측정 가장 긴 기간에 맞춤 (양쪽 subplot 공유)
    if x_min is not None and x_max is not None:
        fig.update_xaxes(range=[x_min, x_max], row=1, col=1)
        fig.update_xaxes(range=[x_min, x_max], row=2, col=1)

    fig.update_layout(
        height=653,              # v1.0.26 대비 EL 영역 1.5배 (346×1.5 + 134)
        barmode="group",
        bargap=0.15,
        margin=dict(t=10, b=80, l=50, r=10),
        legend=dict(
            orientation="h", yanchor="top", y=-0.15,
            xanchor="center", x=0.5,
            font=dict(size=11),
        ),
        font=dict(size=11),
    )
    st.plotly_chart(fig, use_container_width=True, key=f"t3_stn_trend_{sel}")


def _render_stations_table(stations, stn_data, ps_keys, ps, n_gw):
    """유역 내 관측정별 표 — 3기간 × 3지표(최근수위/과거평균/편차) 그리드.

    2단 헤더:
      1행: 관측정(rowspan=2) | 11월(M-2) colspan=3 | 12월(M-1) colspan=3 | 1월(M) colspan=3
      2행:                   | 최근수위 | 과거평균 | 편차 | ... (반복)
    """

    # colgroup: 관측정 + 3기간 × 3열 = 10열
    colgroup = (
        '<colgroup>'
        '<col style="width:140px;">'                # 관측정
        '<col><col><col>'                           # M-2 (수위 / 평균 / 편차)
        '<col><col><col>'                           # M-1
        '<col><col><col>'                           # M
        '</colgroup>'
    )

    group_th = ('padding:6px 8px;background:#f5f5f3;text-align:center;'
                'border-bottom:1px solid #ddd;font-weight:600;font-size:13px;')
    sub_th   = ('padding:5px 4px;background:#f5f5f3;text-align:center;'
                'border-bottom:1.5px solid #ccc;font-size:11px;font-weight:500;'
                'color:#5f5e5a;')

    # 1행: 기간 그룹 헤더
    group_cells = ""
    for i, (pk, p) in enumerate(zip(ps_keys, ps)):
        left_border = "border-left:1px solid #ddd;" if i > 0 else ""
        group_cells += (
            f'<th colspan="3" style="{group_th}{left_border}">'
            f'{p["month"]}월 ({pk})</th>'
        )

    # 2행: 하위 열
    sub_cells = ""
    for i, pk in enumerate(ps_keys):
        left_border = "border-left:1px solid #ddd;" if i > 0 else ""
        sub_cells += (
            f'<th style="{sub_th}{left_border}">최근 수위 (m)</th>'
            f'<th style="{sub_th}">과거 {n_gw}년 평균 (m)</th>'
            f'<th style="{sub_th}">편차 (m)</th>'
        )

    head = (
        '<table style="width:100%;border-collapse:collapse;table-layout:fixed;'
        'font-size:13px;">'
        + colgroup
        + '<thead>'
        '<tr>'
        f'<th rowspan="2" style="padding:6px 8px;background:#f5f5f3;'
        f'text-align:center;vertical-align:middle;border-bottom:1.5px solid #ccc;">'
        f'관측정</th>'
        + group_cells
        + '</tr>'
        '<tr>' + sub_cells + '</tr>'
        '</thead><tbody>'
    )

    base_td = 'padding:6px 4px;border-bottom:0.5px solid #eee;text-align:center;'
    body = ""
    for stn in stations:
        row = (
            '<tr>'
            f'<td style="{base_td}font-size:12px;font-weight:500;">{stn}</td>'
        )
        for i, pk in enumerate(ps_keys):
            left_border = "border-left:1px solid #ddd;" if i > 0 else ""
            actual = stn_data[stn][pk]["actual"]
            avg    = stn_data[stn][pk]["avg"]
            a_s = f"{actual:.2f}" if actual is not None else "–"
            v_s = f"{avg:.2f}"    if avg    is not None else "–"
            if actual is not None and avg is not None:
                d = actual - avg
                c = "#1d9e75" if d >= 0 else "#e24b4a"
                sg = "+" if d >= 0 else ""
                d_s = f'<span style="color:{c};font-weight:500;">{sg}{d:.2f}</span>'
            else:
                d_s = "–"
            row += (
                f'<td style="{base_td}{left_border}font-size:13px;font-weight:500;">{a_s}</td>'
                f'<td style="{base_td}color:#5f5e5a;">{v_s}</td>'
                f'<td style="{base_td}">{d_s}</td>'
            )
        row += '</tr>'
        body += row

    st.markdown(head + body + '</tbody></table>', unsafe_allow_html=True)
