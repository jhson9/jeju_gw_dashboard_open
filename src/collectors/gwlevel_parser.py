# ==============================================================================
#  제주도 지하수위·강수량 분석 대시보드
#  파일명: src/collectors/gwlevel_parser.py
#  모듈: 지하수위 xls 파일 파서 (S11 센서 추출)
# ------------------------------------------------------------------------------
#  Build: 0.6
#  최종 수정일: 2026-04-22
# ------------------------------------------------------------------------------
#  Changelog:
#  - v0.6 (2026-04-22): 최초 생성.
#                       제주도 지하수정보관리시스템에서 받은 JD*.xls 파일을
#                       일괄 파싱하여 대표 센서(S11)의 월별 수위만 추출.
#                       * 설계 이유: 대시보드는 월 단위 분석이므로 S11만 필요.
#                                   향후 S21~S25 파서 확장 가능한 구조로 설계.
#                       * 원본 파일은 수정하지 않고 Row_Data/ 에 그대로 보존.
#                       * 파싱 결과는 data/GWlevel/by_station/관측소명.csv 로 저장.
# ------------------------------------------------------------------------------
#  【이 파일의 역할】
#  data/Row_Data/ 에 있는 JD*.xls 파일을 모두 읽어
#  대표 센서(S11)의 월별 수위(EL)를 추출합니다.
#
#  【실행 방법】
#      python src/collectors/gwlevel_parser.py
#
#  【입력 형식 (JD*.xls)】
#   - 시트: S11, S21, S22, S23, S24, S25 (보통 6개, 일부만 있을 수도 있음)
#   - 헤더: 관측소명 | 날짜 | 센서 | EL | GL | Pressure | Temp | EC | Barometa | Battery
#   - 날짜: YYYY-MM 형식
#   - 결측치: "-" 로 표기
#
#  【출력 형식 (CSV)】
#   관측소명, 날짜(연월), 센서, EL(수위 m), GL, ... (원본 컬럼 유지)
# ==============================================================================

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[2]))

import pandas as pd
from tqdm import tqdm

import config


# 원본 xls의 "-" 같은 문자 → NaN 처리용
MISSING_TOKENS = ["-", "", "NaN", "nan", None]


# load_all_station_data() 실행 시 다중 컬럼 동시 이상으로 drop 된 행 요약.
# tab3 가 caption 표기에 참조.
#
# 캐시 일관성 메모 (검증팀 B, 2026-05):
#   tab3 의 `_load_station_data_cached(ttl=300)` 가 load_all_station_data() 를
#   감싸기 때문에, cache hit 시에는 이 모듈 전역이 갱신되지 않음. 하지만
#   cache hit = 입력 CSV 동일 = drop 결과 동일 이므로 stale 값이 곧 정답.
#   load_all_station_data() 가 cache miss 또는 watershed_mapper 등 다른
#   비-캐시 호출자에서 실행될 때 갱신되어 자연스럽게 일관성 유지.
_LAST_GWLEVEL_DROPPED: list[dict] = []


def get_last_dropped_summary() -> list[dict]:
    """load_all_station_data() 가 마지막으로 drop 한 행 요약을 반환.
    각 dict: {station, yymmdd, reason}.
    """
    return list(_LAST_GWLEVEL_DROPPED)


