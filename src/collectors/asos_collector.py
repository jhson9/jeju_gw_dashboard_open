# ==============================================================================
#  제주도 지하수위·강수량 분석 대시보드
#  파일명: src/collectors/asos_collector.py
#  모듈: 기상청 ASOS 일자료 수집기
# ------------------------------------------------------------------------------
#  Build: 0.5
#  최종 수정일: 2026-04-22
# ------------------------------------------------------------------------------
#  Changelog:
#  - v0.2 (2026-04-21): 최초 생성.
#                       기존 Aws_day.py(v3.0)를 모듈화하여 이식.
#  - v0.3 (2026-04-21): ASOS 수집 안정화.
#                       HTTPS 전환, 상세 에러 로그, 즉시 중단 로직 추가.
#  - v0.4 (2026-04-21): User-Agent 헤더 추가 (403 Forbidden 해결).
#  - v0.5 (2026-04-22): Smart 종료일 로직 추가.
#                       * 문제: 현재 연도는 endDt=YYYY1231이 미래라서
#                               API가 요청 전체를 거부 (code 99).
#                       * 해결: 기준일에 따른 동적 종료일 계산.
#                               - 오늘 1~15일 → 전월 말일
#                               - 오늘 16~말일 → 당월 15일
#                               (기존 HTML 대시보드 M-2·M-1·M 로직과 일치)
#                       * CLI 옵션 추가:
#                         --mode smart  : 기본 (M 기간에 필요한 데이터만)
#                         --mode latest : 어제까지 (최신)
#                         --through YYYY: 특정 연도까지만 수집
#                       * 증분 수집 로직은 그대로 유지.
# ------------------------------------------------------------------------------
#  【이 파일의 역할】
#  기상청 공공데이터포털(apis.data.go.kr)의 ASOS 일자료 API를 호출하여
#  제주도 4개 관측소(제주·서귀포·성산·고산)의 일별 기상 데이터를 수집하고
#  CSV 파일로 누적 저장합니다.
#
#  【실행 방법】
#  VS Code 터미널에서 프로젝트 루트로 이동 후:
#      python src/collectors/asos_collector.py
#
#  【수집 항목】
#   - 일강수량(mm)
#   - 평균기온(°C)
#   - 최고기온(°C)
#   - 최저기온(°C)
#   (향후 농업가뭄 분석용 컬럼을 config.py 에서 확장 가능)
#
#  【에러 처리】
#   - 일시 네트워크 오류: 자동 재시도 (최대 5회, 10초 간격)
#   - API 응답 오류: 에러 코드·메시지를 화면에 출력
#   - 전체 실패: 부분 수집 결과도 CSV로 보존
# ==============================================================================

# --- 상위 폴더 경로 추가 (config.py import를 위함) ---
# 이 파일은 src/collectors/ 안에 있어서, 프로젝트 루트의 config.py를
# 바로 import 할 수 없습니다. 그래서 Python에게 프로젝트 루트를 알려줍니다.
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[2]))

# --- 표준 라이브러리 ---
import logging
import time
from datetime import date, timedelta
from json import JSONDecodeError

# 🆕 (2026-06-06 Stage 2 P1) 표준 로거 — print() 대신 logger.exception() 사용
logger = logging.getLogger(__name__)

# --- 외부 라이브러리 ---
import requests
import pandas as pd
from tqdm import tqdm

# --- 프로젝트 설정 ---
import config


# CLI 실행 호환: streamlit 가 없을 때 no-op 로 폴백. 같은 객체 재사용 보장
# (effective_rainfall.aggregate_* 의 hash_funcs={pd.DataFrame: id} 와 결합해
# 불필요 재집계 차단).
try:
    import streamlit as _st
    _asos_cache = _st.cache_data(ttl=600, show_spinner=False, max_entries=2)
except Exception:
    def _asos_cache(fn):
        return fn


