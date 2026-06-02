# ==============================================================================
#  파일명: src/dashboard/tabs/tab41_population.py  —  Build 2.0
#  탭: 41.농가현황 (농업통계 그룹) — 농업용수 종합계획 보고서 재현형
#  구성: 총괄박스(표2-19+2-21, 최신화) → 표2-20+막대 → 표2-22+누적막대
# ==============================================================================
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.analysis import agri_stats_loader as L
from src.dashboard import agri_stats_helpers as H
from src.dashboard.quit_helper import quit_button

POP = "#185fa5"      # 인구(사파이어)
FARM = "#548235"     # 농가(올리브)
CITY = {"제주시": "#305496", "서귀포시": "#5B9BD5"}

# 15차 Phase2-C: tab43과 동일한 interleave 표 형식 통일.
# 추자·우도 포함 행정순서 — 41/42에서만 사용 (43탭은 GeoJSON 12 features 기준이라 미포함).
EUP_ORDER = ["제주동", "구좌읍", "애월읍", "조천읍", "한림읍", "한경면",
             "서귀포동", "남원읍", "대정읍", "성산읍", "안덕면", "표선면"]
EUP_ORDER_FULL = EUP_ORDER[:6] + ["추자면", "우도면"] + EUP_ORDER[6:]


def _interleave_subtotals(df, value_cols, eup_col="읍면동"):
    """43탭 _render_year_comparison 표준 패턴 (L500~559) 재현.
    raw rows(시군/읍면동 + 값컬럼들)을 받아 interleave 구조로 반환:
      제주도 합계 → 제주시 소계 → 제주시 읍·면(행정순) → 서귀포시 소계 → 서귀포시 읍·면(행정순).
    시군 컬럼은 그룹 첫 행만 표시 (중복 제거).
    CSV에 이미 들어있던 '계'·'소계' 행은 제외하고 원본 행정구역 행만 사용해 재집계.
    """
    if df is None or df.empty:
        return df
    raw = df[~df[eup_col].isin(["계", "소계"])].copy()
    if raw.empty:
        return df

    _ord = {n: i for i, n in enumerate(EUP_ORDER_FULL)}
    raw["_ord"] = raw[eup_col].map(lambda n: _ord.get(str(n).strip(), 999))
    raw["_sg_ord"] = raw["시군"].map({"제주시": 0, "서귀포시": 1}).fillna(2)
    raw = raw.sort_values(["_sg_ord", "_ord"]).drop(columns=["_ord", "_sg_ord"])

    def _make_subtotal_row(label_sigun, label_region, mask):
        sub = raw if mask is None else raw[mask]
        row = {"시군": label_sigun, eup_col: label_region}
        for c in value_cols:
            try:
                row[c] = float(pd.to_numeric(sub[c], errors="coerce").sum())
            except Exception:
                row[c] = 0.0
        return row

    rows = []
    rows.append(_make_subtotal_row("제주도", "합계", None))
    je_mask = raw["시군"] == "제주시"
    if je_mask.any():
        rows.append(_make_subtotal_row("제주시", "소계", je_mask))
        for _, _r in raw[je_mask].iterrows():
            rows.append(_r.to_dict())
    sg_mask = raw["시군"] == "서귀포시"
    if sg_mask.any():
        rows.append(_make_subtotal_row("서귀포시", "소계", sg_mask))
        for _, _r in raw[sg_mask].iterrows():
            rows.append(_r.to_dict())
    disp = pd.DataFrame(rows)

    _prev_sg = None
    _sgun_vals = []
    for _v in disp["시군"].tolist():
        _sgun_vals.append("" if _v == _prev_sg else _v)
        _prev_sg = _v
    disp["시군"] = _sgun_vals
    return disp


