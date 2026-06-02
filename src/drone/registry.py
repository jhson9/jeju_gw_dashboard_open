"""드론 미션 레지스트리.

data_drone/registry.json + 미션별 meta.json 을 결합해 Mission 객체로 노출.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Optional
import config


class MissionNotFound(KeyError):
    """알 수 없는 mission_id 조회 시."""


@dataclass(frozen=True)
class Mission:
    """단일 미션. registry.json 의 한 entry + meta.json 결합 결과.

    site_id: 같은 장소(저수조 등)의 다른 시기 미션을 묶는 식별자. 시계열 비교
    (Phase 2) 에서 같은 site_id 미션 2개 이상을 before/after 쌍으로 사용.
    """
    id: str
    name: str
    site_type: str        # 저수조 / 관정 / 수원지 / 기타
    site_category: str    # 농업용 / 생활용 / ...
    eup_myeon_dong: str
    flight_date: str      # "YYYY-MM"
    data_dir: Path        # 절대 경로
    outputs: dict         # registry.json 의 outputs (가용성 플래그)
    meta: dict            # meta.json 내용 (없으면 빈 dict)
    site_id: str = ""     # 시계열 그룹 식별자 (없으면 빈 문자열)

    # ── 편의 접근자 ──
    def has(self, key: str) -> bool:
        """outputs[key].available 플래그. key: tiles_2d / tiles_3d / dsm / pointcloud_ply."""
        node = self.outputs.get(key) or {}
        return bool(node.get("available", False))

    def output_path(self, key: str, *, sub: str | None = None) -> Optional[Path]:
        """outputs[key].source / outputs[key].tileset / [key].path 의 절대경로 변환."""
        node = self.outputs.get(key) or {}
        rel = sub or node.get("source") or node.get("tileset") or node.get("path")
        if not rel:
            return None
        return self.data_dir / rel

    @property
    def bbox_wgs84(self) -> Optional[tuple[float, float, float, float]]:
        """(lon_min, lat_min, lon_max, lat_max) — meta.json 의 geo.bbox_wgs84.

        ⚠️ 정합성 (2026-05-29 회귀 fix):
          본 bbox 는 Leaflet ImageOverlay 의 bounds 와 측정 도구의 픽셀↔
          위경도 변환에 직접 사용. **반드시 result.tif 의 georeferencing
          과 일치해야** Tab32 거리 측정값이 정확.
          신규 미션 import 후 또는 메타 수동 편집 후엔 데이터 관리 탭의
          "메타 bbox 정합성 검사" 또는
          `src.drone.meta_validator.check_mission_bbox(mission_dir)` 로
          확인 권장.
          이 규약을 어기면 Tab32 측정값이 비율만큼 왜곡됨 (실측 사례:
          lon×2.02 → 가로 거리 2배 부풀림).
        """
        b = (self.meta.get("geo") or {}).get("bbox_wgs84")
        return tuple(b) if b and len(b) == 4 else None

    @property
    def center_wgs84(self) -> Optional[tuple[float, float]]:
        """(lat, lon) — meta.json 의 geo.center_wgs84.

        ⚠️ 순서 주의: **(lat, lon)** — bbox_wgs84 의 [lon, lat] 순서와 다름.
           Folium map center, Cesium 카메라 초기 위치에서 일관되게
           (lat, lon) 으로 사용. 호출자가 [0]/[1] 인덱싱할 때 주의.
        """
        c = (self.meta.get("geo") or {}).get("center_wgs84")
        return tuple(c) if c and len(c) == 2 else None

    @property
    def z_trusted(self) -> bool:
        """Z(표고) 값을 신뢰할 수 있는지 — RTK Fix 모드만 자동 True.

        판정 우선순위:
          1. meta.json 의 survey_info.z_trusted 가 명시되어 있으면 그 값 (override)
          2. survey_info.rtk_mode 에 'fix' 포함 (대소문자 무관) → True
          3. 그 외 (Single / 일반 GPS / 미상) → False

        DJI Terra 의 RTK Single 모드는 RTK 신호 수신 실패 시의 GPS 단독 측위.
        절대 정확도 RMSE 0.3~1m 수준이라 Z(표고) 값을 의사결정에 쓰면 위험.
        Fix 모드는 RTK 보정 완료 — cm 단위 정확도라 표고 신뢰 가능.

        특정 미션을 강제로 신뢰하려면 meta.json 의 survey_info 에
        "z_trusted": true 한 줄 추가.
        """
        survey = self.meta.get("survey_info") or {}
        explicit = survey.get("z_trusted")
        if explicit is not None:
            return bool(explicit)
        rtk_mode = str(survey.get("rtk_mode") or "").lower()
        return "fix" in rtk_mode


class DroneRegistry:
    """미션 enumerate · 조회 진입점. JSON 파일은 첫 호출 시 1회 로드.

    Parameters
    ----------
    data_root : Path | None
        data_drone 폴더 (기본: config.DRONE_DATA_ROOT).
    registry_file : Path | None
        registry.json 경로 (기본: data_root / "registry.json").
    """

    def __init__(self,
                 data_root: Optional[Path] = None,
                 registry_file: Optional[Path] = None):
        if data_root is None or registry_file is None:
            # 늦은 import — config 가 streamlit 외 환경에서도 동작하도록.
            try:
                from config import DRONE_DATA_ROOT, DRONE_REGISTRY_FILE
                data_root = data_root or DRONE_DATA_ROOT
                registry_file = registry_file or DRONE_REGISTRY_FILE
            except ImportError:
                pass
        self.data_root = Path(data_root) if data_root else Path(config.DRONE_DATA_ROOT)
        self.registry_file = Path(registry_file) if registry_file else self.data_root / "registry.json"
        self._missions: list[Mission] = self._load()

    def _load(self) -> list[Mission]:
        if not self.registry_file.exists():
            return []
        try:
            with open(self.registry_file, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError):
            return []

        out: list[Mission] = []
        for entry in (raw.get("missions") or []):
            mid = entry.get("id")
            if not mid:
                continue
            data_dir = self.data_root / entry.get("data_dir", mid)
            meta = self._load_meta(data_dir)
            out.append(Mission(
                id=mid,
                name=entry.get("name", mid),
                site_type=entry.get("site_type", "기타"),
                site_category=entry.get("site_category", ""),
                eup_myeon_dong=entry.get("eup_myeon_dong", ""),
                flight_date=entry.get("flight_date", ""),
                data_dir=data_dir,
                outputs=entry.get("outputs", {}),
                meta=meta,
                site_id=entry.get("site_id", ""),
            ))
        # sites 섹션도 함께 저장 (외부 조회용)
        self._sites_meta: dict = raw.get("sites") or {}
        return out

    @staticmethod
    def _load_meta(data_dir: Path) -> dict:
        p = data_dir / "meta.json"
        if not p.exists():
            return {}
        try:
            with open(p, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return {}

    # ── 컬렉션 API ──
    def __iter__(self) -> Iterable[Mission]:
        return iter(self._missions)

    def __len__(self) -> int:
        return len(self._missions)

    def list_missions(self) -> list[Mission]:
        return list(self._missions)

    def get(self, mission_id: str) -> Mission:
        for m in self._missions:
            if m.id == mission_id:
                return m
        raise MissionNotFound(mission_id)

    # ── 자료 가용성 합계 (메트릭 카드용) ──
    def count_available(self, key: str) -> int:
        return sum(1 for m in self._missions if m.has(key))

    # ── 미션별 산출물 경로 헬퍼 ──
    def get_result_tif(self, mission_id: str) -> Optional[Path]:
        return self.get(mission_id).output_path("tiles_2d")

    def get_dsm_tif(self, mission_id: str) -> Optional[Path]:
        return self.get(mission_id).output_path("dsm")

    def get_3dtiles_path(self, mission_id: str) -> Optional[Path]:
        return self.get(mission_id).output_path("tiles_3d")

    def get_bbox(self, mission_id: str) -> Optional[tuple[float, float, float, float]]:
        return self.get(mission_id).bbox_wgs84

    def get_center(self, mission_id: str) -> Optional[tuple[float, float]]:
        return self.get(mission_id).center_wgs84

    def refresh(self) -> None:
        """디스크 변경을 다시 읽어옴 (Streamlit cache 우회용)."""
        self._missions = self._load()

    # ── 시계열 그룹 API (Phase 2 — 같은 장소의 다른 시기 비교) ──────
    def list_sites(self) -> list[dict]:
        """등록된 site 목록 — registry.json sites 섹션 + 미션이 1건이라도 있는 site.

        반환 형식:
          [{site_id, name, site_type, missions: [Mission ...] (flight_date 오름차순)}, ...]
        """
        # 1) sites 섹션이 명시한 site_id 들
        seen: dict[str, dict] = {}
        for sid, meta in (getattr(self, "_sites_meta", {}) or {}).items():
            seen[sid] = {
                "site_id": sid,
                "name": meta.get("name", sid),
                "site_type": meta.get("site_type", "기타"),
                "missions": [],
            }
        # 2) 각 미션 → 해당 site 에 append (sites 에 미등록이면 자동 추가)
        for m in self._missions:
            sid = m.site_id or m.id   # site_id 없으면 미션 ID 자체를 site_id 로
            if sid not in seen:
                seen[sid] = {
                    "site_id": sid,
                    "name": m.name,
                    "site_type": m.site_type,
                    "missions": [],
                }
            seen[sid]["missions"].append(m)
        # 3) 미션 시간순 정렬
        for sid, info in seen.items():
            info["missions"].sort(key=lambda mm: mm.flight_date)
        return list(seen.values())

    def get_missions_by_site(self, site_id: str) -> "list[Mission]":
        """특정 site_id 의 모든 미션 반환 (flight_date 정렬)."""
        out = [m for m in self._missions if m.site_id == site_id]
        return sorted(out, key=lambda m: m.flight_date)

    def list_comparable_sites(self) -> "list[dict]":
        """재측량 비교 가능한 사이트만 반환 (미션 ≥ 2건).

        Tab31 의 "재측량 비교 분석" 섹션과 src/drone/diff.py 가 호출.

        Returns
        -------
        list[dict]
            [{"site_id": str, "name": str, "site_type": str,
              "missions": [Mission, ...]   # flight_date 오름차순
             }, ...]
            site_id 가 없거나(빈 문자열) 미션이 1건뿐인 사이트는 제외.

        2026-05-29 회귀 fix:
          truncation 복원 시 본 메서드가 누락되어 Tab31 에서 AttributeError
          발생 (사용자 보고). 다시 추가.
        """
        by_site: dict = {}
        for m in self._missions:
            sid = (m.site_id or "").strip()
            if not sid:
                continue
            by_site.setdefault(sid, []).append(m)

        sites_meta = getattr(self, "_sites_meta", {}) or {}

        out: list = []
        for sid, missions in by_site.items():
            if len(missions) < 2:
                continue
            site_info = sites_meta.get(sid) or {}
            name = site_info.get("name") or missions[0].name or sid
            site_type = site_info.get("site_type") or missions[0].site_type or "瑤타"
            # site_type fallback "기타" — escape 로 안전 작성
            if site_type == "瑤타":
                site_type = "기타"
            out.append({
                "site_id":   sid,
                "name":      name,
                "site_type": site_type,
                "missions":  sorted(missions, key=lambda mm: mm.flight_date),
            })
        return sorted(out, key=lambda x: x["name"])

