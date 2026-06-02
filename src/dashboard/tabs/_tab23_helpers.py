# ==============================================================================
#  파일명: src/dashboard/tabs/_tab23_helpers.py
#  ⑧-2 이용량 지도분석 — 데이터 로직 (L0a/L0b/agg/매핑/카운터)
#
#  설계 (_작업지시서_탭8-2_이용량지도분석_FINAL.md 기준):
#    [상수]
#      - _RI_NAME_REMAP       : master.well_ri → 리경계.법정리명 (실측: 빈 dict)
#      - _EUP_DONG_NAMES      : {시 → '제주시 동지역'/'서귀포시 동지역'} 정적 매핑
#      - _QUALITY_PALETTE     : 6단계 hex (theme.PALETTE_QUALITY_6TIER alias)
#      - _NO_DATA_COLOR       : '#BFC6CB'
#      - _DONG_AREA_COLOR     : '#7F7F7F' — 동지역(리 폴리곤 없음) 회색
#    [기간 인덱스]
#      - _month_idx / _idx_to_ym / _idx_to_label : 월 단위 int 슬라이더용
#    [데이터 로딩]
#      - load_master_active_normalized : L0a (907공, eup·ri strip + 매핑 정규화)
#      - load_eup_geojson / load_ri_geojson : GeoJSON 캐시 로드
#      - _load_usage_for_period : 분석기간 usage long DF
#    [모집단]
#      - build_period_population : L0b (사용≥1㎥ permit 만 통과)
#      - _build_filtered_usage : (period + loc_sel) 캐시 wrapper
#      - count_excluded : 휴지(분석기간 사용=0)·폐공(active=False) 카운트
#    [집계]
#      - agg_usage_by_eup : 읍·면 NAME → 집계 metric
#      - agg_usage_by_ri  : 법정리명 → 집계 metric (동지역 자동 제외)
#      - build_kpi_metrics : 5개 KPI 카드 값
#      - chart_monthly_per_well : 12개 막대 (㎥/관정/일)
#    [색상 스코어링]
#      - _quantile_bin_thresholds : 6분위(quantile) 경계값
#      - _color_from_value : value → 6단계 색상 (높을수록 진함, 0/없음 → 회색)
#
#  외부 사용처: tab23_ag_usage_map.py / _tab23_map.py / _tab23_chart.py 전용.
# ==============================================================================
from __future__ import annotations

import calendar
import json
from functools import lru_cache
from pathlib import Path

import pandas as pd
import streamlit as st

import config
from src.analysis import ag_well_loader
from src.dashboard import ag_well_helpers, theme


# ==============================================================================
#  ■ 매핑 사전 — Phase 0 검증으로 확정 (2026-05-20)
# ==============================================================================
#  현 master.csv 와 리경계.shp 의 법정리명이 정확히 일치 (748/748=100%):
#    하귀1리·하귀2리·두모리 모두 양쪽에 분리 표기로 존재.
#  → _작업지시서 §3.5 의 RI_NAME_REMAP (하귀2리→하귀리, 두모리→한원리) 은
#    미러본 데이터 가정 기반이며, 실제 현 데이터에는 적용 불필요.
#  미래에 master 가 통합 표기로 바뀌면 이 dict 만 갱신.
_RI_NAME_REMAP: dict[str, str] = {}

#  동지역 매핑 — well_ri 가 비어있고 well_eup 이 '~동'(법정동) 인 active 관정을
#  읍·면 단위 12개 NAME 중 '제주시 동지역' 또는 '서귀포시 동지역' 으로 매핑.
#  주의: 월평동 같은 동명이동(제주시·서귀포시 양쪽에 존재) 때문에 well_eup
#  단독이 아닌 (well_si, well_eup) 복합키로 식별 → well_si 기반 매핑이 정확.
_EUP_DONG_NAMES: dict[str, str] = {
    "제주시":   "제주시 동지역",
    "서귀포시": "서귀포시 동지역",
}

# 6단계 색상 — _tab13_helpers 와 동일 토큰 (단일 진실 원천: theme.PALETTE_QUALITY_6TIER)
# 의미: 낮을수록 파랑(연), 높을수록 진홍(진) — 본 탭에서는 "이용량 많을수록 진함" 으로
# 순방향 매핑 (디자인 에이전트 결정: 직관성 우선).
_QUALITY_PALETTE = theme.PALETTE_QUALITY_6TIER
_NO_DATA_COLOR = "#BFC6CB"
# 동지역(리·동 지도에서 리 폴리곤이 없는 영역) 회색. theme.COLOR_TEXT_TERTIARY 와 동일.
_DONG_AREA_COLOR = "#7F7F7F"


# ==============================================================================
#  ■ 기간 인덱스 (월 단위 int 슬라이더용)
# ==============================================================================
def _month_idx(year: int, month: int) -> int:
    """(year, month) → 0-base int 인덱스. 기준은 AG_USAGE_YEAR_RANGE[0]·1월."""
    yr_lo, _ = config.AG_USAGE_YEAR_RANGE
    return (int(year) - int(yr_lo)) * 12 + (int(month) - 1)


def _idx_to_ym(idx: int) -> "tuple[int, int]":
    """int 인덱스 → (year, month). 슬라이더 값 → 실제 연·월 변환."""
    yr_lo, _ = config.AG_USAGE_YEAR_RANGE
    y = yr_lo + int(idx) // 12
    m = int(idx) % 12 + 1
    return y, m


def _idx_to_label(idx: int) -> str:
    """int 인덱스 → 'YYYY-MM' 라벨."""
    y, m = _idx_to_ym(idx)
    return f"{y}-{m:02d}"


def _period_range_idx() -> "tuple[int, int]":
    """슬라이더 min/max 인덱스 — AG_USAGE_YEAR_RANGE 의 1월~12월."""
    yr_lo, yr_hi = config.AG_USAGE_YEAR_RANGE
    return _month_idx(yr_lo, 1), _month_idx(yr_hi, 12)


