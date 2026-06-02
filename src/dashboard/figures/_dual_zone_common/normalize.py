# ==============================================================================
#  파일명: src/dashboard/figures/_dual_zone_common/normalize.py
#  공용: master DataFrame 의 cluster · unit 컬럼 부여 (2순위 DRY 통합)
# ------------------------------------------------------------------------------
#  추출 출처:
#    - admin_dual_zone/data.py L13-40 normalize_admin (master+usage)
#    - ri_dual_zone/data.py    L27-55 _normalize_master_admin (master 만)
#
#  통합 동작:
#    - normalize_master(master, idempotent=True): cluster·unit 컬럼 부여.
#    - idempotent=True 이면 이미 두 컬럼이 있으면 조기 반환.
#    - .str.strip() 적용 — '대정읍 ' 같은 후행 공백 더티 데이터 정리 (ri 의
#      V7 변경 사항 admin 도 동기화).
# ==============================================================================
from __future__ import annotations

import pandas as pd


# 제주 본도 외 도서(島嶼) 읍·면 — 농업용 지하수 분석 대상에서 제외 (사용자
# 요청 2026-05-27). cluster·unit 을 None 으로 두면 aggregate_units 등의
# `.notna()` 필터에서 분자·분모 양쪽 모두 자동 제외된다.
#   제주 본도 외 도서: 우도면(우도), 추자면(추자도) — 둘 다 제외 (사용자 확정
#   2026-05-27).
EXCLUDED_ISLAND_EUP: set[str] = {"우도면", "추자면"}


def _cluster_of(row: pd.Series):
    e = row["eup_norm"]
    if e in EXCLUDED_ISLAND_EUP:
        return None
    if not e:
        return f"{row['well_si']} 미상"
    if str(e).endswith("동"):
        return f"{row['well_si']} 동지역"
    return f"{row['well_si']} {e}"


def _unit_of(row: pd.Series):
    if row["eup_norm"] in EXCLUDED_ISLAND_EUP:
        return None
    if str(row["eup_norm"]).endswith("동"):
        return row["eup_norm"]
    return row["ri_norm"] if row["ri_norm"] else None


def normalize_master(
    master: pd.DataFrame,
    *,
    idempotent: bool = True,
) -> pd.DataFrame:
    """master 에 cluster · unit 컬럼 부여. 사본 반환.

    Parameters
    ----------
    master : pd.DataFrame
        well_si, well_eup, well_ri 컬럼이 필요.
    idempotent : bool, default True
        True 이면 이미 cluster · unit 두 컬럼이 있을 때 그대로 사본 반환.
        False 이면 항상 재계산 (admin 의 기존 normalize_admin 호환용).

    Returns
    -------
    pd.DataFrame
        master + 'eup_norm', 'ri_norm', 'cluster', 'unit' 컬럼 부여본.
    """
    if idempotent and "cluster" in master.columns and "unit" in master.columns:
        return master.copy()

    out = master.copy()
    # .str.strip() — '대정읍 ' 후행 공백 정리 (ri 의 V7 변경, admin 도 동기화)
    out["eup_norm"] = out["well_eup"].fillna("").astype(str).str.strip()
    out["ri_norm"] = out["well_ri"].fillna("").astype(str).str.strip()
    out["cluster"] = out.apply(_cluster_of, axis=1)
    out["unit"] = out.apply(_unit_of, axis=1)
    return out
