# ==============================================================================
#  파일명: src/dashboard/tabs/tab41_population.py  —  Build 2.4
#  탭: 41.농가현황 (농업통계 그룹) — 농업용수 종합계획 보고서 재현형
#  레이아웃: 총괄 → AgriX → [Row1 B차트|D차트] [Row2 B표|D표] [Row3 A차트|C차트] [Row4 A표|C표]
#  2026-06-03 v2.4: 4행 2열 그리드, B 도전체 라인 색상 D와 통일(FARM)
#  데이터 신뢰성: 검증된 통계연보·AgriX 단일 출처만 사용 (추정값 제거)
# ==============================================================================
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.analysis import agri_stats_loader as L
from src.dashboard import agri_stats_helpers as H
from src.dashboard.quit_helper import quit_button

POP = "#185fa5"      # 인구(사파이어) — 보조
FARM = "#548235"     # 농가(올리브) — 도전체 라인 통일 색상
AGRIX = "#7E3A8A"
CITY = {"제주시": "#305496", "서귀포시": "#5B9BD5"}

EUP_ORDER = ["제주동", "구좌읍", "애월읍", "조천읍", "한림읍", "한경면",
             "서귀포동", "남원읍", "대정읍", "성산읍", "안덕면", "표선면"]
EUP_ORDER_FULL = EUP_ORDER[:6] + ["추자면", "우도면"] + EUP_ORDER[6:]


def _interleave_subtotals(df, value_cols, eup_col="읍면동"):
    """제주도 합계 → 제주시 소계 → 읍·면(행정순) → 서귀포시 소계 → 읍·면. 시군 중복 제거."""
    if df is None or df.empty:
        return df
    raw = df[~df[eup_col].isin(["계", "소계"])].copy()
    if raw.empty:
        return df
    _ord = {n: i for i, n in enumerate(EUP_ORDER_FULL)}
    raw["_ord"] = raw[eup_col].map(lambda n: _ord.get(str(n).strip(), 999))
    raw["_sg_ord"] = raw["시군"].map({"제주시": 0, "서귀포시": 1}).fillna(2)
    raw = raw.sort_values(["_sg_ord", "_ord"]).drop(columns=["_ord", "_sg_ord"])

    def _sub(label_sg, label_rg, mask):
        sub = raw if mask is None else raw[mask]
        row = {"시군": label_sg, eup_col: label_rg}
        for c in value_cols:
            try:
                row[c] = float(pd.to_numeric(sub[c], errors="coerce").sum())
            except Exception:
                row[c] = 0.0
        return row

    rows = [_sub("제주도", "합계", None)]
    je_m = raw["시군"] == "제주시"
    if je_m.any():
        rows.append(_sub("제주시", "소계", je_m))
        for _, r in raw[je_m].iterrows():
            rows.append(r.to_dict())
    sg_m = raw["시군"] == "서귀포시"
    if sg_m.any():
        rows.append(_sub("서귀포시", "소계", sg_m))
        for _, r in raw[sg_m].iterrows():
            rows.append(r.to_dict())
    disp = pd.DataFrame(rows)
    _prev = None
    _vals = []
    for _v in disp["시군"].tolist():
        _vals.append("" if _v == _prev else _v)
        _prev = _v
    disp["시군"] = _vals
    return disp


