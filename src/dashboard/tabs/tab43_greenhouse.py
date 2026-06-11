# ==============================================================================
#  파일명: src/dashboard/tabs/tab43_greenhouse.py  —  Build 0.1 (2026-05-30)
#  탭: 43.시설재배현황 (농업통계 그룹) — 환경부 EGIS 토지피복 vector 폴리곤 기반
#  구성:
#    ① 면적 변화 시계열 (방법론 경계 표시, tab42 요약과 동일)
#    ② 읍·면·동 분포 (연도 슬라이더 + choropleth)
#    ③ 법정리(177) 분포 — 가장 미세한 단위 (NEW)
#    ④ 이용량 ↔ 시설재배 상관 분석 (NEW, 사용자 핵심 요구)
#       · 도전체 시계열 이중축 비교
#       · 읍·면·동 단위 (시설재배 변화량 vs 이용량 변화량) 산점도
# ==============================================================================
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from src.analysis import ag_well_loader
from src.analysis import landcover_loader as LCL
from src.analysis import agri_stats_loader as L
from src.dashboard import agri_stats_helpers as H
from src.dashboard.quit_helper import quit_button

try:
    import geopandas as gpd  # type: ignore
    _HAS_GPD = True
except Exception:  # noqa: BLE001 — geopandas 미설치 환경 폴백
    gpd = None  # type: ignore
    _HAS_GPD = False

try:
    from config import LANDCOVER_RAW_DIR as _LCV_RAW_DIR  # type: ignore
except Exception:  # noqa: BLE001
    _LCV_RAW_DIR = Path("data/06_landcover/raw")

_EUP_GEOJSON_PATH = Path("data/00_map/읍면동경계.geojson")

# tab23 패턴의 plotly choropleth 헬퍼 (folium 회피).
# import 실패 시 folium 기반 H.render_choropleth_* 로 fallback.
try:
    from src.dashboard.tabs._tab23_plotly_map import (
        render_eup_plotly_choropleth as _render_eup_plotly,
        render_ri_plotly_choropleth as _render_ri_plotly,
    )
    _HAS_PLOTLY_MAP = True
except Exception:  # noqa: BLE001 — fallback 의도, 모든 예외 흡수
    _render_eup_plotly = None
    _render_ri_plotly = None
    _HAS_PLOTLY_MAP = False

C_GREENHOUSE = "#2E8B57"
C_USAGE      = "#185fa5"  # 이용량 = 사파이어
CITY = {"제주시": "#305496", "서귀포시": "#5B9BD5"}

# greenhouse 톤 ramp (agri_stats_helpers RAMPS["greenhouse"] 와 동일 6단계)
GREENHOUSE_RAMP = ["#e6f2ec", "#c5e0cf", "#8fc4a8", "#5aa583", "#3a8a64", "#2E8B57"]


def _pick_default_years(available: list[int]) -> list[int]:
    """다년도 비교 기본 5연도 선정 — 최근 3 + 약 -8년 + 약 -13년."""
    if len(available) <= 5:
        return sorted(available)
    mx = max(available)
    recent3 = sorted(available)[-3:]
    y8  = min(available, key=lambda y: abs(y - (mx - 8)))
    y13 = min(available, key=lambda y: abs(y - (mx - 13)))
    return sorted(set(recent3 + [y8, y13]))

# tab42 와 동일 행정 순서 (추자·우도 미포함 — GeoJSON 12 features)
EUP_ORDER = ["제주동", "구좌읍", "애월읍", "조천읍", "한림읍", "한경면",
             "서귀포동", "남원읍", "대정읍", "성산읍", "안덕면", "표선면"]

# 12개 읍면동 고유색 (categorical palette) — 15차: 대비 강한 12색
EUP_COLORS = {
    "제주동":   "#E74C3C",  # 빨강
    "구좌읍":   "#27AE60",  # 진녹
    "애월읍":   "#3498DB",  # 파랑
    "조천읍":   "#F39C12",  # 주황
    "한림읍":   "#9B59B6",  # 보라
    "한경면":   "#E67E22",  # 다크오렌지
    "서귀포동": "#1ABC9C",  # 청록
    "남원읍":   "#C0392B",  # 짙은빨강
    "대정읍":   "#2ECC71",  # 라임
    "성산읍":   "#34495E",  # 남색
    "안덕면":   "#D35400",  # 테라코타
    "표선면":   "#16A085",  # 다크청록
}


# ──────────────────────────────────────────────────────────────────────────
#  16차: 색 ramp 헬퍼 (그룹바 per-X 색 + focus 모드 리별 본색 팔레트)
# ──────────────────────────────────────────────────────────────────────────
def _hex_to_rgb(h: str) -> "tuple[int,int,int]":
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return "#%02X%02X%02X" % (max(0, min(255, r)),
                              max(0, min(255, g)),
                              max(0, min(255, b)))


def _hex_ramp(base_hex: str, n: int, lightest: float = 0.78) -> "list[str]":
    """본색 → 흰색 방향 N단계 ramp. 결과 [0]=가장 옅음, [n-1]=본색.
    lightest: 가장 옅은 단계의 흰색 혼합 비율(0~1, 1=완전 흰색).
    """
    if n <= 0:
        return []
    if n == 1:
        return [base_hex]
    r, g, b = _hex_to_rgb(base_hex)
    out = []
    for i in range(n):
        # i=0 → lightest, i=n-1 → 본색
        t = lightest * (1 - i / (n - 1))   # i=n-1: t=0(본색), i=0: t=lightest
        rr = int(round(r + (255 - r) * t))
        gg = int(round(g + (255 - g) * t))
        bb = int(round(b + (255 - b) * t))
        out.append(_rgb_to_hex(rr, gg, bb))
    return out


def _ri_color_palette(base_hex: str, n: int) -> "list[str]":
    """focus 모드용: 본색 명도 변형 N개 (간단 명도 ramp).
    리별 색은 본색 명도 사이클 — 9개면 약간씩 다른 톤.
    """
    if n <= 0:
        return []
    # 명도 ramp를 약간 더 넓게 만들고 본색 쪽부터 N개 (옅은 → 진한 순)
    wide = _hex_ramp(base_hex, max(n, 5), lightest=0.65)
    if n <= len(wide):
        return wide[-n:][::-1]   # 본색 쪽부터 N개, 옅은 → 진한 순
    return wide


def _derive_eup_from_full(full_name: str) -> str:
    """법정리이름(예: '제주시구좌읍김녕리') → 읍면동 추출.
    동지역(읍/면 prefix 없음)은 '제주동'/'서귀포동'으로 통합.
    """
    if not full_name:
        return "?"
    if full_name.startswith("제주시"):
        rest = full_name[3:]
        for em in ("구좌읍", "조천읍", "애월읍", "한림읍", "한경면", "추자면", "우도면"):
            if rest.startswith(em):
                return em
        return "제주동"
    elif full_name.startswith("서귀포시"):
        rest = full_name[4:]
        for em in ("성산읍", "표선면", "남원읍", "대정읍", "안덕면"):
            if rest.startswith(em):
                return em
        return "서귀포동"
    return "?"


@st.cache_data(ttl=3600, show_spinner=False)
def _ri_to_eup_map() -> dict:
    """법정리(짧은이름) → 읍면동 매핑 — **spatial join 기반** (12차 재작성).
    리경계.geojson 의 법정리이름은 시군+리명만 보유(읍·면 정보 없음 — 12차 진단 확인),
    따라서 텍스트 추출 불가. 리 centroid 가 어떤 읍·면·동 폴리곤 안인지 sjoin.
    동명이리는 (시군, 리명) 키로 자동 구분.
    return: {(시군, 짧은리명): 읍면동}, 추자/우도는 읍면동경계 미포함이라 매핑 누락.
    """
    try:
        import geopandas as _gpd
    except Exception:
        return {}
    try:
        ri_gdf = _gpd.read_file("data/00_map/리경계.geojson")
        eup_gdf = _gpd.read_file("data/00_map/읍면동경계.geojson")
    except Exception:
        return {}
    if ri_gdf.crs is None:
        ri_gdf = ri_gdf.set_crs("EPSG:4326")
    if eup_gdf.crs is None:
        eup_gdf = eup_gdf.set_crs("EPSG:4326")
    # CRS 통일 (둘 다 4326 가정)
    eup_gdf = eup_gdf.to_crs(ri_gdf.crs)
    # 리의 representative_point (centroid 보다 안전 — 폴리곤 내부 보장)
    ri_pts = ri_gdf.copy()
    ri_pts["geometry"] = ri_gdf.geometry.representative_point()
    joined = _gpd.sjoin(
        ri_pts, eup_gdf[["NAME", "geometry"]],
        how="left", predicate="within",
    )

    def _norm(n: str) -> str:
        if not isinstance(n, str):
            return ""
        if n == "제주시 동지역":
            return "제주동"
        if n == "서귀포시 동지역":
            return "서귀포동"
        return n

    m: dict = {}
    for _, row in joined.iterrows():
        short = row.get("법정리명", "")
        full = row.get("법정리이름", "") or ""
        eup = _norm(row.get("NAME", ""))
        if not short or not eup:
            continue  # 추자/우도 등 읍면동경계 미포함 폴리곤 자동 skip
        sigun = "제주시" if full.startswith("제주시") else (
            "서귀포시" if full.startswith("서귀포시") else "")
        m[(sigun, short)] = eup
    return m


