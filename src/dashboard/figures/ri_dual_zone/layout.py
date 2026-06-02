"""리·동 Dual-Zone 외부 박스 + squarify 패킹 좌표 계산.

데이터와 무관 — `units_df` 의 값으로 (x, y, w, h) 좌표만 계산해 둔다.

  • 6 클러스터 슬롯 × 2 띠 = 12 ClusterSlot
  • 각 클러스터 슬롯 안에 5공 이상 리·동을 squarify 패킹 → UnitSlot
  • UnitLayout 은 unit_slots, cluster_slots 두 리스트와 띠 좌표를 보관
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

import numpy as np
import pandas as pd

try:
    import squarify  # type: ignore
    _HAS_SQUARIFY = True
except ImportError:  # pragma: no cover
    squarify = None  # type: ignore
    _HAS_SQUARIFY = False

from .._dual_zone_common.layout import (
    Slot as ClusterSlot,
    band_heights,
    build_cluster_band,
)
from .constants import ADMIN_AGRI_HA, JEJU_CLUSTERS, SEOG_CLUSTERS


# ──────────────────────────────────────────────────────────────────
#  데이터 클래스 — ClusterSlot 은 공용 Slot 으로 통합 (2026-05-09 DRY).
#  UnitSlot 은 squarify idx + area property 가 필요해 ri 전용 유지.
# ──────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class UnitSlot:
    """1개 리·동 사각형."""
    cluster: str
    unit: str
    idx: int        # units_df 의 원본 index (renderer 에서 행 lookup)
    x: float
    y: float
    width: float
    height: float

    @property
    def cx(self) -> float:
        return self.x + self.width / 2

    @property
    def cy(self) -> float:
        return self.y + self.height / 2

    @property
    def x1(self) -> float:
        return self.x + self.width

    @property
    def y1(self) -> float:
        return self.y + self.height

    @property
    def area(self) -> float:
        return self.width * self.height


# ClusterSlot 은 _dual_zone_common.layout 의 Slot alias (위 import 참조).


@dataclass(frozen=True)
class UnitLayout:
    """리·동 dual-zone 전체 배치."""
    unit_slots: tuple[UnitSlot, ...]
    cluster_slots: tuple[ClusterSlot, ...]
    j_y0: float
    j_y1: float
    s_y0: float
    s_y1: float
    x_min: float
    x_max: float


# ──────────────────────────────────────────────────────────────────
#  내부 헬퍼 — _cluster_slots_band / _band_heights 는 _dual_zone_common.layout
#  으로 통합 (2026-05-09 DRY). build_cluster_band / band_heights 사용.
# ──────────────────────────────────────────────────────────────────
def _squarify_in(sub_df: pd.DataFrame, slot: ClusterSlot, area_col: str,
                 ) -> list[UnitSlot]:
    """클러스터 슬롯 안에 sub_df 의 행을 squarify packed 사각형으로."""
    if not _HAS_SQUARIFY:
        raise RuntimeError(
            "squarify 라이브러리가 필요합니다. `pip install squarify` 로 설치하세요."
        )
    if len(sub_df) == 0 or slot.width <= 0 or slot.height <= 0:
        return []
    sizes = sub_df[area_col].values.astype(float)
    if sizes.sum() <= 0:
        return []
    order = np.argsort(-sizes)
    sub_sorted = sub_df.iloc[order]
    sizes_sorted = sizes[order]
    norm = squarify.normalize_sizes(sizes_sorted, slot.width, slot.height)
    rects = squarify.squarify(norm, slot.x, slot.y, slot.width, slot.height)
    out: list[UnitSlot] = []
    for (idx, _), r in zip(sub_sorted.iterrows(), rects):
        out.append(UnitSlot(
            cluster=slot.cluster,
            unit=str(sub_sorted.loc[idx, "unit"]),
            idx=int(idx),
            x=float(r["x"]),
            y=float(r["y"]),
            width=float(r["dx"]),
            height=float(r["dy"]),
        ))
    return out


# ──────────────────────────────────────────────────────────────────
#  공개 API
# ──────────────────────────────────────────────────────────────────
def build_unit_layout(units_df: pd.DataFrame, *,
                      agri_dict: dict[str, int] = ADMIN_AGRI_HA,
                      page_w: float = 100.0,
                      band_total_h: float = 9.0,
                      gap: float = 0.5,
                      area_col: str = "est_area_ha",
                      ) -> UnitLayout:
    """5공 이상 리·동을 클러스터 슬롯 안에 squarify 패킹한 좌표를 계산.

    Parameters
    ----------
    units_df : DataFrame
        `aggregate_units` 의 결과 (cluster, unit, est_area_ha 컬럼 필요).
    agri_dict : dict[str, int]
        클러스터별 농지면적 (ha) — 슬롯 너비·띠 높이 계산에 사용.
    page_w : float
        가로 캔버스 길이.
    band_total_h : float
        제주 + 서귀포 두 띠의 합산 높이 (한라산 빈 띠는 별도 gap).
    gap : float
        한라산 빈 띠 높이.
    area_col : str
        squarify 가 사용할 면적 컬럼.
    """
    j_h, s_h = band_heights(agri_dict, JEJU_CLUSTERS, SEOG_CLUSTERS, band_total_h)
    s_y0 = 0.0
    s_y1 = s_y0 + s_h
    j_y0 = s_y1 + gap
    j_y1 = j_y0 + j_h

    cluster_slots: list[ClusterSlot] = []
    cluster_slots += build_cluster_band(JEJU_CLUSTERS, agri_dict,
                                         y0=j_y0, h=j_h, total_w=page_w,
                                         side="top")
    cluster_slots += build_cluster_band(SEOG_CLUSTERS, agri_dict,
                                         y0=s_y0, h=s_h, total_w=page_w,
                                         side="bot")

    unit_slots: list[UnitSlot] = []
    for cs in cluster_slots:
        sub = units_df[units_df["cluster"] == cs.cluster]
        unit_slots += _squarify_in(sub, cs, area_col)

    return UnitLayout(
        unit_slots=tuple(unit_slots),
        cluster_slots=tuple(cluster_slots),
        j_y0=j_y0, j_y1=j_y1,
        s_y0=s_y0, s_y1=s_y1,
        x_min=0.0, x_max=page_w,
    )


def build_cluster_only_layout(agri_dict: dict[str, int] = ADMIN_AGRI_HA, *,
                              page_w: float = 100.0,
                              band_total_h: float = 6.6,
                              gap: float = 0.5,
                              ) -> UnitLayout:
    """fig25 용 — 클러스터 슬롯만, unit_slots 는 빈 tuple.

    행정구역 단위(읍·면·동) 12개 박스만 외곽선으로 그리고 싶을 때 사용.
    """
    j_h, s_h = band_heights(agri_dict, JEJU_CLUSTERS, SEOG_CLUSTERS, band_total_h)
    s_y0 = 0.0
    s_y1 = s_y0 + s_h
    j_y0 = s_y1 + gap
    j_y1 = j_y0 + j_h

    cluster_slots: list[ClusterSlot] = []
    cluster_slots += build_cluster_band(JEJU_CLUSTERS, agri_dict,
                                         y0=j_y0, h=j_h, total_w=page_w,
                                         side="top")
    cluster_slots += build_cluster_band(SEOG_CLUSTERS, agri_dict,
                                         y0=s_y0, h=s_h, total_w=page_w,
                                         side="bot")

    return UnitLayout(
        unit_slots=tuple(),
        cluster_slots=tuple(cluster_slots),
        j_y0=j_y0, j_y1=j_y1,
        s_y0=s_y0, s_y1=s_y1,
        x_min=0.0, x_max=page_w,
    )


__all__ = [
    "UnitSlot",
    "ClusterSlot",
    "UnitLayout",
    "build_unit_layout",
    "build_cluster_only_layout",
]