# ==============================================================================
#  ■ 수집 항목 정의
# ==============================================================================
# 기상청 API가 반환하는 필드명 → 우리가 저장할 컬럼명
# 필요 시 이 딕셔너리에 항목을 추가하면 자동으로 수집됩니다.
#   (향후 농업가뭄 분석용: sumSsHr(일조시간), avgRhm(평균습도), avgWs(평균풍속) 등)
API_FIELD_MAP = {
    "stnNm":  "지점명",
    "tm":     "일시",
    "sumRn":  "일강수량(mm)",
    "avgTa":  "평균기온(°C)",
    "minTa":  "최저기온(°C)",
    "maxTa":  "최고기온(°C)",
}

# 숫자형으로 변환할 컬럼들 (문자열 → float)
NUMERIC_COLS = ["일강수량(mm)", "평균기온(°C)", "최저기온(°C)", "최고기온(°C)"]


# ==============================================================================
#  ■ 1. API 호출 함수 (1년치 수집)
# ==============================================================================
def fetch_daily_weather_for_year(year: int, station_id: int,
                                  end_dt_override: str = None
                                  ) -> tuple[str, pd.DataFrame | None]:
    """
    지정된 '년'과 관측소의 1년치 '일별' 날씨 데이터를 API로부터 가져옵니다.

    Parameters
    ----------
    year : int
        조회할 연도 (예: 2020)
    station_id : int
        기상청 관측소 지점코드 (예: 184=제주)
    end_dt_override : str, optional
        🆕 Build 0.5: 종료일 오버라이드 (YYYYMMDD 형식).
        현재 연도 수집 시 12-31이 미래라서 API가 거부하는 문제 해결.
        주어지면 이 날짜까지만 수집, 없으면 YYYY-12-31 사용.

    Returns
    -------
    tuple (status, dataframe)
        status: "SUCCESS" / "RETRY_*" / "API_ERROR[xx]" / 에러 메시지
        dataframe: 성공 시 DataFrame, 실패 시 None
    """
    # 🆕 Build 0.5: end_dt 결정
    end_dt = end_dt_override if end_dt_override else f"{year}1231"

    # API 요청 파라미터 구성
    params = {
        "serviceKey": config.KMA_API_KEY,
        "pageNo": "1",
        "numOfRows": "366",        # 1년치(윤년 포함) 최대 요청
        "dataType": "JSON",
        "dataCd": "ASOS",
        "dateCd": "DAY",
        "startDt": f"{year}0101",  # 해당 연도 1월 1일
        "endDt": end_dt,           # 🆕 Build 0.5: 동적 종료일
        "stnIds": str(station_id),
    }

    try:
        # HTTP GET 요청
        # 🆕 Build 0.4: headers 추가 (403 Forbidden 방지)
        response = requests.get(
            config.KMA_API_URL,
            params=params,
            headers=config.HTTP_HEADERS,
            timeout=config.KMA_API_TIMEOUT
        )

        # 🆕 Build 0.3: HTTP 상태코드가 4xx/5xx면 재시도 없이 즉시 실패
        if response.status_code in (400, 401, 403, 404):
            return f"HTTP_{response.status_code}: 재시도 무의미 (URL/키/파라미터 오류)", None
        response.raise_for_status()

        # 🆕 Build 0.3: 응답이 비어있으면 구체 메시지
        body = response.text.strip()
        if not body:
            return "EMPTY_RESPONSE: 응답 본문 비어있음", None

        # JSON 파싱 시도
        try:
            json_data = response.json()
        except JSONDecodeError:
            # 🆕 Build 0.3: JSON이 아니면 XML 에러 응답에서 코드 추출
            if "<?xml" in body[:100] or "OpenAPI_ServiceResponse" in body[:200]:
                import re
                code_match = re.search(r"<returnReasonCode>([^<]+)</returnReasonCode>", body)
                msg_match = re.search(r"<returnAuthMsg>([^<]+)</returnAuthMsg>", body)
                code = code_match.group(1).strip() if code_match else "XML"
                msg = msg_match.group(1).strip() if msg_match else body[:100]
                # 키 문제는 재시도해도 소용없음
                if code in ("30", "31", "20", "22"):
                    return f"API_KEY_ERROR[{code}]: {msg} (진단: diagnose_api.py 실행)", None
                return f"API_XML_ERROR[{code}]: {msg}", None
            # HTML이나 그 외
            return f"NOT_JSON: {body[:150]}", None

        # API가 반환한 결과 코드 확인
        header = json_data.get("response", {}).get("header", {})
        result_code = header.get("resultCode")
        result_msg = header.get("resultMsg", "")

        if result_code != "00":
            # 🆕 Build 0.3: 키 문제는 재시도 없이 즉시 실패
            if result_code in ("30", "31", "20", "22"):
                return f"API_KEY_ERROR[{result_code}]: {result_msg}", None
            return f"API_ERROR[{result_code}]: {result_msg}", None

        # 실제 데이터 추출
        items = (json_data.get("response", {})
                          .get("body", {})
                          .get("items", {})
                          .get("item", []))
        if not items:
            return "SUCCESS", pd.DataFrame()

        # DataFrame으로 변환
        df = pd.DataFrame(items)

        # 없는 컬럼은 None으로 채워서 안전하게 처리
        for col in API_FIELD_MAP.keys():
            if col not in df.columns:
                df[col] = None

        # 필요한 컬럼만 선택하고 한글 컬럼명으로 변환
        df = df[list(API_FIELD_MAP.keys())].copy()
        df.columns = list(API_FIELD_MAP.values())

        return "SUCCESS", df

    except requests.exceptions.Timeout:
        return "RETRY_TIMEOUT: 응답 시간 초과", None
    except requests.exceptions.ConnectionError as e:
        return f"RETRY_CONN: 연결 실패 ({type(e).__name__})", None
    except requests.exceptions.RequestException as e:
        return f"RETRY_REQ: {type(e).__name__}", None
    except Exception as e:
        # 그 외 예외는 재시도하지 않고 종료
        return f"UNKNOWN_ERROR: {e}", None


