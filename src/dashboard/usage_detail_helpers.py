# ==============================================================================
#  파일명: src/dashboard/usage_detail_helpers.py  -  Build 1.0
#  Changelog:
#   - 2026-05-07: 신규 추가 (tab10 ⑥-2 이용량 세부 분석 데이터 헬퍼)
#   - 2026-05-29 (P3-2): ⚠️ 본 모듈은 사실상 dead code 상태.
#     · 메인 코드 호출 0건 (verified by 검증9팀)
#     · `_tab22_helpers.py:34` 에 `import udh` 가 남아있으나 `udh.` 호출 없음
#       → P3-4 에서 제거 예정.
#     · 유일한 외부 참조: `tests/test_tab10_smoke.py`, `tests/test_smoke_imports.py`
#     · 모듈 통째 삭제하면 위 테스트가 깨지므로 격리 보류, 본 deprecation
#       주석으로만 표시. 신규 코드는 본 모듈에서 import 하지 말 것.
# ------------------------------------------------------------------------------
#  설계 원칙 (Build 1.0 시점):
#   - docs/data/ 의 마스터/지오/샘플 매트릭스를 1차 소스로 사용.
#   - 가능하면 기존 ag_well_loader / ag_well_metrics 헬퍼로 런타임 산출 시도,
#     실패하면 docs/data/*_sample.csv 폴백 (오프라인 호환).
#   - spec_tab22_ag_usage_detail.md 의 헬퍼 시그니처를 그대로 구현.
#   - 모든 데이터 파일 경로는 모듈 위치 기준 절대 경로 (Path).
#   - @st.cache_data(ttl=3600, max_entries=32), 캐시 키에 year_range / agg_unit 포함.
#   - DIVERGING_USAGE / EUP_GRID_LAYOUT / HALLASAN_BLANK 상수는 spec 그대로.
# ==============================================================================

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st

logger = logging.getLogger(__name__)


# ──────────────────────────────────────────────────────────────────
#  상수 (spec §0.2 그대로)
# ──────────────────────────────────────────────────────────────────
DIVERGING_USAGE: list[str] = [
    "#2c7fb8", "#7fcdbb", "#ffffd9", "#fec44f", "#d7301f",
]

EUP_GRID_LAYOUT: dict[str, tuple[int, int]] = {
    "한림읍": (0, 0), "애월읍": (0, 1), "제주시 동지역": (0, 2), "조천읍": (0, 3),
    "한경면": (1, 0),                                              "구좌읍": (1, 3),
    "대정읍": (2, 0),                                              "성산읍": (2, 3),
    "안덕면": (3, 0), "서귀포시 동지역": (3, 1), "남원읍": (3, 2), "표선면": (3, 3),
}

HALLASAN_BLANK: list[tuple[int, int]] = [(1, 1), (1, 2), (2, 1), (2, 2)]

FONT_FAMILY: str = "Malgun Gothic, Noto Sans KR, sans-serif"
DEFAULT_RATIO_MID: float = 30.9
DEFAULT_AVG_MID: float = 7729.0


# ──────────────────────────────────────────────────────────────────
#  데이터 파일 경로 — 모듈 기준 ../../docs/data/
# ──────────────────────────────────────────────────────────────────
_MODULE_DIR = Path(__file__).resolve().parent
_DATA_DIR = _MODULE_DIR.parents[1] / "docs" / "data"


def _data_path(filename: str) -> Path:
    """docs/data/<filename> 절대 경로."""
    return _DATA_DIR / filename


# ──────────────────────────────────────────────────────────────────
#  로더 — 마스터 / 지오 / 핫스팟
# ──────────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600, max_entries=32)
def load_master() -> pd.DataFrame:
    """docs/data/usage_detail_master.json 의 12행 마스터 DataFrame."""
    p = _data_path("usage_detail_master.json")
    with p.open("r", encoding="utf-8-sig") as f:
        payload = json.load(f)
    rows = payload.get("rows", [])
    return pd.DataFrame(rows)


@st.cache_data(ttl=3600, max_entries=32)
def load_eup_geometry() -> pd.DataFrame:
    """docs/data/eup_geometry.csv (12 읍/면/동 + 중앙 보전구역 1행)."""
    p = _data_path("eup_geometry.csv")
    return pd.read_csv(p, encoding="utf-8-sig")


@st.cache_data(ttl=3600, max_entries=32)
def load_ri_centroids() -> pd.DataFrame:
    """docs/data/ri_centroids.csv (172행)."""
    p = _data_path("ri_centroids.csv")
    return pd.read_csv(p, encoding="utf-8-sig")


@st.cache_data(ttl=3600, max_entries=32)
def load_hotspots() -> dict[str, Any]:
    """docs/data/hotspots.json — hot/cold/hot_values/cold_values."""
    p = _data_path("hotspots.json")
    with p.open("r", encoding="utf-8-sig") as f:
        return json.load(f)


