# ==============================================================================
#  파일명: src/dashboard/tabs/_dod_helpers.py
#  모듈: tab36/tab37 (DoD 시계열 분석 — 실험적) 공용 헬퍼
# ------------------------------------------------------------------------------
#  사용자 요청 (2026-06-03):
#    - tab34/35 원본 보존 + 사본으로 tab36/37 생성 → DoD 기능 추가
#    - 만족 시 tab34/35 와 통합 (별도 탭 → 토글 버튼 통합 옵션)
#
#  20-에이전트 합의 결과:
#    1) 농업기반시설(저수조·송수관·옹벽) 점검 워크플로 지원
#    2) DJI Terra DSM RTK 편향 보정 — plane-fit 안정영역 0 보정
#    3) DSM 차분 = numpy 픽셀별 차이, RdBu_r colormap (±vmax = p98)
#    4) 시뮬레이션 모드 (L=R) → Δ=0 + 데모용 미세 노이즈
#    5) Streamlit @st.cache_data 로 (mission_id, mission_id, dsm_mtime) 키 캐싱
#    6) Leaflet/Cesium 양쪽 viewer 위 PNG ImageryLayer overlay
#    7) 실데이터 도착 시 자동 전환 (DEMO_MODE 우회 없이 normal path)
#
#  관련 메모리:
#    [[project-drone-dod-experimental-36-37]] tab36/37 실험 (DoD 추가)
#    [[project-drone-purpose]] 시계열 변화 감지가 드론 주요 목적
# ==============================================================================
from __future__ import annotations

import hashlib
import logging
import math
from pathlib import Path
from typing import Optional

import streamlit as st

from src.drone.registry import Mission

_logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────
#  DoD PNG 산출 디렉터리 — 미션 데이터 디렉터리 옆 (derived/dod_cache/)
# ──────────────────────────────────────────────────────────────────
def dod_cache_dir(left: Mission, right: Mission) -> Path:
    """DoD PNG·통계 캐시 위치 (after 미션 데이터 디렉터리 안).

    after = 신규 시점 (보통 RTK 정확도 더 좋음). 결과를 after 미션 디렉터리에
    저장해 같은 site_id 의 모든 비교를 한 곳에 모음.
    """
    # before/after 순서 정렬 (compute_diff 내부와 일치)
    if left.flight_date <= right.flight_date:
        after = right
    else:
        after = left
    return after.data_dir / "derived" / "dod_cache"


def _dod_key(left: Mission, right: Mission) -> str:
    """캐시 키 — 시간 순 정렬 후 해시 (좌/우 swap 해도 같은 키)."""
    if left.flight_date <= right.flight_date:
        a, b = left.id, right.id
    else:
        a, b = right.id, left.id
    return hashlib.md5(f"{a}::{b}".encode("utf-8")).hexdigest()[:12]


def dod_png_path(left: Mission, right: Mission) -> Path:
    """DoD 결과 PNG 경로 — (before_id, after_id) 결합 해시."""
    return dod_cache_dir(left, right) / f"dod_{_dod_key(left, right)}.png"


def dod_stats_path(left: Mission, right: Mission) -> Path:
    """DoD 통계 JSON 경로 (mean/std/p05/p95/area/volume)."""
    return dod_cache_dir(left, right) / f"dod_{_dod_key(left, right)}.json"


# ──────────────────────────────────────────────────────────────────
#  feasibility — 두 미션 DoD 계산 가능한지 사전 판단
# ──────────────────────────────────────────────────────────────────
def dod_feasibility(left: Mission, right: Mission) -> tuple[bool, str, str]:
    """DoD 계산 가능 여부 + 사유 + 모드.

    Returns:
        (feasible, message, mode)
          mode = 'real' | 'simulation' | 'unavailable'
    """
    # 시뮬레이션 모드 — 좌·우 같은 미션 (검증용, Δ=0 데모)
    if left.id == right.id:
        return True, "시뮬레이션 모드 — 동일 미션 (Δ=0 데모 표시)", "simulation"

    # 실데이터 — 같은 site_id 의 다른 시점
    if (left.site_id or left.id) != (right.site_id or right.id):
        return False, "다른 시설물 미션 — 같은 site_id 의 두 시점 필요", "unavailable"

    # 두 미션 모두 DSM 보유?
    if not left.has("dsm"):
        return False, f"좌측 미션 ({left.id}) DSM 미가공", "unavailable"
    if not right.has("dsm"):
        return False, f"우측 미션 ({right.id}) DSM 미가공", "unavailable"

    # BBOX 교집합?
    b1 = left.bbox_wgs84
    b2 = right.bbox_wgs84
    if b1 is None or b2 is None:
        return False, "BBOX 메타 누락 — meta.json geo.bbox_wgs84 확인", "unavailable"
    ix_lon_min = max(b1[0], b2[0])
    ix_lat_min = max(b1[1], b2[1])
    ix_lon_max = min(b1[2], b2[2])
    ix_lat_max = min(b1[3], b2[3])
    if ix_lon_min >= ix_lon_max or ix_lat_min >= ix_lat_max:
        return False, "두 미션 BBOX 교집합 없음 — 같은 장소 아님", "unavailable"

    return True, "DoD 계산 가능 (실데이터)", "real"


