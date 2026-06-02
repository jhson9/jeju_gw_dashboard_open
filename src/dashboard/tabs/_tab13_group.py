# ==============================================================================
#  파일명: src/dashboard/tabs/_tab13_group.py
#  ⑦ 수질 분석 탭 — 그룹별 박스 플롯 + 시계열 표 섹션
#
#  Source 분리: tab13_ag_quality.py 2101줄 → 그룹별 분리 5단계 (마지막) (2026-05-09).
#    - _region_label_short            : 그룹 분석 제목용 짧은 지역명
#    - _render_group_section          : 메인 진입점 — 박스 플롯 2개 + 시계열 표
#    - _render_group_box_latest       : 마지막 연도 그룹별 박스 플롯
#    - _render_half_box               : (연도, 반기) 박스 플롯 (분석기간 전체)
#    - _render_group_timeseries_table : 그룹 × 시기 평균값 표 (2단 헤더)
#
#  외부 사용처: tab13_ag_quality.py 내부 전용.
# ==============================================================================
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import config
from src.dashboard import theme
from src.dashboard.tabs._tab13_helpers import (
    _LEVEL_TO_LOC_COL,
    _fmt_item,
    _hex_to_rgba,
    _yh_idx,
)


# ==============================================================================
#  그룹별 박스 플롯 + 시계열 표 (사용자 요청 #5·#6·#7)
# ==============================================================================
def _region_label_short(loc_sel: dict) -> str:
    """그룹 분석 제목용 짧은 지역명. 가장 좁은 cascading 단계 우선."""
    return (
        loc_sel.get("well_ri")
        or loc_sel.get("well_eup")
        or loc_sel.get("well_si")
        or "제주도 전역"
    )


def _render_group_section(
    qf: pd.DataFrame,
    item: str,
    level: str,
    loc_sel: dict,
    yh_lo: "tuple[int, str]",
    yh_hi: "tuple[int, str]",
) -> None:
    """집계 단위(level) 의 한 단계 아래 그룹(loc_col) 단위로 분석:
       (1) 박스 플롯 (분석기간 마지막 연도) — 그룹별 분포
       (2) 박스 플롯 (전 분석기간) — 상/하반기 분포
       (3) 시계열 표 — 행=그룹, 열=시기 평균값
    """
    if qf.empty or item not in qf.columns:
        return

    loc_col, loc_label_kor = _LEVEL_TO_LOC_COL.get(level, (None, None))
    if not loc_col or loc_col not in qf.columns:
        return

    std = config.WATER_QUALITY_STANDARDS.get(item, {})
    item_kor = std.get("kor", item)
    unit = std.get("unit", "")
    region = _region_label_short(loc_sel)

    # ── 그룹 컬럼 정리 (빈 문자열·nan 제거)
    work = qf.dropna(subset=[item, loc_col]).copy()
    work[loc_col] = work[loc_col].astype(str).str.strip()
    work = work[work[loc_col] != ""]
    work = work[~work[loc_col].str.lower().isin(["nan", "none"])]
    if work.empty:
        st.caption("그룹별 분석에 사용할 자료가 없습니다.")
        return

    # ── (1) 마지막 연도 그룹별 박스 플롯
    _render_group_box_latest(work, item, loc_col, loc_label_kor,
                              region, item_kor, unit)

    # ── (2) 상/하반기 박스 플롯 (분석기간 전체)
    _render_half_box(work, item, region, item_kor, unit, yh_lo, yh_hi)

    # ── (3) 그룹 × 시기 시계열 표
    _render_group_timeseries_table(work, item, loc_col, loc_label_kor,
                                    region, item_kor, unit)