# ──────────────────────────────────────────────────────────────────
#  샘플 매트릭스 로더 (헤더 주석 라인 # 으로 시작 — pandas comment='#')
# ──────────────────────────────────────────────────────────────────
def _read_sample_matrix(filename: str) -> pd.DataFrame:
    """sample csv 를 읽어 index=eup_dong, columns=1..12 매트릭스로 반환."""
    p = _data_path(filename)
    df = pd.read_csv(p, encoding="utf-8-sig", comment="#")
    df = df.set_index("eup_dong")
    rename = {f"m{m}": m for m in range(1, 13)}
    df = df.rename(columns=rename)
    cols = [c for c in range(1, 13) if c in df.columns]
    return df[cols]


# ──────────────────────────────────────────────────────────────────
#  매트릭스 빌더
#  -------------------------------------------------------------------
#  1차 시도: tab7 헬퍼 기반 런타임 산출 (ag_well_loader / ag_well_metrics)
#  실패 시: 샘플 csv 폴백
# ──────────────────────────────────────────────────────────────────
def _try_runtime_monthly_matrix(
    year_range: tuple[int, int],
    agg_unit: str,
) -> pd.DataFrame | None:
    """ag_well_loader 기반 런타임 산출 시도. 실패 시 None.

    agg_unit:
      - "시"          : index=["제주시","서귀포시"]
      - "읍/면/동"    : index=12개 읍/면/동
      - "리"          : 본 함수에서는 None 반환 (리는 build_ri_monthly_matrix 사용)
    """
    if agg_unit == "리":
        return None
    try:
        from src.analysis import ag_well_loader  # type: ignore
        from src.analysis import ag_well_metrics  # type: ignore
    except Exception:
        return None
    try:
        # 모집단 규칙(2026-05-27): 대상 관정은 active 플래그가 아니라 '이용량'
        # 으로 결정. → 마스터는 전체(active_only=False)로 불러 지역귀속(시/읍면동)
        # 만 부여하고(left join 으로 이용량 행 보존), 모집단은 연 100㎥ 규칙으로
        # 필터한다. 분자(이용량 합)·분모가 동일 (관정,연도) 집합을 공유.
        df_master = ag_well_loader.load_master(active_only=False)
        df_usage = ag_well_loader.load_usage_long()
        if df_usage is None or df_usage.empty:
            return None
        keep_cols = ["permit_no"] + [
            c for c in ("well_si", "well_eup") if c in df_master.columns
        ]
        merged = df_usage.merge(
            df_master[keep_cols].drop_duplicates("permit_no"),
            on="permit_no", how="left",
        )
        merged = merged[
            (merged["year"] >= year_range[0])
            & (merged["year"] <= year_range[1])
        ]
        # 연 100㎥ 미만 (관정,연도) 제외 → 휴면/미사용 관정 배제
        merged = ag_well_metrics.filter_population_by_annual_usage(merged)
        if merged.empty:
            return None
        if "month" not in merged.columns or "volume_m3" not in merged.columns:
            return None

        if agg_unit == "시":
            group_col = "well_si"
        else:
            group_col = "well_eup"

        if group_col not in merged.columns:
            return None

        # 동지역 처리: ○○동 → "동지역" 통합 (tab7 패턴 차용, 단순화 버전)
        if group_col == "well_eup":
            eup = merged[group_col].astype(str).str.strip().replace(
                {"nan": "", "None": "", "NaN": "", "<NA>": ""}
            )
            merged[group_col] = eup.where(
                ~eup.str.endswith("동", na=False), "동지역"
            )
            # well_si 가 있으면 "제주시 동지역"/"서귀포시 동지역" 으로 변환
            if "well_si" in merged.columns:
                is_dong = merged[group_col] == "동지역"
                merged.loc[is_dong, group_col] = (
                    merged.loc[is_dong, "well_si"].astype(str).str.strip()
                    + " 동지역"
                )

        # 월 평균을 위한 분모 = '실제 데이터가 존재하는 연도 수' (L4 수정
        # 2026-05-27). 기존엔 명목 기간폭(year_range[1]-[0]+1)으로 나눠,
        # 일부 연도 자료가 비면 평균이 과소 산출됐음(예: 5년치만 있는데 ÷9).
        n_years = max(1, int(merged["year"].nunique()))
        pivot = (
            merged.groupby([group_col, "month"])["volume_m3"]
            .sum()
            .unstack(fill_value=0.0)
        )
        # 월 평균 (자료 보유 연도 기준의 월합 평균)
        pivot = pivot / float(n_years)
        for m in range(1, 13):
            if m not in pivot.columns:
                pivot[m] = 0.0
        pivot = pivot[[m for m in range(1, 13)]]
        pivot.index.name = group_col
        return pivot
    except Exception:
        # 빈 차트 원인 진단을 위해 로깅 — 마스터 부재/스키마 변경/컬럼 누락
        # 등 무엇이 실패했는지 stacktrace 보존. 호출자는 폴백 경로 계속 사용.
        logger.debug("_try_runtime_monthly_matrix failed", exc_info=True)
        return None