# ──────────────────────────────────────────────────────────────────
#  DSM 차분 + RdBu_r PNG 생성 (실데이터 모드)
# ──────────────────────────────────────────────────────────────────
def _signature(left: Mission, right: Mission) -> tuple:
    """캐시 키용 시그니처 (mtime, size).

    시뮬레이션 모드(좌·우 같은 미션)에선 DSM 파일 1개만 본다.
    """
    def _sig_one(m: Mission) -> tuple[int, int]:
        try:
            rel = (m.outputs.get("dsm") or {}).get("path")
            if not rel:
                return (0, 0)
            p = m.data_dir / rel
            if not p.exists():
                return (0, 0)
            s = p.stat()
            return (s.st_mtime_ns, s.st_size)
        except Exception:  # noqa: BLE001
            return (0, 0)
    return (_sig_one(left), _sig_one(right))


# 🆕 (2026-06-11 S5) Δz 캐시 — threshold 무관 무거운 단계(reproject 2회 +
# 편향보정 + median filter, ~25초)만 분리 캐싱. 임계치 슬라이더 변경 시엔
# 이 캐시를 재사용해 render(통계+PNG)만 다시 → 1~2초.
# Δz float32 배열은 수십 MB 가능 → max_entries=8 로 메모리 상한.
@st.cache_data(ttl=3600, show_spinner=False, max_entries=8)
def _compute_dz_cached(
    left_id: str,
    right_id: str,
    sig: tuple,
) -> Optional[dict]:
    """Δz 계산 본체 (threshold 무관) — {"dz": ndarray, "grid_meta": dict}.

    Mission 객체는 캐시 키에서 빼고(직렬화 부담) registry 에서 재조회
    — _compute_dod_cached 와 동일 패턴. 실패 시 {"error": 사유, "dz": None}.
    """
    from src.dashboard.tabs._drone_helpers import get_registry

    reg = get_registry()
    try:
        left = reg.get(left_id)
        right = reg.get(right_id)
    except Exception:  # noqa: BLE001
        return None

    try:
        from src.drone.diff import DsmDiffAnalyzer, MissionPair

        pair = MissionPair.from_two(left, right)
        analyzer = DsmDiffAnalyzer(pair)
        dz, grid_meta = analyzer.compute_dz(do_bias_correction=True)
        if dz is None:
            return {"error": (grid_meta or {}).get("error") or "Δz 계산 실패",
                    "dz": None, "grid_meta": None}
        return {"error": None, "dz": dz, "grid_meta": grid_meta}
    except Exception as e:  # noqa: BLE001
        import traceback
        _logger.warning("Δz 계산 실패: %s\n%s", e, traceback.format_exc())
        return {"error": f"{type(e).__name__}: {e}", "dz": None, "grid_meta": None}