def _render_group_box_latest(
    work: pd.DataFrame, item: str, loc_col: str, loc_label_kor: str,
    region: str, item_kor: str, unit: str,
) -> None:
    """그룹별 박스 플롯 — 분석기간 내 가장 최근 연도 데이터."""
    if "year" not in work.columns or work["year"].dropna().empty:
        return
    latest_year = int(work["year"].dropna().max())
    sub = work[work["year"] == latest_year]
    if sub.empty:
        return

    # 그룹 정렬 — 평균값 내림차순 (이용량 탭과 동일)
    order = (
        sub.groupby(loc_col)[item].mean()
           .sort_values(ascending=False).index.tolist()
    )
    if not order:
        return

    std = config.WATER_QUALITY_STANDARDS.get(item, {})
    fig = go.Figure()
    for g in order:
        gv = sub[sub[loc_col] == g][item].dropna()
        if gv.empty:
            continue
        fig.add_trace(go.Box(
            y=gv, name=str(g),
            boxpoints="outliers",
            marker=dict(size=4, color=theme.COLOR_ACCENT_BLUE_2),
            line=dict(width=1.2, color=theme.COLOR_ACCENT_BLUE_2),
            fillcolor="#9DC3E6",
        ))
    # 기준선
    if "max" in std:
        fig.add_hline(
            y=std["max"], line_dash="dash", line_color=theme.COLOR_QUALITY_MAX,
            line_width=1.0, opacity=0.7,
            annotation_text=f"기준 ≤ {std['max']}",
            annotation_font=dict(size=13, color=theme.COLOR_QUALITY_MAX),
        )
    if "min" in std:
        fig.add_hline(
            y=std["min"], line_dash="dash", line_color=theme.COLOR_QUALITY_MAX,
            line_width=1.0, opacity=0.6,
        )
    fig.update_layout(
        height=320,
        margin=dict(l=10, r=10, t=10, b=70),
        plot_bgcolor="white",
        showlegend=False,
    )
    fig.update_xaxes(title=loc_label_kor,
                     tickfont=dict(size=13), tickangle=-30)
    fig.update_yaxes(title=f"{item_kor} ({unit})", tickfont=dict(size=13))

    st.markdown(
        f'<p class="subsection-title" style="margin:14px 0 0;">'
        f'{region} {item_kor} 현황 ({latest_year}년)</p>',
        unsafe_allow_html=True,
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_half_box(
    work: pd.DataFrame, item: str,
    region: str, item_kor: str, unit: str,
    yh_lo: "tuple[int, str]", yh_hi: "tuple[int, str]",
) -> None:
    """기간 내 (연도, 반기) 별 박스 플롯 (사용자 요청 #4·#5).

    각 박스 = 한 (연도, 반기) 시점의 「관정별 측정값 분포」.
    분석 기간 슬라이더 범위에 포함된 모든 (year, half) 쌍을 시간 순서로 나열.
    상=라이트 그린, 하=다크 그린.
    """
    if "half" not in work.columns or "year" not in work.columns:
        return
    sub = work.dropna(subset=[item, "year", "half"]).copy()
    sub["half"] = sub["half"].astype(str).str.strip()
    sub = sub[sub["half"].isin(["상", "하"])]
    if sub.empty:
        return

    sub["_yint"] = sub["year"].astype("Int64").astype(int)

    # 슬라이더 범위 내 모든 (year, half) 페어
    lo_idx = _yh_idx(*yh_lo)
    hi_idx = _yh_idx(*yh_hi)
    periods: list[tuple[int, str]] = []
    for i in range(lo_idx, hi_idx + 1):
        y = i // 2
        h = "상" if i % 2 == 0 else "하"
        periods.append((y, h))

    std = config.WATER_QUALITY_STANDARDS.get(item, {})
    color_map = {"상": "#9CCC65", "하": "#33691E"}

    fig = go.Figure()
    for y, h in periods:
        gv = sub[(sub["_yint"] == y) & (sub["half"] == h)][item].dropna()
        if gv.empty:
            continue
        c = color_map.get(h, theme.COLOR_ACCENT_BLUE_2)
        fig.add_trace(go.Box(
            y=gv, name=f"{y}-{h}",
            boxpoints="outliers",
            marker=dict(size=4, color=c),
            line=dict(width=1.2, color=c),
            fillcolor=_hex_to_rgba(c, 0.25),
            hovertemplate=(
                f"<b>{y}-{h}</b><br>"
                f"{item_kor}: %{{y:.2f}} {unit}<br>"
                f"관정별 측정값<extra></extra>"
            ),
        ))
    if "max" in std:
        fig.add_hline(
            y=std["max"], line_dash="dash", line_color=theme.COLOR_QUALITY_MAX,
            line_width=1.0, opacity=0.7,
            annotation_text=f"기준 ≤ {std['max']}",
            annotation_font=dict(size=13, color=theme.COLOR_QUALITY_MAX),
        )
    if "min" in std:
        fig.add_hline(
            y=std["min"], line_dash="dash", line_color=theme.COLOR_QUALITY_MAX,
            line_width=1.0, opacity=0.6,
        )
    fig.update_layout(
        height=320,
        margin=dict(l=10, r=10, t=10, b=40),
        plot_bgcolor="white",
        showlegend=False,
    )
    fig.update_xaxes(title=None, tickfont=dict(size=13), tickangle=-30)
    fig.update_yaxes(title=f"{item_kor} ({unit})", tickfont=dict(size=13))

    st.markdown(
        f'<p class="subsection-title" style="margin:14px 0 0;">'
        f'{region} 상·하반기별 {item_kor} 현황 (Box Plot) '
        f'({yh_lo[0]}년 ~ {yh_hi[0]}년)</p>'
        f'<p style="font-size:15px;color:var(--color-text-secondary);margin:0 0 4px;">'
        f'각 박스 = 해당 (연도-반기) 의 관정별 측정값 분포</p>',
        unsafe_allow_html=True,
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_group_timeseries_table(
    work: pd.DataFrame, item: str, loc_col: str, loc_label_kor: str,
    region: str, item_kor: str, unit: str,
) -> None:
    """그룹 × 시기 평균값 표 (사용자 요청 #7).

    구조 (well 5항목 표와 동일 형식):
      - 행: 그룹 (예: 리)
      - 열: 시기(연도-반기) 2단 헤더 (위=연도 colspan=2, 아래=상/하)
      - 값: 그룹×시기의 item 평균
      - 기준 초과 셀 빨강 강조.
    """
    sub_v = work.dropna(subset=["year", "half", item]).copy()
    sub_v["_yint"] = sub_v["year"].astype("Int64").astype(int)
    sub_v["_hstr"] = sub_v["half"].astype(str).str.strip()
    sub_v = sub_v[sub_v["_hstr"].isin(["상", "하"])]
    if sub_v.empty:
        return

    years_present = sorted(sub_v["_yint"].unique().tolist())
    period_cols = [(y, h) for y in years_present for h in ("상", "하")]

    # 그룹 정렬 — 전체 평균 내림차순
    order = (
        sub_v.groupby(loc_col)[item].mean()
             .sort_values(ascending=False).index.tolist()
    )

    # 그룹 × (year, half) 평균
    grp_avg = (
        sub_v.groupby([loc_col, "_yint", "_hstr"])[item]
             .mean().reset_index()
    )
    val_lookup: "dict[tuple[str, int, str], float]" = {
        (r[loc_col], int(r["_yint"]), str(r["_hstr"])): float(r[item])
        for _, r in grp_avg.iterrows()
    }

    std = config.WATER_QUALITY_STANDARDS.get(item, {})
    std_max = std.get("max")
    std_min = std.get("min")

    def _is_exceed(v: float) -> bool:
        if v is None or pd.isna(v):
            return False
        if std_max is not None and v > std_max:
            return True
        if std_min is not None and v < std_min:
            return True
        return False

    css = """
    <style>
    .qty-grp-table-wrap { width:100%; overflow-x:auto; margin: 8px 0 8px; }
    .qty-grp-table {
        border-collapse: collapse;
        font-size: 15px; color: var(--color-text-primary);
        border: 0.5px solid rgba(26,26,24,0.18);
        min-width: 100%;
    }
    .qty-grp-table th, .qty-grp-table td {
        padding: 4px 6px;
        border: 0.5px solid rgba(26,26,24,0.10);
        text-align: center;
        font-variant-numeric: tabular-nums;
        white-space: nowrap;
    }
    .qty-grp-table thead th.year-th {
        background: var(--color-text-info); color: var(--color-bg-primary);
        font-weight: 700; font-size: 16px;
    }
    .qty-grp-table thead th.half-th {
        background: var(--color-bg-info); color: var(--color-text-info);
        font-weight: 600; font-size: 15px;
    }
    .qty-grp-table thead th.item-th {
        background: var(--color-accent-blue-3); color: var(--color-bg-primary);
        font-weight: 700; vertical-align: middle;
        text-align: center;
    }
    .qty-grp-table td.item-cell {
        background: var(--color-bg-secondary);
        color: var(--color-text-info); font-weight: 600;
        text-align: center;
        min-width: 100px;
    }
    .qty-grp-table td.exceed {
        background: #fdecea;
        color: var(--color-accent-darkred); font-weight: 700;
    }
    .qty-grp-table tbody tr:nth-child(even)
        td:not(.item-cell):not(.exceed) {
        background: #fafaf8;
    }
    .qty-grp-table th.year-sep, .qty-grp-table td.year-sep {
        border-left: 2px solid #185fa5 !important;
    }
    </style>
    """

    head1 = [f'<tr><th class="item-th" rowspan="2">{loc_label_kor}</th>']
    for i, y in enumerate(years_present):
        sep = " year-sep" if i > 0 else ""
        head1.append(f'<th class="year-th{sep}" colspan="2">{y}</th>')
    head1.append("</tr>")

    # 사용자 요청 #5: 상 / 하 → 상반기 / 하반기
    head2 = ["<tr>"]
    for i, _y in enumerate(years_present):
        sep = " year-sep" if i > 0 else ""
        head2.append(f'<th class="half-th{sep}">상반기</th>')
        head2.append('<th class="half-th">하반기</th>')
    head2.append("</tr>")

    head = "<thead>" + "".join(head1) + "".join(head2) + "</thead>"

    body_rows = []
    for grp in order:
        # 사용자 요청 #4: 리 셀 중앙정렬 (CSS 의 .item-cell 이 처리)
        cells = [f'<td class="item-cell">{grp}</td>']
        for col_idx, (y, h) in enumerate(period_cols):
            v = val_lookup.get((grp, y, h))
            sep = (h == "상" and col_idx > 0)
            sep_cls = " year-sep" if sep else ""
            if v is None or pd.isna(v):
                cells.append(
                    f'<td class="{sep_cls.strip()}">-</td>' if sep_cls
                    else '<td>-</td>'
                )
            else:
                text = _fmt_item(v, item)
                exc = _is_exceed(v)
                cls = ("exceed" + sep_cls).strip() if exc else sep_cls.strip()
                if cls:
                    cells.append(f'<td class="{cls}">{text}</td>')
                else:
                    cells.append(f'<td>{text}</td>')
        body_rows.append("<tr>" + "".join(cells) + "</tr>")

    table = (
        css
        + '<div class="qty-grp-table-wrap">'
        + '<table class="qty-grp-table">'
        + head
        + "<tbody>" + "".join(body_rows) + "</tbody>"
        + "</table></div>"
    )

    st.markdown(
        f'<p class="subsection-title" style="margin:14px 0 0;">'
        f'{region} {loc_label_kor}별 {item_kor} 시계열 표 '
        f'<span style="font-size:15px;font-weight:400;color:var(--color-text-secondary);">'
        f'(셀 값 = 해당 {loc_label_kor}·시기 평균)</span></p>',
        unsafe_allow_html=True,
    )
    st.markdown(table, unsafe_allow_html=True)
