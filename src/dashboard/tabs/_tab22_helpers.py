# ==============================================================================
#  파일명: src/dashboard/tabs/_tab22_helpers.py
#  ⑥-2 이용량 세부 분석 탭 - 헬퍼 + 상세 렌더
#
#  Source 분리: tab22_ag_usage_detail.py 669줄 -> 분리 (2026-05-09).
#    - _section                       : 섹션 헤더 헬퍼
#    - _read_plotly_pick              : plotly 클릭 이벤트 -> selected dict
#    - _pick_first                    : selected dict 첫 항목
#    - _render_admin_cluster_detail   : 행정클러스터(시·읍면) 클릭 시 상세
#    - _render_unit_detail            : unit (리·동) 클릭 시 상세
#
#  외부 사용처: tab22_ag_usage_detail.py 내부 전용.
# ==============================================================================
from __future__ import annotations

import calendar

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import config
from src.dashboard import ag_well_helpers, theme
from src.dashboard.figures import admin_dual_zone, ri_dual_zone
from src.dashboard.figures.admin_dual_zone.constants import ADMIN_AGRI_HA
from src.dashboard.theme import render_stat_card

# P3-4 (2026-05-29): 아래 9개 import 가 dead 였음 — 모두 제거. 검증 카운트 0회.
#   - from src.analysis import ag_well_loader, ag_well_metrics  (0/0회)
#   - from ...ri_dual_zone import RI_METRICS, render_compare, render_ri  (0/0/0회)
#   - from ...ri_dual_zone.data import _normalize_master_admin, aggregate_units  (0/0회)
#   - from ...ri_dual_zone.monthly import render_monthly  (0회)
#   - from src.dashboard import usage_detail_helpers as udh  (0회)


def _section(title: str, caption: str | None = None) -> None:
    """tab10 sub-header — subsection-title 클래스 (사용자 요청 2026-05-09 디자인 통일).

    이전 인라인 스타일(15px 파랑) → 18px bold #1a1a18 (theme.py 정의).
    """
    st.markdown(
        f'<p class="subsection-title" style="margin:14px 0 4px;">{title}</p>',
        unsafe_allow_html=True,
    )
    if caption:
        st.caption(caption)


# ──────────────────────────────────────────────────────────────────
#  Plotly 클릭 이벤트 — customdata 추출 헬퍼
# ──────────────────────────────────────────────────────────────────
def _read_plotly_pick(event):
    """st.plotly_chart(on_select='rerun') 이벤트에서 첫 클릭 customdata 반환.

    Returns
    -------
    list | tuple | str | None
        customdata 원본 (배열이면 통째로 반환). 없으면 None.
    """
    if not event:
        return None
    if isinstance(event, dict):
        selection = event.get("selection")
    else:
        selection = getattr(event, "selection", None)
    if selection is None:
        return None
    if isinstance(selection, dict):
        points = selection.get("points")
    else:
        points = getattr(selection, "points", None)
    if not points:
        return None
    first = points[0]
    if isinstance(first, dict):
        cd = first.get("customdata")
    else:
        cd = getattr(first, "customdata", None)
    return cd


def _pick_first(cd):
    """customdata 를 끝까지 풀어 scalar(string/숫자) 로 반환.

    fig23 의 박스 trace customdata 는 `[[cluster]] * 5` 라 plotly 가
    streamlit 버전·클릭 위치에 따라 `[cluster]` (정상) 또는 `[[cluster], ...]`
    (전체 row 묶음) 으로 반환할 수 있다. 한 번만 unwrap 하면 후자에서 list
    를 그대로 session_state 에 저장 → master["cluster"] 비교 실패. 끝까지
    풀어 string 보장. (로직 분석 에이전트 진단 2026-05-10)
    """
    while isinstance(cd, (list, tuple)) and len(cd) > 0:
        cd = cd[0]
    return cd


# ──────────────────────────────────────────────────────────────────
#  단일 클러스터 squarified treemap — fig23 detail 좌측 패널 전용
# ──────────────────────────────────────────────────────────────────
# 사용자 요청 2026-05-10: 그림 23(admin_dual_zone) 와 동일한 colorscale 사용.
# ADMIN_METRICS 의 모든 metric 이 "RdYlBu_r" 이라 detail 도 동일하게 적용.
# plotly.colors.sample_colorscale 로 plotly 내장 스케일을 그대로 재사용.
def _treemap_colors(ratios: "list[float]", colorscale: str) -> "list[str]":
    """0~1 ratio 리스트 → plotly colorscale 의 rgb 문자열 리스트."""
    from plotly.colors import sample_colorscale
    safe = [max(0.0, min(1.0, float(r))) for r in ratios] or [0.0]
    return list(sample_colorscale(colorscale, safe))


def _treemap_color(ratio: float, colorscale: str = "RdYlBu_r") -> str:
    return _treemap_colors([ratio], colorscale)[0]


def _cluster_unit_slots(units_df: "pd.DataFrame | None", cluster: str):
    """ri_dual_zone build_unit_layout 결과에서 선택 클러스터의 cluster_slot
    + unit_slots 를 그대로 추출. 그림 24 와 정확히 동일한 배치 보장.
    """
    if units_df is None or units_df.empty:
        return None, []
    try:
        from src.dashboard.figures.ri_dual_zone.layout import build_unit_layout
        layout = build_unit_layout(units_df)
    except Exception:
        return None, []
    cs = next((c for c in layout.cluster_slots if c.cluster == cluster), None)
    us = [s for s in layout.unit_slots if s.cluster == cluster]
    return cs, us