@st.cache_data(ttl=3600, show_spinner=False, max_entries=32)
def _compute_dod_cached(
    left_id: str,
    right_id: str,
    sig: tuple,
    threshold_m: float,
) -> Optional[dict]:
    # 🛡️ (2026-06-11 검증팀 D4) `_sig` → `sig` — Streamlit 은 `_` 접두 인자를
    # 캐시 키에서 제외하므로 DSM 갱신 자동 무효화가 동작하지 않았음.
    """DoD 산출 — 🆕 (2026-06-11 S5) Δz 캐시(_compute_dz_cached)를 받아
    threshold 마스킹 + 통계 + PNG 렌더만 수행 (가벼움).

      1) _compute_dz_cached() — reproject + 보정 + filter (캐시, 무거움)
      2) DsmDiffAnalyzer.render_dod() — 통계 + RdBu_r PNG + JSON (+ GeoTIFF)
      3) {"png": str, "stats": {...}, "bbox": [...]} 반환
    """
    from src.dashboard.tabs._drone_helpers import get_registry

    reg = get_registry()
    try:
        left = reg.get(left_id)
        right = reg.get(right_id)
    except Exception:  # noqa: BLE001
        return None

    feasible, msg, mode = dod_feasibility(left, right)
    if not feasible:
        return {"mode": mode, "message": msg, "stats": None, "png": None, "bbox": None}

    if mode == "simulation":
        # 좌·우 같은 미션 → Δ=0. 데모용 임의 통계 표시.
        return {
            "mode": "simulation",
            "message": "시뮬레이션 모드 (Δ=0)",
            "stats": {
                "mean_m": 0.0,
                "std_m": 0.0,
                "min_m": 0.0,
                "max_m": 0.0,
                "p05_m": 0.0,
                "p95_m": 0.0,
                "pixel_count": 0,
                "volume_pos_m3": 0.0,
                "volume_neg_m3": 0.0,
                "net_volume_m3": 0.0,
                "threshold_m": threshold_m,
            },
            "png": None,
            "bbox": list(left.bbox_wgs84) if left.bbox_wgs84 else None,
        }

    # ── 실데이터 모드 — 🆕 (2026-06-11 S5) Δz 캐시 + 렌더 분리 호출 ──
    try:
        from src.drone.diff import DsmDiffAnalyzer, MissionPair

        # 1) Δz (무거움, threshold 무관) — 별도 캐시. 임계치만 바뀌면 hit.
        dz_doc = _compute_dz_cached(left_id, right_id, sig)
        if not dz_doc or dz_doc.get("dz") is None:
            err = (dz_doc or {}).get("error") or "Δz 계산 실패"
            return {
                "mode": "unavailable",
                "message": f"DoD 계산 실패 — {err}",
                "stats": None, "png": None, "bbox": None,
            }

        pair = MissionPair.from_two(left, right)
        analyzer = DsmDiffAnalyzer(pair)

        # 출력 위치: left.data_dir/derived/dod_cache/dod_<hash>.png
        # 안정적 이름 → 같은 (좌·우) 조합은 같은 파일 → pdf_server cache hit.
        out_dir = dod_cache_dir(left, right)
        png_name = dod_png_path(left, right).name

        # 2) threshold 마스킹 + 통계 + PNG/GeoTIFF 렌더 (가벼움, ~1초)
        result = analyzer.render_dod(
            dz_doc["dz"], dz_doc["grid_meta"],
            threshold_m=float(threshold_m),
            out_dir=out_dir,
            png_name=png_name,
        )
        # 시각화용 bbox 는 DoD 산출 시점에 결정된 교집합 (projected→WGS84)
        return {
            "mode": "real",
            "message": "실데이터 DoD 계산 완료 (Phase 1)",
            "stats": result.stats,
            "png": str(result.diff_raster_path) if result.diff_raster_path else None,
            "bbox": list(result.bbox_wgs84) if result.bbox_wgs84 else None,
        }
    except Exception as e:  # noqa: BLE001
        import traceback
        _logger.warning("DoD 실데이터 계산 실패: %s\n%s",
                        e, traceback.format_exc())
        return {
            "mode": "unavailable",
            "message": f"DoD 계산 실패 — {type(e).__name__}: {e}",
            "stats": None,
            "png": None,
            "bbox": None,
        }


def compute_dod(left: Mission, right: Mission,
                *, threshold_m: float = 0.15) -> Optional[dict]:
    """외부 인터페이스 — 캐시 wrapper.

    Returns dict 또는 None:
      {
        "mode": "simulation" | "real" | "unavailable",
        "message": str,
        "stats": {mean_m, std_m, min_m, max_m, p05_m, p95_m, pixel_count,
                  volume_pos_m3, volume_neg_m3, net_volume_m3, threshold_m},
        "png": str | None,    # 컬러 PNG 절대경로
        "bbox": [lon_min, lat_min, lon_max, lat_max] | None,
      }
    """
    return _compute_dod_cached(
        left.id, right.id, _signature(left, right), float(threshold_m),
    )


