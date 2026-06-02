# ==============================================================================
#  제주도 지하수위·강수량 분석 대시보드
#  파일명: src/analysis/watershed_mapper.py
#  모듈: 관측소 → 수역 매핑 + 수역별 월별 지하수위 집계
# ------------------------------------------------------------------------------
#  Build: 0.6
#  최종 수정일: 2026-04-22
# ------------------------------------------------------------------------------
#  Changelog:
#  - v0.6 (2026-04-22): 최초 생성.
#                       65개 JD 관측소를 14개 수역으로 매핑.
#                       각 수역별 월별 수위(EL) 평균 계산 및 CSV 저장.
#                       * 매핑 근거: 0_JD관측망_정보.xlsx 의 '유역명' 컬럼.
#                                   예) "동제주유역" → "동제주"
#                       * 수역별 집계는 해당 수역 내 관측소들의 EL 평균.
# ------------------------------------------------------------------------------
#  【이 파일의 역할】
#  - 0_JD관측망_정보.xlsx 의 '유역명' 컬럼으로 관측소 ↔ 수역 매핑 생성
#  - 각 수역별로 월별 수위(EL) 평균 계산
#  - data/GWlevel/by_watershed/수역명.csv 로 저장
#
#  【실행 방법】
#      python src/analysis/watershed_mapper.py
#
#  【전제조건】
#   - data/GWlevel/by_station/*.csv 가 이미 존재 (gwlevel_parser.py 실행 후)
#   - 프로젝트 루트에 0_JD관측망_정보.xlsx 존재
# ==============================================================================

import logging
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[2]))

import pandas as pd

import config
from src.collectors import gwlevel_parser

# P5-4 (2026-05-29): 모듈 표준 logger. verbose=True 시 print() 와 병행 가능.
logger = logging.getLogger(__name__)


# CLI 실행 호환: streamlit 가 없을 때 no-op 데코레이터로 폴백.
try:
    import streamlit as _st
    _cache_data = _st.cache_data(ttl=600, show_spinner=False, max_entries=2)
except Exception:
    def _cache_data(fn):
        return fn


# ==============================================================================
#  ■ 1. 관측소 → 수역 매핑 로드
# ==============================================================================
@_cache_data
def load_station_to_watershed_map(verbose: bool = False) -> dict:
    """
    0_JD관측망_정보.xlsx 에서 관측소명 → 수역명 매핑을 추출.

    xlsx의 '유역명'(예: "동제주유역") 에서 "유역" 접미사를 제거하여
    config.py의 WATERSHEDS 이름과 일치시킴.

    Returns
    -------
    dict : {관측소명: 수역명}
        예) {"JD간드락": "동제주", "JD고산1": "한경", ...}

    Raises
    ------
    FileNotFoundError : xlsx 파일이 없을 때
    """
    xlsx_path = config.find_jd_network_file()
    if xlsx_path is None:
        raise FileNotFoundError(
            "0_JD관측망_정보.xlsx 파일을 찾을 수 없습니다.\n"
            "프로젝트 루트 또는 data/Row_Data/ 에 배치하세요."
        )

    df = pd.read_excel(xlsx_path)

    # 필수 컬럼 확인
    if "관측소명" not in df.columns or "유역명" not in df.columns:
        raise ValueError(
            f"0_JD관측망_정보.xlsx 에 '관측소명' 또는 '유역명' 컬럼이 없습니다. "
            f"컬럼 목록: {list(df.columns)}"
        )

    # "유역"/"수역" 접미사 제거 (실제 데이터에 두 표기 혼재 — 예: "조천수역")
    raw = df["유역명"].astype(str).str.strip()
    norm = (
        raw.str.replace("유역", "", regex=False)
           .str.replace("수역", "", regex=False)
           .str.strip()
    )
    df["수역"] = norm

    # config.WATERSHEDS 에 있는 수역만 유효한 것으로 간주
    valid_watersheds = {w["name"] for w in config.WATERSHEDS}

    mapping = {}
    unmatched = []
    missing = []
    for _, row in df.iterrows():
        station = str(row["관측소명"]).strip()
        ws_raw = str(row.get("유역명", "")).strip()
        watershed = str(row["수역"]).strip()

        # 유역 정보 자체가 비어있는 케이스 (NaN/공백) — 향후 보강 예정
        if not ws_raw or ws_raw.lower() in ("nan", "none"):
            missing.append(station)
            continue

        if watershed in valid_watersheds:
            mapping[station] = watershed
        else:
            unmatched.append((station, ws_raw))

    if verbose:
        print(f"📍 관측소 → 수역 매핑 로드 완료: {len(mapping)}개 관측소")
        if missing:
            print(f"ℹ️ 유역명 누락 (JD관측망 정보 보강 필요): {len(missing)}개")
            print(f"   (샘플) {missing[:8]}{'...' if len(missing) > 8 else ''}")
        if unmatched:
            print(f"⚠️ config 와 매칭 안된 관측소: {len(unmatched)}개")
            for s, w in unmatched[:5]:
                print(f"   {s} → '{w}'")

    return mapping


