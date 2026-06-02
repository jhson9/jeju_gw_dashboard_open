# ==============================================================================
#  파일명: src/analysis/landcover_loader.py  —  Build 1.0 (2026-05-30)
#  토지피복 시설재배지(코드 231/230) 빌드 결과 CSV 로더 (대시보드 read-only)
#  데이터 출처 폴더: config.LANDCOVER_DIR (data/06_landcover)
# ------------------------------------------------------------------------------
#  본 모듈은 scripts/build_greenhouse_stats.py 가 생성한 CSV만 읽는다.
#  파일 없으면 빈 DataFrame 반환 (콘솔 경고 없음 — tab42에서 자체 안내).
# ==============================================================================
from __future__ import annotations

from pathlib import Path

import pandas as pd

try:
    import streamlit as st
    _HAS_ST = True
except ImportError:
    _HAS_ST = False

import config


# ------------------------------------------------------------------------------
#  ■ 캐시 데코 폴백 (단독 import 시)
# ------------------------------------------------------------------------------
def _cache(ttl: int = 600):
    if _HAS_ST:
        return st.cache_data(ttl=ttl)
    def _noop(fn):
        return fn
    return _noop


# ------------------------------------------------------------------------------
#  ■ 안전 reader
# ------------------------------------------------------------------------------
def _safe_read(path: Path, expected_cols: list[str]) -> pd.DataFrame:
    if not path.exists() or path.stat().st_size < 10:
        return pd.DataFrame(columns=expected_cols)
    try:
        df = pd.read_csv(path, encoding="utf-8-sig")
    except Exception:
        return pd.DataFrame(columns=expected_cols)
    for c in expected_cols:
        if c not in df.columns:
            df[c] = pd.NA
    return df


# ------------------------------------------------------------------------------
#  ■ 1. 연도별 도전체 면적
# ------------------------------------------------------------------------------
@_cache(ttl=600)
def load_greenhouse_yearly() -> pd.DataFrame:
    """반환 컬럼: 연도, 레이어, 분류등급, 폴리곤수, 면적_ha,
                도면적비_pct, 경지면적비_pct, 참조값_ha, 검증
    """
    cols = ["연도", "레이어", "분류등급", "폴리곤수", "면적_ha",
            "도면적비_pct", "경지면적비_pct", "참조값_ha", "검증"]
    df = _safe_read(config.LANDCOVER_GREENHOUSE_YEARLY, cols)
    if df.empty:
        return df
    df["연도"] = pd.to_numeric(df["연도"], errors="coerce").astype("Int64")
    for c in ("면적_ha", "도면적비_pct", "경지면적비_pct", "참조값_ha"):
        df[c] = pd.to_numeric(df[c], errors="coerce")
    return df.sort_values("연도").reset_index(drop=True)


# ------------------------------------------------------------------------------
#  ■ 2. 연도 × 읍·면·동 분해
# ------------------------------------------------------------------------------
@_cache(ttl=600)
def load_greenhouse_by_region(year: int | None = None) -> pd.DataFrame:
    """반환 컬럼: 연도, 레이어, 시군, 읍면동, 면적_ha
    year=None → 전체, 정수 → 해당 연도만.
    """
    cols = ["연도", "레이어", "시군", "읍면동", "면적_ha"]
    df = _safe_read(config.LANDCOVER_GREENHOUSE_REGION, cols)
    if df.empty:
        return df
    df["연도"] = pd.to_numeric(df["연도"], errors="coerce").astype("Int64")
    df["면적_ha"] = pd.to_numeric(df["면적_ha"], errors="coerce")
    if year is not None:
        df = df[df["연도"] == int(year)]
    return df.reset_index(drop=True)


# ------------------------------------------------------------------------------
#  ■ 2-B. 연도 × 법정리(177) 분해 — 미세 분석용
# ------------------------------------------------------------------------------
@_cache(ttl=600)
def load_greenhouse_by_ri(year: int | None = None) -> pd.DataFrame:
    """반환 컬럼: 연도, 레이어, 시군, 법정리, 면적_ha
    year=None → 전체, 정수 → 해당 연도만.
    """
    cols = ["연도", "레이어", "시군", "법정리", "면적_ha"]
    df = _safe_read(config.LANDCOVER_GREENHOUSE_RI, cols)
    if df.empty:
        return df
    df["연도"] = pd.to_numeric(df["연도"], errors="coerce").astype("Int64")
    df["면적_ha"] = pd.to_numeric(df["면적_ha"], errors="coerce")
    if year is not None:
        df = df[df["연도"] == int(year)]
    return df.reset_index(drop=True)


# ------------------------------------------------------------------------------
#  ■ 3. 사용 가능 연도 목록
# ------------------------------------------------------------------------------
@_cache(ttl=600)
def available_years() -> list[int]:
    df = load_greenhouse_yearly()
    if df.empty:
        return []
    return sorted(int(y) for y in df["연도"].dropna().unique())


# ------------------------------------------------------------------------------
#  ■ 4. 캐시 무효화 (Tab99 '데이터 새로고침' 연동용)
# ------------------------------------------------------------------------------
def clear_caches() -> None:
    if not _HAS_ST:
        return
    for fn in (load_greenhouse_yearly, load_greenhouse_by_region,
               load_greenhouse_by_ri, available_years):
        try:
            fn.clear()
        except Exception:
            pass
