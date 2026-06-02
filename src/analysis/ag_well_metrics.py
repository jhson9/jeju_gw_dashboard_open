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
#  ■ 활성 사용 관정 집합 (사용자 요청 2026-05-19)
# ------------------------------------------------------------------------------
def active_user_permits(
    usage_period: pd.DataFrame,
    min_annual_m3: "float | None" = None,
) -> set[str]:
    """분석 기간 내 모집단(연간 이용량 ≥ ``min_annual_m3``) permit_no 집합.

    2026-05-28 (P2-1) 변경: 기본 임계가 ``POPULATION_MIN_ANNUAL_M3`` (=100㎥) 로
    승격. 이전엔 `sum > 0` 만 검사하여 휴면 관정도 포함했으나, Tab23 의 모집단
    정의(100㎥)와 일치시켜 KPI/지도/12장의 분모를 통일.

    하위 호환: ``min_annual_m3=0`` 을 명시 전달하면 과거 정의(any usage) 로 복귀.

    Parameters
    ----------
    usage_period : pd.DataFrame
        분석 기간(year_tuple)으로 이미 필터된 usage long-format.
        permit_no, volume_m3 컬럼 필수.
    min_annual_m3 : float, optional
        연간 이용량 임계(㎥). None 이면 ``POPULATION_MIN_ANNUAL_M3`` 사용.

    Returns
    -------
    set[str]
        permit_no 의 집합 (string). 빈 DataFrame 이면 빈 set.
    """
    if usage_period is None or usage_period.empty:
        return set()
    if "volume_m3" not in usage_period.columns \
            or "permit_no" not in usage_period.columns:
        return set()
    threshold = float(min_annual_m3) if min_annual_m3 is not None else POPULATION_MIN_ANNUAL_M3
    if threshold <= 0:
        # 과거 정의: sum > 0 인 관정 (휴면 관정 포함)
        by = usage_period.groupby("permit_no")["volume_m3"].sum(min_count=1)
        return {str(p) for p in by[by > 0].index}
    # 신정의(2026-05-28): 연 ≥ threshold ㎥. population_permits_by_year 와 일치.
    return population_permits_by_year(usage_period, min_annual_m3=threshold)


# ------------------------------------------------------------------------------
#  ■ 모집단 규칙: 연간 이용량 임계 (사용자 요청 2026-05-27)
# ------------------------------------------------------------------------------
#  정책: "관정 모집단은 이용량 유무로 잡는다. 어떤 해의 연간 총이용량이
#         100㎥(=100톤) 미만이면 그 해의 대상 관정에서 제외하고, 100㎥ 이상이면
#         그 해에 '살아있는' 관정으로 본다."
#  → (permit_no, year) 단위로 판정. 분자(이용량 합계)와 분모(관정 수)가 항상
#    같은 집합을 쓰도록, 집계 이전에 long-format 에서 미달 (관정,연도) 행을 제거.
POPULATION_MIN_ANNUAL_M3: float = 100.0


def filter_population_by_annual_usage(
    df_usage: pd.DataFrame,
    min_annual_m3: float = POPULATION_MIN_ANNUAL_M3,
) -> pd.DataFrame:
    """(permit_no, year) 별 연간 이용량이 ``min_annual_m3`` 미만인 행을 제거.

    이용량 분석의 '대상 관정 모집단' 을 정의하는 단일 진입점. 이 필터를 거친
    DataFrame 으로 합계·평균·관정수를 모두 계산하면 분자·분모가 자동으로 같은
    (관정,연도) 집합을 공유한다.

    - 100톤 ≈ 100㎥ (물 1톤 = 1㎥). 기준 미만 = 사실상 미사용/휴면 → 제외.
    - year 컬럼이 없으면 permit_no 전체 합계로 판정(연도 구분 없음).

    원본은 수정하지 않고 사본을 반환.
    """
    if df_usage is None or df_usage.empty:
        return df_usage
    if "volume_m3" not in df_usage.columns or "permit_no" not in df_usage.columns:
        return df_usage

    keys = ["permit_no", "year"] if "year" in df_usage.columns else ["permit_no"]
    annual = df_usage.groupby(keys)["volume_m3"].transform(
        lambda s: s.sum(min_count=1)
    )
    keep = annual >= float(min_annual_m3)
    return df_usage[keep.fillna(False)].copy()


def population_permits_by_year(
    df_usage: pd.DataFrame,
    min_annual_m3: float = POPULATION_MIN_ANNUAL_M3,
) -> set[str]:
    """모집단 규칙(연 ``min_annual_m3`` 이상)을 만족하는 permit_no 집합.

    어느 한 해라도 기준을 넘은 관정이면 포함(분석기간 내 '살아있던' 관정).
    aggregate_units 등에 넘길 ``active_permits`` 로 사용.
    """
    filtered = filter_population_by_annual_usage(df_usage, min_annual_m3)
    if filtered is None or filtered.empty or "permit_no" not in filtered.columns:
        return set()
    return {str(p) for p in filtered["permit_no"].unique()}


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
    """관정 평균 사용률(%) — 관정×월 단위 usage_rate 의 비가중 평균.

    주의 (L3, 2026-05-27): 이것은 '비율의 평균(average-of-ratios)' 으로,
    각 관정×월을 동등 가중한다. 따라서 소형 관정·소분모 이상치에 민감하며
    "지역 전체가 허가량 대비 얼마나 쓰는가" 라는 시스템 수준 지표로는
    오해를 줄 수 있다. 시스템 수준 지표는 `kpi_system_usage_rate`
    (Σ양수량 / Σ허가량) 를 사용할 것. 본 함수는 '관정당 평균' 의미일 때만 사용.
    """
    if df_usage.empty or "usage_rate" not in df_usage.columns:
        return None
    if year is None and "year" in df_usage.columns:
        year = int(df_usage["year"].max())
    sub = df_usage[df_usage["year"] == year] if year is not None else df_usage
    rates = pd.to_numeric(sub["usage_rate"], errors="coerce")
    if rates.notna().sum() == 0:
        return None
    return float(rates.mean(skipna=True))


def kpi_system_usage_rate(df_usage: pd.DataFrame, year: int | None = None) -> float | None:
    """시스템 사용률(%) = Σ양수량 / Σ허가량 × 100 (양수가중).

    L3(2026-05-27) 추가. `kpi_avg_usage_rate` 의 '비율의 평균' 과 달리,
    총량 기준으로 산출해 대형 관정의 비중을 올바르게 반영한다. 지역/전체
    수준의 '허가량 대비 실사용' 헤드라인 지표는 이 함수를 쓰는 것이 옳다.

    유효한(허가량 > 0, 양수량 결측 아님) 행만 분자·분모에 포함한다.
    분모가 0 이거나 유효 행이 없으면 None.
    """
    if df_usage.empty \
            or "volume_m3" not in df_usage.columns \
            or "permit_m3m" not in df_usage.columns:
        return None
    if year is None and "year" in df_usage.columns:
        year = int(df_usage["year"].max())
    sub = df_usage[df_usage["year"] == year] if year is not None else df_usage

    vol = pd.to_numeric(sub["volume_m3"], errors="coerce")
    permit = pd.to_numeric(sub["permit_m3m"], errors="coerce")
    valid = vol.notna() & permit.notna() & (permit > 0)
    if not valid.any():
        return None
    denom = float(permit[valid].sum())
    if denom <= 0:
        return None
    return float(vol[valid].sum() / denom * 100.0)


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
