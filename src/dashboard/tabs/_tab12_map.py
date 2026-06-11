# ==============================================================================
#  파일명: src/dashboard/tabs/_tab12_map.py
#  6 이용량 분석 탭 - 이용량 지도 + 월별 이용량 지도
#
#  Source 분리: tab12_ag_usage.py 2311줄 -> 그룹별 분리 3단계 (2026-05-09).
#    - _render_usage_map         : 6단계 그라디언트 마커 지도
#    - _render_monthly_usage_map : 월별 이용량 지도 (연/월 선택)
#
#  외부 사용처: tab12_ag_usage.py 내부 전용.
#  순환 회피: _render_well_selection_bar / _render_well_detail 는 lazy import.
# ==============================================================================
from __future__ import annotations

import calendar

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from streamlit_folium import st_folium

import config
from src.analysis import ag_well_loader, ag_well_metrics, anomaly_detection
from src.dashboard import ag_well_helpers, theme
from src.dashboard.tabs._tab12_helpers import (
    _DEFAULT_MAP_CENTER,
    _DEFAULT_MAP_ZOOM,
)


_fragment_rerun = ag_well_helpers.fragment_rerun


def _render_usage_map(
    df_master_f: pd.DataFrame,
    merged: pd.DataFrame,
    n_days_in_period: int,
) -> None:
    """필터링된 관정 마커 — 이용량 합계에 마커 크기·톤 비례.

    동작:
      - 줌·중심 보존: st_folium 의 'zoom' / 'center' 반환값을 session_state 에
        저장 → 다음 rerun 에서 그 값으로 마운트. 마커 클릭·필터 변경 등의
        rerun 후에도 사용자가 보던 줌 위치 유지.
      - 마커 클릭 즉시 반영: session_state 갱신 직후 fragment-only rerun 으로
        새 sel 을 그림 → 빨간 강조 원과 아래 분석표가 동시에 갱신.
    """
    by_well = (
        merged.groupby("permit_no", dropna=False)["volume_m3"]
              .sum().reset_index()
    )
    by_well["daily_avg"] = (
        by_well["volume_m3"] / n_days_in_period if n_days_in_period else 0
    )

    sel = st.session_state.get("usage_selected_permit")

    # 관정 선택 시 그 관정 중심으로 zoom 12 (읍/면/동 사이즈) — fingerprint 패턴.
    # 마커 클릭·텍스트 검색 어느 경로든 sel 이 갱신되면 1회 발동.
    ag_well_helpers.maybe_recenter_to_selected_well(
        sel, df_master_f,
        fingerprint_key="_usage_centered_permit",
        center_key="usage_map_center",
        zoom_key="usage_map_zoom",
    )

    saved_zoom = st.session_state.get("usage_map_zoom", _DEFAULT_MAP_ZOOM)
    saved_center = st.session_state.get("usage_map_center", _DEFAULT_MAP_CENTER)

    m = ag_well_helpers.build_usage_map(
        df_master_f, by_well, selected_permit=sel,
        zoom=saved_zoom, center=tuple(saved_center),
    )
    # ── 지도 높이 고정 (Build 2.3, 흰 깜박임/클릭 race 차단):
    # 이전엔 sel 유무에 따라 430/780 토글 → height props 변경 → iframe
    # ResizeObserver → Leaflet click 큐 비움 → 다음 클릭 무반응 + 흰색
    # 깜박임 유발. height 를 고정해 ResizeObserver 트리거를 원천 차단.
    # 사용자는 분석표를 보려면 아래로 스크롤 (tab6/tab8 와 같은 정책).
    map_h = 800  # 사용자 요청 2026-05-09: 화면의 80% 수준
    click = st_folium(
        m, width=None, height=map_h,
        # 사용자 요청 (2026-05-16 v15): zoom/center 제거 — 흰색 깜빡임 차단.
        returned_objects=[
            "last_object_clicked_tooltip",
            "last_object_clicked_popup",
        ],
        key="usage_map",
    )

    if click:
        # ── 줌·중심 보존 — 부동소수점 quantization (tab6 패턴):
        # zoom 정수, center 소수 4자리 (≈11m 분해능) 로 round 하여 미세
        # 변동(33.38231… vs 33.38231042) 이 props identity 변경을 일으켜
        # iframe 재렌더로 흰 깜박임을 유발하는 race 를 차단. rerun 자체는
        # 일으키지 않음 — 사용자 줌·드래그 동작은 그대로 보존.
        z = click.get("zoom")
        c = click.get("center")
        if z is not None:
            try:
                st.session_state["usage_map_zoom"] = round(float(z) * 2) / 2
            except (TypeError, ValueError):
                pass
        if isinstance(c, dict) and "lat" in c and "lng" in c:
            try:
                st.session_state["usage_map_center"] = (
                    round(float(c["lat"]), 4), round(float(c["lng"]), 4),
                )
            except (TypeError, ValueError):
                pass

        # ── 마커 click → 관정 선택
        clicked_permit = ag_well_helpers.lookup_permit_by_well_id(
            click.get("last_object_clicked_tooltip"), df_master_f
        )
        if not clicked_permit:
            clicked_permit = ag_well_helpers.parse_clicked_popup(
                click.get("last_object_clicked_popup")
            )
        if clicked_permit and clicked_permit != sel:
            # session_state 만 갱신하면 build_usage_map 이 옛 sel 로 이미 그려진
            # 상태라 한 단계 lag 가 발생 (사용자 클릭이 한 번씩 밀려 보임).
            # 즉시 fragment rerun 으로 새 sel 을 반영해 빨간 원 + 분석표가 함께 갱신.
            st.session_state["usage_selected_permit"] = clicked_permit
            _fragment_rerun()


