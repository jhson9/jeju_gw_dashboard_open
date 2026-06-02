# ==============================================================================
#  파일명: src/dashboard/tabs/tab42_farm_household.py  —  Build 2.0
#  탭: 42.농경지현황 (농업통계 그룹) — 농업용수 종합계획 보고서 재현형
#  구성: 농지/경지/작물 박스 → 설명 → 표2-23+추이 → 표2-24+누적막대
#        → 표2-25+그림2-19(stacked) → 표2-26 → 표2-27 수혜구역
# ==============================================================================
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.analysis import agri_stats_loader as L
from src.analysis import landcover_loader as LCL
from src.dashboard import agri_stats_helpers as H
from src.dashboard.quit_helper import quit_button

C_NONGJI = "#548235"    # 농지(올리브)
C_GYEONGJI = "#185fa5"  # 경지(사파이어)
C_CROP = "#C65911"      # 작물(테라코타)
C_GREENHOUSE = "#2E8B57"  # 시설재배(SeaGreen — 농업+물 함의, 2026-05-30 신설)
CITY = {"제주시": "#305496", "서귀포시": "#5B9BD5"}
CROP_CATS = ["식량작물", "채소류", "과실류", "특용작물", "사료작물", "기타"]
CROP_COLORS = {"식량작물": "#C65911", "채소류": "#548235", "과실류": "#D9A441",
               "특용작물": "#7E3A8A", "사료작물": "#5B9BD5", "기타": "#A6A6A6"}

# 보고서 행정구역 순서 (추자·우도 미포함 — EUP GeoJSON 12 features 기준)
EUP_ORDER = ["제주동", "구좌읍", "애월읍", "조천읍", "한림읍", "한경면",
             "서귀포동", "남원읍", "대정읍", "성산읍", "안덕면", "표선면"]

# 15차 Phase2-C: 추자·우도 포함 행정순서 — 통계 표용 (GeoJSON 미사용 부분).
# 시설재배 EUP map(tab42 _render_t25_5_greenhouse)·tab43 choropleth는 EUP_ORDER 그대로.
EUP_ORDER_FULL = EUP_ORDER[:6] + ["추자면", "우도면"] + EUP_ORDER[6:]


def _interleave_subtotals(df, value_cols, eup_col="읍면동"):
    """43탭 _render_year_comparison 표준 패턴 (L500~559) 재현 — tab42용.
    raw rows(시군/읍면동 + 값컬럼들) → interleave 구조:
      제주도 합계 → 제주시 소계 → 제주시 읍·면(행정순) → 서귀포시 소계 → 서귀포시 읍·면(행정순).
    CSV 의 '계'·'소계' 행은 제외하고 실제 행정구역만으로 재집계.
    추자·우도가 데이터에 있으면 제주시 그룹에 포함 (EUP_ORDER_FULL 순서).
    """
    if df is None or df.empty:
        return df
    raw = df[~df[eup_col].isin(["계", "소계"])].copy()
    # '기타' 같은 비표준 시군 행도 표에서 제외 (t26: '기타(우도,가파도)')
    raw = raw[raw["시군"].isin(["제주시", "서귀포시"])].copy()
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
        st.markdown('<p class="tab-title" style="margin:0;">42.농경지현황</p>', unsafe_allow_html=True)
    with _q:
        quit_button("quit_in_tab42")

    _render_boxes()
    _render_defs()
    st.markdown('<hr style="margin:10px 0;border:none;border-top:0.5px solid rgba(26,26,24,0.15);">',
                unsafe_allow_html=True)

    H.section_title("농경지 면적 변화 〈표 2-23〉", top=0)
    _render_t23()
    H.source_caption("〈표 2-23〉 농경지 면적 변화(2011~2022) + 통계연보 경지면적 최신연도 확장")

    H.section_title("지역별 농경지 면적 〈표 2-24〉 (2021년)")
    _render_t24()
    H.source_caption("〈표 2-24〉 지역별 농경지 면적 (보고서 2021년 기준)")

    H.section_title("작물 종류별 재배면적 〈표 2-25〉 / 〈그림 2-19〉")
    _render_t25()
    H.source_caption("〈표 2-25〉·〈그림 2-19〉 연도별 재배작물 면적 (2011~2022)")

    _render_t25_5_greenhouse()

    H.section_title("지역별 재배작물 면적 〈표 2-26〉 (2022년)")
    _render_t26()
    H.source_caption("〈표 2-26〉 지역별 재배작물 면적 (보고서 2022년 기준)")

    H.section_title("농업용수 수혜구역 〈표 2-27〉 (2023년)")
    _render_t27()
    H.source_caption("〈표 2-27〉 농업용수 수혜구역 (1994~2023 밭기반정비사업 누적)")
    H.source_footer()


