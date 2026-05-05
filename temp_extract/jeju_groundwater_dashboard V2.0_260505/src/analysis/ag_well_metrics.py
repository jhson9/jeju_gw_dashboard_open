# ==============================================================================
#  파일명: src/analysis/ag_well_metrics.py  —  Build 2.0
#  모듈: 농업용 공공관정 파생 지표 계산
# ------------------------------------------------------------------------------
#  본 모듈은 데이터를 「가공」만 한다 (시각화 X). 입력은 ag_well_loader 가 만든
#  long format DataFrame, 출력은 새로운 DataFrame 또는 scalar.
#  탭 4개에서 공통으로 호출.
# ==============================================================================

from __future__ import annotations

import pandas as pd

import config


# ------------------------------------------------------------------------------
#  집계 키 매핑 (행정 5단계 + 유역)
# ------------------------------------------------------------------------------
AGG_KEYS: dict[str, str | None] = {
    "제주도 전역": None,         # 전체 합계 (groupby 없음)
    "도전역":      None,         # legacy alias
    "시":          "authority",  # 제주도에는 군이 없으므로 '시' 로 표기
    "읍면동":      "well_eup",
    "리":          "well_ri",
    "관정":        "permit_no",
    "유역":        "watershed",
}

# authority 영문 코드 → 한국어 라벨 (시 단위 집계 결과 표시용)
AUTHORITY_KOR: dict[str, str] = {
    "jeju":     "제주시",
    "seogwipo": "서귀포시",
}


# ------------------------------------------------------------------------------
#  ■ 사용률 계산
# ------------------------------------------------------------------------------
def compute_usage_rate(df: pd.DataFrame) -> pd.DataFrame:
    """사용률(%) 컬럼이 없거나 NaN 이면 다시 계산해 반환."""
    df = df.copy()
    if "permit_m3m" not in df.columns or "volume_m3" not in df.columns:
        return df
    mask = df["permit_m3m"].notna() & (df["permit_m3m"] > 0) & df["volume_m3"].notna()
    df["usage_rate"] = pd.NA
    df.loc[mask, "usage_rate"] = (
        df.loc[mask, "volume_m3"] / df.loc[mask, "permit_m3m"] * 100
    ).round(2)
    return df


def compute_exceed_count(
    df_quality: pd.DataFrame,
    item: str,
) -> int:
    """수질 항목의 부적합 카운트.

    {item}_exceed 컬럼이 미리 만들어져 있다는 가정 (loader 가 자동 생성).
    """
    col = f"{item}_exceed"
    if col not in df_quality.columns:
        return 0
    return int(df_quality[col].fillna(False).sum())


def compute_yoy_change(
    df: pd.DataFrame,
    target_year: int,
    metric: str = "volume_m3",
    group_col: str | None = None,
) -> pd.DataFrame:
    """전년 대비(YoY) 증감 계산.

    Returns DataFrame: [group_col?, current, previous, yoy_pct]
    """
    if "year" not in df.columns or metric not in df.columns:
        return pd.DataFrame()

    grp_cols = ["year"] if group_col is None else [group_col, "year"]
    agg = df.groupby(grp_cols, dropna=False)[metric].sum().reset_index()
    cur = agg[agg["year"] == target_year].rename(columns={metric: "current"})
    prv = agg[agg["year"] == target_year - 1].rename(columns={metric: "previous"})

    if group_col is None:
        cur = cur.drop(columns=["year"])
        prv = prv.drop(columns=["year"])
        if cur.empty or prv.empty:
            return pd.DataFrame()
        out = pd.concat([cur.reset_index(drop=True),
                         prv.reset_index(drop=True)], axis=1)
    else:
        out = cur.drop(columns=["year"]).merge(
            prv.drop(columns=["year"]), on=group_col, how="outer"
        )

    out["yoy_pct"] = pd.NA
    mask = out["previous"].notna() & (out["previous"] != 0) & out["current"].notna()
    out.loc[mask, "yoy_pct"] = (
        (out.loc[mask, "current"] - out.loc[mask, "previous"])
        / out.loc[mask, "previous"] * 100
    ).round(2)
    return out


# ------------------------------------------------------------------------------
#  ■ 다단 집계 (도→시→읍면→리→관정 / 유역)
# ------------------------------------------------------------------------------
def aggregate(
    df: pd.DataFrame,
    level: str,
    metric: str = "volume_m3",
    extra_keys: list[str] | None = None,
    agg_func: str = "sum",
) -> pd.DataFrame:
    """동적 groupby — `level` 에 따라 행정 단계를 선택.

    Parameters
    ----------
    level : str
        AGG_KEYS 의 키 ('도전역','시','읍면동','리','관정','유역')
    metric : str
        집계 대상 컬럼 (기본 volume_m3)
    extra_keys : list[str]
        추가 그룹 키 (예: ['year'] 시계열 비교)
    agg_func : 'sum' | 'mean' | 'max' | 'min' | 'count'
    """
    if df.empty or metric not in df.columns:
        return pd.DataFrame()

    key = AGG_KEYS.get(level)
    extra = extra_keys or []

    if key is None:
        if not extra:
            val = getattr(df[metric], agg_func)()
            return pd.DataFrame({metric: [val]})
        return df.groupby(extra, dropna=False)[metric].agg(agg_func).reset_index()

    cols = [key] + extra if extra else [key]
    return df.groupby(cols, dropna=False)[metric].agg(agg_func).reset_index()