def _render_focus_selector() -> "str | None":
    """tab22 패턴의 읍면동 focus selectbox. 반환: None(전체) 또는 읍면동 이름."""
    options = ["전체 (도전체)"] + EUP_ORDER
    sel_l, sel_r = st.columns([1.5, 6])
    with sel_l:
        st.markdown(
            '<div style="padding-top:0.55rem;font-weight:600;">📍 읍·면·동 선택 :</div>',
            unsafe_allow_html=True,
        )
    with sel_r:
        sel = st.selectbox(
            "읍·면·동 선택", options=options,
            key="tab43_focus_eup", label_visibility="collapsed",
        )
    return None if sel.startswith("전체") else sel
EUP_NAME_TO_GEOJSON = {"제주동": "제주시 동지역", "서귀포동": "서귀포시 동지역"}
SIGUN_MAP = {
    "구좌읍": "제주시", "조천읍": "제주시", "애월읍": "제주시",
    "한림읍": "제주시", "한경면": "제주시", "제주동": "제주시",
    "성산읍": "서귀포시", "표선면": "서귀포시", "남원읍": "서귀포시",
    "대정읍": "서귀포시", "안덕면": "서귀포시", "서귀포동": "서귀포시",
}


@st.fragment
def render() -> None:
    """43.시설재배현황 — @st.fragment 로 위젯 변경 시 다른 탭으로 튕기는 현상 차단
    (tab02/04/05/11/12/13/23 패턴과 동일). 사용자 보고: 9차 라운드 2026-05-31.
    """
    # (2026-06-11 v2) 탭 제목 제거 — 하위탭 pill 문구와 중복 (사용자 요청)

    yr = LCL.load_greenhouse_yearly()
    if yr.empty:
        st.warning(
            "시설재배 데이터가 빌드되지 않았습니다.\n\n"
            "PC에서 `python scripts/build_greenhouse_stats.py --all --region --ri` 를 1회 실행하면 "
            "이 탭에 시계열·읍면동·리·이용량 상관 분석이 표시됩니다."
        )
        return

    # ── 읍·면·동 focus selector (tab22 패턴 — 11차 사용자 요청) ──
    # 전체 = 도전체 / 특정 읍면동 = 그 안의 법정리(or 동) 단위로 ①②가 자동 전환
    focus_eup = _render_focus_selector()
    if focus_eup:
        st.markdown(
            f'<p class="subsection-title" style="margin:6px 0 12px;color:#185fa5;">'
            f'📍 {focus_eup} — 세부 분석 (시계열·법정리 비교)</p>',
            unsafe_allow_html=True,
        )

    # ── ① 면적 시계열
    _render_timeseries(yr, focus_eup)
    st.markdown('<hr style="margin:18px 0;border:none;border-top:0.5px solid rgba(26,26,24,0.15);">',
                unsafe_allow_html=True)

    # ── ② 다년도 비교 — focus=None: 읍면동 / focus=구좌읍: 그 안의 법정리
    _render_year_comparison(yr, focus_eup)
    st.markdown('<hr style="margin:18px 0;border:none;border-top:0.5px solid rgba(26,26,24,0.15);">',
                unsafe_allow_html=True)

    # ── ③ 이용량 ↔ 시설재배 상관
    _render_usage_correlation(yr)
    st.markdown('<hr style="margin:18px 0;border:none;border-top:0.5px solid rgba(26,26,24,0.15);">',
                unsafe_allow_html=True)

    # ── ④ 시설재배지 분포 지도 (보고서 〈그림 2-16/17〉 형식 — 두 연도 좌우 비교)
    _render_polygon_distribution(yr)

    H.source_footer(extra=(
        "시설재배지: 환경공간정보서비스(EGIS) WFS 토지피복지도 "
        "Lv2(2000~2007, 30m) / Lv3(2013~2025, 5m) 폴리곤 — 제주 본도(추자·우도 미포함). "
        "이용량: 농업용 공공관정(행정자치부) 월별 사용량 신고치."
    ))


# ──────────────────────────────────────────────────────────────────────────
#  ① 면적 시계열
# ──────────────────────────────────────────────────────────────────────────
def _render_egis_agrix_compare(yr_egis: pd.DataFrame) -> None:
    """EGIS(환경부 토지피복) vs AgriX(농식품부 농업경영체) 시설재배 면적 비교 박스.
    두 자료는 정의·집계 단위·갱신 주기가 달라 절대값은 차이나지만, 추세 일치 여부 확인용.
    """
    try:
        ax = L.load_agrix()
    except Exception:
        return
    if ax is None or ax.empty or "시설_ha" not in ax.columns:
        return
    ax_dz = ax[(ax["시군"] == "도전체")].dropna(subset=["시설_ha"]).copy()
    if ax_dz.empty or yr_egis.empty:
        return
    # 공통 연도 비교
    common = sorted(set(int(y) for y in ax_dz["연도"]) & set(int(y) for y in yr_egis["연도"]))
    if not common:
        return
    y_latest = max(common)
    egis_v = float(yr_egis[yr_egis["연도"] == y_latest]["면적_ha"].iloc[0])
    agrix_v = float(ax_dz[ax_dz["연도"] == y_latest]["시설_ha"].iloc[0])
    diff = egis_v - agrix_v
    pct = diff / agrix_v * 100 if agrix_v else 0
    # 추세 일치성 (전년 대비 증감 부호)
    trend_msg = "—"
    if len(common) >= 2:
        y_prev = sorted(common)[-2]
        ep = float(yr_egis[yr_egis["연도"] == y_prev]["면적_ha"].iloc[0])
        ap = float(ax_dz[ax_dz["연도"] == y_prev]["시설_ha"].iloc[0])
        e_chg = (egis_v - ep) / ep * 100 if ep else 0
        a_chg = (agrix_v - ap) / ap * 100 if ap else 0
        same = (e_chg > 0) == (a_chg > 0)
        trend_msg = f"EGIS {e_chg:+.1f}% · AgriX {a_chg:+.1f}% — {'동일 방향 ✓' if same else '반대 방향 ⚠'}"
    cards = [
        H.kpi_card(f"EGIS (환경부, {y_latest})", f"{egis_v:,.0f} ha",
                   "토지피복지도 폴리곤", "#2E8B57"),
        H.kpi_card(f"AgriX (농식품부, {y_latest})", f"{agrix_v:,.0f} ha",
                   "농업경영체 등록 시설면적", "#7E3A8A"),
        H.kpi_card("출처 간 차이", f"{diff:+,.0f} ha ({pct:+.1f}%)",
                   "EGIS − AgriX (정의 차이)", "#888888"),
        H.kpi_card(f"전년 대비 변화 ({sorted(common)[-2] if len(common)>=2 else '-'}→{y_latest})",
                   trend_msg.split(" — ")[1] if " — " in trend_msg else trend_msg,
                   trend_msg.split(" — ")[0] if " — " in trend_msg else "", "#185fa5"),
    ]
    H.kpi_row(cards)
    st.caption(
        "EGIS(환경공간정보서비스 WFS 토지피복지도): 위성·항공영상에서 추출한 비닐하우스·온실 폴리곤 면적. "
        "AgriX(농업경영체 등록정보 현황 서비스, uni.agrix.go.kr): 농업경영체가 등록신청서에 신고한 시설 재배면적. "
        "두 자료는 측정 방식·갱신 주기·정의가 다르므로 절대값을 직접 비교하지 말고 **추세 일관성**을 보세요."
    )


