"""행정 구역 Dual-Zone 외부 박스 뼈대.

데이터와 무관 — 12개 슬롯의 (x, y, width, height) 좌표만 계산.
박스 너비 ∝ 농지면적, 띠 높이 ∝ 시별 농지면적 합.

DRY: 공용 ``Slot`` dataclass + ``band_heights`` / ``build_cluster_band`` 는
``_dual_zone_common.layout`` 으로 분리 (2026-05-09).
"""
from __future__ import annotations

from dataclasses import dataclass

from .._dual_zone_common.layout import (   # noqa: F401  re-export Slot
    Slot,
    band_heights,
    build_cluster_band,
)
from .constants import ADMIN_AGRI_HA, JEJU_CLUSTERS, SEOG_CLUSTERS


@dataclass(frozen=True)
class Layout:
    """Dual-zone 전체 배치 — 제주(위) / 한라산 빈 띠 / 서귀포(아래)."""
    slots: "tuple[Slot, ...]"
    j_y0: float
    j_y1: float
    s_y0: float
    s_y1: float
    x_min: float
    x_max: float


def build_layout(*, page_w: float = 100.0, band_total_h: float = 5.4,
                 gap: float = 0.5) -> Layout:
    """제주시(위) / 서귀포시(아래) 두 띠의 슬롯 좌표를 계산.

    page_w     : 가로 캔버스 길이 (단위 free)
    band_total_h: 두 띠 합산 높이
    gap        : 한라산(빈 띠) 높이
    """
    j_h, s_h = band_heights(
        ADMIN_AGRI_HA, JEJU_CLUSTERS, SEOG_CLUSTERS, band_total_h,
    )
    s_y0 = 0.0
    s_y1 = s_y0 + s_h
    j_y0 = s_y1 + gap
    j_y1 = j_y0 + j_h

    slots = (
        build_cluster_band(JEJU_CLUSTERS, ADMIN_AGRI_HA,
                           y0=j_y0, h=j_h, total_w=page_w)
        + build_cluster_band(SEOG_CLUSTERS, ADMIN_AGRI_HA,
                             y0=s_y0, h=s_h, total_w=page_w)
    )
    return Layout(
        slots=tuple(slots),
        j_y0=j_y0, j_y1=j_y1,
        s_y0=s_y0, s_y1=s_y1,
        x_min=0.0, x_max=page_w,
    )