# ==============================================================================
#  ■ 2. 재시도 래퍼
# ==============================================================================
def fetch_with_retry(year: int, station_id: int, station_name: str,
                     end_dt_override: str = None,
                     pbar: tqdm = None) -> tuple[pd.DataFrame | None, bool]:
    """
    fetch_daily_weather_for_year()를 감싸서 자동 재시도 로직을 추가합니다.
    (네트워크 불안정 대응)

    🆕 Build 0.3: fatal_error 플래그를 반환하여, 키 문제 등 치명적 오류 시
                  전체 수집을 즉시 중단할 수 있도록 함.
    🆕 Build 0.5: end_dt_override 파라미터를 fetch 함수로 전달.

    Returns
    -------
    tuple (dataframe, fatal_error)
        dataframe : 성공 시 DataFrame, 실패 시 None
        fatal_error : True이면 전체 수집을 중단해야 함 (키 문제 등)
    """
    for attempt in range(config.KMA_API_MAX_RETRIES):
        status, data = fetch_daily_weather_for_year(
            year, station_id, end_dt_override=end_dt_override
        )

        if status == "SUCCESS":
            return data, False  # data는 DataFrame (빈 것일 수도 있음)

        # 🆕 Build 0.3: 재시도 무의미한 치명적 오류
        if status.startswith("API_KEY_ERROR") or status.startswith("HTTP_"):
            msg = (f"   ❌❌ [{year}년 {station_name}] 치명적 오류 (재시도 불가):\n"
                   f"        {status}\n"
                   f"        👉 python src/collectors/diagnose_api.py 실행 권장")
            if pbar:
                pbar.write(msg)
            else:
                print(msg)
            return None, True  # fatal_error=True → 전체 수집 중단

        # P4-3 (2026-05-29): API_ERROR[03] (No Data) 는 재시도해도 동일 결과.
        # 무의미한 호출/대기 회피. 같은 해 다른 지점은 정상일 수 있어 fatal 은 아님.
        if status.startswith("API_ERROR[03]"):
            msg = f"   ⚪ [{year}년 {station_name}] No Data — 재시도 생략"
            if pbar:
                pbar.write(msg)
            else:
                print(msg)
            return None, False

        # P4-3: API_ERROR[22] (트래픽 초과) 는 즉시 fatal — 지수 백오프로도 회복 불가.
        # 일일 호출 한도라 다음 날까지 대기 필요.
        if status.startswith("API_ERROR[22]"):
            msg = (f"   ❌❌ [{year}년 {station_name}] API 트래픽 초과 (일일 한도):\n"
                   f"        {status}\n"
                   f"        👉 내일 다시 실행하세요. 전체 수집 중단.")
            if pbar:
                pbar.write(msg)
            else:
                print(msg)
            return None, True

        # 재시도 가능한 오류 — 지수 백오프(5/10/20초)
        if status.startswith("RETRY") or status.startswith("API_ERROR[0"):
            if attempt < config.KMA_API_MAX_RETRIES - 1:
                # P4-3: 고정 5초 → 지수 백오프 (base * 2^attempt)
                base_delay = config.KMA_API_RETRY_DELAY
                actual_delay = base_delay * (2 ** attempt)
                msg = (f"   ⏳ [{year}년 {station_name}] {status}\n"
                       f"        {actual_delay}초 후 재시도... "
                       f"({attempt + 1}/{config.KMA_API_MAX_RETRIES}, 지수 백오프)")
                if pbar:
                    pbar.write(msg)
                else:
                    print(msg)
                time.sleep(actual_delay)
                continue
            else:
                msg = f"   ❌ [{year}년 {station_name}] 최대 재시도 초과: {status}"
                if pbar:
                    pbar.write(msg)
                else:
                    print(msg)
                return None, False

        # 그 외 오류
        msg = f"   ❌ [{year}년 {station_name}] 오류: {status}"
        if pbar:
            pbar.write(msg)
        else:
            print(msg)
        return None, False

    return None, False


