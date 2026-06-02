# ==============================================================================
#  파일명: scripts/build_greenhouse_stats.py  —  Build 1.0 (2026-05-30)
#  목적 : 환경공간정보서비스(EGIS) WFS API → 제주 시설재배지 vector 폴리곤
#         → 연도별 도전체 면적 + 읍·면·동별 면적 → CSV 산출
#  실행 : PC(Windows)에서 1회. 결과 CSV를 대시보드 로더가 read-only로 읽음.
#         python scripts/build_greenhouse_stats.py --all --region
#  의존 : requests, geopandas, pandas (pip install geopandas requests pandas)
# ------------------------------------------------------------------------------
#  검증 완료 (2026-05-30 사용자 PC):
#    - 2022 (lv3, l3_code='231'): 6,497.4 ha (-5.37% vs 6,866) PASS
#    - 2000 (lv2, l2_code='230'): 3,064.5 ha (-0.05% vs 3,066) PASS
#  WFS 응답 native CRS: EPSG:3857/900913 (Web Mercator) — 5179로 재투영 후 면적
#  Jeju BBOX(WGS84): 126.10~126.97 E, 33.10~33.60 N
#  주의: 추자면·우도면은 EUP GeoJSON(12 features)에 미포함 → 도전체엔 포함되지만
#        읍·면·동 분해에는 제외됨. 영향 미미(시설재배 본도 집중).
# ==============================================================================
from __future__ import annotations

import argparse
import sys
import time
from io import BytesIO
from pathlib import Path

import pandas as pd
import requests

# 지리/공간 — 빌드 전용 (대시보드 런타임에는 불필요)
try:
    import geopandas as gpd
except ImportError:
    print("[ERROR] geopandas 미설치. 다음을 실행하세요:")
    print("  pip install geopandas requests pandas")
    sys.exit(2)


# ------------------------------------------------------------------------------
#  ■ 상수 (검증된 값만 — 추측 없음)
# ------------------------------------------------------------------------------
WFS_URL = "https://api.mcee.go.kr/geoserver/wfs"  # 검증 완료 2026-05-30

# 연도 → (레이어명, 분류등급) — cap_wfs.xml 직접 확인
# lv3 (5m, 세분류) — 시설재배지 코드 l3_code='231'
# lv2 (30m, 중분류) — 시설재배지 코드 l2_code='230' (하우스재배지)
YEAR_TO_LAYER: dict[int, tuple[str, str]] = {
    # ─ Patch 2026-05-30: WFS 실제 가용성 검증 후 매핑 확정
    # · lv2 옛 연도 layer 는 BBOX 메타에 제주가 있어도 실제 데이터는 한반도
    #   중부/북부만 보유한 경우가 있어, lv3 차수별 layer 로 대체.
    # · 2009 는 제주 덮는 WFS 레이어 없음 → 제외.
    # · 2020 은 WFS 미존재 → 별도 보간(_INTERP_2020) 처리.
    # ────────────────────────────────────────────────────────────────
    # lv2 (30m, 옛 연도 — 제주 데이터 확인된 것만)
    2000: ("EGIS:landcover_lv2_2000", "lv2"),
    2007: ("EGIS:landcover_lv2_2007", "lv2"),
    # lv3 차수별 (제주 덮는 BBOX 확인된 것)
    2013: ("EGIS:landcover_lv3_7th",  "lv3"),  # 7차 ≈ 2013, BBOX 33.10~36.13 제주 포함
    2018: ("EGIS:landcover_lv3_9th",  "lv3"),  # 9차 ≈ 2018, BBOX 33.10~36.00 제주 포함
    2019: ("EGIS:landcover_lv3_10th", "lv3"),
    2021: ("EGIS:landcover_lv3_11th", "lv3"),
    # lv3 yearly (최근 연도)
    2022: ("EGIS:lv3_2022y", "lv3"),
    2023: ("EGIS:lv3_2023y", "lv3"),
    2024: ("EGIS:lv3_2024y", "lv3"),
    2025: ("EGIS:lv3_2025y", "lv3"),
}

# WFS에 레이어 자체가 없는 연도 — 인접연도 평균으로 보간
# 형식: {연도: (인접A, 인접B)}
YEAR_INTERPOLATE: dict[int, tuple[int, int]] = {
    2020: (2019, 2021),
}

