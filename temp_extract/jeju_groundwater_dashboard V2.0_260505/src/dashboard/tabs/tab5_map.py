# ==============================================================================
#  파일명: src/dashboard/tabs/tab5_map.py
#  탭: ④ 공간 분석 (관측정/AWS) — Build 1.2.02
# ------------------------------------------------------------------------------
#  v1.2.02 변경:
#   - 레이아웃: 지도 1줄 전체 폭 + 그 아래 상세(전체 폭) (요청 1·2)
#   - 모드 라디오 크기 확대 (요청 5)
#   - 기간 라벨: 첫 칸/연도 변경 행만 'YY년 M월', 그 외 'M월' (요청 8·12)
#   - 그래프 범례: '과거 평균' → '과거 N년 해당월 평균' (요청 12)
#   - 각주: 동적 baseline 연도 그룹 표시 (요청 9·13)
#   - 관측정 baseline = 직전 3년 (요청 7·10)
# ==============================================================================

from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from streamlit_folium import st_folium

import config
from src.analysis import effective_rainfall, aws_yearly
from src.collectors import gwlevel_day_parser
from src.dashboard import map_helpers, theme, ag_well_helpers


# ==============================================================================
#  ■ 캐시
# ==============================================================================
@st.cache_data(ttl=600)
def _load_meta_cached() -> pd.DataFrame:
    return map_helpers.load_station_meta()


@st.cache_data(ttl=600)
def _load_day_cached(station: str) -> pd.DataFrame:
    return gwlevel_day_parser.load_station_day(station)


@st.cache_data(ttl=600)
def _list_day_stations_cached() -> list[str]:
    return gwlevel_day_parser.list_day_stations()


# ==============================================================================
#  ■ 색상 헬퍼
# ==============================================================================
def _diff_html(d: float | None, unit: str = "", decimals: int = 1) -> str:
    if d is None:
        return "–"
    c = "#1d9e75" if d >= 0 else "#e24b4a"
    sg = "+" if d >= 0 else ""
    return f'<span style="color:{c};font-weight:500;">{sg}{d:.{decimals}f}{unit}</span>'


# ─── 기간 라벨 헬퍼 ─────────────────────────────────────────
def _smart_period_labels(table: pd.DataFrame) -> list[str]:
    """첫 칸과 연도가 바뀌는 칸은 'YY년 M월', 그 외에는 'M월' 만 반환.

    예) [25년 5월, 6월, 7월, ..., 12월, 26년 1월, 2월, 3월, 4월]
    """
    out, prev_y = [], None
    for _, r in table.iterrows():
        y, m = int(r["연월"][:4]), int(r["연월"][5:7])
        if prev_y is None or y != prev_y:
            out.append(f"{str(y)[2:]}년 {m}월")
        else:
            out.append(f"{m}월")
        prev_y = y
    return out


def _baseline_footnote(table: pd.DataFrame, n_baseline: int,
                       label: str = "과거 N년 평균") -> str:
    """12개월 표를 (year-group) 단위로 묶고, 각 그룹의 baseline 연도 범위를 텍스트로.

    출력 예: "과거 3년 평균 : 5월 ~ 12월 : 22년 ~ 24년 해당 월평균 수위
                          | 1월 ~ 4월 : 23년 ~ 25년 해당 월평균 수위"
    """
    if table.empty:
        return ""
    label = label.replace("N년", f"{n_baseline}년")

    # (year, month) 순서대로 그룹화
    groups: list[tuple[int, list[int]]] = []
    cur_y, cur_ms = None, []
    for _, r in table.iterrows():
        y, m = int(r["연월"][:4]), int(r["연월"][5:7])
        if cur_y is None or y == cur_y:
            cur_y = y
            cur_ms.append(m)
        else:
            groups.append((cur_y, cur_ms))
            cur_y, cur_ms = y, [m]
    if cur_y is not None:
        groups.append((cur_y, cur_ms))

    parts = []
    for y, ms in groups:
        m_first, m_last = ms[0], ms[-1]
        bl_first = (y - n_baseline) % 100
        bl_last = (y - 1) % 100
        if m_first == m_last:
            month_str = f"{m_first}월"
        else:
            month_str = f"{m_first}월 ~ {m_last}월"
        parts.append(
            f"{month_str} : {bl_first:02d}년 ~ {bl_last:02d}년 해당 월평균 수위"
        )
    return f"{label} : " + " &nbsp;|&nbsp; ".join(parts)


