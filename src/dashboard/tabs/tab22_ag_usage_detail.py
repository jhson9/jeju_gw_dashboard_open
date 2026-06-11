# ==============================================================================
#  파일명: src/dashboard/tabs/tab22_ag_usage_detail.py  -  Build 3.0
#  탭: ⑥-2 이용량 세부 분석 (V6 dual-zone × 면적 비례 squarify 5종)
#  Changelog:
#    2026-05-07 (Build 1.0): 신규 추가
#    2026-05-07 (Build 1.1): 트리맵 4가지 변경 (다이버징 + 연간 합계 등)
#    2026-05-08 (Build 2.0): 기존 트리맵·히트맵·4-패널·드릴다운 전부 제거,
#                            V6 5개 그림(그림 23·24·25·26·27)으로 재구성.
#                            연도 슬라이더만 적용, cascading 필터는 미반영.
#    2026-05-08 (Build 3.0): 그림 24·25·26·27 모두 src/ plotly 모듈로 이전.
#                            fig_v6_codes / streamlit_adapter 의존 완전 제거.
#                            그림 24·25 클릭 드릴다운 추가.
# ------------------------------------------------------------------------------
#  설계 원칙:
#   - 그림 23~27 모두 plotly Figure (인터랙티브) — st.plotly_chart 임베드.
#   - 그림 23·24·25 = 클릭 드릴다운 (selection_mode=points).
#   - render() 전체를 @st.fragment 로 감싸 탭 점프 차단 (streamlit 1.47.1 폴백).
#   - aggregate_units 등 무거운 계산은 동일 rerun 내에서 1회만 수행.
# ==============================================================================

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from src.analysis import ag_well_loader, ag_well_metrics
from src.dashboard import ag_well_helpers, theme
from src.dashboard.quit_helper import quit_button
from src.dashboard.figures.admin_dual_zone import (
    METRICS as ADMIN_METRICS,
    render as render_admin_dual_zone,
)
from src.dashboard.figures._dual_zone_common.color import DAILY_USAGE_VMAX
from src.dashboard.figures.admin_dual_zone.constants import (
    ADMIN_AGRI_HA,
    JEJU_CLUSTERS,
    SEOG_CLUSTERS,
)
from src.dashboard.figures.ri_dual_zone import (
    RI_METRICS,
    render_compare,
    render_ri,
)
from src.dashboard.figures.ri_dual_zone.data import (
    _normalize_master_admin,
    aggregate_units,
)
from src.dashboard.theme import render_stat_card

# 그림 27 (월별 12장) — 팀 C 산출물
try:
    from src.dashboard.figures.ri_dual_zone.monthly import render_monthly
    _HAS_MONTHLY = True
except Exception:  # pragma: no cover
    _HAS_MONTHLY = False


# ──────────────────────────────────────────────────────────────────
#  fragment 데코레이터 폴백 (streamlit 1.47.1 환경 보호)
# ──────────────────────────────────────────────────────────────────
try:
    _fragment = st.fragment  # type: ignore[attr-defined]
except AttributeError:  # pragma: no cover
    def _fragment(func):
        return func


from src.dashboard.tabs._tab22_helpers import (   # noqa: E402
    _section,
    _read_plotly_pick,
    _pick_first,
    _render_admin_cluster_detail,
    _render_unit_detail,
)


