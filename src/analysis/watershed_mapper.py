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

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[2]))

import pandas as pd

import config
from src.collectors import gwlevel_parser


# ==============================================================================
#  ■ 1. 관측소 → 수역 매핑 로드
# ==============================================================================
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
def aggregate_by_watershed(gw_df: pd.DataFrame,
                           station_map: dict) -> dict:
    """
    관측소별 지하수위 데이터를 수역별 월별 평균으로 집계.

    Parameters
    ----------
    gw_df : pd.DataFrame
        gwlevel_parser.load_all_station_data() 결과
        (컬럼: 관측소명, 날짜/연월, 센서, EL, ...)
    station_map : dict
        {관측소명: 수역명}

    Returns
    -------
    dict : {수역명: DataFrame(연월, EL_평균, 관측소_수)}
    """
    if gw_df.empty:
        return {}

    df = gw_df.copy()

    # 관측소명 → 수역명 매핑 추가 (매칭 안되면 NaN → 제거됨)
    df["수역"] = df["관측소명"].map(station_map)
    df = df.dropna(subset=["수역", "EL"])

    # 연월 컬럼 우선 사용, 없으면 날짜에서 추출
    if "연월" in df.columns:
        df["연월_str"] = df["연월"]
    elif "날짜" in df.columns:
        df["연월_str"] = pd.to_datetime(df["날짜"]).dt.strftime("%Y-%m")
    else:
        raise ValueError("'연월' 또는 '날짜' 컬럼이 필요합니다.")

    # 수역별·월별 집계: 평균 EL + 관측소 수
    result = {}
    for watershed, grp in df.groupby("수역"):
        monthly = (grp.groupby("연월_str")
                     .agg(EL_평균=("EL", "mean"),
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
def load_watershed_data() -> dict:
    """
    저장된 수역별 CSV 전체를 dict로 반환.
    대시보드에서 사용.
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
