# ==============================================================================
#  파일명: src/dashboard/tabs/_tab12_well_detail.py
#  6 이용량 분석 탭 - 관정 상세 + 연도별 취수허가량 표 + 월별 이용량 표
#
#  Source 분리: tab12_ag_usage.py 2311줄 -> 그룹별 분리 4단계 (2026-05-09).
#    - _render_well_detail         : 관정 상세
#    - _render_yearly_permit_table : 연도별 취수허가량 표
#    - _render_well_monthly_table  : 관정 월별 이용량 표
#
#  외부 사용처: tab12_ag_usage.py 내부 전용.
# ==============================================================================
from __future__ import annotations

import calendar
import re

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import config
from src.analysis import ag_well_loader, ag_well_metrics, anomaly_detection
from src.dashboard import ag_well_helpers, theme
from src.dashboard.tabs._tab12_helpers import (
    _PERMIT_PALETTE,
    _yearly_permit_for_well,
    _yr_label,
)
from src.dashboard.tabs._tab12_aws import (
    _select_aws_for_region,
    _render_aws_rainfall,
)


def _render_well_detail(
    permit_no: str,
    df_master_f: pd.DataFrame,
) -> None:
    """단일 관정 상세 — 월별 표 + 연도별 허가량 표 + AWS dual-axis 그래프.

    헤더(관정명·주소·선택 해제·검색)는 _render_well_selection_bar 가 담당.
    슬라이더 연도와 무관하게 그 관정의 자료가 존재하는 전체 기간을 표시.
    """
    info = ag_well_loader.get_well_info(permit_no)
    well_id = (info.get("well_id") if info else permit_no) or permit_no

    # ── 단일 관정의 가용 자료 전체 로드 (슬라이더 무시)
    df_usage_all = ag_well_loader.load_usage_long()
    sub = df_usage_all[df_usage_all["permit_no"] == permit_no].copy()

    if sub.empty:
        st.caption("선택된 관정의 이용량 자료가 없습니다.")
        return

    well_yr_range = (int(sub["year"].min()), int(sub["year"].max()))

    # ── 월별 이용량 표 (year × month pivot)
    _render_well_monthly_table(sub)

    # ── 연도별 취수허가량 변화표 (보유한 모든 연도 · 최신값=흰색, 다른 값=같은 값끼리 같은 톤)
    _render_yearly_permit_table(permit_no, sub)

    # ── Dual-axis 그래프: AWS 강수량 + 해당 관정 월 이용량
    aws_name = _select_aws_for_region(df_master_f)
    aws_label = aws_name or "(매핑 AWS 없음)"
    yr_label = _yr_label(well_yr_range)
    st.markdown(
        f'<div class="subsection-title" style="color:var(--color-text-info);'
        f'margin-top:10px;">{well_id} 월별 강수량 · 이용량 비교 '
        f'(적용 AWS: <span style="color:var(--color-accent-darkred);">{aws_label}</span>) '
        f'({yr_label})</div>',
        unsafe_allow_html=True,
    )
    # 단일 관정 — 우측 Y축 0~2000 고정 (8 grid, 250 단위), 강수량과 보조선 정렬.
    # 연도별 「취수허가량 ÷ 30(㎥/일)」을 점선으로 함께 표시 → 일일 허가량 한도선.
    daily_permit_by_year = {
        y: v / 30.0 for y, v in _yearly_permit_for_well(permit_no, sub).items()
    }
    _render_aws_rainfall(
        aws_name, well_yr_range, sub,
        usage_y_max=2000,
        daily_permit_by_year=daily_permit_by_year,
    )