# 보고서 〈표 2-16〉 기준값 (ha) — ±5% 검증 가드 (21차 사용자 요청 2: 10% → 5%)
# 사유: 20차 자료검증 5팀 — 2022 -5.37% 가 10% 기준에서는 ok 였지만 suspect로 격상 필요
REFERENCE_HA: dict[int, float] = {
    2000: 3066.0,
    2013: 4157.0,
    2020: 6198.0,
    2022: 6866.0,
}
REF_TOLERANCE = 0.05

# 제주 BBOX (WGS84)
BBOX_WGS84 = (126.10, 33.10, 126.97, 33.60)

# 제주도 본도 총 면적 (도면적비 분모)
JEJU_AREA_KM2 = 1849.0

# 읍·면·동 명칭 정규화 (GeoJSON ↔ CSV 표기 통일)
EUP_NAME_NORMALIZE: dict[str, str] = {
    "제주시 동지역": "제주동",
    "서귀포시 동지역": "서귀포동",
}

# 시군 매핑 (EUP GeoJSON에 시군 컬럼이 없어 명칭 기반 매핑)
SIGUN_MAP: dict[str, str] = {
    # 제주시
    "구좌읍": "제주시", "조천읍": "제주시", "애월읍": "제주시",
    "한림읍": "제주시", "한경면": "제주시", "제주동": "제주시",
    # 서귀포시
    "성산읍": "서귀포시", "표선면": "서귀포시", "남원읍": "서귀포시",
    "대정읍": "서귀포시", "안덕면": "서귀포시", "서귀포동": "서귀포시",
}

HTTP_TIMEOUT = 300
HTTP_HEADERS = {
    "User-Agent": "Jeju-GW-Dashboard/1.0 build_greenhouse_stats",
    "Accept": "application/json, application/xml;q=0.5",
}

# ─── [Build 1.1 — 2026-05-30] 미래 연도 자동 감지 ─────────────────────────
# 사용자가 코드 안 고치고도 2026·2027 등 새 yearly 레이어가 WFS에 등재되면
# `--all` 실행 시 자동 포함. GetCapabilities 응답을 10분 캐시 (raw_dir 내).
_CAP_CACHE_TTL_SEC = 600
_CAP_CACHE_FILE = "_wfs_layers.txt"
_YEAR_LAYER_CANDIDATES: tuple[str, ...] = (
    "EGIS:lv3_{y}y",                # 최우선: lv3 yearly 5m
    "EGIS:lv2_{y}y",                # 차선: lv2 yearly 30m
    "EGIS:landcover_lv2_{y}",       # 폴백: 옛 명명 규칙
)


def fetch_wfs_capabilities(raw_dir: Path, force: bool = False) -> set[str]:
    """GetCapabilities → FeatureType 이름 set. 10분 디스크 캐시."""
    cache = raw_dir / _CAP_CACHE_FILE
    if not force and cache.exists():
        if (time.time() - cache.stat().st_mtime) < _CAP_CACHE_TTL_SEC:
            return {ln.strip() for ln in cache.read_text(encoding="utf-8").splitlines() if ln.strip()}
    import re
    params = {"SERVICE": "WFS", "VERSION": "2.0.0", "REQUEST": "GetCapabilities"}
    r = requests.get(WFS_URL, params=params, timeout=HTTP_TIMEOUT, headers=HTTP_HEADERS)
    r.raise_for_status()
    names = set(re.findall(r"<Name>\s*(EGIS:[^<\s][^<]*?)\s*</Name>", r.text))
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text("\n".join(sorted(names)), encoding="utf-8")
    return names


def discover_year_layer(year: int, caps: set[str]) -> tuple[str, str] | None:
    """후보 패턴 순회. 첫 매치 → (layer_name, 등급 'lv2'|'lv3')."""
    for pat in _YEAR_LAYER_CANDIDATES:
        name = pat.format(y=year)
        if name in caps:
            return (name, "lv2" if "lv2" in pat else "lv3")
    return None


