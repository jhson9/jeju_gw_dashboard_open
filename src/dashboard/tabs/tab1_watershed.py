# ==============================================================================
#  파일명: src/dashboard/tabs/tab1_watershed.py
#  탭: ① 유역별 현황  —  Build 1.0 Final
#  기존 HTML 대시보드 v8의 탭1 완전 이식
# ==============================================================================

import re
import streamlit as st
import pandas as pd
import plotly.graph_objects as go

import config
from src.analysis import effective_rainfall
from src.dashboard import theme


def _hex_alpha(hex_col: str, alpha: float) -> str:
    h = hex_col.lstrip("#")
    r, g, b = int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)
    return f"rgba({r},{g},{b},{alpha})"

def _short_label(label: str) -> str:
    m = re.match(r"(\d{4})년 (\d+)월", str(label))
    return f"{m.group(1)[2:]}년 {m.group(2)}월" if m else label


# ==============================================================================
def render(asos_df: pd.DataFrame, ws_data_all: dict, periods: dict):

    # ── 유역 선택 ──────────
    # st.radio(horizontal=True): deselect 이슈가 없고 widget key 로 상태 관리됨.
    # segmented_control 의 "한 박자 늦은 반영 + 탭 튕김" 복합 버그를 해소.
    ws_names = [w["name"] for w in config.WATERSHEDS]
    ws_color = {w["name"]: w["color"] for w in config.WATERSHEDS}
    ws_aws   = {w["name"]: w["aws"]   for w in config.WATERSHEDS}

    if "tab1_ws_radio" not in st.session_state:
        st.session_state["tab1_ws_radio"] = ws_names[0]

    sel = st.radio(
        "유역 선택",
        options=ws_names,
        horizontal=True,
        key="tab1_ws_radio",
        label_visibility="collapsed",
    )
    # 하위 호환: 기존에 tab1_ws 를 참조하는 곳이 있을 수 있어 같이 동기화
    st.session_state["tab1_ws"] = sel
    nearby    = ws_aws.get(sel, "제주")
    ws_col    = ws_color.get(sel, "#185fa5")
    aws_col   = config.AWS_COLOR_MAP.get(nearby, "#378ADD")
    aws_code  = config.AWS_CODE_MAP.get(nearby, "")

    st.markdown(
        f'<p style="margin:8px 0 10px;">'
        f'<span style="font-size:16px;font-weight:600;color:{ws_col};">'
        f'● {sel} 유역 현황</span>'
        f'&nbsp;&nbsp;<span style="font-size:13px;color:#5f5e5a;">'
        f'(강수량 AWS: <strong>{nearby}</strong>)</span>'
        f'</p>',
        unsafe_allow_html=True
    )

    # ── 데이터 준비 ───────────────────────────────────────────
    has_asos = not asos_df.empty
    ws_df    = ws_data_all.get(sel) if ws_data_all else None
    has_ws   = (ws_df is not None and not ws_df.empty)

    if has_asos:
        monthly = effective_rainfall.aggregate_monthly(asos_df)
        half    = effective_rainfall.aggregate_half_monthly(asos_df)

    ps_keys = ["M-2", "M-1", "M"]
    ps      = [periods[k] for k in ps_keys]
    # 차트 X축 라벨 (축약): "11월 (M-2)"
    xlabels = [f"{p['month']}월 ({k})" for k, p in zip(ps_keys, ps)]
    n_rain  = config.RAINFALL_BASELINE_YEARS
    n_gw    = config.GWLEVEL_BASELINE_YEARS

    # ── M-2·M-1·M 요약 카드 (기존 HTML .card 스타일) ─────────
    card_cols = st.columns(3)
    for i, (pk, p) in enumerate(zip(ps_keys, ps)):
        ym = f"{p['year']}-{p['month']:02d}"
        bl = list(range(p["year"] - n_gw, p["year"]))

        rain_a = rain_v = gw_a = gw_v = None
        if has_asos:
            rain_a  = effective_rainfall.get_period_value(monthly, half, p, nearby, "월강수량(mm)")
            rain_v, _ = effective_rainfall.get_baseline_average(monthly, half, p, nearby, "월강수량(mm)", n_years=n_rain)
        if has_ws:
            ra = ws_df[ws_df["연월"] == ym]
            gw_a = float(ra["EL_평균"].iloc[0]) if not ra.empty else None
            bv = [float(ws_df[ws_df["연월"] == f"{y}-{p['month']:02d}"]["EL_평균"].iloc[0])
                  for y in bl
                  if not ws_df[ws_df["연월"] == f"{y}-{p['month']:02d}"].empty
                  and pd.notna(ws_df[ws_df["연월"] == f"{y}-{p['month']:02d}"]["EL_평균"].iloc[0])]
            gw_v = sum(bv)/len(bv) if bv else None

        def _diff(a, v, unit, dec=1):
            if a is None or v is None: return ""
            d = a - v
            c = "#1d9e75" if d >= 0 else "#e24b4a"
            s = "+" if d >= 0 else ""
            return f'<span style="color:{c};font-weight:500;">{s}{d:.{dec}f}{unit}</span>'

        is_m = (pk == "M")
        bg   = "#e6f1fb" if is_m else "#f5f5f3"
        bd   = "2px" if is_m else "1px"
        bd_c = ws_col if is_m else ws_col + "80"

        # 짧은 연도 (YY)
        yy_m      = str(p["year"])[2:]
        bl_r      = list(range(p["year"] - n_rain, p["year"]))
        yr_rain_s = f"{str(bl_r[0])[2:]}~{str(bl_r[-1])[2:]}"
        yr_gw_s   = f"{str(bl[0])[2:]}~{str(bl[-1])[2:]}"

        ra_str   = f"{rain_a:.0f} mm" if rain_a is not None else "–"
        rv_str   = f"{rain_v:.0f} mm" if rain_v is not None else "–"
        gw_str   = f"{gw_a:.2f} m"    if gw_a    is not None else "–"
        gv_str   = f"{gw_v:.2f} m"    if gw_v    is not None else "–"

        date_col = ws_col if is_m else "#1a1a18"

        html = (
            f'<div style="background:{bg};border:0.5px solid {ws_col}40;'
            f'border-left:{bd} solid {bd_c};border-radius:8px;padding:10px 12px;">'
            # 기간 헤더 — "2025년 11월 (M-2)" 중앙 정렬
            f'<p style="margin:0 0 8px;text-align:center;">'
            f'<span style="font-size:15px;font-weight:600;color:{date_col};">'
            f'{p["year"]}년 {p["month"]}월</span>'
            f'&nbsp;&nbsp;<span style="font-size:11px;color:#5f5e5a;">({pk})</span>'
            f'</p>'
            # 강수량 / 지하수위 그리드
            f'<div style="display:grid;grid-template-columns:1fr 8px 1fr;gap:6px;">'
            # ── 강수량 ──
            f'<div>'
            f'<p style="font-size:12px;color:#5f5e5a;margin:0 0 2px;">강수량 ({nearby})</p>'
            # 실측 + 월 레이블
            f'<p style="margin:0;">'
            f'<span style="font-size:18px;font-weight:500;">{ra_str}</span>'
            f'&nbsp;<span style="font-size:10px;color:#5f5e5a;">{yy_m}년 {p["month"]}월 평균</span>'
            f'</p>'
            # 직전 5년 평균 + 기간 레이블 + 편차
            f'<p style="margin:2px 0 0;">'
            f'<span style="font-size:15px;font-weight:500;color:#5f5e5a;">{rv_str}</span>'
            f'&nbsp;<span style="font-size:10px;color:#5f5e5a;">{yr_rain_s}년 {p["month"]}월 평균</span>'
            f'&nbsp;<span style="font-size:10px;color:#5f5e5a;">|</span>'
            f'&nbsp;<span style="font-size:10px;">{_diff(rain_a, rain_v, "mm")}</span>'
            f'</p>'
            f'</div>'
            f'<div style="background:rgba(26,26,24,0.12);"></div>'
            # ── 지하수위 (강수량과 동일 구조) ──
            f'<div>'
            f'<p style="font-size:12px;color:#5f5e5a;margin:0 0 2px;">지하수위 ({sel})</p>'
            # 실측 + 월 레이블
            f'<p style="margin:0;">'
            f'<span style="font-size:18px;font-weight:500;">{gw_str}</span>'
            f'&nbsp;<span style="font-size:10px;color:#5f5e5a;">{yy_m}년 {p["month"]}월 평균</span>'
            f'</p>'
            # 직전 3년 평균 + 기간 레이블 + 편차
            f'<p style="margin:2px 0 0;">'
            f'<span style="font-size:15px;font-weight:500;color:#5f5e5a;">{gv_str}</span>'
            f'&nbsp;<span style="font-size:10px;color:#5f5e5a;">{yr_gw_s}년 {p["month"]}월 평균</span>'
            f'&nbsp;<span style="font-size:10px;color:#5f5e5a;">|</span>'
            f'&nbsp;<span style="font-size:10px;">{_diff(gw_a, gw_v, "m", 2)}</span>'
            f'</p>'
            f'</div>'
            f'</div>'
            f'</div>'
        )
        with card_cols[i]:
            st.markdown(html, unsafe_allow_html=True)

    st.markdown("<div style='height:12px;'></div>", unsafe_allow_html=True)

    # ── 2열 차트: 강수량 + 지하수위 (나란히/grouped) ──────────
    ch1, ch2 = st.columns(2)

    # 차트용 데이터
    rain_act = rain_avg_v = eff_act = eff_avg_v = None
    gw_act_v = gw_avg_v = None
    if has_asos:
        rain_act   = [effective_rainfall.get_period_value(monthly, half, p, nearby, "월강수량(mm)") for p in ps]
        rain_avg_v = [effective_rainfall.get_baseline_average(monthly, half, p, nearby, "월강수량(mm)", n_years=n_rain)[0] for p in ps]

    if has_ws:
        gw_act_v = []
        gw_avg_v = []
        for p in ps:
            ym = f"{p['year']}-{p['month']:02d}"
            bl = list(range(p["year"] - n_gw, p["year"]))
            ra = ws_df[ws_df["연월"] == ym]
            gw_act_v.append(float(ra["EL_평균"].iloc[0]) if not ra.empty else None)
            bv = [float(ws_df[ws_df["연월"] == f"{y}-{p['month']:02d}"]["EL_평균"].iloc[0])
                  for y in bl
                  if not ws_df[ws_df["연월"] == f"{y}-{p['month']:02d}"].empty]
            gw_avg_v.append(sum(bv)/len(bv) if bv else None)

    # 범례/캡션용 문자열 — 차트와 표에서 공용으로 사용
    lbl_r_avg = f"과거 {n_rain}년 해당월 평균"
    lbl_r_act = "최근 강수량"
    lbl_g_avg = f"과거 {n_gw}년 해당월 평균"
    lbl_g_act = "최근 지하수위"

    recent_months = ", ".join(
        f"{str(p['year'])[2:]}년 {p['month']}월" for p in ps
    )
    baseline_rain_str = ", ".join(
        f"{str(p['year']-n_rain)[2:]}~{str(p['year']-1)[2:]}년 {p['month']}월"
        for p in ps
    )
    baseline_gw_str = ", ".join(
        f"{str(p['year']-n_gw)[2:]}~{str(p['year']-1)[2:]}년 {p['month']}월"
        for p in ps
    )
    caption_style = 'font-size:10px;color:#5f5e5a;margin:4px 0 0;'

    with ch1:
        st.markdown(
            f'<p style="font-size:15px;font-weight:600;margin:0 0 4px;">강수량(mm)</p>',
            unsafe_allow_html=True
        )
        _legend_row(lbl_r_avg, lbl_r_act, aws_col)
        if has_asos and rain_act:
            fig = _grouped_bar(xlabels, rain_avg_v, rain_act, aws_col,
                               lbl_r_avg, lbl_r_act, "mm", decimals=0)
            st.plotly_chart(fig, use_container_width=True, key=f"t1_rain_{sel}")
            st.markdown(
                f'<p style="{caption_style}">'
                f'* 최근 월 강수량 : {recent_months}'
                f' &nbsp;|&nbsp; 과거 {n_rain}년 해당월 : {baseline_rain_str}</p>',
                unsafe_allow_html=True
            )
        else:
            st.info("ASOS 데이터 없음")

    with ch2:
        st.markdown(
            f'<p style="font-size:15px;font-weight:600;margin:0 0 4px;">지하수위(EL)</p>',
            unsafe_allow_html=True
        )
        _legend_row(lbl_g_avg, lbl_g_act, ws_col)
        if has_ws and gw_act_v:
            all_v = [v for v in gw_act_v + gw_avg_v if v is not None]
            y_min = min(all_v) * 0.96 if all_v else 0
            fig = _grouped_bar(xlabels, gw_avg_v, gw_act_v, ws_col,
                               lbl_g_avg, lbl_g_act, "m", y_min=y_min, decimals=2)
            st.plotly_chart(fig, use_container_width=True, key=f"t1_gw_{sel}")
            st.markdown(
                f'<p style="{caption_style}">'
                f'* 최근 월 수위 : {recent_months}'
                f' &nbsp;|&nbsp; 과거 {n_gw}년 해당월 : {baseline_gw_str}</p>',
                unsafe_allow_html=True
            )
        else:
            st.info(f"{sel} 유역 지하수위 데이터 없음")

    st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

    # ── 표 A: 강수량 + 유효강수일수 ─────────────────────────
    st.markdown(
        f'<p style="font-size:15px;font-weight:600;margin:0 0 4px;">'
        f'강수량 및 농업유효강수일수 : {nearby} ({aws_code})</p>'
        f'<p style="font-size:10px;color:#5f5e5a;margin:0 0 8px;">'
        f'농업유효강수일수: 일강수량 {config.EFFECTIVE_RAINFALL_THRESHOLD_MM} mm 이상</p>',
        unsafe_allow_html=True
    )
    if has_asos:
        _render_aws_table(monthly, half, periods, nearby, ps_keys)
        st.markdown(
            f'<p style="font-size:10px;color:#5f5e5a;margin:4px 0 0;">'
            f'* 최근 월 강수량 : {recent_months}'
            f' &nbsp;|&nbsp; 과거 {n_rain}년 해당월 : {baseline_rain_str}</p>',
            unsafe_allow_html=True
        )
    else:
        st.info("ASOS 데이터 없음")

    st.markdown("<div style='height:12px;'></div>", unsafe_allow_html=True)

    # ── 표 B: 유역 지하수위 현황 ──────────────────────────────
    st.markdown(
        f'<p style="font-size:15px;font-weight:600;margin:0;">'
        f'지하수위(EL) 현황 : {sel}유역</p>',
        unsafe_allow_html=True
    )
    st.markdown("<div style='height:4px;'></div>", unsafe_allow_html=True)
    if has_ws:
        _render_gw_table(ws_df, periods, ps_keys)
        st.markdown(
            f'<p style="font-size:10px;color:#5f5e5a;margin:4px 0 0;">'
            f'* 최근 월 수위 : {recent_months}'
            f' &nbsp;|&nbsp; 과거 {n_gw}년 해당월 : {baseline_gw_str}</p>',
            unsafe_allow_html=True
        )
    else:
        st.info("지하수위 데이터 없음")


