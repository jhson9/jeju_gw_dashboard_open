# ==============================================================================
#  파일명: src/dashboard/tabs/_tab13_well_detail.py
#  ⑦ 수질 분석 탭 — 관정 선택 바 + 검색 + 상세 (수질 막대 / 강수량 / 5항목 표)
#
#  Source 분리: tab13_ag_quality.py 2101줄 → 그룹별 분리 4단계 (2026-05-09).
#    - _render_well_selection_bar : 선택 관정 표시 + 검색 + 선택 해제 버튼
#    - _render_well_search_input  : 관정명 검색 (Enter → 선택)
#    - _select_aws_for_well       : 관정의 watershed → 인접 AWS 결정
#    - _render_well_detail        : 상세 (1) 수질 막대 + (2) 강수량 + (3) 5항목 표
#    - _bar_color                 : 반기·부적합 4가지 조합 색상
#    - _render_quality_bar        : 선택 항목 시계열 막대
#    - _render_rainfall_bar       : AWS 반기강수량 막대 (Y=0~1000)
#    - _render_quality_table      : 5항목 시계열 표 (2단 헤더)
#    - _BAR_COLOR_HALF, _BAR_COLOR_EXCEED_HALF, _BAR_COLOR_EXCEED, _RAIN_COLOR_HALF
#
#  외부 사용처: tab13_ag_quality.py 내부 전용. _tab13_map._render_map 도 lazy import.
# ==============================================================================
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import config
from src.analysis import ag_well_loader
from src.dashboard import ag_well_helpers, theme
from src.dashboard.tabs._tab13_helpers import (
    QUALITY_ITEM_ORDER,
    _cached_asos_data,
    _clean_no_data_rows,
    _fmt_item,
    _yh_idx_series,
    _yh_to_date,
)


# fragment_rerun alias (ag_well_helpers 의 facade 통해)
_fragment_rerun = ag_well_helpers.fragment_rerun


# ==============================================================================
#  관정 선택 바 (+ 검색) — 공용 헬퍼로 위임 (tab7 과 110 줄 공유)
# ==============================================================================
from src.dashboard.tabs._ag_well_select_helpers import (
    render_well_selection_bar as _shared_render_well_selection_bar,
    render_well_search_input as _shared_render_well_search_input,
    render_map_header_with_search as _shared_render_map_header_with_search,
)


_QTY_PLACEHOLDER = "관정명 입력 후 Enter (예: F-273)"


def _render_well_selection_bar(
    df_master: pd.DataFrame, selected_permit: "str | None",
    *, include_search: bool = True,
) -> None:
    """선택된 관정 표시 + (옵션) 검색 + 선택 해제 — 이용량 탭과 동일 UX.

    2026-05-17: 검색 input 을 지도 헤더 라인으로 이동 → 본 바는 선택 표시 +
    해제만 노출하는 모드(`include_search=False`) 추가.
    """
    _shared_render_well_selection_bar(
        df_master, selected_permit,
        key_prefix="qty",
        search_placeholder=_QTY_PLACEHOLDER,
        include_search=include_search,
    )


def _render_well_search_input(df_master: pd.DataFrame) -> None:
    """관정명 검색 — 공용 헬퍼 위임 (key prefix='qty')."""
    _shared_render_well_search_input(
        df_master,
        key_prefix="qty",
        placeholder=_QTY_PLACEHOLDER,
    )


def _render_map_header_with_search(
    df_master: pd.DataFrame, *, title_html: str,
) -> None:
    """지도 헤더 라인 — [제목] + [검색 input] (수질 탭, 2026-05-17)."""
    _shared_render_map_header_with_search(
        df_master,
        key_prefix="qty",
        search_placeholder=_QTY_PLACEHOLDER,
        title_html=title_html,
    )


