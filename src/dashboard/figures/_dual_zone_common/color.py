# ==============================================================================
#  파일명: src/dashboard/figures/_dual_zone_common/color.py
#  공용: admin_dual_zone, ri_dual_zone 의 정규화·색상 헬퍼 (1순위 통합)
# ------------------------------------------------------------------------------
#  추출 출처:
#    - admin_dual_zone/renderer.py L34 _normalize  (단순 min-max)
#    - ri_dual_zone/renderer.py    L44 _vmin_vmax  (outlier 클립 분위수)
#    - ri_dual_zone/renderer.py    L64 _norm_t
#    - 양쪽 _slot_color, _short_name (100% 동일)
#
#  통합 동작:
#    - vmin_vmax(values, pct_clip=None): pct_clip None 이면 admin 동작(min/max),
#      tuple 이면 ri 동작(np.percentile).
#    - normalize_values(values, pct_clip=None): vmin_vmax + 각 value norm_t
#      매핑. NaN 은 0.5, 결과는 [0.0, 1.0] 클립.
#    - admin 의 기존 _normalize 도 클립 추가가 결과 동일 (admin 데이터에선
#      vmax 가 실제 최댓값이라 클립 영향 없음).
# ==============================================================================
from __future__ import annotations

from typing import Iterable

import numpy as np
import pandas as pd
from plotly.colors import sample_colorscale


def vmin_vmax(
    values: Iterable[float],
    pct_clip: tuple[int, int] | None = None,
) -> tuple[float, float]:
    """outlier 클립 분위수로 vmin/vmax 산출.

    pct_clip=None  → 단순 min/max (기존 admin 동작)
    pct_clip=(5,95) → 5~95 percentile (기존 ri 동작)
    """
    arr = np.array([np.nan if pd.isna(v) else float(v) for v in values],
                   dtype=float)
    valid = arr[~np.isnan(arr)]
    if len(valid) == 0:
        return 0.0, 1.0
    if pct_clip is None:
        vmin = float(valid.min())
        vmax = float(valid.max())
    else:
        lo, hi = pct_clip
        vmin = float(np.percentile(valid, lo))
        vmax = float(np.percentile(valid, hi))
    if vmax - vmin < 1e-9:
        vmax = vmin + 1.0
    return vmin, vmax


def norm_t(value: float, vmin: float, vmax: float) -> float:
    """단일 value 를 [0,1] 정규화. NaN → 0.5, 클립 범위 밖 → 끝값 고정."""
    if pd.isna(value):
        return 0.5
    if vmax - vmin < 1e-9:
        return 0.5
    t = (float(value) - vmin) / (vmax - vmin)
    return float(np.clip(t, 0.0, 1.0))


def normalize_values(
    values: Iterable[float],
    pct_clip: tuple[int, int] | None = None,
) -> tuple[list, float, float]:
    """value 리스트를 (norm_t 리스트, vmin, vmax) 로 매핑.

    기존 admin `_normalize(values)` 와 동등 (pct_clip 미지정).
    기존 ri `_vmin_vmax + _norm_t` 조합과도 동등 (pct_clip 지정).
    """
    vals = list(values)
    vmin, vmax = vmin_vmax(vals, pct_clip)
    norm = [norm_t(v, vmin, vmax) for v in vals]
    return norm, vmin, vmax


def slot_color(t: float, colorscale) -> str:
    """plotly colorscale 의 t (0~1) 위치 색상.

    Parameters
    ----------
    colorscale : str | list[list]
        plotly 내장 이름 ('RdYlBu', 'Viridis' 등) 또는
        custom stop list ([[0.0, 'rgb(...)'], [1.0, 'rgb(...)']]).
    """
    return sample_colorscale(colorscale, [t])[0]


# ============================================================================
#  "관정당 일 이용량" 전용 colorscale (사용자 요청 2026-05-15 → 2026-05-16 보강)
# ----------------------------------------------------------------------------
#  사용자 의도:
#    0    = 흰색-약간 grey (사용 적음 — 명확히 보이지만 데이터 없음과 구분)
#    400  = sky blue (낮음)
#    800  = dark navy (표준 임계 — 사용자 명시)
#    1200 = orange (많이 사용)
#    1600+= red (매우 많이 사용)
#
#  중요: 800 (navy) → 1200 (orange) 사이 RGB 직선보간은 t=0.625 에서
#  카키-진흙색(rgb(132,132,54)) 으로 떨어짐 (색상환 정반대 보간 문제).
#  해결: 800 직후(0.5001) 에 light-gold 점프 stop 을 두어 임계 명확화 +
#  흙탕물 색 제거. 사용자가 800 임계를 색 단절로 즉시 인지.
#
#  적용 범위: per_well_daily / per_well_monthly / intensity_ha MetricSpec
#  (fig23/24/25/27 + tab10 detail). 다른 metric (total_period, annual,
#  per_well_annual, n_wells) 은 "RdYlBu_r" 유지.
#
#  매핑은 cmin=0, cmax=1600 절대값 고정 전제 (per_well_daily 만).
#  per_well_monthly/intensity_ha 는 단위가 달라 자체 percentile vmax 사용
#  (색상 톤만 통일, 절대값 매핑 아님).
# ============================================================================
DAILY_USAGE_COLORSCALE: list[list] = [
    [0.0,    "rgb(245, 245, 245)"],  # near-white grey — 0 ㎥/공·일
    [0.25,   "rgb(135, 206, 235)"],  # sky blue        — 400
    [0.5,    "rgb(8, 48, 107)"],     # dark navy       — 800 (표준 임계)
    [0.5001, "rgb(255, 235, 100)"],  # light gold      — 800+ (점프, 임계 단절)
    [0.75,   "rgb(255, 140, 0)"],    # orange          — 1200 (많이 사용)
    [1.0,    "rgb(211, 47, 47)"],    # red             — 1600+ (매우 많이 사용)
]

# 절대값 고정 임계 — per_well_daily 만 사용.
DAILY_USAGE_VMIN: float = 0.0
DAILY_USAGE_VMAX: float = 1600.0

# 월 단위 환산 (사용자 정책 2026-05-22): per_well_monthly 의 절대 vmax 를
# per_well_daily 의 vmax × 30 (개월·일 환산) 으로 강제 → 일/월 단위 두 시각화
# (8-2 탭 map grid 와 fig27 dual-zone 등) 가 동일 색 계조 도메인 공유.
DAILY_USAGE_VMAX_MONTHLY: float = DAILY_USAGE_VMAX * 30.0   # = 48000


def short_name(cluster: str) -> str:
    """'제주시 한림읍' → '한림읍' (공백 첫 분리). 공백 없으면 그대로."""
    return cluster.split(" ", 1)[1] if " " in cluster else cluster