# ==============================================================================
#  ■ 2. 역매핑 (수역 → 관측소 목록)
# ==============================================================================
@_cache_data
def get_watershed_to_stations_map(verbose: bool = False) -> dict:
    """
    수역명 → [관측소 목록] 역매핑.

    Returns
    -------
    dict : {수역명: [관측소1, 관측소2, ...]}
    """
    station_map = load_station_to_watershed_map(verbose=verbose)

    reverse = {}
    for station, watershed in station_map.items():
        reverse.setdefault(watershed, []).append(station)

    # 관측소 이름 정렬
    for watershed in reverse:
        reverse[watershed].sort()

    return reverse


# ==============================================================================
#  ■ 3. 수역별 월별 평균 집계
# ==============================================================================
# 결측 임계 (사용자 정책 2026-05-27)
#   일별 자료에서 (관측소·월) 의 결측이 이 일수 '이상' 이면 그 달의 평균을
#   NaN 으로 처리해 baseline 평균·편차에서 자동 제외 — '다른 유효 자료로
#   자료를 구성' 하라는 사용자 요청과 부합.
MAX_MISSING_DAYS_PER_MONTH: int = 10


def aggregate_by_watershed(gw_df: pd.DataFrame,
                           station_map: dict,
                           *,
                           max_missing_days: int = MAX_MISSING_DAYS_PER_MONTH,
                           ) -> dict:
    """
    관측소별 지하수위 데이터를 수역별 월별 평균으로 집계.

    Parameters
    ----------
    gw_df : pd.DataFrame
        gwlevel_parser / gwlevel_day_parser 결과
        (컬럼: 관측소명, 날짜 또는 연월, EL, ...)
    station_map : dict
        {관측소명: 수역명}
    max_missing_days : int, default 10
        일별 자료가 입력일 때, (관측소·월) 의 결측이 이 일수 '이상' 이면 그
        달 평균을 NaN 처리. 월별 자료가 입력이면 일별 결측 정보가 없으므로
        룰은 적용되지 않는다.

    Returns
    -------
    dict : {수역명: DataFrame(연월, EL_평균, 관측소_수)}
    """
    if gw_df is None or gw_df.empty:
        return {}

    import calendar as _cal

    df = gw_df.copy()
    df["수역"] = df["관측소명"].map(station_map)
    df = df.dropna(subset=["수역"])

    # 자료 종류 판별 + 연월 컬럼 통일
    has_day = "날짜" in df.columns and "연월" not in df.columns
    if has_day:
        df["연월_str"] = pd.to_datetime(df["날짜"], errors="coerce") \
                            .dt.strftime("%Y-%m")
        df = df.dropna(subset=["연월_str"])
    elif "연월" in df.columns:
        df["연월_str"] = df["연월"].astype(str)
    elif "날짜" in df.columns:
        df["연월_str"] = pd.to_datetime(df["날짜"]).dt.strftime("%Y-%m")
    else:
        raise ValueError("'연월' 또는 '날짜' 컬럼이 필요합니다.")

    # (관측소·월) per_station 산출
    if has_day:
        # 일별 자료 — 10일↑ 결측 (관측소·월) 은 NaN 처리 (사용자 정책 2026-05-27)
        agg = (df.groupby(["관측소명", "수역", "연월_str"])["EL"]
                 .agg(EL_평균="mean", _valid="count")
                 .reset_index())
        agg["_dim"] = agg["연월_str"].apply(
            lambda ym: _cal.monthrange(int(ym.split("-")[0]),
                                        int(ym.split("-")[1]))[1]
        )
        too_few = (agg["_dim"] - agg["_valid"]) >= max_missing_days
        agg.loc[too_few, "EL_평균"] = float("nan")
        per_station = (agg[["관측소명", "수역", "연월_str", "EL_평균"]]
                          .dropna(subset=["EL_평균"]))
    else:
        # 월별 자료 — 일별 결측 정보 없음. 그대로 (관측소·월) 평균 사용.
        df = df.dropna(subset=["EL"])
        per_station = (df.groupby(["관측소명", "수역", "연월_str"])["EL"]
                          .mean()
                          .reset_index()
                          .rename(columns={"EL": "EL_평균"}))

    # L2 2단계 평균 — 수역 × 월: 관측소 간 평균 (NaN/제외된 관측소-월은
    # 자동으로 분모에서 차감 → 결측 불균형의 가중 편향 동시 회피).
    result = {}
    for watershed, grp in per_station.groupby("수역"):
        monthly = (grp.groupby("연월_str")
                     .agg(EL_평균=("EL_평균", "mean"),
                          관측소_수=("관측소명", "nunique"))
                     .reset_index()
                     .rename(columns={"연월_str": "연월"}))
        monthly = monthly.sort_values("연월").reset_index(drop=True)
        monthly["EL_평균"] = monthly["EL_평균"].round(3)
        result[watershed] = monthly

    return result