def _render_yearly_permit_table(permit_no: str, sub: pd.DataFrame) -> None:
    """관정의 연도별 취수허가량(permit_m3m)을 2행 표로 렌더.

    상단 행: 연도, 하단 행: 취수허가량(㎥/월).
    표 폭은 컨테이너 100% 로 월별 이용량 표와 동일 길이.

    색 규칙:
      - 가장 최근 연도의 값(=현재 기준) → 흰색 배경
      - 그와 다른 값은 unique 값별로 pastel tone 부여, 같은 값은 같은 색
      - 직전 연도 대비 값이 바뀐 해는 ▲ 마크
    """
    yr_to_pm = _yearly_permit_for_well(permit_no, sub)

    if not yr_to_pm:
        st.caption("연도별 취수허가량 자료가 없습니다.")
        return

    # 정수 반올림으로 정규화 (소수 노이즈 흡수)
    yr_to_pm_int: dict[int, int] = {y: int(round(v)) for y, v in yr_to_pm.items()}

    sorted_years = sorted(yr_to_pm_int.keys())
    latest_val = yr_to_pm_int[sorted_years[-1]]

    # 색 매핑 — 최신값=흰색, 그 외 unique 값은 팔레트 순환
    other_unique = sorted({v for v in yr_to_pm_int.values() if v != latest_val})
    color_map: dict[int, str] = {latest_val: "#ffffff"}
    for i, v in enumerate(other_unique):
        color_map[v] = _PERMIT_PALETTE[i % len(_PERMIT_PALETTE)]

    # 셀 빌드
    year_cells: list[str] = []
    permit_cells: list[str] = []
    prev_v: int | None = None
    for y in sorted_years:
        v = yr_to_pm_int[y]
        bg = color_map[v]
        change_mark = ""
        if prev_v is not None and v != prev_v:
            change_mark = ' <span style="color:var(--color-accent-darkred);font-weight:700;">▲</span>'
        year_cells.append(f'<td>{y}</td>')
        permit_cells.append(
            f'<td style="background:{bg};">{v:,}{change_mark}</td>'
        )
        prev_v = v

    table_html = (
        '<table class="permit-history">'
        '<tbody>'
        f'<tr class="row-year"><th>연도</th>{"".join(year_cells)}</tr>'
        f'<tr class="row-permit"><th>취수허가량 (㎥/월)</th>{"".join(permit_cells)}</tr>'
        '</tbody></table>'
    )

    css = """
    <style>
    .permit-history {
        width: 100%;
        border-collapse: collapse;
        font-size: 15px; color: var(--color-text-primary);
        border: 0.5px solid rgba(26,26,24,0.18);
        margin: 6px 0 8px;
        table-layout: fixed;
    }
    .permit-history th, .permit-history td {
        padding: 5px 4px;
        border: 0.5px solid rgba(26,26,24,0.10);
        text-align: center;
        font-variant-numeric: tabular-nums;
        white-space: nowrap;
    }
    .permit-history th {
        background: var(--color-text-info); color: var(--color-bg-primary);
        font-weight: 600;
    }
    .permit-history tr.row-year td {
        background: var(--color-bg-info);
        color: var(--color-text-info);
        font-weight: 700;
    }
    .permit-history tr.row-permit td {
        font-weight: 600;
    }
    </style>
    """
    st.markdown(css + table_html, unsafe_allow_html=True)