def _ri_unit_aggregates(m: pd.DataFrame, u: pd.DataFrame,
                        *, active_permits: "set[str] | None" = None,
                        ) -> "tuple[dict[str, int], dict[str, float]]":
    """리·동별 (관정수, 기간 합 이용량) 두 dict 반환.

    키는 normalize_master 가 채운 `unit` 컬럼 (동지역=eup, 비동지역=ri) —
    `slot.unit` 과 직접 매칭하기 위함. 과거 well_ri 키잉은 동지역에서
    slot.unit("노형동")과 ri_master 키("(미분류)" 또는 빈 문자열) 불일치로
    모든 박스가 회색 처리되는 버그를 일으켰음 (2026-05-19 8팀 진단).

    active_permits 가 주어지면 n_dict 계산 시 그 집합에 속한 관정만
    카운트 — 「분석 기간 내 사용 보고가 없는 관정」을 트리맵 분모에서
    제외 (사용자 요청 2026-05-19).
    """
    n_dict: dict[str, int] = {}
    vol_dict: dict[str, float] = {}
    src_col = "unit" if "unit" in m.columns else (
        "well_ri" if "well_ri" in m.columns else None)
    if src_col is None:
        return n_dict, vol_dict
    # _key: u 측에 이미 unit 컬럼이 있을 수 있어 merge 충돌(unit_x/unit_y)
    # 회피용 sentinel 이름 사용.
    ri_master = m[["permit_no", src_col]].drop_duplicates("permit_no").copy()
    ri_master = ri_master.rename(columns={src_col: "_unit_key"})
    ri_master["_unit_key"] = ri_master["_unit_key"].fillna("(미분류)").astype(str)
    # N 분모 — 사용자 요청 2026-05-19: 사용 보고 관정만 카운트.
    if active_permits is not None:
        n_src = ri_master[ri_master["permit_no"].astype(str).isin(active_permits)]
    else:
        n_src = ri_master
    n_per_ri = n_src.groupby("_unit_key").size()
    n_dict = {k: int(v) for k, v in n_per_ri.items()}
    if not u.empty and "volume_m3" in u.columns:
        u_ri = u.merge(ri_master, on="permit_no", how="left")
        u_ri["_unit_key"] = u_ri["_unit_key"].fillna("(미분류)").astype(str)
        vp = u_ri.groupby("_unit_key")["volume_m3"].sum()
        vol_dict = {k: float(v) for k, v in vp.items()}
    return n_dict, vol_dict


# P3-4 (2026-05-29): _global_monthly_per_well_daily_max 제거 (57줄, 호출처 0건).
# 전역 vmax 는 figures._dual_zone_common.color.DAILY_USAGE_VMAX 상수(절대도메인)
# 로 대체되어 본 함수는 dead. tab22/23 둘 다 더 이상 사용 안 함.


def _monthly_per_well_daily_range(m: pd.DataFrame, u: pd.DataFrame,
                                  *, cluster: str,
                                  units_df: "pd.DataFrame | None" = None,
                                  active_permits: "set[str] | None" = None,
                                  ) -> "tuple[float, float]":
    """B(12개월 패널) 의 월별 관정당 일 이용량 (vmin, vmax) 계산.

    A(좌측) 와 B(우측) 가 같은 colorbar 스케일을 공유하기 위한 헬퍼.
    B 의 월별 값 분포가 A 의 기간평균보다 항상 더 넓으므로 (평균은 피크
    보다 작음), B 의 범위를 양쪽에 공통 적용하는 것이 자연스럽다.
    (사용자 요청 2026-05-10: A·B colorbar 통합)
    """
    cluster_slot, unit_slots = _cluster_unit_slots(units_df, cluster)
    if cluster_slot is None or not unit_slots or u is None or u.empty:
        return 0.0, 1.0
    # 사용자 요청 2026-05-19: well_ri 대신 normalize_master 가 채운 unit 컬럼
    # 사용 (동지역=eup, 비동지역=ri). slot.unit 과 직접 매칭.
    src_col = "unit" if "unit" in m.columns else (
        "well_ri" if "well_ri" in m.columns else None)
    if "year" not in u.columns or "month" not in u.columns or src_col is None:
        return 0.0, 1.0
    n_dict, _ = _ri_unit_aggregates(m, u, active_permits=active_permits)
    years = sorted(int(y) for y in u["year"].dropna().unique())
    days_pm = {mn: sum(calendar.monthrange(y, mn)[1] for y in years)
               for mn in range(1, 13)}
    # _unit_key sentinel: u 에 이미 unit 컬럼이 있을 수 있어 merge 충돌 회피.
    ri_master = m[["permit_no", src_col]].drop_duplicates("permit_no").copy()
    ri_master = ri_master.rename(columns={src_col: "_unit_key"})
    ri_master["_unit_key"] = ri_master["_unit_key"].fillna("(미분류)").astype(str)
    u_ri = u.dropna(subset=["month"]).merge(
        ri_master, on="permit_no", how="left",
    )
    if u_ri.empty:
        return 0.0, 1.0
    u_ri["month"] = u_ri["month"].astype(int)
    u_ri["_unit_key"] = u_ri["_unit_key"].fillna("(미분류)").astype(str)
    grp = u_ri.groupby(["month", "_unit_key"])["volume_m3"].sum()
    pwd_vals: list[float] = []
    for (mn, ri), vv in grp.items():
        n = n_dict.get(str(ri), 0)
        d = days_pm.get(int(mn), 30)
        if n > 0 and d > 0:
            pwd_vals.append(float(vv) / d / n)
    if not pwd_vals:
        return 0.0, 1.0
    return min(pwd_vals), max(pwd_vals)