def _stacked_line_chart(years, je_vals, sg_vals, total_vals,
                        total_name="제주도", total_color=FARM,
                        height=340, ytitle="(명)", y_max=None):
    """B·D 공통: 스택바(제주시+서귀포) + 도전체 라인 + 값 라벨.

    y_max : None (기본) — total_vals 의 max × 1.15 로 자동 계산
            float       — 그 값을 y축 상한으로 강제 (두 차트의 Y축 동일화용)
    """
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=years, y=sg_vals, name="서귀포시",
        marker_color=CITY["서귀포시"],
        text=[f"{int(v):,}" if pd.notna(v) and v else "" for v in sg_vals],
        textposition="inside", textfont=dict(size=10, color="white"),
        hovertemplate="%{x}년 · 서귀포시<br>%{y:,.0f} 명<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        x=years, y=je_vals, name="제주시",
        marker_color=CITY["제주시"],
        text=[f"{int(v):,}" if pd.notna(v) and v else "" for v in je_vals],
        textposition="inside", textfont=dict(size=10, color="white"),
        hovertemplate="%{x}년 · 제주시<br>%{y:,.0f} 명<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=years, y=total_vals, name=total_name, mode="lines+markers",
        line=dict(color=total_color, width=2.5),
        marker=dict(size=8),
        hovertemplate="%{x}년 · " + total_name + "<br>%{y:,.0f} 명<extra></extra>",
    ))
    fig.add_trace(go.Scatter(
        x=years, y=total_vals, mode="text",
        text=[f"<b>{int(v):,}</b>" if pd.notna(v) and v else "" for v in total_vals],
        textposition="top center",
        textfont=dict(size=10, color="#1a1a18"),
        showlegend=False, hoverinfo="skip", cliponaxis=False,
    ))
    # 🆕 (2026-06-03) y_max 외부 override 지원 — 두 차트(B·D) Y축 동일화용
    if y_max is not None:
        _yrange = [0, float(y_max)]
    else:
        _ymax = max((v for v in total_vals if v), default=0)
        _yrange = [0, _ymax * 1.15] if _ymax else None
    fig.update_layout(
        barmode="stack", height=height, plot_bgcolor="white",
        margin=dict(l=10, r=10, t=30, b=30),
        xaxis=dict(title="연도", type="category"),
        yaxis=dict(title=ytitle, range=_yrange),
        legend=dict(orientation="h", y=1.10, font=dict(size=11)),
    )
    return fig


def _eup_bar_chart(d, value_col, ytitle, height=340):
    """A·C 공통: 읍·면·동 막대 + 값 라벨."""
    colors = [CITY.get(c, "#999") for c in d["시군"]]
    vals = d[value_col].tolist()
    fig = go.Figure(go.Bar(
        x=d["읍면동"], y=vals, marker_color=colors,
        text=[f"{int(v):,}" if pd.notna(v) else "" for v in vals],
        textposition="auto",
        hovertemplate="%{x}<br>" + value_col + ": %{y:,.0f}<extra></extra>",
    ))
    fig.update_layout(
        height=height, plot_bgcolor="white",
        margin=dict(l=10, r=10, t=24, b=80),
        yaxis=dict(title=ytitle),
        xaxis=dict(categoryorder="array",
                   categoryarray=d["읍면동"].tolist(), tickangle=-45),
    )
    return fig


# ─────────────────────────────────────────────────────────────────
#  데이터 로더 (각 섹션 공통)
# ─────────────────────────────────────────────────────────────────
def _b_data():
    pop = L.load_pop_yearly()
    if pop.empty:
        return None
    s = pop.sort_values("연도").reset_index(drop=True)
    return s


def _d_data():
    t = L.load_report("t22_farmpop_trend")
    if t.empty:
        return None
    t_sg = t[(t["읍면동"] == "소계") & (t["시군"].isin(["제주시", "서귀포시"]))].copy()
    t_dz = t[(t["시군"] == "제주도") & (t["읍면동"] == "계")].copy()
    if t_sg.empty:
        return None
    # 사용자 요청: 2017~ 표시
    t_sg = t_sg[t_sg["연도"] >= 2017]
    t_dz = t_dz[t_dz["연도"] >= 2017]
    yrs = sorted(int(y) for y in t_sg["연도"].unique())
    if not yrs:
        return None
    je = t_sg[t_sg["시군"] == "제주시"].set_index("연도")["농가인구"].to_dict()
    sg = t_sg[t_sg["시군"] == "서귀포시"].set_index("연도")["농가인구"].to_dict()
    dz = t_dz.set_index("연도")["농가인구"].to_dict()
    return {"yrs": yrs, "je": je, "sg": sg, "dz": dz}


def _a_data():
    return L.load_report("t20_pop_region")


