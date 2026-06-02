# ==============================================================================
#  파일명: src/dashboard/tabs/_tab13_helpers.py
#  ⑦ 수질 분석 탭 — 헬퍼 (포맷·색상·점수·반기 변환·캐시) + 상수
#
#  Source 분리: tab13_ag_quality.py 2101줄 → 그룹별 분리 1단계 (2026-05-09).
#    [상수]
#      - QUALITY_ITEM_ORDER  : 5항목 표시 순서
#      - _ITEM_DECIMALS      : 항목별 소수점 자릿수
#      - _QUALITY_PALETTE    : 6단계 색상 (theme.PALETTE_QUALITY_6TIER)
#      - _NO_DATA_COLOR      : '#BFC6CB'
#      - _SIZE_MULTIPLIERS   : 6단계 마커 크기 배율
#      - _BASE_RADIUS        : 6.0
#      - _AGG_LABELS         : 집계 단위 라벨
#      - _LEVEL_TO_LOC_COL   : level → (column, label) 매핑
#    [캐시]
#      - _cached_asos_data         : ASOS 자료 5분 캐시
#      - _build_filtered_qf_cached : (loc_sel + yh range) → (df_master_f, qf) 5분 캐시
#    [헬퍼]
#      - _fmt_item / _fmt_val      : 포맷
#      - _hex_to_rgba              : hex → rgba 변환
#      - _clean_no_data_rows       : pH=0/NaN 행을 '측정 없음' 으로
#      - _yh_idx / _yh_idx_series  : (year, half) → int 인덱스
#      - _yh_label / _yh_to_date   : 반기 라벨/날짜 변환
#      - _color_score / _bin_index : 기준 대비 점수 → 6-bin 인덱스
#      - _color_from_score / _radius_from_score : bin → 색상/반지름
#      - _std_label                : 기준 라벨 ("≤ X mg/L" 등)
#
#  외부 사용처: tab13_ag_quality.py 내부 전용.
# ==============================================================================
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.analysis import ag_well_loader
from src.collectors import asos_collector
from src.dashboard import ag_well_helpers, theme


# 표시 순서 (사용자 요청): 질산성질소 → 염소이온 → 전기전도도 → 수소이온농도 → 암모니아성 질소
QUALITY_ITEM_ORDER = ["nitrate_n", "chloride", "EC", "pH", "ammonia_n"]

# 항목별 표시 소수점 자릿수 (사용자 요청 #1):
#   - 질산성질소·염소이온·암모니아성 질소·수소이온농도(pH) → 소수 1자리
#   - 전기전도도(EC) → 소수점 없음 (정수)
_ITEM_DECIMALS: dict[str, int] = {
    "nitrate_n": 1,
    "chloride":  1,
    "ammonia_n": 1,
    "pH":        1,
    "EC":        0,
}

# 6단계 색상 — 푸른색(낮음) → 빨간색(높음). 기준값(100%) = 4·5번째 단계 경계.
# theme.PALETTE_QUALITY_6TIER 와 동일 — 단일 진실 원천 (디자인 시스템).
_QUALITY_PALETTE = theme.PALETTE_QUALITY_6TIER
_NO_DATA_COLOR = "#BFC6CB"

# 마커 크기 배율 — 색상과 같은 6단계.
#   bin 0(0~25%) 은 사용자 요청 #2: 1/3 → 0.6 으로 키워 클릭 가능한 크기 확보.
# Phase 1-B (2026-05-14): tab7 (ag_map_builders.SIZE_MULTIPLIERS) 와 동기 조정 →
#   7px floor 보장. 한 화면에서 두 탭 마커 크기 정책 일치.
#   이전: [0.6, 2/3, 1, 4/3, 5/3, 2] × 6 → 최소 3.6px, 최대 12.0px
#   현재: [1, 4/3, 5/3, 2, 7/3, 8/3] × 7 → 최소 7.0px, 최대 ≈ 18.7px
_SIZE_MULTIPLIERS = [1.0, 4/3, 5/3, 2.0, 7/3, 8/3]
_BASE_RADIUS = 7.0

_AGG_LABELS = ["제주도 전역", "시", "읍면동", "리", "유역"]

_LEVEL_TO_LOC_COL: dict[str, tuple[str, str]] = {
    "제주도 전역": ("well_si", "시"),
    "시":          ("well_eup", "읍/면/동"),
    "읍면동":      ("well_ri", "리"),
    "리":          ("well_id", "관정명"),
    "유역":        ("watershed", "유역"),
}


