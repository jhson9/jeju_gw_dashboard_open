# ==============================================================================
#  파일명: src/dashboard/tabs/_tab12_helpers.py
#  ⑥ 이용량 분석 탭 — 헬퍼 + 상수 + 캐시
#
#  Source 분리: tab12_ag_usage.py 2311줄 → 그룹별 분리 1단계 (2026-05-09).
#    [상수]
#      - _AGG_LABELS              : 집계 단위 라벨
#      - _LEVEL_TO_GROUP          : 집계 단위 → (group_col, group_label_kor)
#      - _LEVEL_TO_SUBGROUP_COL   : 집계 단위 → 하위 그룹 컬럼
#      - _DEFAULT_MAP_ZOOM        : 11.5
#      - _DEFAULT_MAP_CENTER      : (33.42, 126.55)
#      - _PERMIT_PALETTE          : 연도별 취수허가량 색 팔레트
#      - _SUBGROUP_LINE_PALETTE   : 다중 라인 색 팔레트 (12색)
#    [캐시]
#      - _cached_asos_data        : ASOS 자료 5분 캐시
#    [함수]
#      - _maybe_recenter_usage_map : 위치 필터 변경 시 지도 중심 갱신
#      - _normalize_group_values   : 동지역 그룹 정규화
#      - _stats_filter_for_level   : 집계단위별 부분 cascading 필터
#      - _yr_label                 : 연도 범위 라벨 ('YYYY년' / 'YYYY ~ YYYY년')
#      - _location_label           : cascading 결과 → 위치 라벨
#      - _stats_title_scope        : 통계 표 제목용 위치 라벨
#      - _yearly_permit_for_well   : 관정의 연도별 permit_m3m 사전
#      - _fmt_int                  : 콤마 정수 (0.5 단위 반올림, NaN→'-')
#      - _nice_y_max               : nice number y2 축 max
#
#  외부 사용처: tab12_ag_usage.py 내부 전용.
# ==============================================================================
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.analysis import ag_well_loader
from src.collectors import asos_collector


# asos_collector.load_asos_data() 는 매 호출마다 read_csv 실행 → 새 DataFrame.
# 이 함수에 직접 cache 데코레이터를 못 붙이는 이유는 collectors 모듈이
# asos_collector.load_asos_data 가 자체 streamlit cache 를 가지므로 wrapper
# 의 자체 decorator 는 제거. 4개 호출처(_tab7/_tab8/app/이외) 가 모두 같은
# 객체를 받아 effective_rainfall.aggregate_monthly 의 hash_funcs={DF:id} cache
# 와 통일.
def _cached_asos_data() -> pd.DataFrame:
    return asos_collector.load_asos_data()


_AGG_LABELS = ["제주도 전역", "시", "읍면동", "리", "유역"]


# ── 집계 단위별 하위 그룹 키 정의
#   key: 집계 단위 라벨
#   group_col: 집계할 컬럼 (merged 에 존재해야 함)
#   group_label: 표 헤더에 보일 한국어 라벨
_LEVEL_TO_GROUP: dict[str, tuple[str, str]] = {
    "제주도 전역": ("authority", "시"),
    "도전역":      ("authority", "시"),   # legacy alias
    "시":          ("well_eup",  "읍/면/동"),
    "읍면동":      ("well_ri",   "리"),
    "리":          ("well_id",   "관정명"),
    "유역":        ("watershed", "유역"),
}


# 집계단위별 하위 그룹 컬럼: 한 단계 아래로 분해.
#   - 시 단위        → 읍/면/동 (well_eup, 동→'동지역')
#   - 읍/면/동 단위  → 리/동   (well_ri,  ri 가 비고 eup 이 동이면 그 동을 키로)
#   - 리 단위        → 개별 관정 (permit_no)
#   - 제주도 전역    → 시 (well_si) — 옵션
#   - 유역           → watershed — 옵션
_LEVEL_TO_SUBGROUP_COL: dict[str, str] = {
    "제주도 전역": "well_si",
    "도전역":      "well_si",
    "시":          "well_eup",
    "읍면동":      "well_ri",
    "리":          "permit_no",
    "유역":        "watershed",
}


# 지도 default
_DEFAULT_MAP_ZOOM = 11.5
_DEFAULT_MAP_CENTER = (33.42, 126.55)


# 연도별 취수허가량 변동 색 팔레트 — 가장 최근 값(=현재 기준)은 흰색,
# 그와 다른 과거 값들은 unique 값별로 pastel tone 을 순환 부여 → 같은 값은 같은 색.
_PERMIT_PALETTE = (
    "#C8E6C9", "#FFE082", "#90CAF9", "#FFAB91",
    "#CE93D8", "#A5D6A7", "#F8BBD0", "#80DEEA",
)