# ==============================================================================
#  ■ 차트 헬퍼
# ==============================================================================
def _legend_html(label: str, color: str, outline: bool):
    if outline:
        box = f'<span style="width:10px;height:10px;border-radius:2px;border:1.5px solid {color};display:inline-block;"></span>'
    else:
        box = f'<span style="width:10px;height:10px;border-radius:2px;background:{color};display:inline-block;"></span>'
    st.markdown(
        f'<span style="display:inline-flex;align-items:center;gap:4px;'
        f'font-size:11px;color:#5f5e5a;margin-right:10px;">{box} {label}</span>',
        unsafe_allow_html=True
    )


def _legend_row(label_avg: str, label_act: str, color: str):
    """평균(외곽선) + 실측(채움) 범례를 한 줄로 렌더링."""
    box_avg = (f'<span style="width:10px;height:10px;border-radius:2px;'
               f'border:1.5px solid {color};display:inline-block;"></span>')
    box_act = (f'<span style="width:10px;height:10px;border-radius:2px;'
               f'background:{color};display:inline-block;"></span>')
    st.markdown(
        f'<div style="font-size:11px;color:#5f5e5a;margin:0 0 4px;">'
        f'<span style="display:inline-flex;align-items:center;gap:4px;margin-right:14px;">'
        f'{box_avg} {label_avg}</span>'
        f'<span style="display:inline-flex;align-items:center;gap:4px;">'
        f'{box_act} {label_act}</span>'
        f'</div>',
        unsafe_allow_html=True
    )