def _period_label(period_lo: int, period_hi: int) -> str:
    """분석기간 라벨 — KPI 푸터·hover 에 사용."""
    return f"{_idx_to_label(period_lo)} ~ {_idx_to_label(period_hi)}"


def _months_in_period(period_lo: int, period_hi: int) -> int:
    """분석기간 개월수."""
    return max(0, int(period_hi) - int(period_lo) + 1)


def _days_in_period(period_lo: int, period_hi: int) -> int:
    """분석기간 일수 합계 (월별 실제 일수 — 윤년 포함)."""
    total = 0
    for idx in range(int(period_lo), int(period_hi) + 1):
        y, m = _idx_to_ym(idx)
        total += calendar.monthrange(y, m)[1]
    return total


# ==============================================================================
#  ■ master 정규화 — L0a (정적 모집단, period 무관)
# ==============================================================================
def _normalize_well_eup_row(well_si, well_eup, well_ri) -> "str | None":
    """master 의 (well_si, well_eup, well_ri) 한 행을 읍면동경계 NAME 으로 정규화.

    매핑 규칙:
      1) well_ri 가 있고 well_eup 이 '~읍/면' 이면 well_eup 그대로 (예: '애월읍')
      2) well_ri 가 비어있고 well_eup 이 '~동' 이면 → '{시} 동지역'
      3) 그 외(둘 다 비어있음) → None
    """
    eup = (well_eup or "").strip() if isinstance(well_eup, str) else None
    ri  = (well_ri  or "").strip() if isinstance(well_ri,  str) else None
    si  = (well_si  or "").strip() if isinstance(well_si,  str) else None
    if not eup:
        return None
    # case 1: 읍·면 (well_ri 가 있거나 eup 이 읍/면 으로 끝나는 경우)
    if eup.endswith("읍") or eup.endswith("면"):
        return eup
    # case 2: 동지역 — well_ri 가 비어있음 + eup 이 동
    if not ri and eup.endswith("동"):
        return _EUP_DONG_NAMES.get(si)
    # case 3: well_ri 가 있는데 eup 이 동(법정동)? — 일반적이지 않음
    if eup.endswith("동"):
        return _EUP_DONG_NAMES.get(si)
    return None


@st.cache_data(ttl=300, show_spinner=False, max_entries=2)
def load_master_active_normalized() -> pd.DataFrame:
    """L0a — active=True 정적 모집단. master.csv + 매핑 + 정규화.

    Returns
    -------
    DataFrame columns (원본 master + 추가):
      - well_si_clean, well_eup_clean, well_ri_clean : strip 적용
      - eup_norm  : 읍면동경계 NAME 12개 중 하나 ('제주시 동지역' 포함) / None
      - ri_norm   : 법정리명 (_RI_NAME_REMAP 적용 후) / None (동지역은 None)
    """
    df = ag_well_loader.load_master(active_only=True)
    if df.empty:
        return df

    out = df.copy()
    out["well_si_clean"]  = out["well_si"].astype("string").str.strip()
    out["well_eup_clean"] = out["well_eup"].astype("string").str.strip()
    out["well_ri_clean"]  = (
        out["well_ri"].astype("string").str.strip().replace(_RI_NAME_REMAP)
    )

    # eup_norm: 12개 NAME 중 하나로 정규화 (동지역 → '{시} 동지역')
    out["eup_norm"] = [
        _normalize_well_eup_row(si, eup, ri)
        for si, eup, ri in zip(
            out["well_si_clean"], out["well_eup_clean"], out["well_ri_clean"]
        )
    ]
    # ri_norm: 법정리명 — 비어있거나 동(법정동)이면 None
    out["ri_norm"] = out["well_ri_clean"].where(
        out["well_ri_clean"].notna() & (out["well_ri_clean"] != ""), None
    )

    # ri_full_key: GeoJSON 의 'properties.법정리이름' 과 매칭되는 복합 키.
    #   - 일반 리: well_si + well_ri  (예: '서귀포시수산리', '제주시수산리')
    #   - 동지역:  well_si + well_eup (예: '제주시강정동', '서귀포시노형동')
    # 동명이리(同名異里) 자연 분리 — 수산리·세화리·고성리 등 4건 회귀 차단.
    # 사용자 보고 (2026-05-20): ⑧-2 의 수산리가 성산읍(11공)+애월읍(5공)=16공
    # 합산으로 부풀려져 표시됨 → 본 키로 그룹핑하면 두 폴리곤 정확히 분리.
    def _make_full_key(row):
        si = row["well_si_clean"]
        if not isinstance(si, str) or not si:
            return None
        ri = row["ri_norm"]
        if isinstance(ri, str) and ri:
            return f"{si}{ri}"
        eup = row["well_eup_clean"]
        if isinstance(eup, str) and eup.endswith("동"):
            return f"{si}{eup}"
        return None

    out["ri_full_key"] = out.apply(_make_full_key, axis=1)
    return out


# ==============================================================================
#  ■ GeoJSON 로더 — Phase 0 산출물
# ==============================================================================
@lru_cache(maxsize=2)
def _read_geojson_cached(path_str: str, mtime: float) -> dict:
    """(path, mtime) 캐시 — 파일 수정 시 자동 무효화."""
    with open(path_str, encoding="utf-8") as f:
        return json.load(f)


def load_eup_geojson() -> dict:
    """읍면동경계.geojson (12 features). 캐시 키에 mtime 포함."""
    p = Path(config.EUP_BOUNDARY_GEOJSON)
    if not p.exists():
        return {"type": "FeatureCollection", "features": []}
    return _read_geojson_cached(str(p), p.stat().st_mtime)


def load_ri_geojson() -> dict:
    """리경계.geojson (177 features, 172 유니크 법정리명). 캐시 키에 mtime 포함."""
    p = Path(config.RI_BOUNDARY_GEOJSON)
    if not p.exists():
        return {"type": "FeatureCollection", "features": []}
    return _read_geojson_cached(str(p), p.stat().st_mtime)