# ==============================================================================
#  ■ 캐시 — ASOS 자료 (read_csv 비용 회피)
# ==============================================================================
# asos_collector.load_asos_data 가 자체 streamlit cache 를 가지므로 wrapper
# 의 decorator 는 제거. 모든 호출처가 같은 객체를 받음 — hash_funcs={DF:id}
# cache 통일.
def _cached_asos_data() -> pd.DataFrame:
    return asos_collector.load_asos_data()


# ==============================================================================
#  ■ 포맷 헬퍼
# ==============================================================================
def _fmt_item(v, item: str) -> str:
    """항목별 소수점 자릿수에 맞춘 표시 문자열. 결측은 '-'."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "-"
    try:
        d = _ITEM_DECIMALS.get(item, 1)
        return f"{float(v):,.{d}f}"
    except (TypeError, ValueError):
        return str(v)


# 로컬 _hex_to_rgba 는 theme.hex_alpha 와 동일 → alias 로 단일 진실 원천 유지
# (2026-05-09 디자인 시스템 정리). 기존 호출처 호환을 위해 이름 보존.
_hex_to_rgba = theme.hex_alpha


def _clean_no_data_rows(df: pd.DataFrame) -> pd.DataFrame:
    """pH 가 0 또는 NaN 인 행을 '측정 없음' 으로 처리 (사용자 요청 #3).

    이유: 원본 CSV 에서 측정 자료가 없는 시기는 pH=0 (혹은 빈 값) 으로 들어와
    있어 5개 항목·_exceed 플래그까지 모두 0/False 로 잘못 표시됨.
    pH=0 은 물리적으로 불가능 → 「측정 없음」 의 가장 신뢰성 높은 마커.

    Returns: 영향받는 행의 5개 항목 값을 NaN, _exceed 를 False 로 치환한 사본.
    """
    if df.empty or "pH" not in df.columns:
        return df
    no_data = df["pH"].isna() | (df["pH"] == 0)
    if not no_data.any():
        return df
    out = df.copy()
    for col in QUALITY_ITEM_ORDER:
        if col in out.columns:
            out.loc[no_data, col] = pd.NA
        exc_col = f"{col}_exceed"
        if exc_col in out.columns:
            out.loc[no_data, exc_col] = False
    return out


# ==============================================================================
#  ■ 반기 (year, half) 변환 헬퍼
# ==============================================================================
def _yh_idx(y, h) -> int:
    """(year, half) → 정수 인덱스 (단일값)."""
    if y is None or (isinstance(y, float) and pd.isna(y)) or pd.isna(y):
        return -1
    try:
        y = int(y)
    except (TypeError, ValueError):
        return -1
    return y * 2 + (0 if str(h).strip() == "상" else 1)


def _yh_idx_series(year_s: pd.Series, half_s: pd.Series) -> pd.Series:
    """벡터화 (year, half) → 정수 인덱스. NaN year → -1.

    19K+ 행 데이터에서 apply(axis=1) 가 너무 느려 벡터화 필수.
    """
    y = pd.to_numeric(year_s, errors="coerce")
    h_offset = (
        half_s.astype(str).str.strip().ne("상").astype(int)
    )
    idx = y * 2 + h_offset
    return idx.where(y.notna(), -1).astype("int64")


def _yh_label(y, h) -> str:
    return f"{int(y)}-{h}" if pd.notna(y) else "-"


def _yh_to_date(y, h) -> pd.Timestamp:
    """반기를 datetime 으로 변환 — 상=3월 15일, 하=9월 15일 (사용자 요청 #4)."""
    if pd.isna(y):
        return pd.NaT
    y = int(y)
    return pd.Timestamp(year=y, month=3 if str(h).strip() == "상" else 9, day=15)


# ==============================================================================
#  ■ cache wrapper — (loc_sel + yh range) 키로 (df_master_f, qf) 5분 캐시
#
#  사용자 요청 2026-05-09: ⑦ 수질 탭 진입 속도 개선. 분석 보고(로직4·오류5)에서
#  `qf.merge(df_master_f)` 19K+ 행 + `_clean_no_data_rows` + reindex 가 매 rerun
#  마다 실행 → -40% 개선 권장. wrapper 가 (loc_sel, yh_lo, yh_hi) primitive
#  키로만 받아 cache 효율 보장 (DataFrame 인자 hash 비용 회피).
# ==============================================================================
@st.cache_data(ttl=300, show_spinner=False)
def _build_filtered_qf_cached(
    loc_si: "str | None",
    loc_eup: "str | None",
    loc_ri: "str | None",
    yh_lo: tuple,
    yh_hi: tuple,
) -> "tuple[pd.DataFrame, pd.DataFrame]":
    """(df_master_f, qf) 반환. 동일 (loc, yh range) 입력에 대해 5분 캐시."""
    df_master = ag_well_loader.load_master(active_only=True)
    df_qual = ag_well_loader.load_quality_semiannual()

    loc_sel = {"well_si": loc_si, "well_eup": loc_eup, "well_ri": loc_ri}
    df_master_f = ag_well_helpers.apply_cascading_filters(df_master, loc_sel)

    if df_master_f.empty:
        return df_master_f, df_qual.iloc[0:0].copy()

    permit_set = set(df_master_f["permit_no"].dropna().unique())
    qf = df_qual[df_qual["permit_no"].isin(permit_set)].copy()

    if "year" in qf.columns and "half" in qf.columns:
        lo_idx = _yh_idx(*yh_lo)
        hi_idx = _yh_idx(*yh_hi)
        qf["_yh"] = _yh_idx_series(qf["year"], qf["half"])
        qf = qf[(qf["_yh"] >= lo_idx) & (qf["_yh"] <= hi_idx)].copy()

    qf = _clean_no_data_rows(qf)

    loc_keep_cols = [
        c for c in ("well_id", "well_si", "well_eup", "well_ri",
                    "watershed", "lat", "lon")
        if c in df_master_f.columns
    ]
    qf = qf.merge(
        df_master_f[["permit_no"] + loc_keep_cols].drop_duplicates("permit_no"),
        on="permit_no", how="left", suffixes=("", "_m"),
    )
    return df_master_f, qf


def _fmt_val(v, decimals: int = 2) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "-"
    try:
        f = float(v)
        if abs(f) >= 1000 and decimals <= 2:
            return f"{f:,.0f}"
        return f"{f:,.{decimals}f}"
    except (TypeError, ValueError):
        return str(v)


# ==============================================================================
#  ■ 6단계 점수 / 색상 / 반지름
# ==============================================================================
def _color_score(value, std: dict, fallback_max: "float | None" = None) -> "float | None":
    """기준값 대비 비율(0~1.5+).

    - max·min 둘 다 있음(pH): |v - mid| / half_range
    - max 만:  v / max
    - max 없음: fallback_max 사용
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if "max" in std and "min" in std:
        mid = (std["max"] + std["min"]) / 2.0
        half = (std["max"] - std["min"]) / 2.0
        if half <= 0:
            return 0.0
        return abs(v - mid) / half
    if "max" in std and std["max"] > 0:
        return v / std["max"]
    if fallback_max is not None and fallback_max > 0:
        return v / fallback_max
    return None


def _bin_index(score: "float | None") -> "int | None":
    """score(0~1.5+) → 6단계 인덱스(0~5). None 이면 None."""
    if score is None or (isinstance(score, float) and pd.isna(score)):
        return None
    pct = score * 100.0
    if pct < 25:    return 0
    if pct < 50:    return 1
    if pct < 75:    return 2
    if pct < 100:   return 3
    if pct < 125:   return 4
    return 5


def _color_from_score(score: "float | None") -> str:
    idx = _bin_index(score)
    return _NO_DATA_COLOR if idx is None else _QUALITY_PALETTE[idx]


def _radius_from_score(score: "float | None") -> float:
    """6단계 마커 반지름. None 이면 절반 크기 회색 마커."""
    idx = _bin_index(score)
    if idx is None:
        return _BASE_RADIUS * 0.5
    return _BASE_RADIUS * _SIZE_MULTIPLIERS[idx]


def _std_label(std: dict) -> str:
    unit = std.get("unit", "")
    if "max" in std and "min" in std:
        return f"{std['min']}~{std['max']} {unit}"
    if "max" in std:
        return f"≤ {std['max']} {unit}"
    if "min" in std:
        return f"≥ {std['min']} {unit}"
    return f"({unit})" if unit else "-"