def _grouped_bar(xlabels, avg_vals, act_vals, color, avg_name, act_name, unit,
                 y_min=None, decimals=1):
    """평균=투명+테두리, 실측=채움, grouped. 실측 바 위에 값 라벨 표시."""
    def _fmt(v):
        return "" if v is None else f"{v:.{decimals}f}"

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name=avg_name, x=xlabels, y=avg_vals,
        marker=dict(color=_hex_alpha(color, 0.18), line=dict(color=color, width=1.5)),
        text=[_fmt(v) for v in avg_vals],
        textposition="outside",
        textfont=dict(size=10, color="#5f5e5a"),
        cliponaxis=False,
        hovertemplate=f"%{{x}}<br>{avg_name}: %{{y:.2f}} {unit}<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        name=act_name, x=xlabels, y=act_vals,
        marker=dict(color=color),
        text=[_fmt(v) for v in act_vals],
        textposition="outside",
        textfont=dict(size=10, color="#1a1a18"),
        cliponaxis=False,
        hovertemplate=f"%{{x}}<br>{act_name}: %{{y:.2f}} {unit}<extra></extra>",
    ))
    layout = dict(
        barmode="group", height=220,
        xaxis_title="", yaxis_title=unit,
        xaxis=dict(tickfont=dict(size=12)),      # X축 라벨 1사이즈 확대
        bargap=0.35,                              # 기간 그룹 간격
        bargroupgap=0.18,                         # 평균/실측 바 사이 간격
        margin=dict(t=14, b=4, l=38, r=8),
        showlegend=False, font=dict(size=11),
    )
    if y_min is not None:
        layout["yaxis"] = dict(range=[y_min, None])
    fig.update_layout(**layout)
    return fig