# ==============================================================================
#  관정 상세 — 항목 단일 막대 + 강수량(½) + 5항목 표
# ==============================================================================
def _select_aws_for_well(info: dict) -> "str | None":
    """관정의 watershed 로 인접 AWS 1개 결정. 매핑 실패 시 None."""
    if not info:
        return None
    ws = info.get("watershed")
    if not ws or (isinstance(ws, float) and pd.isna(ws)):
        return None
    raw = str(ws).strip()
    candidates = [raw]
    if raw.endswith("수역"):
        candidates.append(raw[:-2])
    else:
        candidates.append(raw + "수역")
    for cand in candidates:
        aws = config.WATERSHED_AWS_MAP.get(cand)
        if aws:
            return aws
    return None


def _render_well_detail(
    permit_no: str, df_master_f: pd.DataFrame, item: str,
) -> None:
    """선택 관정 상세:
       (1) 선택 항목 단일 막대 (Y=기준×2, 매 바마다 상/하·연도 X 라벨)
       (2) AWS 반기강수량 막대 (½ 높이, Y=0~1000, 동일 X 축)
       (3) 5항목 시계열 표 — 행=항목, 열=(연도/반기) 2단 헤더
    """
    df_qual_all = ag_well_loader.load_quality_semiannual()
    sub = df_qual_all[df_qual_all["permit_no"] == permit_no].copy()
    # 사용자 요청 #3: 측정 자료 없는 행 정리 (pH=0 → 모두 NaN)
    sub = _clean_no_data_rows(sub)
    if sub.empty:
        st.caption("선택된 관정의 수질 자료가 없습니다.")
        return

    sub["_yh"] = _yh_idx_series(sub["year"], sub["half"])
    sub = sub.sort_values("_yh").reset_index(drop=True)

    sub["_date"] = sub.apply(
        lambda r: _yh_to_date(r["year"], r["half"]), axis=1
    )
    sub = sub.dropna(subset=["_date"])
    if sub.empty:
        st.caption("선택된 관정의 시기 정보가 누락되어 표시할 수 없습니다.")
        return

    info = ag_well_loader.get_well_info(permit_no)
    aws_name = _select_aws_for_well(info or {})
    well_id = (info.get("well_id") if info else permit_no) or permit_no

    # ── 두 차트가 공유할 X tick · 범위 (사용자 요청 #10·#11)
    yh_min = int(sub["_yh"].min())
    yh_max = int(sub["_yh"].max())
    tick_dates: list[pd.Timestamp] = []
    tick_text: list[str] = []
    for i in range(yh_min, yh_max + 1):
        y = i // 2
        h = "상" if i % 2 == 0 else "하"
        d = _yh_to_date(y, h)
        tick_dates.append(d)
        # 매 바마다 "상/하" + 연도 모두 표시 (요청 #10)
        tick_text.append(f"{h}<br>{y}")
    x_min = tick_dates[0] - pd.Timedelta(days=120)
    x_max = tick_dates[-1] + pd.Timedelta(days=120)

    # ── (1) 선택 항목 단일 막대 (제목에 well_id 포함, 요청 #7)
    _render_quality_bar(sub, item, tick_dates, tick_text, x_min, x_max,
                         well_id=well_id)

    # ── (2) AWS 반기강수량 막대 (Y=0~1000, 동일 X 축)
    _render_rainfall_bar(aws_name, tick_dates, tick_text, x_min, x_max)

    # ── (3) 5항목 시계열 표 (행=항목, 열=시기) + well_id 제목
    _render_quality_table(sub, well_id)


# 반기별 막대 색상 — 4 가지 조합 (상/하 × 정상/부적합).
#   사용자 요청: 부적합일 때도 상/하 가 색깔로 구분되어야 함.
#   - 상 정상: 라이트 그린 / 하 정상: 다크 그린
#   - 상 부적합: 라이트 레드 / 하 부적합: 다크 레드
#   라이트(연한)/다크(짙은) 의 톤 차이로 부적합 안에서도 상/하 구분 가능.
_BAR_COLOR_HALF = {"상": "#9CCC65", "하": "#33691E"}
_BAR_COLOR_EXCEED_HALF = {"상": "#EF9A9A", "하": "#B71C1C"}
# 레거시 호환: 단색 부적합 색상 (다른 곳에서 import 했을 때 깨지지 않게)
_BAR_COLOR_EXCEED = theme.COLOR_ACCENT_DARKRED