@st.fragment  # 15차 Phase3 회귀 fix: 위젯 변경 시 다른 탭 튕김 방지 (AGENT_GUIDE §6)
def render() -> None:
    _t, _q = st.columns([10, 1])
    with _t:
        st.markdown('<p class="tab-title" style="margin:0;">41.농가현황</p>', unsafe_allow_html=True)
    with _q:
        quit_button("quit_in_tab41")

    _render_summary_box()
    st.markdown('<hr style="margin:12px 0;border:none;border-top:0.5px solid rgba(26,26,24,0.15);">',
                unsafe_allow_html=True)

    H.section_title("지역별 인구 현황 〈표 2-20〉", top=0)
    _render_t20()
    H.source_caption("제주특별자치도 농업용수 종합계획 보고서 〈표 2-20〉 (2022년 기준)")

    _render_change_tables()

    H.section_title("농가인구 변화 〈표 2-22〉")
    _render_t22()
    H.source_caption("〈표 2-22〉 농가인구 변화(2015~2022, 농업경영체 등록정보) + 통계연보 최신연도 확장")
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
            "농업경영체 등록 기준", FARM))
        share = (fp_latest["농가인구"] / float(pop_latest["도전체인구"]) * 100) if pop_latest is not None else None
        cards.append(H.kpi_card("인구대비 농가인구 (%d년)" % yf,
            (format(share, ".1f") + " %") if share is not None else "-",
            "농가인구 ÷ 제주도 인구", "#2f6aa8"))
        cards.append(H.kpi_card("농가호수 (%d년)" % yf, format(int(fp_latest["농가수"]), ",") + " 호",
            "전업 " + format(int(fp_latest["전업농가"]), ",") + " · 겸업 " +
            format(int(fp_latest["겸업농가"]), ","), FARM))
    if cards:
        H.kpi_row(cards)
    if not pop_yr.empty and not dz.empty:
        s = pop_yr.sort_values("연도")
        st.markdown(
            '<div style="font-size:13px;color:var(--color-text-secondary);margin-top:4px;">'
            '· 제주도 인구: ' + format(int(s.iloc[0]["도전체인구"]), ",") + '명(' + str(int(s.iloc[0]["연도"])) +
            ') → ' + format(int(s.iloc[-1]["도전체인구"]), ",") + '명(' + str(int(s.iloc[-1]["연도"])) + ')'
            ' &nbsp;|&nbsp; 농가인구: ' + format(int(dz.iloc[0]["농가인구"]), ",") + '명(' + str(int(dz.iloc[0]["연도"])) +
            ') → ' + format(int(dz.iloc[-1]["농가인구"]), ",") + '명(' + str(int(dz.iloc[-1]["연도"])) + ')</div>',
            unsafe_allow_html=True)


def _render_t20():
    df = L.load_report("t20_pop_region")
    if df.empty:
        st.caption("자료 없음"); return
    G_, T_ = st.columns([1, 1.1])
    with G_:
        d = df[~df["읍면동"].isin(["계", "소계"])].copy()
        colors = [CITY.get(c, "#999") for c in d["시군"]]
        fig = go.Figure(go.Bar(x=d["읍면동"], y=d["전체"], marker_color=colors,
                               text=[format(int(v), ",") for v in d["전체"]], textposition="auto"))
        fig.update_layout(height=460, plot_bgcolor="white", margin=dict(l=10, r=10, t=10, b=90),
                          yaxis=dict(title="등록인구 (명)"),
                          xaxis=dict(categoryorder="array",
                                     categoryarray=d["읍면동"].tolist(), tickangle=-45))
        st.plotly_chart(fig, use_container_width=True)
    with T_:
        # 15차 Phase2-C: 43탭 표준 interleave (제주도 합계 → 제주시 소계 → 읍면동 → 서귀포시 소계 → 읍면동)
        disp = _interleave_subtotals(df, ["가구수", "남", "여", "전체"])
        for c in ("가구수", "남", "여", "전체"):
            disp[c] = disp[c].map(lambda v: format(int(round(v)), ",") if pd.notna(v) else "-")
        st.markdown(H.html_table(disp, headers=["시군", "읍·면·동", "가구수", "남", "여", "전체"]),
                    unsafe_allow_html=True)


