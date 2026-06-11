"""리·동 Dual-Zone Plotly Figure 빌더 (fig24·fig25·fig26 통합).

설계:
  • 리·동 박스 = go.Scatter (mode='lines', fill='toself') — 면 전체가 호버 가능
  • 각 박스 trace 의 customdata = [[cluster, unit, idx]] * 5 → on_select 로 식별
  • 클러스터 외곽선 = 별도 trace (fill 없음, 굵은 청색 선)
  • 텍스트는 별도 mode='text' trace 들 (큰 박스만 3줄 — w*h 임계값 분기)
  • show_meta_label=True 면 클러스터 외곽 위에 4줄 메타 라벨 (fig26 모드)
  • selected_unit_idx 로 강조 박스(굵은 테두리) 지정
  • 컬러바는 데이터 없는 더미 marker scatter
  • render_compare(): 좌(전체) · 우(200m이하) 클러스터 박스 비교 (fig25)
"""
from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from .._dual_zone_common.color import (
    DAILY_USAGE_COLORSCALE,
    norm_t,
    short_name,
    slot_color,
    vmin_vmax,
)
from ..admin_dual_zone.data import aggregate_clusters
from .constants import (
    ADMIN_AGRI_HA,
    CLUSTER_ASOS,
    NO_WELL_FILL,
    NO_WELL_PATTERN,
)
from .data import _normalize_master_admin, admin_below200_ha, aggregate_units
from .layout import (
    ClusterSlot,
    UnitLayout,
    UnitSlot,
    build_cluster_only_layout,
    build_unit_layout,
)
from .metrics import MetricSpec, RI_METRICS
from src.dashboard import theme


# ──────────────────────────────────────────────────────────────────
#  내부 유틸 — 색상화·정규화는 _dual_zone_common.color 에서 import
#  (분석팀 권고 2026-05-09, 1순위 DRY 통합 — admin_dual_zone 과 공용)
# ──────────────────────────────────────────────────────────────────


