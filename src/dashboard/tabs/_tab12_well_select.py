# ==============================================================================
#  파일명: src/dashboard/tabs/_tab12_well_select.py
#  6 이용량 분석 탭 - 관정 선택 바 + 검색 입력
#
#  Source 분리: tab12_ag_usage.py 2311줄 -> 그룹별 분리 2단계 (2026-05-09).
#    - _render_well_selection_bar : 선택 관정 표시 + 검색 + 선택 해제
#    - _render_well_search_input  : 관정명 검색 (Enter -> 선택)
#
#  외부 사용처: tab12_ag_usage.py 내부 전용.
# ==============================================================================
from __future__ import annotations

import pandas as pd

from src.dashboard.tabs._ag_well_select_helpers import (
    render_well_selection_bar,
    render_well_search_input,
    render_map_header_with_search,
)


# tab7 prefix 고정 wrapper (호출처 시그니처 유지)
_USAGE_PLACEHOLDER = "관정명 입력 후 Enter (예: F-430, 90감산)"


def _render_well_selection_bar(
    df_master: pd.DataFrame, selected_permit: str | None,
    *, include_search: bool = True,
) -> None:
    """상시 표시되는 「선택 관정 + (옵션) 검색 + 선택 해제」 바 (이용량 탭).

    2026-05-17: 검색 input 은 지도 헤더 라인으로 이동 → 호출처에서
    `include_search=False` 로 검색 칼럼을 숨기고 본 바는 선택 표시 + 해제만
    노출.
    """
    render_well_selection_bar(
        df_master, selected_permit,
        key_prefix="usage",
        search_placeholder=_USAGE_PLACEHOLDER,
        include_search=include_search,
    )


def _render_well_search_input(df_master: pd.DataFrame) -> None:
    """관정명 직접 검색 입력 (이용량 탭)."""
    render_well_search_input(
        df_master,
        key_prefix="usage",
        placeholder=_USAGE_PLACEHOLDER,
    )


def _render_map_header_with_search(
    df_master: pd.DataFrame, *, title_html: str,
) -> None:
    """지도 헤더 라인 — [제목] + [검색 input] (이용량 탭, 2026-05-17)."""
    render_map_header_with_search(
        df_master,
        key_prefix="usage",
        search_placeholder=_USAGE_PLACEHOLDER,
        title_html=title_html,
    )