def _c_data():
    t = L.load_report("t22_farmpop_trend")
    if t.empty:
        return None, None
    eup_rows = t[~t["읍면동"].isin(["계", "소계"])]
    if eup_rows.empty:
        return None, None
    base_yr = int(eup_rows["연도"].max())
    df_base = eup_rows[eup_rows["연도"] == base_yr][["시군", "읍면동", "농가인구"]].copy()
    return base_yr, df_base


# ─────────────────────────────────────────────────────────────────
#  Render (4행 2열 그리드)
# ─────────────────────────────────────────────────────────────────
@st.fragment
def render() -> None:
    # (2026-06-11 v2) 탭 제목 제거 — 하위탭 pill 문구와 중복 (사용자 요청)

    _render_summary_box()
    _render_agrix_box()
    st.markdown('<hr style="margin:12px 0;border:none;border-top:0.5px solid rgba(26,26,24,0.15);">',
                unsafe_allow_html=True)

    # ═════════════════ Row 1: 인구 차트 | 농가인구 차트 ═════════════════
    # 🆕 (2026-06-03) [B]/[D] 라벨 제거. 두 차트의 Y축을 동일화 하여
    #   전체 인구 대비 농가 인구 비중을 한눈에 비교 가능하도록 변경.
    b_data = _b_data()
    d_data = _d_data()

    # 두 차트의 도전체 총합 중 더 큰 값을 공통 Y축 상한으로 (× 1.15 여유)
    b_tot, d_tot = [], []
    yrs_b = je_b = sg_b = tot_b = []
    yrs_d = je_d = sg_d = tot_d = []
    if b_data is not None and not b_data.empty:
        yrs_b = [int(y) for y in b_data["연도"]]
        je_b = [float(v) for v in b_data["제주시인구"]]
        sg_b = [float(v) for v in b_data["서귀포시인구"]]
        tot_b = [float(v) for v in b_data["도전체인구"]]
    if d_data is not None:
        yrs_d = d_data["yrs"]
        je_d = [float(d_data["je"].get(y, 0)) for y in yrs_d]
        sg_d = [float(d_data["sg"].get(y, 0)) for y in yrs_d]
        tot_d = [float(d_data["dz"].get(y, je_d[i] + sg_d[i])) for i, y in enumerate(yrs_d)]
    _common_ymax = max(max(tot_b, default=0), max(tot_d, default=0)) * 1.15 or None

    col_l, col_r = st.columns(2)
    with col_l:
        if b_data is not None and not b_data.empty:
            y0, y1 = int(b_data["연도"].iloc[0]), int(b_data["연도"].iloc[-1])
            H.section_title("제주도 인구 변화 (시군별, %d~%d년)" % (y0, y1), top=0)
            fig_b = _stacked_line_chart(yrs_b, je_b, sg_b, tot_b,
                                        total_name="제주도", total_color=FARM,
                                        ytitle="인구 (명)",
                                        y_max=_common_ymax)
            st.plotly_chart(fig_b, use_container_width=True, key="b_pop_chart")
    with col_r:
        if d_data is not None:
            y0d, y1d = yrs_d[0], yrs_d[-1]
            H.section_title("제주도 농가인구 변화 (시군별, %d~%d년)" % (y0d, y1d), top=0)
            fig_d = _stacked_line_chart(yrs_d, je_d, sg_d, tot_d,
                                        total_name="제주도", total_color=FARM,
                                        ytitle="농가인구 (명) — 위 차트와 동일 축",
                                        y_max=_common_ymax)
            st.plotly_chart(fig_d, use_container_width=True, key="d_farmpop_chart")

    # ═════════════════ Row 2: B 표 | D 표 ═════════════════
    col_l, col_r = st.columns(2)
    with col_l:
        if b_data is not None and not b_data.empty:
            rows = []
            for _, r in b_data.iterrows():
                rows.append({
                    "연도": int(r["연도"]),
                    "제주도": format(int(r["도전체인구"]), ","),
                    "제주시": format(int(r["제주시인구"]), ","),
                    "서귀포시": format(int(r["서귀포시인구"]), ","),
                })
            st.markdown(H.html_table(pd.DataFrame(rows), highlight_last_row=True),
                        unsafe_allow_html=True)
            H.source_caption("제주통계연보 시군별 등록인구 (외국인 포함)")
    with col_r:
        if d_data is not None:
            yrs_d = d_data["yrs"]
            rows = []
            for y in yrs_d:
                je_v = int(d_data["je"].get(y, 0))
                sg_v = int(d_data["sg"].get(y, 0))
                dz_v = int(d_data["dz"].get(y, je_v + sg_v))
                rows.append({
                    "연도": y,
                    "제주도": format(dz_v, ","),
                    "제주시": format(je_v, ","),
                    "서귀포시": format(sg_v, ","),
                })
            st.markdown(H.html_table(pd.DataFrame(rows), highlight_last_row=True),
                        unsafe_allow_html=True)
            H.source_caption("〈표 2-22〉 농업경영체 등록정보 기준")

    st.markdown('<hr style="margin:16px 0;border:none;border-top:0.5px solid rgba(26,26,24,0.10);">',
                unsafe_allow_html=True)

    # ═════════════════ Row 3: 읍·면동 인구 차트 | 농가인구 차트 ═════════════════
    # 🆕 (2026-06-03) 제목의 [A]/[C] 라벨만 제거. 차트·표는 유지.
    a_df = _a_data()
    c_base_yr, c_df = _c_data()
    col_l, col_r = st.columns(2)
    with col_l:
        if a_df is not None and not a_df.empty:
            a_base = 2022
            H.section_title("읍·면동별 인구 현황 (기준년도 %d년)" % a_base, top=0)
            d = a_df[~a_df["읍면동"].isin(["계", "소계"])].copy()
            fig_a = _eup_bar_chart(d, "전체", ytitle="등록인구 (명)")
            st.plotly_chart(fig_a, use_container_width=True, key="a_pop_eup_chart")
    with col_r:
        if c_df is not None and not c_df.empty:
            H.section_title("읍·면동별 농가인구 현황 (기준년도 %d년)" % c_base_yr, top=0)
            fig_c = _eup_bar_chart(c_df, "농가인구", ytitle="농가인구 (명)")
            st.plotly_chart(fig_c, use_container_width=True, key="c_farmpop_eup_chart")

    # ═════════════════ Row 4: 인구 표 | 농가인구 표 ═════════════════
    col_l, col_r = st.columns(2)
    with col_l:
        if a_df is not None and not a_df.empty:
            disp = _interleave_subtotals(a_df, ["가구수", "남", "여", "전체"])
            for c in ("가구수", "남", "여", "전체"):
                disp[c] = disp[c].map(lambda v: format(int(round(v)), ",") if pd.notna(v) else "-")
            st.markdown(H.html_table(disp, headers=["시군", "읍·면·동", "가구수", "남", "여", "전체"]),
                        unsafe_allow_html=True)
            H.source_caption("제주특별자치도 농업용수 종합계획 보고서 〈표 2-20〉")
    with col_r:
        if c_df is not None and not c_df.empty:
            disp_c = _interleave_subtotals(c_df, ["농가인구"])
            disp_c["농가인구"] = disp_c["농가인구"].map(lambda v: format(int(round(v)), ",") if pd.notna(v) else "-")
            st.markdown(H.html_table(disp_c, headers=["시군", "읍·면·동", "농가인구"]),
                        unsafe_allow_html=True)
            H.source_caption("〈표 2-22〉 농업경영체 등록정보 기준")

    H.source_footer()