@st.cache_data(ttl=3600, max_entries=32)
def build_monthly_heatmap_df(
    year_range: tuple[int, int] = (2024, 2025),
    agg_unit: str = "읍/면/동",
) -> pd.DataFrame:
    """index=region, columns=1..12, values=월이용량 (m³).

    런타임 산출이 가능하면 우선 사용, 실패 시 샘플 매트릭스 폴백.
    """
    runtime = _try_runtime_monthly_matrix(year_range, agg_unit)
    if runtime is not None and not runtime.empty:
        return runtime

    df = _read_sample_matrix("monthly_matrix_sample.csv")

    if agg_unit == "시":
        master = load_master()
        zone = df.index.map(
            lambda x: "제주시" if EUP_GRID_LAYOUT.get(x, (3, 0))[0] <= 1 else "서귀포시"
        )
        tmp = df.copy()
        tmp["_zone"] = zone
        agg = tmp.groupby("_zone").sum(numeric_only=True)
        agg = agg.reindex(["제주시", "서귀포시"])
        _ = master  # 명시적 unused 회피
        return agg
    return df


@st.cache_data(ttl=3600, max_entries=32)
def build_ratio_matrix(
    year_range: tuple[int, int] = (2024, 2025),
    agg_unit: str = "읍/면/동",
) -> pd.DataFrame:
    """월이용량 / (permit_m3day × 30) × 100. 단위 = %, midpoint = DEFAULT_RATIO_MID."""
    # 런타임 monthly 가 있으면 master 의 permit_m3day 로 즉석 산출
    monthly = _try_runtime_monthly_matrix(year_range, agg_unit)
    master = load_master()
    if monthly is not None and not monthly.empty and agg_unit == "읍/면/동":
        permit = master.set_index("eup_dong")["permit_m3day"].astype(float)
        idx = monthly.index.intersection(permit.index)
        if len(idx) > 0:
            denom = (permit.loc[idx] * 30.0).replace(0.0, pd.NA)
            ratio = monthly.loc[idx].div(denom, axis=0) * 100.0
            return ratio.fillna(0.0)
    # 폴백: 샘플 ratio 매트릭스
    df = _read_sample_matrix("ratio_matrix_sample.csv")
    if agg_unit == "시":
        zone = df.index.map(
            lambda x: "제주시" if EUP_GRID_LAYOUT.get(x, (3, 0))[0] <= 1 else "서귀포시"
        )
        tmp = df.copy()
        tmp["_zone"] = zone
        return tmp.groupby("_zone").mean(numeric_only=True).reindex(
            ["제주시", "서귀포시"]
        )
    return df


@st.cache_data(ttl=3600, max_entries=32)
def build_unit_area_matrix(
    year_range: tuple[int, int] = (2024, 2025),
    agg_unit: str = "읍/면/동",
) -> pd.DataFrame:
    """월이용량 / 농지면적_ha. 단위 = m³/ha."""
    monthly = _try_runtime_monthly_matrix(year_range, agg_unit)
    master = load_master()
    if monthly is not None and not monthly.empty and agg_unit == "읍/면/동":
        farm = master.set_index("eup_dong")["farm_area_ha"].astype(float)
        idx = monthly.index.intersection(farm.index)
        if len(idx) > 0:
            denom = farm.loc[idx].replace(0.0, pd.NA)
            ua = monthly.loc[idx].div(denom, axis=0)
            return ua.fillna(0.0)
    df = _read_sample_matrix("unit_area_matrix_sample.csv")
    if agg_unit == "시":
        zone = df.index.map(
            lambda x: "제주시" if EUP_GRID_LAYOUT.get(x, (3, 0))[0] <= 1 else "서귀포시"
        )
        tmp = df.copy()
        tmp["_zone"] = zone
        return tmp.groupby("_zone").mean(numeric_only=True).reindex(
            ["제주시", "서귀포시"]
        )
    return df


# ──────────────────────────────────────────────────────────────────
#  리 단위 월별 매트릭스 (섹션 F)
# ──────────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600, max_entries=32)
def build_ri_monthly_matrix(
    year_range: tuple[int, int] = (2024, 2025),
) -> pd.DataFrame:
    """index=법정리명, columns=1..12. 데이터 부재 시 샘플 매트릭스로 분배 추정.

    리 단위 사용량은 동/읍/면/동 매트릭스에서 면적 비례 분할로 폴백.
    런타임 산출이 가능해지면 본 함수만 교체.
    """
    ri_df = load_ri_centroids()
    monthly_eup = build_monthly_heatmap_df(year_range, "읍/면/동")
    rows = []
    for eup_name, sub in ri_df.groupby("eup_dong"):
        if eup_name not in monthly_eup.index:
            continue
        total_area = sub["area_km2"].sum()
        if total_area <= 0:
            continue
        eup_row = monthly_eup.loc[eup_name]
        for _, ri in sub.iterrows():
            share = float(ri["area_km2"]) / float(total_area)
            r = (eup_row * share).copy()
            r["법정리명"] = ri["법정리명"]
            r["eup_dong"] = eup_name
            r["lon"] = ri.get("lon")
            r["lat"] = ri.get("lat")
            r["area_km2"] = ri.get("area_km2")
            rows.append(r)
    if not rows:
        return pd.DataFrame(columns=list(range(1, 13)))
    out = pd.DataFrame(rows)
    out = out.set_index("법정리명")
    return out


