# ==============================================================================
#  파일명: src/analysis/agri_stats_loader.py  —  Build 1.0
#  농업통계(tab41~45) 데이터 로더 · 정규화 · choropleth 집계
#  데이터 출처 폴더: config.AGRI_STATS_DIR (V3: data/05_ag_stat, 폴백: data/agri_stats)
# ==============================================================================
from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

import pandas as pd

import config

AGRI_DIR: Path = config.AGRI_STATS_DIR   # V3: data/05_ag_stat (폴백: data/agri_stats)

EUP_GEOJSON_NAMES = (
    "한림읍", "애월읍", "구좌읍", "조천읍", "한경면",
    "대정읍", "남원읍", "성산읍", "안덕면", "표선면",
    "제주시 동지역", "서귀포시 동지역",
)
GEOJSON_UNMAPPED = ("추자면", "우도면")


@lru_cache(maxsize=1)
def load_meta() -> dict:
    p = AGRI_DIR / "_meta.json"
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def _read(name: str) -> pd.DataFrame:
    p = AGRI_DIR / name
    if not p.exists():
        return pd.DataFrame()
    return pd.read_csv(p, encoding="utf-8-sig")


def _is_real_eupmyeon(name: object) -> bool:
    if not isinstance(name, str):
        return False
    s = name.strip()
    return s.endswith(("읍", "면", "동")) and not s.startswith(("주", "주:"))


@lru_cache(maxsize=1)
def load_pop_eup() -> pd.DataFrame:
    df = _read("population_by_eupmyeon.csv")
    if df.empty:
        return df
    df = df[df["읍면동"].map(_is_real_eupmyeon)].copy()
    return df.reset_index(drop=True)


@lru_cache(maxsize=1)
def load_pop_yearly() -> pd.DataFrame:
    return _read("population_yearly_total.csv")


@lru_cache(maxsize=1)
def load_farm_household() -> pd.DataFrame:
    return _read("farm_household_yearly.csv")


@lru_cache(maxsize=1)
def load_farmland() -> pd.DataFrame:
    return _read("farmland_area_yearly.csv")


@lru_cache(maxsize=1)
def load_farm_size() -> pd.DataFrame:
    return _read("farm_size_distribution.csv")


@lru_cache(maxsize=1)
def load_crop() -> pd.DataFrame:
    return _read("crop_cultivation_area.csv")


@lru_cache(maxsize=1)
def load_agrix() -> pd.DataFrame:
    """AgriX 농업경영체 등록정보(시군별·연도별).
    컬럼: 연도, 시군, 경영체수, 남, 여, 전업, 겸업, 고령자_65세이상, 재배면적_ha, 출처.
    출처: https://uni.agrix.go.kr/docs7/biOlap/ (자료갱신 2026.3.17., 추출 2026.6.3.)
    참고: 농업경영체수는 통계연보 농가수와 정의가 달라 직접 대체 불가 — 보조지표로 사용.
    """
    return _read("agrix_jeju_yearly.csv")


def classify_to_geojson_name(sigun: str, eupmyeon: str):
    if not isinstance(eupmyeon, str):
        return None
    s = eupmyeon.strip()
    if s in GEOJSON_UNMAPPED:
        return None
    if s.endswith("동"):
        if "제주" in str(sigun):
            return "제주시 동지역"
        if "서귀" in str(sigun):
            return "서귀포시 동지역"
        return None
    if s in EUP_GEOJSON_NAMES:
        return s
    return None


def agg_pop_by_geojson_name(value_col: str) -> dict:
    df = load_pop_eup()
    if df.empty or value_col not in df.columns:
        return {}
    out = {}
    for _, row in df.iterrows():
        name = classify_to_geojson_name(row.get("시군"), row.get("읍면동"))
        if name is None:
            continue
        v = row.get(value_col)
        if pd.isna(v):
            continue
        out[name] = out.get(name, 0.0) + float(v)
    return out


def yoy(series: pd.Series):
    s = series.dropna()
    if len(s) < 2:
        return None
    return float(s.iloc[-1] - s.iloc[-2])