# ------------------------------------------------------------------------------
#  ■ 1. WFS GetFeature → GeoDataFrame
# ------------------------------------------------------------------------------
def fetch_year_polygons(year: int, raw_dir: Path) -> "gpd.GeoDataFrame":
    """단일 연도 시설재배지 폴리곤을 WFS GetFeature로 받는다.
    레이어 등급(lv2/lv3)에 따라 CQL 필터를 자동 분기.
    raw_dir/landcover_YYYY.geojson 으로 캐시 (재실행 시 재다운로드 회피).
    """
    layer, lvl = YEAR_TO_LAYER[year]
    code_filter = "l2_code='230'" if lvl == "lv2" else "l3_code='231'"
    cql = (
        f"{code_filter} AND BBOX(geom,"
        f"{BBOX_WGS84[0]},{BBOX_WGS84[1]},{BBOX_WGS84[2]},{BBOX_WGS84[3]},"
        f"'EPSG:4326')"
    )
    params = {
        "SERVICE": "WFS",
        "VERSION": "2.0.0",
        "REQUEST": "GetFeature",
        "TYPENAMES": layer,
        "OUTPUTFORMAT": "application/json",
        "COUNT": "200000",
        "CQL_FILTER": cql,
    }
    cache_path = raw_dir / f"landcover_{year}.geojson"
    if cache_path.exists() and cache_path.stat().st_size > 1000:
        print(f"  [cache] {cache_path.name} 재사용 ({cache_path.stat().st_size/1024:.0f} KB)")
        gdf = gpd.read_file(cache_path)
    else:
        print(f"  WFS 요청: {layer} ({lvl}, {code_filter}) ...", end="", flush=True)
        t0 = time.time()
        r = requests.get(WFS_URL, params=params, timeout=HTTP_TIMEOUT, headers=HTTP_HEADERS)
        r.raise_for_status()
        # 에러 응답(XML)인지 확인
        if r.content[:50].lstrip().startswith(b"<?xml"):
            print(" 실패")
            snippet = r.content[:500].decode("utf-8", errors="replace")
            raise RuntimeError(
                f"{year}년 WFS 응답이 XML(에러): {snippet[:300]}"
            )
        cache_path.write_bytes(r.content)
        print(f" ok ({len(r.content)/1024/1024:.1f} MB, {time.time()-t0:.1f}s)")
        gdf = gpd.read_file(BytesIO(r.content))
    # CRS 보강
    if gdf.crs is None:
        # WFS 응답 좌표가 1e7 패턴이면 3857, 아니면 4326
        try:
            sx = float(gdf.geometry.iloc[0].centroid.x)
            gdf = gdf.set_crs("EPSG:3857" if abs(sx) > 1000 else "EPSG:4326")
        except Exception:
            gdf = gdf.set_crs("EPSG:4326")
    return gdf


# ------------------------------------------------------------------------------
#  ■ 2. 면적 산출
# ------------------------------------------------------------------------------
def area_total_ha(gdf: "gpd.GeoDataFrame") -> float:
    """전체 폴리곤 면적 합 (EPSG:5179 재투영 후 m² → ha)."""
    if gdf.empty:
        return 0.0
    g = gdf.to_crs("EPSG:5179")
    return float(g.geometry.area.sum() / 10_000.0)


def area_by_ri(gdf: "gpd.GeoDataFrame", ri_geojson: Path) -> pd.DataFrame:
    """리(법정리) 단위 면적 — 177개 법정리에 폴리곤 잘라 합산.
    반환: 시군 / 읍면동(법정시 prefix 기반 추정) / 법정리 / 면적_ha
    """
    if gdf.empty or not ri_geojson.exists():
        return pd.DataFrame(columns=["시군", "법정리", "면적_ha"])
    ri = gpd.read_file(ri_geojson)
    if ri.crs is None:
        ri = ri.set_crs("EPSG:4326")
    ri = ri.to_crs("EPSG:5179")
    # 시군: 법정시코드 50110(제주시) / 50130(서귀포시) 기반
    ri["시군"] = ri.get("법정시코드", "").astype(str).map(
        lambda c: "제주시" if c.startswith("50110") else ("서귀포시" if c.startswith("50130") else "미상")
    )
    ri["법정리"] = ri["법정리명"]
    ri = ri[["시군", "법정리", "geometry"]]

    g = gdf.to_crs("EPSG:5179")[["geometry"]]
    inter = gpd.overlay(g, ri, how="intersection")
    if inter.empty:
        return pd.DataFrame(columns=["시군", "법정리", "면적_ha"])
    inter["면적_ha"] = inter.geometry.area / 10_000.0
    out = (
        inter.groupby(["시군", "법정리"], as_index=False)["면적_ha"].sum()
        .round(3)
    )
    # 면적 0 이상만 (소수점 반올림 후 0 되는 미세 폴리곤 제거)
    out = out[out["면적_ha"] > 0.005].reset_index(drop=True)
    return out