def _render_timeseries(yr: pd.DataFrame, focus_eup: "str | None" = None) -> None:
    """면적 시계열 — focus 없으면 도전체, 있으면 그 읍면동 시계열.
    16차: 도전체 모드에서 2013~2025 는 12 읍면동 stacked, 2000·2007 은 단색 단일바.
    """
    # ── 16차: 도전체 모드 — 2013+ stacked + 2000·2007 단색 (별도 렌더링) ──
    if focus_eup is None:
        H.section_title("① 시설재배지 면적 시계열 — 도전체", top=0)
        _render_egis_agrix_compare(yr)
        if yr.empty:
            st.caption("시계열 데이터 없음")
            return
        yr_sorted = yr.sort_values("연도").copy()
        x_all = [str(int(y)) for y in yr_sorted["연도"]]
        # by_region 로드 (2013~2025 8개년 × 12 EUP)
        br = LCL.load_greenhouse_by_region()
        br_years_set = (set(int(y) for y in br["연도"].dropna().unique())
                        if not br.empty else set())

        G_, T_ = st.columns([1.4, 1])
        with G_:
            fig = go.Figure()
            # EUP별 12 trace (stacked) — by_region 가용 연도만 비-0
            if not br.empty:
                for eup in EUP_ORDER:
                    _yvals = []
                    for y_int in (int(yy) for yy in yr_sorted["연도"]):
                        if y_int in br_years_set:
                            sel = br[(br["연도"] == y_int) & (br["읍면동"] == eup)]
                            _yvals.append(float(sel["면적_ha"].sum())
                                          if not sel.empty else 0.0)
                        else:
                            _yvals.append(0.0)  # 2000·2007 → 단색 trace 가 채움
                    fig.add_trace(go.Bar(
                        name=eup, x=x_all, y=_yvals,
                        marker_color=EUP_COLORS.get(eup, "#888"),
                        hovertemplate="%{x}년 · " + eup
                                      + "<br>면적: %{y:,.1f} ha<extra></extra>",
                    ))
            # 2000·2007 단색 (by_region 부재 — 도전체 yearly 합계)
            non_br_years = [int(yy) for yy in yr_sorted["연도"]
                            if int(yy) not in br_years_set]
            if non_br_years:
                _y_old = [float(yr_sorted.loc[
                                    yr_sorted["연도"] == y_int, "면적_ha"
                                ].iloc[0])
                          for y_int in non_br_years]
                fig.add_trace(go.Bar(
                    name="도전체 (Lv2)",
                    x=[str(y) for y in non_br_years], y=_y_old,
                    marker_color="#8FBC8F",
                    hovertemplate="%{x}년 · 도전체(Lv2)"
                                  "<br>면적: %{y:,.1f} ha<extra></extra>",
                ))
            # 합계 라벨 (각 연도 stack 위)
            _tot_by_year = {}
            for _i, _r in yr_sorted.iterrows():
                _tot_by_year[str(int(_r["연도"]))] = float(_r["면적_ha"])
            fig.add_trace(go.Scatter(
                x=list(_tot_by_year.keys()),
                y=list(_tot_by_year.values()),
                mode="text",
                text=[f"<b>{int(round(v)):,}</b>" for v in _tot_by_year.values()],
                textposition="top center",
                textfont=dict(size=11, color="#1a1a18"),
                showlegend=False, hoverinfo="skip", cliponaxis=False,
            ))
            # ── 2026-06-03: AgriX 농식품부 시설재배 면적 오버레이 (보조 비교) ──
            try:
                _ax = L.load_agrix()
                if _ax is not None and not _ax.empty and "시설_ha" in _ax.columns:
                    _ax_dz = _ax[(_ax["시군"] == "도전체")].dropna(subset=["시설_ha"]).copy()
                    if not _ax_dz.empty:
                        _ax_x = [str(int(y)) for y in _ax_dz["연도"]]
                        _ax_y = [float(v) for v in _ax_dz["시설_ha"]]
                        fig.add_trace(go.Scatter(
                            x=_ax_x, y=_ax_y, name="AgriX(농식품부)",
                            mode="lines+markers",
                            line=dict(color="#7E3A8A", width=2.5, dash="dash"),
                            marker=dict(size=9, symbol="diamond"),
                            hovertemplate="%{x}년 · AgriX(농식품부)<br>면적: %{y:,.1f} ha<extra></extra>",
                        ))
            except Exception:
                pass
            _ymax = max(_tot_by_year.values()) if _tot_by_year else 0
            _shapes = []
            _annos = []
            if "2013" in x_all and "2007" in x_all:
                _mid = (x_all.index("2007") + x_all.index("2013")) / 2.0
                _shapes.append(dict(type="line", xref="x", yref="paper",
                                    x0=_mid, x1=_mid, y0=0, y1=1,
                                    line=dict(color="#B45309",
                                              width=1.5, dash="dot")))
                _annos.append(dict(xref="x", yref="paper",
                                   x=_mid, y=1.0,
                                   xanchor="left", yanchor="bottom",
                                   showarrow=False,
                                   text="<i>측정방법 변경 (Lv2 30m → Lv3 5m)</i>",
                                   font=dict(size=10, color="#B45309")))
            fig.update_layout(
                barmode="stack", height=440, plot_bgcolor="white",
                margin=dict(l=10, r=10, t=40, b=30),
                xaxis=dict(title="연도", type="category",
                           categoryorder="array", categoryarray=x_all),
                yaxis=dict(title="면적 (ha)",
                           range=[0, _ymax * 1.12] if _ymax > 0 else None),
                legend=dict(orientation="h", y=-0.18, font=dict(size=10)),
                shapes=_shapes, annotations=_annos,
            )
            st.plotly_chart(fig, use_container_width=True,
                            key="tab43_ts_stacked")
        with T_:
            disp = yr_sorted.copy()
            disp["면적_ha"] = disp["면적_ha"].map(lambda v: format(int(v), ","))
            disp["분류등급"] = disp["분류등급"].map(
                lambda g: {"lv2": "L2", "lv3": "L3", "interp": "補"}
                .get(str(g), "-")
            )
            st.markdown(
                H.html_table(
                    disp[["연도", "분류등급", "면적_ha"]],
                    headers=["연도", "등급", "면적(ha)"],
                    highlight_last_row=True,
                ),
                unsafe_allow_html=True,
            )
        return

    # ── 18차 focus 모드 — 리(법정리)별 stacked + 합계 라벨 ──
    H.section_title(f"① {focus_eup} 시설재배지 면적 시계열 (리별)", top=0)
    # 리 단위 데이터 + 매핑 로드
    ri_full = LCL.load_greenhouse_by_ri()
    if ri_full.empty:
        st.warning(
            "법정리 분해 데이터가 없습니다. PC에서 1회 실행:\n\n"
            "`python scripts/build_greenhouse_stats.py --all --ri`"
        )
        return
    _m = _ri_to_eup_map()
    if not _m:
        st.caption("리경계 GeoJSON 로드 실패 — 매핑 불가")
        return
    ri_full = ri_full.copy()
    ri_full["_eup_map"] = ri_full.apply(
        lambda r: _m.get((r["시군"], r["법정리"]), None), axis=1)
    ri_focus = ri_full[ri_full["_eup_map"] == focus_eup].copy()
    if ri_focus.empty:
        st.caption(f"({focus_eup} 소속 법정리 데이터 없음)")
        return
    ri_list = sorted(ri_focus["법정리"].unique())
    ts_years = sorted(int(y) for y in ri_focus["연도"].dropna().unique())

    G_, T_ = st.columns([1.4, 1])
    with G_:
        fig = go.Figure()
        _base = EUP_COLORS.get(focus_eup, "#888")
        ri_colors = _ri_color_palette(_base, len(ri_list))
        for ri_name, ri_color in zip(ri_list, ri_colors):
            _yvals = []
            for y in ts_years:
                sel = ri_focus[(ri_focus["연도"] == y) & (ri_focus["법정리"] == ri_name)]
                _yvals.append(float(sel["면적_ha"].sum()) if not sel.empty else 0.0)
            fig.add_trace(go.Bar(
                name=ri_name, x=[str(y) for y in ts_years], y=_yvals,
                marker_color=ri_color,
                hovertemplate="%{x}년 · " + ri_name
                              + "<br>면적: %{y:,.1f} ha<extra></extra>",
            ))
        _tot_by_year = {}
        for y in ts_years:
            _tot_by_year[str(y)] = float(
                ri_focus[ri_focus["연도"] == y]["면적_ha"].sum())
        fig.add_trace(go.Scatter(
            x=list(_tot_by_year.keys()),
            y=list(_tot_by_year.values()),
            mode="text",
            text=[f"<b>{int(round(v)):,}</b>" for v in _tot_by_year.values()],
            textposition="top center",
            textfont=dict(size=11, color="#1a1a18"),
            showlegend=False, hoverinfo="skip", cliponaxis=False,
        ))
        _ymax = max(_tot_by_year.values()) if _tot_by_year else 0
        fig.update_layout(
            barmode="stack", height=440, plot_bgcolor="white",
            margin=dict(l=10, r=10, t=20, b=30),
            xaxis=dict(title="연도", type="category",
                       categoryorder="array",
                       categoryarray=[str(y) for y in ts_years]),
            yaxis=dict(title="면적 (ha)",
                       range=[0, _ymax * 1.12] if _ymax > 0 else None),
            legend=dict(orientation="h", y=-0.18, font=dict(size=10)),
        )
        st.plotly_chart(fig, use_container_width=True,
                        key=f"tab43_ts_focus_{focus_eup}")
    with T_:
        # 표: focus 합계 연도별
        disp_rows = []
        for y in ts_years:
            _v = float(ri_focus[ri_focus["연도"] == y]["면적_ha"].sum())
            disp_rows.append({"연도": y, "면적_ha": format(int(round(_v)), ",")})
        disp = pd.DataFrame(disp_rows)
        st.markdown(
            H.html_table(
                disp[["연도", "면적_ha"]],
                headers=["연도", "면적(ha)"],
                highlight_last_row=True,
            ),
            unsafe_allow_html=True,
        )