def _render_change_tables():
    pop = L.load_pop_yearly()
    if not pop.empty:
        s = pop.sort_values("연도")
        y0, y1 = int(s.iloc[0]["연도"]), int(s.iloc[-1]["연도"])
        H.section_title("제주도 인구 변화 (시군별, %d~%d)" % (y0, y1))
        G_, T_ = st.columns([1, 1.1])
        with G_:
            fig = go.Figure()
            for col, name, color in (("도전체인구", "제주도", POP),
                                     ("제주시인구", "제주시", CITY["제주시"]),
                                     ("서귀포시인구", "서귀포시", CITY["서귀포시"])):
                fig.add_trace(go.Scatter(x=s["연도"], y=s[col], name=name, mode="lines+markers",
                                         line=dict(color=color, width=2.5)))
            fig.update_layout(height=320, plot_bgcolor="white", margin=dict(l=10, r=10, t=24, b=30),
                              yaxis=dict(title="인구 (명)"),
                              legend=dict(orientation="h", y=1.12, font=dict(size=12)))
            fig.update_xaxes(tickvals=s["연도"].tolist())
            st.plotly_chart(fig, use_container_width=True)
        with T_:
            rows = []
            for col, name in (("도전체인구", "제주도"), ("제주시인구", "제주시"), ("서귀포시인구", "서귀포시")):
                v0, v1 = int(s.iloc[0][col]), int(s.iloc[-1][col])
                d = v1 - v0
                rate = (d / v0 * 100) if v0 else 0
                rows.append({"구분": name, "%d년" % y0: format(v0, ","), "%d년" % y1: format(v1, ","),
                             "증감(명)": format(d, "+,d"), "증감률": ("%+.1f%%" % rate)})
            st.markdown(H.html_table(pd.DataFrame(rows)), unsafe_allow_html=True)
        H.source_caption("제주통계연보 시군별 총인구 (%d~%d) — 읍·면·동 단위 다년도 총인구는 미공표"
                         % (y0, y1))

    t = L.load_report("t22_farmpop_trend")
    if not t.empty:
        yrs = sorted(int(y) for y in t["연도"].unique())
        ya, yb = yrs[0], yrs[-1]
        piv = t.pivot_table(index=["시군", "읍면동"], columns="연도",
                            values="농가인구", aggfunc="sum").reset_index()
        order = t.drop_duplicates(["시군", "읍면동"])[["시군", "읍면동"]]
        piv = order.merge(piv, on=["시군", "읍면동"], how="left")
        piv["증감"] = piv[yb] - piv[ya]
        piv["증감률"] = piv["증감"] / piv[ya] * 100
        H.section_title("읍면동별 농가인구 변화율 (%d → %d)" % (ya, yb))
        G_, T_ = st.columns([1, 1.1])
        with G_:
            d = piv[~piv["읍면동"].isin(["계", "소계"])].copy()
            colors = [CITY.get(c, "#999") for c in d["시군"]]
            fig = go.Figure(go.Bar(
                x=d["읍면동"], y=d["증감률"], marker_color=colors,
                text=[("%+.1f%%" % v) if pd.notna(v) else "" for v in d["증감률"]],
                textposition="auto"))
            fig.update_layout(height=460, plot_bgcolor="white", margin=dict(l=10, r=10, t=10, b=90),
                              yaxis=dict(title="농가인구 증감률 (%)"),
                              xaxis=dict(categoryorder="array",
                                         categoryarray=d["읍면동"].tolist(), tickangle=-45))
            st.plotly_chart(fig, use_container_width=True)
        with T_:
            disp = pd.DataFrame({
                "시군": piv["시군"], "읍·면·동": piv["읍면동"],
                "%d년" % ya: piv[ya].map(lambda v: format(int(v), ",") if pd.notna(v) else "-"),
                "%d년" % yb: piv[yb].map(lambda v: format(int(v), ",") if pd.notna(v) else "-"),
                "증감": piv["증감"].map(lambda v: format(int(v), "+,d") if pd.notna(v) else "-"),
                "증감률": piv["증감률"].map(lambda v: ("%+.1f%%" % v) if pd.notna(v) else "-"),
            })
            st.markdown(H.html_table(disp), unsafe_allow_html=True)
        H.source_caption("〈표 2-22〉 농가인구 (%d→%d) 증감률 — 농업경영체 등록정보" % (ya, yb))


def _render_t22():
    df = L.load_report("t22_farmpop_trend")
    if df.empty:
        st.caption("자료 없음"); return
    G_, T_ = st.columns([1, 1.15])
    with T_:
        piv = df.pivot_table(index=["시군", "읍면동"], columns="연도", values="농가인구", aggfunc="sum")
        piv = piv.reset_index()
        ycols = [c for c in piv.columns if isinstance(c, int)]
        # 15차 Phase2-C: 43탭 표준 interleave (제주도 합계 → 제주시 소계 → 읍면동 → 서귀포시 소계 → 읍면동)
        # 원본 CSV 의 '계'·'소계' 행을 제외하고 실제 읍면동만으로 재집계 후 소계를 다시 만듦.
        disp = _interleave_subtotals(piv, ycols)
        for c in ycols:
            disp[c] = disp[c].map(lambda v: format(int(round(v)), ",") if pd.notna(v) else "-")
        disp.columns = ["시군", "읍·면·동"] + [str(c) for c in ycols]
        st.markdown(H.html_table(disp), unsafe_allow_html=True)
    with G_:
        jeju = df[(df["시군"] == "제주시") & (df["읍면동"] == "소계")].set_index("연도")["농가인구"]
        seog = df[(df["시군"] == "서귀포시") & (df["읍면동"] == "소계")].set_index("연도")["농가인구"]
        yrs = sorted(jeju.index.tolist())
        fig = go.Figure()
        fig.add_trace(go.Bar(x=yrs, y=[seog.get(y) for y in yrs], name="서귀포시", marker_color=CITY["서귀포시"]))
        fig.add_trace(go.Bar(x=yrs, y=[jeju.get(y) for y in yrs], name="제주시", marker_color=CITY["제주시"]))
        ext = L.farmpop_total_trend_extended()
        fig.add_trace(go.Scatter(x=ext["연도"], y=ext["농가인구"], name="도전체(최신확장)",
                                 mode="lines+markers", line=dict(color="#C65911", width=2)))
        fig.update_layout(barmode="stack", height=460, plot_bgcolor="white",
                          margin=dict(l=10, r=10, t=24, b=30), yaxis=dict(title="농가인구 (명)"),
                          legend=dict(orientation="h", y=1.06, font=dict(size=12)))
        fig.update_xaxes(tickvals=yrs)
        st.plotly_chart(fig, use_container_width=True)