def _render_summary_box():
    pop_yr = L.load_pop_yearly()
    fh = L.load_farm_household()
    pop_latest = pop_yr.sort_values("연도").iloc[-1] if not pop_yr.empty else None
    dz = fh[fh["시군"] == "도전체"].sort_values("연도") if not fh.empty else pd.DataFrame()
    fp_latest = dz.iloc[-1] if not dz.empty else None
    cards = []
    if pop_latest is not None:
        y = int(pop_latest["연도"])
        cards.append(H.kpi_card("제주도 인구 (%d년)" % y, format(int(pop_latest["도전체인구"]), ",") + " 명",
            "제주시 " + format(int(pop_latest["제주시인구"]), ",") + " · 서귀포 " +
            format(int(pop_latest["서귀포시인구"]), ","), POP))
    if fp_latest is not None:
        yf = int(fp_latest["연도"])
        cards.append(H.kpi_card("농가인구 (%d년)" % yf, format(int(fp_latest["농가인구"]), ",") + " 명",
            "통계청 농림어업조사", FARM))
        share = (fp_latest["농가인구"] / float(pop_latest["도전체인구"]) * 100) if pop_latest is not None else None
        cards.append(H.kpi_card("인구대비 농가인구 (%d년)" % yf,
            (format(share, ".1f") + " %") if share is not None else "-",
            "농가인구 ÷ 제주도 인구", "#2f6aa8"))
        cards.append(H.kpi_card("농가호수 (%d년)" % yf, format(int(fp_latest["농가수"]), ",") + " 호",
            "전업 " + format(int(fp_latest["전업농가"]), ",") + " · 겸업 " +
            format(int(fp_latest["겸업농가"]), ","), FARM))
    if cards:
        H.kpi_row(cards)


