# ==============================================================================
#  파일명: src/dashboard/tabs/tab23_ag_usage_map.py  —  Build 2.x
#  탭: ⑧-2 이용량 지도분석 (행정구역별 이용량 Choropleth + 월별 차트)
# ------------------------------------------------------------------------------
#  설계 (_작업지시서_탭8-2_이용량지도분석_FINAL.md 기준):
#    - 모집단: active=True AND 분석기간 사용≥1㎥ (휴지·폐공 제외)
#    - 1줄: 집계 단위 · 표시 방식 · 분석 기간(월 슬라이더 — int 기반)
#    - 2줄: 시 → 읍/면/동 → 리 (cascading, '제주시 동지역' 포함)
#    - KPI 카드 5개 (theme.render_period_kpi_card 재사용)
#    - 지도 1 (12개 NAME 폴리곤 choropleth · 클릭 → 읍/면 cascading 동기)
#    - 지도 2 (172 법정리명 폴리곤 choropleth · 클릭 → 리 cascading 동기)
#    - 차트 (1~12월 ㎥/관정/일 막대)
#    - fragment: 메인 render() 만 단일 @st.fragment (nested 금지)
# ==============================================================================
from __future__ import annotations

import streamlit as st

import config
from src.dashboard import ag_well_helpers, theme
from src.dashboard.quit_helper import quit_button
from src.dashboard.tabs._tab23_chart import render_monthly_chart
from src.dashboard.tabs._tab23_helpers import (
    _period_label,
    agg_usage_by_eup,
    # agg_usage_by_ri,  # P3-3 (2026-05-29): dead — agg_usage_by_ri_with_dong 만 사용
    agg_usage_by_ri_with_dong,
    build_filtered_usage,
    build_kpi_metrics,
    build_period_population,
    chart_monthly_per_well,
    count_excluded,
    load_master_active_normalized,
    render_ri_monthly_daily_grid,
    render_ri_monthly_map_grid,
)
from src.dashboard.tabs._tab23_plotly_map import (
    render_eup_plotly_choropleth,
    render_ri_plotly_choropleth,
)
from src.dashboard.tabs._tab23_widgets import render_top_controls


_fragment_rerun = ag_well_helpers.fragment_rerun


def _row_pair_tight_css() -> None:
    """tab8/tab7 의 1줄-2줄 사이 압축 CSS — 동일 패턴 (간격 통일).

    memory: feedback_preserve_filter_spacing — row-pair-tight 블록 절대 수정 금지.
    아래 CSS 는 tab13_ag_quality.py 의 줄간격 보호 블록과 동일 구조.
    """
    st.markdown("""
    <style>
    [data-testid="stMarkdown"]:has(.row-pair-tight),
    [data-testid="stElementContainer"]:has(.row-pair-tight) {
        height: 0 !important;
        min-height: 0 !important;
        max-height: 0 !important;
        margin: -0.8rem 0 0 0 !important;
        padding: 0 !important;
        line-height: 0 !important;
        overflow: hidden !important;
    }
    [data-testid="stMarkdown"]:has(.row-pair-tight) + [data-testid="stHorizontalBlock"],
    [data-testid="stMarkdown"]:has(.row-pair-tight) + [data-testid="stMarkdown"],
    [data-testid="stElementContainer"]:has(.row-pair-tight) + [data-testid="stHorizontalBlock"],
    [data-testid="stElementContainer"]:has(.row-pair-tight) + [data-testid="stElementContainer"],
    [data-testid="stElementContainer"]:has(.row-pair-tight) + [data-testid="stMarkdown"] {
        margin-top: -0.5rem !important;
    }
    [data-testid="stMarkdown"]:has(.row-pair-tight) + [data-testid="stHorizontalBlock"] [data-testid="stWidgetLabel"],
    [data-testid="stElementContainer"]:has(.row-pair-tight) + [data-testid="stHorizontalBlock"] [data-testid="stWidgetLabel"],
    [data-testid="stElementContainer"]:has(.row-pair-tight) + [data-testid="stElementContainer"] [data-testid="stWidgetLabel"],
    [data-testid="stMarkdown"]:has(.row-pair-tight) ~ [data-testid="stHorizontalBlock"]:first-of-type [data-testid="stWidgetLabel"] {
        margin-top: 0 !important;
        padding-top: 0 !important;
    }
    </style>
    """, unsafe_allow_html=True)