def _box3pt(tbl, col, color, label, unit="ha", target=None):
    def _val(y):
        r = tbl[tbl["연도"] == y]
        return int(r[col].iloc[0]) if (not r.empty and pd.notna(r[col].iloc[0])) else None
    pts = [(y, _val(y)) for y in (2012, 2017, 2022)]
    if pts[-1][1] is None:
        last = tbl.dropna(subset=[col]).sort_values("연도")
        if not last.empty:
            pts[-1] = (int(last.iloc[-1]["연도"]), int(last.iloc[-1][col]))
    latest_y, latest_v = pts[-1]
    big = (format(latest_v, ",") + unit) if latest_v is not None else "-"
    sub_parts = [format(v, ",") + unit + "(" + str(y) + ")" for y, v in pts[:-1] if v is not None]
    sub = " · ".join(sub_parts)
    if target:
        sub += " · 목표 " + format(target[1], ",") + unit + "(" + str(target[0]) + ")"
    return H.kpi_card("%s (%d년)" % (label, latest_y), big, sub, color)


def _render_boxes():
    t = L.load_report("t23_farmland_trend")
    if t.empty:
        return
    H.kpi_row([
        _box3pt(t, "농지면적", C_NONGJI, "농지면적"),
        _box3pt(t, "경지면적", C_GYEONGJI, "경지면적"),
        _box3pt(t, "작물재배면적", C_CROP, "작물재배면적", target=(2030, 67533)),
    ])


def _render_defs():
    st.markdown(
        '<div style="font-size:12.5px;color:var(--color-text-secondary);line-height:1.6;margin:4px 0 2px;">'
        '· <b>농지면적</b>: 토지 지목상 논·밭·과수원의 면적<br>'
        '· <b>경지면적</b>: 지목에 관계없이 농사짓는 경작지(임야·목초지 등 포함)<br>'
        '· <b>작물재배면적</b>: 작물별 재배면적의 합산(이모작 시 면적 중복 적용)</div>',
        unsafe_allow_html=True)


def _render_t23():
    ext = L.farmland_trend_extended()
    rep = L.load_report("t23_farmland_trend")
    G_, T_ = st.columns([1.1, 1])
    with G_:
        fig = go.Figure()
        for col, color, name in (("농지면적", C_NONGJI, "농지면적"),
                                 ("경지면적", C_GYEONGJI, "경지면적"),
                                 ("작물재배면적", C_CROP, "작물재배면적")):
            d = ext.dropna(subset=[col])
            fig.add_trace(go.Scatter(x=d["연도"], y=d[col], name=name, mode="lines+markers",
                                     line=dict(color=color, width=2.5)))
        fig.update_layout(height=360, plot_bgcolor="white", margin=dict(l=10, r=10, t=24, b=30),
                          yaxis=dict(title="면적 (ha)"), legend=dict(orientation="h", y=1.08, font=dict(size=12)))
        st.plotly_chart(fig, use_container_width=True)
    with T_:
        disp = rep.copy()
        for c in ("농지면적", "경지면적", "작물재배면적"):
            disp[c] = disp[c].map(lambda v: format(int(v), ",") if pd.notna(v) else "-")
        st.markdown(H.html_table(disp, headers=["연도", "농지면적", "경지면적", "작물재배면적"],
                                 highlight_last_row=True), unsafe_allow_html=True)