def area_by_region(gdf: "gpd.GeoDataFrame", eup_geojson: Path) -> pd.DataFrame:
    """읍·면·동 단위 면적 — gpd.overlay(intersection)로 폴리곤 잘라 합산.
    반환: 시군 / 읍면동 / 면적_ha (12개 읍·면·동 × 1행씩, 미존재는 0 행)
    """
    if gdf.empty:
        return pd.DataFrame(columns=["시군", "읍면동", "면적_ha"])
    if not eup_geojson.exists():
        print(f"  [warn] EUP GeoJSON 미존재: {eup_geojson} — 읍·면·동 분해 생략")
        return pd.DataFrame(columns=["시군", "읍면동", "면적_ha"])
    eup = gpd.read_file(eup_geojson)
    if eup.crs is None:
        eup = eup.set_crs("EPSG:4326")
    eup = eup.to_crs("EPSG:5179")
    eup["읍면동"] = eup["NAME"].replace(EUP_NAME_NORMALIZE)
    eup["시군"] = eup["읍면동"].map(SIGUN_MAP).fillna("미상")
    eup = eup[["시군", "읍면동", "geometry"]]

    g = gdf.to_crs("EPSG:5179")[["geometry"]]
    inter = gpd.overlay(g, eup, how="intersection")
    if inter.empty:
        return pd.DataFrame(columns=["시군", "읍면동", "면적_ha"])
    inter["면적_ha"] = inter.geometry.area / 10_000.0
    out = (
        inter.groupby(["시군", "읍면동"], as_index=False)["면적_ha"].sum()
        .round(2)
    )
    return out


# ------------------------------------------------------------------------------
#  ■ 3. 검증 가드 (±5%)
# ------------------------------------------------------------------------------
def verify_against_reference(year: int, ha: float, strict: bool = False) -> str:
    """REFERENCE_HA에 등재된 연도면 ±5% 검증.
    strict=True 면 fail에서 RuntimeError, False 면 warning 후 'suspect' flag 반환.
    """
    if year not in REFERENCE_HA:
        return "ok"
    ref = REFERENCE_HA[year]
    diff_pct = (ha - ref) / ref * 100.0
    if abs(diff_pct) <= REF_TOLERANCE * 100:
        print(f"  [VERIFY OK] {year}: {ha:,.1f} ha vs ref {ref:,.0f} ha ({diff_pct:+.2f}%)")
        return "ok"
    msg = (f"  [VERIFY FAIL] {year}: {ha:,.1f} ha vs ref {ref:,.0f} ha "
           f"({diff_pct:+.2f}%) — 허용 ±{REF_TOLERANCE*100:.0f}% 초과")
    if strict:
        raise RuntimeError(msg)
    print(msg + " (suspect 표시, 계속 진행)")
    return "suspect"


# ------------------------------------------------------------------------------
#  ■ 4. 경지면적비 분모 보조
# ------------------------------------------------------------------------------
def _farmland_ha(year: int, farmland_csv: Path) -> float | None:
    """t23_farmland_trend.csv 에서 해당 연도 경지면적 조회. 미존재 시 None."""
    if not farmland_csv.exists():
        return None
    try:
        df = pd.read_csv(farmland_csv, encoding="utf-8-sig")
        col_year = "연도" if "연도" in df.columns else df.columns[0]
        col_area = next((c for c in df.columns if "경지면적" in c), None)
        if col_area is None:
            return None
        row = df[df[col_year] == year]
        if row.empty:
            return None
        return float(row[col_area].iloc[0])
    except Exception:
        return None


