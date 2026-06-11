"""리·동 Dual-Zone 상수.

대부분 admin_dual_zone.constants 를 재사용하고, fig24·fig26 에서 쓰는
한글 월 이름·관정 수 임계값·기본 컬러스케일만 추가로 노출.
"""
from __future__ import annotations

from ..admin_dual_zone.constants import (
    ADMIN_AGRI_HA,
    CLUSTER_ASOS,
    JEJU_CLUSTERS,
    MONTHS_ABBR,
    SEOG_CLUSTERS,
)

# 한글 월 라벨 (annual breakdown 등에서 사용)
MONTHS_KR: tuple[str, ...] = (
    "1월", "2월", "3월", "4월", "5월", "6월",
    "7월", "8월", "9월", "10월", "11월", "12월",
)

# V7 마이그레이션: 5공 → 1공 임계 + 동지역 50ha 임계 (cowork 검증 완료)
# 5공 필터에서 누락되던 70개 의미있는 농지 권역(176공·~10,800ha)을 모두 포함.
MIN_WELLS: int = 1
MIN_AGRI_HA_DONG: float = 50.0   # 동지역만 적용되는 최소 농지면적 (ha)

# 0공 농지 권역 — master.csv 에 관정은 없으나 인접 상류부에서 공급되는 농지.
# cowork zero_well_ri_analysis 결과:
#   • 우도면(연평리 등) / 추자면 — 지하수 이용량 조사 제외 (자동 제외)
#   • 교래리 / 오라2동 / 아라2동 — 산간·골프장 등 비농지 (자동 제외)
#   • 하도리(구좌읍) — 해안 농지 200ha, 상류부 관정에서 공급 → 회색·빗금 박스
# cx/cy 는 squarify 가 사용하지 않아 0.0 안전 (data.py L160 참고).
MANUAL_NO_WELL_UNITS: tuple[dict, ...] = (
    {
        "cluster":     "제주시 구좌읍",
        "unit":        "하도리",
        "est_area_ha": 200.0,
        "cx":          0.0,
        "cy":          0.0,
        "note":        "0공 — 상류부 관정에서 농업용수 공급",
    },
)

# fig24·26 의 기본 컬러스케일 (관정당 사용량: 청 → 황 → 적)
RDYL_R: str = "RdYlBu_r"

# 0공 unit 시각화 — 회색 + 경사 빗금 (matplotlib hatch='///' 와 동등)
NO_WELL_FILL: str = "#D6D6D6"
NO_WELL_PATTERN: dict = dict(
    shape="/", fgcolor="rgba(80,80,80,0.55)",
    fgopacity=0.55, size=6, solidity=0.35,
)

__all__ = [
    "ADMIN_AGRI_HA",
    "CLUSTER_ASOS",
    "JEJU_CLUSTERS",
    "MONTHS_ABBR",
    "SEOG_CLUSTERS",
    "MONTHS_KR",
    "MIN_WELLS",
    "MIN_AGRI_HA_DONG",
    "MANUAL_NO_WELL_UNITS",
    "RDYL_R",
    "NO_WELL_FILL",
    "NO_WELL_PATTERN",
]