# ──────────────────────────────────────────────────────────────────
#  핫스팟 마커 좌표 (섹션 C)
# ──────────────────────────────────────────────────────────────────
def annotate_hotspots(df: pd.DataFrame) -> list[dict[str, Any]]:
    """Heatmap 위에 표시할 ▲(hot) ▽(cold) annotation 좌표 리스트.

    반환: [{"x": <month or label>, "y": <region>, "text": "▲", "kind": "hot"}, ...]
    df.index 에 존재하는 region 만 추가.
    """
    hs = load_hotspots()
    out: list[dict[str, Any]] = []
    if df is None or df.empty:
        return out
    for region in hs.get("hot", []):
        if region in df.index:
            out.append(
                {"y": region, "text": "▲", "kind": "hot",
                 "value": hs.get("hot_values", {}).get(region)}
            )
    for region in hs.get("cold", []):
        if region in df.index:
            out.append(
                {"y": region, "text": "▽", "kind": "cold",
                 "value": hs.get("cold_values", {}).get(region)}
            )
    return out


# ──────────────────────────────────────────────────────────────────
#  검증 헬퍼 — eup_geometry.csv 로부터 grid 매핑 산출
# ──────────────────────────────────────────────────────────────────
@st.cache_data(ttl=3600, max_entries=32)
def grid_from_centroids() -> dict[str, tuple[int, int]]:
    """eup_geometry.csv 의 grid_row/grid_col 컬럼에서 매핑 산출 (검증용).

    중앙 보전구역 행은 grid 가 NaN 이라 자동 제외 → 12개 읍/면/동만 반환.
    이 결과는 EUP_GRID_LAYOUT 과 100% 일치해야 함 (spec H10).
    """
    df = load_eup_geometry()
    df = df.dropna(subset=["grid_row", "grid_col"])
    out: dict[str, tuple[int, int]] = {}
    for _, row in df.iterrows():
        out[str(row["eup_dong"])] = (int(row["grid_row"]), int(row["grid_col"]))
    return out


# ──────────────────────────────────────────────────────────────────
#  유틸 — 매트릭스 중앙값
# ──────────────────────────────────────────────────────────────────
def compute_midpoint(matrix: pd.DataFrame, percentile: float = 50.0) -> float:
    """매트릭스 전체 값의 percentile 분위 — cmid/zmid 기본값 산출용."""
    if matrix is None or matrix.empty:
        return 0.0
    vals = matrix.to_numpy(dtype=float).ravel()
    vals = vals[~pd.isna(vals)]
    if vals.size == 0:
        return 0.0
    return float(pd.Series(vals).quantile(percentile / 100.0))


# ──────────────────────────────────────────────────────────────────
#  트리맵 재설계 (PPT 원본 형식, 2026-05-07 추가)
#  spec_treemap_redesign.md §A/§E.2 기준
# ──────────────────────────────────────────────────────────────────
TREEMAP_ZONE_ORDER: tuple[str, ...] = ("제주시", "서귀포시")
TREEMAP_EUP_ORDER: dict[str, list[str]] = {
    "제주시": ["한경면", "한림읍", "애월읍", "제주시 동지역", "조천읍", "구좌읍"],
    "서귀포시": ["대정읍", "안덕면", "서귀포시 동지역", "표선면", "남원읍", "성산읍"],
}
TREEMAP_ROW_Y: dict[str, tuple[float, float]] = {
    "제주시": (0.55, 1.00),
    "서귀포시": (0.00, 0.45),
}
TREEMAP_COLOR_CMIN: float = 1100.0
TREEMAP_COLOR_CMAX: float = 2300.0
TREEMAP_COLORSCALE: str = "YlOrRd"


@st.cache_data(ttl=3600, max_entries=32)
def load_treemap_eup_cells() -> pd.DataFrame:
    """docs/data/treemap_eup_cells.csv 12행 로드 (트리맵 셀 사전 산출 데이터)."""
    p = _data_path("treemap_eup_cells.csv")
    df = pd.read_csv(p, encoding="utf-8-sig")
    return df


@st.cache_data(ttl=3600, max_entries=32)
def load_treemap_ri_cells() -> pd.DataFrame:
    """docs/data/treemap_ri_cells.csv 171행 로드 (리 단위 사전 산출 데이터)."""
    p = _data_path("treemap_ri_cells.csv")
    df = pd.read_csv(p, encoding="utf-8-sig")
    return df