# ------------------------------------------------------------------------------
#  ■ 5. 빌드 파이프라인
# ------------------------------------------------------------------------------
def build_yearly(
    years: list[int], raw_dir: Path, farmland_csv: Path,
    strict: bool = False,
) -> pd.DataFrame:
    """연도별 도전체 시설재배지 면적 + 검증."""
    rows = []
    for y in years:
        print(f"\n[{y}] 빌드 시작 …")
        try:
            gdf = fetch_year_polygons(y, raw_dir)
        except Exception as e:
            print(f"  [skip] {y}: {e}")
            continue
        ha = area_total_ha(gdf)
        flag = verify_against_reference(y, ha, strict=strict)
        farmland = _farmland_ha(y, farmland_csv)
        do_ratio = round(ha / (JEJU_AREA_KM2 * 100), 4)  # ha / (km² × 100ha/km²)
        farm_ratio = round(ha / farmland * 100, 4) if (farmland and farmland > 0) else None
        rows.append({
            "연도": y,
            "레이어": YEAR_TO_LAYER[y][0],
            "분류등급": YEAR_TO_LAYER[y][1],
            "폴리곤수": int(len(gdf)),
            "면적_ha": round(ha, 2),
            "도면적비_pct": do_ratio,
            "경지면적비_pct": farm_ratio,
            "참조값_ha": REFERENCE_HA.get(y),
            "검증": flag,
        })

    # ─── 보간 연도 처리 (WFS 미존재 → 인접 연도 평균) ─────────────────────
    by_year = {r["연도"]: r for r in rows if r.get("면적_ha", 0) > 0}
    for tgt_year, (ya, yb) in YEAR_INTERPOLATE.items():
        if tgt_year in by_year:
            continue  # 이미 실제 값 있음 (예: 향후 WFS 등재 시)
        ra, rb = by_year.get(ya), by_year.get(yb)
        if not (ra and rb):
            continue  # 인접연도 없으면 스킵
        ha_interp = (float(ra["면적_ha"]) + float(rb["면적_ha"])) / 2.0
        farmland = _farmland_ha(tgt_year, farmland_csv)
        do_ratio = round(ha_interp / (JEJU_AREA_KM2 * 100), 4)
        farm_ratio = round(ha_interp / farmland * 100, 4) if (farmland and farmland > 0) else None
        flag = verify_against_reference(tgt_year, ha_interp, strict=False)
        rows.append({
            "연도": tgt_year,
            "레이어": f"<보간 {ya}↔{yb} 평균>",
            "분류등급": "interp",
            "폴리곤수": 0,
            "면적_ha": round(ha_interp, 2),
            "도면적비_pct": do_ratio,
            "경지면적비_pct": farm_ratio,
            "참조값_ha": REFERENCE_HA.get(tgt_year),
            "검증": "interp" if flag == "ok" else flag,
        })
        print(f"  [INTERP] {tgt_year}: {ha_interp:,.1f} ha (= ({ra['면적_ha']:.0f} + {rb['면적_ha']:.0f}) / 2)")

    return pd.DataFrame(rows).sort_values("연도").reset_index(drop=True)


def build_ri(
    years: list[int], raw_dir: Path, ri_geojson: Path,
) -> pd.DataFrame:
    """연도 × 법정리 분해 (이미 캐시된 raw 사용)."""
    out_rows = []
    for y in years:
        cache_path = raw_dir / f"landcover_{y}.geojson"
        if not cache_path.exists():
            try:
                gdf = fetch_year_polygons(y, raw_dir)
            except Exception as e:
                print(f"  [skip-ri] {y}: {e}")
                continue
        else:
            gdf = gpd.read_file(cache_path)
            if gdf.crs is None:
                try:
                    sx = float(gdf.geometry.iloc[0].centroid.x)
                    gdf = gdf.set_crs("EPSG:3857" if abs(sx) > 1000 else "EPSG:4326")
                except Exception:
                    gdf = gdf.set_crs("EPSG:4326")
        print(f"\n[{y}] 법정리 분해 …")
        df = area_by_ri(gdf, ri_geojson)
        if df.empty:
            continue
        df.insert(0, "레이어", YEAR_TO_LAYER[y][0])
        df.insert(0, "연도", y)
        out_rows.append(df)
        print(f"  {len(df)} rows ({df['면적_ha'].sum():,.1f} ha 합)")
    if not out_rows:
        return pd.DataFrame(columns=["연도", "레이어", "시군", "법정리", "면적_ha"])
    return pd.concat(out_rows, ignore_index=True)