# ==============================================================================
#  ■ 3. 🆕 Build 0.5: Smart 종료일 계산
# ==============================================================================
def get_collection_end_date(mode: str = "smart", today: date = None) -> date:
    """
    🆕 Build 0.5: 수집 종료일을 모드에 따라 계산.

    Parameters
    ----------
    mode : str
        "smart"  : M-2·M-1·M 분석에 필요한 데이터만 (기본)
                   - 오늘 1~15일 → 전월 말일
                   - 오늘 16~말일 → 당월 15일
                   (기존 HTML 대시보드 기간 로직과 일치)
        "latest" : 어제까지 (최신 데이터 전부)
        "y2025"  : 2025년 12월 31일까지만 (개발용)
    today : date, optional
        기준일 (테스트용, 기본은 오늘)

    Returns
    -------
    date : 종료일
    """
    if today is None:
        today = date.today()

    if mode == "latest":
        # 어제까지 (기상청 API는 전날 데이터까지만 제공)
        return today - timedelta(days=1)

    elif mode == "y2025":
        # 개발 단계용 고정 종료일
        return date(2025, 12, 31)

    else:  # "smart" (기본)
        if today.day <= 15:
            # 전월 말일
            first_of_this_month = today.replace(day=1)
            return first_of_this_month - timedelta(days=1)
        else:
            # 당월 15일
            return today.replace(day=15)


# ==============================================================================
#  ■ 4. 저장된 CSV 로드 (증분 수집 판단용)
# ==============================================================================
def get_output_csv_path() -> Path:
    """
    누적 저장용 CSV 파일의 경로를 반환합니다.
    파일명: data/ASOS/jeju_asos_daily.csv (연도 범위는 가변적이므로 파일명 고정)
    """
    return config.ASOS_DIR / "jeju_asos_daily.csv"


def load_existing_data() -> pd.DataFrame:
    """
    이미 저장된 CSV 파일을 불러옵니다.
    파일이 없으면 빈 DataFrame 반환.

    🆕 Build 0.5: 기존 CSV의 일강수량 NaN도 자동으로 0.0으로 보정
                  (이전 빌드에서 저장된 CSV도 호환).
    """
    csv_path = get_output_csv_path()
    if not csv_path.exists():
        return pd.DataFrame()

    try:
        df = pd.read_csv(csv_path, encoding="utf-8-sig")
        df["일시"] = pd.to_datetime(df["일시"])
        # 🆕 Build 0.5: 일강수량 NaN → 0.0 (하위 호환)
        if "일강수량(mm)" in df.columns:
            df["일강수량(mm)"] = df["일강수량(mm)"].fillna(0.0)
        return df
    except Exception as e:  # noqa: BLE001
        # 🆕 (2026-06-06 Stage 2 P1) print → logger.exception (traceback 포함)
        logger.exception(
            "기존 ASOS CSV 로드 실패 — 파일을 다시 수집합니다: %s", e
        )
        return pd.DataFrame()