def _render_well_monthly_table(sub: pd.DataFrame) -> None:
    """단일 관정의 연도×월 표 — HTML 직접 렌더.

    각 연도마다 두 행:
      ① 월 합계 (㎥)         — 그달의 이용량 총량
      ② 일 평균 (㎥/일)      — 월 합계 ÷ 그달의 실제 일수 (윤년 자동 처리)
    우측 끝 「연 합계」 컬럼은 12개월 합계 / 365(366) 기준.

    모든 셀 중앙정렬 + 천단위 콤마.
    """
    if sub.empty:
        st.caption("선택된 관정의 이용량 자료가 없습니다.")
        return

    pv = sub.pivot_table(
        index="year", columns="month", values="volume_m3", aggfunc="sum",
    )
    if pv.empty:
        st.caption("선택된 관정의 월별 이용량 자료가 없습니다.")
        return

    # 1~12월 모두 컬럼 보장
    for m in range(1, 13):
        if m not in pv.columns:
            pv[m] = pd.NA
    pv = pv[sorted([c for c in pv.columns if isinstance(c, (int, float))])]

    # ── 일평균 셀의 분위수 기반 배경색 (heat-map 스타일, 6 단계)
    #   분석기간의 「모든 (연도 × 1~12월)」 일평균 값을 한 풀에 모아
    #   P10 / P25 / P50 / P75 / P90 산출 → 6 구간 색상.
    #   동일 풀 기준이라 모든 연도의 셀이 같은 기준으로 색상 결정.
    daily_pool: list[float] = []
    for year in pv.index:
        for m in range(1, 13):
            v = pv.loc[year, m]
            if pd.notna(v):
                days = calendar.monthrange(int(year), m)[1]
                daily_pool.append(float(v) / days)

    p10 = p25 = p50 = p75 = p90 = mean_val = None
    if len(daily_pool) >= 6:
        s = pd.Series(daily_pool)
        p10 = float(s.quantile(0.10))
        p25 = float(s.quantile(0.25))
        p50 = float(s.quantile(0.50))
        p75 = float(s.quantile(0.75))
        p90 = float(s.quantile(0.90))
        mean_val = float(s.mean())

    # ── 취수허가량 라벨 — 가장 최근 연도의 permit_m3m 을 단일 기준으로 사용.
    #   설계: 연도별로 허가량이 변경되었더라도 「현재 기준」으로 일관되게 색상 판정.
    #   데이터 소스: usage + master_yearly union (가용한 가장 최근 연도 채택).
    latest_year_permit: int | None = None
    latest_permit_value: float | None = None
    permit_label = "-"
    permit_no_in_sub: str | None = None
    if "permit_no" in sub.columns:
        nz = sub["permit_no"].dropna()
        if not nz.empty:
            permit_no_in_sub = str(nz.iloc[0])
    if permit_no_in_sub:
        yr_to_pm = _yearly_permit_for_well(permit_no_in_sub, sub)
        if yr_to_pm:
            latest_year_permit = max(yr_to_pm.keys())
            latest_permit_value = float(yr_to_pm[latest_year_permit])
            permit_label = (
                f"{latest_permit_value:,.0f} ㎥/월 "
                f'<span style="color:#7a7a76;font-weight:400;">'
                f"(기준년도: {latest_year_permit}년)</span>"
            )

    # ── Legend (표 위) — 2 섹션 수평 배치
    #   ① 일 평균 이용량 색상 기준 (6분위)
    #   ② 월 이용량 색상 기준 (취수허가량 초과 → 빨강)
    if p10 is not None:
        n_years = len(pv.index)
        legend_html = f"""
        <div style="margin:4px 0 6px;padding:8px 12px;
                    background:var(--color-bg-secondary);border-radius:6px;
                    border-left:3px solid var(--color-text-info);
                    font-size:15px;color:var(--color-text-primary);">
          <div style="display:flex;gap:20px;flex-wrap:wrap;align-items:flex-start;">

            <!-- 섹션 ① 일 평균 이용량 -->
            <div style="flex:2 1 600px;min-width:480px;">
              <div style="margin-bottom:5px;color:var(--color-text-secondary);">
                <b style="color:var(--color-text-info);">일 평균 이용량 색상 기준</b>
                · {n_years}년 전체 6분위 (모든 연도 동일):
                평균 <b>{mean_val:,.0f}</b> ·
                P10 <b>{p10:,.0f}</b> ·
                P25 <b>{p25:,.0f}</b> ·
                중위 <b>{p50:,.0f}</b> ·
                P75 <b>{p75:,.0f}</b> ·
                P90 <b>{p90:,.0f}</b> ㎥/일
              </div>
              <div style="display:flex;gap:3px;align-items:center;flex-wrap:wrap;">
                <span style="background:#C8E6C9;padding:2px 7px;border-radius:3px;">하위 10% (≤ {p10:,.0f})</span>
                <span style="background:#DCEDC8;padding:2px 7px;border-radius:3px;">~ {p25:,.0f}</span>
                <span style="background:#FFF59D;padding:2px 7px;border-radius:3px;">~ {p50:,.0f}</span>
                <span style="background:#FFE082;padding:2px 7px;border-radius:3px;">~ {p75:,.0f}</span>
                <span style="background:#FFAB91;padding:2px 7px;border-radius:3px;">~ {p90:,.0f}</span>
                <span style="background:#EF9A9A;padding:2px 7px;border-radius:3px;font-weight:700;">상위 10% (> {p90:,.0f})</span>
              </div>
            </div>

            <!-- 섹션 ② 월 이용량 -->
            <!-- 사용자 요청 (2026-05-16): "(기준년도: 2025년)" 텍스트가
                 240px 폭에서 줄바꿈 발생 → 320px 로 확장하여 한 줄 유지. -->
            <div style="flex:1 1 320px;min-width:320px;
                        border-left:1px dashed rgba(0,0,0,0.15);padding-left:14px;">
              <div style="margin-bottom:5px;color:var(--color-text-secondary);">
                <b style="color:var(--color-text-info);">월 이용량 색상 기준</b>
                · 취수허가량 <b>{permit_label}</b>
              </div>
              <div style="display:flex;gap:4px;align-items:center;flex-wrap:wrap;">
                <span style="padding:2px 7px;border-radius:3px;border:0.5px solid rgba(0,0,0,0.18);background:var(--color-bg-primary);">정상</span>
                <span style="background:#F4978E;padding:2px 7px;border-radius:3px;font-weight:700;">취수허가량 초과</span>
              </div>
            </div>

          </div>
        </div>
        """
        # Streamlit markdown 의 「indented code block」 인식(4+ spaces) 회피.
        # 멀티라인 f-string 의 leading whitespace 가 그대로 들어가면 HTML 이
        # raw 텍스트로 렌더되므로 모든 공백을 single space 로 압축.
        legend_html = re.sub(r"\s+", " ", legend_html).strip()
        st.markdown(legend_html, unsafe_allow_html=True)

    # 6단계 색상 — 옅은 녹색 → 연두 → 옅은 노랑 → 진노랑 → 연주황 → 빨강.
    # 상위 10% (P90 초과) 는 빨강 + 굵게로 한눈에 식별.
    _common = "color:var(--color-text-primary);font-style:normal;"
    def _heat_style(v: float) -> str:
        if p10 is None or v is None or pd.isna(v):
            return ""
        if v > p90:
            return f"background:#EF9A9A;font-weight:700;{_common}"  # 상위 10%
        if v > p75:
            return f"background:#FFAB91;{_common}"                  # P75 ~ P90
        if v > p50:
            return f"background:#FFE082;{_common}"                  # P50 ~ P75
        if v > p25:
            return f"background:#FFF59D;{_common}"                  # P25 ~ P50
        if v > p10:
            return f"background:#DCEDC8;{_common}"                  # P10 ~ P25
        return f"background:#C8E6C9;{_common}"                      # 하위 10%

    css = """
    <style>
    .well-monthly {
        width: 100%; border-collapse: collapse;
        font-size: 15px; color: var(--color-text-primary);
        border: 0.5px solid rgba(26,26,24,0.18);
        margin: 6px 0 8px;
    }
    .well-monthly th, .well-monthly td {
        padding: 6px 4px;
        border: 0.5px solid rgba(26,26,24,0.10);
        text-align: center;
        font-variant-numeric: tabular-nums;
        white-space: nowrap;
    }
    .well-monthly thead th {
        background: var(--color-text-info); color: var(--color-bg-primary);
        font-weight: 600;
    }
    /* 연도 컬럼 (rowspan=2 로 두 행 묶음) — 짙은 파랑 + 흰 글자 */
    .well-monthly td.year-col {
        background: var(--color-text-info); color: var(--color-bg-primary);
        font-weight: 700; font-size: 16px;
        vertical-align: middle;
    }
    /* 구분 컬럼 (월 이용량 / 일 평균) */
    .well-monthly td.kind-col {
        background: var(--color-bg-info); color: var(--color-text-info);
        font-weight: 600;
    }
    /* 일 평균 행 — 옅은 배경 (heat-map 셀은 inline style 이 우선) */
    .well-monthly tbody tr.daily-row td {
        background: #fafaf8;
        color: var(--color-text-secondary);
        font-style: italic;
    }
    .well-monthly tbody tr.daily-row td.kind-col {
        background: #d7e6f5;
        color: var(--color-text-info);
        font-style: normal;
    }
    .well-monthly td.total-col {
        background: #d7e6f5; font-weight: 700; color: var(--color-text-info);
        font-style: normal;
    }
    /* 취수허가량 초과 — 빨강 강조 */
    .well-monthly td.over-permit {
        background: #F4978E !important;
        color: var(--color-text-primary); font-weight: 700;
        font-style: normal;
    }
    </style>
    """

    def _fmt(v) -> str:
        if v is None or pd.isna(v):
            return "-"
        try:
            # 사용자 요청 (2026-05-16): 0.5 단위 반올림 (`.0`/`.5` 노출) →
            # 정수 반올림. 월 이용량 / 일평균 / 연 합계 / 연 일평균 셀 모두 정수 표시.
            return f"{int(round(float(v))):,}"
        except (TypeError, ValueError):
            return "-"

    # ── 취수허가량 초과 판정 — 연도별 변경과 무관하게 「최근 기준값」하나로 비교.
    def _is_over_permit(yr: int, mo: int, vol: float) -> bool:
        if latest_permit_value is None or latest_permit_value <= 0:
            return False
        return vol > latest_permit_value

    body_rows = []
    for year, row_data in pv.iterrows():
        yr = int(year)
        # 연 합계 산출 (NaN 제외)
        year_total = float(row_data.sum(skipna=True))
        year_days = 366 if calendar.isleap(yr) else 365

        # ── ① 월 이용량 행 — 연도 셀은 rowspan=2 로 다음 행과 묶음
        cells = [
            f'<td class="year-col" rowspan="2">{yr}</td>',
            '<td class="kind-col">월 이용량 (㎥)</td>',
        ]
        for m in range(1, 13):
            v = row_data[m]
            if pd.isna(v):
                cells.append('<td>-</td>')
            else:
                if _is_over_permit(yr, m, float(v)):
                    cells.append(
                        f'<td class="over-permit">{_fmt(v)}</td>'
                    )
                else:
                    cells.append(f'<td>{_fmt(v)}</td>')
        cells.append(f'<td class="total-col">{_fmt(year_total)}</td>')
        body_rows.append('<tr class="total-row">' + "".join(cells) + "</tr>")

        # ── ② 일 평균 이용량 행 — heat-map 색상 (분위수 기반)
        cells = ['<td class="kind-col">일 평균 이용량 (㎥/일)</td>']
        for m in range(1, 13):
            v = row_data[m]
            if pd.isna(v):
                cells.append('<td>-</td>')
            else:
                days = calendar.monthrange(yr, m)[1]
                daily = float(v) / days if days else 0
                style = _heat_style(daily)
                style_attr = f' style="{style}"' if style else ""
                cells.append(f'<td{style_attr}>{_fmt(daily)}</td>')
        # 연 일평균 = 연 합계 / 365(366)
        if year_total > 0:
            cells.append(
                f'<td class="total-col">{_fmt(year_total / year_days)}</td>'
            )
        else:
            cells.append('<td class="total-col">-</td>')
        body_rows.append('<tr class="daily-row">' + "".join(cells) + "</tr>")

    headers = (
        "<thead><tr>"
        '<th>연도</th>'
        '<th>구분</th>'
        + "".join(f"<th>{m}월</th>" for m in range(1, 13))
        + '<th>연 합계</th>'
        + "</tr></thead>"
    )

    html = (
        css
        + '<table class="well-monthly">'
        + headers
        + "<tbody>" + "".join(body_rows) + "</tbody>"
        + "</table>"
    )
    st.markdown(html, unsafe_allow_html=True)


