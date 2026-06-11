# ==============================================================================
#  파일명: src/dashboard/ag_well_helpers.py  —  Build 3.0 (facade)
#  모듈: 농업용 공공관정 탭 4개에서 공유하는 UI 컴포넌트의 통합 facade.
# ------------------------------------------------------------------------------
#  본체: fragment-only rerun 헬퍼 2개 (_in_fragment_context, fragment_rerun).
#
#  나머지는 6개 모듈로 분리 (2026-05-09) → re-export 로 기존 호출 경로 유지:
#    - well_count_table.py   : 관정 수 표 (4 심볼)
#    - permit_lookup.py      : permit 추출 (3 심볼)
#    - year_slider.py        : 연도 슬라이더 (1 심볼)
#    - ag_map_builders.py    : 지도 빌더 (3 심볼)
#    - well_card.py          : 단일 관정 카드 + 미니차트 (4 심볼)
#    - ag_filters.py         : 필터 위젯 + 정렬 상수 (6 심볼)
# ==============================================================================

from __future__ import annotations

import inspect

import streamlit as st


# ------------------------------------------------------------------------------
#  ■ Fragment-only rerun 헬퍼 — 컨텍스트 가드 포함
# ------------------------------------------------------------------------------
#  st.rerun(scope="fragment") 는 호출자가 @st.fragment 안에 있어야 의미가 있다.
#  fragment 컨텍스트 외부에서 호출하면 streamlit 이 "Couldn't find fragment with
#  id ..." 디버그 로그를 출력하며 결국 full rerun 으로 폴백 → st.tabs 의
#  selected_index 가 0 으로 reset 되어 사용자가 "탭이 점프했다" 고 인지.
#
#  이 헬퍼는:
#    1) streamlit 빌드가 scope="fragment" 를 지원하는지 검사
#    2) 현재 호출 컨텍스트가 fragment 안인지 best-effort 로 판단
#    3) 둘 다 만족하면 fragment-only rerun, 아니면 일반 rerun 으로 폴백
# ------------------------------------------------------------------------------
_HAS_FRAGMENT_SCOPE = "scope" in inspect.signature(st.rerun).parameters


def _in_fragment_context() -> bool:
    """현재 호출 위치가 @st.fragment 함수 안인지 정확히 판단.

    streamlit 1.47.1 의 ScriptRunContext.current_fragment_id 만 검사.
    이전엔 ``fragment_storage`` / ``fragment_id`` 도 함께 봤는데 이는
    fragment 컨텍스트 외부에서도 항상 존재(FragmentStorage 객체 자체)해서
    false positive → ``st.rerun(scope="fragment")`` 호출 → streamlit 이
    fragment id 를 못 찾고 ``Couldn't find fragment with id ...`` 디버그 로그
    + full rerun 폴백 유발 (사용자 보고 2026-05-09).
    """
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        ctx = get_script_run_ctx()
        if ctx is None:
            return False
        # current_fragment_id 만 — fragment 안에 있을 때만 set 되는 정확한 마커.
        return bool(getattr(ctx, "current_fragment_id", None))
    except Exception:
        return False


def fragment_rerun() -> None:
    """fragment-only rerun. 컨텍스트가 fragment 가 아니면 일반 rerun 으로 폴백."""
    if _HAS_FRAGMENT_SCOPE and _in_fragment_context():
        st.rerun(scope="fragment")
    else:
        st.rerun()


# ------------------------------------------------------------------------------
#  ■ Re-exports — 6개 모듈로부터 (호출처 변경 없이 backward-compat 유지)
# ------------------------------------------------------------------------------
from src.dashboard.ag_filters import (   # noqa: E402,F401
    SI_DROPDOWN_LIST,
    EUP_DROPDOWN_ORDER,
    RI_BY_LOCATION,
    _eup_clean,
    cascading_location_filters,
    apply_cascading_filters,
)
from src.dashboard.year_slider import year_slider   # noqa: E402,F401
from src.dashboard.well_card import (   # noqa: E402,F401
    _CARD_SECTIONS,
    _format_card_value,
    render_well_card,
    build_mini_charts,
)
from src.dashboard.well_card_pdf import (   # noqa: E402,F401
    available_pdf_years,
    render_well_card_pdf_box,
)
from src.dashboard.ag_map_builders import (   # noqa: E402,F401
    maybe_recenter_to_selected_well,
    build_search_map,
    build_usage_map,
)
from src.dashboard.permit_lookup import (   # noqa: E402,F401
    _PERMIT_RE,
    parse_clicked_popup,
    lookup_permit_by_well_id,
)
from src.dashboard.well_count_table import (   # noqa: E402,F401
    WELL_COUNT_TABLE_STRUCTURE,
    compute_well_count_summary,
    _well_counts_dict,
    render_well_count_table,
)
