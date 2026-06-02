"""행정 구역·리·동 Dual-Zone 월별 12장 small multiples (그림 27).

fig24 (`renderer.render`) 와 동일한 dual-zone 패킹을 12개 월 패널로 펼친다.

  • 레이아웃은 1번만 계산 → 12 패널이 같은 좌표를 공유
  • 색은 ``{Jan..Dec}_pw`` 컬럼 (관정당 월 이용량 ㎥/공·월)
  • subplot_titles 에 ASOS 평년 월강수량 표기 (옵션)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.colors import sample_colorscale
from plotly.subplots import make_subplots

from src.dashboard import theme

from .._dual_zone_common.color import (
    DAILY_USAGE_COLORSCALE, DAILY_USAGE_VMAX_MONTHLY, DAILY_USAGE_VMIN,
)
from .constants import (
    ADMIN_AGRI_HA, JEJU_CLUSTERS, MONTHS_ABBR, MONTHS_KR,
    NO_WELL_FILL, NO_WELL_PATTERN, SEOG_CLUSTERS,
)
from .data import _normalize_master_admin, aggregate_units, load_asos_monthly
from .layout import UnitLayout, build_unit_layout


# ──────────────────────────────────────────────────────────────────
#  공개 API
# ──────────────────────────────────────────────────────────────────
def render_monthly(master: pd.DataFrame, usage: pd.DataFrame,
                   units_df: pd.DataFrame | None = None, *,
                   asos_monthly: pd.DataFrame | None = None,
                   period_label: str | None = None,
                   height: int = 1200,
                   color_vmin: "float | None" = None,
                   color_vmax: "float | None" = None,
                   active_permits: "set[str] | None" = None,
                   ) -> go.Figure:
    """월별 12장 dual-zone — 1번 layout 계산 후 12 panel 에 재사용.

    Parameters
    ----------
    master, usage : DataFrame
        ag_well_loader 의 master / usage_long. 내부에서 cluster·unit 정규화.
    units_df : DataFrame, optional
        미리 ``aggregate_units`` 결과를 가지고 있으면 재사용 (성능).
    asos_monthly : DataFrame, optional
        ASOS 월강수 (station × Jan..Dec). 없으면 ``load_asos_monthly`` 호출.
    period_label : str, optional
        제목용 기간 라벨 — 현재 figure 자체에는 미반영 (Streamlit 측 caption).
    height : int
        figure 전체 높이. 4 row × 3 col 이라 1200 정도 권장.
    """
    # 0) 데이터 준비 (master·usage 정규화)
    if "cluster" not in master.columns or "unit" not in master.columns:
        master = _normalize_master_admin(master)
    if "cluster" not in usage.columns or "unit" not in usage.columns:
        usage = usage.merge(
            master[["permit_no", "cluster", "unit"]],
            on="permit_no", how="left",
        )
    if units_df is None:
        units_df = aggregate_units(master, usage, active_permits=active_permits)

    # 1) 레이아웃 1번만 (band_total_h=9.0, fig24 와 동일)
    layout: UnitLayout = build_unit_layout(units_df, band_total_h=9.0)

    # 2) 색 스케일 — 사용자 정책 (2026-05-22): per_well_daily × 30 절대 도메인
    #    강제 (=DAILY_USAGE_VMAX_MONTHLY = 48000 ㎥/공·월). 일/월 단위 두
    #    시각화 (8-2 탭 map grid 와 fig27) 가 동일 색 계조 공유 → 같은
    #    리·동이 두 차트에서 동일 색으로 표시. 외부 override 우선.
    computed_vmin = DAILY_USAGE_VMIN
    computed_vmax = DAILY_USAGE_VMAX_MONTHLY
    if color_vmin is not None and color_vmax is not None:
        vmin, vmax = float(color_vmin), float(color_vmax)
    else:
        vmin, vmax = computed_vmin, computed_vmax

    # 3) ASOS 월별 강수 (옵션)
    if asos_monthly is None:
        try:
            asos_monthly, _ = load_asos_monthly()
        except Exception:
            asos_monthly = pd.DataFrame()

    if asos_monthly is not None and not asos_monthly.empty:
        rain_per_month = asos_monthly.mean(axis=0)  # 4개 관측소 평균
    else:
        rain_per_month = pd.Series(0.0, index=list(MONTHS_ABBR))

    # 4) subplot titles — "1월  강수 65mm"
    titles: list[str] = []
    for i, m in enumerate(MONTHS_ABBR):
        rmm = float(rain_per_month.get(m, 0.0))
        rain_str = f"강수 {rmm:.0f}mm" if rmm > 0 else ""
        titles.append(f"{MONTHS_KR[i]}  {rain_str}".strip())

    fig = make_subplots(
        rows=4, cols=3,
        subplot_titles=titles,
        horizontal_spacing=0.02,
        vertical_spacing=0.06,
    )

    # 5) 12 패널 — 같은 layout, {month}_pw 컬럼만 바꿔가며 색칠
    for mi, mname in enumerate(MONTHS_ABBR):
        r, c = mi // 3 + 1, mi % 3 + 1
        _add_panel_traces(fig, layout, units_df, mname,
                          vmin, vmax, DAILY_USAGE_COLORSCALE, row=r, col=c)
        fig.update_xaxes(visible=False, fixedrange=True,
                         range=[layout.x_min - 1, layout.x_max + 1],
                         row=r, col=c)
        fig.update_yaxes(visible=False, fixedrange=True,
                         range=[layout.s_y0 - 1.0, layout.j_y1 + 1.0],
                         row=r, col=c)

    # 6) 공유 colorbar — dummy trace
    fig.add_trace(go.Scatter(
        x=[None], y=[None], mode="markers",
        marker=dict(
            colorscale=DAILY_USAGE_COLORSCALE, cmin=vmin, cmax=vmax, color=[vmin],
            size=0.0001,
            colorbar=dict(
                title=dict(text="관정당 월 이용량 (㎥/공·월)", side="right"),
                thickness=14, len=0.85, x=1.02, y=0.5,
            ),
        ),
        hoverinfo="skip", showlegend=False,
    ))

    # 7) 전체 layout
    fig.update_layout(
        title=dict(text=""),
        height=height,
        plot_bgcolor="white",
        paper_bgcolor="white",
        margin=dict(l=10, r=140, t=40, b=20),
        hoverlabel=dict(bgcolor="white", font_size=14,
                        bordercolor="rgba(26,26,24,0.30)"),
        font=dict(family="-apple-system, BlinkMacSystemFont, 'Segoe UI', "
                         "Roboto, sans-serif", color=theme.COLOR_TEXT_PRIMARY),
    )

    # subplot_titles 폰트 통일
    for ann in fig.layout.annotations:
        ann.font = dict(size=14, color=theme.COLOR_TEXT_PRIMARY)

    return fig


# ──────────────────────────────────────────────────────────────────
#  내부: 1개 월 패널 traces
# ──────────────────────────────────────────────────────────────────
_MONTH_KR_BY_ABBR = dict(zip(MONTHS_ABBR, MONTHS_KR))
# L6 (2026-05-27): 월값→일값 환산에 쓸 '해당 월의 실제 일수'.
#   기존엔 모든 달을 고정 30 으로 나눠 28~31일 달에서 최대 ~7% 오차가 났음.
#   다년 평균이라 2월은 평년 기준 28 사용(윤년 보정은 표시 오차 영향 미미).
_MONTH_DAYS_BY_ABBR = dict(zip(
    MONTHS_ABBR, [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
))


def _add_panel_traces(fig: go.Figure, layout: UnitLayout,
                      units_df: pd.DataFrame, mname: str,
                      vmin: float, vmax: float, colorscale: str,
                      *, row: int, col: int) -> None:
    """1 개 월 패널의 traces 추가 — 박스 색은 ``{mname}_pw`` 컬럼."""
    pw_col = f"{mname}_pw"
    v_by_idx = units_df[pw_col].to_dict()
    n_by_idx = units_df["n"].to_dict() if "n" in units_df.columns else {}
    area_by_idx = (units_df["est_area_ha"].to_dict()
                   if "est_area_ha" in units_df.columns else {})
    span = vmax - vmin
    month_kr = _MONTH_KR_BY_ABBR.get(mname, mname)

    # 5-1) unit 박스 — 각 unit 별로 fill='toself' + 면 hover.
    #     0공 unit (n==0): 회색·빗금. v 는 NaN 이라 비교 회피.
    for slot in layout.unit_slots:
        raw_v = v_by_idx.get(slot.idx, 0.0)
        v = float(raw_v) if raw_v is not None else float("nan")
        n_val = int(n_by_idx.get(slot.idx, 0))
        area_val = float(area_by_idx.get(slot.idx, 0.0))
        is_no_well = (n_val == 0)
        fillpattern = None
        # 사용자 요청 (2026-05-22): hover 형식을 8-2 탭 map grid 와 통일.
        #   - 라벨: slot.unit (예: "위미리") — cluster·읍·면 prefix 제거
        #   - 관정수: "{n}공" — "관정" 단어 제거
        #   - 값: 일 단위 환산 (월값/30) "{v_day:.1f} ㎥/공·일" — 8-2 와 정합
        # plotly 5.22 의 `hoveron='fills'` + polygon trace 조합은 hovertemplate
        # 의 multi-line `<br>` 을 trace.name 단일 라벨로 축약하는 동작이 있음
        # (fill-hover 경로). 따라서 hovertemplate 대신 text + hoverinfo='text'
        # 로 fill 면 위에서도 multi-line 표시 보장 — `<extra></extra>` 불필요.
        _days = _MONTH_DAYS_BY_ABBR.get(mname, 30)
        v_day = (v / _days) if (not np.isnan(v) and v > 0) else 0.0
        if is_no_well:
            color = NO_WELL_FILL
            fillpattern = NO_WELL_PATTERN
            hover = (
                f"<b>{slot.unit}</b><br>"
                f"0공<br>"
                f"0.0 ㎥/공·일"
            )
        elif np.isnan(v) or v <= 0:
            color = "rgba(220,220,220,0.4)"
            hover = (
                f"<b>{slot.unit}</b><br>"
                f"{n_val:,}공<br>"
                f"0.0 ㎥/공·일"
            )
        else:
            t = (v - vmin) / span if span > 0 else 0.5
            t = max(0.0, min(1.0, t))
            color = sample_colorscale(colorscale, [t])[0]
            hover = (
                f"<b>{slot.unit}</b><br>"
                f"{n_val:,}공<br>"
                f"{v_day:,.1f} ㎥/공·일"
            )
        trace_kwargs: dict = dict(
            x=[slot.x, slot.x + slot.width, slot.x + slot.width,
               slot.x, slot.x],
            y=[slot.y, slot.y, slot.y + slot.height,
               slot.y + slot.height, slot.y],
            mode="lines", fill="toself",
            fillcolor=color,
            line=dict(color="rgba(20,20,20,0.5)", width=0.3),
            # plotly 5.22 의 hoveron='fills' + Scatter polygon 조합은
            # hovertemplate/text/hoverinfo 를 전부 무시하고 trace.name 만
            # 단일 라벨로 표시하는 fill-hover 경로 동작이 있음. 따라서
            # name 자체에 multi-line hover 내용을 박아 강제 표출.
            # `<br>` 은 trace.name 에서도 plotly hover label 의 줄바꿈으로
            # 정상 렌더됨.
            text=[hover] * 5,
            hoverinfo="text",
            hoveron="fills",
            customdata=[[slot.cluster, slot.unit, slot.idx, mname]] * 5,
            name=hover,
            showlegend=False,
        )
        if fillpattern is not None:
            trace_kwargs["fillpattern"] = fillpattern
        fig.add_trace(go.Scatter(**trace_kwargs), row=row, col=col)

    # 5-2) 클러스터 외곽선 — 12 cluster_slot
    for cs in layout.cluster_slots:
        fig.add_trace(go.Scatter(
            x=[cs.x, cs.x + cs.width, cs.x + cs.width, cs.x, cs.x],
            y=[cs.y, cs.y, cs.y + cs.height, cs.y + cs.height, cs.y],
            mode="lines",
            line=dict(color=theme.COLOR_ACCENT_NAVY, width=1.2),
            hoverinfo="skip", showlegend=False,
            name="",
        ), row=row, col=col)


__all__ = ["render_monthly"]