def compute_eup_color_value(
    eup_dong: str,
    year_range: tuple[int, int],
    month_range: tuple[int, int],
    master_df: pd.DataFrame,
) -> float:
    """단위면적당 연간이용량 (㎥/ha) 산출.

    공식: avg_monthly_usage_m3 × wells_public × n_months / farm_area_ha
        - n_months = (month_range 내 월 수) × (year_range 연 수) 기반 정규화
        - 명세 기본 산식은 ×12 (연간) 이지만 month_range 미만이면 비례 축소

    실제 월별 데이터(ag_well_loader.load_usage_long) 가 있으면 우선 사용,
    실패 시 마스터 평균값 폴백.
    """
    # 1차 시도: 런타임 월별 데이터
    try:
        from src.analysis import ag_well_loader  # type: ignore
        from src.analysis import ag_well_metrics  # type: ignore

        # 모집단 규칙(2026-05-27): active 플래그 대신 이용량으로 모집단 결정.
        df_master_ag = ag_well_loader.load_master(active_only=False)
        df_usage = ag_well_loader.load_usage_long()
        if df_usage is not None and not df_usage.empty:
            keep_cols = ["permit_no"] + [
                c for c in ("well_si", "well_eup") if c in df_master_ag.columns
            ]
            merged = df_usage.merge(
                df_master_ag[keep_cols].drop_duplicates("permit_no"),
                on="permit_no",
                how="left",
            )
            merged = merged[
                (merged["year"] >= year_range[0])
                & (merged["year"] <= year_range[1])
                & (merged["month"] >= month_range[0])
                & (merged["month"] <= month_range[1])
            ]
            # 연 100㎥ 미만 (관정,연도) 제외 (해당 연도 기준)
            merged = ag_well_metrics.filter_population_by_annual_usage(merged)
            if not merged.empty and "well_eup" in merged.columns:
                eup_col = merged["well_eup"].astype(str).str.strip()
                # 동지역 통합
                if "well_si" in merged.columns:
                    is_dong = eup_col.str.endswith("동", na=False)
                    si_col = merged["well_si"].astype(str).str.strip()
                    eup_col = eup_col.mask(is_dong, si_col + " 동지역")
                merged = merged.assign(_eup=eup_col)
                sub = merged[merged["_eup"] == eup_dong]
                if not sub.empty and "volume_m3" in sub.columns:
                    # 분모 = 실제 자료 보유 연도 수 (L4 수정 2026-05-27).
                    # 기존 명목 기간폭 분모는 결측 연도가 있으면 과소 산출.
                    n_years = max(1, int(sub["year"].nunique())) \
                        if "year" in sub.columns \
                        else max(1, year_range[1] - year_range[0] + 1)
                    n_months_window = max(1, month_range[1] - month_range[0] + 1)
                    # 연간 이용량 환산 (월 범위가 일부면 12/n 으로 비례 확장 —
                    # 월별 사용량 균일 가정의 근사치. 계절성 큰 경우 한계 있음)
                    period_total = float(sub["volume_m3"].sum())
                    annual_total = period_total / n_years * (12.0 / n_months_window)
                    if "eup_dong" in master_df.columns:
                        farm_row = master_df[master_df["eup_dong"] == eup_dong]
                        if not farm_row.empty:
                            farm_ha = float(farm_row.iloc[0].get("farm_area_ha", 0))
                            if farm_ha > 0:
                                return annual_total / farm_ha
    except Exception:
        # 런타임 산출 실패 시 fallback (마스터 평균) 으로 진행. silent fail
        # 이 아니라 debug 레벨 로그 — 첫 호출에 자료가 없을 수도 있어 매번
        # WARNING 출력은 과한 것으로 판단 (오류팀4 권고 2026-05-08).
        import logging as _logging
        _logging.getLogger(__name__).debug(
            "런타임 ri_per_ha 산출 실패 — 마스터 평균 폴백",
            exc_info=True,
        )

    # 폴백: 마스터 평균 (avg_monthly_usage × wells_public × 12 / farm_area_ha)
    if "eup_dong" in master_df.columns:
        row = master_df[master_df["eup_dong"] == eup_dong]
        if not row.empty:
            r = row.iloc[0]
            avg = float(r.get("avg_monthly_usage_m3", 0) or 0)
            wells_pub = float(r.get("wells_public", 0) or 0)
            farm = float(r.get("farm_area_ha", 0) or 0)
            if farm > 0:
                return avg * wells_pub * 12.0 / farm
    # 셀 csv 폴백
    cells = load_treemap_eup_cells()
    cell = cells[cells["eup_dong"] == eup_dong]
    if not cell.empty:
        return float(cell.iloc[0]["color_value_default"])
    return float("nan")