def _build_cluster_ri_treemap(m: pd.DataFrame, u: pd.DataFrame,
                              *, cluster: str, agri_ha: float,
                              units_df: pd.DataFrame | None = None,
                              colorscale: str = "RdYlBu_r",
                              color_vmin: "float | None" = None,
                              color_vmax: "float | None" = None,
                              active_permits: "set[str] | None" = None,
                              ) -> "go.Figure | None":
    """선택 클러스터 안의 리·동 트리맵 — ri_dual_zone (그림 24) 와 동일 배치.

    박스 좌표는 ri_dual_zone 의 build_unit_layout 결과 unit_slots 를
    그대로 재사용 → 동의 상대 위치·크기 (그림 24 와 동일).

    사용자 요청 2026-05-10 (재): 박스 색·라벨을 모두 '관정당 일 이용량
    (㎥/공·일)' 로 통일. = 기간 합계 ÷ 기간(일) ÷ N공. 이전엔 '기간 합계
    천㎥' 였는데 라벨/colorbar 가 B 와 따로 놀았음.
    """
    cluster_slot, unit_slots = _cluster_unit_slots(units_df, cluster)
    if cluster_slot is None or not unit_slots:
        return None

    n_dict, vol_dict = _ri_unit_aggregates(m, u, active_permits=active_permits)

    # 기간 일수 = 분석 연도 × 12개월 실제 일수 합 (윤년 정확).
    if not u.empty and "year" in u.columns:
        years_in_u = sorted(int(y) for y in u["year"].dropna().unique())
        period_days = sum(
            calendar.monthrange(y, mn)[1]
            for y in years_in_u for mn in range(1, 13)
        )
    else:
        period_days = 365
    period_days = max(period_days, 1)

    # 리별 관정당 일 이용량
    per_well_daily_dict: dict[str, float] = {}
    for s in unit_slots:
        n = n_dict.get(s.unit, 0)
        v = vol_dict.get(s.unit, 0.0)
        per_well_daily_dict[s.unit] = (v / period_days / n) if n > 0 else 0.0

    # 사용자 요청 2026-05-10: A·B colorbar 통합 — 외부에서 (B의) 통합 범위
    #   를 받으면 그대로 사용. 그래야 A의 색이 B colorbar 와 1:1 매칭.
    if color_vmin is not None and color_vmax is not None:
        vmin, vmax = float(color_vmin), float(color_vmax)
    else:
        pwd_vals = [per_well_daily_dict.get(s.unit, 0.0) for s in unit_slots]
        vmin = min(pwd_vals) if pwd_vals else 0.0
        vmax = max(pwd_vals) if pwd_vals else 1.0
    vrng = (vmax - vmin) if vmax > vmin else 1.0

    fig = go.Figure()
    text_xs: list[float] = []
    text_ys: list[float] = []
    text_strs: list[str] = []

    for slot in unit_slots:
        v = vol_dict.get(slot.unit, 0.0)  # 기간 합 (hover 용)
        n = n_dict.get(slot.unit, 0)
        pwd = per_well_daily_dict.get(slot.unit, 0.0)
        ratio = (pwd - vmin) / vrng if vmax > vmin else 0.5
        if pwd <= 0:
            fillcolor = "rgba(220,220,220,0.55)"
        else:
            fillcolor = _treemap_color(ratio, colorscale)
        hover = (
            f"<b>{slot.unit}</b><br>"
            f"관정 {n} 공 · 기간합 {v/1e3:,.1f} 천㎥<br>"
            f"관정당 일평균 {pwd:,.0f} ㎥/공·일"
            f"<extra></extra>"
        )
        fig.add_trace(go.Scatter(
            x=[slot.x, slot.x + slot.width, slot.x + slot.width, slot.x, slot.x],
            y=[slot.y, slot.y, slot.y + slot.height, slot.y + slot.height, slot.y],
            mode="lines",
            fill="toself",
            fillcolor=fillcolor,
            line=dict(color="rgba(20,20,20,0.6)", width=0.7),
            hoveron="fills",
            hovertemplate=hover,
            showlegend=False,
            name=str(slot.unit),
        ))
        # 박스 면적이 충분할 때 텍스트 표시 (값을 ㎥/일 로 줄바꿈하여 단위 분리)
        area = slot.width * slot.height
        if area > 0.55:
            if pwd > 0:
                # fig24 metric.fmt='{:,.1f}' 와 자릿수 통일 (사용자 요청 2026-05-10)
                txt = (f"<b>{slot.unit}</b><br>{n}공<br>"
                       f"{pwd:,.1f}<br>㎥/일")
            else:
                txt = f"<b>{slot.unit}</b><br>{n}공"
        elif area > 0.20:
            txt = f"<b>{slot.unit}</b><br>{n}공"
        elif area > 0.06:
            txt = f"{slot.unit}"
        else:
            txt = ""
        if txt:
            text_xs.append(slot.x + slot.width / 2.0)
            text_ys.append(slot.y + slot.height / 2.0)
            text_strs.append(txt)

    if text_strs:
        fig.add_trace(go.Scatter(
            x=text_xs, y=text_ys,
            mode="text", text=text_strs,
            textfont=dict(size=12.5, color="#1a1a18"),
            hoverinfo="skip", showlegend=False,
        ))

    margin = 0.05
    fig.update_xaxes(
        range=[cluster_slot.x - margin,
               cluster_slot.x + cluster_slot.width + margin],
        visible=False, fixedrange=True,
    )
    # ri_dual_zone layout 의 y 는 math 컨벤션 (작은 y = 남쪽 = 화면 아래).
    # fig24 와 같은 ascending range 로 통일 (사용자 요청 2026-05-10):
    # 이전엔 reversed range 라 같은 클러스터 안에서 fig24 와 위·아래가
    # 뒤집혀 보였음 (예: 한경면의 조수리/저지리 swap).
    # plot 영역 높이 = 280 × 1.2 = 336px, B(840px)와 vertical center 위해
    # t/b margin = (840-336)/2 = 252.
    fig.update_yaxes(
        range=[cluster_slot.y - margin,
               cluster_slot.y + cluster_slot.height + margin],
        visible=False, fixedrange=True,
    )
    fig.update_layout(
        height=840,
        margin=dict(l=4, r=4, t=252, b=252),
        plot_bgcolor="white", paper_bgcolor="white",
        showlegend=False,
        hoverlabel=dict(bgcolor="white",
                        bordercolor="rgba(26,26,24,0.30)"),
        font=dict(family="-apple-system, BlinkMacSystemFont, 'Segoe UI', "
                         "Roboto, sans-serif",
                  color=theme.COLOR_TEXT_PRIMARY),
    )
    return fig