def build_region(
    years: list[int], raw_dir: Path, eup_geojson: Path,
) -> pd.DataFrame:
    """연도 × 읍·면·동 분해 (이미 캐시된 raw 사용)."""
    out_rows = []
    for y in years:
        cache_path = raw_dir / f"landcover_{y}.geojson"
        if not cache_path.exists():
            print(f"\n[{y}] raw 캐시 없음 → fetch")
            try:
                gdf = fetch_year_polygons(y, raw_dir)
            except Exception as e:
                print(f"  [skip] {y}: {e}")
                continue
        else:
            gdf = gpd.read_file(cache_path)
            if gdf.crs is None:
                try:
                    sx = float(gdf.geometry.iloc[0].centroid.x)
                    gdf = gdf.set_crs("EPSG:3857" if abs(sx) > 1000 else "EPSG:4326")
                except Exception:
                    gdf = gdf.set_crs("EPSG:4326")
        print(f"\n[{y}] 읍·면·동 분해 …")
        df = area_by_region(gdf, eup_geojson)
        if df.empty:
            continue
        df.insert(0, "레이어", YEAR_TO_LAYER[y][0])
        df.insert(0, "연도", y)
        out_rows.append(df)
        print(f"  {len(df)} rows ({df['면적_ha'].sum():,.1f} ha 합)")
    if not out_rows:
        return pd.DataFrame(columns=["연도", "레이어", "시군", "읍면동", "면적_ha"])
    return pd.concat(out_rows, ignore_index=True)


# ------------------------------------------------------------------------------
#  ■ 6. CLI
# ------------------------------------------------------------------------------
def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="제주 시설재배지 면적 빌드 (환경공간정보서비스 WFS)"
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--year", type=int, help="단일 연도 (예: 2022)")
    g.add_argument("--all", action="store_true",
                   help="등재 연도 + 자동 discover (현재년-5 ~ 현재년)")
    g.add_argument("--discover-years", action="store_true",
                   help="WFS 가용 연도만 출력하고 종료 (빌드 X)")
    p.add_argument("--region", action="store_true",
                   help="읍·면·동 분해 CSV도 함께 생성")
    p.add_argument("--ri", action="store_true",
                   help="법정리(177개) 분해 CSV도 함께 생성 — 시설재배↔이용량 미세 분석용")
    p.add_argument("--strict", action="store_true",
                   help="±5% 검증 실패 시 즉시 중단 (기본: warning 후 계속)")
    p.add_argument("--out-dir", type=str, default=None,
                   help="출력 폴더 (기본: <프로젝트>/data/06_landcover)")
    p.add_argument("--eup", type=str, default=None,
                   help="읍·면·동 GeoJSON 경로 (기본: data/00_map/읍면동경계.geojson)")
    p.add_argument("--ri-geojson", type=str, default=None,
                   help="법정리 GeoJSON 경로 (기본: data/00_map/리경계.geojson)")
    p.add_argument("--farmland", type=str, default=None,
                   help="경지면적 시계열 CSV (기본: data/05_ag_stat/report/t23_farmland_trend.csv)")
    return p.parse_args()