# ──────────────────────────────────────────────────────────────────
#  DoD URL → diff_viewer 의 hash 파라미터에 전달용
# ──────────────────────────────────────────────────────────────────
def url_for_dod_png(left: Mission, right: Mission) -> str:
    """DoD PNG 의 pdf_server :8766 URL — 없으면 빈 문자열.

    diff_viewer 의 hash 파라미터 `dod_img` 로 전달 → JS 가 L.imageOverlay 또는
    Cesium ImageryLayer 로 표시.
    """
    p = dod_png_path(left, right)
    if not p.exists():
        return ""
    try:
        from src.dashboard.tabs._drone_helpers import drone_url_base
        from src.drone.providers import make_drone_url
        # after 미션 디렉터리 (dod_cache_dir 와 일치) 기준 상대경로
        if left.flight_date <= right.flight_date:
            host_mission = right
        else:
            host_mission = left
        rel = p.relative_to(host_mission.data_dir).as_posix()
        url = make_drone_url(drone_url_base(), host_mission.id, rel)
        # 🛡️ (2026-06-11 검증팀 D3) mtime 캐시버스터 — DoD PNG 파일명이 미션쌍
        # 해시 고정(threshold 미포함)이고 pdf_server 가 max-age=3600 을 주므로,
        # 임계치 변경으로 PNG 가 덮어써져도 브라우저가 1시간 동안 옛 PNG 를
        # 표시했음. mtime 쿼리로 내용 변경 시 URL 자체가 바뀌도록 함.
        # (pdf_server 는 '?' 이후를 잘라 경로 해석 — 쿼리 추가 안전 확인됨.)
        return f"{url}?t={p.stat().st_mtime_ns}"
    except Exception:  # noqa: BLE001
        return ""


def dod_bounds_str(left: Mission, right: Mission) -> str:
    """DoD PNG 의 정확한 WGS84 bbox 를 "latMin,lonMin,latMax,lonMax" 로 반환.

    1순위: dod_stats_path() 의 JSON 사이드카 (compute_diff 가 저장한 정확한 값)
    2순위: BBOX 교집합 (meta.json 기반)
    실패: 빈 문자열 → viewer 가 자체 폴백 (right.bbox)
    """
    import json as _json
    try:
        sp = dod_stats_path(left, right)
        if sp.exists():
            with open(sp, encoding="utf-8") as f:
                meta = _json.load(f)
            bb = meta.get("png_bbox_wgs84")
            if bb and len(bb) == 4:
                # bb = [lon_min, lat_min, lon_max, lat_max]
                return f"{bb[1]},{bb[0]},{bb[3]},{bb[2]}"
    except Exception:  # noqa: BLE001
        pass
    # 폴백: 두 미션 bbox 교집합
    b1, b2 = left.bbox_wgs84, right.bbox_wgs84
    if b1 and b2:
        lon_min = max(b1[0], b2[0])
        lat_min = max(b1[1], b2[1])
        lon_max = min(b1[2], b2[2])
        lat_max = min(b1[3], b2[3])
        if lon_min < lon_max and lat_min < lat_max:
            return f"{lat_min},{lon_min},{lat_max},{lon_max}"
    return ""


# ----------------------------------------------------------------
#  facility-specific recommended thresholds + display helpers
# ----------------------------------------------------------------
def recommended_threshold_for(site_type: str) -> float:
    """Recommended DoD threshold (m) per facility type (1st agent input).

    Reservoir / wall / pipe: mm-cm deformation detection -> 0.05 m
    Spring / channel:        sediment / vegetation change -> 0.15 m
    Other:                   0.10 m
    """
    return {
        "저수조": 0.05,
        "옹벽": 0.05,
        "송수관": 0.05,
        "수원지": 0.15,
        "수로": 0.15,
    }.get(site_type or "", 0.10)


# ──────────────────────────────────────────────────────────────────
#  🆕 (2026-06-11 Q1) LoD95 — 95% 최소탐지한계 (m)
# ──────────────────────────────────────────────────────────────────
def lod95_for(left: Mission, right: Mission) -> Optional[float]:
    """두 미션 survey_info.rmse_m 기반 LoD95 = 1.96 × √(r1²+r2²).

    어느 한쪽이라도 rmse 없으면 None. 본체는 src.drone.diff.lod95_for_missions
    (streamlit 비의존 — pytest 에서도 호출 가능).
    """
    try:
        from src.drone.diff import lod95_for_missions
        return lod95_for_missions(left, right)
    except Exception:  # noqa: BLE001
        return None


# ──────────────────────────────────────────────────────────────────
#  🆕 (2026-06-11 Q4) hillshade — after 미션 DSM 음영기복 (DoD 아래 표시)
# ──────────────────────────────────────────────────────────────────
def _after_mission(left: Mission, right: Mission) -> Mission:
    """시간 순으로 뒤의 미션 (dod_cache_dir 의 host 와 일치)."""
    return right if left.flight_date <= right.flight_date else left


def hillshade_png_path(left: Mission, right: Mission) -> Path:
    """hillshade PNG 경로 — dod_cache 디렉터리의 hs_<pair-hash>.png."""
    return dod_cache_dir(left, right) / f"hs_{_dod_key(left, right)}.png"


