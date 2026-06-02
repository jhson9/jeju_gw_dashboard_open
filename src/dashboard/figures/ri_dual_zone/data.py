"""마스터·이용량 → 리·동 단위 집계.

`_v6_common.aggregate_units` 의 wide-format(Jan~Dec) 패턴을 plotly 환경으로
이식. ag_well_loader 가 long-format 으로 반환하므로 내부에서 pivot 해
연평균 → 관정당 → 추정 농지면적까지 채워서 돌려준다.
"""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pandas as pd

from .._dual_zone_common.normalize import normalize_master
from .constants import (
    ADMIN_AGRI_HA,
    MANUAL_NO_WELL_UNITS,
    MIN_AGRI_HA_DONG,
    MIN_WELLS,
    MONTHS_ABBR,
)


# ──────────────────────────────────────────────────────────────────
#  마스터 정규화 — _dual_zone_common.normalize.normalize_master 와 공용.
#  이 wrapper 는 tab22_ag_usage_detail.py 가 import 하는 공개 시그니처를
#  보존하기 위해 유지 (메모리 보호 규칙).
# ──────────────────────────────────────────────────────────────────
def _normalize_master_admin(master: pd.DataFrame) -> pd.DataFrame:
    """master 에 cluster·unit 컬럼 부여 (이중 정규화 방지)."""
    return normalize_master(master, idempotent=True)


# ──────────────────────────────────────────────────────────────────
#  long → wide pivot helper
# ──────────────────────────────────────────────────────────────────
_MONTH_NUM_TO_ABBR = dict(zip(range(1, 13), MONTHS_ABBR))


def _to_wide_by_unit(usage: pd.DataFrame) -> pd.DataFrame:
    """long-format usage → (cluster, unit) × (Jan..Dec) wide DataFrame.

    long 또는 이미 wide 인 경우 모두 지원.
    """
    months = list(MONTHS_ABBR)
    # 이미 wide 면 (cluster, unit) 합으로 바로 반환
    if all(m in usage.columns for m in months):
        wide = (usage.groupby(["cluster", "unit"])[months]
                .sum())
        return wide

    if "volume_m3" not in usage.columns:
        raise KeyError(
            "usage 에 'volume_m3' 또는 12개 월 컬럼(Jan~Dec)이 필요합니다. "
            f"현재 컬럼: {list(usage.columns)}"
        )

    df = usage.copy()
    df["month_abbr"] = df["month"].map(_MONTH_NUM_TO_ABBR)
    df = df[df["month_abbr"].notna()]
    pivot = (df.pivot_table(
        index=["cluster", "unit"],
        columns="month_abbr",
        values="volume_m3",
        aggfunc="sum",
        fill_value=0.0,
    ))
    # 빈 컬럼 보정 — 12개 월 모두 존재하도록
    for m in months:
        if m not in pivot.columns:
            pivot[m] = 0.0
    return pivot[months]