# ──────────────────────────────────────────────────────────────────
#  공개 API
# ──────────────────────────────────────────────────────────────────
def render_ri(master: pd.DataFrame, usage: pd.DataFrame,
              units_df: pd.DataFrame | None = None, *,
              metric_key: str = "per_well_annual",
              period_label: str | None = None,
              asos_annual: pd.Series | None = None,
              selected_unit_idx: int | None = None,
              show_meta_label: bool = False,
              height: int = 720,
              color_vmin: "float | None" = None,
              color_vmax: "float | None" = None,
              active_permits: "set[str] | None" = None,
              ) -> go.Figure:
    """리·동 Dual-Zone Plotly Figure 생성.

    Parameters
    ----------
    master, usage : DataFrame
        ag_well_loader 의 원본 또는 cluster·unit 부여본.
    units_df : DataFrame | None
        사전 계산된 aggregate_units 결과. None 이면 내부에서 호출.
    metric_key : str
        RI_METRICS 의 키 (기본: per_well_annual = fig24/26 색).
    period_label : str | None
        "2024년" 등 — period_aware 메트릭의 컬러바 prefix.
    asos_annual : pd.Series | None
        관측소별 연평균 강수 mm — show_meta_label 시 4번째 줄에 표시.
    selected_unit_idx : int | None
        강조할 unit 의 units_df.index (클릭 선택용).
    show_meta_label : bool
        True 이면 클러스터 외곽 위에 4줄 메타 라벨 (fig26 모드),
        False 이면 1줄 라벨 (이름만).
    height : int
        Plotly Figure 높이 (px).
    """
    # ── 0. 데이터 준비 ─────────────────────────────────────────────
    if "cluster" not in master.columns or "unit" not in master.columns:
        master = _normalize_master_admin(master)
    if "cluster" not in usage.columns or "unit" not in usage.columns:
        usage = usage.merge(
            master[["permit_no", "cluster", "unit"]],
            on="permit_no", how="left",
        )
    if units_df is None:
        units_df = aggregate_units(master, usage, active_permits=active_permits)

    if metric_key not in RI_METRICS:
        raise KeyError(
            f"unknown metric: {metric_key} (available: {list(RI_METRICS)})"
        )
    metric: MetricSpec = RI_METRICS[metric_key]
    if metric.column not in units_df.columns:
        raise KeyError(
            f"metric column '{metric.column}' not in units_df: "
            f"{list(units_df.columns)}"
        )

    layout = build_unit_layout(units_df, band_total_h=9.0)

    # idx → row 빠른 조회용
    units_by_idx = units_df.set_index(units_df.index)

    # ── 1. 색 계산 (vmin/vmax + 클립) ─────────────────────────────
    #     0공 unit (n==0, MANUAL_NO_WELL_UNITS) 은 회색·빗금으로 사후 처리.
    #     vmin/vmax 산정에서 NaN 자동 제외 — `_vmin_vmax` 가 처리.
    raw_values = [float(units_by_idx.loc[s.idx, metric.column])
                  if s.idx in units_by_idx.index else np.nan
                  for s in layout.unit_slots]
    is_no_well_list: list[bool] = []
    for s in layout.unit_slots:
        if s.idx in units_by_idx.index:
            is_no_well_list.append(int(units_by_idx.loc[s.idx, "n"]) == 0)
        else:
            is_no_well_list.append(False)
    computed_vmin, computed_vmax = vmin_vmax(raw_values, metric.pct_clip)
    # 우선순위: 외부 주입 > metric.absolute_* > computed (pct_clip 분위수).
    eff_vmin = color_vmin if color_vmin is not None else metric.absolute_vmin
    eff_vmax = color_vmax if color_vmax is not None else metric.absolute_vmax
    if eff_vmin is not None and eff_vmax is not None:
        vmin, vmax = float(eff_vmin), float(eff_vmax)
    else:
        vmin, vmax = computed_vmin, computed_vmax
    colors: list[str] = []
    for v, is_nw in zip(raw_values, is_no_well_list):
        if is_nw:
            colors.append(NO_WELL_FILL)  # sentinel — fillpattern 으로 빗금 처리
        else:
            colors.append(slot_color(norm_t(v, vmin, vmax), metric.colorscale))

    fig = go.Figure()

    # ── 2. 리·동 박스 trace (hover + customdata) ──────────────────
    # 사용자 요청 2026-05-19: 클러스터 N 도 사용 보고 관정 기준 (메타 라벨용).
    if active_permits is not None:
        _m_for_n = master[master["permit_no"].astype(str).isin(active_permits)]
    else:
        _m_for_n = master
    cluster_n = _m_for_n.groupby("cluster").size()

    for slot, value, color, is_no_well in zip(
            layout.unit_slots, raw_values, colors, is_no_well_list):
        row = units_by_idx.loc[slot.idx] if slot.idx in units_by_idx.index else None
        n = int(row["n"]) if row is not None else 0
        est_area = float(row["est_area_ha"]) if row is not None else 0.0
        pw = float(row["per_well_annual"]) if row is not None else np.nan
        annual = float(row["annual"]) if row is not None else np.nan
        rain_part = ""
        if asos_annual is not None:
            asos_st = CLUSTER_ASOS.get(slot.cluster)
            if asos_st and asos_st in asos_annual.index:
                rain_part = (
                    f"<br>강수: {asos_st} "
                    f"{float(asos_annual[asos_st]):,.0f} mm/년"
                )
        if is_no_well:
            hover = (
                f"<b>{slot.cluster} · {slot.unit}</b><br>"
                f"추정 농지: {est_area:,.0f} ha · 관정 0공<br>"
                f"<i>인접 상류부 관정에서 농업용수 공급</i>"
                f"{rain_part}<extra></extra>"
            )
        else:
            hover = (
                f"<b>{slot.cluster} · {slot.unit}</b><br>"
                f"관정: {n} 공 · 추정농지: {est_area:,.0f} ha<br>"
                f"연평균: {annual/1e6:,.2f} 백만㎥/년<br>"
                f"관정당: {pw:,.0f} ㎥/공·년"
            )
            if metric_key not in ("per_well_annual", "annual"):
                hover += f"<br>{metric.label}: {metric.display(value)}"
            hover += f"{rain_part}<extra></extra>"

        is_selected = (selected_unit_idx is not None
                       and selected_unit_idx == slot.idx)
        line_color = theme.COLOR_TEXT_INFO if is_selected else "rgba(20,20,20,0.85)"
        line_width = 3.0 if is_selected else 0.4

        trace_kwargs: dict = dict(
            x=[slot.x, slot.x1, slot.x1, slot.x, slot.x],
            y=[slot.y, slot.y, slot.y1, slot.y1, slot.y],
            mode="lines",
            fill="toself",
            fillcolor=color,
            line=dict(color=line_color, width=line_width),
            hoveron="fills",
            hovertemplate=hover,
            customdata=[[slot.cluster, slot.unit, int(slot.idx)]] * 5,
            showlegend=False,
            name=f"{slot.cluster}·{slot.unit}",
        )
        if is_no_well:
            trace_kwargs["fillpattern"] = NO_WELL_PATTERN
        fig.add_trace(go.Scatter(**trace_kwargs))

    # ── 3. 클러스터 외곽선 trace ───────────────────────────────────
    cluster_line_w = 1.6 if show_meta_label else 1.4
    for cs in layout.cluster_slots:
        fig.add_trace(go.Scatter(
            x=[cs.x, cs.x1, cs.x1, cs.x, cs.x],
            y=[cs.y, cs.y, cs.y1, cs.y1, cs.y],
            mode="lines",
            fill=None,
            line=dict(color=theme.COLOR_ACCENT_NAVY, width=cluster_line_w),
            hoverinfo="skip",
            showlegend=False,
            name=cs.cluster,
        ))

    # ── 4. 리·동 텍스트 (큰 박스만 3줄, 중간 1줄, 작은 건 생략) ───
    big_x: list[float] = []; big_y: list[float] = []; big_text: list[str] = []
    mid_x: list[float] = []; mid_y: list[float] = []; mid_text: list[str] = []
    sm_x: list[float] = []; sm_y: list[float] = []; sm_text: list[str] = []
    val_x: list[float] = []; val_y: list[float] = []; val_text: list[str] = []
    n_x: list[float] = []; n_y: list[float] = []; n_text: list[str] = []

    for slot, value, is_no_well in zip(
            layout.unit_slots, raw_values, is_no_well_list):
        row = units_by_idx.loc[slot.idx] if slot.idx in units_by_idx.index else None
        n = int(row["n"]) if row is not None else 0
        pw = float(row["per_well_annual"]) if row is not None else np.nan
        area = slot.area
        if area >= 3.0:
            # 큰 박스 — 4줄 (이름 / N공 / 숫자 / 단위)
            big_x.append(slot.cx); big_y.append(slot.y + slot.height * 0.78)
            big_text.append(f"<b>{slot.unit}</b>")
            n_x.append(slot.cx); n_y.append(slot.y + slot.height * 0.55)
            n_text.append(f"{n}공")
            val_x.append(slot.cx); val_y.append(slot.y + slot.height * 0.30)
            if is_no_well:
                # 사용자 요청 2026-05-09: '상류 공급' 라벨 제거. 빈 텍스트.
                # (관정 0공 은 hover/tooltip 에 여전히 표시됨)
                val_text.append("")
            else:
                num_part, unit_part = metric.display_parts(value)
                val_text.append(
                    f"{num_part}<br>"
                    f"<span style='font-size:9.5px;color:#444'>{unit_part}</span>"
                )
        elif area >= 1.0:
            # 중간 박스 — 이름만 (작은 글자)
            mid_x.append(slot.cx); mid_y.append(slot.cy)
            mid_text.append(f"<b>{slot.unit}</b>")
        else:
            # 매우 작은 박스 — 이름만 (더 작은 글자)
            sm_x.append(slot.cx); sm_y.append(slot.cy)
            sm_text.append(slot.unit)

    if big_text:
        fig.add_trace(go.Scatter(
            x=big_x, y=big_y, mode="text",
            text=big_text,
            textfont=dict(size=13, color=theme.COLOR_TEXT_PRIMARY,
                          family="Arial Black, sans-serif"),
            hoverinfo="skip", showlegend=False,
        ))
        fig.add_trace(go.Scatter(
            x=n_x, y=n_y, mode="text",
            text=n_text,
            textfont=dict(size=11.5, color=theme.COLOR_TEXT_PRIMARY),
            hoverinfo="skip", showlegend=False,
        ))
        fig.add_trace(go.Scatter(
            x=val_x, y=val_y, mode="text",
            text=val_text,
            textfont=dict(size=10.5, color=theme.COLOR_TEXT_PRIMARY),
            hoverinfo="skip", showlegend=False,
        ))
    if mid_text:
        fig.add_trace(go.Scatter(
            x=mid_x, y=mid_y, mode="text",
            text=mid_text,
            textfont=dict(size=10.5, color=theme.COLOR_TEXT_PRIMARY,
                          family="Arial Black, sans-serif"),
            hoverinfo="skip", showlegend=False,
        ))
    if sm_text:
        fig.add_trace(go.Scatter(
            x=sm_x, y=sm_y, mode="text",
            text=sm_text,
            textfont=dict(size=6.5, color=theme.COLOR_TEXT_PRIMARY),
            hoverinfo="skip", showlegend=False,
        ))

    # ── 5. 클러스터 메타 라벨 (외곽 박스 위·아래) ──────────────────
    cluster_pw = _per_cluster_per_well(master, usage)

    for cs in layout.cluster_slots:
        n_w = int(cluster_n.get(cs.cluster, 0))
        short = short_name(cs.cluster)
        if cs.side == "top":
            anchor_y_label = cs.y1 + (0.32 if show_meta_label else 0.06)
            anchor_y_sub = cs.y1 + 0.05
            yanchor = "bottom"
        else:
            anchor_y_label = cs.y - (0.32 if show_meta_label else 0.06)
            anchor_y_sub = cs.y - 0.05
            yanchor = "top"

        fig.add_annotation(
            x=cs.cx, y=anchor_y_label,
            text=f"<b>{short}</b>" if show_meta_label
                 else f"<b>{short}  {ADMIN_AGRI_HA[cs.cluster]:,}ha</b>",
            showarrow=False,
            font=dict(size=14.5 if show_meta_label else 12,
                      color=theme.COLOR_ACCENT_NAVY),
            xanchor="center", yanchor=yanchor,
        )
        if show_meta_label:
            asos_str = ""
            if asos_annual is not None:
                asos_st = CLUSTER_ASOS.get(cs.cluster)
                if asos_st and asos_st in asos_annual.index:
                    p = float(asos_annual[asos_st])
                    if p > 0:
                        asos_str = f" · {asos_st} {p:,.0f}mm"
            pw = cluster_pw.get(cs.cluster, np.nan)
            pw_str = "—" if pd.isna(pw) else f"{pw/1000:,.0f}k㎥/공"
            fig.add_annotation(
                x=cs.cx, y=anchor_y_sub,
                text=(f"{ADMIN_AGRI_HA[cs.cluster]:,}ha · {n_w}공 · "
                      f"{pw_str}{asos_str}"),
                showarrow=False,
                font=dict(size=11, color=theme.COLOR_TEXT_TERTIARY),
                xanchor="center", yanchor=yanchor,
            )

    # ── 6. 시 라벨 ────────────────────────────────────────────────
    title_offset = 0.85 if show_meta_label else 0.45
    fig.add_annotation(
        x=layout.x_max / 2, y=layout.j_y1 + title_offset,
        text="<b>제주시</b>", showarrow=False,
        font=dict(size=20, color=theme.COLOR_ACCENT_NAVY),
        xanchor="center", yanchor="bottom",
    )
    fig.add_annotation(
        x=layout.x_max / 2, y=layout.s_y0 - title_offset,
        text="<b>서귀포시</b>", showarrow=False,
        font=dict(size=20, color=theme.COLOR_ACCENT_NAVY),
        xanchor="center", yanchor="top",
    )

    # ── 7. 컬러바 더미 trace ───────────────────────────────────────
    fig.add_trace(go.Scatter(
        x=[None], y=[None],
        mode="markers",
        marker=dict(
            colorscale=metric.colorscale,
            cmin=vmin, cmax=vmax,
            color=[vmin],
            size=0.0001,
            colorbar=dict(
                title=dict(text=metric.colorbar_title(period_label),
                           side="right"),
                thickness=14, len=0.78, x=1.02,
            ),
        ),
        hoverinfo="skip", showlegend=False,
    ))

    # ── 8. 축·레이아웃 ────────────────────────────────────────────
    y_pad = 1.4 if show_meta_label else 1.0
    fig.update_xaxes(range=[layout.x_min - 1, layout.x_max + 1],
                     visible=False, fixedrange=True)
    fig.update_yaxes(range=[layout.s_y0 - y_pad, layout.j_y1 + y_pad],
                     visible=False, fixedrange=True)

    fig.update_layout(
        title=dict(text=""),
        height=height,
        margin=dict(l=10, r=130, t=20, b=20),
        plot_bgcolor="white",
        paper_bgcolor="white",
        hoverlabel=dict(bgcolor="white", font_size=15,
                        bordercolor="rgba(26,26,24,0.30)"),
        font=dict(family="-apple-system, BlinkMacSystemFont, 'Segoe UI', "
                         "Roboto, sans-serif",
                  color=theme.COLOR_TEXT_PRIMARY),
    )
    return fig