# ==============================================================================
#  ■ 1. 단일 파일 파싱
# ==============================================================================
def parse_single_xls(file_path: Path,
                     sensor: str = None) -> tuple[str, pd.DataFrame | None]:
    """
    단일 JD xls 파일을 읽어 지정 센서 시트를 DataFrame으로 반환.

    Parameters
    ----------
    file_path : Path
        JD xls 파일 경로 (예: data/Row_Data/JD하모2.xls)
    sensor : str, optional
        추출할 센서 시트명 (기본: config.GW_REPRESENTATIVE_SENSOR = "S11")

    Returns
    -------
    tuple (status, dataframe)
        status : "SUCCESS" / "NO_SHEET" / "PARSE_ERROR" / "EMPTY"
        dataframe : 성공 시 DataFrame
    """
    if sensor is None:
        sensor = config.GW_REPRESENTATIVE_SENSOR

    try:
        # 시트 목록 확인
        xl = pd.ExcelFile(file_path)

        # 두 가지 xls 포맷 지원:
        #  (구) 센서별 시트 분리: 'S11', 'S21', ... 시트 중 해당 sensor 시트를 읽음
        #  (신) 단일 시트 'Sheet1' 에 모든 센서 행이 섞여 있음 → '센서' 컬럼으로 필터
        if sensor in xl.sheet_names:
            df = pd.read_excel(file_path, sheet_name=sensor)
        elif "Sheet1" in xl.sheet_names:
            df = pd.read_excel(file_path, sheet_name="Sheet1")
            if "센서" in df.columns:
                df = df[df["센서"] == sensor].copy()
            else:
                return "NO_SHEET", None
        else:
            return "NO_SHEET", None

        if df.empty:
            return "EMPTY", None

        # 원본 데이터의 결측치 토큰("-" 등)을 NaN으로 변환
        df = df.replace(MISSING_TOKENS, pd.NA)

        # 날짜를 Period(월) 형식으로 변환
        # "2021-01" 형식 → 2021-01월
        if "날짜" in df.columns:
            # NaN 제거 후 datetime 변환
            df["날짜"] = pd.to_datetime(df["날짜"].astype(str),
                                       format="%Y-%m", errors="coerce")
            # 변환 실패한 행 제거
            df = df.dropna(subset=["날짜"])
            # YYYY-MM 문자열로 통일 (CSV 저장 시 깔끔)
            df["연월"] = df["날짜"].dt.strftime("%Y-%m")

        # EL, GL 등 수치형 컬럼 변환 (NaN 유지)
        numeric_cols = ["EL", "GL", "Pressure", "Temp", "EC", "Barometa", "Battery"]
        for col in numeric_cols:
            if col in df.columns:
                df[col] = pd.to_numeric(df[col], errors="coerce")

        # 관측소명 추출 (파일명으로 백업)
        if "관측소명" not in df.columns or df["관측소명"].isna().all():
            df["관측소명"] = file_path.stem  # 예: "JD하모2"

        # NaN 관측소명은 파일명으로 채움
        df["관측소명"] = df["관측소명"].fillna(file_path.stem)

        return "SUCCESS", df

    except FileNotFoundError:
        return "PARSE_ERROR", None
    except Exception as e:
        return f"PARSE_ERROR: {type(e).__name__}: {e}", None


# ==============================================================================
#  ■ 2. 전체 Row_Data 폴더 파싱
# ==============================================================================
def _collect_month_xls() -> list[Path]:
    """월자료 xls 파일 수집 — ROW_DATA_MONTH_DIR 우선, 없으면 legacy ROW_DATA_DIR.

    JD관측망_정보.xlsx 의 모든 관측소(JD/JH/JI/JM/JP/JQ/JR/JW/PW 등 prefix 무관)
    를 포괄. 임시 파일(`~$*.xls`) 과 정보 파일(`0_*.xlsx`) 은 제외.
    """
    candidates: list[Path] = []
    for src in (config.ROW_DATA_MONTH_DIR, config.ROW_DATA_DIR):
        if not src.exists():
            continue
        for pat in ("*.xls", "*.xlsx"):
            for p in src.glob(pat):
                name = p.name
                if name.startswith("~$") or name.startswith("0_"):
                    continue
                candidates.append(p)
        if candidates:
            break   # ROW_DATA_MONTH_DIR 에 파일이 있으면 거기만 사용
    return sorted(candidates)


def parse_all_row_data(sensor: str = None, verbose: bool = True) -> dict:
    """
    data/Row_Data/Month/ (또는 legacy data/Row_Data/) 에 있는 모든 관측소 xls
    파일을 일괄 파싱. JD/JH/JI/JM/JP/JQ/JR/JW/PW 등 prefix 무관.

    Returns
    -------
    dict : {
        "dataframes"   : {관측소명: DataFrame, ...},
        "failed"       : [(파일명, 실패사유), ...],
        "total_files"  : int,
        "success_count": int,
    }
    """
    if sensor is None:
        sensor = config.GW_REPRESENTATIVE_SENSOR

    xls_files = _collect_month_xls()

    if not xls_files:
        if verbose:
            print(f"⚠️ {config.ROW_DATA_MONTH_DIR} (또는 {config.ROW_DATA_DIR}) "
                  f"에 관측소 xls 파일이 없습니다.")
        return {"dataframes": {}, "failed": [],
                "total_files": 0, "success_count": 0}

    src_dir = xls_files[0].parent
    if verbose:
        print("=" * 70)
        print(f"🌊 지하수위 xls 파일 파싱 시작")
        print(f"   대상 센서: {sensor}")
        print(f"   대상 경로: {src_dir}")
        print(f"   파일 수: {len(xls_files)}개")
        print("=" * 70)

    dataframes = {}
    failed = []

    # 진행바와 함께 파싱
    iterator = tqdm(xls_files, desc="파싱 진행") if verbose else xls_files
    for file_path in iterator:
        status, df = parse_single_xls(file_path, sensor=sensor)

        if status == "SUCCESS" and df is not None and not df.empty:
            station_name = df["관측소명"].iloc[0]
            dataframes[station_name] = df
        else:
            failed.append((file_path.name, status))
            if verbose:
                tqdm.write(f"   ⚠️ {file_path.name} 실패: {status}")

    if verbose:
        print(f"\n✅ 파싱 완료: {len(dataframes)}개 성공 / {len(failed)}개 실패")
        if failed:
            print("\n❌ 실패한 파일 목록:")
            for name, reason in failed:
                print(f"   - {name}: {reason}")

    return {
        "dataframes": dataframes,
        "failed": failed,
        "total_files": len(xls_files),
        "success_count": len(dataframes),
    }