def get_collected_years_by_station(existing_df: pd.DataFrame) -> dict:
    """
    기존 데이터에서 각 관측소별로 이미 수집된 '완전한 연도'를 찾습니다.
    '완전한 연도'의 기준: 해당 연도의 데이터가 360일 이상
    (윤년 366일, 평년 365일이지만 일부 누락될 수 있으므로 360일로 여유)

    단, 현재 연도는 아직 진행 중이므로 항상 재수집합니다.

    Returns
    -------
    dict : { 지점명: set(이미_수집된_연도들) }
    """
    if existing_df.empty:
        return {}

    current_year = date.today().year
    result = {}

    # 지점별·연도별 데이터 개수 집계
    existing_df = existing_df.copy()
    existing_df["연도"] = existing_df["일시"].dt.year
    grouped = existing_df.groupby(["지점명", "연도"]).size()

    for (station, year), count in grouped.items():
        # 현재 연도는 진행 중이므로 재수집 대상
        if year == current_year:
            continue
        # 평년 365 / 윤년 366 일을 모두 채운 해만 '완전'으로 간주 (V6 수정
        # 2026-05-27). 이전 '360일 이상' 기준은 360~364일짜리 해를 영구히
        # 미완성으로 남겨, 인터넷에 연결돼도 빠진 날을 채우지 못했음. 이제
        # 완전치 않은 과거 연도는 재수집 대상에 포함되어, 온라인일 때 누락분이
        # 보강된다(오프라인이면 수집 시도가 실패해도 기존 자료는 유지).
        import calendar as _cal
        expected_days = 366 if _cal.isleap(year) else 365
        if count >= expected_days:
            result.setdefault(station, set()).add(year)

    return result