# ------------------------------------------------------------------------------
#  ■ 월별 일평균 이용량 지도 (⑧) — 연·월 슬라이더 + zoom/center 보존
#
#  Build 2.3 (2026-05-08): nested @st.fragment 시도 → **롤백** (사용자 화면
#    테스트에서 StreamlitDuplicateElementKey: 'usage_monthly_map_year' 발생).
#    원인 추정: streamlit 1.47.1 에서 외부 render() fragment + 내부 nested
#    fragment 조합 시 외부 rerun 동안 내부 fragment 가 두 번 등록되어 같은
#    selectbox key 가 중복 생성. 검증 3팀 모두 통과했지만 정적/구조 검증
#    으로는 잡히지 않는 런타임 race condition.
#    → 데코레이터 제거. 외부 render() fragment 만 사용 (메모리 보호 규칙
#       그대로 유지). 위 필터와 무관 동작은 다른 방식으로 재시도 예정.
# ------------------------------------------------------------------------------
def _render_monthly_usage_map(
    df_master_f: pd.DataFrame,
    df_usage: pd.DataFrame,
    yr_min: int,
    yr_max: int,
) -> None:
    """월별 일평균 이용량 지도 — 연도 dropdown + 월 12버튼으로 시간변화 탐색.

    설계:
      - 컨트롤은 슬라이더 대신 selectbox(연도) + button×12(월) 사용 → 한 번의
        클릭으로 즉시 이동, 슬라이더 드래그 중 매 step rerun 비용 제거.
      - zoom/center 는 별도 session_state 키 (`usage_monthly_map_zoom`/`_center`)
        에 보존되어 컨트롤 변경 시에도 사용자가 보던 위치 유지.
      - 마커 색·크기는 `build_usage_map` 의 6단계 청색 그라데이션 (0~1200 ㎥/일)
        을 그대로 사용 — 위 지도와 범례 100% 일치.
      - 클릭 이벤트는 zoom/center 만 수집, 관정 선택은 무시 (위 지도 담당).
    """
    # ── default 초기화 (rerun 안전, 위젯 이전 후 키 호환 유지)
    if "usage_monthly_map_year" not in st.session_state:
        st.session_state["usage_monthly_map_year"] = yr_max
    if "usage_monthly_map_month" not in st.session_state:
        st.session_state["usage_monthly_map_month"] = 1

    # 데이터 범위가 좁아져 default 가 범위 밖이면 안전 보정
    years = list(range(yr_max, yr_min - 1, -1))   # 최신 → 과거
    cur_y = st.session_state.get("usage_monthly_map_year", yr_max)
    try:
        cur_y = int(cur_y)
    except (TypeError, ValueError):
        cur_y = yr_max
    if cur_y not in years:
        cur_y = yr_max
        st.session_state["usage_monthly_map_year"] = cur_y

    cur_m = st.session_state.get("usage_monthly_map_month", 1)
    try:
        cur_m = int(cur_m)
    except (TypeError, ValueError):
        cur_m = 1
    if cur_m < 1 or cur_m > 12:
        cur_m = 1
        st.session_state["usage_monthly_map_month"] = cur_m

    # ── 컨트롤: 연도 dropdown (좌) + 월 버튼 12개 (우)
    c_year, c_months = st.columns([1, 7])
    with c_year:
        year_sel = st.selectbox(
            "연도", years,
            index=years.index(cur_y),
            key="usage_monthly_map_year",
        )
    with c_months:
        # 라벨 — selectbox 라벨 라인과 높이 정렬
        st.markdown(
            '<div style="font-size:17px;font-weight:400;color:var(--color-text-primary);'
            'margin:0 0 6px;line-height:1.4;height:24px;">월</div>',
            unsafe_allow_html=True,
        )
        # 12개 버튼 — 같은 폭으로 한 줄. 선택된 월은 primary(파랑) 강조.
        # button 클릭은 Streamlit 이 자동으로 rerun 트리거 — 명시적
        # _fragment_rerun() 호출은 불필요(중복 rerun 방지).
        btn_cols = st.columns(12, gap="small")
        for i, mo in enumerate(range(1, 13)):
            with btn_cols[i]:
                if st.button(
                    str(mo),
                    key=f"usage_monthly_map_month_btn_{mo}",
                    type=("primary" if mo == cur_m else "secondary"),
                    use_container_width=True,
                ):
                    if mo != cur_m:
                        st.session_state["usage_monthly_map_month"] = mo
                        cur_m = mo

    # 위젯에서 최종 선택된 (year, month) 확정
    year_sel = int(year_sel)
    month_sel = int(st.session_state["usage_monthly_map_month"])

    # ── 해당 (year, month) 의 관정별 volume_m3 합 / 일수 = 일평균 사용량
    sub = df_usage[
        (df_usage["year"] == year_sel)
        & (df_usage["month"] == month_sel)
    ]
    by_well = (
        sub.groupby("permit_no", dropna=False)["volume_m3"]
           .sum().reset_index()
    )
    days = calendar.monthrange(year_sel, month_sel)[1]
    by_well["daily_avg"] = (
        by_well["volume_m3"] / days if days else 0
    )

    # ── 줌·중심 보존 — 위 지도와 별도 키
    saved_zoom = st.session_state.get(
        "usage_monthly_map_zoom", _DEFAULT_MAP_ZOOM,
    )
    saved_center = st.session_state.get(
        "usage_monthly_map_center", _DEFAULT_MAP_CENTER,
    )

    m = ag_well_helpers.build_usage_map(
        df_master_f, by_well,
        selected_permit=None,
        zoom=saved_zoom, center=tuple(saved_center),
        legend_unit=f"{year_sel}년 {month_sel}월 · 관정별 일평균 사용량 (㎥/일)",
    )
    # G1 fix 2026-05-30: returned_objects=[] 이라 click 은 항상 빈 dict.
    # 이전 click 처리 블록(zoom/center 보존)이 dead code 였음. 가독성 회복.
    st_folium(
        m, width=None, height=800,
        returned_objects=[],
        key="usage_monthly_map",
    )