def _render_t24():
    df = L.load_report("t24_farmland_region")
    if df.empty:
        st.caption("자료 없음"); return
    G_, T_ = st.columns([1, 1.1])
    with G_:
        d = df[~df["읍면동"].isin(["계", "소계"])].copy()
        colors = [CITY.get(c, "#999") for c in d["시군"]]
        fig = go.Figure(go.Bar(x=d["읍면동"], y=d["농지면적"], marker_color=colors,
                               text=[format(int(v), ",") for v in d["농지면적"]], textposition="auto"))
        fig.update_layout(height=400, plot_bgcolor="white", margin=dict(l=10, r=10, t=10, b=90),
                          yaxis=dict(title="농지면적 (ha)"),
                          xaxis=dict(categoryorder="array",
                                     categoryarray=d["읍면동"].tolist(), tickangle=-45))
        st.plotly_chart(fig, use_container_width=True)
    with T_:
        # 15차 Phase2-C: 43탭 표준 interleave 적용 (추자·우도 포함).
        disp = _interleave_subtotals(df, ["농지면적"])
        disp["농지면적"] = disp["농지면적"].map(
            lambda v: format(int(round(v)), ",") if pd.notna(v) else "-")
        st.markdown(H.html_table(disp, headers=["시군", "읍·면·동", "농지면적(ha)"]), unsafe_allow_html=True)


def _render_t25():
    df = L.load_report("t25_crop_trend")
    if df.empty:
        st.caption("자료 없음"); return
    G_, T_ = st.columns([1.15, 1])
    with G_:
        fig = go.Figure()
        for cat in CROP_CATS:
            fig.add_trace(go.Bar(x=df["연도"], y=df[cat], name=cat, marker_color=CROP_COLORS[cat]))
        fig.update_layout(barmode="stack", height=380, plot_bgcolor="white",
                          margin=dict(l=10, r=10, t=24, b=30), yaxis=dict(title="재배면적 (ha)"),
                          legend=dict(orientation="h", y=1.08, font=dict(size=11)),
                          title=dict(text="〈그림 2-19〉 연도별 재배작물 면적", font=dict(size=12), x=0.5))
        fig.update_xaxes(tickvals=df["연도"].tolist())
        st.plotly_chart(fig, use_container_width=True)
    with T_:
        disp = df.copy()
        for c in ["계"] + CROP_CATS:
            disp[c] = disp[c].map(lambda v: format(int(v), ",") if pd.notna(v) else "-")
        st.markdown(H.html_table(disp, highlight_last_row=True), unsafe_allow_html=True)


