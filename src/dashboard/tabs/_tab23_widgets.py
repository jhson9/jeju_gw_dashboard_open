# ==============================================================================
#  파일명: src/dashboard/tabs/_tab23_widgets.py
#  ⑧-2 이용량 지도분석 — 위젯 (월 단위 int 슬라이더 + 캐스케이딩 필터)
#
#  설계:
#    - _month_int_slider : 월 단위 int 슬라이더 (0..(N-1), N=AG_USAGE_YEAR_RANGE×12)
#      _tab13_widgets._half_year_slider 의 int-slider 패턴 계승.
#      라벨은 slider 아래 caption "YYYY-MM ~ YYYY-MM" 로 표시.
#      ※ select_slider 사용 금지 (BaseWeb null current 에러 회피).
#    - render_top_controls : 1줄(집계단위·표시방식·분석기간) + 2줄(시→읍→리)
#
#  외부 사용처: tab23_ag_usage_map.py 전용.
# ==============================================================================
from __future__ import annotations

import streamlit as st

import config
from src.dashboard.tabs._tab23_helpers import (
    _idx_to_label,
    _period_range_idx,
)


# ==============================================================================
#  ■ 월 단위 int 슬라이더
# ==============================================================================
def _month_int_slider(key: str = "t8_2_period_idx") -> "tuple[int, int]":
    """월 단위 int 슬라이더 — (lo_idx, hi_idx) 반환.

    인덱스: 0 = AG_USAGE_YEAR_RANGE[0]·01월, max = AG_USAGE_YEAR_RANGE[1]·12월.
    기본값: 최근 12개월 (1년).
    """
    lo_min, hi_max = _period_range_idx()
    n = hi_max - lo_min + 1
    if n <= 0:
        return lo_min, lo_min

    default_hi = hi_max
    default_lo = max(lo_min, hi_max - 11)  # 최근 12개월

    cur = st.session_state.get(key)
    valid = (
        isinstance(cur, (tuple, list)) and len(cur) == 2
        and all(isinstance(x, int) and lo_min <= x <= hi_max for x in cur)
        and cur[0] <= cur[1]
    )
    if not valid:
        if key in st.session_state:
            del st.session_state[key]
        st.session_state[key] = (default_lo, default_hi)

    # CSS — _half_year_slider 와 동일 패턴 (slider 위 padding 흡수, native min/max 라벨 숨김).
    st.markdown("""
    <style>
    [data-testid="stSlider"] [data-testid="stTickBarMin"],
    [data-testid="stSlider"] [data-testid="stTickBarMax"],
    [data-testid="stSlider"] [data-testid="stSliderTickBarMin"],
    [data-testid="stSlider"] [data-testid="stSliderTickBarMax"],
    [data-testid="stSlider"] [class*="TickBarMin"],
    [data-testid="stSlider"] [class*="TickBarMax"] {
        display: none !important;
    }
    [data-testid="stElementContainer"]:has([data-testid="stSlider"]) {
        margin-top: -0.8rem !important;
    }
    </style>
    """, unsafe_allow_html=True)

    val = st.slider(
        "분석 기간 (월)",
        min_value=lo_min, max_value=hi_max,
        step=1, key=key,
    )

    if isinstance(val, (tuple, list)) and len(val) == 2:
        lo_i, hi_i = int(val[0]), int(val[1])
    else:
        lo_i = hi_i = int(val)

    # 슬라이더 아래 년도 tick — 각 년도 1월 위치에 absolute 배치 (보조 단위).
    # 2017~2025 전체 9개 년도가 트랙 위에 균등 표시되어 중간 시점 식별이 쉬워짐.
    y_start, y_end = config.AG_USAGE_YEAR_RANGE
    total_idx_span = hi_max - lo_min if hi_max > lo_min else 1
    year_ticks_html = ""
    for y in range(y_start, y_end + 1):
        # 해당 년도 1월의 idx (lo_min 기준 정규화) — _period_range_idx 가
        # 0=y_start·01월로 시작한다고 가정 (helpers 의 _idx_to_label 과 동일 규약).
        jan_idx_norm = (y - y_start) * 12
        pct = (jan_idx_norm / total_idx_span) * 100
        # 끝 년도(12월 위치) 가 100% 이므로 1월만 표시하면 우측 약간 여유.
        year_ticks_html += (
            f'<span style="position:absolute;left:{pct:.2f}%;'
            f'transform:translateX(-50%);white-space:nowrap;">{y}</span>'
        )
    st.markdown(
        f'<div style="position:relative;height:16px;padding:0 12px;'
        f'margin-top:-12px;margin-bottom:2px;'
        f'font-size:11px;color:var(--color-text-secondary);font-weight:500;">'
        f'{year_ticks_html}</div>',
        unsafe_allow_html=True,
    )

    # 선택 범위 라벨 — YYYY-MM ~ YYYY-MM 중앙 표시
    caption = (
        f'<div style="display:flex;justify-content:space-between;'
        f'padding:0 12px;margin-bottom:4px;'
        f'font-size:13px;color:var(--color-text-secondary);font-weight:500;">'
        f'<span>{_idx_to_label(lo_min)}</span>'
        f'<span style="color:var(--color-text-info);font-weight:700;">'
        f'{_idx_to_label(lo_i)} ~ {_idx_to_label(hi_i)}'
        f'</span>'
        f'<span>{_idx_to_label(hi_max)}</span></div>'
    )
    st.markdown(caption, unsafe_allow_html=True)
    return lo_i, hi_i


# ==============================================================================
#  ■ Cascading 필터 (시 → 읍/면 → 리)
# ==============================================================================
# 2026-05-21: 사용자 결정 — 폴리곤·마커 colorscale 도메인을 ㎥/공·일 로 통일.
# "총 이용량 (㎥)" 옵션 제거. mode 인자는 호환을 위해 유지하되 항상 "per_well".
_MODE_OPTIONS = {
    "관정당 일 이용량 (㎥/공·일)": "per_well",
}


def render_top_controls() -> dict:
    """⑧ 탭과 동일한 1줄 컨트롤: 색에 매핑할 지표 + 분석 기간 슬라이더.

    2026-05-20 (사용자 요청): cascading 필터 제거 — 지도가 모든 동·리를
    표시하므로 시/읍/리 selectbox 불필요. 집계단위 radio 도 제거 (두 지도 항상 표시).

    Returns
    -------
    dict(mode, period_lo, period_hi, loc_sel)
      loc_sel 은 항상 {None, None, None} — 시그니처 호환을 위해 유지.
    """
    # 2026-05-21: 색에 매핑할 지표 selectbox 제거 — ㎥/공·일 단일 도메인 고정.
    # 슬라이더가 전체 폭 사용. mode 키는 다운스트림 호환을 위해 유지.
    period_lo, period_hi = _month_int_slider(key="t8_2_period_idx")
    mode = "per_well"

    return {
        "mode":      mode,
        "period_lo": int(period_lo),
        "period_hi": int(period_hi),
        "loc_sel":   {"well_si": None, "well_eup": None, "well_ri": None},
    }