# ──────────────────────────────────────────────────────────────────
#  공개 API — fig25: 좌(전체 농지) vs 우(200m 이하 농지) 비교
# ──────────────────────────────────────────────────────────────────
def render_compare(master: pd.DataFrame, usage: pd.DataFrame, *,
                   period_label: str | None = None,
                   selected_cluster: str | None = None,
                   height: int = 520,
                   color_vmin: "float | None" = None,
                   color_vmax: "float | None" = None,
                   active_permits: "set[str] | None" = None,
                   ) -> go.Figure:
    """클러스터 박스 비교 — 좌: 전체 농지 / 우: 표고 200m 이하 농지.

    공유 컬러스케일(YlOrRd, intensity_ha) · 5/95% 분위수 클립 · 동일 배치.
    customdata = [[cluster, panel_id]] * 5 (panel_id = "full" | "b200").

    Parameters
    ----------
    master, usage : DataFrame
        cluster 컬럼이 없으면 자동 부여.
    period_label : str | None
        컬러바 prefix.
    selected_cluster : str | None
        클릭 강조용. 두 패널 모두 굵은 청색 테두리.
    height : int
        Plotly 전체 Figure 높이.
    """
    # ── 0. 데이터 준비 ─────────────────────────────────────────────
    if "cluster" not in master.columns or "unit" not in master.columns:
        master = _normalize_master_admin(master)
    if "cluster" not in usage.columns:
        usage = usage.merge(
            master[["permit_no", "cluster", "unit"]],
            on="permit_no", how="left",
        )
    usage = usage[usage["cluster"].notna()]  # 미매핑 row 제거 → groupby NaN 방지

    cluster_df = aggregate_clusters(master, usage,
                                    active_permits=active_permits)
    # 사용자 요청 2026-05-19: well_n 도 사용 보고 관정 기준.
    if active_permits is not None:
        _m_for_n = master[master["permit_no"].astype(str).isin(active_permits)]
    else:
        _m_for_n = master
    well_n = _m_for_n.groupby("cluster").size()

    agri_full: dict[str, int] = dict(ADMIN_AGRI_HA)
    agri_b200: dict[str, int] = admin_below200_ha(master)

    # ── 1. 강도 계산 (양 패널) — annual / agri_dict[cluster] ─────────
    def _intensity_dict(agri_dict: dict[str, int]) -> dict[str, float]:
        out: dict[str, float] = {}
        for c in ADMIN_AGRI_HA.keys():
            ann = float(cluster_df["annual"].get(c, np.nan)) \
                if c in cluster_df.index else np.nan
            ha = agri_dict.get(c, 0)
            out[c] = (ann / ha) if (ha > 0 and not np.isnan(ann)) else np.nan
        return out

    intens_full = _intensity_dict(agri_full)
    intens_b200 = _intensity_dict(agri_b200)

    all_vals = list(intens_full.values()) + list(intens_b200.values())
    computed_vmin, computed_vmax = vmin_vmax(all_vals, (5, 95))
    if color_vmin is not None and color_vmax is not None:
        vmin, vmax = float(color_vmin), float(color_vmax)
    else:
        vmin, vmax = computed_vmin, computed_vmax
    # 사용자 요청 (2026-05-16): fig25 도 fig23/24 와 같은 색상 톤.
    # DAILY_USAGE_COLORSCALE: 0=흰그레이 / 400=sky / 800=navy / 800+=노랑 점프
    # / 1200=주황 / 1600=빨강. cmin/cmax 는 intensity_ha 자체 5/95 percentile
    # 유지 (단위 ㎥/ha·년 — per_well_daily 의 절대값 임계 의미 없음, 톤만 통일).
    colorscale = DAILY_USAGE_COLORSCALE

    # ── 2. subplot 생성 ────────────────────────────────────────────
    fig = make_subplots(
        rows=1, cols=2,
        subplot_titles=("전체 농지 기준", "200m 이하 농지 기준"),
        horizontal_spacing=0.06,
    )

    panels = [
        ("full", agri_full, intens_full, 1),
        ("b200", agri_b200, intens_b200, 2),
    ]

    layout_full: UnitLayout | None = None
    for panel_id, agri_dict, intens_dict, col in panels:
        layout = build_cluster_only_layout(
            agri_dict=agri_dict,
            page_w=100.0, band_total_h=6.6, gap=0.5,
        )
        if panel_id == "full":
            layout_full = layout

        # 박스 traces — 클러스터 12개
        for cs in layout.cluster_slots:
            value = intens_dict.get(cs.cluster, np.nan)
            t = norm_t(value, vmin, vmax)
            color = slot_color(t, colorscale)

            n = int(well_n.get(cs.cluster, 0))
            ha = agri_dict.get(cs.cluster, 0)
            ann = float(cluster_df["annual"].get(cs.cluster, np.nan)) \
                if cs.cluster in cluster_df.index else np.nan
            hover = (
                f"<b>{cs.cluster}</b><br>"
                f"농지: {ha:,} ha · 관정: {n:,} 공<br>"
                f"연평균: "
                f"{(ann/1e6):,.2f} 백만㎥/년<br>"
                f"단위면적 강도: "
                f"{value:,.0f} ㎥/ha·년"
                f"<extra></extra>"
            )
            is_selected = (selected_cluster is not None
                           and selected_cluster == cs.cluster)
            line_color = theme.COLOR_TEXT_INFO if is_selected else "rgba(20,20,20,0.85)"
            line_width = 3.0 if is_selected else 0.7
            fig.add_trace(
                go.Scatter(
                    x=[cs.x, cs.x1, cs.x1, cs.x, cs.x],
                    y=[cs.y, cs.y, cs.y1, cs.y1, cs.y],
                    mode="lines",
                    fill="toself",
                    fillcolor=color,
                    line=dict(color=line_color, width=line_width),
                    hoveron="fills",
                    hovertemplate=hover,
                    customdata=[[cs.cluster, panel_id]] * 5,
                    showlegend=False,
                    name=f"{cs.cluster}·{panel_id}",
                ),
                row=1, col=col,
            )

        # 텍스트 traces — 박스 안 4줄 (이름·면적관정·숫자·단위)
        cx_list = [cs.cx for cs in layout.cluster_slots]
        name_y = [cs.y1 - cs.height * 0.18 for cs in layout.cluster_slots]
        mid_y = [cs.cy + cs.height * 0.05 for cs in layout.cluster_slots]
        val_y = [cs.y + cs.height * 0.22 for cs in layout.cluster_slots]

        fig.add_trace(
            go.Scatter(
                x=cx_list, y=name_y,
                text=[f"<b>{short_name(cs.cluster)}</b>"
                      for cs in layout.cluster_slots],
                mode="text",
                textfont=dict(size=14, color=theme.COLOR_TEXT_PRIMARY,
                              family="Arial Black, sans-serif"),
                hoverinfo="skip", showlegend=False,
            ),
            row=1, col=col,
        )
        fig.add_trace(
            go.Scatter(
                x=cx_list, y=mid_y,
                text=[f"{agri_dict.get(cs.cluster, 0):,} ha · "
                      f"{int(well_n.get(cs.cluster, 0))} 공"
                      for cs in layout.cluster_slots],
                mode="text",
                textfont=dict(size=11.5, color=theme.COLOR_TEXT_PRIMARY),
                hoverinfo="skip", showlegend=False,
            ),
            row=1, col=col,
        )
        fig.add_trace(
            go.Scatter(
                x=cx_list, y=val_y,
                text=[(f"{intens_dict.get(cs.cluster, np.nan):,.0f}"
                       f"<br><span style='font-size:9.5px;color:#444'>"
                       f"㎥/ha·년</span>"
                       if not pd.isna(intens_dict.get(cs.cluster, np.nan))
                       else "—")
                      for cs in layout.cluster_slots],
                mode="text",
                textfont=dict(size=11, color=theme.COLOR_TEXT_PRIMARY),
                hoverinfo="skip", showlegend=False,
            ),
            row=1, col=col,
        )

        # 시 라벨 — 패널마다
        fig.add_annotation(
            xref=f"x{'' if col == 1 else col}",
            yref=f"y{'' if col == 1 else col}",
            x=layout.x_max / 2, y=layout.j_y1 + 0.50,
            text="<b>제주시</b>", showarrow=False,
            font=dict(size=15, color=theme.COLOR_ACCENT_NAVY),
            xanchor="center", yanchor="bottom",
        )
        fig.add_annotation(
            xref=f"x{'' if col == 1 else col}",
            yref=f"y{'' if col == 1 else col}",
            x=layout.x_max / 2, y=layout.s_y0 - 0.50,
            text="<b>서귀포시</b>", showarrow=False,
            font=dict(size=15, color=theme.COLOR_ACCENT_NAVY),
            xanchor="center", yanchor="top",
        )

    # ── 3. 공유 컬러바 더미 trace ──────────────────────────────────
    head = f"{period_label} " if period_label else ""
    fig.add_trace(go.Scatter(
        x=[None], y=[None],
        mode="markers",
        marker=dict(
            colorscale=colorscale,
            cmin=vmin, cmax=vmax,
            color=[vmin],
            size=0.0001,
            colorbar=dict(
                title=dict(text=f"{head}단위면적 강도 (㎥/ha·년)",
                           side="right"),
                thickness=14, len=0.78, x=1.02,
            ),
        ),
        hoverinfo="skip", showlegend=False,
    ))

    # ── 4. 축·레이아웃 ────────────────────────────────────────────
    assert layout_full is not None
    x_range = [-1, 101]
    y_range = [layout_full.s_y0 - 1.2, layout_full.j_y1 + 1.2]
    for col in (1, 2):
        fig.update_xaxes(range=x_range, visible=False, fixedrange=True,
                         row=1, col=col)
        fig.update_yaxes(range=y_range, visible=False, fixedrange=True,
                         row=1, col=col)

    fig.update_layout(
        title=dict(text=""),
        height=height,
        margin=dict(l=10, r=130, t=40, b=20),
        plot_bgcolor="white",
        paper_bgcolor="white",
        hoverlabel=dict(bgcolor="white", font_size=15,
                        bordercolor="rgba(26,26,24,0.30)"),
        font=dict(family="-apple-system, BlinkMacSystemFont, 'Segoe UI', "
                         "Roboto, sans-serif",
                  color=theme.COLOR_TEXT_PRIMARY),
    )
    # subplot_titles 폰트 통일
    for ann in fig.layout.annotations:
        if ann.text in ("전체 농지 기준", "200m 이하 농지 기준"):
            ann.font = dict(size=14, color=theme.COLOR_ACCENT_NAVY,
                            family="-apple-system, BlinkMacSystemFont, "
                                   "'Segoe UI', Roboto, sans-serif")
    return fig


# ──────────────────────────────────────────────────────────────────
#  헬퍼 — 클러스터별 per_well_annual (메타 라벨 4번째 줄용)
# ──────────────────────────────────────────────────────────────────
def _per_cluster_per_well(master: pd.DataFrame,
                          usage: pd.DataFrame) -> pd.Series:
    """관정당 연이용량 클러스터별 단순 계산.

    `admin_dual_zone.aggregate_clusters` 가 더 풍부하지만 여기선 라벨 한 줄에
    숫자만 필요해 직접 계산.
    """
    if "cluster" not in usage.columns:
        usage = usage.merge(
            master[["permit_no", "cluster"]],
            on="permit_no", how="left",
        )
    n_year = max(int(usage["year"].nunique()), 1) if "year" in usage.columns else 1
    if "volume_m3" in usage.columns:
        annual = usage.groupby("cluster")["volume_m3"].sum() / n_year
    else:
        from .constants import MONTHS_ABBR
        cols = list(MONTHS_ABBR)
        annual = usage.groupby("cluster")[cols].sum().sum(axis=1) / n_year
    cluster_n = master.groupby("cluster").size()
    return annual / cluster_n.replace(0, pd.NA)


__all__ = ["render_ri", "render_compare"]