@st.cache_data(ttl=3600, max_entries=32)
def build_eup_treemap_payload(
    year_range: tuple[int, int],
    month_range: tuple[int, int] = (1, 12),
) -> list[dict]:
    """읍/면/동 트리맵 셀 12개의 layout payload 빌드.

    각 셀:
      {"zone": "제주시"|"서귀포시", "eup_dong": str,
       "x0", "x1", "y0", "y1": float (0~1 정규화),
       "width_pct": float (0~100),
       "color_value": float (㎥/ha),
       "labels": [L1, L2, L3, L4]}

    - 제주시 행: y0=0.55, y1=1.00 (위)
    - 서귀포시 행: y0=0.00, y1=0.45 (아래)
    - 가운데 0.45~0.55: 한라산 캡션 영역
    - 각 행 내에서 width_pct 비율로 x0~x1 정규화 (합계=1.0).
    """
    cells = load_treemap_eup_cells()
    master = load_master()
    payload: list[dict] = []

    for zone in TREEMAP_ZONE_ORDER:
        y0, y1 = TREEMAP_ROW_Y[zone]
        order = TREEMAP_EUP_ORDER[zone]
        zone_cells = cells[cells["zone"] == zone].copy()
        zone_cells = zone_cells.sort_values("cell_order")
        # 순서 검증 (csv 가 명세 순서대로 저장되어 있다고 가정)
        total_w = float(zone_cells["width_pct"].sum())
        if total_w <= 0:
            continue
        x_cur = 0.0
        for eup_name in order:
            row_match = zone_cells[zone_cells["eup_dong"] == eup_name]
            if row_match.empty:
                continue
            row = row_match.iloc[0]
            w_norm = float(row["width_pct"]) / total_w
            x0 = x_cur
            x1 = x_cur + w_norm
            color_val = compute_eup_color_value(
                eup_name, year_range, month_range, master
            )
            # 라벨 4줄
            l1 = str(row["label_line1"])
            l2 = str(row["label_line2"])
            if pd.notna(color_val):
                l3 = f"{int(round(color_val)):,} ㎥/ha"
            else:
                l3 = "—"
            l4 = str(row["label_line4"])
            payload.append({
                "zone": zone,
                "eup_dong": eup_name,
                "x0": x0,
                "x1": x1,
                "y0": y0,
                "y1": y1,
                "width_pct": float(row["width_pct"]),
                "color_value": float(color_val) if pd.notna(color_val) else None,
                "labels": [l1, l2, l3, l4],
            })
            x_cur = x1
    return payload


#  ──────────────────────────────────────────────────────────────────
#  v2 (2026-05-07): 다이버징 색상 + 절대 연간 이용량 합계 라벨
#  ──────────────────────────────────────────────────────────────────
EUP_DONG_STANDARD: tuple[str, ...] = (
    "한경면", "한림읍", "애월읍", "제주시 동지역", "조천읍", "구좌읍",
    "대정읍", "안덕면", "서귀포시 동지역", "표선면", "남원읍", "성산읍",
)


def compute_eup_annual_volume(merged: pd.DataFrame) -> pd.Series:
    """이미 연도 필터된 merged DataFrame → 읍/면/동별 연간 이용량 합계 (m³).

    Parameters
    ----------
    merged : columns 'well_eup', 'volume_m3' 필수.
             'well_si' 가 있으면 동지역을 '제주시 동지역' / '서귀포시 동지역' 분리.

    Returns
    -------
    pd.Series : index=12개 표준 eup_dong, values=합계 m³ (없으면 0).
    """
    if merged is None or merged.empty or "well_eup" not in merged.columns:
        return pd.Series(0.0, index=list(EUP_DONG_STANDARD), name="volume_m3")

    work = merged.copy()
    eup_clean = (
        work["well_eup"].astype(str).str.strip()
            .replace({"nan": "", "None": "", "NaN": "", "<NA>": ""})
    )
    # 동지역 통합 → "제주시 동지역" / "서귀포시 동지역"
    is_dong = eup_clean.str.endswith("동", na=False) | (eup_clean == "")
    if "well_si" in work.columns:
        si_clean = work["well_si"].astype(str).str.strip()
        eup_clean = eup_clean.where(~is_dong, si_clean + " 동지역")
    else:
        eup_clean = eup_clean.where(~is_dong, "동지역")

    work = work.assign(_eup_norm=eup_clean)
    sums = work.groupby("_eup_norm")["volume_m3"].sum()

    out = pd.Series(0.0, index=list(EUP_DONG_STANDARD), name="volume_m3")
    for k, v in sums.items():
        if k in out.index and pd.notna(v):
            out.loc[k] = float(v)
    return out


def _format_volume_label(vol: float) -> str:
    """절대 m³ 값 → 자릿수 적응 라벨.

    - 1,000,000 이상 → "{vol/1000:,.0f} 천㎥"
    - 그 외          → "{vol:,.0f} ㎥"
    """
    if pd.isna(vol) or vol is None:
        return "—"
    v = float(vol)
    if v >= 1_000_000:
        return f"{v / 1000:,.0f} 천㎥"
    return f"{v:,.0f} ㎥"


