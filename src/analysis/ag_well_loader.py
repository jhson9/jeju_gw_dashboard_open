# ==============================================================================
#  파일명: src/analysis/ag_well_loader.py  —  Build 2.0
#  모듈: 농업용 공공관정 데이터 로더 (data_ag_well/)
# ------------------------------------------------------------------------------
#  역할:
#    - master.csv / master_yearly/*.csv / usage/*.csv / water_quality/*.csv 를
#      안정적으로 읽고, 좌표 변환·숫자 클리닝·long format 변환까지 마쳐 반환.
#    - Streamlit @st.cache_data 로 캐싱하여 반복 로드 방지 (ttl=300).
#  데이터 클리닝 정책:
#    - 숫자 컬럼 빈 문자열·콤마·공백 → NaN 또는 float
#    - 수질 토큰: '불검출' → 0.0,  '누락' → NaN
#    - 좌표는 EPSG:5186 (한국 통합 TM 중부원점) → WGS84 변환
# ==============================================================================

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
import streamlit as st

import config
from src.dashboard.map_helpers import _tm_to_wgs84


# ------------------------------------------------------------------------------
#  공통 헬퍼: 숫자/토큰 클리닝
# ------------------------------------------------------------------------------
def _clean_num(v) -> float | None:
    """문자열 숫자(콤마·공백·빈 문자열) → float 또는 None."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        if pd.isna(v):
            return None
        return float(v)
    # 콤마 제거 후 공백 처리 (V7 수정 2026-05-27).
    #  기존엔 모든 공백을 무조건 제거 → "1 2"(별개 토큰 2개)가 "12" 로 위조될
    #  위험이 있었음. 이제 공백은 '천단위 구분' 패턴일 때만(뒤 그룹이 정확히
    #  3자리) 제거하고, 그 외 숫자 사이 공백이 있으면 파싱 불가로 간주(None).
    s = re.sub(r"\s+", " ", str(v).strip()).replace(",", "")
    if s == "" or s.lower() in ("nan", "none"):
        return None
    if " " in s:
        if re.fullmatch(r"[+-]?\d{1,3}(?: \d{3})+(?:\.\d+)?", s):
            s = s.replace(" ", "")
        else:
            return None
    try:
        return float(s)
    except ValueError:
        return None


def _parse_quality(v) -> float | None:
    """수질 측정값 토큰 처리.

    - '불검출' → 0.0  (적합으로 카운트)
    - '누락' / 빈값  → None (분석 제외)
    - 그 외 숫자 → float
    """
    if v is None:
        return None
    if isinstance(v, (int, float)):
        if pd.isna(v):
            return None
        return float(v)
    s = str(v).strip()
    if s == "" or s in ("누락", "결측", "측정안됨", "-"):
        return None
    if s in ("불검출", "ND", "N.D.", "N.D"):
        return 0.0
    s = s.replace(",", "")
    try:
        return float(s)
    except ValueError:
        return None


_NUMERIC_MASTER_COLS = (
    "tank_count", "coord_x", "coord_y",
    "elevation_m", "drill_depth_m", "casing_diameter_mm",
    "discharge_diameter_mm", "capacity_m3d", "permit_m3m",
    "natural_water_level_m", "stable_water_level_m",
    "voltage_v", "motor_hp", "pump_depth_m",
)


def _normalize_master(df: pd.DataFrame) -> pd.DataFrame:
    """master 류 DataFrame 의 공통 정규화 (숫자 변환 + 좌표 변환 + 주소 합성)."""
    df = df.copy()

    # 숫자 컬럼
    for col in _NUMERIC_MASTER_COLS:
        if col in df.columns:
            df[col] = df[col].apply(_clean_num)

    # active 정규화 (true/false 문자열 → bool).
    # master.csv 는 'active', master_yearly/master_YYYY.csv 는 'is_active' 컬럼명.
    # 두 형태 모두 받아 'active' 컬럼으로 통일 (2026-05-28 검증2팀 지적).
    if "is_active" in df.columns and "active" not in df.columns:
        df = df.rename(columns={"is_active": "active"})
    elif "is_active" in df.columns and "active" in df.columns:
        # 양쪽 모두 있는 비정상 케이스 — active 우선, is_active 폐기.
        df = df.drop(columns=["is_active"])
    if "active" in df.columns:
        df["active"] = (
            df["active"].astype(str).str.strip().str.lower()
            .map({"true": True, "false": False, "1": True, "0": False})
            .fillna(False)
        )

    # 시설년도
    if "install_date" in df.columns:
        df["install_date"] = pd.to_datetime(df["install_date"], errors="coerce")

    # 좌표 변환 (TM → WGS84)
    if "coord_x" in df.columns and "coord_y" in df.columns:
        latlons = df.apply(
            lambda r: _tm_to_wgs84(r["coord_x"], r["coord_y"])
            if pd.notna(r["coord_x"]) and pd.notna(r["coord_y"])
            else (None, None),
            axis=1,
        )
        df["lat"] = [ll[0] for ll in latlons]
        df["lon"] = [ll[1] for ll in latlons]

    # 관할 (authority): well_si 기반 영문 코드 (jeju/seogwipo) — 다수 코드가
    # 이 값에 의존 (tab21_ag_stats:304, _tab12_group_stats:99, ag_map_builders:126 등).
    # master.csv 의 원본 한글 authority (제주시/서귀포시/농어촌공사/제주특별자치도)
    # 는 tab6 결과 표 '관리주체' 컬럼 표시용으로 authority_kor 에 별도 보존.
    if "authority" in df.columns:
        df["authority_kor"] = df["authority"]
    if "well_si" in df.columns:
        df["authority"] = df["well_si"].apply(
            lambda s: "seogwipo" if isinstance(s, str) and "서귀포" in s
            else ("jeju" if isinstance(s, str) and "제주" in s else None)
        )

    # 주소 합성 (검색용) — NaN/None 모두 빈 문자열로 정규화
    def _s(v) -> str:
        if v is None:
            return ""
        if isinstance(v, float) and pd.isna(v):
            return ""
        return str(v).strip()

    addr_parts = []
    for _, row in df.iterrows():
        parts = [
            _s(row.get("well_si")),
            _s(row.get("well_eup")),
            _s(row.get("well_ri")),
            _s(row.get("well_bunji")),
        ]
        addr_parts.append(" ".join(p for p in parts if p))
    df["address_full"] = addr_parts

    # ID 컬럼 정규화 — CSV 에 숫자 한 행이라도 섞이면 dtype 이 object/int 로
    # 갈라져 `==` 비교가 silent False 가 되는 케이스 차단. 호출처 6곳이 무방비
    # 비교를 하던 문제 해결.
    for _id_col in ("permit_no", "well_id"):
        if _id_col in df.columns:
            df[_id_col] = df[_id_col].astype("string").str.strip()

    # 검색 인덱스
    df["search_text"] = (
        df.get("permit_no", pd.Series(dtype=str)).fillna("").astype(str).str.lower()
        + " "
        + df.get("well_id", pd.Series(dtype=str)).fillna("").astype(str).str.lower()
        + " "
        + df["address_full"].astype(str).str.lower()
    )

    return df


# ------------------------------------------------------------------------------
#  ■ master.csv
# ------------------------------------------------------------------------------
@st.cache_data(ttl=300, show_spinner=False, max_entries=4)
def load_master(active_only: bool = True) -> pd.DataFrame:
    """data_ag_well/master.csv 를 로드.

    Parameters
    ----------
    active_only : bool
        True 면 active=True (운영중) 관정만 반환. 지도 표시·검색 기본값.
        False 면 전체 (사라진 관정 포함). 통계 탭에서 사용.
    """
    p = config.AG_MASTER_FILE
    if not p.exists():
        return pd.DataFrame()

    df = pd.read_csv(p, encoding="utf-8-sig")
    df = _normalize_master(df)

    if active_only and "active" in df.columns:
        df = df[df["active"]].copy()
    return df.reset_index(drop=True)


@st.cache_data(ttl=300, show_spinner=False, max_entries=4)
def load_master_yearly(year: int) -> pd.DataFrame:
    """master_yearly/master_YYYY.csv 를 로드. 없으면 빈 DataFrame."""
    p = config.AG_MASTER_YEARLY_DIR / f"master_{year}.csv"
    if not p.exists():
        return pd.DataFrame()
    df = pd.read_csv(p, encoding="utf-8-sig")
    df = _normalize_master(df)
    df["year"] = year
    return df.reset_index(drop=True)


@st.cache_data(ttl=300, show_spinner=False, max_entries=4)
def load_master_yearly_all() -> pd.DataFrame:
    """master_yearly/ 의 모든 연도를 concat 해 반환 (변동 추적용).

    각 frame 의 「전부 NA 인 컬럼」은 concat 직전에 제거 — 일부 yearly 파일
    (특히 master_2017) 에는 여러 컬럼이 빈 값으로만 채워져 있어, 다른 연도의
    float/datetime 컬럼과 섞일 때 pandas 의 dtype-inference 변경 예고
    (FutureWarning) 가 발생함. 해당 컬럼은 다른 연도 값으로 concat 후 자동
    채워지므로 결과 DataFrame 에는 영향 없음.
    """
    frames = []
    if not config.AG_MASTER_YEARLY_DIR.exists():
        return pd.DataFrame()
    for p in sorted(config.AG_MASTER_YEARLY_DIR.glob("master_*.csv")):
        try:
            year = int(p.stem.split("_")[-1])
        except ValueError:
            continue
        d = pd.read_csv(p, encoding="utf-8-sig")
        d = _normalize_master(d)
        d["year"] = year
        d = d.dropna(axis=1, how="all")
        frames.append(d)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ------------------------------------------------------------------------------
#  ■ usage/usage_montly_YYYY.csv  (wide → long 변환)
# ------------------------------------------------------------------------------
_MONTH_MAP = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}


@st.cache_data(ttl=300, show_spinner=False, max_entries=4)
def load_usage_long() -> pd.DataFrame:
    """usage/usage_montly_*.csv 9년치 → long format 통합.

    Returns
    -------
    DataFrame columns: permit_no, well_id, year, month, volume_m3,
                       capacity_m3d, permit_m3m, usage_rate, date
    """
    if not config.AG_USAGE_DIR.exists():
        return pd.DataFrame()

    frames = []
    yr_lo, yr_hi = config.AG_USAGE_YEAR_RANGE
    for yr in range(yr_lo, yr_hi + 1):
        p = config.AG_USAGE_DIR / f"usage_montly_{yr}.csv"
        if not p.exists():
            continue
        d = pd.read_csv(p, encoding="utf-8-sig")
        # 숫자 클리닝 (콤마·공백 처리)
        for m in _MONTH_MAP:
            if m in d.columns:
                d[m] = d[m].apply(_clean_num)
        for col in ("capacity_m3d", "permit_m3m"):
            if col in d.columns:
                d[col] = d[col].apply(_clean_num)
        # year 컬럼이 없거나 비어있으면 파일명 기반으로 보충
        if "year" not in d.columns or d["year"].isna().all():
            d["year"] = yr

        long = d.melt(
            id_vars=[c for c in ("permit_no", "well_id", "year",
                                 "capacity_m3d", "permit_m3m") if c in d.columns],
            value_vars=[m for m in _MONTH_MAP if m in d.columns],
            var_name="month_name",
            value_name="volume_m3",
        )
        long["month"] = long["month_name"].map(_MONTH_MAP)
        long = long.drop(columns=["month_name"])
        frames.append(long)

    if not frames:
        return pd.DataFrame()

    df = pd.concat(frames, ignore_index=True)

    # ID 컬럼 정규화 — master 와 동일 정책 (string dtype + strip)
    for _id_col in ("permit_no", "well_id"):
        if _id_col in df.columns:
            df[_id_col] = df[_id_col].astype("string").str.strip()

    # 사용률 (%) — permit_m3m 대비
    df["usage_rate"] = pd.NA
    mask = df["permit_m3m"].notna() & (df["permit_m3m"] > 0) & df["volume_m3"].notna()
    df.loc[mask, "usage_rate"] = (
        df.loc[mask, "volume_m3"] / df.loc[mask, "permit_m3m"] * 100
    ).round(2)

    # 시계열 편의 컬럼
    df["date"] = pd.to_datetime(
        df["year"].astype(str) + "-" + df["month"].astype(str).str.zfill(2) + "-01",
        errors="coerce",
    )
    df = df.sort_values(["permit_no", "year", "month"]).reset_index(drop=True)

    # 이상값 마킹 — drop 하지 않음. tab7 화면에서 사용자에게 표시.
    # current_year 를 명시 전달해야 cache_data ttl 동안 결과가 안정적.
    from datetime import date as _date_cls
    from src.analysis import anomaly_detection
    df = anomaly_detection.detect_usage_anomalies(
        df, current_year=_date_cls.today().year,
    )

    return df


# ------------------------------------------------------------------------------
#  ■ water_quality/water_quality_semiannual.csv  (long format)
# ------------------------------------------------------------------------------
_QUALITY_NUMERIC_COLS = ("ammonia_n", "nitrate_n", "pH", "chloride", "EC")


@st.cache_data(ttl=300, show_spinner=False, max_entries=4)
def load_quality_semiannual() -> pd.DataFrame:
    """반기 수질 5항목 long format. 부적합 플래그(*_exceed) 자동 추가."""
    p = config.AG_QUALITY_SEMIANNUAL
    if not p.exists():
        return pd.DataFrame()

    df = pd.read_csv(p, encoding="utf-8-sig")
    for col in _QUALITY_NUMERIC_COLS:
        if col in df.columns:
            df[col] = df[col].apply(_parse_quality)

    # ID 컬럼 정규화 — master/usage 와 동일 정책
    for _id_col in ("permit_no", "well_id"):
        if _id_col in df.columns:
            df[_id_col] = df[_id_col].astype("string").str.strip()

    if "year" in df.columns:
        df["year"] = pd.to_numeric(df["year"], errors="coerce").astype("Int64")
    if "sampling_date" in df.columns:
        df["sampling_date"] = pd.to_datetime(df["sampling_date"], errors="coerce")
    if "half" in df.columns:
        df["half"] = df["half"].astype(str).str.strip()

    df = _add_exceed_flags(df, config.WATER_QUALITY_STANDARDS)
    return df.reset_index(drop=True)


@st.cache_data(ttl=300, show_spinner=False, max_entries=4)
def load_quality_regular() -> pd.DataFrame:
    """정기검사 15항목."""
    p = config.AG_QUALITY_REGULAR
    if not p.exists():
        return pd.DataFrame()

    df = pd.read_csv(p, encoding="utf-8-sig")
    for col in config.WATER_QUALITY_REGULAR_STANDARDS:
        if col in df.columns:
            df[col] = df[col].apply(_parse_quality)

    # ID 컬럼 정규화
    for _id_col in ("permit_no", "well_id"):
        if _id_col in df.columns:
            df[_id_col] = df[_id_col].astype("string").str.strip()

    if "sampling_date" in df.columns:
        df["sampling_date"] = pd.to_datetime(df["sampling_date"], errors="coerce")
        df["year"] = df["sampling_date"].dt.year.astype("Int64")

    df = _add_exceed_flags(df, config.WATER_QUALITY_REGULAR_STANDARDS)
    return df.reset_index(drop=True)


def _add_exceed_flags(df: pd.DataFrame, standards: dict) -> pd.DataFrame:
    """기준치 초과 플래그 컬럼(*_exceed) 추가. EC 처럼 기준 없는 항목은 스킵."""
    for item, std in standards.items():
        if item not in df.columns:
            continue
        col = f"{item}_exceed"
        flag = pd.Series(False, index=df.index)
        if "max" in std:
            flag = flag | (df[item] > std["max"])
        if "min" in std:
            flag = flag | (df[item] < std["min"])
        # 결측은 부적합으로 카운트하지 않음
        flag = flag & df[item].notna()
        df[col] = flag
    return df


# ------------------------------------------------------------------------------
#  ■ 편의 함수: 단일 관정 조회
# ------------------------------------------------------------------------------
def get_well_info(permit_no: str) -> dict | None:
    """master 에서 단일 관정의 기본 정보를 dict 로 반환."""
    df = load_master(active_only=False)
    if df.empty or "permit_no" not in df.columns:
        return None
    row = df[df["permit_no"] == permit_no]
    if row.empty:
        return None
    return row.iloc[0].to_dict()