def aggregate_with_master(
    df_usage: pd.DataFrame,
    df_master: pd.DataFrame,
    level: str,
    extra_keys: list[str] | None = None,
) -> pd.DataFrame:
    """usage 와 master 를 join 후 집계.

    usage CSV 에는 well_eup/well_ri/watershed/authority 가 없으므로
    permit_no 로 master 와 merge 후 집계해야 한다.
    """
    if df_usage.empty or df_master.empty:
        return pd.DataFrame()

    join_cols = ["permit_no"]
    add = [c for c in ("authority", "well_eup", "well_ri", "watershed")
           if c in df_master.columns]
    merged = df_usage.merge(
        df_master[join_cols + add].drop_duplicates("permit_no"),
        on="permit_no", how="left",
    )
    return aggregate(merged, level=level, metric="volume_m3", extra_keys=extra_keys)


# ------------------------------------------------------------------------------
#  ■ 통계 탭용 KPI 집계
# ------------------------------------------------------------------------------
def kpi_active_count(df_master: pd.DataFrame) -> tuple[int, int]:
    """(active_count, inactive_count)."""
    if df_master.empty or "active" not in df_master.columns:
        return (0, 0)
    return (
        int(df_master["active"].fillna(False).sum()),
        int((~df_master["active"].fillna(False)).sum()),
    )


def kpi_total_volume(df_usage: pd.DataFrame, year: int | None = None) -> float:
    """연간 총 양수량(㎥). year 미지정 시 가장 최근 연도."""
    if df_usage.empty or "volume_m3" not in df_usage.columns:
        return 0.0
    if year is None and "year" in df_usage.columns:
        year = int(df_usage["year"].max())
    sub = df_usage[df_usage["year"] == year] if year is not None else df_usage
    return float(sub["volume_m3"].sum(skipna=True))


def kpi_avg_usage_rate(df_usage: pd.DataFrame, year: int | None = None) -> float | None:
    """평균 사용률(%) — 결측은 제외."""
    if df_usage.empty or "usage_rate" not in df_usage.columns:
        return None
    if year is None and "year" in df_usage.columns:
        year = int(df_usage["year"].max())
    sub = df_usage[df_usage["year"] == year] if year is not None else df_usage
    rates = pd.to_numeric(sub["usage_rate"], errors="coerce")
    if rates.notna().sum() == 0:
        return None
    return float(rates.mean(skipna=True))


def kpi_overuse_count(df_usage: pd.DataFrame, year: int | None = None) -> int:
    """취수허가량 초과 발생 관정×월 수."""
    if df_usage.empty:
        return 0
    if year is None and "year" in df_usage.columns:
        year = int(df_usage["year"].max())
    sub = df_usage[df_usage["year"] == year] if year is not None else df_usage
    mask = (
        sub["volume_m3"].notna()
        & sub["permit_m3m"].notna()
        & (sub["volume_m3"] > sub["permit_m3m"])
    )
    return int(mask.sum())


def kpi_quality_exceed_count(df_quality: pd.DataFrame, year: int | None = None) -> int:
    """반기 수질 5항목 중 1개라도 초과한 측정 건수."""
    if df_quality.empty:
        return 0
    sub = df_quality.copy()
    if year is not None and "year" in sub.columns:
        sub = sub[sub["year"] == year]
    flag_cols = [c for c in sub.columns if c.endswith("_exceed")]
    if not flag_cols:
        return 0
    any_exceed = sub[flag_cols].fillna(False).any(axis=1)
    return int(any_exceed.sum())


# ------------------------------------------------------------------------------
#  ■ 사용 빈도 높은 도우미: 단일 관정의 5년 시계열
# ------------------------------------------------------------------------------
def well_yearly_summary(
    df_usage: pd.DataFrame,
    permit_no: str,
    last_n_years: int = 5,
) -> pd.DataFrame:
    """단일 관정의 최근 N년 연 합계 + 평균 사용률.

    Returns columns: year, volume_m3, usage_rate, permit_m3m_total
    """
    if df_usage.empty:
        return pd.DataFrame()
    sub = df_usage[df_usage["permit_no"] == permit_no].copy()
    if sub.empty:
        return pd.DataFrame()

    yearly = sub.groupby("year", dropna=False).agg(
        volume_m3=("volume_m3", "sum"),
        usage_rate_mean=("usage_rate", "mean"),
        permit_m3m_max=("permit_m3m", "max"),
    ).reset_index()
    yearly["permit_m3y"] = yearly["permit_m3m_max"] * 12
    if not yearly.empty:
        max_year = int(yearly["year"].max())
        yearly = yearly[yearly["year"] >= max_year - last_n_years + 1]
    return yearly.reset_index(drop=True)