def _build_cluster_monthly_treemaps(m: pd.DataFrame, u: pd.DataFrame,
                                    *, cluster: str,
                                    units_df: pd.DataFrame | None = None,
                                    colorscale: str = "RdYlBu_r",
                                    color_vmin: "float | None" = None,
                                    color_vmax: "float | None" = None,
                                    active_permits: "set[str] | None" = None,
                                    ) -> "go.Figure | None":
    """선택 클러스터의 12 개월 mini 트리맵 — 3 행 4 열 subplot.

    동의 배치는 좌측 큰 트리맵과 동일 (ri_dual_zone unit_slots 재사용).
    각 패널의 박스 색은 해당 월의 리·동별 이용량 (전체 12 개월 통합 vmin/vmax).
    """
    from plotly.subplots import make_subplots

    cluster_slot, unit_slots = _cluster_unit_slots(units_df, cluster)
    if cluster_slot is None or not unit_slots:
        return None

    # 사용자 요청 2026-05-10: 패널 라벨에 N공·㎥/일 추가.
    # 사용자 요청 2026-05-19: 분모 N 을 사용 보고 관정으로 한정.
    n_dict, _ = _ri_unit_aggregates(m, u, active_permits=active_permits)
    # 2026-05-28 P2-2 (Tab23 방식 채택): 분모(일수)는 "실제 데이터가 있는
    # (연,월)" 만 합산. 결측 연도까지 분모로 잡으면 일평균이 underestimate 됨.
    if not u.empty and "year" in u.columns and "month" in u.columns:
        present = (u.dropna(subset=["year", "month"])
                    .assign(y=lambda d: d["year"].astype(int),
                            m=lambda d: d["month"].astype(int))
                    [["y", "m"]].drop_duplicates())
        days_per_month: dict[int, int] = {mn: 0 for mn in range(1, 13)}
        for y_val, m_val in present.itertuples(index=False):
            days_per_month[m_val] = days_per_month.get(m_val, 0) + calendar.monthrange(y_val, m_val)[1]
    else:
        _DAYS_DEFAULT = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
        days_per_month = {mn: _DAYS_DEFAULT[mn - 1] for mn in range(1, 13)}

    # 월별 리·동별 이용량
    # 사용자 요청 2026-05-19: well_ri → unit 컬럼 (동지역=eup, 비동지역=ri).
    # slot.unit("노형동") 과 dict 키를 직접 매칭. 과거 well_ri 키잉 시
    # 동지역에서 매칭 실패 → 전 박스 회색 처리되던 버그 fix.
    # _unit_key sentinel: u 에 이미 unit 컬럼이 있을 수 있어 merge 충돌 회피.
    monthly_ri: dict[tuple[int, str], float] = {}
    src_col = "unit" if "unit" in m.columns else (
        "well_ri" if "well_ri" in m.columns else None)
    if "month" in u.columns and src_col is not None and not u.empty:
        ri_master = m[["permit_no", src_col]].drop_duplicates("permit_no").copy()
        ri_master = ri_master.rename(columns={src_col: "_unit_key"})
        ri_master["_unit_key"] = ri_master["_unit_key"].fillna("(미분류)").astype(str)
        u_ri = u.dropna(subset=["month"]).merge(
            ri_master, on="permit_no", how="left",
        )
        if not u_ri.empty:
            u_ri["month"] = u_ri["month"].astype(int)
            u_ri["_unit_key"] = u_ri["_unit_key"].fillna("(미분류)").astype(str)
            grp = u_ri.groupby(["month", "_unit_key"])["volume_m3"].sum()
            monthly_ri = {(int(k[0]), str(k[1])): float(v)
                          for k, v in grp.items()}

    # 사용자 요청 2026-05-10 (재): 색·colorbar 를 '관정당 일 이용량
    #  (㎥/공·일)' 로 통일 — = (해당월 합 across years) ÷ (해당월 일수 합) ÷ N공.
    per_well_daily_monthly: dict[tuple[int, str], float] = {}
    for (mn, ri), vv in monthly_ri.items():
        nn = n_dict.get(ri, 0)
        dd = days_per_month.get(mn, 30)
        if nn > 0 and dd > 0:
            per_well_daily_monthly[(mn, ri)] = vv / dd / nn
        else:
            per_well_daily_monthly[(mn, ri)] = 0.0

    # 전체 12 개월 통합 vmin/vmax — 패널 간 색 비교 가능 (관정당 일평균 기준)
    # 사용자 요청 2026-05-10: A·B colorbar 통합 — 외부 범위 우선.
    if color_vmin is not None and color_vmax is not None:
        vmin, vmax = float(color_vmin), float(color_vmax)
    else:
        all_vals = list(per_well_daily_monthly.values()) or [0.0]
        vmin = min(all_vals)
        vmax = max(all_vals)
    vrng = (vmax - vmin) if vmax > vmin else 1.0

    fig = make_subplots(
        rows=3, cols=4,
        subplot_titles=[f"{m_num}월" for m_num in range(1, 13)],
        horizontal_spacing=0.012, vertical_spacing=0.06,
    )

    # 박스 면적이 충분히 큰 동에만 텍스트 표시 (subplot 좁아 글자 겹침 방지).
    # 면적 임계값은 cluster_slot 영역 대비 상대 비율로 산정.
    # 사용자 요청 2026-05-10: 4-tier 라벨 — name / +N공 / +값+㎥/일 / 값·㎥/일 분리.
    cs_area = cluster_slot.width * cluster_slot.height
    area_thr_4line = cs_area * 0.085  # 리 + N공 + 값 + ㎥/일 (4줄, 단위 분리)
    area_thr_3line = cs_area * 0.045  # 리 + N공 + 값 ㎥/일 (3줄, 단위 같은 줄)
    area_thr_2line = cs_area * 0.022  # 리 + N공 (2줄)
    area_thr_1line = cs_area * 0.012  # 리 이름만

    for m_num in range(1, 13):
        r = (m_num - 1) // 4 + 1
        c = (m_num - 1) % 4 + 1
        text_xs: list[float] = []
        text_ys: list[float] = []
        text_strs: list[str] = []
        for slot in unit_slots:
            v = monthly_ri.get((m_num, slot.unit), 0.0)
            n_wells = n_dict.get(slot.unit, 0)
            # 사용자 요청 2026-05-10 (재): 라벨·색 모두 '관정당 일평균'.
            #   = (월 합 m³) ÷ (월 일수) ÷ (N공). 이전엔 N공 으로 안 나눠 ri 합계
            #   가 노출돼 stat card '관정당 연이용량 ÷ 365' 보다 ~N배 컸음.
            daily_per_well = per_well_daily_monthly.get((m_num, slot.unit), 0.0)
            ratio = (daily_per_well - vmin) / vrng if vmax > vmin else 0.0
            fillcolor = (_treemap_color(ratio, colorscale)
                         if daily_per_well > 0 else "rgba(220,220,220,0.4)")
            fig.add_trace(go.Scatter(
                x=[slot.x, slot.x + slot.width, slot.x + slot.width,
                   slot.x, slot.x],
                y=[slot.y, slot.y, slot.y + slot.height,
                   slot.y + slot.height, slot.y],
                mode="lines",
                fill="toself",
                fillcolor=fillcolor,
                line=dict(color="rgba(20,20,20,0.4)", width=0.4),
                hoveron="fills",
                hovertemplate=(
                    f"<b>{m_num}월 · {slot.unit}</b><br>"
                    f"{n_wells}공 · 월합 {v/1e3:,.1f} 천㎥<br>"
                    f"관정당 일평균 {daily_per_well:,.0f} ㎥/공·일"
                    f"<extra></extra>"
                ),
                # 사용자 요청 2026-05-10: 작은 박스에서 hover 가 'trace N'
                #   으로 떨어지지 않게 name 을 ri 이름으로 명시 (안전망).
                name=str(slot.unit),
                showlegend=False,
            ), row=r, col=c)

            # 박스 면적에 따라 라벨 단계 결정 (4-tier).
            area = slot.width * slot.height
            if area >= area_thr_4line:
                if n_wells > 0 and v > 0:
                    txt = (f"<b>{slot.unit}</b><br>"
                           f"{n_wells}공<br>"
                           f"{daily_per_well:,.0f}<br>"
                           f"㎥/일")
                elif n_wells > 0:
                    txt = f"<b>{slot.unit}</b><br>{n_wells}공"
                else:
                    txt = f"<b>{slot.unit}</b>"
            elif area >= area_thr_3line:
                if n_wells > 0 and v > 0:
                    txt = (f"<b>{slot.unit}</b><br>"
                           f"{n_wells}공<br>"
                           f"{daily_per_well:,.0f} ㎥/일")
                elif n_wells > 0:
                    txt = f"<b>{slot.unit}</b><br>{n_wells}공"
                else:
                    txt = f"<b>{slot.unit}</b>"
            elif area >= area_thr_2line:
                if n_wells > 0:
                    txt = f"<b>{slot.unit}</b><br>{n_wells}공"
                else:
                    txt = f"<b>{slot.unit}</b>"
            elif area >= area_thr_1line:
                txt = slot.unit
            else:
                txt = ""
            if txt:
                text_xs.append(slot.x + slot.width / 2.0)
                text_ys.append(slot.y + slot.height / 2.0)
                text_strs.append(txt)

        if text_strs:
            fig.add_trace(go.Scatter(
                x=text_xs, y=text_ys,
                mode="text", text=text_strs,
                textfont=dict(size=10, color="#1a1a18"),
                hoverinfo="skip", showlegend=False,
            ), row=r, col=c)

        # 각 subplot 의 axis range = cluster_slot 영역
        fig.update_xaxes(
            range=[cluster_slot.x, cluster_slot.x + cluster_slot.width],
            visible=False, fixedrange=True, row=r, col=c,
        )
        # 사용자 요청 2026-05-10: A 와 같은 ascending 으로 fig24 방향 통일.
        fig.update_yaxes(
            range=[cluster_slot.y, cluster_slot.y + cluster_slot.height],
            visible=False, fixedrange=True, row=r, col=c,
        )

    # 사용자 요청 2026-05-10: 그림 23 과 동일한 colorscale 의 colorbar 통합.
    # plotly 내장 colorscale 이름을 그대로 marker 에 부착 → figure 전역 표시.
    # 사용자 요청 2026-05-10 (재): 색·라벨이 모두 '관정당 일 이용량' 이므로
    #   colorbar 제목·단위도 동일하게 (㎥/공·일) — 이전 '월 이용량 (천㎥)' 과
    #   라벨이 따로 놀던 문제 해소.
    if vmax > vmin:
        fig.add_trace(go.Scatter(
            x=[None], y=[None],
            mode="markers",
            marker=dict(
                colorscale=colorscale,
                cmin=vmin, cmax=vmax,
                color=[vmin],
                size=0.0001,
                colorbar=dict(
                    title=dict(text="관정당 일 이용량 (㎥/공·일)",
                               side="right"),
                    thickness=12, len=0.85, x=1.005,
                    tickfont=dict(size=13),
                ),
            ),
            hoverinfo="skip", showlegend=False,
        ))

    # subplot 제목 폰트 (subplot_titles 의 annotation 들)
    for ann in fig.layout.annotations:
        ann.font = dict(size=11, color=theme.COLOR_TEXT_PRIMARY)

    # 사용자 요청 2026-05-10: 12 개월 트리맵 height 1.5 배 (560 → 840).
    fig.update_layout(
        height=840,
        margin=dict(l=4, r=110, t=22, b=4),  # r 마진 colorbar 공간 확보
        plot_bgcolor="white", paper_bgcolor="white",
        showlegend=False,
        hoverlabel=dict(bgcolor="white",
                        bordercolor="rgba(26,26,24,0.30)"),
        font=dict(family="-apple-system, BlinkMacSystemFont, 'Segoe UI', "
                         "Roboto, sans-serif",
                  color=theme.COLOR_TEXT_PRIMARY),
    )
    return fig