@_fragment
def render(asos_df=None, periods=None) -> None:
    """22.이용량 경향분석 — V6 dual-zone 5종."""
    _ = asos_df, periods  # 시그니처 호환

    # (2026-06-11 v2) 탭 제목 제거 — 하위탭 pill 문구와 중복 (사용자 요청)

    df_master = ag_well_loader.load_master(active_only=True)
    df_usage = ag_well_loader.load_usage_long()
    if df_usage is None or df_usage.empty:
        st.warning("이용량 자료를 찾을 수 없습니다 (usage/usage_montly_*.csv).")
        return
    if df_master is None or df_master.empty:
        st.error("마스터 데이터를 로드하지 못했습니다.")
        return

    # ── 컨트롤: 한 행 = [색 지표 selectbox 1/5] + [연도 슬라이더 4/5]
    #   사용자 요청 2026-05-09: 색 지표를 탭 상단 (행정구역+리·동 둘 다 적용)
    #   으로 이동 + 6종으로 확장 (이용량 합계 / 연평균 / 관정당 연·월·일 /
    #   단위면적 강도). 공통 키만 노출 → fig23·fig24 같은 지표로 색칠.
    _SHARED_METRIC_KEYS = [
        "total_period",       # 이용량 합계
        "annual",             # 연 평균 이용량 합계
        "per_well_annual",    # 관정당 연 이용량
        "per_well_monthly",   # 관정당 월 이용량
        "per_well_daily",     # 관정당 일 이용량
        "intensity_ha",       # 단위 면적 강도 (= 연평균 이용량 ÷ 농지면적)
    ]
    # 사용자 요청 2026-05-09: default 를 '관정당 일 이용량'(per_well_daily) 로.
    # migration: 단일 sentinel 가드로 fragment hot path 비용 최소화.
    # 첫 진입 후에는 sentinel 1개만 lookup (조기 단락).
    if not st.session_state.get("_tab10_metric_default_v2"):
        st.session_state["tab10_metric"] = "per_well_daily"
        st.session_state["_tab10_metric_default_v2"] = True

    yr_min = int(df_usage["year"].min())
    yr_max = int(df_usage["year"].max())

    c_metric, c_year = st.columns([1, 4])
    with c_metric:
        metric_key = st.selectbox(
            "색에 매핑할 지표",
            options=_SHARED_METRIC_KEYS,
            format_func=lambda k: ADMIN_METRICS[k].label,
            key="tab10_metric",
            help=" · ".join(f"{ADMIN_METRICS[k].label}: "
                            f"{ADMIN_METRICS[k].description}"
                            for k in _SHARED_METRIC_KEYS),
        )
    with c_year:
        yr_range = ag_well_helpers.year_slider(
            yr_min, yr_max, key="tab10_year_range_v6"
        )
    year_tuple = (int(yr_range[0]), int(yr_range[1]))

    n_yr = year_tuple[1] - year_tuple[0] + 1
    period_text = (
        f"{year_tuple[0]}~{year_tuple[1]} 평균 ({n_yr}년)"
        if n_yr > 1
        else f"{year_tuple[0]}년"
    )
    st.caption(f"분석 기간: **{period_text}**  ·  V6 5개 그림 산출")

    st.markdown(
        '<hr style="margin:6px 0 14px;border:none;'
        'border-top:0.5px solid rgba(26,26,24,0.15);">',
        unsafe_allow_html=True,
    )

    # ── 공용 데이터 — 한 번 계산해 24·25·26·27 모두 재사용
    m_normed = _normalize_master_admin(df_master)
    u_filtered = df_usage[
        (df_usage["year"] >= year_tuple[0])
        & (df_usage["year"] <= year_tuple[1])
    ]
    if u_filtered.empty:
        st.warning(f"{period_text} 구간에 이용량 자료가 없습니다.")
        return
    u_with_cluster = u_filtered.merge(
        m_normed[["permit_no", "cluster", "unit"]],
        on="permit_no", how="left",
    )
    # 사용자 요청 2026-05-19: 분석 기간 내 이용량>0 관정 집합을 한 번만
    # 계산해 fig23/24/27 + KPI 카드 모두에 전파 → "관정당" 분모 통일.
    active_permits = ag_well_metrics.active_user_permits(u_with_cluster)
    units_df = aggregate_units(m_normed, u_with_cluster,
                               active_permits=active_permits)

    # 사용자 요청 2026-05-10: tab10 colorbar 전역 통일 — 모든 그림이 같은 vmin/
    #   vmax 를 공유해야 같은 색이 같은 값을 의미.
    # 사용자 요청 2026-05-15: per_well_daily 의 vmax 를 데이터 기반(_GLOBAL_PWD_MAX)
    #   에서 절대값 DAILY_USAGE_VMAX(=1600) 로 변경. DAILY_USAGE_COLORSCALE 의 stop
    #   (0=하늘, 800=남색, 1200=노랑, 1600=빨강) 이 의미를 가지려면 cmax 가 항상
    #   1600 으로 고정되어야 함. 데이터 max 가 1600 을 넘으면 plotly 의 cmax clip
    #   으로 빨강 saturation. 다른 metric 은 None → renderer 가 자체 범위로 폴백.
    _UNIFY_COLOR = (metric_key == "per_well_daily")
    _color_vmin = 0.0 if _UNIFY_COLOR else None
    _color_vmax = DAILY_USAGE_VMAX if _UNIFY_COLOR else None

    # ── 그림 23 — 행정 구역 dual-zone (Plotly 인터랙티브 + 클릭 드릴다운)
    _fig23_period = (
        f"{year_tuple[0]}년"
        if year_tuple[0] == year_tuple[1]
        else f"{year_tuple[0]}~{year_tuple[1]}년 합계"
    )
    _section("행정구역별 현황 · 읍·면·동을 농지면적 비례 박스")

    # ── 사용자 요청 2026-05-10: plotly 박스 클릭이 일부 환경에서 무반응
    #   → selectbox 우회 경로 + default "제주시 구좌읍". plotly 클릭은
    #   보조 경로로 유지 (잡히면 selectbox 동기화).
    _ALL_CLUSTERS = list(JEJU_CLUSTERS) + list(SEOG_CLUSTERS)
    _DEFAULT_CLUSTER = "제주시 구좌읍"
    if st.session_state.get("tab10_fig23_picked") not in _ALL_CLUSTERS:
        st.session_state["tab10_fig23_picked"] = _DEFAULT_CLUSTER

    try:
        picked_23 = st.session_state["tab10_fig23_picked"]
        fig23 = render_admin_dual_zone(
            m_normed, u_with_cluster,
            metric_key=metric_key,
            period_label=_fig23_period,
            selected_cluster=picked_23,
            color_vmin=_color_vmin,
            color_vmax=_color_vmax,
            active_permits=active_permits,
        )
        _v23 = st.session_state.get("tab10_fig23_chart_v", 0)
        event23 = st.plotly_chart(
            fig23, use_container_width=True,
            key=f"tab10_fig23_chart_{_v23}",
            on_select="rerun",
            selection_mode=("points",),
            config={"displayModeBar": False},
        )

        # 1) plotly 박스 클릭 (보조 경로) — 잡히면 selectbox 와 동기화
        new_pick_23 = _pick_first(_read_plotly_pick(event23))
        if new_pick_23 and new_pick_23 in _ALL_CLUSTERS \
                and new_pick_23 != picked_23:
            st.session_state["tab10_fig23_picked"] = new_pick_23
            ag_well_helpers.fragment_rerun()

        # 2) detail 패널 — picked 는 default 보장되어 항상 표시.
        #    사용자 요청 2026-05-10: 기존 fig23 위쪽 standalone selectbox 제거,
        #    detail 헤더 바로 아래 인라인 selectbox 로 이동 (cluster_options 전달).
        picked_23 = st.session_state["tab10_fig23_picked"]
        _render_admin_cluster_detail(
            m_normed, u_with_cluster,
            cluster=picked_23,
            period_text=_fig23_period,
            clear_btn_key="tab10_fig23_clear",
            clear_state_key="tab10_fig23_picked",
            yr_chart_key="tab10_fig23_detail_yr",
            chart_version_key="tab10_fig23_chart_v",
            units_df=units_df,
            colorscale=ADMIN_METRICS[metric_key].colorscale,
            cluster_options=_ALL_CLUSTERS,
            color_vmin=_color_vmin,
            color_vmax=_color_vmax,
            active_permits=active_permits,
        )
    except Exception as e:
        st.error(f"그림 23 생성 실패: {e}")

    st.markdown("&nbsp;", unsafe_allow_html=True)

    # ── 그림 24 — 리·동 dual-zone (사용자 핵심 + 클릭 드릴다운)
    #   사용자 요청 2026-05-09: 자체 selectbox 제거 — 탭 상단 통합 metric_key
    #   사용. 색 지표는 fig23 과 같은 값으로 일관.
    _section(
        "리·동별 현황",
        "1공 이상 리·동의 사각형 트리맵 (동지역은 농지 50ha 이상). "
        "박스 면적 ∝ 추정 농지면적, 색 = 위 통합 지표. "
        "회색 빗금 박스는 관정이 없으나 인접 상류부에서 공급되는 "
        "농지(예: 하도리). 박스를 클릭하면 세부 분석이 표시됩니다.",
    )

    try:
        picked_idx_24 = st.session_state.get("tab10_fig24_picked_idx")
        fig24 = render_ri(
            m_normed, u_with_cluster, units_df,
            metric_key=metric_key,
            period_label=_fig23_period,
            selected_unit_idx=picked_idx_24,
            color_vmin=_color_vmin,
            color_vmax=_color_vmax,
            active_permits=active_permits,
        )
        _v24 = st.session_state.get("tab10_fig24_chart_v", 0)
        event24 = st.plotly_chart(
            fig24, use_container_width=True,
            key=f"tab10_fig24_chart_{_v24}",
            on_select="rerun",
            selection_mode=("points",),
            config={"displayModeBar": False},
        )

        cd24 = _read_plotly_pick(event24)
        # cd24 는 [cluster, unit, idx] (3-tuple)
        if (cd24 is not None
                and isinstance(cd24, (list, tuple))
                and len(cd24) >= 3):
            new_idx = int(cd24[2])
            # picked_idx_24 가 None 이거나 다른 idx 일 때만 업데이트 → idx=0 stale 방지
            if picked_idx_24 is None or new_idx != picked_idx_24:
                st.session_state["tab10_fig24_picked_idx"] = new_idx
                st.session_state["tab10_fig24_picked_cluster"] = str(cd24[0])
                st.session_state["tab10_fig24_picked_unit"] = str(cd24[1])
                ag_well_helpers.fragment_rerun()

        picked_idx_24 = st.session_state.get("tab10_fig24_picked_idx")
        if picked_idx_24 is not None:
            _render_unit_detail(
                m_normed, u_with_cluster,
                cluster=st.session_state.get("tab10_fig24_picked_cluster", ""),
                unit=st.session_state.get("tab10_fig24_picked_unit", ""),
                period_text=_fig23_period,
                units_df=units_df,
                active_permits=active_permits,
            )
        else:
            st.info(
                "📍 박스를 클릭하면 해당 리·동 세부 분석이 표시됩니다."
            )
    except Exception as e:
        st.error(f"그림 24 생성 실패: {e}")

    st.markdown("&nbsp;", unsafe_allow_html=True)

    # ── 그림 25 — 전체 vs 200m이하 비교 (Plotly + 클릭 드릴다운)
    _section(
        "사각형 비교 · 전체 농지 vs 200m 이하",
        "좌·우 동일 색 스케일. 200m 이하 기준에서 박스가 작아지면 "
        "중산간 비중이 큰 행정구역. 박스를 클릭하면 세부 분석이 표시됩니다.",
    )

    try:
        picked_25 = st.session_state.get("tab10_fig25_picked")
        # 사용자 요청 2026-05-10: fig25 는 metric=intensity_ha (㎥/ha·년) 으로
        #   per_well_daily 와 단위가 달라 공통 vmax 적용 시 전부 saturate 됨.
        #   override 미전달 → 자체 5/95 백분위수 범위로 색칠.
        fig25 = render_compare(
            m_normed, u_with_cluster,
            period_label=_fig23_period,
            selected_cluster=picked_25,
            active_permits=active_permits,
        )
        _v25 = st.session_state.get("tab10_fig25_chart_v", 0)
        event25 = st.plotly_chart(
            fig25, use_container_width=True,
            key=f"tab10_fig25_chart_{_v25}",
            on_select="rerun",
            selection_mode=("points",),
            config={"displayModeBar": False},
        )

        cd25 = _read_plotly_pick(event25)
        # cd25 는 [cluster, panel_id]
        if (cd25 is not None
                and isinstance(cd25, (list, tuple))
                and len(cd25) >= 1):
            new_cluster = str(cd25[0])
            if new_cluster != picked_25:
                st.session_state["tab10_fig25_picked"] = new_cluster
                ag_well_helpers.fragment_rerun()

        picked_25 = st.session_state.get("tab10_fig25_picked")
        if picked_25:
            _render_admin_cluster_detail(
                m_normed, u_with_cluster,
                cluster=picked_25,
                period_text=_fig23_period,
                units_df=units_df,
                colorscale=ADMIN_METRICS[metric_key].colorscale,
                clear_btn_key="tab10_fig25_clear",
                clear_state_key="tab10_fig25_picked",
                yr_chart_key="tab10_fig25_detail_yr",
                chart_version_key="tab10_fig25_chart_v",
                color_vmin=_color_vmin,
                color_vmax=_color_vmax,
            )
        else:
            st.info(
                "📍 위 비교 박스 중 하나를 클릭하면 "
                "해당 클러스터 세부 분석이 여기에 표시됩니다."
            )
    except Exception as e:
        st.error(f"그림 25 생성 실패: {e}")

    st.markdown("&nbsp;", unsafe_allow_html=True)

    # ── 그림 26 (통합 현황판) 사용자 요청 2026-05-10 으로 삭제 — 그림 24
    #   '리·동별 현황'과 정보 중복.

    # ── 그림 27 — 월별 12장 small multiples (팀 C 산출물)
    _section(
        "월별 현황 · 12개월 Dual-Zone",
        "4 분기 행 배열, 동일 색 스케일(0~48000 ㎥/공·월 = 일 1600×30 절대 도메인)·동일 배치. "
        "색 = 관정당 월 사용량, 호버는 일 단위 환산(㎥/공·일)으로 8-2 탭과 통일. "
        "패널 제목 = 평년 월강수량.",
    )

    if not _HAS_MONTHLY:
        st.info(
            "그림 27 (월별 12장) 모듈을 아직 사용할 수 없습니다. "
            "monthly.py 모듈이 준비되면 자동으로 표시됩니다."
        )
    else:
        try:
            # 사용자 요청 2026-05-10: fig27 은 metric=per_well_monthly (㎥/공·월)
            #   로 per_well_daily 와 단위가 달라 공통 vmax 적용 시 전부 saturate.
            #   override 미전달 → 자체 0~95% 범위로 색칠.
            fig27 = render_monthly(
                m_normed, u_with_cluster, units_df,
                period_label=_fig23_period,
                active_permits=active_permits,
            )
            st.plotly_chart(
                fig27, use_container_width=True,
                key="tab10_fig27_chart",
                config={"displayModeBar": False},
            )
        except Exception as e:
            st.error(f"그림 27 생성 실패: {e}")
