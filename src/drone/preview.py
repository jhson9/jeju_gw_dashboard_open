"""DJI Terra 산출물 → Folium ImageOverlay 용 다운샘플 PNG.

- 정사사진(result.tif) → preview.png  (RGB, 미션 BBOX 크기)
- DSM(dsm.tif)         → dsm_heatmap.png  (viridis 색상매핑, alpha 마스킹)

원본 GeoTIFF 는 수억 픽셀이라 그대로 ImageOverlay 에 넣으면 브라우저가 멈춤.
첫 호출 시 max_side 이하로 thumbnail → data_drone/{id}/derived/*.png 저장.
원본 의 mtime 이 더 새로우면 자동 재생성.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

from .registry import Mission

_logger = logging.getLogger(__name__)

PREVIEW_FILENAME = "preview.png"
DSM_HEATMAP_FILENAME = "dsm_heatmap.png"
DERIVED_SUBDIR = "derived"


def derived_dir(mission: Mission) -> Path:
    """미션의 파생 산출물 폴더(필요 시 생성)."""
    d = mission.data_dir / DERIVED_SUBDIR
    d.mkdir(parents=True, exist_ok=True)
    return d


def preview_path(mission: Mission) -> Path:
    """preview.png 경로 — 존재 여부 무관, 경로만 반환."""
    return mission.data_dir / DERIVED_SUBDIR / PREVIEW_FILENAME


def dsm_heatmap_path(mission: Mission) -> Path:
    """DSM heatmap PNG 경로."""
    return mission.data_dir / DERIVED_SUBDIR / DSM_HEATMAP_FILENAME


def _needs_rebuild(src: Path, dst: Path) -> bool:
    if not dst.exists():
        return True
    try:
        return src.stat().st_mtime > dst.stat().st_mtime
    except OSError:
        return True


def get_or_make_preview(mission: Mission,
                        *,
                        max_side: int = 2048,
                        force: bool = False) -> Optional[Path]:
    """미션의 preview.png 경로 반환. 필요 시 생성.

    Parameters
    ----------
    mission : Mission
    max_side : int
        결과 PNG 의 긴 변 최대 픽셀 (기본 2048 — Folium ImageOverlay 성능 기준).
    force : bool
        True 면 mtime 비교 없이 무조건 재생성.

    Returns
    -------
    Path | None
        생성된 preview.png 의 절대경로. 원본이 없거나 변환 실패 시 None.
    """
    src = mission.output_path("tiles_2d")
    if not src or not src.exists():
        return None

    dst = preview_path(mission)
    if not force and not _needs_rebuild(src, dst):
        return dst

    derived_dir(mission)   # 폴더 보장

    from PIL import Image
    prev_limit = Image.MAX_IMAGE_PIXELS
    Image.MAX_IMAGE_PIXELS = None   # 큰 GeoTIFF 허용
    try:
        with Image.open(src) as img:
            # GeoTIFF → RGBA (배경 투명도 확보)
            if img.mode != "RGBA":
                img = img.convert("RGBA")
            img.thumbnail((max_side, max_side), Image.LANCZOS)
            img.save(dst, format="PNG", optimize=False)
        _logger.info("[drone.preview] built %s (%d×%d)", dst, *Image.open(dst).size)
        return dst
    except Exception as e:   # noqa: BLE001
        _logger.warning("[drone.preview] failed for %s: %s", src, e)
        # 깨진 파일 정리
        try:
            if dst.exists():
                dst.unlink()
        except OSError:
            pass
        return None
    finally:
        Image.MAX_IMAGE_PIXELS = prev_limit


def get_or_make_dsm_heatmap(mission: Mission,
                            *,
                            max_side: int = 2048,
                            colormap: str = "viridis",
                            force: bool = False) -> Optional[Path]:
    """DSM(GeoTIFF float32) → 색상 매핑된 PNG (Folium ImageOverlay 용).

    NoData(-9999, -inf, 한국 해발 -1000m 미만)는 알파 0(투명) 처리. 표고 범위는
    valid pixel 의 min~max 로 정규화 — 미션마다 색이 다르므로 caller 가 colorbar
    별도 표시 필요.

    Returns
    -------
    Path | None
        dsm_heatmap.png 경로. min/max 통계는 PNG 옆 dsm_heatmap.meta.json 에 저장.
    """
    src = mission.output_path("dsm")
    if not src or not src.exists():
        return None

    dst = dsm_heatmap_path(mission)
    if not force and not _needs_rebuild(src, dst):
        return dst

    derived_dir(mission)
    import numpy as np
    import matplotlib
    matplotlib.use("Agg")
    from matplotlib import cm
    from PIL import Image as PILImage

    prev_limit = PILImage.MAX_IMAGE_PIXELS
    PILImage.MAX_IMAGE_PIXELS = None
    try:
        with PILImage.open(src) as img:
            # 다운샘플 — DSM 은 대용량 float32, max_side 이하로 LANCZOS
            img.thumbnail((max_side, max_side), PILImage.LANCZOS)
            arr = np.array(img, dtype=np.float32)

        # NoData 마스킹
        nodata_mask = (~np.isfinite(arr)) | (arr <= -1000.0)
        valid = arr[~nodata_mask]
        if valid.size == 0:
            _logger.warning("[drone.preview] DSM 전부 NoData: %s", src)
            return None

        el_min = float(valid.min())
        el_max = float(valid.max())
        rng = max(el_max - el_min, 1e-6)
        norm = (arr - el_min) / rng
        norm = np.clip(norm, 0.0, 1.0)

        cmap = cm.get_cmap(colormap)
        rgba = cmap(norm)   # (H, W, 4) float 0~1
        rgba[nodata_mask, 3] = 0.0   # NoData 투명
        rgba_u8 = (rgba * 255).astype(np.uint8)
        out_img = PILImage.fromarray(rgba_u8, mode="RGBA")
        out_img.save(dst, format="PNG")

        # min/max 메타 동봉 — caller 가 colorbar 그릴 때 사용
        import json
        meta = {
            "el_min_m": el_min, "el_max_m": el_max,
            "colormap": colormap,
            "size": out_img.size,
        }
        with open(dst.with_suffix(".meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)

        _logger.info("[drone.preview] DSM heatmap %s (EL %.1f~%.1fm)", dst, el_min, el_max)
        return dst
    except Exception as e:   # noqa: BLE001
        _logger.warning("[drone.preview] DSM heatmap failed for %s: %s", src, e)
        try:
            if dst.exists():
                dst.unlink()
        except OSError:
            pass
        return None
    finally:
        PILImage.MAX_IMAGE_PIXELS = prev_limit


def load_dsm_meta(mission: Mission) -> Optional[dict]:
    """DSM heatmap meta(min/max EL) 읽기. 없으면 None."""
    import json
    p = dsm_heatmap_path(mission).with_suffix(".meta.json")
    if not p.exists():
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, json.JSONDecodeError):
        return None