# ──────────────────────────────────────────────────────────────────
#  드릴다운 헬퍼 — 그림 23·25 (클러스터 단위) 공용
# ──────────────────────────────────────────────────────────────────
def _render_admin_cluster_detail(master: pd.DataFrame, usage: pd.DataFrame,
                                 *, cluster: str, period_text: str,
                                 clear_btn_key: str,
                                 clear_state_key: str,
                                 yr_chart_key: str,
                                 chart_version_key: str | None = None,
                                 units_df: pd.DataFrame | None = None,
                                 colorscale: str = "RdYlBu_r",
                                 cluster_options: "list[str] | None" = None,
                                 color_vmin: "float | None" = None,
                                 color_vmax: "float | None" = None,
                                 active_permits: "set[str] | None" = None,
                                 ) -> None:
    """선택된 행정구역의 세부 분석 패널 — 그림 23·25 클릭 드릴다운 공용.

    chart_version_key 가 주어지면 선택 해제 시 카운터를 1 증가시켜
    plotly_chart 의 selection state 까지 리셋한다.

    cluster_options 가 주어지면 헤더 바로 아래에 '읍·면·동 선택 :' 라벨 +
    selectbox 를 한 줄로 렌더 (사용자 요청 2026-05-10).
    """
    # 사용자 요청 2026-05-10: 안내 박스 자리(plotly_chart 직후)에 detail 이
    # 즉시 표시되도록 hr 위·아래 마진을 0 으로. 박스와 detail 헤더 사이 간격
    # 최소화 → 클릭 후 detail 이 시야에 바로 들어옴.
    st.markdown(
        '<hr style="margin:0 0 6px;border:none;'
        'border-top:0.5px solid rgba(26,26,24,0.15);">',
        unsafe_allow_html=True,
    )

    head_l, head_r = st.columns([8, 2])
    with head_l:
        st.markdown(
            f'<p class="subsection-title" style="margin:0 0 2px;">'
            f'📍 {cluster} — 세부 분석</p>',
            unsafe_allow_html=True,
        )
        st.caption(f"분석 기간 **{period_text}**")
    with head_r:
        if st.button("선택 해제", key=clear_btn_key,
                     use_container_width=True):
            st.session_state.pop(clear_state_key, None)
            if chart_version_key:
                st.session_state[chart_version_key] = (
                    st.session_state.get(chart_version_key, 0) + 1
                )
            ag_well_helpers.fragment_rerun()

    # ── 사용자 요청 2026-05-10: 헤더 바로 아래 1줄 인라인 selectbox.
    #   '읍·면·동 선택 :' 라벨 + dropdown 한 라인. 기존에는 fig23 위쪽에
    #   별도 selectbox 가 있었으나 detail 패널 헤더 직하로 이동.
    if cluster_options:
        sel_l, sel_r = st.columns([1, 5])
        with sel_l:
            st.markdown(
                '<div style="padding-top:0.55rem;">읍·면·동 선택 :</div>',
                unsafe_allow_html=True,
            )
        with sel_r:
            sel_index = (cluster_options.index(cluster)
                         if cluster in cluster_options else 0)
            new_sel = st.selectbox(
                "읍·면·동 선택",
                options=cluster_options,
                index=sel_index,
                key=f"{clear_state_key}_inline_sel",
                label_visibility="collapsed",
            )
            if new_sel and new_sel != cluster:
                st.session_state[clear_state_key] = new_sel
                ag_well_helpers.fragment_rerun()

    m = master[master["cluster"] == cluster]
    u = usage[usage["cluster"] == cluster]
    if m.empty:
        st.warning(f"{cluster} 에 매핑된 관정이 없습니다.")
        return

    # 사용자 요청 2026-05-19: 분모 N 을 "분석 기간 내 이용량>0 관정"으로.
    # 등록 관정 수(n_total) 는 서브텍스트에 표기.
    n_total = int(len(m))
    if active_permits is not None:
        n_used = int(m["permit_no"].astype(str).isin(active_permits).sum())
    else:
        n_used = n_total
    n_wells = n_used  # per_well 분모
    agri = ADMIN_AGRI_HA.get(cluster, 0)
    has_volume = "volume_m3" in u.columns
    total_use = float(u["volume_m3"].sum()) if has_volume else 0.0
    n_year = max(int(u["year"].nunique()), 1) if not u.empty else 1
    annual_avg = total_use / n_year
    per_well = annual_avg / n_wells if n_wells else 0.0
    intensity = annual_avg / agri if agri else 0.0

    _n_sub = (f"등록 {n_total:,}공 중 사용 {n_used:,}공 · 농지 {agri:,} ha"
              if n_used != n_total else f"농지 {agri:,} ha")
    c1, c2, c3, c4 = st.columns(4)
    render_stat_card("관정 수 (사용)", f"{n_wells:,} 공",
                     sub=_n_sub,
                     color=theme.COLOR_TEXT_INFO, container=c1)
    render_stat_card("총 이용량 (기간)",
                     f"{total_use/1e6:,.1f} 백만㎥",
                     sub=f"{n_year}년", color=theme.COLOR_TEXT_INFO, container=c2)
    render_stat_card("연평균 이용량",
                     f"{annual_avg/1e6:,.2f} 백만㎥/년",
                     sub=f"단위면적 {intensity:,.0f} ㎥/ha·년",
                     color=theme.COLOR_TEXT_INFO, container=c3)
    render_stat_card("관정당 연이용량",
                     f"{per_well:,.0f} ㎥/공·년",
                     color=theme.COLOR_TEXT_INFO, container=c4)

    if u.empty or not has_volume:
        st.info("이용량 데이터가 없어 리·동별·월별 분석을 표시할 수 없습니다.")
        return

    # ──────────────────────────────────────────────────────────────────
    #  사용자 요청 2026-05-10:
    #   기존 '연도별 막대 + 상위 관정 표' → 좌·우 2 컬럼:
    #     좌 — 리·동별 이용량 가로 막대 (단일 큰 차트)
    #     우 — 3×4 그리드 12 개월 패널 (선택 기간 누적 합)
    # ──────────────────────────────────────────────────────────────────
    # 사용자 요청 2026-05-10: 좌측 총괄 트리맵 폭을 현재의 60% 로 축소 (50%
    # → 30%) 하고 우측 12 개월 트리맵을 70% 로 확대.
    L, R = st.columns([3, 7])

    # 사용자 요청 2026-05-10: A(좌)·B(우) 색 스케일 통합 — B 의 월별 범위
    #   (= A 의 평균 범위보다 항상 넓음) 를 양쪽에 공통 적용해야 같은 값이
    #   같은 색으로 보임. 이전엔 각자 vmin/vmax 라 평균값이 A에서는 빨강
    #   이지만 B에서는 중간색으로 표시되는 불일치 발생.
    # 사용자 요청 2026-05-10 (재): tab10 전역 통합 — 외부에서 global vmax
    #   가 주어지면 그대로 사용. 그래야 fig23/24/25/27 과 detail A/B 가
    #   모두 같은 colorbar 스케일을 공유.
    if color_vmin is None or color_vmax is None:
        color_vmin, color_vmax = _monthly_per_well_daily_range(
            m, u, cluster=cluster, units_df=units_df,
            active_permits=active_permits,
        )

    # ── 좌측: 리·동별 squarified treemap (박스 면적 ∝ 농지면적, 색 = 이용량)
    #   사용자 요청 2026-05-10: 가로 막대 → ri_dual_zone 과 같은 사각형 트리맵.
    #   클러스터 헤더 ('구좌읍 4,496ha') + 박스 안 (리 이름 / n공 / 이용량).
    with L:
        agri_ha = ADMIN_AGRI_HA.get(cluster, 0)
        short_cluster = cluster.replace("제주시 ", "").replace("서귀포시 ", "")
        st.markdown(
            f'<p class="subsection-title">{short_cluster} {agri_ha:,}ha — '
            f'리·동별 트리맵</p>',
            unsafe_allow_html=True,
        )
        fig_tm = _build_cluster_ri_treemap(m, u, cluster=cluster,
                                           agri_ha=agri_ha, units_df=units_df,
                                           colorscale=colorscale,
                                           color_vmin=color_vmin,
                                           color_vmax=color_vmax,
                                           active_permits=active_permits)
        if fig_tm is None:
            st.caption("리·동 정보가 없거나 이용량이 0 입니다.")
        else:
            st.plotly_chart(fig_tm, use_container_width=True,
                            key=yr_chart_key,
                            config={"displayModeBar": False})

    # ── 우측: 12 개월 mini 트리맵 (3×4 subplot) — 좌측과 동일 배치, 색만 월별
    with R:
        short_cluster = cluster.replace("제주시 ", "").replace("서귀포시 ", "")
        st.markdown(
            f'<p class="subsection-title">{short_cluster} 월별 이용량 트리맵 '
            f'(1~12월 · 색=월 이용량)</p>',
            unsafe_allow_html=True,
        )
        fig_m = _build_cluster_monthly_treemaps(m, u, cluster=cluster,
                                                units_df=units_df,
                                                colorscale=colorscale,
                                                color_vmin=color_vmin,
                                                color_vmax=color_vmax,
                                                active_permits=active_permits)
        if fig_m is None:
            st.caption("월별 자료가 없거나 리·동 슬롯이 비었습니다.")
        else:
            st.plotly_chart(fig_m, use_container_width=True,
                            key=f"{yr_chart_key}_monthly",
                            config={"displayModeBar": False})