# ==============================================================================
#  ■ 5. 메인 수집 함수
# ==============================================================================
def collect_asos_data(start_year: int = None, end_year: int = None,
                      force_refresh: bool = False,
                      mode: str = "smart") -> pd.DataFrame:
    """
    전체 수집 로직을 수행합니다.

    Parameters
    ----------
    start_year : int, optional
        시작 연도 (기본값: config.ASOS_START_DATE의 연도)
    end_year : int, optional
        종료 연도 (기본값: 오늘 연도, mode에 따라 종료일 자동 조정)
    force_refresh : bool
        True이면 증분 수집을 무시하고 전체를 다시 수집
    mode : str
        🆕 Build 0.5: 수집 종료일 계산 모드
        - "smart"  : M-2·M-1·M 분석에 필요한 데이터만 (기본)
        - "latest" : 어제까지
        - "y2025"  : 2025년 12월 31일까지만

    Returns
    -------
    pd.DataFrame
        전체 누적 데이터
    """
    # 기본값 처리
    if start_year is None:
        start_year = int(config.ASOS_START_DATE[:4])

    # 🆕 Build 0.5: 종료일과 종료 연도 계산
    collection_end_date = get_collection_end_date(mode)
    if end_year is None:
        end_year = collection_end_date.year
    else:
        # 사용자가 end_year를 명시하면 그 연도 12-31까지
        collection_end_date = date(end_year, 12, 31)

    # API 키 체크
    if not config.KMA_API_KEY:
        print("❌ 기상청 API 키가 설정되지 않았습니다.")
        print("   .env 파일을 확인하세요. (KMA_API_KEY=...)")
        return pd.DataFrame()

    # 디렉토리 보장
    config.ensure_directories()

    print("=" * 70)
    print(f"🌤️  기상청 ASOS 일자료 수집 시작")
    print(f"   모드:      {mode}")
    print(f"   기간:      {start_year}년 ~ {end_year}년")
    print(f"   종료일:    {collection_end_date} (모드에 따라 자동 결정)")
    print(f"   지점:      {[s['name'] for s in config.STATIONS_ASOS]}")
    print(f"   저장 위치: {get_output_csv_path()}")
    print("=" * 70)

    # --- 증분 수집 판단 ---
    # 기존 CSV 파일을 로드하고, 각 지점별로 '이미 완전히 수집된 연도'를 파악
    existing_df = pd.DataFrame() if force_refresh else load_existing_data()
    collected = {} if force_refresh else get_collected_years_by_station(existing_df)

    if not existing_df.empty:
        print(f"📂 기존 CSV에서 {len(existing_df):,}개 데이터 로드됨")
        if collected:
            for station, years in sorted(collected.items()):
                sorted_years = sorted(years)
                if sorted_years:
                    print(f"   - {station}: {min(sorted_years)}~{max(sorted_years)}년 "
                          f"({len(sorted_years)}개년 스킵 예정)")
        print()

    # --- 수집 작업 계획 ---
    # 수집해야 할 (연도, 지점) 조합을 미리 계산
    tasks = []
    for year in range(start_year, end_year + 1):
        for station in config.STATIONS_ASOS:
            # 이미 완전히 수집된 연도는 건너뛰기
            if not force_refresh and year in collected.get(station["name"], set()):
                continue
            tasks.append((year, station))

    if not tasks:
        print("✅ 모든 데이터가 이미 수집되어 있습니다. (증분 수집 완료)")
        return existing_df

    print(f"📋 수집 작업: 총 {len(tasks)}건 (연도 × 지점)")
    print()

    # --- 실제 수집 ---
    # tqdm 진행바와 함께 API를 순차 호출
    new_data = []
    fatal_occurred = False  # 🆕 Build 0.3: 치명적 오류 플래그
    with tqdm(total=len(tasks), desc="수집 진행") as pbar:
        for year, station in tasks:
            pbar.set_description(f"수집: {year}년 ({station['name']})")

            # 🆕 Build 0.5: 연도별 end_dt 결정
            #   과거 연도: YYYY-12-31 (그대로)
            #   현재/종료 연도: collection_end_date 사용 (미래 날짜 회피)
            if year < collection_end_date.year:
                year_end_dt = f"{year}1231"
            elif year == collection_end_date.year:
                year_end_dt = collection_end_date.strftime("%Y%m%d")
            else:
                # 미래 연도 (정상적으론 tasks에 포함되지 않음)
                pbar.update(1)
                continue

            df, fatal = fetch_with_retry(
                year, station["id"], station["name"],
                end_dt_override=year_end_dt, pbar=pbar
            )

            # 🆕 Build 0.3: 치명적 오류 발생 시 즉시 전체 중단
            if fatal:
                pbar.write("")
                pbar.write("=" * 70)
                pbar.write("  🛑 치명적 오류로 전체 수집 중단")
                pbar.write("  👉 python src/collectors/diagnose_api.py 를 실행하여 원인 확인 필요")
                pbar.write("=" * 70)
                fatal_occurred = True
                break

            if df is not None and not df.empty:
                # 숫자형 변환 (비어있으면 NaN, 그 외는 float)
                for col in NUMERIC_COLS:
                    if col in df.columns:
                        df[col] = pd.to_numeric(df[col], errors="coerce")

                # 🆕 Build 0.5: 일강수량 NaN → 0.0 (비 안 온 날)
                #   기상청 API는 비 안 온 날 sumRn을 빈 문자열로 반환하여
                #   pd.to_numeric 후 NaN이 됨. 강수량은 0이 맞으므로 0으로 보정.
                #   ※ 기온 계열은 NaN 유지 (0°C와 '측정 불가'는 전혀 다름)
                if "일강수량(mm)" in df.columns:
                    df["일강수량(mm)"] = df["일강수량(mm)"].fillna(0.0)

                new_data.append(df)

            pbar.update(1)
            time.sleep(1)   # API 서버 부하 방지 (각 요청 간 1초 대기)

    if fatal_occurred:
        if new_data:
            # 일부라도 받은 데이터는 저장 시도
            print("\n⚠️ 일부 수집된 데이터만 저장합니다.")
        else:
            print("\n❌ 수집된 데이터 없음. 기존 CSV만 유지됨.")
            return existing_df

    # --- 기존 데이터와 병합 ---
    if new_data:
        new_df = pd.concat(new_data, ignore_index=True)
        new_df["일시"] = pd.to_datetime(new_df["일시"])
        print(f"\n📥 신규 수집: {len(new_df):,}개 레코드")

        if not existing_df.empty:
            # 기존 데이터와 병합 후 중복 제거 (같은 지점·날짜가 있으면 신규로 덮어쓰기)
            combined = pd.concat([existing_df, new_df], ignore_index=True)
            combined = combined.drop_duplicates(
                subset=["지점명", "일시"], keep="last"
            )
        else:
            combined = new_df
    else:
        combined = existing_df
        print("\n⚠️ 신규 수집된 데이터가 없습니다.")

    # --- 정렬 및 저장 ---
    if not combined.empty:
        combined = combined.sort_values(by=["지점명", "일시"]).reset_index(drop=True)
        csv_path = get_output_csv_path()
        # Atomic write — Windows 에서 사용자가 Excel 로 CSV 열어둔 채 수집 실행
        # 시 PermissionError 회피. tmp 에 쓴 뒤 os.replace 로 원자적 rename.
        import os
        tmp_path = csv_path.with_suffix(csv_path.suffix + ".tmp")
        combined.to_csv(tmp_path, index=False, encoding="utf-8-sig")
        os.replace(tmp_path, csv_path)
        print(f"\n✅ 저장 완료: {csv_path}")
        print(f"   총 레코드: {len(combined):,}개")
        print(f"   기간: {combined['일시'].min().date()} ~ {combined['일시'].max().date()}")
        print(f"   지점: {sorted(combined['지점명'].unique().tolist())}")

    return combined