def _bar_color(half: str, exceed: bool) -> str:
    """막대 색상: (반기, 부적합) 조합으로 4가지."""
    h = str(half).strip()
    if exceed:
        return _BAR_COLOR_EXCEED_HALF.get(h, _BAR_COLOR_EXCEED)
    return _BAR_COLOR_HALF.get(h, "#9CCC65")


def _render_quality_bar(
    sub: pd.DataFrame, item: str,
    tick_dates: list, tick_text: list,
    x_min: pd.Timestamp, x_max: pd.Timestamp,
    well_id: str = "",
) -> None:
    """선택 항목의 시계열 막대.

    - Y 축: 기준값 × 2 (사용자 요청 #13 — 질산성질소 기준 30 → 40).
            기준 없는 EC 는 데이터 max × 1.3.
    - 바 위 라벨: 측정값.
    - X 축: 호출자가 빌드한 tick_dates/tick_text 사용 — 매 바 아래 "상/하 + YYYY"
            (요청 #10), 강수량 차트와 X 축 공유 (요청 #11).
    - 바 색상: 상=라이트그린, 하=다크그린, 부적합=빨강.
    """
    std = config.WATER_QUALITY_STANDARDS.get(item, {})
    item_kor = std.get("kor", item)
    unit = std.get("unit", "")

    if item not in sub.columns:
        st.caption(f"{item_kor} 자료가 없습니다.")
        return
    ys = sub[item]
    if ys.dropna().empty:
        st.caption(f"{item_kor} 측정값이 없습니다.")
        return

    # Y 축 max — 기준값 × 2 (요청 #13)
    if "max" in std:
        y_top = float(std["max"]) * 2.0
    else:
        data_max = float(ys.dropna().max())
        y_top = max(data_max * 1.3, 1.0)

    # 사용자 요청 #1: 항목별 소수점 자릿수 고정.
    text_labels = [
        "" if pd.isna(v) else _fmt_item(v, item)
        for v in ys
    ]

    exc_col = f"{item}_exceed"
    excs = (
        sub[exc_col].fillna(False).astype(bool).tolist()
        if exc_col in sub.columns else [False] * len(sub)
    )
    halves = [str(h).strip() for h in sub["half"].tolist()]
    # 사용자 요청 #3: 부적합 시에도 상/하 색상 구분 (4가지 조합)
    bar_colors = [_bar_color(h, e) for e, h in zip(excs, halves)]

    x_dates = sub["_date"].tolist()

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=x_dates, y=ys,
        marker_color=bar_colors,
        text=text_labels,
        textposition="outside",
        textfont=dict(size=13, color=theme.COLOR_TEXT_PRIMARY),
        cliponaxis=False,
        width=1000 * 60 * 60 * 24 * 90,  # 90 days in ms
        hovertemplate=f"<b>%{{x|%Y-%m}}</b><br>{item_kor}: %{{y:.2f}} {unit}<extra></extra>",
        name=item_kor,
    ))

    if "max" in std:
        fig.add_hline(
            y=std["max"], line_dash="dash", line_color=theme.COLOR_QUALITY_MAX,
            line_width=1.2, opacity=0.7,
            annotation_text=f"기준 ≤ {std['max']} {unit}",
            annotation_position="top right",
            annotation_font=dict(size=13, color=theme.COLOR_QUALITY_MAX),
        )
    if "min" in std:
        fig.add_hline(
            y=std["min"], line_dash="dash", line_color=theme.COLOR_QUALITY_MAX,
            line_width=1.2, opacity=0.6,
            annotation_text=f"기준 ≥ {std['min']} {unit}",
            annotation_position="bottom right",
            annotation_font=dict(size=13, color=theme.COLOR_QUALITY_MAX),
        )

    # 사용자 요청 #7: 선택 관정명을 제목에 포함
    title_prefix = f"{well_id} " if well_id else ""
    st.markdown(
        f'<div class="subsection-title" style="color:var(--color-text-info);'
        f'margin-top:10px;margin-bottom:0;">'
        f'{title_prefix}{item_kor} 시계열 ({unit})'
        f'</div>',
        unsafe_allow_html=True,
    )
    fig.update_layout(
        height=320,
        margin=dict(l=10, r=10, t=24, b=64),
        plot_bgcolor="white",
        showlegend=False,
        bargap=0.2,
    )
    fig.update_yaxes(
        range=[0, y_top], tickfont=dict(size=13),
        title=dict(text=unit, font=dict(size=13)),
    )
    # X 축 — 호출자가 빌드한 공유 tick 사용 (강수량 차트와 동일)
    fig.update_xaxes(
        tickvals=tick_dates, ticktext=tick_text,
        range=[x_min, x_max],
        tickangle=0, tickfont=dict(size=13),
        title=None,
    )
    st.plotly_chart(fig, use_container_width=True)