# ==============================================================================
#  ■ 표 렌더링
# ==============================================================================
def _yr3(y): return f"{y-3}~{y-1}년"
def _yr5(y): return f"{y-5}~{y-1}년"

def _th(text, width="", extra=""):
    w = f"width:{width};" if width else ""
    return (f'<th style="padding:6px 8px;border-bottom:1px solid #ccc;'
            f'background:#f5f5f3;{w}{extra}">{text}</th>')

def _td(text, extra=""):
    return f'<td style="padding:6px 8px;border-bottom:0.5px solid #eee;{extra}">{text}</td>'

def _diff_str(a, v, unit, dec=1):
    if a is None or v is None: return "–"
    d = a - v
    c = "#1d9e75" if d >= 0 else "#e24b4a"
    s = "+" if d >= 0 else ""
    return (f'<span style="color:{c};font-weight:500;">'
            f'{s}{d:.{dec}f}{unit}</span>')


def _render_gw_table(ws_df, periods, ps_keys):
    """기간=행, 지표=열 구조.
    열: 기간 | 최근 월 수위 (m) | 과거 N년 해당월 평균 (m) | 지하수위 편차 (m)
    table-layout:fixed 로 열 폭을 균등 분배."""
    ps = [periods[k] for k in ps_keys]
    n  = config.GWLEVEL_BASELINE_YEARS

    # colgroup: 기간 = 공용 120px, 데이터 3열 = 균등 분배(33% 씩)
    colgroup = (
        '<colgroup>'
        '<col style="width:360px;">'
        '<col><col><col>'
        '</colgroup>'
    )

    head = (
        '<table style="width:100%;border-collapse:collapse;'
        'table-layout:fixed;font-size:13px;">'
        + colgroup
        + '<thead><tr style="background:#f5f5f3;">'
        + _th("기간", extra="text-align:center;border-bottom:1.5px solid #ccc;")
        + _th("최근 월 수위 (m)", extra="text-align:center;border-bottom:1.5px solid #ccc;")
        + _th(f"과거 {n}년 해당월 평균 (m)", extra="text-align:center;border-bottom:1.5px solid #ccc;")
        + _th("지하수위 편차 (m)", extra="text-align:center;border-bottom:1.5px solid #ccc;")
        + '</tr></thead><tbody>'
    )

    body = ""
    for pk, p in zip(ps_keys, ps):
        ym = f"{p['year']}-{p['month']:02d}"
        bl = list(range(p["year"] - n, p["year"]))
        ra = ws_df[ws_df["연월"] == ym]
        actual = float(ra["EL_평균"].iloc[0]) if not ra.empty else None
        bv = [float(ws_df[ws_df["연월"] == f"{y}-{p['month']:02d}"]["EL_평균"].iloc[0])
              for y in bl
              if not ws_df[ws_df["연월"] == f"{y}-{p['month']:02d}"].empty]
        avg = sum(bv)/len(bv) if bv else None
        diff = round(actual - avg, 2) if (actual is not None and avg is not None) else None

        a_s = f'<span style="font-size:14px;font-weight:600;">{actual:.2f}</span>' if actual is not None else "–"
        v_s = f'{avg:.2f}' if avg is not None else "–"
        d_s = _diff_cell(diff, "") if diff is not None else "–"

        body += (
            '<tr>'
            f'<td style="padding:6px 8px;border-bottom:0.5px solid #eee;text-align:center;">'
            f'<div style="font-size:13px;font-weight:500;">{p["month"]}월</div>'
            f'<div style="font-size:11px;color:#5f5e5a;">({pk})</div>'
            f'</td>'
            f'<td style="padding:6px 8px;border-bottom:0.5px solid #eee;text-align:center;">{a_s}</td>'
            f'<td style="padding:6px 8px;border-bottom:0.5px solid #eee;text-align:center;">{v_s}</td>'
            f'<td style="padding:6px 8px;border-bottom:0.5px solid #eee;text-align:center;">{d_s}</td>'
            '</tr>'
        )
    st.markdown(head + body + "</tbody></table>", unsafe_allow_html=True)