# ==============================================================================
#  ■ usage 로딩 — 분석기간 필터 적용
# ==============================================================================
@st.cache_data(ttl=300, show_spinner=False, max_entries=4)
def _load_usage_for_period(
    period_lo: int, period_hi: int,
) -> pd.DataFrame:
    """분석기간 내 usage long DF — period 외 월은 제거.

    Returns columns: permit_no, year, month, volume_m3
    """
    df = ag_well_loader.load_usage_long()
    if df.empty:
        return df
    # month_idx 컬럼 추가 (벡터화)
    yr_lo, _ = config.AG_USAGE_YEAR_RANGE
    idx = (df["year"].astype("Int64") - yr_lo) * 12 + (df["month"].astype("Int64") - 1)
    mask = idx.notna() & (idx >= int(period_lo)) & (idx <= int(period_hi))
    sub = df.loc[mask, ["permit_no", "year", "month", "volume_m3"]].copy()
    # volume_m3 결측은 0 으로 (분석기간 가동 판정용)
    sub["volume_m3"] = pd.to_numeric(sub["volume_m3"], errors="coerce").fillna(0.0)
    return sub


# ==============================================================================
#  ■ L0b — 동적 모집단 (분석기간 사용≥1㎥ 인 active 관정만)
# ==============================================================================
@st.cache_data(ttl=300, show_spinner=False, max_entries=4)
def build_period_population(period_lo: int, period_hi: int) -> pd.DataFrame:
    """L0b — active AND 분석기간 사용≥1㎥ 인 관정만 통과.

    Returns: load_master_active_normalized() 의 부분집합 (df_pop).
    """
    master = load_master_active_normalized()
    if master.empty:
        return master

    usage = _load_usage_for_period(period_lo, period_hi)
    if usage.empty:
        # usage 자체가 비어있으면 모집단도 빈집합 (분석기간 0개월·자료 없음)
        return master.iloc[0:0].copy()

    yearly_total = usage.groupby("permit_no", as_index=False)["volume_m3"].sum()
    operating = set(
        yearly_total.loc[yearly_total["volume_m3"] >= 1, "permit_no"].astype(str)
    )
    pop = master[master["permit_no"].astype(str).isin(operating)].copy()
    return pop


def count_excluded(period_lo: int, period_hi: int) -> dict:
    """KPI 푸터용 — 분석기간 휴지(active=True인데 사용=0)·폐공(active=False) 카운트."""
    df_all = ag_well_loader.load_master(active_only=False)
    if df_all.empty:
        return {"inactive": 0, "dormant": 0, "active_total": 0, "pop": 0}
    # 제주 본도 외 도서(우도·추자)는 농업용 지하수 분석 대상 제외 (2026-05-27)
    from src.dashboard.figures._dual_zone_common.normalize import (
        EXCLUDED_ISLAND_EUP,
    )
    if "well_eup" in df_all.columns:
        df_all = df_all[
            ~df_all["well_eup"].astype(str).str.strip().isin(EXCLUDED_ISLAND_EUP)
        ]
    if "active" in df_all.columns:
        n_inactive = int((~df_all["active"]).sum())
        n_active   = int(df_all["active"].sum())
    else:
        n_inactive = 0
        n_active   = len(df_all)
    pop = build_period_population(period_lo, period_hi)
    n_pop = int(len(pop))
    n_dormant = max(0, n_active - n_pop)
    return {
        "inactive":     n_inactive,
        "dormant":      n_dormant,
        "active_total": n_active,
        "pop":          n_pop,
    }


# ==============================================================================
#  ■ L1 — 분석기간·위치 필터 적용된 long DF 빌더 (캐시)
# ==============================================================================
def _apply_loc_sel(df: pd.DataFrame, loc_sel: dict) -> pd.DataFrame:
    """master_active_normalized 에 cascading 위치 필터 적용 (well_si/eup/ri 컬럼 사용)."""
    out = df
    si  = loc_sel.get("well_si")
    eup = loc_sel.get("well_eup")
    ri  = loc_sel.get("well_ri")
    if si:
        out = out[out["well_si_clean"] == si]
    if eup:
        # '제주시 동지역' / '서귀포시 동지역' 선택 시 eup_norm 으로 필터
        if eup.endswith("동지역"):
            out = out[out["eup_norm"] == eup]
        else:
            out = out[out["well_eup_clean"] == eup]
    if ri:
        out = out[out["ri_norm"] == ri]
    return out


@st.cache_data(ttl=300, show_spinner=False, max_entries=8)
def _build_filtered_usage_cached(
    period_lo: int, period_hi: int,
    loc_si: "str | None", loc_eup: "str | None", loc_ri: "str | None",
) -> pd.DataFrame:
    """(period + loc_sel) 키로 5분 캐시. df_pop ∩ usage inner join.

    Returns columns: permit_no, well_si_clean, well_eup_clean, well_ri_clean,
                     eup_norm, ri_norm, year, month, volume_m3
    """
    pop = build_period_population(period_lo, period_hi)
    loc_sel = {"well_si": loc_si, "well_eup": loc_eup, "well_ri": loc_ri}
    pop_f = _apply_loc_sel(pop, loc_sel)
    if pop_f.empty:
        return pd.DataFrame(columns=[
            "permit_no", "well_si_clean", "well_eup_clean", "well_ri_clean",
            "eup_norm", "ri_norm", "year", "month", "volume_m3",
        ])
    usage = _load_usage_for_period(period_lo, period_hi)
    if usage.empty:
        return pd.DataFrame(columns=[
            "permit_no", "well_si_clean", "well_eup_clean", "well_ri_clean",
            "eup_norm", "ri_norm", "year", "month", "volume_m3",
        ])
    keep_cols = ["permit_no", "well_si_clean", "well_eup_clean",
                 "well_ri_clean", "eup_norm", "ri_norm", "ri_full_key"]
    return usage.merge(
        pop_f[keep_cols].drop_duplicates("permit_no"),
        on="permit_no", how="inner",
    )