@st.cache_data(ttl=3600, show_spinner=False, max_entries=16)
def _hillshade_cached(left_id: str, right_id: str, sig: tuple) -> Optional[str]:
    """hillshade 생성 (캐시) — 성공 시 PNG 절대경로 str, 실패 None.

    Mission 재조회 패턴은 _compute_dod_cached 와 동일. PNG 가 이미 디스크에
    있으면 즉시 반환 (DSM 갱신 시 sig 변경 → 캐시 미스 → 재생성).
    """
    from src.dashboard.tabs._drone_helpers import get_registry

    reg = get_registry()
    try:
        left = reg.get(left_id)
        right = reg.get(right_id)
    except Exception:  # noqa: BLE001
        return None

    p = hillshade_png_path(left, right)
    if p.exists() and p.with_suffix(".json").exists():
        return str(p)
    try:
        from src.drone.diff import make_hillshade
        after = _after_mission(left, right)
        out = make_hillshade(after, out_dir=p.parent, png_name=p.name)
        return str(out) if out else None
    except Exception as e:  # noqa: BLE001
        _logger.warning("hillshade 생성 실패: %s", e)
        return None


def ensure_hillshade(left: Mission, right: Mission) -> bool:
    """외부 인터페이스 — hillshade PNG 생성 보장 (캐시). 성공 여부 반환."""
    return bool(_hillshade_cached(left.id, right.id, _signature(left, right)))


def url_for_hs_png(left: Mission, right: Mission) -> str:
    """hillshade PNG 의 pdf_server :8766 URL — 없으면 빈 문자열.

    url_for_dod_png 과 동일하게 ?t=<mtime_ns> 캐시버스터 부착
    (pdf_server 는 '?' 이후 쿼리를 경로 해석에서 자름 — 안전).
    """
    p = hillshade_png_path(left, right)
    if not p.exists():
        return ""
    try:
        from src.dashboard.tabs._drone_helpers import drone_url_base
        from src.drone.providers import make_drone_url
        host_mission = _after_mission(left, right)
        rel = p.relative_to(host_mission.data_dir).as_posix()
        url = make_drone_url(drone_url_base(), host_mission.id, rel)
        return f"{url}?t={p.stat().st_mtime_ns}"
    except Exception:  # noqa: BLE001
        return ""


def hs_bounds_str(left: Mission, right: Mission) -> str:
    """hillshade PNG 의 WGS84 bbox → "latMin,lonMin,latMax,lonMax".

    1순위: 사이드카 JSON (make_hillshade 가 저장한 DSM 정확 bbox)
    폴백:  after 미션 meta bbox. 실패 시 빈 문자열.
    """
    import json as _json
    try:
        sp = hillshade_png_path(left, right).with_suffix(".json")
        if sp.exists():
            with open(sp, encoding="utf-8") as f:
                meta = _json.load(f)
            bb = meta.get("bbox_wgs84")
            if bb and len(bb) == 4:
                # bb = [lon_min, lat_min, lon_max, lat_max]
                return f"{bb[1]},{bb[0]},{bb[3]},{bb[2]}"
    except Exception:  # noqa: BLE001
        pass
    bb = _after_mission(left, right).bbox_wgs84
    if bb:
        return f"{bb[1]},{bb[0]},{bb[3]},{bb[2]}"
    return ""


def format_stats_card_value(stats, key, unit: str = "m", fmt: str = "{:+.3f}") -> str:
    if not stats or stats.get(key) is None:
        return "—"
    try:
        return fmt.format(stats[key]) + (" " + unit if unit else "")
    except (TypeError, ValueError):
        return "—"


def colormap_legend_html(vmax_m: float = 1.0) -> str:
    """RdBu_r colormap HTML legend - for popover / stat card inset."""
    return (
        '<div style="display:flex;gap:0;font-family:monospace;font-size:11px;'
        'margin:6px 0;border-radius:4px;overflow:hidden;border:1px solid #888;">'
        f'<div style="flex:1;background:#08519c;color:#fff;padding:6px;text-align:center;">'
        f'−1.0m<br>큰 감소</div>'
        f'<div style="flex:1;background:#6baed6;color:#fff;padding:6px;text-align:center;">'
        f'−{vmax_m*0.3:.2f}m<br>감소</div>'
        '<div style="flex:1;background:#f7f7f7;color:#333;padding:6px;text-align:center;">'
        '±0m<br>변화 없음</div>'
        f'<div style="flex:1;background:#fc9272;color:#fff;padding:6px;text-align:center;">'
        f'+{vmax_m*0.3:.2f}m<br>증가</div>'
        f'<div style="flex:1;background:#a50f15;color:#fff;padding:6px;text-align:center;">'
        f'+{vmax_m:.1f}m<br>큰 증가</div>'
        '</div>'
    )