# ==============================================================================
#  ■ 메인 렌더 — render() 전체를 단일 @st.fragment 로 (Phase 3 P1).
#    tab6/7/8 와 동일 패턴. 마커 클릭·selectbox·radio 변경 시 fragment-only
#    rerun 으로 처리되어 흰 깜박임·탭 점프 차단.
#    ※ st_folium 의 동적 key (`tab5_map_{mode}`) 는 mode 변경 시 iframe 을
#      재마운트하지만 fragment 안에서도 동일 동작 — 위험 없음.
# ==============================================================================
@st.fragment
def render(asos_df: pd.DataFrame, periods: dict, base_date: date):
    meta = _load_meta_cached()
    day_stations = _list_day_stations_cached()

    if meta.empty:
        st.warning("⚠️ 관측망 정보 파일을 찾을 수 없습니다. data/0_JD관측망_정보.xlsx 확인.")
        return

    # 일자료 CSV 가 있는 관측정만 드롭다운 후보
    avail_stations = [s for s in meta["관측소명"].tolist() if s in day_stations]
    if not avail_stations:
        st.warning("⚠️ data/GWlevel/by_station_day/ 에 일자료 CSV 가 없습니다. "
                   "process_gwlevel_day.py 또는 ⚙️ 데이터 탭에서 파싱을 실행하세요.")
        return

    # ── 세션 상태 (위젯 key 와 동일하게 사용해 양방향 동기화 보장) ──
    aws_names_all = [s["name"] for s in config.STATIONS_ASOS]
    if "tab5_mode" not in st.session_state:
        st.session_state["tab5_mode"] = "관측정"
    if "tab5_station_sel" not in st.session_state:
        st.session_state["tab5_station_sel"] = avail_stations[0]
    if "tab5_aws_sel" not in st.session_state:
        st.session_state["tab5_aws_sel"] = aws_names_all[0]
    # 선택된 관측정이 avail 목록에 없으면(새 데이터 추가 등) 첫 항목으로 보정
    if st.session_state["tab5_station_sel"] not in avail_stations:
        st.session_state["tab5_station_sel"] = avail_stations[0]

    # ── v1.2.06: 직전 실행의 지도 클릭으로 보류된 선택 적용 (위젯 인스턴스화 전!) ──
    # Streamlit 제약: 위젯 key 와 동일한 session_state 는 위젯 렌더 후엔 수정 불가.
    # 따라서 클릭 핸들러는 'tab5_pending' 에만 적어두고 rerun → 다음 실행 최상단에서 적용.
    _pending = st.session_state.pop("tab5_pending", None)
    if _pending:
        p_mode = _pending.get("mode")
        p_val = _pending.get("value")
        if p_mode == "관측정" and p_val in avail_stations:
            st.session_state["tab5_mode"] = "관측정"
            st.session_state["tab5_station_sel"] = p_val
        elif p_mode == "AWS" and p_val in aws_names_all:
            st.session_state["tab5_mode"] = "AWS"
            st.session_state["tab5_aws_sel"] = p_val

    # ── 상단 컨트롤: 모드(폭 2배) + 드롭다운(폭 1/2) + V-World 상태 ──
    # v1.2.03: 라디오 가로 padding 50px → 버튼 폭 ~2배 (요청 3)
    st.markdown("""
    <style>
    div[data-testid="stRadio"][aria-label="모드_t5"] > div[role="radiogroup"] {
        gap: 8px !important;
    }
    div[data-testid="stRadio"][aria-label="모드_t5"] label {
        font-size: 14px !important;
        padding: 8px 50px !important;
        border: 1px solid rgba(26,26,24,0.18) !important;
        border-radius: 6px !important;
        background: #ffffff !important;
        cursor: pointer;
        margin-right: 0 !important;
    }
    div[data-testid="stRadio"][aria-label="모드_t5"] label:has(input:checked) {
        background: #185fa5 !important;
        color: #ffffff !important;
        border-color: #185fa5 !important;
    }
    div[data-testid="stRadio"][aria-label="모드_t5"] label:has(input:checked) p {
        color: #ffffff !important;
    }
    </style>
    """, unsafe_allow_html=True)

    # 컬럼 분할: [라디오 1.4] [좌pad 0.5] [드롭다운 1.0] [우pad 1.5] [VW상태 1.0]
    # → 드롭다운 너비가 c2 컬럼의 1/2 정도가 되도록 좌·우 padding 컬럼으로 좁힘 (요청 4)
    c1, cp1, c2, cp2, c3 = st.columns([1.4, 0.4, 1.2, 1.4, 1.0])
    with c1:
        mode = st.radio(
            "모드_t5", ["관측정", "AWS"],
            horizontal=True,
            key="tab5_mode",
            label_visibility="collapsed",
        )
    with c2:
        if mode == "관측정":
            st.selectbox(
                "관측정 선택", avail_stations,
                key="tab5_station_sel",
                label_visibility="collapsed",
            )
        else:
            st.selectbox(
                "AWS 선택", aws_names_all,
                key="tab5_aws_sel",
                label_visibility="collapsed",
            )
    with c3:
        st.markdown(
            '<div style="font-size:11px;color:#5f5e5a;padding:10px 0;text-align:right;">'
            f'V-World API: <b>{"활성" if config.VWORLD_API_KEY else "비활성 (OSM 폴백)"}</b>'
            "</div>",
            unsafe_allow_html=True,
        )

    # ── 지도: 화면 전체 폭, 높이 1.5배 (요청 5: 520 → 780) ──
    cur_station = (st.session_state["tab5_station_sel"]
                   if mode == "관측정" else None)
    cur_aws = st.session_state["tab5_aws_sel"] if mode == "AWS" else None
    # v1.2.07: 줌 11 — 제주도 본섬이 화면을 가득 채우도록
    m = map_helpers.make_map(zoom=11)
    map_helpers.add_station_markers(m, meta, selected=cur_station)
    map_helpers.add_aws_markers(m, selected=cur_aws)
    st_data = st_folium(
        m, width=None, height=780,
        returned_objects=["last_object_clicked_tooltip"],
        key=f"tab5_map_{mode}",
    )

    # 마커 클릭 → 드롭다운/모드 동기화 (양방향 연동)
    # v1.2.06: 위젯 인스턴스화 후이므로 직접 수정 불가. 'tab5_pending' 에만 적고 rerun.
    clicked_tip = (st_data or {}).get("last_object_clicked_tooltip")
    if clicked_tip:
        tip = str(clicked_tip).replace("★ ", "").replace(" (선택됨)", "").strip()
        if tip.endswith(" AWS"):
            aws_nm = tip[:-4].strip()
            if aws_nm in aws_names_all:
                if (st.session_state.get("tab5_mode") != "AWS"
                        or st.session_state.get("tab5_aws_sel") != aws_nm):
                    st.session_state["tab5_pending"] = {
                        "mode": "AWS", "value": aws_nm
                    }
                    ag_well_helpers.fragment_rerun()
        elif tip in avail_stations:
            if (st.session_state.get("tab5_mode") != "관측정"
                    or st.session_state.get("tab5_station_sel") != tip):
                st.session_state["tab5_pending"] = {
                    "mode": "관측정", "value": tip
                }
                ag_well_helpers.fragment_rerun()

    st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)

    # ── 상세: 화면 전체 폭, 지도 아래 (요청 2) ──
    if mode == "관측정":
        _render_station_detail(st.session_state["tab5_station_sel"], meta,
                                asos_df, base_date, periods)
    else:
        _render_aws_detail(st.session_state["tab5_aws_sel"], asos_df, base_date)


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
    aws_color = config.AWS_COLOR_MAP.get(aws_name, "#185fa5")

    # ── 헤더 (요청 6: 작은 글자 '관측정 분석' 제거 / 요청 7: '관측정 : XXX') ──
    st.markdown(
        f'<h3 style="font-size:18px;font-weight:600;margin:0 0 6px;color:#1a1a18;">'
        f'🌊 관측정 : {station} '
        f'<span style="font-size:12px;font-weight:400;color:#5f5e5a;">'
        f'· {ws_name}유역 · 인접 AWS: {aws_name}</span></h3>',
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
    th = ('padding:5px 8px;background:#f5f5f3;font-size:11px;color:#5f5e5a;'
          'border-bottom:0.5px solid #ddd;text-align:left;font-weight:500;width:110px;')
    td = ('padding:5px 8px;border-bottom:0.5px solid #eee;font-size:12px;'
          'color:#1a1a18;')
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
            f'<p style="font-size:15px;font-weight:600;margin:0;padding:6px 0;">'
            f'지하수위(EL) 일평균 변화</p>',
            unsafe_allow_html=True,
        )
    with h_lbl:
        st.markdown(
            '<p style="font-size:13px;color:#1a1a18;margin:0;padding:10px 0;'
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
            line=dict(color="#185fa5", width=1.4),
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
                         tickfont=dict(size=10))
        fig.update_yaxes(title_text=f"일강수량 ({aws_name}AWS, mm)",
                         row=2, col=1, tickfont=dict(size=10),
                         rangemode="tozero")
        fig.update_xaxes(tickfont=dict(size=10), row=2, col=1)

        # X축 범위 동기화
        x_min = plot_df["날짜"].min()
        x_max = plot_df["날짜"].max()
        fig.update_xaxes(range=[x_min, x_max], row=1, col=1)
        fig.update_xaxes(range=[x_min, x_max], row=2, col=1)

        fig.update_layout(
            height=440,
            margin=dict(t=10, b=8, l=55, r=10),
            font=dict(size=11),
            bargap=0.05,
            showlegend=False,
        )
        st.plotly_chart(fig, use_container_width=True,
                        key=f"t5_st_ts_{station}")

        st.markdown(
            f'<p style="font-size:10px;color:#5f5e5a;margin:0;">'
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
        f'<p style="font-size:15px;font-weight:600;margin:0 0 4px;">'
        f'지하수위(EL) 12개월 월평균과 과거 {n_gw}년 월평균</p>',
        unsafe_allow_html=True,
    )
    month_table = _build_station_12month_table(day_df, base_date, n_gw)
    _render_12month_chart(month_table, "최근 월평균", "m", "#185fa5",
                           key=f"t5_st_12mo_chart_{station}", decimals=2,
                           n_baseline=n_gw)
    _render_12month_table(month_table, unit="m", decimals=2,
                           metric_label="월평균(EL)", n_baseline=n_gw)
    # 동적 baseline 각주
    st.markdown(
        f'<p style="font-size:10px;color:#5f5e5a;margin:4px 0 0;">'
        f'{_baseline_footnote(month_table, n_gw, label="과거 N년 평균")}</p>',
        unsafe_allow_html=True,
    )

    st.markdown("<div style='height:18px;'></div>", unsafe_allow_html=True)

    # ── (요청 15) 최근 12개월 박스플롯: 일평균 EL 분포 ──
    st.markdown(
        f'<p style="font-size:15px;font-weight:600;margin:0 0 4px;">'
        f'최근 12개월 월별 지하수위(EL) 일자료 분포 — 박스플롯</p>',
        unsafe_allow_html=True,
    )
    _render_monthly_boxplot(day_df, base_date, station_color="#185fa5",
                             key=f"t5_st_box_{station}")

    st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)

    # ── (요청 16) 최근 12개월 월별 기초통계표 ──
    st.markdown(
        f'<p style="font-size:15px;font-weight:600;margin:0 0 4px;">'
        f'최근 12개월 월별 일자료 기초통계 (m)</p>',
        unsafe_allow_html=True,
    )
    _render_monthly_stats_table(day_df, base_date)
    st.markdown(
        f'<p style="font-size:10px;color:#5f5e5a;margin:4px 0 0;">'
        f'* 각 월의 일자료(EL) 기준 — 산술평균 / 중앙값 / 최대 / 최소 / 표준편차 / 일수.'
        f'</p>',
        unsafe_allow_html=True,
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
        f'<p style="font-size:11px;color:#5f5e5a;margin:0;letter-spacing:0.06em;">'
        f'AWS 분석</p>'
        f'<h3 style="font-size:18px;font-weight:600;margin:0 0 8px;color:{color};">'
        f'🌧 {aws_name} <span style="font-size:12px;font-weight:400;color:#5f5e5a;">'
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
        f'<p style="font-size:15px;font-weight:600;margin:0 0 4px;">'
        f'월별 강수량 — 직전 12개월 (mm)</p>',
        unsafe_allow_html=True,
    )
    _render_12month_chart(rain_table, "강수량", "mm", color,
                           key=f"t5_aws_rain_{aws_name}", decimals=0,
                           n_baseline=n_rain)

    st.markdown("<div style='height:6px;'></div>", unsafe_allow_html=True)
    st.markdown(
        f'<p style="font-size:15px;font-weight:600;margin:0 0 4px;">'
        f'강수량 비교표 — 직전 12개월 (mm)</p>',
        unsafe_allow_html=True,
    )
    _render_12month_table(rain_table, unit="mm", decimals=0,
                           metric_label="월강수량", n_baseline=n_rain)
    # 요청 13: 강수량 비교표 각주
    st.markdown(
        f'<p style="font-size:10px;color:#5f5e5a;margin:4px 0 0;">'
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
        f'<p style="font-size:15px;font-weight:600;margin:0 0 4px;">'
        f'월별 농업유효 강수일수 — 직전 12개월 (일)</p>'
        f'<p style="font-size:10px;color:#5f5e5a;margin:0 0 4px;">'
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
            f'<p style="font-size:15px;font-weight:600;margin:0;'
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
        f'<p style="font-size:15px;font-weight:600;margin:0 0 4px;">'
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
        font=dict(size=11),
        showlegend=False,
        bargap=0,
        yaxis=dict(rangemode="tozero"),
    )
    st.plotly_chart(fig_d, use_container_width=True,
                    key=f"t5_aws_10y_daily_{aws_name}")

    # ── ② 월별 강수량 추이 ──
    st.markdown(
        f'<p style="font-size:15px;font-weight:600;margin:8px 0 4px;">'
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
        font=dict(size=11),
        showlegend=False,
        bargap=0.1,
    )
    st.plotly_chart(fig, use_container_width=True,
                    key=f"t5_aws_10y_{aws_name}")
    st.markdown(
        f'<p style="font-size:10px;color:#5f5e5a;margin:0;">'
        f'데이터 전체 범위: {earliest_ym} ~ {latest_ym} '
        f'&nbsp;|&nbsp; 총 {len(df_m)}개월 (선택 표시: {len(plot)}개월) '
        f'&nbsp;|&nbsp; 일자료: {len(daily):,}일</p>',
        unsafe_allow_html=True,
    )

    # ── ③ 12개월 유효강수 비교표 (요청 5: 위치 이동 — 10년 유효 차트 직상단) ──
    st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)
    st.markdown(
        f'<p style="font-size:15px;font-weight:600;margin:0 0 4px;">'
        f'농업유효강수일수 비교표 — 직전 12개월 (일)</p>',
        unsafe_allow_html=True,
    )
    _render_12month_table(eff_table, unit="일", decimals=0,
                           metric_label="유효강수일수", n_baseline=n_rain)
    st.markdown(
        f'<p style="font-size:10px;color:#5f5e5a;margin:4px 0 0;">'
        f'{_baseline_footnote(eff_table, n_rain, label="과거 N년 평균")}</p>',
        unsafe_allow_html=True,
    )

    # ── ④ 월별 농업유효강수일수 추이 (요청 1·2·3: Y축 0~15, 2씩, ≥15 라벨) ──
    st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)
    st.markdown(
        f'<p style="font-size:15px;font-weight:600;margin:0 0 4px;">'
        f'월별 농업유효강수일수 추이 — {aws_name} (10년+ 범위)</p>'
        f'<p style="font-size:10px;color:#5f5e5a;margin:0 0 4px;">'
        f'기준: 일강수량 {config.EFFECTIVE_RAINFALL_THRESHOLD_MM} mm 이상 / '
        f'시작월은 위 강수량 차트와 공유</p>',
        unsafe_allow_html=True,
    )
    eff_color = "#1d9e75"
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
        textfont=dict(size=10, color=eff_color, family="Arial Black"),
        cliponaxis=False,
        hovertemplate="%{x}<br>%{y:.0f} 일<extra></extra>",
    ))
    fig2.update_layout(
        height=270,
        xaxis_title="", yaxis_title="유효강수일수 (일)",
        margin=dict(t=14, b=8, l=50, r=10),
        font=dict(size=11),
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
        textfont=dict(size=9, color="#5f5e5a"),
        cliponaxis=False,
        hovertemplate=f"%{{x}}<br>{avg_legend}: %{{y:.{decimals}f}} {unit}<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        name=f"실측 {metric_label}", x=xs, y=actual,
        marker=dict(color=color),
        text=[(f"{v:.{decimals}f}" if v is not None else "") for v in actual],
        textposition="outside",
        textfont=dict(size=9, color="#1a1a18"),
        cliponaxis=False,
        hovertemplate=f"%{{x}}<br>실측: %{{y:.{decimals}f}} {unit}<extra></extra>",
    ))
    fig.update_layout(
        barmode="group", height=260,
        xaxis_title="", yaxis_title=unit,
        xaxis=dict(tickfont=dict(size=11), tickangle=0),
        bargap=0.25, bargroupgap=0.12,
        margin=dict(t=18, b=8, l=44, r=8),
        showlegend=True,
        legend=dict(orientation="h", yanchor="top", y=1.20,
                    xanchor="right", x=1.0, font=dict(size=11)),
        font=dict(size=11),
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
    th_pd = ('padding:5px 6px;background:#f5f5f3;text-align:center;'
             'border-bottom:1.5px solid #ccc;font-size:11px;font-weight:500;'
             'color:#5f5e5a;')
    # 요청 12: 기간 헤더 셀(좌측 라벨 + 12개 월 라벨) 모두 중앙 정렬
    th_lbl = ('padding:5px 8px;background:#f5f5f3;text-align:center;'
              'border-bottom:1.5px solid #ccc;font-size:12px;font-weight:600;'
              'color:#1a1a18;')

    period_labels = _smart_period_labels(table)

    head = (
        '<table style="width:100%;border-collapse:collapse;font-size:12px;table-layout:fixed;">'
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
               'font-size:12px;')
    label_td = ('padding:5px 8px;border-bottom:0.5px solid #eee;text-align:left;'
                'font-size:12px;color:#5f5e5a;')

    def _fmt(v):
        return ("–" if v is None
                else (f"{int(round(v))}" if decimals == 0
                      else f"{v:.{decimals}f}"))

    # 행 1: 실측
    body = f'<tr><td style="{label_td};font-weight:500;color:#1a1a18;">실측 {metric_label} ({unit})</td>'
    for _, r in table.iterrows():
        v = r["실측"]
        body += f'<td style="{base_td};font-weight:600;">{_fmt(v)}</td>'
    body += "</tr>"
    # 행 2: 과거 평균 (n_baseline 동적)
    body += (f'<tr><td style="{label_td};">'
             f'과거 {n_baseline}년 평균 ({unit})</td>')
    for _, r in table.iterrows():
        v = r["평균"]
        body += f'<td style="{base_td};color:#5f5e5a;">{_fmt(v)}</td>'
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
                   tickfont=dict(size=11)),
        yaxis=dict(tickfont=dict(size=10)),
        margin=dict(t=10, b=8, l=50, r=8),
        font=dict(size=11),
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

    th = ('padding:6px 8px;background:#f5f5f3;text-align:center;'
          'border-bottom:1.5px solid #ccc;font-size:12px;font-weight:600;'
          'color:#1a1a18;')
    td = ('padding:5px 6px;border-bottom:0.5px solid #eee;text-align:center;'
          'font-size:12px;')
    label_td = ('padding:5px 8px;border-bottom:0.5px solid #eee;text-align:center;'
                'font-size:12px;color:#5f5e5a;')

    head = (
        '<table style="width:100%;border-collapse:collapse;font-size:12px;table-layout:fixed;">'
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
        body += f'<tr><td style="{label_td};font-weight:500;color:#1a1a18;">{label}</td>'
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