def build_eup_treemap_payload_v2(annual_volume: pd.Series) -> list[dict]:
    """v2 트리맵 payload — 색상 변수 = 연간 이용량 합계, 셀 폭 = 농지면적 비율 고정.

    한라산 캡션 영역 제거 — 두 행 사이 빈 공간을 0.04 로 축소:
      제주시 행:    y0=0.52, y1=1.00
      서귀포시 행:  y0=0.00, y1=0.48

    각 셀 dict 키:
      zone, eup_dong, x0, x1, y0, y1, width_pct, color_value, labels (4줄 list)
    """
    cells = load_treemap_eup_cells()
    payload: list[dict] = []

    # v2 행 좌표 (한라산 캡션 영역 축소)
    row_y_v2: dict[str, tuple[float, float]] = {
        "제주시":   (0.52, 1.00),
        "서귀포시": (0.00, 0.48),
    }

    for zone in TREEMAP_ZONE_ORDER:
        y0, y1 = row_y_v2[zone]
        order = TREEMAP_EUP_ORDER[zone]
        zone_cells = cells[cells["zone"] == zone].copy().sort_values("cell_order")
        total_w = float(zone_cells["width_pct"].sum())
        if total_w <= 0:
            continue
        x_cur = 0.0
        for eup_name in order:
            row_match = zone_cells[zone_cells["eup_dong"] == eup_name]
            if row_match.empty:
                continue
            row = row_match.iloc[0]
            w_norm = float(row["width_pct"]) / total_w
            x0 = x_cur
            x1 = x_cur + w_norm

            vol = (
                float(annual_volume.loc[eup_name])
                if (annual_volume is not None and eup_name in annual_volume.index)
                else float("nan")
            )

            l1 = str(row["label_line1"])
            l2 = str(row["label_line2"])
            l3 = _format_volume_label(vol)
            l4 = str(row["label_line4"])

            payload.append({
                "zone": zone,
                "eup_dong": eup_name,
                "x0": x0,
                "x1": x1,
                "y0": y0,
                "y1": y1,
                "width_pct": float(row["width_pct"]),
                "color_value": float(vol) if pd.notna(vol) else None,
                "labels": [l1, l2, l3, l4],
            })
            x_cur = x1
    return payload


def compute_ri_annual_volume(merged: pd.DataFrame) -> pd.Series:
    """리(법정리)별 연간 이용량 합계 (m³). index=well_ri 문자열."""
    if merged is None or merged.empty or "well_ri" not in merged.columns:
        return pd.Series(dtype=float, name="volume_m3")
    work = merged.copy()
    ri_clean = (
        work["well_ri"].astype(str).str.strip()
            .replace({"nan": "", "None": "", "NaN": "", "<NA>": ""})
    )
    work = work.assign(_ri_norm=ri_clean)
    work = work[work["_ri_norm"] != ""]
    if work.empty:
        return pd.Series(dtype=float, name="volume_m3")
    return work.groupby("_ri_norm")["volume_m3"].sum().astype(float)


def build_ri_treemap_payload_v2(
    parent_payload: list[dict],
    ri_volume: pd.Series,
) -> list[dict]:
    """리 단위 v2 트리맵 — 색상 = 리별 연간 이용량 합계, 셀 = 부모 슬롯 안에서 squarify."""
    eup_lookup = {p["eup_dong"]: p for p in parent_payload}
    ri_cells = load_treemap_ri_cells()

    try:
        import squarify  # type: ignore
        has_squarify = True
    except ImportError:
        has_squarify = False

    out: list[dict] = []
    for parent_eup, sub in ri_cells.groupby("parent_eup"):
        slot = eup_lookup.get(parent_eup)
        if slot is None:
            continue
        sx0, sx1 = slot["x0"], slot["x1"]
        sy0, sy1 = slot["y0"], slot["y1"]
        slot_w = sx1 - sx0
        slot_h = sy1 - sy0
        sub_sorted = (
            sub.sort_values("width_pct_in_slot", ascending=False).reset_index(drop=True)
        )
        sizes = sub_sorted["width_pct_in_slot"].astype(float).tolist()

        if has_squarify and sizes and sum(sizes) > 0:
            normed = squarify.normalize_sizes(sizes, slot_w, slot_h)
            rects = squarify.squarify(normed, sx0, sy0, slot_w, slot_h)
            for ri_row, rect in zip(sub_sorted.itertuples(index=False), rects):
                ri_name = str(ri_row.ri_name)
                vol_v = (
                    float(ri_volume.loc[ri_name])
                    if (ri_volume is not None and ri_name in ri_volume.index)
                    else float("nan")
                )
                l1 = str(ri_row.label_line1)
                l2_orig = str(ri_row.label_line2)
                l3 = _format_volume_label(vol_v)
                out.append({
                    "zone": ri_row.zone,
                    "parent_eup": parent_eup,
                    "ri_name": ri_name,
                    "x0": float(rect["x"]),
                    "y0": float(rect["y"]),
                    "x1": float(rect["x"] + rect["dx"]),
                    "y1": float(rect["y"] + rect["dy"]),
                    "color_value": float(vol_v) if pd.notna(vol_v) else None,
                    "width_pct_in_slot": float(ri_row.width_pct_in_slot),
                    "labels": [l1, l2_orig, l3],
                })
        else:
            total = sum(sizes) if sum(sizes) > 0 else 1.0
            x_cur = sx0
            for ri_row in sub_sorted.itertuples(index=False):
                w = (float(ri_row.width_pct_in_slot) / total) * slot_w
                x_next = x_cur + w
                ri_name = str(ri_row.ri_name)
                vol_v = (
                    float(ri_volume.loc[ri_name])
                    if (ri_volume is not None and ri_name in ri_volume.index)
                    else float("nan")
                )
                l1 = str(ri_row.label_line1)
                l2_orig = str(ri_row.label_line2)
                l3 = _format_volume_label(vol_v)
                out.append({
                    "zone": ri_row.zone,
                    "parent_eup": parent_eup,
                    "ri_name": ri_name,
                    "x0": float(x_cur),
                    "y0": float(sy0),
                    "x1": float(x_next),
                    "y1": float(sy1),
                    "color_value": float(vol_v) if pd.notna(vol_v) else None,
                    "width_pct_in_slot": float(ri_row.width_pct_in_slot),
                    "labels": [l1, l2_orig, l3],
                })
                x_cur = x_next
    return out