def yoy_pct(series: pd.Series):
    s = series.dropna()
    if len(s) < 2 or s.iloc[-2] == 0:
        return None
    return float((s.iloc[-1] - s.iloc[-2]) / s.iloc[-2] * 100)


def cagr(series: pd.Series, periods=None):
    s = series.dropna()
    if len(s) < 2 or s.iloc[0] <= 0:
        return None
    n = periods if periods is not None else (len(s) - 1)
    if n <= 0:
        return None
    return float(((s.iloc[-1] / s.iloc[0]) ** (1.0 / n) - 1.0) * 100)


def base_year() -> int:
    return int(load_meta().get("base_year", 2024))


def clear_caches() -> None:
    # P5-1 (2026-05-29): load_report 추가 — 검증3팀 지적 버그 fix.
    # 이전엔 보고서 캐시(load_report)가 누락되어 Tab99 "데이터 새로고침" 시에도
    # 보고서 CSV 변경이 반영되지 않았음. 9종 t19~t27 보고서 모두 영향.
    for fn in (load_meta, load_pop_eup, load_pop_yearly, load_farm_household,
               load_farmland, load_farm_size, load_crop, load_report, load_agrix):
        fn.cache_clear()


# ==============================================================================
#  보고서(농업용수 종합계획) 표 로더 — tab41·tab42 보고서형 재현용
# ==============================================================================
REPORT_DIR = AGRI_DIR / "report"


@lru_cache(maxsize=16)
def load_report(stem: str) -> pd.DataFrame:
    """report/<stem>.csv 로드 (t19_pop_admin … t27_susye)."""
    p = REPORT_DIR / (stem if stem.endswith(".csv") else stem + ".csv")
    if not p.exists():
        return pd.DataFrame()
    return pd.read_csv(p, encoding="utf-8-sig")


def farmpop_total_trend_extended() -> pd.DataFrame:
    """도전체 농가인구 추이: 보고서 표2-22(2015~2017) + 통계연보(2018~2024) 결합.
    반환 컬럼: 연도, 농가인구, 출처('보고서'|'통계연보')."""
    rep = load_report("t22_farmpop_trend")
    rows = []
    if not rep.empty:
        t = rep[(rep["시군"] == "제주도") & (rep["읍면동"] == "계")][["연도", "농가인구"]]
        for _, r in t[t["연도"] <= 2017].iterrows():
            rows.append([int(r["연도"]), int(r["농가인구"]), "보고서"])
    fh = load_farm_household()
    if not fh.empty:
        dz = fh[fh["시군"] == "도전체"][["연도", "농가인구"]]
        for _, r in dz.iterrows():
            rows.append([int(r["연도"]), int(r["농가인구"]), "통계연보"])
    df = pd.DataFrame(rows, columns=["연도", "농가인구", "출처"]).drop_duplicates("연도", keep="last")
    return df.sort_values("연도").reset_index(drop=True)


def farmland_trend_extended() -> pd.DataFrame:
    """농경지 면적 추이: 보고서 표2-23(2011~2022) + 통계연보 경지면적(2023~2024) 확장.
    반환: 연도, 농지면적, 경지면적, 작물재배면적, 출처."""
    rep = load_report("t23_farmland_trend").copy()
    if not rep.empty:
        rep["출처"] = "보고서"
    fl = load_farmland()
    add_rows = []
    if not fl.empty:
        dz = fl[fl["시군"] == "도전체"]
        have = set(rep["연도"].tolist()) if not rep.empty else set()
        for _, r in dz.iterrows():
            y = int(r["연도"])
            if y not in have:
                add_rows.append({"연도": y, "농지면적": None,
                                 "경지면적": float(r["경지면적_합계_ha"]),
                                 "작물재배면적": None, "출처": "통계연보"})
    out = pd.concat([rep, pd.DataFrame(add_rows)], ignore_index=True) if add_rows else rep
    return out.sort_values("연도").reset_index(drop=True)