# ──────────────────────────────────────────────────────────────────────────
#  ② 다년도 비교 (읍면동/리) — 5년 multiselect + grouped bar + plotly choropleth
# ──────────────────────────────────────────────────────────────────────────
def _render_year_comparison(yr: pd.DataFrame, focus_eup: "str | None" = None) -> None:
    """다년도 비교 — focus None: 12 읍면동 / focus 설정: 그 읍면동 내 법정리.
    Build: 11차 (2026-05-31) — 단위 토글 폐기, focus_eup 파라미터로 자동 전환.
    """
    if focus_eup is None:
        H.section_title("② 다년도 비교 — 읍·면·동")
        unit_code = "eup"
    else:
        H.section_title(f"② 다년도 비교 — {focus_eup} 내 법정리")
        unit_code = "ri_filtered"

    # ── 데이터 로드 + 가용 연도 산출 ──
    ri_full = None
    if unit_code == "eup":
        years_all = sorted(int(y) for y in yr["연도"].dropna().unique())
    else:
        ri_full = LCL.load_greenhouse_by_ri()
        if ri_full.empty:
            st.warning(
                "법정리 분해 데이터가 없습니다. PC에서 1회 실행:\n\n"
                "`python scripts/build_greenhouse_stats.py --all --ri`"
            )
            return
        years_all = sorted(int(y) for y in ri_full["연도"].dropna().unique())
    if not years_all:
        st.caption("데이터 없음")
        return

    # ── 컨트롤 행 (단위 라디오 제거 — focus selector로 대체) ──
    # 비교 연도 | 상위 N
    default_years = _pick_default_years(years_all)
    c_year, c_topn = st.columns([4.0, 1.0])
    with c_year:
        sel_years = st.multiselect(
            "비교 연도 (최대 5개)", options=years_all,
            default=default_years, max_selections=5,
            key="tab43_years_compare",
        )
    with c_topn:
        topn_choice = st.selectbox(
            "상위 N", options=["10", "15", "20", "전체"],
            index=2, key="tab43_topn",
        )
    sort_mode = "행정 순서"

    if not sel_years:
        st.caption("비교할 연도를 1개 이상 선택하세요.")
        return
    sel_years = sorted(int(y) for y in sel_years)

    # ── long-form DataFrame 구성 [지역, 시군, 연도, 면적_ha] ──
    if unit_code == "eup":
        frames = []
        for y in sel_years:
            rg = LCL.load_greenhouse_by_region(year=y)
            if rg.empty:
                continue
            rg = rg[rg["읍면동"].isin(EUP_ORDER)][["시군", "읍면동", "면적_ha"]].copy()
            rg["연도"] = y
            rg = rg.rename(columns={"읍면동": "지역"})
            frames.append(rg)
        if not frames:
            st.caption("선택 연도에 대한 읍면동 데이터 없음 (--region 빌드 필요)")
            return
        long_df = pd.concat(frames, ignore_index=True)
        region_label = "읍·면·동"
    else:
        # focus 읍면동에 속한 리만 추출 — 리경계.geojson 기반 매핑
        ri_eup_map = _ri_to_eup_map()
        if not ri_eup_map:
            st.caption("리경계 GeoJSON 로드 실패 — 매핑 불가")
            return
        cur = ri_full[ri_full["연도"].isin(sel_years)][["시군", "법정리", "연도", "면적_ha"]].copy()
        # 매핑 적용 + focus 필터
        cur["_eup"] = cur.apply(
            lambda r: ri_eup_map.get((r["시군"], r["법정리"]), "?"), axis=1
        )
        cur = cur[cur["_eup"] == focus_eup]
        if cur.empty:
            st.caption(f"({focus_eup}에 속한 법정리 데이터 없음)")
            return
        long_df = cur.drop(columns="_eup").rename(columns={"법정리": "지역"})
        region_label = "법정리"

    # ── 피벗: 행=지역, 열=연도, 값=면적_ha ──
    pivot = long_df.pivot_table(
        index=["시군", "지역"], columns="연도", values="면적_ha", aggfunc="sum"
    ).fillna(0.0)
    pivot = pivot.reindex(columns=sel_years, fill_value=0.0)
    pivot = pivot.reset_index()

    y_latest = sel_years[-1]
    y_oldest = sel_years[0]
    pivot["Δ"]   = pivot[y_latest] - pivot[y_oldest]
    pivot["Δ%"] = pivot.apply(
        lambda r: ((r[y_latest] - r[y_oldest]) / r[y_oldest] * 100.0)
        if r[y_oldest] not in (0, 0.0) else float("nan"),
        axis=1,
    )

    # ── 정렬 ──
    if sort_mode == "최신 면적순":
        pivot = pivot.sort_values(y_latest, ascending=False)
    elif sort_mode == "변화량순":
        pivot = pivot.sort_values("Δ", ascending=False)
    else:  # 행정 순서 — 보고서 표2-20 순서 (제주시 → 서귀포시)
        if unit_code == "eup":
            order_map = {n: i for i, n in enumerate(EUP_ORDER)}
            pivot["_ord"] = pivot["지역"].map(order_map).fillna(999)
            pivot = pivot.sort_values(["_ord", "지역"]).drop(columns="_ord")
        else:
            # 리: 시군(제주시 먼저) → 리명 가나다순
            _sigun_ord = {"제주시": 0, "서귀포시": 1}
            pivot["_sg"] = pivot["시군"].map(_sigun_ord).fillna(9)
            pivot = pivot.sort_values(["_sg", "지역"]).drop(columns="_sg")

    # ── 상위 N 적용 (가나다순일 때도 동일하게 컷) ──
    if topn_choice != "전체":
        pivot = pivot.head(int(topn_choice))

    if pivot.empty:
        st.caption("표시할 데이터 없음")
        return

    # ── 18차: ② stacked bar 블록 삭제됨 (사용자 요청)
    # 그룹바(③ → ②)로 대체. 코드 흐름: pivot → 그룹바 → 표 → choropleth
    region_order = pivot["지역"].tolist()

    # ── 18차 재배치: 읍면동(또는 리)별 그룹바 (X=지역, Y=면적, N연도) ──
    # 색 정책 (Q3=1 / Q4=3):
    #   · 도전체 모드: 각 X(읍면동)별 본색=EUP_COLORS[X]
    #   · focus 모드:  본색=EUP_COLORS[focus_eup] → 리별로 명도 변형 팔레트
    #   · 각 X마다 N연도 ramp (가장 옛=옅음, 최근=본색)
    _x_regions = pivot["지역"].tolist()
    N = len(sel_years)
    if focus_eup:
        _base = EUP_COLORS.get(focus_eup, "#888")
        _ri_bases = _ri_color_palette(_base, len(_x_regions))
        _x_base_map = {r: _ri_bases[i] for i, r in enumerate(_x_regions)}
    else:
        _x_base_map = {r: EUP_COLORS.get(r, "#888") for r in _x_regions}
    _x_ramp = {r: _hex_ramp(_x_base_map[r], N) for r in _x_regions}

    fig_grp = go.Figure()
    for i, _y in enumerate(sel_years):
        _yvals_grp = [float(pivot.loc[pivot["지역"] == r, _y].iloc[0])
                      if (pivot["지역"] == r).any() else 0.0
                      for r in _x_regions]
        fig_grp.add_trace(go.Bar(
            name=str(_y),
            x=_x_regions,
            y=_yvals_grp,
            text=[f"{v:,.0f}" if v > 0 else "" for v in _yvals_grp],
            textposition="outside",
            textfont=dict(size=9),
            cliponaxis=False,
            # per-X color: 각 X에서 i번째 ramp 단계 (옛=옅음, 최근=본색)
            marker_color=[
                _x_ramp[r][i] if i < len(_x_ramp[r]) else _x_ramp[r][-1]
                for r in _x_regions
            ],
            hovertemplate=f"{_y}년 · " + "%{x}<br>면적: %{y:,.1f} ha<extra></extra>",
        ))
    fig_grp.update_layout(
        barmode="group", height=500, plot_bgcolor="white",
        margin=dict(l=10, r=10, t=40, b=80),
        xaxis=dict(title=region_label, type="category",
                   categoryorder="array", categoryarray=_x_regions,
                   tickangle=-30),
        yaxis=dict(title="시설재배 면적 (ha)"),
        legend=dict(orientation="h", y=-0.25, title="연도", font=dict(size=11)),
        bargap=0.20, bargroupgap=0.05,
    )
    _grpbar_title = ("▍ 읍·면·동별 비교 (연도별 그룹바)" if unit_code == "eup"
                     else "▍ 리(or 동별) 비교 (연도별 그룹바)")
    st.markdown(
        f'<p class="subsection-title" style="margin:8px 0 6px;">{_grpbar_title}</p>',
        unsafe_allow_html=True,
    )
    st.plotly_chart(fig_grp, use_container_width=True,
                    key=f"tab43_cmp_grpbar_{unit_code}")

    # ── 비교표 (H.html_table) — 12차: 소계 행 추가 ──
    # focus None(전체): 제주도 합계 + 제주시 소계 + 서귀포시 소계 (3행 prepend)
    # focus 설정(읍면동): {읍면동} 소계 (1행 prepend)
    def _make_subtotal_row(label_sigun: str, label_region: str, mask):
        """소계 행 생성 — mask=None 이면 pivot 전체 합."""
        sub = pivot if mask is None else pivot[mask]
        row = {"시군": label_sigun, "지역": label_region}
        for y in sel_years:
            row[y] = float(sub[y].sum())
        row["Δ"] = row[sel_years[-1]] - row[sel_years[0]]
        # 21차 사용자 요청 4: 분모 0 시 0.0% (오해 소지) → NaN ("—" 표시)
        row["Δ%"] = (row["Δ"] / row[sel_years[0]] * 100.0
                     if row[sel_years[0]] else pd.NA)
        return row

    # 13차: interleave — 시군 그룹 직전에 해당 시군 소계 (이미지 참조)
    # 제주도 합계 → 제주시 소계 → 제주시 읍면동 → 서귀포시 소계 → 서귀포시 읍면동
    rows: list = []
    if focus_eup is None:
        rows.append(_make_subtotal_row("제주도", "합계", None))
        je_mask = pivot["시군"] == "제주시"
        if je_mask.any():
            rows.append(_make_subtotal_row("제주시", "소계", je_mask))
            for _, _r in pivot[je_mask].iterrows():
                rows.append(_r.to_dict())
        sg_mask = pivot["시군"] == "서귀포시"
        if sg_mask.any():
            rows.append(_make_subtotal_row("서귀포시", "소계", sg_mask))
            for _, _r in pivot[sg_mask].iterrows():
                rows.append(_r.to_dict())
    else:
        # 19차 사용자 요청: focus 모드 첫 행 첫 컬럼에 focus_eup(예: 애월읍),
        # 두 번째 컬럼은 "소계"
        rows.append(_make_subtotal_row(focus_eup, "소계", None))
        for _, _r in pivot.iterrows():
            rows.append(_r.to_dict())
    disp_full = pd.DataFrame(rows)

    # 포맷팅 (소계+본문 한꺼번에)
    for y in sel_years:
        disp_full[y] = disp_full[y].map(
            lambda v: format(int(round(v)), ",") if pd.notna(v) else "—"
        )
    disp_full["Δ"] = disp_full["Δ"].map(
        lambda v: format(v, "+,.0f") if pd.notna(v) else "—"
    )
    disp_full["Δ%"] = disp_full["Δ%"].map(
        lambda v: ("%+.1f%%" % v) if pd.notna(v) else "—"
    )

    # 시군 컬럼 그룹 첫 행만 표시 — 소계 행도 같은 시군이면 반복 제거
    # 19차: focus 모드는 본문 모두 빈값 (첫 행 "애월읍"만, 사용자 요청 3 "제주시 삭제")
    if focus_eup is None:
        _prev_sg = None
        _sgun_vals = []
        for _v in disp_full["시군"].tolist():
            _sgun_vals.append("" if _v == _prev_sg else _v)
            _prev_sg = _v
        disp_full["시군"] = _sgun_vals
    else:
        # 첫 행(소계)에만 focus_eup 값, 나머지는 모두 빈값
        _sgun_vals = [disp_full["시군"].iloc[0]] + [""] * (len(disp_full) - 1)
        disp_full["시군"] = _sgun_vals

    # 19차 사용자 요청 1: focus 모드는 첫 컬럼 헤더 "읍·면·동" (도전체는 "시군" 유지)
    _col1_header = "읍·면·동" if focus_eup else "시군"
    table_cols = ["시군", "지역"] + sel_years + ["Δ", "Δ%"]
    headers = [_col1_header, region_label] + [f"{y}" for y in sel_years] + \
              [f"Δ({y_oldest}→{y_latest})", "Δ%"]
    st.markdown(
        H.html_table(disp_full[table_cols], headers=headers,
                     highlight_last_row=False),
        unsafe_allow_html=True,
    )

    # ── 18차: 구 그룹바 블록 삭제됨 (위 ② 자리로 이동)
    # ── 단일 연도 choropleth (selectbox — st.select_slider 금지) ──
    st.markdown("&nbsp;", unsafe_allow_html=True)
    map_year = st.selectbox(
        "지도 표시 연도",
        options=sel_years,
        index=len(sel_years) - 1,
        key="tab43_map_year",
    )
    st.markdown(f"**{region_label}별 분포 지도 ({map_year}년)**")

    # 해당 연도 데이터만 추출 → choropleth agg 빌드
    year_df = long_df[long_df["연도"] == map_year]
    if year_df.empty:
        st.caption(f"({map_year}년 {region_label} 데이터 없음)")
        return

    map_key = f"tab43_cmp_map_{unit_code}_{map_year}"

    if unit_code == "eup":
        # plotly 경로: render_eup_plotly_choropleth 는 agg[NAME] = {metric, n_well, sum_m3, per_well_day}
        # 형식을 받으므로 시설재배 면적을 metric 으로 매핑.
        # GeoJSON 키 변환: '제주동' → '제주시 동지역' 등.
        if _HAS_PLOTLY_MAP and _render_eup_plotly is not None:
            agg_plotly = {}
            for _, r in year_df.iterrows():
                gj_name = EUP_NAME_TO_GEOJSON.get(r["지역"], r["지역"])
                agg_plotly[gj_name] = {
                    "metric":       float(r["면적_ha"]),
                    "n_well":       0,
                    "sum_m3":       0.0,
                    "per_well_day": 0.0,
                }
            try:
                _render_eup_plotly(agg_plotly, mode="abs", height=480)
            except Exception as e:  # noqa: BLE001
                # plotly 실패 → folium fallback
                st.caption(f"(plotly choropleth 실패 — folium 폴백: {type(e).__name__})")
                _fallback_eup_choropleth(year_df, map_year, map_key)
        else:
            _fallback_eup_choropleth(year_df, map_year, map_key)
    else:
        if _HAS_PLOTLY_MAP and _render_ri_plotly is not None:
            # 리 단위: build_script가 짧은이름('수산리')으로 저장한 반면 GeoJSON 매칭은
            # 풀네임('서귀포시수산리')이라 회색 폴리곤 회귀가 발생 (7차-E 확인). 풀네임으로 변환.
            try:
                _gj = H.load_ri_geojson()
                _full_by_short_sigun: dict[tuple[str, str], str] = {}
                for f in _gj.get("features", []):
                    p = f.get("properties", {})
                    short = p.get("법정리명")
                    full = p.get("법정리이름")
                    sigun_code = str(p.get("법정시코드", ""))
                    sigun_name = "제주시" if sigun_code.startswith("50110") else (
                        "서귀포시" if sigun_code.startswith("50130") else "")
                    if short and full:
                        _full_by_short_sigun[(short, sigun_name)] = full
            except Exception:
                _full_by_short_sigun = {}
            agg_plotly = {}
            for _, r in year_df.iterrows():
                full = _full_by_short_sigun.get((r["지역"], r["시군"]), r["지역"])
                agg_plotly[full] = {
                    "metric":       float(r["면적_ha"]),
                    "n_well":       0,
                    "sum_m3":       0.0,
                    "per_well_day": 0.0,
                    "ri_norm":      r["지역"],
                }
            try:
                _render_ri_plotly(agg_plotly, mode="abs", height=520)
            except Exception as e:  # noqa: BLE001
                st.caption(f"(plotly choropleth 실패 — folium 폴백: {type(e).__name__})")
                _fallback_ri_choropleth(year_df, map_year, map_key)
        else:
            _fallback_ri_choropleth(year_df, map_year, map_key)


