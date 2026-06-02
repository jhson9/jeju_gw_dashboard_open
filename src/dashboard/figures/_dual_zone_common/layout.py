"""Dual-Zone 레이아웃 공용 부품.

admin_dual_zone (12 클러스터 박스) 와 ri_dual_zone (squarify 패킹) 가
공유하는 레이아웃 기초 — 면적 비례 띠 분할 + 슬롯 배치.

- ``Slot``                  : 공용 사각형 dataclass (admin Slot ↔ ri ClusterSlot 통합)
- ``band_heights``          : 제주·서귀포 두 띠 높이를 농지면적 합 비율로 분배
- ``build_cluster_band``    : 클러스터 슬롯을 면적 비례로 한 띠에 배치

이 모듈로 admin/ri 의 layout.py 가 중복했던 약 40줄 분량을 제거.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Type, TypeVar


@dataclass(frozen=True)
class Slot:
    """1개 읍·면·동 박스의 좌표·크기.

    admin 의 Slot 과 ri 의 ClusterSlot 을 공용화. ``side`` 는 ri 에서만
    의미 있고 admin 은 빈 문자열 default 사용.
    """
    cluster: str
    x: float
    y: float
    width: float
    height: float
    side: str = ""   # "top" | "bot" | "" (admin)

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


T = TypeVar("T", bound=Slot)


def band_heights(agri_dict: "dict[str, int]",
                 jeju_clusters: Iterable[str],
                 seog_clusters: Iterable[str],
                 band_total_h: float) -> "tuple[float, float]":
    """제주·서귀포 농지면적 합 비율로 두 띠 높이 분배.

    Returns
    -------
    (j_h, s_h) : 제주 띠 높이, 서귀포 띠 높이
    """
    j_total = sum(agri_dict[c] for c in jeju_clusters)
    s_total = sum(agri_dict[c] for c in seog_clusters)
    grand = j_total + s_total
    if grand <= 0:
        return 0.0, 0.0
    j_h = band_total_h * j_total / grand
    s_h = band_total_h * s_total / grand
    return j_h, s_h


def build_cluster_band(
    clusters: Iterable[str],
    agri_dict: "dict[str, int]",
    *,
    y0: float, h: float, total_w: float,
    side: str = "",
    slot_cls: "Type[T]" = Slot,
) -> "list[T]":
    """W → E 순서로 클러스터를 면적 비례 슬롯에 배치 — 1개 띠.

    Parameters
    ----------
    clusters    : 띠에 배치할 클러스터 이름 (W → E 순서).
    agri_dict   : 클러스터별 농지면적 (ha).
    y0, h       : 띠의 y 좌표·높이.
    total_w     : 가로 캔버스 길이.
    side        : "top" | "bot" — ri 의 ClusterSlot 에 들어가는 마커. admin 은 "".
    slot_cls    : 반환 슬롯 dataclass (default 공용 Slot). admin/ri 가 자기
                  dataclass 로 받으려면 이 인자에 자기 타입 전달.
    """
    cl_list = list(clusters)
    total = sum(agri_dict[c] for c in cl_list)
    if total <= 0 or total_w <= 0:
        return []
    out: "list[T]" = []
    x = 0.0
    for c in cl_list:
        w = total_w * agri_dict[c] / total
        out.append(slot_cls(
            cluster=c, x=x, y=y0, width=w, height=h, side=side,
        ))
        x += w
    return out


__all__ = ["Slot", "band_heights", "build_cluster_band"]