# ──────────────────────────────────────────────────────────────────
#  드릴다운 헬퍼 — 그림 24 (리·동 단위)
# ──────────────────────────────────────────────────────────────────
def _render_unit_detail(master: pd.DataFrame, usage: pd.DataFrame,
                        *, cluster: str, unit: str,
                        period_text: str,
                        units_df: pd.DataFrame | None = None,
                        active_permits: "set[str] | None" = None) -> None:
    """선택된 리·동의 세부 분석 패널 — 그림 24 클릭 드릴다운.

    units_df 가 주어지면 0공(MANUAL) unit 도 그 row 의 est_area_ha 를 활용.
    """
    st.markdown(
        '<hr style="margin:14px 0 10px;border:none;'
        'border-top:0.5px solid rgba(26,26,24,0.15);">',
        unsafe_allow_html=True,
    )

    head_l, head_r = st.columns([8, 2])
    with head_l:
        st.markdown(f"#### 📍 {cluster} · {unit} — 세부 분석")
        st.caption(f"분석 기간 **{period_text}**")
    with head_r:
        if st.button("선택 해제", key="tab10_fig24_clear",
                     use_container_width=True):
            for k in ("tab10_fig24_picked_idx",
                      "tab10_fig24_picked_cluster",
                      "tab10_fig24_picked_unit"):
                st.session_state.pop(k, None)
            # chart key 카운터 증가 → plotly selection state 리셋
            st.session_state["tab10_fig24_chart_v"] = (
                st.session_state.get("tab10_fig24_chart_v", 0) + 1
            )
            ag_well_helpers.fragment_rerun()

    m = master[(master["cluster"] == cluster) & (master["unit"] == unit)]
    u = usage[(usage["cluster"] == cluster) & (usage["unit"] == unit)]

    # 사용자 요청 2026-05-19: 분모 N 을 사용 보고 관정으로 한정.
    n_total = int(len(m))
    if active_permits is not None:
        n_wells = int(m["permit_no"].astype(str).isin(active_permits).sum())
    else:
        n_wells = n_total
    cluster_agri = ADMIN_AGRI_HA.get(cluster, 0)
    cluster_n_total = int((master["cluster"] == cluster).sum())
    if active_permits is not None:
        cluster_n = int(
            master.loc[master["cluster"] == cluster, "permit_no"]
            .astype(str).isin(active_permits).sum()
        )
    else:
        cluster_n = cluster_n_total

    # units_df 에서 est_area_ha lookup — 0공(MANUAL) unit 의 농지면적 보존
    est_area_lookup: float | None = None
    note_from_unit: str | None = None
    if units_df is not None:
        sub = units_df[(units_df["cluster"] == cluster)
                       & (units_df["unit"] == unit)]
        if not sub.empty:
            est_area_lookup = float(sub.iloc[0]["est_area_ha"])
            if int(sub.iloc[0]["n"]) == 0:
                note_from_unit = "인접 상류부 관정에서 농업용수 공급"

    # 0공 unit 분기 (m.empty + units_df 에 등록된 MANUAL row)
    if m.empty:
        if est_area_lookup is None:
            st.warning(f"{cluster} · {unit} 에 매핑된 관정이 없습니다.")
            return
        # MANUAL_NO_WELL_UNITS 항목 — 0공 농지 권역
        c1, c2, c3, c4 = st.columns(4)
        render_stat_card("관정 수", "0 공",
                         sub=note_from_unit or "관정 없음",
                         color="#888", container=c1)
        render_stat_card("추정 농지면적",
                         f"{est_area_lookup:,.0f} ha",
                         sub=f"클러스터 {cluster_agri:,} ha 기준",
                         color="#888", container=c2)
        render_stat_card("연평균 이용량", "—",
                         sub="이 unit 직속 관정 없음",
                         color="#888", container=c3)
        render_stat_card("관정당 연이용량", "—",
                         sub="—", color="#888", container=c4)
        st.info(
            f"📍 **{cluster} · {unit}** 은 직속 농업용 관정이 없어 "
            "이용량 추이 · 상위 관정 표는 표시하지 않습니다. "
            f"등록 사유: {note_from_unit or '인접 관정에서 공급'}."
        )
        return

    est_area = (est_area_lookup
                if est_area_lookup is not None
                else (cluster_agri * n_wells / cluster_n) if cluster_n else 0.0)

    has_volume = "volume_m3" in u.columns
    total_use = float(u["volume_m3"].sum()) if has_volume else 0.0
    n_year = max(int(u["year"].nunique()), 1) if not u.empty else 1
    annual_avg = total_use / n_year
    per_well = annual_avg / n_wells if n_wells else 0.0

    _unit_sub = (f"등록 {n_total}공 중 사용 {n_wells}공 · "
                 f"클러스터 사용 {cluster_n}공 중"
                 if n_wells != n_total
                 else f"클러스터 {cluster_n}공 중")
    c1, c2, c3, c4 = st.columns(4)
    render_stat_card("관정 수 (사용)", f"{n_wells:,} 공",
                     sub=_unit_sub,
                     color=theme.COLOR_TEXT_INFO, container=c1)
    render_stat_card("추정 농지면적",
                     f"{est_area:,.0f} ha",
                     sub=f"클러스터 {cluster_agri:,} ha 기준",
                     color=theme.COLOR_TEXT_INFO, container=c2)
    render_stat_card("연평균 이용량",
                     f"{annual_avg/1e6:,.2f} 백만㎥/년",
                     sub=f"{n_year}년 평균",
                     color=theme.COLOR_TEXT_INFO, container=c3)
    render_stat_card("관정당 연이용량",
                     f"{per_well:,.0f} ㎥/공·년",
                     color=theme.COLOR_TEXT_INFO, container=c4)

    if u.empty or not has_volume:
        st.info("이용량 데이터가 없어 추세·관정 표를 표시할 수 없습니다.")
        return

    yearly = (u.groupby("year")["volume_m3"].sum() / 1e6).reset_index()
    yearly.columns = ["year", "volume_M"]
    fig_yr = go.Figure(go.Bar(
        x=yearly["year"], y=yearly["volume_M"],
        marker_color=theme.COLOR_TEXT_INFO,
        hovertemplate="%{x}년 · %{y:,.2f} 백만㎥<extra></extra>",
    ))
    fig_yr.update_layout(
        height=240,
        plot_bgcolor="white", paper_bgcolor="white",
        margin=dict(l=20, r=20, t=10, b=20),
        xaxis_title="연도", yaxis_title="이용량 (백만㎥)",
        xaxis=dict(tickmode="linear", dtick=1),
        showlegend=False,
        font=dict(family="-apple-system, BlinkMacSystemFont, 'Segoe UI', "
                         "Roboto, sans-serif", color=theme.COLOR_TEXT_PRIMARY),
    )
    st.markdown(
        '<p class="subsection-title">연도별 이용량 추이</p>',
        unsafe_allow_html=True,
    )
    st.plotly_chart(fig_yr, use_container_width=True,
                    key="tab10_fig24_detail_yr",
                    config={"displayModeBar": False})

    st.markdown(
        '<p class="subsection-title">'
        '상위 관정 (관정당 연평균 이용량 기준 · 최대 10개)</p>',
        unsafe_allow_html=True,
    )
    top = (u.groupby("permit_no")["volume_m3"].sum() / n_year)
    top = top.sort_values(ascending=False).head(10).reset_index()
    top.columns = ["permit_no", "annual_avg_m3"]
    extra_cols = [c for c in ("well_id", "well_eup", "well_ri")
                  if c in m.columns]
    top = top.merge(m[["permit_no"] + extra_cols].drop_duplicates("permit_no"),
                    on="permit_no", how="left")
    top["연평균 (㎥/년)"] = top["annual_avg_m3"].round(0).astype("Int64")
    rename_map = {"permit_no": "허가번호", "well_id": "관정ID",
                  "well_eup": "읍·면·동", "well_ri": "리"}
    show_cols = ["permit_no"] + extra_cols + ["연평균 (㎥/년)"]
    show_df = top[show_cols].rename(columns=rename_map)
    st.dataframe(show_df, use_container_width=True, hide_index=True)