# 다중 라인용 색상 팔레트 (Plotly D3 + 확장 — 12색까지 명확히 구분).
_SUBGROUP_LINE_PALETTE = (
    "#1f77b4", "#ff7f0e", "#2ca02c", "#d62728", "#9467bd",
    "#8c564b", "#e377c2", "#7f7f7f", "#bcbd22", "#17becf",
    "#aec7e8", "#ffbb78",
)


# ──────────────────────────────────────────────────────────────────
#  지도 중심 갱신 / 위치 라벨
# ──────────────────────────────────────────────────────────────────
def _maybe_recenter_usage_map(loc_sel: dict, df_master_f: pd.DataFrame) -> None:
    """위치 필터(시/읍면동/리)가 변경되면 지도 중심·줌을 그 지역 관정 centroid 로 이동.

    fingerprint(=loc_sel 값 튜플) 가 직전 호출과 다를 때만 갱신.
    줌: 리 14, 읍면동 12, 시 11, 전체 11.
    """
    fp = (loc_sel.get("well_si"), loc_sel.get("well_eup"), loc_sel.get("well_ri"))
    last_fp = st.session_state.get("_usage_loc_fingerprint")
    if fp == last_fp:
        return
    st.session_state["_usage_loc_fingerprint"] = fp

    if df_master_f.empty:
        return
    if "lat" not in df_master_f.columns or "lon" not in df_master_f.columns:
        return
    coords = df_master_f.dropna(subset=["lat", "lon"])
    if coords.empty:
        return

    cy = float(coords["lat"].mean())
    cx = float(coords["lon"].mean())
    st.session_state["usage_map_center"] = (cy, cx)

    if loc_sel.get("well_ri"):
        st.session_state["usage_map_zoom"] = 14
    elif loc_sel.get("well_eup"):
        st.session_state["usage_map_zoom"] = 12
    elif loc_sel.get("well_si"):
        st.session_state["usage_map_zoom"] = 11
    else:
        st.session_state["usage_map_zoom"] = 11


def _normalize_group_values(merged: pd.DataFrame, group_col: str) -> pd.DataFrame:
    """행정구역 동지역 처리 — group_col 값을 일관성 있게 정규화.

    제주시/서귀포시의 동지역(○○동) 처리 규칙:
      - well_eup 그룹: 모든 '○○동' 값을 '동지역' 1개로 통합
      - well_ri 그룹: ri 가 비어있는 동지역 관정은 well_eup 의 동(예: 상효동)으로
                       채워 넣어 「리 단위에서 동을 표시」(사용자 요구) 충족
      - authority/watershed: 변경 없음
    """
    out = merged.copy()
    if group_col == "well_eup":
        eup = out[group_col].astype(str).str.strip().replace(
            {"nan": "", "None": "", "NaN": "", "<NA>": ""}
        )
        out[group_col] = eup.where(~eup.str.endswith("동", na=False), "동지역")
    elif group_col == "well_ri":
        ri = out[group_col].astype(str).str.strip().replace(
            {"nan": "", "None": "", "NaN": "", "<NA>": ""}
        )
        if "well_eup" in out.columns:
            eup = out["well_eup"].astype(str).str.strip().replace(
                {"nan": "", "None": "", "NaN": "", "<NA>": ""}
            )
            # ri 가 있으면 ri 그대로, 없고 eup 이 동이면 그 동을 ri 그룹키로
            fallback = eup.where(eup.str.endswith("동", na=False), "")
            out[group_col] = ri.where(ri != "", fallback)
        else:
            out[group_col] = ri
    return out


def _stats_filter_for_level(level: str, loc_sel: dict) -> dict:
    """집계단위에 따라 cascading filter 를 「한 단계 위」 까지만 적용.

    이유: 집계단위가 「시」이면 표·박스 플롯이 시의 한 단계 아래(읍/면/동) 분포를
          보여줘야 의미가 있다. 사용자가 cascading 에서 읍/면/동 / 리를 선택해
          좁혀도, 통계 표는 시 안의 모든 읍면동을 보여주도록 부분 필터만 적용.

    규칙:
      제주도 전역 → 모두 무시
      시          → well_si 만 적용 (읍/면/동 / 리 무시)
      읍/면/동    → well_si, well_eup 적용 (리 무시)
      리, 유역    → 모든 필터 적용
    """
    if level in ("제주도 전역", "도전역"):
        return {}
    if level == "시":
        return {"well_si": loc_sel.get("well_si")}
    if level == "읍면동":
        return {
            "well_si":  loc_sel.get("well_si"),
            "well_eup": loc_sel.get("well_eup"),
        }
    return dict(loc_sel)