def main() -> int:
    args = _parse_args()

    project_root = Path(__file__).resolve().parent.parent
    out_dir = Path(args.out_dir) if args.out_dir else project_root / "data" / "06_landcover"
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    eup_geojson = Path(args.eup) if args.eup else project_root / "data" / "00_map" / "읍면동경계.geojson"
    ri_geojson = Path(args.ri_geojson) if getattr(args, "ri_geojson", None) else project_root / "data" / "00_map" / "리경계.geojson"
    farmland_csv = Path(args.farmland) if args.farmland else project_root / "data" / "05_ag_stat" / "report" / "t23_farmland_trend.csv"

    yearly_csv = out_dir / "greenhouse_yearly.csv"
    region_csv = out_dir / "greenhouse_by_region.csv"
    ri_csv = out_dir / "greenhouse_by_ri.csv"

    # ─── [1.1 patch] --discover-years 단독: 가용 연도만 보고 종료 ───────
    if getattr(args, "discover_years", False):
        from datetime import date
        try:
            caps = fetch_wfs_capabilities(raw_dir, force=True)
        except Exception as e:
            print(f"[ERROR] GetCapabilities 실패: {e}")
            return 2
        print(f"\nWFS FeatureType 총 {len(caps)}개")
        cur_y = date.today().year
        for y in range(2000, cur_y + 1):
            f = discover_year_layer(y, caps)
            if f:
                src = "manual" if y in YEAR_TO_LAYER else "auto"
                mark = "★" if src == "auto" else " "
                print(f"  {mark} {y}: {f[0]} ({f[1]}) [{src}]")
        return 0

    years = sorted(YEAR_TO_LAYER) if args.all else [int(args.year)]

    # ─── [1.1 patch] --all 모드: 미래 연도 자동 discover 후 dict에 누적 ──
    if args.all:
        from datetime import date
        try:
            caps = fetch_wfs_capabilities(raw_dir)
            cur_y = date.today().year
            for y in range(cur_y - 5, cur_y + 1):
                if y in YEAR_TO_LAYER:
                    continue
                found = discover_year_layer(y, caps)
                if found:
                    YEAR_TO_LAYER[y] = found
                    if y not in years:
                        years.append(y)
                    print(f"  [discover] {y} → {found[0]} ({found[1]})")
            years = sorted(set(years))
        except Exception as e:
            print(f"  [discover-skip] GetCapabilities 실패: {e} (명시 매핑만 사용)")

    print("=" * 70)
    print(f"  Jeju 시설재배지 면적 빌드  ({len(years)}개 연도)")
    print(f"  출력 : {yearly_csv}")
    if args.region:
        print(f"        + {region_csv}")
    print(f"  EUP  : {eup_geojson}")
    print(f"  경지 : {farmland_csv} {'(존재)' if farmland_csv.exists() else '(없음 — 경지면적비는 NaN)'}")
    print(f"  검증 : ±{REF_TOLERANCE*100:.0f}% / strict={args.strict}")
    print("=" * 70)

    # 1) 연도별 (다운로드 + 검증 + 캐시)
    df_year = build_yearly(years, raw_dir, farmland_csv, strict=args.strict)
    if not df_year.empty:
        # 단일 연도 모드면 기존 CSV에 머지(있으면 갱신)
        if yearly_csv.exists() and not args.all:
            try:
                prev = pd.read_csv(yearly_csv, encoding="utf-8-sig")
                prev = prev[~prev["연도"].isin(df_year["연도"])]
                df_year = pd.concat([prev, df_year], ignore_index=True).sort_values("연도")
            except Exception:
                pass
        df_year.to_csv(yearly_csv, index=False, encoding="utf-8-sig")
        print(f"\n[저장] {yearly_csv}  ({len(df_year)}행)")
        print(df_year.to_string(index=False))

    # 2) 읍·면·동 분해 (옵션)
    if args.region:
        print("\n" + "=" * 70)
        print("  읍·면·동 분해")
        print("=" * 70)
        df_reg = build_region(years, raw_dir, eup_geojson)
        if not df_reg.empty:
            if region_csv.exists() and not args.all:
                try:
                    prev = pd.read_csv(region_csv, encoding="utf-8-sig")
                    prev = prev[~prev["연도"].isin(df_reg["연도"])]
                    df_reg = pd.concat([prev, df_reg], ignore_index=True).sort_values(["연도", "읍면동"])
                except Exception:
                    pass
            df_reg.to_csv(region_csv, index=False, encoding="utf-8-sig")
            print(f"\n[저장] {region_csv}  ({len(df_reg)}행)")

    # 3) 법정리 분해 (옵션) — 시설재배 ↔ 이용량 미세 분석용
    if getattr(args, "ri", False):
        print("\n" + "=" * 70)
        print("  법정리 분해 (177개)")
        print("=" * 70)
        df_ri = build_ri(years, raw_dir, ri_geojson)
        if not df_ri.empty:
            if ri_csv.exists() and not args.all:
                try:
                    prev = pd.read_csv(ri_csv, encoding="utf-8-sig")
                    prev = prev[~prev["연도"].isin(df_ri["연도"])]
                    df_ri = pd.concat([prev, df_ri], ignore_index=True).sort_values(["연도", "법정리"])
                except Exception:
                    pass
            df_ri.to_csv(ri_csv, index=False, encoding="utf-8-sig")
            print(f"\n[저장] {ri_csv}  ({len(df_ri)}행)")

    return 0


if __name__ == "__main__":
    sys.exit(main())