@st.fragment
def render() -> None:
    # ── 헤더 ──
    _t, _q = st.columns([10, 1])
    with _t:
        st.markdown(
            '<p class="tab-title" style="margin:0;">23.이용량 공간분석</p>',
            unsafe_allow_html=True,
        )
    with _q:
        quit_button("quit_in_tab8_2")

    # 데이터 사전 점검
    master = load_master_active_normalized()
    if master.empty:
        st.warning("master.csv 자료를 찾을 수 없습니다.")
        return
    if not config.RI_BOUNDARY_GEOJSON.exists() or not config.EUP_BOUNDARY_GEOJSON.exists():
        st.error(
            "행정구역 경계 GeoJSON 파일이 없습니다. "
            "Phase 0 사전 변환 (shp → geojson) 을 먼저 실행해 주세요."
        )
        return

    # ── 줄간격 CSS + 1줄·2줄 컨트롤 ──
    _row_pair_tight_css()
    controls = render_top_controls()

    period_lo = controls["period_lo"]
    period_hi = controls["period_hi"]
    loc_sel   = controls["loc_sel"]
    mode      = controls["mode"]

    # ── 모집단 + 필터 적용된 long DF ──
    pop_full = build_period_population(period_lo, period_hi)
    df_long = build_filtered_usage(period_lo, period_hi, loc_sel)
    # pop 도 동일 필터 적용 — KPI 분모·집계용
    from src.dashboard.tabs._tab23_helpers import _apply_loc_sel
    pop_f = _apply_loc_sel(pop_full, loc_sel)

    # ── KPI 카드 5개 ──
    kpi = build_kpi_metrics(df_long, pop_f, period_lo, period_hi)
    excl = count_excluded(period_lo, period_hi)
    _render_kpi_cards(kpi, excl, period_lo, period_hi)

    # ── 시각화: 읍·면 행정구역 경계 (folium choropleth) ──
    # 2026-05-20 사용자 요청: GIS_Map shape 파일의 실제 행정구역 폴리곤 지도.
    # 단계적 접근 — 우선 읍·면만 미니멀 버전으로 표시, 작동 확인 후 리·동 추가.
    agg_eup = agg_usage_by_eup(df_long, pop_f, period_lo, period_hi, mode=mode)

    # ── 읍·면 헤더 + 토글 (같은 줄, 우측에 단정하게) ──
    c_hdr_eup, c_tog_eup = st.columns([3, 1])
    with c_hdr_eup:
        st.markdown(
            '<h4 style="margin:1rem 0 0.5rem 0;">'
            '행정구역별 현황 · 읍·면</h4>',
            unsafe_allow_html=True,
        )
    with c_tog_eup:
        show_wells_eup = st.checkbox(
            "📍 관정 위치 표시", key="t8_2_show_wells_eup",
            help="각 관정을 점으로 표시 — 색상은 일사용량 (옆 컬러바와 동일)",
        )
    # 2026-05-20 사용자 요청: 분석기간 부분 폰트 2단계 ↑ (13→16)
    st.markdown(
        f'<div style="font-size:13px;color:var(--color-text-secondary);'
        f'margin-bottom:8px;">분석기간: '
        f'<b style="font-size:16px;color:var(--color-text-info);">'
        f'{_period_label(period_lo, period_hi)}</b> · '
        f'색 = 관정당 일 사용량 (㎥/공·일) 6단계 (낮음 → 진함)</div>',
        unsafe_allow_html=True,
    )
    render_eup_plotly_choropleth(
        agg_eup, mode=mode, height=780,
        show_wells=show_wells_eup,
        master_df=pop_f, df_long=df_long,
        period_lo=period_lo, period_hi=period_hi,
    )

    # ── 리·동 헤더 + 토글 (읍·면과 동일 패턴) ──
    c_hdr_ri, c_tog_ri = st.columns([3, 1])
    with c_hdr_ri:
        st.markdown(
            '<h4 style="margin:1.2rem 0 0.5rem 0;">리·동별 현황</h4>',
            unsafe_allow_html=True,
        )
    with c_tog_ri:
        show_wells_ri = st.checkbox(
            "📍 관정 위치 표시", key="t8_2_show_wells_ri",
            help="각 관정을 점으로 표시 — 색상은 일사용량 (옆 컬러바와 동일)",
        )
    st.markdown(
        f'<div style="font-size:13px;color:var(--color-text-secondary);'
        f'margin-bottom:8px;">분석기간: '
        f'<b style="font-size:16px;color:var(--color-text-info);">'
        f'{_period_label(period_lo, period_hi)}</b> · '
        f'172개 법정리·동 (동지역 39개 포함) · '
        f'옅은 회색 = 분석기간 자료 없는 리·동</div>',
        unsafe_allow_html=True,
    )
    agg_ri_full = agg_usage_by_ri_with_dong(
        df_long, pop_f, period_lo, period_hi, mode=mode,
    )
    render_ri_plotly_choropleth(
        agg_ri_full, mode=mode, height=840,
        show_wells=show_wells_ri,
        master_df=pop_f, df_long=df_long,
        period_lo=period_lo, period_hi=period_hi,
    )

    # ── 월별 12장 (지도 중심) · 리경계 shape 기반 small multiples ──
    # 사용자 요청 2026-05-22: dual-zone 추상 박스 대신 실제 리경계 polygon 으로.
    #   - 분석기간 < 24개월: 가장 많이 걸친 년도의 1~12월 (실측)
    #   - 분석기간 ≥ 24개월: 분석기간에 걸친 년도들의 월별 평균
    st.markdown(
        '<h4 style="margin:1.6rem 0 0.4rem 0;">월별 현황 · 리·동 12개월</h4>',
        unsafe_allow_html=True,
    )
    st.markdown(
        '<div style="font-size:13px;color:var(--color-text-secondary);'
        'margin-bottom:6px;">리경계 shape 기반 4행 3열 · '
        '색 = 관정당 일 사용량 (㎥/공·일, 0~1600 절대 도메인) · '
        '12개 월 패널이 같은 색바 공유 → 월별 공간 강도 비교</div>',
        unsafe_allow_html=True,
    )
    try:
        # 사용자 요청 2026-05-22 v2: figure 너비를 streamlit 컨테이너 폭의
        # ~2배로 명시 — 12개 패널이 화면 가로로 길게 펴짐. use_container_width
        # =False 와 함께 사용 (True 면 width 인자 무시됨).
        fig_ri_monthly, _monthly_label = render_ri_monthly_map_grid(
            pop_f, df_long, period_lo, period_hi,
            height=1500, width=2400,
        )
        if fig_ri_monthly is None:
            st.warning(
                "리경계 GeoJSON 을 로드할 수 없어 월별 12장 지도를 표시할 수 없습니다. "
                "데이터 관리 탭에서 shape 파일을 점검해 주세요."
            )
        else:
            st.plotly_chart(
                fig_ri_monthly, use_container_width=False,
                key="t8_2_ri_monthly_map_grid",
                config={"displayModeBar": False},
            )
    except Exception as e:
        st.warning(f"월별 12장 지도 생성 실패: {e}")
        # 폴백 — dual-zone 추상 박스
        try:
            fig_dual, _ = render_ri_monthly_daily_grid(
                pop_f, df_long, period_lo, period_hi, height=1200,
            )
            st.plotly_chart(
                fig_dual, use_container_width=True,
                key="t8_2_ri_monthly_dual_fallback",
                config={"displayModeBar": False},
            )
        except Exception:
            pass

    # ── 월별 12개 막대 (전체 평균) — 사용자 요청 2026-05-22: 맨 밑 ──
    st.markdown(
        '<h4 style="margin:1.4rem 0 0.5rem 0;">월별 관정당 일 사용량 (1월 ~ 12월)</h4>',
        unsafe_allow_html=True,
    )
    chart_data = chart_monthly_per_well(df_long, pop_f, period_lo, period_hi)
    render_monthly_chart(chart_data, _period_label(period_lo, period_hi))

    # ── 푸터 안내 ──
    st.markdown(
        f'<div style="font-size:12px;color:var(--color-text-tertiary);'
        f'margin-top:0.8rem;text-align:right;">'
        f'분석기간 휴지 {excl["dormant"]}공 · 폐공 {excl["inactive"]}공 은 모집단·합계에서 제외됨'
        f'</div>',
        unsafe_allow_html=True,
    )