def build_filtered_usage(
    period_lo: int, period_hi: int, loc_sel: dict,
) -> pd.DataFrame:
    """캐시 wrapper — dict 인자를 primitive 로 풀어 캐시 hit 율 보장."""
    return _build_filtered_usage_cached(
        int(period_lo), int(period_hi),
        loc_sel.get("well_si"), loc_sel.get("well_eup"), loc_sel.get("well_ri"),
    )


# ==============================================================================
#  ■ L2/L3 — 읍·면별 / 리·동별 집계
# ==============================================================================
def agg_usage_by_eup(
    df_long: pd.DataFrame, pop_filtered: pd.DataFrame,
    period_lo: int, period_hi: int, mode: str = "abs",
) -> dict:
    """읍·면 NAME → {'sum_m3', 'n_well', 'per_well_day'}.

    Parameters
    ----------
    mode : 'abs'(절대값) | 'per_well'(관정당 일평균)
    """
    days = max(1, _days_in_period(period_lo, period_hi))
    out = {}
    if df_long.empty:
        return out

    # 합계: eup_norm 별 volume 합
    g_sum = df_long.groupby("eup_norm", dropna=True, observed=True)["volume_m3"].sum()
    # 관정수: pop_filtered 의 eup_norm 별 unique permit_no
    g_cnt = (
        pop_filtered.dropna(subset=["eup_norm"])
        .groupby("eup_norm", observed=True)["permit_no"].nunique()
    )
    for name, sum_m3 in g_sum.items():
        n = int(g_cnt.get(name, 0))
        per_well_day = (sum_m3 / n / days) if n > 0 else None
        out[name] = {
            "sum_m3":       float(sum_m3),
            "n_well":       n,
            "per_well_day": per_well_day,
            "metric":       (per_well_day if mode == "per_well" else float(sum_m3))
                            if (n > 0 or mode == "abs") else 0.0,
        }
    return out


def agg_usage_by_ri_with_dong(
    df_long: pd.DataFrame, pop_filtered: pd.DataFrame,
    period_lo: int, period_hi: int, mode: str = "abs",
) -> dict:
    """ri_full_key (시군구+리/동) → 집계. 동명이리 자연 분리.

    2026-05-20 사용자 결정 (옵션 B): master.csv 의 (well_si, well_eup, well_ri)
    복합키로 동명이리(수산리·세화리·고성리) 분리 집계. shape 파일의
    properties.법정리이름 ('서귀포시수산리') 키와 정확히 매칭.

    Returns
    -------
    dict[ri_full_key → {
        sum_m3, n_well, per_well_day, metric,
        label,    # '성산읍 수산리' (사용자 표시명)
        ri_norm,  # '수산리' (원본 리명)
        si, eup,  # '서귀포시', '성산읍'
    }]
    """
    days = max(1, _days_in_period(period_lo, period_hi))
    out: dict = {}
    if df_long.empty:
        return out

    df_full = df_long[df_long["ri_full_key"].notna()]
    pop_full = pop_filtered[pop_filtered["ri_full_key"].notna()]

    g_sum = df_full.groupby("ri_full_key", observed=True)["volume_m3"].sum()
    g_cnt = pop_full.groupby("ri_full_key", observed=True)["permit_no"].nunique()
    g_meta = pop_full.groupby("ri_full_key", observed=True).agg(
        si=("well_si_clean", "first"),
        eup=("well_eup_clean", "first"),
        ri_norm=("ri_norm", "first"),
    )

    for key in set(g_sum.index) | set(g_cnt.index):
        sum_m3 = float(g_sum.get(key, 0.0))
        n = int(g_cnt.get(key, 0))
        per_well_day = (sum_m3 / n / days) if n > 0 else None
        meta = g_meta.loc[key] if key in g_meta.index else None
        si  = meta["si"]      if meta is not None else None
        eup = meta["eup"]     if meta is not None else None
        ri  = meta["ri_norm"] if meta is not None else None
        if isinstance(ri, str) and ri:
            label = f"{eup} {ri}"
        elif isinstance(eup, str) and eup.endswith("동"):
            label = f"{si} {eup}"
        else:
            label = key
        out[key] = {
            "sum_m3":       sum_m3,
            "n_well":       n,
            "per_well_day": per_well_day,
            "metric":       (per_well_day if mode == "per_well" else sum_m3)
                            if (n > 0 or mode == "abs") else 0.0,
            "label":        label,
            "ri_norm":      ri,
            "si":           si,
            "eup":          eup,
        }
    return out


# P3-3 (2026-05-29): agg_usage_by_ri 제거 — 동명이리(同名異里) 문제로 dead.
# agg_usage_by_ri_with_dong (위) 가 ri_full_key 로 분리하므로 동등 기능을 제공.

# ==============================================================================
#  ■ KPI 5장
# ==============================================================================
def build_kpi_metrics(
    df_long: pd.DataFrame, pop_filtered: pd.DataFrame,
    period_lo: int, period_hi: int,
) -> dict:
    """KPI 카드 5개 값 + Top1 리."""
    n_well = int(pop_filtered["permit_no"].nunique()) if not pop_filtered.empty else 0
    total_m3 = float(df_long["volume_m3"].sum()) if not df_long.empty else 0.0
    months = max(1, _months_in_period(period_lo, period_hi))
    days = max(1, _days_in_period(period_lo, period_hi))

    monthly_avg = total_m3 / months
    daily_avg   = total_m3 / days

    # Top1 리·동 — 동명이리 분리 (옵션 B, 2026-05-20 사용자 결정)
    # 검증팀 5·10 지적: 이전 ri_norm 그룹핑은 성산읍 수산리(11공)+애월읍 수산리
    # (5공) 합산하여 "수산리"로 표시 → 지도 폴리곤과 불일치. ri_full_key 로
    # 그룹핑하고 표시명도 "성산읍 수산리" 형식으로 통일 (지도 hover 일치).
    top1_ri = None
    top1_val = 0.0
    if not df_long.empty:
        df_keyed = df_long[df_long["ri_full_key"].notna()]
        if not df_keyed.empty:
            g = df_keyed.groupby("ri_full_key", observed=True)["volume_m3"].sum()
            if not g.empty:
                top_key = str(g.idxmax())
                top1_val = float(g.max())
                # 표시명 생성 — pop_filtered 의 메타로 "성산읍 수산리" 형식
                sub = pop_filtered[pop_filtered["ri_full_key"] == top_key]
                if not sub.empty:
                    first = sub.iloc[0]
                    ri_n = first.get("ri_norm")
                    eup = first.get("well_eup_clean")
                    si  = first.get("well_si_clean")
                    if isinstance(ri_n, str) and ri_n:
                        top1_ri = f"{eup} {ri_n}"   # 일반 리 → "성산읍 수산리"
                    elif isinstance(eup, str) and eup.endswith("동"):
                        top1_ri = f"{si} {eup}"     # 동지역 → "제주시 노형동"
                    else:
                        top1_ri = top_key
                else:
                    top1_ri = top_key
    return {
        "n_well":       n_well,
        "total_m3":     total_m3,
        "monthly_avg":  monthly_avg,
        "daily_avg":    daily_avg,
        "top1_ri":      top1_ri,
        "top1_val":     top1_val,
        "months":       months,
        "days":         days,
    }