def _fallback_eup_choropleth(year_df: pd.DataFrame, map_year: int, key: str) -> None:
    """plotly 경로 실패/미가용 시 기존 folium 헬퍼로 폴백."""
    agg = {EUP_NAME_TO_GEOJSON.get(n, n): a
           for n, a in zip(year_df["지역"], year_df["면적_ha"])}
    try:
        H.render_choropleth_eup(
            agg, ramp_key="greenhouse",
            value_label=f"시설재배({map_year})",
            value_fmt="{:,.0f}", unit="ha", height=480,
            key=key,
        )
    except Exception as e:  # noqa: BLE001
        st.error(f"choropleth 렌더 실패: {type(e).__name__}: {e}")


def _fallback_ri_choropleth(year_df: pd.DataFrame, map_year: int, key: str) -> None:
    agg = dict(zip(year_df["지역"], year_df["면적_ha"]))
    try:
        H.render_choropleth_ri(
            agg, ramp_key="greenhouse",
            value_label=f"시설재배({map_year})",
            value_fmt="{:,.1f}", unit="ha", height=520,
            key=key,
        )
    except Exception as e:  # noqa: BLE001
        st.error(f"법정리 choropleth 실패: {type(e).__name__}: {e}")


# ──────────────────────────────────────────────────────────────────────────
#  (archived) 기존 단일연도 읍·면·동 분포 — _render_year_comparison 으로 통합
# ──────────────────────────────────────────────────────────────────────────
def _render_eup_distribution(yr: pd.DataFrame) -> None:
    H.section_title("② 읍·면·동 분포")
    years = sorted(int(y) for y in yr["연도"].dropna().unique())
    if not years:
        st.caption("연도 데이터 없음"); return
    sel_year = st.select_slider(
        "연도 선택", options=years, value=years[-1],
        key="tab43_eup_year",
    )
    rg = LCL.load_greenhouse_by_region(year=sel_year)
    if rg.empty:
        st.caption(f"({sel_year}년 읍·면·동 분해 데이터 없음 — `--region` 옵션으로 빌드 필요)")
        return

    rg = rg[rg["읍면동"].isin(EUP_ORDER)].copy()
    rg["_ord"] = rg["읍면동"].map({n: i for i, n in enumerate(EUP_ORDER)})
    rg = rg.sort_values("_ord").drop(columns="_ord")
    city_sum = rg.groupby("시군")["면적_ha"].sum().to_dict()
    rg["시군내_비중"] = rg.apply(
        lambda x: x["면적_ha"] / city_sum.get(x["시군"], 1) * 100, axis=1
    )

    G2_, T2_ = st.columns([1.2, 1])
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
            yaxis=dict(title=f"시설재배면적 (ha) — {sel_year}년"),
            xaxis=dict(categoryorder="array",
                       categoryarray=rg["읍면동"].tolist(),
                       tickangle=-45),
        )
        st.plotly_chart(fig2, use_container_width=True)
    with T2_:
        disp = rg.copy()
        disp["면적_ha"] = disp["면적_ha"].map(lambda v: format(int(v), ","))
        disp["시군내_비중"] = disp["시군내_비중"].map(lambda v: "%.1f%%" % v)
        st.markdown(
            H.html_table(
                disp[["시군", "읍면동", "면적_ha", "시군내_비중"]],
                headers=["시군", "읍·면·동", "면적(ha)", "시군내 비중"],
            ),
            unsafe_allow_html=True,
        )

    # Choropleth — 안정 렌더링 (use_container_width 대신 명시 width)
    st.markdown(f"**읍·면·동별 분포 지도 ({sel_year}년)**")
    agg = {EUP_NAME_TO_GEOJSON.get(n, n): a for n, a in zip(rg["읍면동"], rg["면적_ha"])}
    try:
        H.render_choropleth_eup(
            agg, ramp_key="greenhouse",
            value_label=f"시설재배({sel_year})",
            value_fmt="{:,.0f}", unit="ha", height=480,
            key=f"tab43_eup_map_{sel_year}",
        )
    except Exception as e:
        st.error(f"choropleth 렌더 실패: {type(e).__name__}: {e}")