# ==============================================================================
#  ■ KPI 카드 5개 — theme.render_period_kpi_card 재사용
# ==============================================================================
def _render_kpi_cards(kpi: dict, excl: dict, period_lo: int, period_hi: int) -> None:
    """5개 KPI: 총 관정 · 총 사용량 · 월 평균 · 일 평균 · Top1 리."""
    from src.dashboard.tabs._tab23_helpers import _fmt_m3
    cols = st.columns(5)
    accent_colors = [
        "#185fa5", "#C65911", "#548235", "#305496", "#1D9E75",
    ]
    cards = [
        # 농업용관정 = 폐공되지 않고 살아있는(active) 관정 — 휴지(미사용) 포함,
        # 폐공만 제외 (사용자 요청 2026-05-27). 마지막연도 기준 운영중 관정 전부.
        ("농업용관정",  f"{excl['active_total']:,}공",
         f"폐공 {excl['inactive']}공 제외 · 휴지 포함"),
        ("총 사용량",   f"{_fmt_m3(kpi['total_m3'])} ㎥",
         f"분석기간 누적 · {_period_label(period_lo, period_hi)}"),
        ("월 평균",     f"{_fmt_m3(kpi['monthly_avg'])} ㎥/월",
         f"분석 {kpi['months']}개월"),
        ("일 평균",     f"{_fmt_m3(kpi['daily_avg'])} ㎥/일",
         f"분석 {kpi['days']}일"),
        ("Top1 리·동", f"{kpi['top1_ri'] or '-'}",
         f"{_fmt_m3(kpi['top1_val'])} ㎥" if kpi['top1_ri'] else "자료 없음"),
    ]
    for i, (col, (title, big, sub_text)) in enumerate(zip(cols, cards)):
        if hasattr(theme, "render_period_kpi_card"):
            theme.render_period_kpi_card(
                title="",
                groups=[(title, big, sub_text)],
                accent=accent_colors[i],
                is_base=True,
                container=col,
            )
        else:
            # 폴백 — theme 헬퍼 부재 시 단순 마크다운
            with col:
                st.markdown(
                    f'<div style="border-left:3px solid {accent_colors[i]};'
                    f'background:rgba(0,0,0,0.04);padding:0.55rem 0.9rem 0.7rem;'
                    f'border-radius:8px;">'
                    f'<div style="font-size:14px;color:#1a1a18;font-weight:600;">{title}</div>'
                    f'<div style="font-size:21px;color:{accent_colors[i]};font-weight:700;">{big}</div>'
                    f'<div style="font-size:12px;color:#5f5e5a;">{sub_text}</div>'
                    f'</div>',
                    unsafe_allow_html=True,
                )