# ──────────────────────────────────────────────────────────────────
#  메인: aggregate_units
# ──────────────────────────────────────────────────────────────────
def aggregate_units(master: pd.DataFrame, usage: pd.DataFrame, *,
                    min_wells: int = MIN_WELLS,
                    min_agri_ha: float = 0.0,
                    min_agri_ha_dong: float = MIN_AGRI_HA_DONG,
                    include_manual: bool = True,
                    active_permits: "set[str] | None" = None) -> pd.DataFrame:
    """리·동 단위 집계 — `_v6_common.aggregate_units` 와 동등 결과.

    V7 마이그레이션 (cowork 검증 완료):
      • min_wells 기본 5 → 1 (1공 이상 모두 포함)
      • min_agri_ha_dong 추가 — 동지역만 50ha 이상으로 도심 농지 미미 동 자동 제외
      • MANUAL_NO_WELL_UNITS — 0공 농지 권역(예: 하도리) 수동 추가 (n=0, NaN 통계)

    Parameters
    ----------
    master : DataFrame
        cluster·unit 컬럼 필요 (없으면 자동 부여).
    usage : DataFrame
        long-format(volume_m3) 또는 wide-format(Jan~Dec). cluster·unit 컬럼이
        없으면 master 와 permit_no 로 merge 해 부여한다.
    min_wells : int
        관정 수 임계값 (default 1 — 1공 이상 모두).
    min_agri_ha : float
        모든 unit 의 최소 추정 농지면적 (ha) (default 0 — 미적용).
    min_agri_ha_dong : float
        동지역(`cluster.endswith("동지역")`)에만 적용되는 농지 임계 (default 50).
    include_manual : bool
        True 이면 MANUAL_NO_WELL_UNITS (하도리 등) 를 0공 row 로 append.
    active_permits : set[str] | None
        선택 분석 기간 내 이용량 합계 > 0 인 permit_no 집합.
        주어지면 N(관정수) · per_well_* 분모를 이 집합으로 한정 — 「분석
        기간 동안 사용 보고가 한 번도 없는 관정」을 분모에서 제외 (사용자
        요청 2026-05-19). None 이면 기존 동작 (전체 관정).

    Returns
    -------
    DataFrame columns
        cluster, unit, n, cx, cy,
        Jan..Dec, annual, per_well_annual,
        Jan_pw..Dec_pw, est_area_ha, intensity_ha
    """
    # 0) 마스터에 cluster/unit 보장
    if "cluster" not in master.columns or "unit" not in master.columns:
        master = _normalize_master_admin(master)

    # 1) usage 에 cluster/unit 보장
    if "cluster" not in usage.columns or "unit" not in usage.columns:
        usage = usage.merge(
            master[["permit_no", "cluster", "unit"]],
            on="permit_no", how="left",
        )

    # 1.5) 활성 사용 관정 필터 — N 분모용 master 사본 (사용자 요청 2026-05-19)
    #   active_permits 가 주어지면 그 집합에 속한 관정만 unit_meta n 계산에
    #   사용. usage 측은 그대로 두어 분자(annual 등) 는 모든 사용 보고가
    #   반영되도록 한다 (분자가 0인 비사용 관정은 자동으로 영향 없음).
    if active_permits is not None:
        master_for_n = master[
            master["permit_no"].astype(str).isin(active_permits)
        ]
    else:
        master_for_n = master

    # 2) 메타 (n, cx, cy)
    unit_meta = (master_for_n[master_for_n["unit"].notna()]
                 .groupby(["cluster", "unit"])
                 .agg(n=("permit_no", "count"),
                      cx=("coord_x", "mean"),
                      cy=("coord_y", "mean"))
                 .reset_index())

    # 3) 연평균 wide
    n_year = max(int(usage["year"].nunique()), 1) if "year" in usage.columns else 1
    use_filtered = usage[usage["unit"].notna()]
    wide = _to_wide_by_unit(use_filtered)
    months = list(MONTHS_ABBR)
    use_g = wide.copy()
    for m in months:
        use_g[m] = use_g[m] / n_year
    use_g["annual"] = use_g[months].sum(axis=1)

    # 4) 메타와 합치기
    use_g = use_g.merge(
        unit_meta.set_index(["cluster", "unit"]),
        left_index=True, right_index=True, how="inner",
    )

    # 5) per_well_annual + per_well_monthly/daily + 월별 per-well
    use_g["per_well_annual"] = use_g["annual"] / use_g["n"]
    use_g["per_well_monthly"] = use_g["per_well_annual"] / 12.0
    use_g["per_well_daily"] = use_g["per_well_annual"] / 365.25
    # total_period — 선택 기간 합계 (annual × n_year). admin_dual_zone 과 동일.
    use_g["total_period"] = use_g["annual"] * n_year
    for m in months:
        use_g[f"{m}_pw"] = use_g[m] / use_g["n"]

    # 6) 필터 — min_wells & est_area_ha (전체 임계 + 동지역 추가 임계)
    #    est_area_ha 는 cluster_n 기준 계산이라 필터 전에 미리 채운다.
    #    (L7 수정 2026-05-27) cluster_n 분모를 unit n 과 동일한 모집단
    #    (master_for_n)으로 산출 → 하위 unit 면적 배분의 합이 클러스터
    #    총면적과 일치(분자=n, 분모=cluster_n 모집단 통일).
    cluster_n = master_for_n.groupby("cluster").size()

    use_g = use_g.reset_index()
    # 벡터화 — row-wise apply 2회 제거. ADMIN_AGRI_HA·cluster_n 매핑 후 element 산술
    cluster = use_g["cluster"]
    agri_ha = cluster.map(ADMIN_AGRI_HA).fillna(0.0)
    denom = cluster.map(cluster_n).fillna(0).astype(float)
    use_g["est_area_ha"] = np.where(
        denom > 0, agri_ha * use_g["n"] / denom.replace(0, np.nan), 0.0
    )

    keep = ((use_g["n"] >= min_wells)
            & (use_g["est_area_ha"] >= min_agri_ha))
    is_dong = use_g["cluster"].astype(str).str.endswith("동지역")
    keep = keep & (~is_dong | (use_g["est_area_ha"] >= min_agri_ha_dong))
    units = use_g[keep].reset_index(drop=True)

    # 7) intensity_ha — annual / est_area_ha (벡터화)
    area = units["est_area_ha"].astype(float)
    units["intensity_ha"] = np.where(
        area > 0, units["annual"].astype(float) / area.replace(0, np.nan), np.nan
    )

    # 8) MANUAL_NO_WELL_UNITS — 0공 농지 권역 (하도리 등) 수동 추가
    if include_manual and MANUAL_NO_WELL_UNITS:
        months = list(MONTHS_ABBR)
        manual_rows: list[dict] = []
        for spec in MANUAL_NO_WELL_UNITS:
            row: dict = {
                "cluster":         spec["cluster"],
                "unit":            spec["unit"],
                "n":               0,
                "cx":              float(spec.get("cx", 0.0)),
                "cy":              float(spec.get("cy", 0.0)),
                "annual":          0.0,
                "per_well_annual": np.nan,
                "est_area_ha":     float(spec["est_area_ha"]),
                "intensity_ha":    np.nan,
            }
            for m in months:
                row[m] = 0.0
                row[f"{m}_pw"] = np.nan
            manual_rows.append(row)
        if manual_rows:
            manual_df = pd.DataFrame(manual_rows)
            # 컬럼 순서를 units 와 정렬 (없는 컬럼은 NaN 으로 채워짐)
            units = pd.concat([units, manual_df],
                              ignore_index=True, sort=False)

    return units