# ──────────────────────────────────────────────────────────────────────────
#  ③ 법정리(177) 분포 (NEW)
# ──────────────────────────────────────────────────────────────────────────
def _render_ri_distribution(yr: pd.DataFrame) -> None:
    H.section_title("③ 법정리(177) 단위 분포")
    ri_df = LCL.load_greenhouse_by_ri()
    if ri_df.empty:
        st.warning(
            "법정리 분해 데이터가 없습니다. PC에서 다음 명령 1회 실행:\n\n"
            "`python scripts/build_greenhouse_stats.py --all --ri`"
        )
        return
    years = sorted(int(y) for y in ri_df["연도"].dropna().unique())
    sel_year = st.select_slider(
        "연도 선택", options=years, value=years[-1],
        key="tab43_ri_year",
    )
    cur = ri_df[ri_df["연도"] == sel_year].copy()
    if cur.empty:
        st.caption(f"({sel_year}년 법정리 데이터 없음)"); return
    cur = cur.sort_values("면적_ha", ascending=False)

    c1, c2, c3 = st.columns(3)
    c1.metric("총 법정리 수", f"{len(cur):,}")
    c2.metric("최대 면적 리", cur.iloc[0]["법정리"] if len(cur) else "—",
              f"{cur['면적_ha'].iloc[0]:,.1f} ha" if len(cur) else "")
    c3.metric("합계 면적", f"{cur['면적_ha'].sum():,.1f} ha")

    # 상위 N개 막대 + 전체 표
    top_n = st.slider("상위 N개 표시", 10, min(50, len(cur)), 20,
                      key="tab43_ri_topn")
    G3_, T3_ = st.columns([1.2, 1])
    with G3_:
        top = cur.head(top_n).iloc[::-1]  # 가로막대 위→아래 순
        colors = [CITY.get(c, "#999") for c in top["시군"]]
        fig3 = go.Figure(go.Bar(
            x=top["면적_ha"], y=top["법정리"], orientation="h",
            marker_color=colors,
            text=[format(round(v, 1), ",") for v in top["면적_ha"]],
            textposition="auto",
        ))
        fig3.update_layout(
            height=max(360, top_n * 20), plot_bgcolor="white",
            margin=dict(l=10, r=10, t=10, b=30),
            xaxis=dict(title=f"시설재배면적 (ha) — {sel_year}년"),
        )
        st.plotly_chart(fig3, use_container_width=True)
    with T3_:
        disp = cur.head(50).copy()
        disp["면적_ha"] = disp["면적_ha"].map(lambda v: format(round(v, 2), ","))
        st.markdown(
            H.html_table(
                disp[["시군", "법정리", "면적_ha"]],
                headers=["시군", "법정리", "면적(ha)"],
            ),
            unsafe_allow_html=True,
        )

    # 법정리 choropleth
    st.markdown(f"**법정리(177) 분포 지도 ({sel_year}년)**")
    agg_ri = dict(zip(cur["법정리"], cur["면적_ha"]))
    try:
        H.render_choropleth_ri(
            agg_ri, ramp_key="greenhouse",
            value_label=f"시설재배({sel_year})",
            value_fmt="{:,.1f}", unit="ha", height=520,
            key=f"tab43_ri_map_{sel_year}",
        )
    except Exception as e:
        st.error(f"법정리 choropleth 실패: {type(e).__name__}: {e}")