def _render_agrix_box():
    """AgriX 농업경영체 등록정보 보조 KPI."""
    ax = L.load_agrix()
    if ax is None or ax.empty:
        return
    yrs = sorted(ax["연도"].unique().tolist())
    if not yrs:
        return
    y_latest = int(yrs[-1])
    y_prev = int(yrs[-2]) if len(yrs) >= 2 else None
    dz = ax[(ax["연도"] == y_latest) & (ax["시군"] == "도전체")]
    if dz.empty:
        return
    r = dz.iloc[0]
    je = ax[(ax["연도"] == y_latest) & (ax["시군"] == "제주시")]
    sg = ax[(ax["연도"] == y_latest) & (ax["시군"] == "서귀포시")]
    yoy_txt = ""
    if y_prev is not None:
        prev = ax[(ax["연도"] == y_prev) & (ax["시군"] == "도전체")]
        if not prev.empty:
            d = int(r["경영체수"]) - int(prev.iloc[0]["경영체수"])
            yoy_txt = f"전년 {y_prev} 대비 {d:+,}건"
    aged_pct = (float(r["고령자_65세이상"]) / float(r["경영체수"]) * 100) if r["경영체수"] else None
    pro_pct = (float(r["전업"]) / float(r["경영체수"]) * 100) if r["경영체수"] else None
    cards = [
        H.kpi_card(f"AgriX 농업경영체수 ({y_latest})", f"{int(r['경영체수']):,} 건",
                   yoy_txt or "농업경영체 등록정보 기준", AGRIX),
        H.kpi_card("전업 비율", (f"{pro_pct:.1f} %") if pro_pct is not None else "-",
                   f"전업 {int(r['전업']):,} / 겸업 {int(r['겸업']):,}", AGRIX),
        H.kpi_card("65세 이상 비중", (f"{aged_pct:.1f} %") if aged_pct is not None else "-",
                   f"{int(r['고령자_65세이상']):,} 건 (고령 경영주)", AGRIX),
    ]
    if not je.empty and not sg.empty:
        cards.append(H.kpi_card("시군 분포",
            f"제주 {int(je.iloc[0]['경영체수']):,} / 서귀포 {int(sg.iloc[0]['경영체수']):,}",
            "AgriX 등록 경영체 기준", AGRIX))
    H.section_title("AgriX 농업경영체 등록정보 비교", top=8)
    H.kpi_row(cards)
    st.caption(
        "출처: 농림축산식품부 농업경영체 등록정보 현황 서비스 "
        "([uni.agrix.go.kr](https://uni.agrix.go.kr/docs7/biOlap/)) · "
        "자료갱신 2026-03-17 · 추출 2026-06-03. "
        "※ AgriX '경영체수'는 통계연보 '농가수'와 정의가 달라 직접 대체가 아닌 보조지표로 병기합니다."
    )