# ==============================================================================
#  ■ 4. 수역별 CSV 저장
# ==============================================================================
def save_watershed_csvs(watershed_data: dict, verbose: bool = True) -> list:
    """
    수역별 DataFrame을 개별 CSV로 저장.

    Returns
    -------
    list : 저장된 CSV 파일 경로 목록
    """
    config.ensure_directories()
    saved = []
    for watershed, df in watershed_data.items():
        out_path = config.GW_WATERSHED_DIR / f"{watershed}.csv"
        df.to_csv(out_path, index=False, encoding="utf-8-sig")
        saved.append(out_path)

    if verbose:
        print(f"📁 수역별 CSV 저장: {len(saved)}개 → {config.GW_WATERSHED_DIR}")

    return saved


# ==============================================================================
#  ■ 5. 대시보드용 헬퍼
# ==============================================================================
# M2 fix 2026-05-30: 본체 캐싱 추가. 이전엔 app.py 의 wrapper(ttl=300) 만 캐싱해
#   매 5분 30개 유역 CSV glob+read 비용 발생. 본체 ttl=600 + max_entries=2 로 늘려
#   동일 인스턴스 반환 (app.py 의 wrapper hash_funcs={DataFrame: id} 가 ID 안정성에
#   의존하므로 본체 캐싱이 더 효율적). CLI 환경 폴백은 위 _cache_data 정의로 보장.
@_cache_data
def load_watershed_data() -> dict:
    """
    저장된 수역별 CSV 전체를 dict로 반환.
    대시보드에서 사용. M2 fix 2026-05-30: 본체 캐싱으로 30 CSV glob+read 1회화.
    """
    if not config.GW_WATERSHED_DIR.exists():
        return {}

    result = {}
    for csv_path in config.GW_WATERSHED_DIR.glob("*.csv"):
        try:
            df = pd.read_csv(csv_path, encoding="utf-8-sig")
            result[csv_path.stem] = df
        except Exception as e:
            print(f"⚠️ {csv_path.name} 로드 실패: {e}")

    return result