@st.cache_data(ttl=3600, max_entries=32)
def build_ri_treemap_payload(
    year_range: tuple[int, int],
    month_range: tuple[int, int] = (1, 12),
) -> list[dict]:
    """리 단위 트리맵 payload 빌드 (171개 리).

    부모 슬롯(읍/면/동) 좌표 = build_eup_treemap_payload 와 동일.
    각 슬롯 내부에서 squarify (가능 시) 또는 단순 가로 분할 폴백.

    각 셀:
      {"zone", "parent_eup", "ri_name",
       "x0","x1","y0","y1": float,
       "color_value": float (부모 동일 값 = 옵션A),
       "width_pct_in_slot": float,
       "labels": [L1(이름), L2(면적 km²)]}
    """
    eup_payload = build_eup_treemap_payload(year_range, month_range)
    eup_lookup = {p["eup_dong"]: p for p in eup_payload}
    ri_cells = load_treemap_ri_cells()

    # squarify 라이브러리 시도
    try:
        import squarify  # type: ignore
        has_squarify = True
    except ImportError:
        has_squarify = False

    out: list[dict] = []
    for parent_eup, sub in ri_cells.groupby("parent_eup"):
        slot = eup_lookup.get(parent_eup)
        if slot is None:
            continue
        sx0, sx1 = slot["x0"], slot["x1"]
        sy0, sy1 = slot["y0"], slot["y1"]
        slot_w = sx1 - sx0
        slot_h = sy1 - sy0
        # 면적 큰 순 정렬 (squarify 기본 요구)
        sub_sorted = sub.sort_values("width_pct_in_slot", ascending=False).reset_index(drop=True)
        sizes = sub_sorted["width_pct_in_slot"].astype(float).tolist()
        # 부모 동일 색상 (옵션A) — 부모 payload 의 color_value 사용
        parent_color = slot["color_value"]

        if has_squarify and len(sizes) > 0 and sum(sizes) > 0:
            # squarify normalize_sizes → squarify 사이즈를 부모 슬롯 영역에 맞게 정규화
            normed = squarify.normalize_sizes(sizes, slot_w, slot_h)
            rects = squarify.squarify(normed, sx0, sy0, slot_w, slot_h)
            for ri_row, rect in zip(sub_sorted.itertuples(index=False), rects):
                out.append({
                    "zone": ri_row.zone,
                    "parent_eup": parent_eup,
                    "ri_name": ri_row.ri_name,
                    "x0": float(rect["x"]),
                    "y0": float(rect["y"]),
                    "x1": float(rect["x"] + rect["dx"]),
                    "y1": float(rect["y"] + rect["dy"]),
                    "color_value": parent_color,
                    "width_pct_in_slot": float(ri_row.width_pct_in_slot),
                    "labels": [str(ri_row.label_line1), str(ri_row.label_line2)],
                })
        else:
            # 폴백: 부모 슬롯 안에서 면적비례 가로 분할 (single row)
            total = sum(sizes) if sum(sizes) > 0 else 1.0
            x_cur = sx0
            for ri_row in sub_sorted.itertuples(index=False):
                w = (float(ri_row.width_pct_in_slot) / total) * slot_w
                x_next = x_cur + w
                out.append({
                    "zone": ri_row.zone,
                    "parent_eup": parent_eup,
                    "ri_name": ri_row.ri_name,
                    "x0": float(x_cur),
                    "y0": float(sy0),
                    "x1": float(x_next),
                    "y1": float(sy1),
                    "color_value": parent_color,
                    "width_pct_in_slot": float(ri_row.width_pct_in_slot),
                    "labels": [str(ri_row.label_line1), str(ri_row.label_line2)],
                })
                x_cur = x_next
    return out