# ──────────────────────────────────────────────────────────────────────────
#  ④ 이용량 ↔ 시설재배 상관 (NEW — 사용자 핵심 요구)
# ──────────────────────────────────────────────────────────────────────────
def _render_usage_correlation(yr: pd.DataFrame) -> None:
    H.section_title("④ 이용량 ↔ 시설재배 상관 분석")
    st.caption(
        "💡 시설재배(비닐하우스·온실)는 노지 대비 관개·점적관수 수요가 커서 "
        "면적 증가가 지하수 이용량 상승 압력으로 이어지는 경향. "
        "최근 이용량 변화와 시설재배 면적 변화의 정량 비교."
    )
    try:
        df_usage = ag_well_loader.load_usage_long()
        master   = ag_well_loader.load_master(active_only=False)
    except Exception as e:
        st.error(f"이용량 데이터 로드 실패: {e}")
        return
    if df_usage.empty or master.empty:
        st.warning("이용량/관정 마스터 데이터 없음")
        return

    # (a) 도전체 연도별 이용량 합 (m³) — 시설재배 면적과 이중축 비교
    usage_year = (df_usage.groupby("year")["volume_m3"].sum().reset_index()
                  .rename(columns={"year": "연도", "volume_m3": "이용량_m3"}))
    usage_year["이용량_백만m3"] = usage_year["이용량_m3"] / 1_000_000.0
    yr_s = yr[["연도", "면적_ha"]].dropna().copy()
    merged = pd.merge(yr_s, usage_year, on="연도", how="inner").sort_values("연도")
    if merged.empty:
        st.caption("이용량 ↔ 시설재배 공통 연도 없음")
    else:
        H.section_title("(a) 도전체 시계열 비교 — 이용량 vs 시설재배 면적", top=12)
        G_, T_ = st.columns([1.4, 1])
        with G_:
            _xc = merged["연도"].astype(str).tolist()
            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=_xc, y=merged["면적_ha"], name="시설재배 (ha)",
                marker_color=C_GREENHOUSE, yaxis="y",
            ))
            fig.add_trace(go.Scatter(
                x=_xc, y=merged["이용량_백만m3"],
                name="이용량 (백만 m³)", yaxis="y2",
                mode="lines+markers",
                line=dict(color=C_USAGE, width=2.5), marker=dict(size=8),
            ))
            fig.update_layout(
                height=380, plot_bgcolor="white",
                margin=dict(l=10, r=10, t=30, b=30),
                yaxis=dict(title="시설재배 면적 (ha)"),
                yaxis2=dict(title="이용량 (백만 m³)", overlaying="y",
                            side="right", showgrid=False, rangemode="tozero"),
                xaxis=dict(type="category"),
                legend=dict(orientation="h", y=1.10, font=dict(size=12)),
            )
            st.plotly_chart(fig, use_container_width=True)
        with T_:
            disp = merged.copy()
            disp["면적_ha"] = disp["면적_ha"].map(lambda v: format(int(v), ","))
            disp["이용량_백만m3"] = disp["이용량_백만m3"].map(lambda v: "%.1f" % v)
            st.markdown(
                H.html_table(
                    disp[["연도", "면적_ha", "이용량_백만m3"]],
                    headers=["연도", "시설재배(ha)", "이용량(백만m³)"],
                ),
                unsafe_allow_html=True,
            )
        # 상관계수
        if len(merged) >= 3:
            corr = merged["면적_ha"].corr(merged["이용량_백만m3"])
            st.markdown(
                f"<div style='font-size:13px;color:var(--color-text-secondary);"
                f"margin-top:6px;'>· 피어슨 상관계수 (시설재배 ha ↔ 이용량 백만 m³): "
                f"<b style='color:{C_GREENHOUSE};'>r = {corr:+.3f}</b> "
                f"(공통 연도 {len(merged)}개) — "
                f"{'강한 양의 상관' if corr > 0.7 else ('중간 상관' if corr > 0.4 else '약/무 상관')}</div>",
                unsafe_allow_html=True,
            )

    # (b) 읍·면·동 단위 — 최근 vs 과거 면적 변화 vs 이용량
    H.section_title("(b) 읍·면·동 단위 — 시설재배 변화량 vs 이용량 변화량", top=18)
    years_avail = sorted(int(y) for y in yr["연도"].dropna().unique())
    if len(years_avail) < 2:
        st.caption("비교할 두 연도가 부족합니다.")
        return
    cy1, cy2 = st.columns(2)
    with cy1:
        ya = st.selectbox("기준 연도(과거)", years_avail,
                          index=max(0, years_avail.index(2019) if 2019 in years_avail else 0),
                          key="tab43_corr_ya")
    with cy2:
        yb_options = [y for y in years_avail if y > ya]
        yb = st.selectbox("비교 연도(최근)", yb_options,
                          index=len(yb_options) - 1 if yb_options else 0,
                          key="tab43_corr_yb")
    if yb is None or yb <= ya:
        st.caption("기준<비교 연도 선택 필요")
        return

    # 읍면동별 시설재배 변화
    rg_a = LCL.load_greenhouse_by_region(year=ya)
    rg_b = LCL.load_greenhouse_by_region(year=yb)
    if rg_a.empty or rg_b.empty:
        st.caption(f"({ya} 또는 {yb}년 읍면동 데이터 없음 — --region 빌드 필요)")
        return
    gh = pd.merge(
        rg_a[["읍면동", "면적_ha"]].rename(columns={"면적_ha": "ha_a"}),
        rg_b[["읍면동", "면적_ha"]].rename(columns={"면적_ha": "ha_b"}),
        on="읍면동", how="inner",
    )
    gh["시설재배_변화_ha"] = gh["ha_b"] - gh["ha_a"]

    # 읍면동별 이용량 변화 (master.well_eup 기반 집계)
    use_a = _usage_by_eup(df_usage, master, ya)
    use_b = _usage_by_eup(df_usage, master, yb)
    if use_a.empty or use_b.empty:
        st.caption(f"({ya} 또는 {yb}년 이용량 데이터 없음)")
        return
    us = pd.merge(
        use_a.rename(columns={"이용량_m3": "u_a"}),
        use_b.rename(columns={"이용량_m3": "u_b"}),
        on="읍면동", how="inner",
    )
    us["이용량_변화_백만m3"] = (us["u_b"] - us["u_a"]) / 1_000_000.0

    df_corr = pd.merge(
        gh[["읍면동", "시설재배_변화_ha"]],
        us[["읍면동", "이용량_변화_백만m3"]],
        on="읍면동", how="inner",
    )
    df_corr["시군"] = df_corr["읍면동"].map(SIGUN_MAP).fillna("미상")
    if df_corr.empty:
        st.caption("매칭되는 읍면동 없음")
        return

    G_, T_ = st.columns([1.3, 1])
    with G_:
        fig_s = go.Figure()
        for sigun, color in CITY.items():
            sub = df_corr[df_corr["시군"] == sigun]
            if sub.empty:
                continue
            fig_s.add_trace(go.Scatter(
                x=sub["시설재배_변화_ha"], y=sub["이용량_변화_백만m3"],
                mode="markers+text", name=sigun,
                text=sub["읍면동"], textposition="top center",
                marker=dict(color=color, size=14, line=dict(color="white", width=1)),
            ))
        fig_s.add_hline(y=0, line_dash="dot", line_color="#999", line_width=1)
        fig_s.add_vline(x=0, line_dash="dot", line_color="#999", line_width=1)
        fig_s.update_layout(
            height=440, plot_bgcolor="white",
            margin=dict(l=10, r=10, t=30, b=40),
            xaxis=dict(title=f"시설재배 면적 변화 (ha, {ya}→{yb})"),
            yaxis=dict(title=f"이용량 변화 (백만 m³, {ya}→{yb})"),
            legend=dict(orientation="h", y=1.10, font=dict(size=12)),
        )
        st.plotly_chart(fig_s, use_container_width=True)
    with T_:
        disp = df_corr.copy()
        # %-format 콤마 미지원 — format() 사용 (5차 tab41·7차 tab43:328 동일 패턴)
        disp["시설재배_변화_ha"] = disp["시설재배_변화_ha"].map(
            lambda v: format(v, "+,.0f") if pd.notna(v) else "—"
        )
        disp["이용량_변화_백만m3"] = disp["이용량_변화_백만m3"].map(
            lambda v: ("%+.2f" % v) if pd.notna(v) else "—"
        )
        st.markdown(
            H.html_table(
                disp[["시군", "읍면동", "시설재배_변화_ha", "이용량_변화_백만m3"]],
                headers=["시군", "읍·면·동", "시설재배 Δ(ha)", "이용량 Δ(백만m³)"],
            ),
            unsafe_allow_html=True,
        )
    if len(df_corr) >= 3:
        corr2 = df_corr["시설재배_변화_ha"].corr(df_corr["이용량_변화_백만m3"])
        st.markdown(
            f"<div style='font-size:13px;color:var(--color-text-secondary);'>"
            f"· 읍·면·동 변화량 피어슨 상관 ({ya}→{yb}): "
            f"<b style='color:{C_GREENHOUSE};'>r = {corr2:+.3f}</b> (n={len(df_corr)}) "
            f"— 양의 상관일수록 시설재배가 많이 늘어난 지역에서 이용량도 많이 늘어났음을 시사.</div>",
            unsafe_allow_html=True,
        )


def _usage_by_eup(df_usage: pd.DataFrame, master: pd.DataFrame, year: int) -> pd.DataFrame:
    """연도별 이용량을 읍면동 단위로 집계 (master.well_eup 기준).
    반환: 읍면동 / 이용량_m3
    """
    u = df_usage[df_usage["year"] == year][["permit_no", "volume_m3"]]
    if u.empty:
        return pd.DataFrame(columns=["읍면동", "이용량_m3"])
    m = master[["permit_no", "well_eup", "well_si"]].copy()

    def _norm(row):
        s = str(row.get("well_si", "")).strip()
        e = str(row.get("well_eup", "")).strip()
        if not e or e == "nan":
            return None
        if e.endswith("동"):
            return "제주동" if "제주" in s else ("서귀포동" if "서귀" in s else e)
        return e
    m["읍면동"] = m.apply(_norm, axis=1)
    j = pd.merge(u, m[["permit_no", "읍면동"]], on="permit_no", how="left")
    j = j.dropna(subset=["읍면동"])
    out = j.groupby("읍면동", as_index=False)["volume_m3"].sum()
    out = out.rename(columns={"volume_m3": "이용량_m3"})
    return out




