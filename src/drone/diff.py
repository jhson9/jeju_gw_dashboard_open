"""시계열 미션 비교 — 같은 장소(site_id)의 다른 시기 2건을 align·차분.

**현재 상태: Phase 2 구현 대기 (골격만 정의).**
4개 미션이 모두 다른 장소라 시계열 비교 가능한 site 가 없는 상태.
2026-06-23 경 송당저수조 재촬영 → "songdang_reservoir" site 에 2건이 모이면
이 모듈의 실제 구현을 채워서 활성화.

설계 방향:
- MissionPair (before, after) 데이터 클래스
- DsmDiffAnalyzer: 두 DSM 의 BBOX 교집합 → 동일 해상도로 resample → Δ raster
- 2D 비교: 두 정사사진을 같은 BBOX 로 swipe/blend (Leaflet sidebyside 플러그인)
- 3D 비교: CesiumJS 의 두 tileset 토글
- 결과: 차분 heatmap (RdBu colormap, 음수 파랑·양수 빨강), Δ표고 통계

🆕 (2026-06-11 S5) 2단계 API 분리 — threshold 슬라이더 응답성 25초 → 1~2초:
  1) compute_dz()  : reproject(2회) + RTK 편향보정 + 3x3 median filter
                     → Δz 배열 + grid 메타. threshold 무관 (캐시 가능).
  2) render_dod()  : threshold 마스킹 → 통계 → PNG/GeoTIFF 렌더 (가벼움).
  기존 compute_diff() 는 두 함수를 순서대로 호출하는 thin wrapper 로 유지
  (시그니처·반환 하위 호환).

외부에서 사용:
    from src.drone import DroneRegistry, MissionPair, DsmDiffAnalyzer
    reg = DroneRegistry()
    sites = reg.list_comparable_sites()   # 미션 2건+ 인 site 만
    for site in sites:
        pair = MissionPair.latest_two(site["missions"])
        analyzer = DsmDiffAnalyzer(pair)
        # result = analyzer.compute_diff()   # Phase 2 구현 예정
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Sequence

from .registry import Mission

_logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────
#  🆕 (2026-06-11 Q1) LoD95 — 95% 최소탐지한계
# ──────────────────────────────────────────────────────────────────
def lod95_for_missions(m1: Mission, m2: Mission) -> Optional[float]:
    """두 미션의 georeferencing RMSE 로부터 LoD95 (m) 산출.

    LoD95 = 1.96 × √(RMSE₁² + RMSE₂²)
    — DoD 문헌 표준 (Brasington et al. 2003; Wheaton et al. 2010).
    이보다 작은 |Δz| 는 측량 불확실도 이내라 실제 변화로 단정 불가.

    meta.json 의 survey_info.rmse_m (예: 0.93, 0.42) 사용.
    어느 한쪽이라도 없거나 0 이하이면 None.
    """
    import math

    def _rmse(m: Mission) -> Optional[float]:
        try:
            v = (m.meta.get("survey_info") or {}).get("rmse_m")
            if isinstance(v, (int, float)) and float(v) > 0:
                return float(v)
        except Exception:  # noqa: BLE001
            pass
        return None

    r1, r2 = _rmse(m1), _rmse(m2)
    if r1 is None or r2 is None:
        return None
    return 1.96 * math.sqrt(r1 * r1 + r2 * r2)


# ──────────────────────────────────────────────────────────────────
#  🆕 (2026-06-11 Q4) hillshade — DSM 음영기복 PNG (DoD 지형 맥락용)
# ──────────────────────────────────────────────────────────────────
def make_hillshade(
    mission: Mission,
    *,
    out_dir: Path,
    png_name: str,
    max_dim: int = 4000,
    azimuth_deg: float = 315.0,
    altitude_deg: float = 45.0,
) -> Optional[Path]:
    """미션 DSM 에서 numpy gradient 기반 hillshade 회색 PNG 생성.

    - ESRI/GDAL 표준식: cos(zenith)·cos(slope) + sin(zenith)·sin(slope)·cos(az−aspect)
    - 다운샘플 상한 max_dim (기본 4000px) — 메모리·렌더 시간 제한
    - 무효(nodata) 픽셀은 alpha=0 (투명) — Leaflet imageOverlay 에서 깔끔
    - bbox 사이드카 JSON (<png>.json) 에 WGS84 bbox 저장 → viewer bounds 용
    - rasterio/PIL 미설치·실패 시 None 반환 (로그만 — 탭 죽지 않음)
    """
    if not mission.has("dsm"):
        return None
    dsm_path = mission.output_path("dsm")
    if dsm_path is None or not dsm_path.exists():
        return None
    try:
        import numpy as np
        import rasterio
        from rasterio.enums import Resampling
        from rasterio.warp import transform_bounds
        from PIL import Image
    except ImportError as e:
        _logger.info("hillshade 의존성 없음 — skip: %s", e)
        return None

    try:
        with rasterio.open(dsm_path) as ds:
            scale = max(ds.width / float(max_dim), ds.height / float(max_dim), 1.0)
            out_w = max(int(round(ds.width / scale)), 1)
            out_h = max(int(round(ds.height / scale)), 1)
            # nearest — bilinear 는 nodata(-9999 등) 가 유효값에 번짐
            z = ds.read(1, out_shape=(out_h, out_w),
                        resampling=Resampling.nearest).astype("float32")
            nodata = ds.nodata
            if nodata is not None:
                z = np.where(np.isclose(z, float(nodata)), np.nan, z)
            z = np.where(z < -5000, np.nan, z)   # 극단 outlier 방어
            gsd_x = abs(ds.transform.a) * (ds.width / float(out_w))
            gsd_y = abs(ds.transform.e) * (ds.height / float(out_h))
            try:
                bb = (transform_bounds(ds.crs, "EPSG:4326", *ds.bounds,
                                       densify_pts=21) if ds.crs else None)
            except Exception:  # noqa: BLE001
                bb = None

        valid = np.isfinite(z)
        if not valid.any():
            _logger.warning("hillshade: 유효 픽셀 없음 (%s)", mission.id)
            return None
        fill = float(np.nanmedian(z))
        zf = np.where(valid, z, fill)

        # ESRI hillshade 공식 (az=315°, alt=45° 기본)
        zen = np.radians(90.0 - altitude_deg)
        azm = np.radians(360.0 - azimuth_deg + 90.0)
        gy, gx = np.gradient(zf, gsd_y, gsd_x)
        dzdx = gx
        dzdy = -gy   # row 증가 방향 = 남쪽 → north-up 보정
        slope = np.arctan(np.hypot(dzdx, dzdy))
        aspect = np.arctan2(dzdy, -dzdx)
        hs = (np.cos(zen) * np.cos(slope)
              + np.sin(zen) * np.sin(slope) * np.cos(azm - aspect))
        gray = (np.clip(hs, 0.0, 1.0) * 255).astype("uint8")
        alpha = np.where(valid, 255, 0).astype("uint8")

        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        png_path = out_dir / png_name
        Image.fromarray(np.dstack([gray, alpha]), mode="LA").save(
            png_path, optimize=True)

        # bbox 사이드카 (viewer bounds 용)
        import json as _json
        with open(png_path.with_suffix(".json"), "w", encoding="utf-8") as f:
            _json.dump({
                "mission_id": mission.id,
                "bbox_wgs84": list(bb) if bb else None,
                "azimuth_deg": float(azimuth_deg),
                "altitude_deg": float(altitude_deg),
                "width": int(out_w), "height": int(out_h),
            }, f, ensure_ascii=False, indent=2)

        _logger.info("hillshade ok: %s %dx%d → %s",
                     mission.id, out_w, out_h, png_path)
        return png_path
    except Exception as e:  # noqa: BLE001
        _logger.warning("hillshade 생성 실패 (%s): %s", mission.id, e)
        return None


@dataclass(frozen=True)
class MissionPair:
    """시계열 비교용 미션 쌍 — 같은 site_id 의 두 미션 (before/after).

    `before.flight_date < after.flight_date` 보장 (생성자가 정렬).
    """
    site_id: str
    before: Mission
    after: Mission

    @classmethod
    def from_two(cls, m1: Mission, m2: Mission) -> "MissionPair":
        """두 미션을 시간 순서로 정렬해 MissionPair 생성."""
        if (m1.site_id or m1.id) != (m2.site_id or m2.id):
            raise ValueError(
                f"다른 site_id 의 미션을 비교할 수 없습니다: "
                f"{m1.id}({m1.site_id}) vs {m2.id}({m2.site_id})"
            )
        if m1.flight_date <= m2.flight_date:
            before, after = m1, m2
        else:
            before, after = m2, m1
        return cls(site_id=(m1.site_id or m1.id), before=before, after=after)

    @classmethod
    def latest_two(cls, missions: Sequence[Mission]) -> Optional["MissionPair"]:
        """미션 리스트에서 가장 최근 두 건으로 pair 구성. 2건 미만이면 None."""
        if len(missions) < 2:
            return None
        sorted_ms = sorted(missions, key=lambda m: m.flight_date)
        return cls.from_two(sorted_ms[-2], sorted_ms[-1])

    @property
    def label(self) -> str:
        return f"{self.before.flight_date} → {self.after.flight_date}"

    @property
    def days_between(self) -> Optional[int]:
        """두 촬영일 사이 일수. 파싱 실패 시 None."""
        from datetime import datetime
        try:
            d1 = datetime.strptime(self.before.flight_date, "%Y-%m")
            d2 = datetime.strptime(self.after.flight_date, "%Y-%m")
            return (d2 - d1).days
        except (ValueError, TypeError):
            return None


@dataclass(frozen=True)
class DsmDiffResult:
    """DSM 차분 결과 — Phase 2 에서 채움.

    필드 예시 (구현 시):
      diff_raster_path : Path  — Δz 색상 매핑 PNG
      bbox_wgs84       : tuple — 교집합 BBOX
      stats            : dict  — {mean, std, min, max, p05, p95, pixel_count}
      sign_split       : dict  — {positive_m3, negative_m3, net_m3} (체적)
    """
    pair: MissionPair
    diff_raster_path: Optional[Path] = None
    bbox_wgs84: Optional[tuple[float, float, float, float]] = None
    stats: Optional[dict] = None


class DsmDiffAnalyzer:
    """두 미션의 DSM 을 align·차분해 변화 raster + 통계 산출.

    🆕 (2026-06-11 S5) 2단계 구조:
      compute_dz()  — 무거운 부분 (reproject + 편향보정 + median filter)
      render_dod()  — 가벼운 부분 (threshold 마스킹 + 통계 + PNG/GeoTIFF)
      compute_diff() — 하위 호환 thin wrapper (둘을 순서대로 호출)

    제약 (DJI Terra 전문가 시각):
    - 두 미션의 RTK 모드가 다르면 절대 z 편향이 다를 수 있어 글로벌 offset 보정 필요
    - 안정 영역(예: 도로·바위) 의 Δz 평균을 0 으로 만드는 plane fitting 권장
    - 식생 계절 변화(여름 무성·겨울 잎 없음)는 DSM 차이로 잘못 잡힐 수 있음
    - 같은 site 라도 BBOX 가 일부 비대칭일 수 있어 교집합 영역만 산출
    """

    def __init__(self, pair: MissionPair):
        self.pair = pair

    def is_feasible(self) -> tuple[bool, str]:
        """차분 가능 여부 + 사유 메시지.

        - before/after 모두 DSM 보유 + BBOX 메타 존재
        - BBOX 교집합 면적 > 0
        """
        if not self.pair.before.has("dsm"):
            return False, f"before 미션 {self.pair.before.id} 에 DSM 없음"
        if not self.pair.after.has("dsm"):
            return False, f"after 미션 {self.pair.after.id} 에 DSM 없음"
        b1 = self.pair.before.bbox_wgs84
        b2 = self.pair.after.bbox_wgs84
        if b1 is None or b2 is None:
            return False, "BBOX 메타 누락 (meta.json geo.bbox_wgs84 확인)"
        # 교집합 검사
        ix_lon_min = max(b1[0], b2[0])
        ix_lat_min = max(b1[1], b2[1])
        ix_lon_max = min(b1[2], b2[2])
        ix_lat_max = min(b1[3], b2[3])
        if ix_lon_min >= ix_lon_max or ix_lat_min >= ix_lat_max:
            return False, "두 미션 BBOX 교집합이 없음 — 같은 장소가 아닐 가능성"
        return True, "차분 가능"

    def intersection_bbox(self) -> Optional[tuple[float, float, float, float]]:
        """두 미션 BBOX 의 교집합 (lon_min, lat_min, lon_max, lat_max). 없으면 None."""
        b1 = self.pair.before.bbox_wgs84
        b2 = self.pair.after.bbox_wgs84
        if not b1 or not b2:
            return None
        ix = (
            max(b1[0], b2[0]), max(b1[1], b2[1]),
            min(b1[2], b2[2]), min(b1[3], b2[3]),
        )
        if ix[0] >= ix[2] or ix[1] >= ix[3]:
            return None
        return ix

    # ──────────────────────────────────────────────────────────
    #  🆕 (2026-06-11 S5) 1단계 — Δz 계산 (threshold 무관, 무거움 ~25초)
    # ──────────────────────────────────────────────────────────
    def compute_dz(
        self,
        *,
        do_bias_correction: bool = True,
    ) -> "tuple[Optional[object], dict]":
        """reproject(2회) + RTK 편향보정 + 3x3 median filter — Δz 배열 산출.

        threshold 와 무관한 무거운 단계만 수행. 임계치 슬라이더 변경 시엔
        이 결과(캐시)를 재사용해 render_dod() 만 다시 돌리면 1~2초.

        Returns:
            (dz, grid_meta)
              dz        : np.ndarray float32 (NaN=무효) | None (실패)
              grid_meta : {
                "transform": [a,b,c,d,e,f],   # rasterio Affine 계수
                "crs_wkt": str, "epsg": int,
                "gsd": float, "width": int, "height": int,
                "bounds": [left,bottom,right,top],            # projected
                "bbox_wgs84": [lonmin,latmin,lonmax,latmax],  # PNG overlay 용
                "unit_is_meter": bool,
                "rtk_bias_m": float, "median_filter": bool,
              }
              실패 시 (None, {"error": 사유})
        """
        ok, msg = self.is_feasible()
        if not ok:
            _logger.warning("DsmDiffAnalyzer.compute_dz infeasible: %s", msg)
            return None, {"error": msg}

        import numpy as np
        import rasterio
        from rasterio.warp import reproject, Resampling, transform_bounds
        from rasterio.transform import from_bounds
        from pyproj import Transformer

        before = self.pair.before
        after  = self.pair.after
        before_dsm = before.output_path("dsm")
        after_dsm  = after.output_path("dsm")
        if before_dsm is None or after_dsm is None:
            return None, {"error": "DSM 경로 해석 실패"}

        with rasterio.open(before_dsm) as ds_b, rasterio.open(after_dsm) as ds_a:
            crs_b = ds_b.crs
            crs_a = ds_a.crs
            if crs_b is None or crs_a is None:
                return None, {"error": "DSM CRS 누락"}

            target_crs = crs_a  # after 기준 (보통 RTK 더 정확)

            def _bnds_in(crs_src, bnds_src, crs_dst):
                if crs_src == crs_dst:
                    return bnds_src
                return transform_bounds(crs_src, crs_dst, *bnds_src, densify_pts=21)

            b_bnds = _bnds_in(crs_b, ds_b.bounds, target_crs)
            a_bnds = _bnds_in(crs_a, ds_a.bounds, target_crs)
            left   = max(b_bnds[0], a_bnds[0])
            bottom = max(b_bnds[1], a_bnds[1])
            right  = min(b_bnds[2], a_bnds[2])
            top    = min(b_bnds[3], a_bnds[3])
            if left >= right or bottom >= top:
                return None, {"error": "두 DSM projected bbox 교집합 없음"}

            gsd_b = abs(ds_b.transform.a)
            gsd_a = abs(ds_a.transform.a)
            gsd   = max(gsd_b, gsd_a, 0.05)   # 하한 5cm
            width  = max(int(round((right - left) / gsd)), 1)
            height = max(int(round((top - bottom) / gsd)), 1)
            MAX_DIM = 4000
            if width > MAX_DIM or height > MAX_DIM:
                scale = max(width / MAX_DIM, height / MAX_DIM)
                gsd   = gsd * scale
                width  = max(int(round((right - left) / gsd)), 1)
                height = max(int(round((top - bottom) / gsd)), 1)

            dst_transform = from_bounds(left, bottom, right, top, width, height)

            def _reproject_one(ds_src):
                arr = np.full((height, width), np.nan, dtype=np.float32)
                reproject(
                    source=rasterio.band(ds_src, 1),
                    destination=arr,
                    src_transform=ds_src.transform,
                    src_crs=ds_src.crs,
                    src_nodata=ds_src.nodata,
                    dst_transform=dst_transform,
                    dst_crs=target_crs,
                    dst_nodata=float("nan"),
                    resampling=Resampling.bilinear,
                )
                arr = np.where(np.isfinite(arr), arr, np.nan)
                return arr

            z_before = _reproject_one(ds_b)
            z_after  = _reproject_one(ds_a)

        dz = z_after - z_before

        if do_bias_correction:
            valid = np.isfinite(dz)
            if int(valid.sum()) > 100:
                bias = float(np.nanmedian(dz))
                dz = dz - bias
            else:
                bias = 0.0
        else:
            bias = 0.0

        # ── Build 1.2 (2026-06-03): edge halo 완화 — 3x3 median filter ──
        # 사용자 제보 (덕천 저수조): 둥근 탱크 벽면 가장자리에 ±수 m 빨강/파랑 halo.
        # 원인: 수직면(탱크 벽)에서 sub-pixel 수평 시프트로 한 픽셀이 "벽 위(높음)"
        #       옆 픽셀이 "지면(낮음)" → 차분 시 양극단 oscillation.
        # 해결: 3x3 median filter 로 single-pixel outlier 제거. mean 보다 robust.
        #       경계는 손실 적음. scipy 가 없으면 그냥 skip (의존성 회피).
        try:
            from scipy.ndimage import median_filter as _medfilt
            mask_in = np.isfinite(dz)
            dz_filled = np.where(mask_in, dz, 0.0)
            dz_med = _medfilt(dz_filled, size=3, mode='reflect')
            # 원래 NaN 영역은 그대로 유지 (median이 인접 픽셀 평균값으로 채우지 않게)
            dz = np.where(mask_in, dz_med, np.nan)
            median_filter_applied = True
        except ImportError:
            median_filter_applied = False
            _logger.info("scipy 없음 - median filter skip")

        # WGS84 bbox (PNG overlay bounds 용)
        try:
            tr = Transformer.from_crs(target_crs, "EPSG:4326", always_xy=True)
            wgs_lonmin, wgs_latmin = tr.transform(left, bottom)
            wgs_lonmax, wgs_latmax = tr.transform(right, top)
            png_bbox = [float(wgs_lonmin), float(wgs_latmin),
                        float(wgs_lonmax), float(wgs_latmax)]
        except Exception as e:  # noqa: BLE001
            _logger.warning("WGS84 transform failed: %s", e)
            ib = self.intersection_bbox()
            png_bbox = list(ib) if ib else None

        try:
            unit_is_meter = (target_crs.linear_units or "").lower().startswith("met")
        except Exception:  # noqa: BLE001
            unit_is_meter = True

        grid_meta = {
            "transform": [dst_transform.a, dst_transform.b, dst_transform.c,
                          dst_transform.d, dst_transform.e, dst_transform.f],
            "crs_wkt": target_crs.to_wkt(),
            "epsg": int(target_crs.to_epsg() or 0),
            "gsd": float(gsd),
            "width": int(width),
            "height": int(height),
            "bounds": [float(left), float(bottom), float(right), float(top)],
            "bbox_wgs84": png_bbox,
            "unit_is_meter": bool(unit_is_meter),
            "rtk_bias_m": float(bias),
            "median_filter": bool(median_filter_applied),
        }
        return dz, grid_meta

    # ──────────────────────────────────────────────────────────
    #  🆕 (2026-06-11 S5) 2단계 — threshold 마스킹 + 통계 + 렌더 (~1초)
    # ──────────────────────────────────────────────────────────
    def render_dod(
        self,
        dz,
        grid_meta: dict,
        *,
        threshold_m: float = 0.0,
        out_dir: "Optional[Path]" = None,
        png_name: "Optional[str]" = None,
        vmax_m: "Optional[float]" = None,
    ) -> "DsmDiffResult":
        """compute_dz() 결과를 받아 threshold 마스킹 → 통계 → PNG/GeoTIFF 저장.

        - 통계: 기존 항목 + 🆕 lod95_m (Q1) + volume_uncert_m3 (Q2)
                + hist (Q3 — Δz 히스토그램 -1.0~+1.0m, 80 bins, 범위 밖 클립)
        - 🆕 (Q5) Δz GeoTIFF (dod_<hash>.tif, float32, nodata=-9999) 함께 저장
          — rasterio 실패 시 로그만 남기고 skip.
        """
        if dz is None or not grid_meta or grid_meta.get("error"):
            err = (grid_meta or {}).get("error") or "Δz 배열 없음"
            return DsmDiffResult(
                pair=self.pair, bbox_wgs84=self.intersection_bbox(),
                stats={"error": err}, diff_raster_path=None,
            )

        import numpy as np

        before = self.pair.before
        after  = self.pair.after

        valid_mask = np.isfinite(dz)
        n_valid = int(valid_mask.sum())
        if n_valid == 0:
            return DsmDiffResult(
                pair=self.pair, bbox_wgs84=self.intersection_bbox(),
                stats={"error": "유효 픽셀 없음"}, diff_raster_path=None,
            )

        dz_valid = dz[valid_mask]
        gsd = float(grid_meta.get("gsd") or 0.05)
        width = int(grid_meta.get("width") or dz.shape[1])
        height = int(grid_meta.get("height") or dz.shape[0])
        unit_is_meter = bool(grid_meta.get("unit_is_meter", True))
        pixel_area_m2 = (gsd * gsd) if unit_is_meter else 0.0

        if threshold_m > 0:
            sig = np.abs(dz_valid) > float(threshold_m)
            dz_for_vol = dz_valid[sig]
        else:
            dz_for_vol = dz_valid
        vol_pos = float(np.sum(np.clip(dz_for_vol, 0, None))) * pixel_area_m2
        vol_neg = float(np.sum(np.clip(dz_for_vol, None, 0))) * pixel_area_m2

        # 🆕 (2026-06-11 Q1) LoD95 — 95% 최소탐지한계 (rmse 없으면 None)
        lod95 = lod95_for_missions(before, after)
        # 🆕 (2026-06-11 Q2) 부피 불확실도 = LoD95(없으면 threshold) × 변화면적
        uncert_basis = lod95 if (lod95 is not None and lod95 > 0) else float(threshold_m)
        volume_uncert = float(uncert_basis) * float(dz_for_vol.size) * pixel_area_m2

        # 🆕 (2026-06-11 Q3) Δz 히스토그램 — -1.0~+1.0 m, 80 bins, 범위 밖 클립
        try:
            clipped = np.clip(dz_valid, -1.0, 1.0)
            counts, bin_edges = np.histogram(clipped, bins=80, range=(-1.0, 1.0))
            hist = {
                "bin_edges": [float(x) for x in bin_edges],
                "counts":    [int(c) for c in counts],
            }
        except Exception as _he:  # noqa: BLE001
            _logger.warning("Δz 히스토그램 계산 실패: %s", _he)
            hist = None

        # Build 1.8: argmax/argmin 좌표 산출 — "최대 증가/감소 지점" 자동 flyTo 용.
        # dz 는 (height, width) 배열. nan 제외하고 max/min 픽셀의 (row, col) 추출.
        max_lat = max_lon = min_lat = min_lon = None
        try:
            # threshold 적용해서 노이즈 outlier 가 argmax 잡지 않도록 — 단,
            # threshold 이상 변화만 있는 영역에서 진짜 max 찾기. 없으면 전체에서.
            if threshold_m > 0:
                # 절댓값 임계치 이상인 픽셀에서 max/min 위치
                masked = np.where(np.abs(dz) >= float(threshold_m), dz, np.nan)
                if np.isfinite(masked).any():
                    ridx_max, cidx_max = np.unravel_index(np.nanargmax(masked), masked.shape)
                    ridx_min, cidx_min = np.unravel_index(np.nanargmin(masked), masked.shape)
                else:
                    ridx_max, cidx_max = np.unravel_index(np.nanargmax(dz), dz.shape)
                    ridx_min, cidx_min = np.unravel_index(np.nanargmin(dz), dz.shape)
            else:
                ridx_max, cidx_max = np.unravel_index(np.nanargmax(dz), dz.shape)
                ridx_min, cidx_min = np.unravel_index(np.nanargmin(dz), dz.shape)

            # 픽셀 (row, col) → projected (x, y) → WGS84 (lat, lon)
            from pyproj import Transformer as _Tr
            tr_back = _Tr.from_crs(grid_meta["crs_wkt"], "EPSG:4326", always_xy=True)
            # transform = (a, b, c, d, e, f) — col→x, row→y
            t = grid_meta["transform"]
            x_max = t[2] + (cidx_max + 0.5) * t[0]
            y_max = t[5] + (ridx_max + 0.5) * t[4]
            x_min = t[2] + (cidx_min + 0.5) * t[0]
            y_min = t[5] + (ridx_min + 0.5) * t[4]
            max_lon, max_lat = tr_back.transform(x_max, y_max)
            min_lon, min_lat = tr_back.transform(x_min, y_min)
        except Exception as _e:  # noqa: BLE001
            _logger.warning("argmax/argmin 좌표 계산 실패: %s", _e)

        stats = {
            "mean_m":         float(np.mean(dz_valid)),
            "std_m":          float(np.std(dz_valid)),
            "min_m":          float(np.min(dz_valid)),
            "max_m":          float(np.max(dz_valid)),
            "p05_m":          float(np.percentile(dz_valid, 5)),
            "p95_m":          float(np.percentile(dz_valid, 95)),
            "p98_abs_m":      float(np.percentile(np.abs(dz_valid), 98)),
            "median_m":       float(np.median(dz_valid)),
            "pixel_count":    n_valid,
            "valid_ratio":    float(n_valid) / float(dz.size),
            "gsd_m":          float(gsd),
            "rtk_bias_m":     float(grid_meta.get("rtk_bias_m") or 0.0),
            "threshold_m":    float(threshold_m),
            "volume_pos_m3":  vol_pos,
            "volume_neg_m3":  vol_neg,
            "net_volume_m3":  vol_pos + vol_neg,
            "epsg_target":    int(grid_meta.get("epsg") or 0),
            "median_filter":  bool(grid_meta.get("median_filter", False)),
            # Build 1.8: 최대 증가/감소 지점 좌표 (flyTo 용)
            "max_lat":        float(max_lat) if max_lat is not None else None,
            "max_lon":        float(max_lon) if max_lon is not None else None,
            "min_lat":        float(min_lat) if min_lat is not None else None,
            "min_lon":        float(min_lon) if min_lon is not None else None,
            # 🆕 (2026-06-11 Q1/Q2) LoD95 + 부피 불확실도
            "lod95_m":           float(lod95) if lod95 is not None else None,
            "volume_uncert_m3":  volume_uncert,
            "changed_pixel_count": int(dz_for_vol.size),
            # 🆕 (2026-06-11 Q3) Δz 히스토그램
            "hist":           hist,
        }

        if vmax_m is None or vmax_m <= 0:
            vmax = max(stats["p98_abs_m"], 0.05)
        else:
            vmax = float(vmax_m)

        out_dir = Path(out_dir) if out_dir else (after.data_dir / "derived" / "dod_cache")
        out_dir.mkdir(parents=True, exist_ok=True)
        if not png_name:
            png_name = f"dod_{before.id}_vs_{after.id}.png"
        png_path = out_dir / png_name
        json_path = png_path.with_suffix(".json")

        from PIL import Image
        normed = np.clip(dz / vmax, -1, 1)
        normed[~valid_mask] = 0
        if threshold_m > 0:
            tr_norm = float(threshold_m) / vmax
            below_thr = np.abs(normed) < tr_norm
        else:
            below_thr = np.zeros_like(valid_mask, dtype=bool)

        def _rgb(t):
            stops = [
                (-1.0, (8, 81, 156)),
                (-0.3, (107, 174, 214)),
                ( 0.0, (247, 247, 247)),
                ( 0.3, (252, 146, 114)),
                ( 1.0, (165, 15, 21)),
            ]
            r = np.zeros_like(t, dtype=np.uint8)
            g = np.zeros_like(t, dtype=np.uint8)
            b = np.zeros_like(t, dtype=np.uint8)
            for i in range(len(stops) - 1):
                x0, c0 = stops[i]
                x1, c1 = stops[i+1]
                mask = (t >= x0) & (t <= x1) if i == 0 else (t > x0) & (t <= x1)
                if not mask.any():
                    continue
                w = (t[mask] - x0) / (x1 - x0 + 1e-9)
                r[mask] = (c0[0] + (c1[0] - c0[0]) * w).astype(np.uint8)
                g[mask] = (c0[1] + (c1[1] - c0[1]) * w).astype(np.uint8)
                b[mask] = (c0[2] + (c1[2] - c0[2]) * w).astype(np.uint8)
            return r, g, b

        r, g, b = _rgb(normed)
        alpha = np.zeros_like(normed, dtype=np.uint8)
        active = valid_mask & ~below_thr
        if active.any():
            mag = np.clip(np.abs(normed[active]), 0, 1)
            alpha[active] = (255 * (0.3 + 0.7 * mag)).astype(np.uint8)
        rgba = np.dstack([r, g, b, alpha])
        Image.fromarray(rgba, mode="RGBA").save(png_path, optimize=True)

        png_bbox = (tuple(grid_meta["bbox_wgs84"])
                    if grid_meta.get("bbox_wgs84") else self.intersection_bbox())

        import json as _json
        with open(json_path, "w", encoding="utf-8") as f:
            _json.dump({
                "before_id": before.id, "after_id": after.id,
                "vmax_m": float(vmax),
                "png_bbox_wgs84": list(png_bbox) if png_bbox else None,
                "png_width": int(width), "png_height": int(height),
                "stats": stats,
            }, f, ensure_ascii=False, indent=2)

        # 🆕 (2026-06-11 Q5) Δz GeoTIFF 보존 — GIS 후처리(QGIS 등)용.
        # rasterio 미설치/실패 시 로그만 남기고 skip (탭 죽지 않음).
        try:
            import rasterio as _rio
            from rasterio.transform import Affine as _Affine
            t6 = grid_meta.get("transform")
            crs_wkt = grid_meta.get("crs_wkt")
            if t6 and crs_wkt:
                tif_path = png_path.with_suffix(".tif")
                dz_out = np.where(valid_mask, dz, -9999.0).astype("float32")
                with _rio.open(
                    tif_path, "w", driver="GTiff",
                    height=int(dz.shape[0]), width=int(dz.shape[1]),
                    count=1, dtype="float32",
                    crs=crs_wkt, transform=_Affine(*t6[:6]),
                    nodata=-9999.0, compress="deflate",
                ) as dst:
                    dst.write(dz_out, 1)
                stats["geotiff_path"] = str(tif_path)
        except Exception as _ge:  # noqa: BLE001
            _logger.info("DoD GeoTIFF 저장 skip: %s", _ge)

        _logger.info(
            "DoD ok: %s vs %s n=%d mean=%.3fm p98=%.3fm bias=%.3fm png=%s",
            before.id, after.id, n_valid, stats["mean_m"],
            stats["p98_abs_m"], stats["rtk_bias_m"], png_path,
        )

        return DsmDiffResult(
            pair=self.pair, bbox_wgs84=png_bbox, stats=stats,
            diff_raster_path=png_path,
        )

    def compute_diff(
        self,
        *,
        threshold_m: float = 0.0,
        out_dir: "Optional[Path]" = None,
        png_name: "Optional[str]" = None,
        vmax_m: "Optional[float]" = None,
        do_bias_correction: bool = True,
    ) -> "DsmDiffResult":
        """Phase 1 — DSM 차분 raster + 통계 + RdBu_r PNG 산출.

        🆕 (2026-06-11 S5) compute_dz() + render_dod() 의 thin wrapper 로 전환
        — 기존 시그니처·반환 그대로 (하위 호환). 캐시 분리 호출은
        _dod_helpers._compute_dz_cached / _compute_dod_cached 참조.

        Steps:
          1) compute_dz(): DSM open → 공통 grid reproject → Δz
             → RTK 편향보정 → 3x3 median filter
          2) render_dod(): threshold 마스킹 → 통계 → RdBu_r PNG + JSON
             (+ GeoTIFF) 저장
        """
        dz, grid_meta = self.compute_dz(do_bias_correction=do_bias_correction)
        return self.render_dod(
            dz, grid_meta,
            threshold_m=threshold_m,
            out_dir=out_dir,
            png_name=png_name,
            vmax_m=vmax_m,
        )