def _render_t25_5_greenhouse():
    """시설재배지(비닐하우스·온실) 면적·분포 — EGIS WFS vector 폴리곤 기반.
    데이터 빌드: scripts/build_greenhouse_stats.py --all --region 1회 실행.
    """
    yr = LCL.load_greenhouse_yearly()
    if yr.empty:
        H.section_title("시설재배지 면적 변화 〈표 2-16〉")
        st.info(
            "시설재배지 데이터가 아직 빌드되지 않았습니다.\n\n"
            "PC에서 `python scripts/build_greenhouse_stats.py --all --region` 를 1회 실행하면 "
            "이 섹션에 〈표2-16〉·〈표2-17〉 + 분포 지도가 나타납니다."
        )
        return

    H.section_title("시설재배지 면적 변화 〈표 2-16〉")

    st.markdown(
        '<div style="font-size:12.5px;color:var(--color-text-secondary);'
        'line-height:1.6;margin:4px 0 6px;">'
        '· <b>작물재배면적</b>: 노지·시설을 모두 포함한 경작 전체 면적(이모작 시 중복 합산) — 농업통계연보 기준<br>'
        '· <b>시설재배면적</b>: 비닐하우스·온실 등 피복시설 내 재배면적 — '
        '환경공간정보서비스(EGIS) 토지피복지도 Lv2 코드 230(하우스재배지) / Lv3 코드 231(시설재배지) 폴리곤 면적<br>'
        '· <span style="color:#B45309;">※ 2013년부터 Lv3(5m 해상도) 적용으로 보고서(Lv2 30m) 대비 일관적으로 '
        '+20~30% 더 많이 측정됨. 같은 방법론(Lv3) 구간 내 시계열 추이는 정확.</span></div>',
        unsafe_allow_html=True,
    )

    yr_sorted = yr.sort_values("연도").copy()
    base2000 = (
        float(yr_sorted.loc[yr_sorted["연도"] == 2000, "면적_ha"].iloc[0])
        if (yr_sorted["연도"] == 2000).any() else None
    )
    yr_sorted["2000년比"] = yr_sorted["면적_ha"].map(
        lambda v: ("%.2f배" % (v / base2000)) if (base2000 and pd.notna(v)) else "-"
    )

    G_, T_ = st.columns([1.1, 1])
    with G_:
        _CMAP = {"lv2": "#A8C5B0", "lv3": C_GREENHOUSE, "interp": "#FFFFFF"}
        _LINE = {"lv2": "#A8C5B0", "lv3": C_GREENHOUSE, "interp": C_GREENHOUSE}
        _grade = yr_sorted["분류등급"].fillna("lv3").astype(str).tolist()
        _x_str = yr_sorted["연도"].astype(str).tolist()
        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=_x_str, y=yr_sorted["면적_ha"],
            name="시설재배면적",
            marker=dict(
                color=[_CMAP.get(g, C_GREENHOUSE) for g in _grade],
                line=dict(color=[_LINE.get(g, C_GREENHOUSE) for g in _grade], width=2),
            ),
            text=[format(int(v), ",") if pd.notna(v) else "" for v in yr_sorted["면적_ha"]],
            textposition="auto",
            customdata=_grade,
            hovertemplate="%{x}년<br>면적: %{y:,.0f} ha<br>분류등급: %{customdata}<extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=_x_str, y=yr_sorted["도면적비_pct"],
            name="도면적비(%)", yaxis="y2", mode="lines+markers",
            line=dict(color="#7F7F7F", width=2), marker=dict(size=6),
        ))
        if "2007" in _x_str and "2013" in _x_str:
            _mid_idx = (_x_str.index("2007") + _x_str.index("2013")) / 2.0
            fig.add_vline(
                x=_mid_idx, line_dash="dot", line_color="#B45309", line_width=1.5,
                annotation_text="측정방법 변경 (Lv2 30m → Lv3 5m)",
                annotation_position="top", annotation_font_size=11,
                annotation_font_color="#B45309",
            )
        fig.update_layout(
            height=360, plot_bgcolor="white",
            margin=dict(l=10, r=10, t=44, b=30),
            yaxis=dict(title="면적 (ha)"),
            yaxis2=dict(title="도면적비 (%)", overlaying="y", side="right",
                        showgrid=False, rangemode="tozero"),
            legend=dict(orientation="h", y=1.14, font=dict(size=12)),
            xaxis=dict(type="category"),
        )
        st.plotly_chart(fig, use_container_width=True)
    with T_:
        disp = yr_sorted.copy()
        disp["면적_ha"] = disp["면적_ha"].map(lambda v: format(int(v), ",") if pd.notna(v) else "-")
        disp["도면적비_pct"] = disp["도면적비_pct"].map(lambda v: ("%.2f%%" % v) if pd.notna(v) else "-")
        disp["경지면적비_pct"] = disp["경지면적비_pct"].map(lambda v: ("%.1f%%" % v) if pd.notna(v) else "-")
        disp["면적_ha"] = disp.apply(
            lambda r: (r["면적_ha"] + " *") if r.get("검증") == "suspect" else r["면적_ha"],
            axis=1,
        )
        _BADGE = {
            "lv2":    '<span style="background:#A8C5B0;color:#1f3d2a;padding:1px 6px;border-radius:8px;font-size:11px;">L2</span>',
            "lv3":    '<span style="background:#2E8B57;color:#fff;padding:1px 6px;border-radius:8px;font-size:11px;">L3</span>',
            "interp": '<span style="background:#FDE68A;color:#7C2D12;padding:1px 6px;border-radius:8px;font-size:11px;">補</span>',
        }
        disp["등급"] = disp["분류등급"].map(lambda g: _BADGE.get(str(g), str(g) if pd.notna(g) else "-"))
        st.markdown(
            H.html_table(
                disp[["연도", "등급", "면적_ha", "도면적비_pct", "경지면적비_pct", "2000년比"]],
                headers=["연도", "등급", "면적(ha)", "도면적比", "경지면적比", "2000년比"],
                highlight_last_row=True,
            ),
            unsafe_allow_html=True,
        )
    H.source_caption(
        "〈표 2-16〉 EGIS 토지피복지도 시설재배지 폴리곤 면적 시계열 "
        "(L2=Lv2 30m: 2000·2007 / L3=Lv3 5m: 2013~2025 / 補=보간: 2020년은 2019·2021 평균). "
        "2013년 * 표시는 보고서 참조값(Lv2 기반) 대비 +26.9% — 데이터 오류가 아니라 "
        "Lv3(5m) 도입으로 소형 시설까지 포착된 측정정확도 향상의 결과. "
        "방법론이 동일한 2013~2025 구간 내 추이만 직접 비교 가능."
    )
    st.caption(
        "추세 해석: 외형상 3,065ha(2000)→7,166ha(2025) 약 2.34배. "
        "단 Lv2→Lv3 보정계수(+25% 추정) 반영 시 보정기준 약 3,830ha 대비 1.87배 "
        "(연평균 +2.5%). 동일 방법론 구간 2013→2025는 5,275→7,166ha (+35.8%, 연평균 +2.6%). "
        "시설재배는 노지 대비 단위면적 관개수요(난방·점적관수·연중재배)가 커, "
        "12년간 +1,891ha 순증은 지하수 취수 수요의 구조적 상향 압력으로 작용."
    )

    latest = int(yr_sorted["연도"].max())
    rg = LCL.load_greenhouse_by_region(year=latest)
    if rg.empty:
        st.caption(f"({latest}년 읍·면·동 분해 데이터 없음 — `--region` 옵션으로 빌드 필요)")
    else:
        H.section_title("읍·면·동별 시설재배지 면적 〈표 2-17〉 (%d년)" % latest)
        rg = rg[rg["읍면동"].isin(EUP_ORDER)].copy()
        rg["_ord"] = rg["읍면동"].map({n: i for i, n in enumerate(EUP_ORDER)})
        rg = rg.sort_values("_ord").drop(columns="_ord")
        city_sum = rg.groupby("시군")["면적_ha"].sum().to_dict()
        rg["시군내_비중"] = rg.apply(
            lambda x: x["면적_ha"] / city_sum.get(x["시군"], 1) * 100, axis=1
        )

        G2_, T2_ = st.columns([1, 1.1])
        with G2_:
            colors = [CITY.get(c, "#999") for c in rg["시군"]]
            fig2 = go.Figure(go.Bar(
                x=rg["읍면동"], y=rg["면적_ha"], marker_color=colors,
                text=[format(int(v), ",") for v in rg["면적_ha"]],
                textposition="auto",
            ))
            fig2.update_layout(
                height=400, plot_bgcolor="white",
                margin=dict(l=10, r=10, t=10, b=90),
                yaxis=dict(title="시설재배면적 (ha)"),
                xaxis=dict(categoryorder="array",
                           categoryarray=rg["읍면동"].tolist(),
                           tickangle=-45),
            )
            st.plotly_chart(fig2, use_container_width=True)
        with T2_:
            disp2 = rg.copy()
            disp2["면적_ha"] = disp2["면적_ha"].map(lambda v: format(int(v), ","))
            disp2["시군내_비중"] = disp2["시군내_비중"].map(lambda v: "%.1f%%" % v)
            st.markdown(
                H.html_table(
                    disp2[["시군", "읍면동", "면적_ha", "시군내_비중"]],
                    headers=["시군", "읍·면·동", "면적(ha)", "시군내 비중"],
                ),
                unsafe_allow_html=True,
            )
        H.source_caption(
            "〈표 2-17〉 %d년 시설재배지 폴리곤 면적 — 추자면·우도면은 본 분석의 GeoJSON(12 features) "
            "미포함으로 합계에서 제외." % latest
        )

        H.section_title("읍·면·동별 시설재배지 분포 지도 (%d년)" % latest)
        _back = {"제주동": "제주시 동지역", "서귀포동": "서귀포시 동지역"}
        agg = {_back.get(n, n): a for n, a in zip(rg["읍면동"], rg["면적_ha"])}
        st.caption("연도별 분포 지도, 법정리(177) 단위, 이용량 상관 분석은 "
                   "**43.시설재배현황** 탭에서 확인하세요.")
        try:
            H.render_choropleth_eup(
                agg, ramp_key="greenhouse",
                value_label="시설재배면적 (%d년)" % latest,
                value_fmt="{:,.0f}", unit="ha", height=420,
                key="t42_greenhouse_eup_map_%d" % latest,
            )
        except Exception as _e:
            st.error("지도 표시 오류: %s — 43.시설재배현황 탭에서 확인 가능합니다." % str(_e))