# ==============================================================================
#  ■ 3. 관측소별 CSV 저장
# ==============================================================================
def save_by_station(dataframes: dict, verbose: bool = True) -> list:
    """
    관측소별 DataFrame을 개별 CSV로 저장.

    저장 경로: data/GWlevel/by_station/관측소명.csv

    Returns
    -------
    list : 저장된 CSV 파일 경로 목록
    """
    config.ensure_directories()
    saved = []

    for station, df in dataframes.items():
        # 원본 컬럼 순서 유지, 저장 경로
        out_path = config.GW_STATION_DIR / f"{station}.csv"
        df.to_csv(out_path, index=False, encoding="utf-8-sig")
        saved.append(out_path)

    if verbose:
        print(f"📁 관측소별 CSV 저장: {len(saved)}개 → {config.GW_STATION_DIR}")

    return saved


# ==============================================================================
#  ■ 4. 대시보드에서 사용할 헬퍼
# ==============================================================================
def load_all_station_data() -> pd.DataFrame:
    """
    저장된 관측소별 CSV를 모두 읽어 통합 DataFrame으로 반환.
    대시보드에서 사용.
    """
    if not config.GW_STATION_DIR.exists():
        return pd.DataFrame()

    csv_files = list(config.GW_STATION_DIR.glob("*.csv"))
    if not csv_files:
        return pd.DataFrame()

    all_dfs = []
    for csv_path in csv_files:
        try:
            df = pd.read_csv(csv_path, encoding="utf-8-sig")
            all_dfs.append(df)
        except Exception as e:
            print(f"⚠️ {csv_path.name} 로드 실패: {e}")

    if not all_dfs:
        return pd.DataFrame()

    combined = pd.concat(all_dfs, ignore_index=True)
    if "날짜" in combined.columns:
        combined["날짜"] = pd.to_datetime(combined["날짜"], errors="coerce")

    # 다중 컬럼 동시 이상 = 기기 오동작 → drop. EL 단독 이상은 자연 변동 가능
    # 으로 간주, 임계 카운트 제외 (사용자 정책).
    from src.analysis import anomaly_detection
    combined = anomaly_detection.detect_gwlevel_anomalies(combined)
    combined, dropped = anomaly_detection.drop_gwlevel_anomalies(combined)

    # tab3 caption 에서 표기하도록 요약을 모듈 전역에 보관 (session_state 는
    # streamlit context 가 아니면 접근 불가하므로 모듈 변수 사용. 캐시된
    # combined 와 함께 일관 — load_all_station_data 가 다시 실행되면 갱신).
    global _LAST_GWLEVEL_DROPPED
    _LAST_GWLEVEL_DROPPED = dropped

    return combined


def get_station_list() -> list:
    """저장된 관측소 이름 목록"""
    if not config.GW_STATION_DIR.exists():
        return []
    return sorted([p.stem for p in config.GW_STATION_DIR.glob("*.csv")])


# ==============================================================================
#  ■ 5. 메인 실행
# ==============================================================================
def run_full_pipeline(verbose: bool = True) -> dict:
    """
    전체 파이프라인 실행:
    1) Row_Data/*.xls 일괄 파싱
    2) 관측소별 CSV 저장
    3) 요약 정보 반환
    """
    result = parse_all_row_data(verbose=verbose)

    if result["success_count"] > 0:
        save_by_station(result["dataframes"], verbose=verbose)

        # 간단 통계
        if verbose:
            print("\n" + "=" * 70)
            print("📊 수집 현황 요약")
            print("=" * 70)
            total_rows = sum(len(df) for df in result["dataframes"].values())
            print(f"   관측소 수:    {result['success_count']}개")
            print(f"   총 월별 레코드: {total_rows:,}개")

            # 날짜 범위
            all_dates = []
            for df in result["dataframes"].values():
                if "날짜" in df.columns:
                    all_dates.extend(df["날짜"].dropna().tolist())
            if all_dates:
                print(f"   기간: {min(all_dates).date()} ~ {max(all_dates).date()}")

    return result


if __name__ == "__main__":
    run_full_pipeline()