# ==============================================================================
#  ■ L4 — 월별 12개 막대 (관정당 일 사용량)
# ==============================================================================
def chart_monthly_per_well(
    df_long: pd.DataFrame, pop_filtered: pd.DataFrame,
    period_lo: int, period_hi: int,
) -> dict:
    """1월~12월 ㎥/관정/일 12개 값. 분모(N_pop) = 분석기간 가동 관정 수 (고정).

    Returns
    -------
    dict(x, y, n_active, n_pop, days_per_month)
      - x: [1..12]
      - y: 12개 float (㎥/관정/일). N_pop=0 또는 분석기간 그 월 부재 시 None.
      - n_active: 12개 — 그 월에 사용≥1 인 관정 수 (hover 보조)
      - n_pop: 단일 정수 (전 월 공통 분모)
      - days_per_month: 12개 (분석기간 내 그 월 평균 일수)
    """
    out_x = list(range(1, 13))
    n_pop = int(pop_filtered["permit_no"].nunique()) if not pop_filtered.empty else 0
    if n_pop == 0 or df_long.empty:
        return {
            "x":              out_x,
            "y":              [None] * 12,
            "n_active":       [0] * 12,
            "n_pop":          n_pop,
            "days_per_month": [calendar.monthrange(2025, m)[1] for m in out_x],
        }

    y_vals: list = []
    n_act:  list = []
    days_m: list = []

    # 검증팀1 지적 (위험): 이전 코드는 df_long 의 unique year 수를 분모로 써서,
    # 분석기간이 부분년도 (예: 2024-07 ~ 2025-06) 일 때 2024-07 만 있는 7월·
    # 2025-01 만 있는 1월에도 n_years=2 가 적용되어 값이 절반으로 왜곡됐다.
    # 정확한 분모는 "분석기간 안에서 그 month 가 등장한 횟수" (= count_m).
    # 동일 원리로 total_days 도 분석기간에 포함된 (year, month) 만 합산해야 함.
    months_in_period = [_idx_to_ym(i) for i in range(period_lo, period_hi + 1)]

    for m in out_x:
        # 분석기간 안에 month=m 이 등장한 연도 리스트
        ys_for_m = [y for (y, mm) in months_in_period if mm == m]
        count_m = len(ys_for_m)

        sub = df_long[df_long["month"].astype("Int64") == m]
        s_total = float(sub["volume_m3"].sum())

        if count_m == 0:
            # 분석기간 안에 이 월이 한 번도 없음 — E1: None 표시
            y_vals.append(None)
            days_m.append(calendar.monthrange(2025, m)[1])
        else:
            total_days = sum(calendar.monthrange(int(y), m)[1] for y in ys_for_m)
            avg_days = total_days / count_m
            avg_per_year = s_total / count_m
            y_vals.append(avg_per_year / n_pop / avg_days)
            days_m.append(avg_days)

        # n_active (그 월 실가동 N — hover 보조)
        if not sub.empty:
            n_act.append(int(sub[sub["volume_m3"] >= 1]["permit_no"].nunique()))
        else:
            n_act.append(0)

    return {
        "x":              out_x,
        "y":              y_vals,
        "n_active":       n_act,
        "n_pop":          n_pop,
        "days_per_month": days_m,
    }