def _yr_label(yr_range: "tuple[int, int]") -> str:
    """기간 라벨 — 단일 연도면 'YYYY년', 범위면 'YYYY ~ YYYY년'."""
    if yr_range[0] == yr_range[1]:
        return f"{yr_range[0]}년"
    return f"{yr_range[0]} ~ {yr_range[1]}년"


def _location_label(loc_sel: dict) -> str:
    """cascading filter 결과 → 지역 라벨. 단계가 깊어질수록 ' > ' 로 연결."""
    parts = []
    for k in ("well_si", "well_eup", "well_ri"):
        v = loc_sel.get(k)
        if v:
            parts.append(v)
    return " > ".join(parts) if parts else "제주도 전역"


def _stats_title_scope(level: str, loc_sel: dict) -> str:
    """집계 단위별 통계 표의 제목 — 사용자가 선택한 위치명을 우선 표시.

    예) 집계단위='읍면동' + 사용자가 '대정읍' 선택 → '대정읍'
        집계단위='시'   + 사용자가 '서귀포시' 선택 → '서귀포시'
        선택 없으면 집계단위 라벨 그대로.
    """
    si = loc_sel.get("well_si") or ""
    eup = loc_sel.get("well_eup") or ""
    ri = loc_sel.get("well_ri") or ""
    if level in ("제주도 전역", "도전역"):
        return "제주도 전역"
    if level == "시":
        return si or "제주도 전역 (시 미선택)"
    if level == "읍면동":
        return eup or si or "제주도 전역 (읍면동 미선택)"
    if level == "리":
        return ri or eup or si or "제주도 전역 (리 미선택)"
    if level == "유역":
        return "유역별"
    return level


def _yearly_permit_for_well(
    permit_no: str, sub: pd.DataFrame
) -> "dict[int, float]":
    """관정의 연도별 permit_m3m 사전.

    데이터 소스(양쪽 union — 보유한 「모든 연도」 망라):
      - sub  : 이용량 long format (연도별 permit_m3m)
      - master_yearly/master_YYYY.csv : 이용량이 없는 연도까지 보강
    """
    yr_to_pm: dict[int, float] = {}

    if not sub.empty and "permit_m3m" in sub.columns and "year" in sub.columns:
        for yr, grp in sub.dropna(subset=["permit_m3m"]).groupby("year"):
            try:
                yr_to_pm[int(yr)] = float(grp["permit_m3m"].iloc[0])
            except (TypeError, ValueError):
                continue

    if permit_no:
        df_my = ag_well_loader.load_master_yearly_all()
        if not df_my.empty and "permit_no" in df_my.columns:
            my_sub = df_my[df_my["permit_no"] == permit_no]
            if not my_sub.empty and "permit_m3m" in my_sub.columns:
                for yr, grp in my_sub.dropna(subset=["permit_m3m"]).groupby("year"):
                    y = int(yr)
                    if y not in yr_to_pm:
                        try:
                            yr_to_pm[y] = float(grp["permit_m3m"].iloc[0])
                        except (TypeError, ValueError):
                            continue
    return yr_to_pm


def _fmt_int(v) -> str:
    """수치 → 콤마 정수 문자열 (NaN/None → '-')."""
    if v is None or (isinstance(v, float) and pd.isna(v)) or pd.isna(v):
        return "-"
    try:
        return f"{round(float(v) * 2) / 2:,}"
    except (TypeError, ValueError):
        return str(v)


def _nice_y_max(data_max: float, n_ticks: int = 8) -> float:
    """data_max 보다 큰 「nice number」(1·2·2.5·5 × 10^n) × n_ticks 를 반환.

    여러 차트의 y2 축을 같은 nice max 로 정렬해 시각적 비교를 쉽게 하기 위함.
    """
    if (
        data_max is None or data_max <= 0
        or (isinstance(data_max, float) and pd.isna(data_max))
    ):
        return 0.0
    import math as _math
    target = float(data_max) * 1.05
    step_raw = target / n_ticks
    if step_raw <= 0:
        return 0.0
    exp = _math.floor(_math.log10(step_raw))
    base = 10 ** exp
    f = step_raw / base
    if f <= 1:    nice = 1
    elif f <= 2:  nice = 2
    elif f <= 2.5: nice = 2.5
    elif f <= 5:  nice = 5
    else:         nice = 10
    return nice * base * n_ticks