# ──────────────────────────────────────────────────────────────────
#  표고 200m 이하 농지 추정 — _v6_common.admin_below200_ha
# ──────────────────────────────────────────────────────────────────
def admin_below200_ha(master: pd.DataFrame) -> dict[str, int]:
    """200m 이하 농지면적 추정 — 클러스터별 (elevation_m ≤ 200) 비율 적용.

    cluster 컬럼이 없으면 자동 부여.
    """
    if "cluster" not in master.columns:
        master = _normalize_master_admin(master)

    out: dict[str, int] = {}
    for c, ha in ADMIN_AGRI_HA.items():
        sub = master[master["cluster"] == c]
        ratio = float((sub["elevation_m"] <= 200).mean()) if len(sub) else 0.85
        out[c] = round(ha * ratio)
    return out


# ──────────────────────────────────────────────────────────────────
#  ASOS 월·연 강수량 — fig27 dual-zone monthly small multiples 용
# ──────────────────────────────────────────────────────────────────
def load_asos_monthly() -> tuple[pd.DataFrame, pd.Series]:
    """ASOS 월·연 강수량 로딩. (monthly_df, annual_series) 반환.

    데이터 없으면 빈 DataFrame/Series 반환 (fig27 이 옵션처리).

    경로 우선순위
    -------------
    1) ``$JEJU_DATA_ROOT/data/ASOS/jeju_asos_daily.csv``
    2) ``<프로젝트 루트>/data/ASOS/jeju_asos_daily.csv``
       (data.py 가 src/dashboard/figures/ri_dual_zone 안에 있으므로
        ``parents[4]`` 가 프로젝트 루트)
    """
    data_root = Path(os.environ.get(
        "JEJU_DATA_ROOT",
        str(Path(__file__).resolve().parents[4]),
    ))
    asos_path = data_root / "data" / "ASOS" / "jeju_asos_daily.csv"
    if not asos_path.exists():
        return pd.DataFrame(), pd.Series(dtype=float)
    rain = pd.read_csv(asos_path, encoding="utf-8-sig")
    rain.columns = ["station", "date", "precip", "t_avg", "t_min", "t_max"]
    rain["date"] = pd.to_datetime(rain["date"])
    rain["year"] = rain["date"].dt.year
    rain["month"] = rain["date"].dt.month
    rain = rain[(rain["year"] >= 2017) & (rain["year"] <= 2025)]
    monthly = (rain.groupby(["station", "month"])["precip"]
               .sum().unstack().div(rain.groupby("station")["year"].nunique(),
                                    axis=0))
    monthly.columns = list(MONTHS_ABBR)
    annual = monthly.sum(axis=1)
    return monthly, annual


__all__ = [
    "_normalize_master_admin",
    "aggregate_units",
    "admin_below200_ha",
    "load_asos_monthly",
]