def _render_t26():
    df = L.load_report("t26_crop_region")
    if df.empty:
        st.caption("자료 없음"); return
    # 15차 Phase2-C: 43탭 표준 interleave 적용.
    # NOTE: t26 CSV 에는 추자/우도 데이터가 별도 행 '기타(우도,가파도)'로만 존재 (제주시 행 없음).
    # _interleave_subtotals 가 비표준 시군 '기타'를 제외하므로 표 합계는 제주시·서귀포시 실제 행정구역만 집계.
    disp = _interleave_subtotals(df, ["계"] + CROP_CATS)
    for c in ["계"] + CROP_CATS:
        disp[c] = disp[c].map(lambda v: format(int(round(v)), ",") if pd.notna(v) else "-")
    st.markdown(H.html_table(disp), unsafe_allow_html=True)
    st.caption("※ 우도·가파도(소면적) 자료는 보고서 〈표 2-26〉 원자료에서 '기타' 행으로만 집계되어 "
               "읍·면·동 단위 표에서는 제외 — 도 합계는 제주시+서귀포시 행정구역 합산값.")


def _render_t27():
    df = L.load_report("t27_susye")
    if df.empty:
        st.caption("자료 없음"); return
    G_, T_ = st.columns([1, 1.1])
    with G_:
        d = df[~df["읍면동"].isin(["계", "소계"])].copy()
        fig = go.Figure()
        fig.add_trace(go.Bar(x=d["읍면동"], y=d["수혜구역"], name="수혜구역",
                             marker_color="#185fa5"))
        fig.add_trace(go.Bar(x=d["읍면동"], y=d["비수혜구역"], name="비수혜구역",
                             marker_color="#C9C9C9"))
        fig.update_layout(barmode="stack", height=440, plot_bgcolor="white",
                          margin=dict(l=10, r=10, t=24, b=90), yaxis=dict(title="면적 (ha)"),
                          legend=dict(orientation="h", y=1.06, font=dict(size=12)),
                          xaxis=dict(categoryorder="array",
                                     categoryarray=d["읍면동"].tolist(), tickangle=-45))
        st.plotly_chart(fig, use_container_width=True)
    with T_:
        # 15차 Phase2-C: 43탭 표준 interleave 적용 (추자·우도 포함).
        disp = _interleave_subtotals(df, ["농지면적", "수혜구역", "비수혜구역"])
        for c in ("농지면적", "수혜구역", "비수혜구역"):
            disp[c] = disp[c].map(lambda v: format(v, ",.1f") if pd.notna(v) else "-")
        st.markdown(H.html_table(disp, headers=["시군", "읍·면·동", "농지면적", "수혜구역", "비수혜구역"]),
                    unsafe_allow_html=True)