# ── 17차 재작성: 좌표계 진단 + 로컬 00_map 기반 베이스맵 ──
# 16차 복구본의 carto-positron(외부 CartoDB) 베이스 + EPSG:4326 가정 잘못 → 마커 미표시.
# 17차: ① landcover geojson EPSG:3857/900913 → 4326 reproject. ② base style="white-bg".
# ③ mb_layers 에 data/00_map 의 리경계 + 읍면동경계 추가 (외부 의존 0).
# ──────────────────────────────────────────────────────────────────
# ⚡ (2026-06-11 검증팀 G2) 폴리곤 분포 캐시 헬퍼
#   기존: 매 rerun 마다 landcover geojson(연도당 29~32MB) ×2 를 json.loads
#   + geopandas 재투영 → 위젯 하나만 건드려도 수 초 지연.
#   해결: 모듈 레벨 st.cache_data — 키 = (경로, 파일 mtime). 반환은 중심점
#   DataFrame(lat/lon)만 (수 MB → 수십 KB). 파일 교체 시 mtime 으로 자동 무효화.
# ──────────────────────────────────────────────────────────────────
def _lcv_to_wgs84_pts(_gj: dict) -> "pd.DataFrame":
    """landcover geojson → 폴리곤 중심점 lat/lon DataFrame.
    CRS 자동 감지(EPSG:3857/900913/5179/5181/5186) 후 4326 reproject.
    (기존 _render_polygon_distribution 내부 중첩 함수를 모듈 레벨로 이동.)
    """
    src_crs_name = ""
    crs_obj = _gj.get("crs", {}) or {}
    if isinstance(crs_obj, dict):
        src_crs_name = (crs_obj.get("properties", {}) or {}).get("name", "") or ""
    if "3857" in src_crs_name or "900913" in src_crs_name:
        init_crs = "EPSG:3857"
    elif "5179" in src_crs_name:
        init_crs = "EPSG:5179"
    elif "5181" in src_crs_name:
        init_crs = "EPSG:5181"
    elif "5186" in src_crs_name:
        init_crs = "EPSG:5186"
    else:
        init_crs = "EPSG:4326"
    if _HAS_GPD:
        gdf = gpd.GeoDataFrame.from_features(_gj["features"])
        try:
            gdf = gdf.set_crs(init_crs, allow_override=True)
        except Exception:
            pass
        if str(gdf.crs).upper() not in ("EPSG:4326", "WGS 84", "EPSG:4326+CRS84"):
            try:
                gdf = gdf.to_crs(epsg=4326)
            except Exception:
                pass
        pt_series = gdf.geometry.representative_point()
        return pd.DataFrame({
            "lat": [p.y for p in pt_series],
            "lon": [p.x for p in pt_series],
        })
    # gpd 없을 때: 수동 평균 + EPSG:3857 → 4326 변환
    import math
    def _merc_to_wgs(x, y):
        lon = (x / 20037508.34) * 180.0
        lat = (y / 20037508.34) * 180.0
        lat = (180.0/math.pi) * (2.0 * math.atan(math.exp(lat*math.pi/180.0)) - math.pi/2.0)
        return lon, lat
    coords_list = []
    is_mercator = init_crs in ("EPSG:3857",)
    for f_ in _gj["features"]:
        g = f_.get("geometry", {})
        rings = []
        if g.get("type") == "Polygon":
            rings = [g["coordinates"][0]]
        elif g.get("type") == "MultiPolygon":
            rings = [poly[0] for poly in g["coordinates"]]
        for ring in rings:
            xs = [c[0] for c in ring]; ys = [c[1] for c in ring]
            cx, cy = sum(xs)/len(xs), sum(ys)/len(ys)
            if is_mercator:
                lon, lat = _merc_to_wgs(cx, cy)
            else:
                lon, lat = cx, cy
            coords_list.append((lon, lat))
    return pd.DataFrame(coords_list, columns=["lon", "lat"])


@st.cache_data(ttl=3600, show_spinner=False, max_entries=8)
def _landcover_pts_cached(gj_path_str: str, mtime_ns: int) -> "pd.DataFrame":
    """연도별 landcover geojson → 중심점 DataFrame (파일 mtime 키 캐시)."""
    _gj = json.loads(Path(gj_path_str).read_text(encoding="utf-8"))
    return _lcv_to_wgs84_pts(_gj)


@st.cache_data(ttl=3600, show_spinner=False, max_entries=2)
def _eup_geojson_cached(path_str: str, mtime_ns: int) -> dict:
    """읍면동 경계 geojson 파싱 캐시 (파일 mtime 키)."""
    return json.loads(Path(path_str).read_text(encoding="utf-8"))


def _render_polygon_distribution(yr: pd.DataFrame) -> None:
    """④ 시설재배지 분포 지도 — 보고서 그림 형식 (두 연도 좌우 비교).
    제주 본도 + 읍·면·동 경계(local 00_map) 위에 시설재배 폴리곤 중심점을 청색으로 표시.
    좌표 정규화: EPSG:3857 / 900913 → 4326 자동 reproject.
    """
    st.markdown(
        '<p class="subsection-title" style="margin:18px 0 6px;">'
        '④ 시설재배지 분포 지도 (보고서 그림 형식 — 두 연도 좌우 비교)</p>',
        unsafe_allow_html=True,
    )
    st.markdown(
        "<div style='font-size:13px;color:var(--color-text-secondary);margin-bottom:8px;'>"
        "보고서 〈그림 2-16〉(2000년)·〈그림 2-17〉(2023년) 형식: "
        "제주 본도 + 읍·면·동 경계 위에 시설재배 폴리곤 중심점을 청색으로 표시. "
        "베이스맵: <code>data/00_map</code> (외부 타일 미사용).</div>",
        unsafe_allow_html=True,
    )
    avail = LCL.available_years()
    if not avail:
        st.caption("데이터 없음")
        return
    y_left_default = 2000 if 2000 in avail else avail[0]
    y_right_default = 2023 if 2023 in avail else avail[-1]
    sel_l, sel_r = st.columns(2)
    with sel_l:
        y_left = st.selectbox("좌측 연도", avail,
                              index=avail.index(y_left_default),
                              key="tab43_poly_left")
    with sel_r:
        y_right = st.selectbox("우측 연도", avail,
                               index=avail.index(y_right_default),
                               key="tab43_poly_right")

    # ── 로컬 00_map 폴리곤 layer (외부 타일 사용 안 함)
    _RI_LINE  = "rgba(150,150,150,0.45)"
    _EUP_LINE = "#222"
    _POLY_COLOR = "#1f6fb2"
    mb_layers: list = []
    # ── 17차 → 18차: 리경계 layer 제거 (사용자 요청, 너무 조밀)
    # 읍·면·동 경계만 유지
    # 읍·면·동 경계 (진하게)
    try:
        # ⚡ (2026-06-11 G2) mtime 키 캐시 — 매 rerun json.loads 제거
        eup_gj = _eup_geojson_cached(str(_EUP_GEOJSON_PATH),
                                     _EUP_GEOJSON_PATH.stat().st_mtime_ns)
        mb_layers.append(dict(
            sourcetype="geojson", source=eup_gj, type="line",
            line=dict(width=1.2), color=_EUP_LINE,
        ))
    except Exception:
        pass

    # _to_wgs84_pts 중첩 함수는 모듈 레벨 _lcv_to_wgs84_pts + 캐시 wrapper
    # _landcover_pts_cached 로 이동 (2026-06-11 검증팀 G2).

    mL, mR = st.columns(2)
    for col, y_sel, side in [(mL, y_left, "left"), (mR, y_right, "right")]:
        with col:
            st.markdown(
                f"<div style='text-align:center;font-weight:600;margin-bottom:4px;'>"
                f"{y_sel}년 시설재배 분포</div>",
                unsafe_allow_html=True,
            )
            try:
                gj_path = _LCV_RAW_DIR / f"landcover_{y_sel}.geojson"
                if not gj_path.exists():
                    st.caption(f"{y_sel}년 raw geojson 없음 ({gj_path.name})")
                    continue
                # ⚡ (2026-06-11 G2) 30MB 파싱+재투영 → mtime 키 캐시 호출
                pts = _landcover_pts_cached(str(gj_path),
                                            gj_path.stat().st_mtime_ns)
            except Exception as e:
                st.caption(f"{y_sel}년 로드 실패: {e}")
                continue
            fig = go.Figure()
            if not pts.empty:
                fig.add_trace(go.Scattermapbox(
                    lat=pts["lat"], lon=pts["lon"],
                    mode="markers",
                    marker=dict(size=2.5, color=_POLY_COLOR, opacity=0.5),
                    hoverinfo="skip", showlegend=False,
                ))
            fig.update_layout(
                # 19차 사용자 요청: 지도 높이 1.5배 (528 → 792)
                height=792, margin=dict(l=0, r=0, t=8, b=0),
                showlegend=False,
                mapbox=dict(
                    # 외부 타일 미사용 (17차 사용자 요청)
                    style="white-bg",
                    center=dict(lat=33.38, lon=126.55),
                    zoom=9.5, layers=mb_layers,
                ),
            )
            n_pts = 0 if pts.empty else len(pts)
            st.plotly_chart(fig, use_container_width=True,
                            key=f"tab43_poly_map_{side}_{y_sel}")
            st.caption(f"폴리곤 중심점 {format(n_pts, ',')}개")
# EOF — tab43_greenhouse.py