# ==============================================================================
#  ■ 포맷 헬퍼 (㎥)  —  KPI 카드 표시용
# ==============================================================================
def _fmt_m3(v: "float | None") -> str:
    """㎥ 값 포맷 — None/NaN 은 '-'."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "-"
    try:
        return f"{float(v):,.0f}"
    except (TypeError, ValueError):
        return str(v)


# P3-3 (2026-05-29): folium choropleth 구현체 폐기에 따라 아래 함수들이 dead 가 됨:
#  - _quantile_bin_thresholds : 6분위 경계 계산 (plotly 는 절대 도메인 사용)
#  - _color_from_value         : value → 6단계 색상 매핑 (plotly Colorscale 대체)
#  - inject_agg_into_geojson   : folium GeoJsonTooltip 용 properties 주입 (plotly 미사용)
#  - _fmt_per_well_day         : inject_agg_into_geojson 전용 포맷
# → 모두 제거. 호출처 0건 검증 완료. plotly 경로는 DAILY_USAGE_VMIN/VMAX 절대도메인 사용.


# ==============================================================================
#  ■ 월별 12장 dual-zone (리·동) — 관정당 일 사용량
# ==============================================================================
# 사용자 요청 2026-05-21:
#   - 4행 3열 (1월~12월) ri_dual_zone monthly small multiples
#   - 분석기간 ≤ 12개월: 가장 많이 걸친 년도의 1~12월 (실측)
#   - 분석기간 >  12개월: 분석기간에 걸친 모든 년도의 월별 평균
#   - figure title 영역에 분석기간 표시
#   - 단위: ㎥/공·일 (월 사용량 ÷ 해당 월 일수)
# ──────────────────────────────────────────────────────────────────────────────
_DAYS_PER_MONTH_AVG: dict = {
    # 윤년 평균(2월 28.25) — 다년 평균 케이스에서만 사용. 단년 케이스는
    # _days_in_month(year, m) 헬퍼로 calendar.monthrange 결과를 써야 정확.
    "Jan": 31, "Feb": 28.25, "Mar": 31, "Apr": 30,
    "May": 31, "Jun": 30, "Jul": 31, "Aug": 31,
    "Sep": 30, "Oct": 31, "Nov": 30, "Dec": 31,
}
_DAYS_PER_MONTH_AVG_NUM: dict = {
    1: 31, 2: 28.25, 3: 31, 4: 30, 5: 31, 6: 30,
    7: 31, 8: 31, 9: 30, 10: 31, 11: 30, 12: 31,
}
# 영문 월 약어(MONTHS_ABBR) → 월번호 매핑 — _DAYS_PER_MONTH_AVG 와의 호환용.
_MONTHS_ABBR_TO_NUM = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


def _days_in_month(year: "int | None", month: int) -> float:
    """월 일수 산정 헬퍼 (2026-05-28, 검증9팀 윤년 통일).

    - year 가 주어지면(단년 케이스): calendar.monthrange 로 정확한 일수
      (윤년의 2월=29 도 정확히 반영).
    - year=None (다년 평균 케이스): 2월=28.25 평균 사용.
    """
    if year is not None:
        import calendar
        return float(calendar.monthrange(int(year), int(month))[1])
    return float(_DAYS_PER_MONTH_AVG_NUM[int(month)])


def _select_monthly_period_strategy(period_lo: int, period_hi: int) -> dict:
    """분석기간 → (target_year|None, period_label, years_list, n_years).

    사용자 명세 (2026-05-22):
      - 분석기간 <  24개월: 가장 많이 걸친 년도의 1~12월 전체 자료 (실측).
        ※ 분석기간 무관하게 target_year 의 12개월 자료 사용 — 부분 결측은 회색.
      - 분석기간 ≥ 24개월: 분석기간에 걸친 모든 년도의 월별 평균 (다년 평균).
    """
    from collections import Counter
    n_months = period_hi - period_lo + 1
    years_cnt: Counter = Counter()
    for idx in range(period_lo, period_hi + 1):
        y, _m = _idx_to_ym(idx)
        years_cnt[y] += 1
    years_list = sorted(years_cnt.keys())
    n_years_in_period = len(years_list)

    if n_months < 24:
        target_year = years_cnt.most_common(1)[0][0]
        label = f"{target_year}년 1월 ~ 12월 (실측)"
        return {
            "target_year": target_year, "label": label,
            "years": [target_year], "n_years": 1,
        }
    label = (
        f"{years_list[0]}년 ~ {years_list[-1]}년 "
        f"({n_years_in_period}년 월별 평균)"
    )
    return {
        "target_year": None, "label": label,
        "years": years_list, "n_years": n_years_in_period,
    }


def render_ri_monthly_daily_grid(
    master: pd.DataFrame, df_long: pd.DataFrame,
    period_lo: int, period_hi: int, *,
    height: int = 1200,
):
    """tab8-2 전용 — 4행 3열 리·동 dual-zone 월별 일사용량.

    내부적으로 [ri_dual_zone.monthly.render_monthly](src/dashboard/figures/ri_dual_zone/monthly.py)
    를 재사용하되, ``_pw`` 컬럼을 일사용량으로 사전 변환하고 colorbar·hover
    단위만 사후 교체. tab10 의 fig27(월 단위) 호출은 영향 없음.
    """
    # lazy import — 모듈 로드 순환 회피.
    from src.dashboard.figures.ri_dual_zone.constants import MONTHS_ABBR
    from src.dashboard.figures.ri_dual_zone.data import aggregate_units
    from src.dashboard.figures.ri_dual_zone.monthly import render_monthly

    strat = _select_monthly_period_strategy(period_lo, period_hi)

    # 1) usage 필터 + (다년 케이스) /n_years 평균화
    if strat["target_year"] is not None:
        usage_f = df_long[df_long["year"] == strat["target_year"]].copy()
    else:
        usage_f = df_long[df_long["year"].isin(strat["years"])].copy()

    # 1.5) 모집단 규칙(2026-05-27): 연 100㎥ 미만 (관정,연도) 제외.
    #      /n_years 평균화 '이전' 의 실제 연간값으로 판정해야 하므로 여기서
    #      먼저 적용하고, 같은 집합을 active_permits 로 넘겨 분자·분모를 통일.
    from src.analysis import ag_well_metrics
    usage_f = ag_well_metrics.filter_population_by_annual_usage(usage_f)
    pop_permits = ag_well_metrics.population_permits_by_year(usage_f)

    if strat["target_year"] is None and strat["n_years"] > 0:
        usage_f["volume_m3"] = usage_f["volume_m3"] / strat["n_years"]

    # 2) units 집계 (월 단위 _pw 컬럼) — 모집단 한정 N 분모
    units_df = aggregate_units(master, usage_f, active_permits=pop_permits)

    # 3) _pw 를 일사용량으로 변환 (해당 월 일수 ÷). 단년 케이스는 윤년 정확.
    units_df = units_df.copy()
    _yr_for_days = strat.get("target_year")   # 단년 케이스만 not None
    for m_abbr in MONTHS_ABBR:
        col = f"{m_abbr}_pw"
        if col in units_df.columns:
            m_num = _MONTHS_ABBR_TO_NUM[m_abbr]
            units_df[col] = units_df[col] / _days_in_month(_yr_for_days, m_num)

    # 4) render_monthly 호출 (units_df 사전 변환 결과 재사용)
    #    units_df 의 _pw 컬럼이 이미 일사용량으로 변환되었으므로 절대 도메인
    #    DAILY_USAGE_VMIN/VMAX (0~1600) 명시 — fig27 의 monthly fallback
    #    (월 단위 48000) 이 적용되지 않도록 강제.
    from src.dashboard.figures._dual_zone_common.color import (
        DAILY_USAGE_VMAX, DAILY_USAGE_VMIN,
    )
    fig = render_monthly(
        master, usage_f, units_df=units_df,
        period_label=strat["label"], height=height,
        color_vmin=DAILY_USAGE_VMIN, color_vmax=DAILY_USAGE_VMAX,
    )

    # 5) 사후 변환: colorbar title + hover 단위 라벨 교체.
    for trace in fig.data:
        mk = getattr(trace, "marker", None)
        if mk is not None:
            cb = getattr(mk, "colorbar", None)
            if cb is not None:
                tt = getattr(cb, "title", None)
                if tt is not None:
                    txt = getattr(tt, "text", "") or ""
                    if "월 이용량" in txt or "월 사용량" in txt:
                        tt.text = "관정당 일 이용량 (㎥/공·일)"
        ht = getattr(trace, "hovertemplate", None)
        if isinstance(ht, str) and ht:
            ht2 = ht.replace("㎥/공·월", "㎥/공·일")
            ht2 = ht2.replace("관정당 사용량:", "관정당 일사용량:")
            trace.hovertemplate = ht2

    # 6) 분석기간 표시 — figure title 영역
    fig.update_layout(
        title=dict(
            text=f"<b>분석기간:</b> {strat['label']}",
            x=0.5, xanchor="center", y=0.985,
            font=dict(size=15, color=theme.COLOR_TEXT_INFO),
        ),
        margin=dict(l=10, r=140, t=66, b=20),
    )
    return fig, strat["label"]


# ==============================================================================
#  ■ 월별 12장 리경계 choropleth small multiples — 지도 중심 (사용자 요청 2026-05-22)
# ==============================================================================
# _DAYS_NUM 은 위 _DAYS_PER_MONTH_AVG_NUM 으로 통합. 단년 케이스는 _days_in_month 사용.
_MONTHS_KR_LIST = (
    "1월", "2월", "3월", "4월", "5월", "6월",
    "7월", "8월", "9월", "10월", "11월", "12월",
)


def render_ri_monthly_map_grid(
    master: pd.DataFrame, df_long: pd.DataFrame,
    period_lo: int, period_hi: int, *,
    height: int = 1100,
    width: "int | None" = None,
):
    """리경계 shape (GeoJSON) 기반 4행 3열 월별 일사용량 small multiples.

    사용자 명세 (2026-05-22):
      - 분석기간 < 24개월: 가장 많이 걸친 년도(target_year) 의 1~12월 실측
      - 분석기간 ≥ 24개월: 분석기간에 걸친 모든 년도 월별 평균
      - 색: 관정당 일사용량 (㎥/공·일) — DAILY_USAGE_COLORSCALE 절대 도메인 0~1600
      - 자료 없는 리·동: 옅은 회색 base layer
      - figure title 영역에 분석기간 표시

    Returns
    -------
    (fig, period_label) | (None, period_label) — GeoJSON 부재 시 fig=None
    """
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    from src.dashboard.figures._dual_zone_common.color import (
        DAILY_USAGE_COLORSCALE, DAILY_USAGE_VMAX, DAILY_USAGE_VMIN,
    )

    strat = _select_monthly_period_strategy(period_lo, period_hi)

    # 1) usage 사전 필터 + (다년 케이스) /n_years 평균화
    if strat["target_year"] is not None:
        usage_f = df_long[df_long["year"] == strat["target_year"]].copy()
    else:
        usage_f = df_long[df_long["year"].isin(strat["years"])].copy()
        if strat["n_years"] > 0:
            usage_f["volume_m3"] = usage_f["volume_m3"] / strat["n_years"]

    # 2) ri GeoJSON 로드 + 베이스 키 추출
    gj = load_ri_geojson()
    if not gj.get("features"):
        return None, strat["label"]
    base_keys = [
        f["properties"].get("법정리이름")
        for f in gj["features"]
        if f["properties"].get("법정리이름")
    ]

    # 3) 모집단(관정수)·메타 — ri_full_key 기준
    pop_full = master[master["ri_full_key"].notna()].copy()
    if pop_full.empty:
        return None, strat["label"]
    g_cnt = (pop_full.groupby("ri_full_key", observed=True)["permit_no"]
                     .nunique())
    g_meta = (pop_full.groupby("ri_full_key", observed=True)
                      .agg(eup=("well_eup_clean", "first"),
                           ri_norm=("ri_norm", "first")))

    # 4) 월별 일사용량 산정 — df_long 에 ri_full_key 없으면 master 와 merge
    if "ri_full_key" not in usage_f.columns:
        usage_f = usage_f.merge(
            master[["permit_no", "ri_full_key"]].drop_duplicates("permit_no"),
            on="permit_no", how="left",
        )
    usage_f_ri = usage_f[usage_f["ri_full_key"].notna()].copy()
    usage_f_ri["month_int"] = usage_f_ri["month"].astype("Int64")

    monthly_per_well: dict = {}
    _yr_for_days_map = strat.get("target_year")   # 단년 케이스만 not None — 윤년 정확
    for m in range(1, 13):
        sub = usage_f_ri[usage_f_ri["month_int"] == m]
        g_sum = sub.groupby("ri_full_key", observed=True)["volume_m3"].sum()
        days_m = _days_in_month(_yr_for_days_map, m)
        per_w: dict = {}
        for k, v in g_sum.items():
            n = int(g_cnt.get(k, 0))
            if n > 0 and days_m > 0:
                per_w[k] = float(v) / n / days_m
        monthly_per_well[m] = per_w

    # 5) ASOS 월 강수량 (subplot title 부착)
    try:
        from src.dashboard.figures.ri_dual_zone.constants import MONTHS_ABBR
        from src.dashboard.figures.ri_dual_zone.data import load_asos_monthly
        asos_monthly, _ = load_asos_monthly()
        rain_per_month = (
            asos_monthly.mean(axis=0)
            if asos_monthly is not None and not asos_monthly.empty else None
        )
    except Exception:
        rain_per_month = None
        MONTHS_ABBR = (
            "Jan", "Feb", "Mar", "Apr", "May", "Jun",
            "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
        )

    titles: list[str] = []
    for i in range(12):
        if rain_per_month is not None:
            rmm = float(rain_per_month.get(MONTHS_ABBR[i], 0.0))
            rain_str = f" · 강수 {rmm:.0f}mm" if rmm > 0 else ""
        else:
            rain_str = ""
        titles.append(f"{_MONTHS_KR_LIST[i]}{rain_str}")

    # 6) make_subplots — choropleth specs (간격 최소화 → 지도 면적 최대)
    fig = make_subplots(
        rows=4, cols=3,
        subplot_titles=titles,
        specs=[[{"type": "choropleth"}] * 3] * 4,
        horizontal_spacing=0.003, vertical_spacing=0.02,
    )

    zmin, zmax = DAILY_USAGE_VMIN, DAILY_USAGE_VMAX

    for mi in range(12):
        m = mi + 1
        r, c = mi // 3 + 1, mi % 3 + 1

        # 6-1) 베이스 — 자료 없는 리·동 옅은 회색
        fig.add_trace(go.Choropleth(
            geojson=gj,
            locations=base_keys,
            z=[0] * len(base_keys),
            featureidkey="properties.법정리이름",
            colorscale=[[0, "rgba(232,232,232,0.85)"],
                        [1, "rgba(232,232,232,0.85)"]],
            showscale=False, hoverinfo="skip",
            marker_line_color="#9e9e9e", marker_line_width=0.35,
        ), row=r, col=c)

        # 6-2) 색 layer — 자료 있는 리·동만 + 툴팁(이름·관정수·일사용량)
        per_w = monthly_per_well[m]
        if per_w:
            keys = list(per_w.keys())
            z_vals = [float(per_w[k]) for k in keys]
            # customdata: [라벨, 관정수] — hover 에 함께 표시.
            # 사용자 요청 2026-05-22: 읍·면 prefix 제거 → 리(또는 동) 이름만.
            cdata = []
            for k in keys:
                meta = g_meta.loc[k] if k in g_meta.index else None
                rn = meta["ri_norm"] if meta is not None else None
                eup = meta["eup"] if meta is not None else None
                if isinstance(rn, str) and rn:
                    lab = rn                  # "금악리"
                else:
                    lab = eup or k            # 동지역은 "강정동" 그대로
                cdata.append([lab, int(g_cnt.get(k, 0))])

            # 통합 colorbar — 첫 패널 trace 에만 부착. 하단 가로 막대로 배치하여
            # 우측 공간 회수 → 12 지도 패널이 가로 폭 최대 활용.
            colorbar_dict = None
            if mi == 0:
                colorbar_dict = dict(
                    title=dict(
                        text="관정당 일 이용량 (㎥/공·일)",
                        side="top",
                    ),
                    orientation="h",
                    thickness=14, len=0.45,
                    x=0.5, xanchor="center",
                    y=-0.025, yanchor="top",
                )
            fig.add_trace(go.Choropleth(
                geojson=gj,
                locations=keys, z=z_vals,
                featureidkey="properties.법정리이름",
                colorscale=DAILY_USAGE_COLORSCALE,
                zmin=zmin, zmax=zmax,
                customdata=cdata,
                # 사용자 요청 2026-05-22: 월·"관정"·"관정당 일 이용량:" 라벨 제거.
                hovertemplate=(
                    "<b>%{customdata[0]}</b><br>"
                    + "%{customdata[1]:,}공<br>"
                    + "<b>%{z:,.1f}</b> ㎥/공·일"
                    + "<extra></extra>"
                ),
                marker_line_color="#444444", marker_line_width=0.35,
                showscale=(mi == 0),
                colorbar=colorbar_dict,
            ), row=r, col=c)

    # 7) 12 geo 도메인 — 제주 전체 bbox 명시.
    #    fitbounds="locations" 대신 명시 lonaxis/lataxis range 사용.
    #    근거: plotly.js 클라이언트의 fitbounds 비동기 픽셀 측정이 12개 패널
    #    중 일부에서 타이밍 어긋남 → mercator scale 폭주 → "정사각형 줌인"
    #    증상. 명시 bbox 는 서버측 결정적이라 12 패널 완전 동일 줌 보장.
    JEJU_LON_RANGE = [126.13, 126.99]
    JEJU_LAT_RANGE = [33.18, 33.58]
    for mi in range(12):
        geo_key = "geo" if mi == 0 else f"geo{mi + 1}"
        fig.update_layout(**{
            geo_key: dict(
                visible=False,
                projection_type="mercator",
                lonaxis=dict(range=JEJU_LON_RANGE),
                lataxis=dict(range=JEJU_LAT_RANGE),
                showcoastlines=False,
                showframe=False,
                showland=False,
                bgcolor="rgba(0,0,0,0)",
            )
        })

    # 8) figure 전체 layout — 우측 colorbar 제거 → 우측 margin 축소,
    #    하단 horizontal colorbar 공간 확보. 12 패널이 가로 폭 최대 활용.
    #    width 명시 시 use_container_width=False 와 함께 사용 → 컨테이너 폭
    #    제한 우회하여 figure 자체 폭을 강제 (사용자 요청 2026-05-22 v2).
    layout_kwargs: dict = dict(
        height=height,
        margin=dict(l=4, r=4, t=56, b=64),
        title=dict(
            text=f"<b>분석기간:</b> {strat['label']}",
            x=0.5, xanchor="center", y=0.985,
            font=dict(size=15, color=theme.COLOR_TEXT_INFO),
        ),
        paper_bgcolor="white", plot_bgcolor="white",
        hoverlabel=dict(bgcolor="white", font_size=14,
                        bordercolor="rgba(26,26,24,0.30)"),
    )
    if width is not None:
        layout_kwargs["width"] = int(width)
        layout_kwargs["autosize"] = False
    fig.update_layout(**layout_kwargs)
    for ann in fig.layout.annotations:
        if hasattr(ann, "font"):
            ann.font = dict(size=14, color=theme.COLOR_TEXT_PRIMARY)

    return fig, strat["label"]
