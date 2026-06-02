"""마스터·이용량 → 클러스터 단위 집계.

ag_well_loader 의 long-format usage(컬럼: permit_no, year, month, volume_m3 …)을
입력으로 받는다. wide-format(Jan…Dec)이 들어오면 자동 변환.
"""
from __future__ import annotations

import pandas as pd

from .._dual_zone_common.normalize import normalize_master
from .constants import ADMIN_AGRI_HA, MONTHS_ABBR


def normalize_admin(master: pd.DataFrame, usage: pd.DataFrame
                    ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """master/usage에 cluster·unit 컬럼 부여.

    cluster·unit 부여 로직은 _dual_zone_common.normalize.normalize_master 와
    공용 (분석팀 권고 2026-05-09, 2순위 DRY 통합).
    """
    master = normalize_master(master, idempotent=False)
    usage = usage.merge(
        master[["permit_no", "cluster", "unit"]],
        on="permit_no", how="left",
    )
    return master, usage


def _annual_total_by_cluster(usage: pd.DataFrame) -> pd.Series:
    """usage → cluster별 (선택 기간 합계) ㎥. wide/long 모두 지원."""
    months = list(MONTHS_ABBR)
    if "volume_m3" in usage.columns:           # long-format
        return usage.groupby("cluster")["volume_m3"].sum()
    if all(m in usage.columns for m in months):  # wide-format
        return usage.groupby("cluster")[months].sum().sum(axis=1)
    raise KeyError(
        "usage 에 'volume_m3' 또는 12개 월 컬럼(Jan~Dec)이 필요합니다. "
        f"현재 컬럼: {list(usage.columns)}"
    )


def aggregate_clusters(master: pd.DataFrame, usage: pd.DataFrame,
                       *, active_permits: "set[str] | None" = None
                       ) -> pd.DataFrame:
    """클러스터(읍·면·동) 집계 → 메트릭 컬럼.

    반환 컬럼:
      total_period      : 선택 기간 누적 이용량 (㎥)
      annual            : 연평균 이용량 (㎥/년) = total_period / n_year
      per_well_annual   : 관정당 연이용량 (㎥/공·년) = annual / n
      per_well_monthly  : 관정당 월이용량 (㎥/공·월) = per_well_annual / 12
      per_well_daily    : 관정당 일이용량 (㎥/공·일) = per_well_annual / 365.25
      intensity_ha      : 단위면적 강도 (㎥/ha·년) = annual / 농지면적(ha)
      n                 : 클러스터 내 관정 수
      n_year            : 선택 기간 연도 수

    Parameters
    ----------
    active_permits : set[str] | None
        선택 분석 기간 내 이용량 합계 > 0 인 permit_no 집합. 주어지면 N
        분모를 이 집합으로 한정 — 「분석 기간 동안 사용 보고가 한 번도
        없는 관정」을 제외 (사용자 요청 2026-05-19). None 이면 기존 동작.
    """
    n_year = max(int(usage["year"].nunique()), 1)
    period_total = _annual_total_by_cluster(usage)

    # 사용자 요청 2026-05-19: N 분모를 사용 보고 관정만으로 한정.
    if active_permits is not None:
        master_for_n = master[
            master["permit_no"].astype(str).isin(active_permits)
        ]
    else:
        master_for_n = master
    cluster_n = master_for_n.groupby("cluster").size()
    out = pd.DataFrame({"total_period": period_total})
    out = out.merge(cluster_n.rename("n"),
                    left_index=True, right_index=True, how="left")
    out["n"] = out["n"].fillna(0).astype(int)
    out["annual"] = out["total_period"] / n_year
    out["per_well_annual"] = out["annual"] / out["n"].replace(0, pd.NA)
    out["per_well_monthly"] = out["per_well_annual"] / 12.0
    out["per_well_daily"] = out["per_well_annual"] / 365.25
    out["intensity_ha"] = out["annual"] / pd.Series(ADMIN_AGRI_HA)
    out["n_year"] = n_year
    return out