# ==============================================================================
#  ■ 6. 대시보드에서 사용할 헬퍼 함수
# ==============================================================================
@_asos_cache
def load_asos_data() -> pd.DataFrame:
    """
    대시보드에서 저장된 ASOS CSV를 읽어올 때 사용합니다.

    streamlit 환경에서는 자동 캐시(ttl=300, max_entries=2). 모든 호출처가
    같은 객체를 받으므로 하위 hash_funcs={DataFrame: id} 캐시가 통일됨.
    """
    csv_path = get_output_csv_path()
    if not csv_path.exists():
        return pd.DataFrame()

    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    df["일시"] = pd.to_datetime(df["일시"], errors="coerce")
    df = df.dropna(subset=["일시"])
    return df


# ==============================================================================
#  ■ 직접 실행용 진입점
# ==============================================================================
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="기상청 ASOS 일자료 수집기 (제주도 4개 지점)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  python src/collectors/asos_collector.py                  # Smart 모드 (기본)
  python src/collectors/asos_collector.py --mode latest    # 어제까지 수집
  python src/collectors/asos_collector.py --through 2025   # 2025년까지만
  python src/collectors/asos_collector.py --force          # 전체 재수집

Smart 모드 동작:
  오늘이 매월 1~15일 → 전월 말일까지 수집
  오늘이 매월 16~말일 → 당월 15일까지 수집
  (기존 대시보드의 M-2·M-1·M 기간 로직과 일치)
"""
    )
    parser.add_argument("--start", type=int, default=None,
                        help=f"시작 연도 (기본: {config.ASOS_START_DATE[:4]})")
    parser.add_argument("--through", type=int, default=None, dest="end",
                        help="특정 연도까지만 수집 (예: --through 2025)")
    parser.add_argument("--mode", choices=["smart", "latest", "y2025"],
                        default="smart",
                        help="수집 종료일 계산 모드 (기본: smart)")
    parser.add_argument("--force", action="store_true",
                        help="증분 수집을 무시하고 전체 재수집")
    args = parser.parse_args()

    collect_asos_data(
        start_year=args.start,
        end_year=args.end,
        force_refresh=args.force,
        mode=args.mode,
    )