# 강수량 막대 색상 — 사용자 요청 #12: 푸른 계열, 상/하 색상 차별화.
_RAIN_COLOR_HALF = {"상": "#9CC3D5", "하": "#1F4E79"}


def _render_rainfall_bar(
    aws_name: "str | None",
    tick_dates: list, tick_text: list,
    x_min: pd.Timestamp, x_max: pd.Timestamp,
) -> None:
    """반기강수량 막대 (½ 높이, Y=0~1000).

    - 6개월 합계: 1~6월 → 상, 7~12월 → 하.
    - Y 축: 0 ~ 1000 mm, dtick=250 (요청 #4).
    - X 축: 수질 차트와 동일 tickvals/ticktext 사용 (요청 #11).
    - 색상: 상=라이트블루, 하=다크블루 (요청 #12).
    """
    if not aws_name:
        st.caption("적용 AWS 가 매핑되지 않아 강수량 그래프를 생략합니다.")
        return

    asos_df = _cached_asos_data()
    if asos_df is None or asos_df.empty:
        st.caption("ASOS 강수량 자료를 찾을 수 없습니다.")
        return

    sub = asos_df[asos_df["지점명"] == aws_name].copy()
    if sub.empty:
        st.caption(f"{aws_name} AWS 자료가 없습니다.")
        return

    sub["일시"] = pd.to_datetime(sub["일시"], errors="coerce")
    sub = sub.dropna(subset=["일시"])
    sub = sub[(sub["일시"] >= x_min) & (sub["일시"] <= x_max)]
    if sub.empty:
        st.caption(f"{aws_name} AWS — 해당 기간 자료가 없습니다.")
        return

    # 반기 합계
    sub["_y"] = sub["일시"].dt.year
    sub["_half"] = sub["일시"].dt.month.apply(lambda m: "상" if m <= 6 else "하")
    rain = (
        sub.groupby(["_y", "_half"])["일강수량(mm)"]
           .sum().reset_index()
    )
    rain.columns = ["year", "half", "rainfall"]
    rain["period"] = rain.apply(
        lambda r: _yh_to_date(r["year"], r["half"]), axis=1
    )
    rain = rain.dropna(subset=["period"]).sort_values("period")

    if rain.empty:
        st.caption(f"{aws_name} AWS — 반기 합계 자료가 없습니다.")
        return

    # 색상 — 푸른 계열 (요청 #12)
    bar_colors = [
        _RAIN_COLOR_HALF.get(str(h), "#5B9BD5") for h in rain["half"]
    ]

    st.markdown(
        f'<div class="subsection-title" style="color:var(--color-text-info);'
        f'margin-top:6px;margin-bottom:0;">'
        f'{aws_name} AWS 반기강수량 (mm)'
        f'</div>',
        unsafe_allow_html=True,
    )
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=rain["period"], y=rain["rainfall"],
        marker_color=bar_colors,
        width=1000 * 60 * 60 * 24 * 90,
        text=[f"{v:.0f}" for v in rain["rainfall"]],
        textposition="outside",
        textfont=dict(size=13),
        cliponaxis=False,
        hovertemplate=(
            "%{x|%Y-%m}<br>반기 강수량: %{y:,.0f} mm<extra></extra>"
        ),
    ))
    fig.update_layout(
        height=160,
        margin=dict(l=10, r=10, t=10, b=64),
        plot_bgcolor="white",
        showlegend=False,
        bargap=0.2,
    )
    fig.update_yaxes(
        range=[0, 1000], dtick=250,
        tickfont=dict(size=13),
        title=dict(text="mm", font=dict(size=13)),
    )
    # X 축 — 수질 차트와 동일 (요청 #11)
    fig.update_xaxes(
        tickvals=tick_dates, ticktext=tick_text,
        range=[x_min, x_max],
        tickangle=0, tickfont=dict(size=13),
        title=None,
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_quality_table(sub: pd.DataFrame, well_id: str) -> None:
    """5항목 시계열 표 (행=항목, 열=시기).

    헤더 2단 (요청 #9):
      - 1행: 항목(rowspan=2) + 연도(colspan=2) ...
      - 2행: 상 / 하 / 상 / 하 ...
    제목: "{well_id} 수질 5항목 시계열 표" (요청 #7).
    부적합 셀 빨강 + 굵게.
    """
    items = QUALITY_ITEM_ORDER

    # ── 시기 컬럼 결정 — sub 에 존재하는 모든 (year, half) 페어를 정렬해 그대로 사용.
    #   같은 (year, half) 가 중복되면 가장 마지막 행 채택 (sub 는 _yh 기준 정렬됨).
    sub_v = sub.dropna(subset=["year"]).copy()
    if sub_v.empty:
        st.caption("표시할 시기 자료가 없습니다.")
        return
    sub_v["_yint"] = sub_v["year"].astype("Int64").astype(int)
    sub_v["_hstr"] = sub_v["half"].astype(str).str.strip()

    # 데이터에 등장하는 모든 (year, half) → 한 셀당 한 행 dict 매핑
    row_by_yh: dict[tuple[int, str], pd.Series] = {}
    for _, r in sub_v.iterrows():
        row_by_yh[(int(r["_yint"]), r["_hstr"])] = r

    # 컬럼 시기 = 가용한 모든 연도 × (상, 하) — 데이터에 한 쪽만 있어도 양쪽 컬럼 생성해
    # year colspan=2 가 깨지지 않도록 (요청 #9).
    years_present = sorted(sub_v["_yint"].unique().tolist())
    period_cols: list[tuple[int, str]] = [
        (y, h) for y in years_present for h in ("상", "하")
    ]
    if not period_cols:
        st.caption("표시할 시기 자료가 없습니다.")
        return

    css = """
    <style>
    .qty-table-wrap {
        width: 100%;
        overflow-x: auto;
        margin: 10px 0 8px;
    }
    .qty-table {
        border-collapse: collapse;
        font-size: 15px; color: var(--color-text-primary);
        border: 0.5px solid rgba(26,26,24,0.18);
        min-width: 100%;
    }
    .qty-table th, .qty-table td {
        padding: 4px 6px;
        border: 0.5px solid rgba(26,26,24,0.10);
        text-align: center;
        font-variant-numeric: tabular-nums;
        white-space: nowrap;
    }
    .qty-table thead th.year-th {
        background: var(--color-text-info); color: var(--color-bg-primary);
        font-weight: 700; font-size: 16px;
    }
    .qty-table thead th.half-th {
        background: var(--color-bg-info); color: var(--color-text-info);
        font-weight: 600; font-size: 15px;
    }
    .qty-table thead th.item-th {
        background: var(--color-accent-blue-3); color: var(--color-bg-primary);
        font-weight: 700; vertical-align: middle;
        text-align: left; padding-left: 10px;
    }
    .qty-table td.item-cell {
        background: var(--color-bg-secondary);
        color: var(--color-text-info); font-weight: 600;
        text-align: left; padding-left: 10px;
        min-width: 110px;
    }
    .qty-table td.exceed {
        background: #fdecea;
        color: var(--color-accent-darkred); font-weight: 700;
    }
    .qty-table tbody tr:nth-child(even) td:not(.item-cell):not(.exceed) {
        background: #fafaf8;
    }
    /* 연도 경계선 (홀수 컬럼 = 새 연도 시작) */
    .qty-table th.year-sep, .qty-table td.year-sep {
        border-left: 2px solid #185fa5 !important;
    }
    </style>
    """

    # ── 1행 헤더: 항목(rowspan=2) + 연도(colspan=2) 반복
    head1 = ['<tr><th class="item-th" rowspan="2">항목</th>']
    for i, y in enumerate(years_present):
        sep_cls = " year-sep" if i > 0 else ""
        head1.append(f'<th class="year-th{sep_cls}" colspan="2">{y}</th>')
    head1.append("</tr>")

    # ── 2행 헤더: 상반기 / 하반기 반복 (사용자 요청 #5)
    head2 = ["<tr>"]
    for i, _y in enumerate(years_present):
        sep_cls = " year-sep" if i > 0 else ""
        head2.append(f'<th class="half-th{sep_cls}">상반기</th>')
        head2.append('<th class="half-th">하반기</th>')
    head2.append("</tr>")

    head = "<thead>" + "".join(head1) + "".join(head2) + "</thead>"

    def _cell(v, exceed: bool, item: str, sep: bool) -> str:
        sep_cls = " year-sep" if sep else ""
        if v is None or (isinstance(v, float) and pd.isna(v)):
            # 사용자 요청 #3: 측정값 없으면 '0' 도 안 적고 '-' 표시
            return f'<td class="{sep_cls.strip()}">-</td>' if sep_cls else '<td>-</td>'
        text = _fmt_item(v, item)
        cls = ("exceed" + sep_cls).strip() if exceed else sep_cls.strip()
        if cls:
            return f'<td class="{cls}">{text}</td>'
        return f'<td>{text}</td>'

    body_rows = []
    for it in items:
        std = config.WATER_QUALITY_STANDARDS.get(it, {})
        item_label = (
            f'{std.get("kor", it)} '
            f'<span style="font-weight:400;opacity:0.85;font-size:14px;">'
            f'({std.get("unit", "")})</span>'
        )

        cells = [f'<td class="item-cell">{item_label}</td>']
        for col_idx, (y, h) in enumerate(period_cols):
            r = row_by_yh.get((y, h))
            v = r.get(it) if (r is not None and it in r.index) else None
            exc = bool(r.get(f"{it}_exceed")) if r is not None else False
            # 새 연도의 첫 컬럼(=상)에 좌측 경계선
            sep = (h == "상" and col_idx > 0)
            cells.append(_cell(v, exc, it, sep))
        body_rows.append("<tr>" + "".join(cells) + "</tr>")

    table = (
        css
        + '<div class="qty-table-wrap">'
        + '<table class="qty-table">'
        + head
        + "<tbody>" + "".join(body_rows) + "</tbody>"
        + "</table></div>"
    )
    # 요청 #7: 제목에 well_id 포함
    st.markdown(
        f'<div class="subsection-title" style="color:var(--color-text-info);'
        f'margin-top:8px;margin-bottom:0;">'
        f'{well_id} 수질 5항목 시계열 표</div>',
        unsafe_allow_html=True,
    )
    st.markdown(table, unsafe_allow_html=True)