def compute_gwlevel_diff_dict(
    ws_data_all: dict,
    periods: dict,
    n_years: int,
) -> dict:
    """유역 × 기간(M-2/M-1/M) 별 (실측·평균·편차) dict 산출 — 단일 진실 원천.

    이전엔 app.py 와 tab01_overview.py 가 같은 계산을 두 번 했음 (분석팀 권고
    2026-05-08 — 로직1 보고). 이 함수가 한 번 계산해 dict 로 반환하면 두 곳
    이 같은 결과를 공유.

    Parameters
    ----------
    ws_data_all : dict[str, pd.DataFrame]
        load_watershed_data() 결과. 유역명 → DataFrame (연월·EL_평균).
    periods : dict
        period_calculator.compute_periods() 결과. 'M-2', 'M-1', 'M' 키.
    n_years : int
        baseline 평균 산출에 쓸 직전 N년.

    Returns
    -------
    dict[str, dict[str, dict | None]]
        ``{ws_name: {pk: {"실측": float, "평균": float, "편차": float}}}``
        값이 부족하면 ``None``. ``round(2)`` 적용.
    """
    out: dict = {}
    if not ws_data_all:
        return out

    for ws_name, df_ws in ws_data_all.items():
        if df_ws is None or df_ws.empty:
            continue
        per_period: dict = {}
        for pk in ("M-2", "M-1", "M"):
            if pk not in periods:
                continue
            p = periods[pk]
            ym_str = f"{p['year']}-{p['month']:02d}"
            bl_years = list(range(p["year"] - n_years, p["year"]))

            actual_row = df_ws[df_ws["연월"] == ym_str]
            if actual_row.empty:
                per_period[pk] = None
                continue
            actual = float(actual_row["EL_평균"].iloc[0])

            base_vals: list = []
            for y in bl_years:
                ym_b = f"{y}-{p['month']:02d}"
                base_row = df_ws[df_ws["연월"] == ym_b]
                if not base_row.empty:
                    v = float(base_row["EL_평균"].iloc[0])
                    if pd.notna(v):
                        base_vals.append(v)

            if not base_vals:
                per_period[pk] = None
                continue
            avg = sum(base_vals) / len(base_vals)
            per_period[pk] = {
                "실측": round(actual, 2),
                "평균": round(avg, 2),
                "편차": round(actual - avg, 2),
            }
        if any(v is not None for v in per_period.values()):
            out[ws_name] = per_period
    return out


# ==============================================================================
#  ■ 6. 메인 실행
# ==============================================================================
def run_watershed_pipeline(verbose: bool = True) -> dict:
    """
    전체 파이프라인:
    1) 관측소 → 수역 매핑 로드
    2) 관측소별 지하수위 데이터 로드
    3) 수역별 월별 평균 집계
    4) 수역별 CSV 저장
    """
    if verbose:
        print("=" * 70)
        print("🗺️ 수역별 지하수위 집계 시작")
        print("=" * 70)

    # 1) 매핑
    station_map = load_station_to_watershed_map(verbose=verbose)

    # 2) 관측소별 데이터 로드 (gwlevel_parser.py의 결과)
    gw_df = gwlevel_parser.load_all_station_data()
    if gw_df.empty:
        print("❌ 관측소별 데이터가 없습니다. 먼저 gwlevel_parser.py 를 실행하세요.")
        return {}

    if verbose:
        print(f"📂 {gw_df['관측소명'].nunique()}개 관측소의 "
              f"총 {len(gw_df):,}개 레코드 로드")

    # 3) 수역별 집계
    watershed_data = aggregate_by_watershed(gw_df, station_map)

    if verbose and watershed_data:
        print(f"\n📊 수역별 집계 결과:")
        for ws in sorted(watershed_data.keys()):
            df = watershed_data[ws]
            station_count = station_map and \
                sum(1 for s, w in station_map.items() if w == ws)
            if not df.empty:
                first = df["연월"].min()
                last = df["연월"].max()
                print(f"   - {ws:6s}: 관측소 {station_count}개 / "
                      f"{first}~{last} ({len(df)}개월)")

    # 4) 저장
    save_watershed_csvs(watershed_data, verbose=verbose)

    if verbose:
        print("\n✅ 수역별 집계 완료")

    return watershed_data


if __name__ == "__main__":
    run_watershed_pipeline()