def _diff_cell(val, unit, is_pct=False):
    if val is None: return "–"
    c = "#1d9e75" if val >= 0 else "#e24b4a"
    s = "+" if val >= 0 else ""
    return f'<span style="color:{c};font-weight:500;">{s}{val}{unit}</span>'


def _render_aws_table(monthly, half, periods, station, ps_keys):
    """기간=행, 지표=열 구조.
    열: 기간 | 최근 월강수량 | 과거 5년 평균 | 강수량 편차 |
         금년 해당월 유효강수 | 과거 5년 해당월 유효강수 | 유효강수일수 편차"""
    ps    = [periods[k] for k in ps_keys]
    n_r   = config.RAINFALL_BASELINE_YEARS

    # 2단 헤더: 1행은 그룹(강수량 / 농업유효 강수일수), 2행은 하위 열
    # table-layout:fixed + colgroup 으로 6개 데이터 열은 균등 폭으로 표시
    group_th_base = (
        'padding:6px 8px;background:#f5f5f3;text-align:center;'
        'border-bottom:1px solid #ddd;font-weight:600;'
    )
    sub_th_base = (
        'padding:5px 6px;background:#f5f5f3;text-align:center;'
        'border-bottom:1.5px solid #ccc;font-size:11px;font-weight:500;color:#5f5e5a;'
    )

    colgroup = (
        '<colgroup>'
        '<col style="width:360px;">'      # 기간
        '<col><col><col>'                 # 강수량 3열 (균등)
        '<col><col><col>'                 # 유효강수 3열 (균등)
        '</colgroup>'
    )

    head = (
        '<table style="width:100%;border-collapse:collapse;'
        'table-layout:fixed;font-size:13px;">'
        + colgroup
        + '<thead>'
        # ── 1행: 그룹 헤더
        '<tr>'
        f'<th rowspan="2" style="padding:6px 8px;background:#f5f5f3;text-align:center;'
        f'vertical-align:middle;border-bottom:1.5px solid #ccc;">기간</th>'
        f'<th colspan="3" style="{group_th_base}">강수량 (mm)</th>'
        f'<th colspan="3" style="{group_th_base}border-left:1px solid #ddd;">'
        f'농업유효 강수일수 (일)</th>'
        '</tr>'
        # ── 2행: 하위 열
        '<tr>'
        f'<th style="{sub_th_base}">최근 월강수량</th>'
        f'<th style="{sub_th_base}">과거 {n_r}년 해당월 평균</th>'
        f'<th style="{sub_th_base}">편차</th>'
        f'<th style="{sub_th_base}border-left:1px solid #ddd;">최근 유효강수</th>'
        f'<th style="{sub_th_base}">과거 {n_r}년 해당월 평균</th>'
        f'<th style="{sub_th_base}">편차</th>'
        '</tr>'
        '</thead><tbody>'
    )

    body = ""
    for pk, p in zip(ps_keys, ps):
        ra   = effective_rainfall.get_period_value(monthly, half, p, station, "월강수량(mm)")
        rv,_ = effective_rainfall.get_baseline_average(monthly, half, p, station, "월강수량(mm)", n_years=n_r)
        ea   = effective_rainfall.get_period_value(monthly, half, p, station, "유효강수일수(일)")
        ev,_ = effective_rainfall.get_baseline_average(monthly, half, p, station, "유효강수일수(일)", n_years=n_r)

        ra_s = f'<span style="font-size:14px;font-weight:600;">{ra:.0f}</span>' if ra is not None else "–"
        rv_s = f"{rv:.0f}" if rv is not None else "–"
        rd_s = _diff_str(ra, rv, "", dec=0) if (ra is not None and rv is not None) else "–"
        ea_s = f'<span style="font-size:14px;font-weight:600;">{int(round(ea))}</span>' if ea is not None else "–"
        ev_s = f"{ev:.1f}" if ev is not None else "–"
        ed_s = _diff_str(ea, ev, "", dec=0) if (ea is not None and ev is not None) else "–"

        base_td = 'padding:6px 8px;border-bottom:0.5px solid #eee;text-align:center;'
        body += (
            '<tr>'
            f'<td style="{base_td}">'
            f'<div style="font-size:13px;font-weight:500;">{p["month"]}월</div>'
            f'<div style="font-size:11px;color:#5f5e5a;">({pk})</div>'
            f'</td>'
            f'<td style="{base_td}">{ra_s}</td>'
            f'<td style="{base_td}">{rv_s}</td>'
            f'<td style="{base_td}">{rd_s}</td>'
            f'<td style="{base_td}border-left:1px solid #ddd;">{ea_s}</td>'
            f'<td style="{base_td}">{ev_s}</td>'
            f'<td style="{base_td}">{ed_s}</td>'
            '</tr>'
        )
    st.markdown(head + body + "</tbody></table>", unsafe_allow_html=True)


def _hex_alpha(hex_col: str, alpha: float) -> str:
    h = hex_col.lstrip("#")
    r, g, b = int(h[0:2],16), int(h[2:4],16), int(h[4:6],16)
    return f"rgba({r},{g},{b},{alpha})"
