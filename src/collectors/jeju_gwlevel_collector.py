# ==============================================================================
#  파일명: src/collectors/jeju_gwlevel_collector.py
#  모듈: 제주 지하수정보관리시스템 (water.jeju.go.kr) 자동 수집기
# ------------------------------------------------------------------------------
#  Build: 0.1 (2026-06-01)
#  설계 근거:
#    - 프로토타입(scripts/proto_jeju_gwlevel_fetch.py) 으로 JW연동 1개소 검증 완료
#      · 31일×7컬럼=217셀 형변환 100% 성공
#      · 5/31 화면 캡처와 비트단위 일치
#      · 기존 csv 4월 4일치와 Δ=0.0000 (단위·정밀도·소스 동일성 확인)
#    - 검증 5팀 실측 보고서의 권고를 모두 반영:
#      · Atomic write (tmp → os.replace) ✓
#      · Fatal 플래그 전체중단 ✓
#      · ASOS collector 패턴(증분/재시도/백오프) 차용 ✓
#      · 부팅 자동 호출 회피 — 별도 CLI/스케줄러 권장 ✓
#      · SSL 한국 정부 CA 미포함 → verify=False 자동 폴백 ✓
# ------------------------------------------------------------------------------
#  【수집 흐름】
#    1) 0_JD관측망_정보.xlsx 에서 (관측소명, 허가번호=siteCode) 추출
#    2) water.jeju.go.kr 페이지 GET → JSESSIONID 발급
#    3) 관측소별:
#       a. 기존 by_station_day/_month CSV 의 마지막 날짜 파악
#       b. (마지막+1) ~ 어제 구간만 selectObsvEachList.json 호출
#       c. 응답 JSON 의 list 배열에서 의미 있는 7컬럼 추출
#       d. 기존 CSV 와 병합·중복 제거·정렬 → atomic 저장
#    4) 진행바 + 요청 간 1초 sleep (rate limit 보호)
#
#  【사용법】
#    # 일평균 전체 (어제까지 부족분만)
#    python src/collectors/jeju_gwlevel_collector.py
#
#    # 월평균
#    python src/collectors/jeju_gwlevel_collector.py --granularity month
#
#    # 일+월 동시
#    python src/collectors/jeju_gwlevel_collector.py --granularity both
#
#    # 1개소만 (테스트용)
#    python src/collectors/jeju_gwlevel_collector.py --station JW연동
#
#    # 전체 재수집 (기존 CSV 무시)
#    python src/collectors/jeju_gwlevel_collector.py --force
#
#  【에러 처리】
#    - HTTP 4xx (400/401/403/404): fatal — 즉시 전체 중단 (파라미터/세션 문제)
#    - HTTP 5xx, 타임아웃, ConnectionError: 재시도 (5초/10초/20초 백오프)
#    - SSL 검증 실패: verify=False 폴백 (1회만)
#    - 빈 응답: 정상 처리 (이미 최신 또는 이 기간 데이터 없음)
# ==============================================================================
from __future__ import annotations

import argparse
import os
import random
import sys
import time
from datetime import date, datetime, timedelta
from json import JSONDecodeError
from pathlib import Path

import pandas as pd
import requests
import urllib3
from tqdm import tqdm

# 프로젝트 루트 path 등록 (config import 용)
sys.path.append(str(Path(__file__).resolve().parents[2]))
import config


# ==============================================================================
#  ■ 상수
# ==============================================================================
BASE_URL = "https://water.jeju.go.kr"
PAGE_URL = f"{BASE_URL}/obsvsystem/gwobsv/obsvData/dataSearch/multiSearch.cs"
API_URL  = f"{BASE_URL}/obsvsystem/gwobsv/selectObsvEachList.json"

# JSON 응답 키 → CSV 컬럼명 매핑 (config.GW_COLUMNS 와 정합)
JSON_TO_CSV = {
    "dataTime": "날짜",
    "mSn":      "센서",
    "el":       "EL",
    "gl":       "GL",
    "wPress":   "Pressure",
    "wTemp":    "Temp",
    "scond":    "EC",
    "wBaro":    "Barometa",
    "battery":  "Battery",
}
# 저장 컬럼 순서 (관측소명은 별도 추가)
CSV_COLUMNS = ["관측소명"] + list(JSON_TO_CSV.values())
NUMERIC_COLS = ["EL", "GL", "Pressure", "Temp", "EC", "Barometa", "Battery"]

# 최초 백필 기본 시작일 (CSV 가 없을 때) — 사용자 작업지시문의 2015 와 일치
DEFAULT_START_DATE = "2015-01-01"

# 재시도 / Rate limit
MAX_RETRIES = 3
RETRY_BASE_DELAY = 5         # 초
INTER_REQUEST_SLEEP = 1.0    # 관측소 간 대기 (서버 부하 방지)
INTER_REQUEST_JITTER = 0.3   # ±0.3 초 jitter (검증팀 권고)

# 한 번에 요청할 최대 기간 (일평균 기준 약 1년).
# 너무 길게 잡으면 응답이 비대해지고 timeout 위험.
MAX_FETCH_WINDOW_DAYS = 366

# HTTP 헤더
HEADERS_HTML = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
    ),
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
HEADERS_API = {
    "Referer": PAGE_URL,
    "X-Requested-With": "XMLHttpRequest",
    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
    "Accept": "application/json, text/javascript, */*; q=0.01",
}


# Streamlit cache 호환 (CLI 실행 시 no-op)
try:
    import streamlit as _st
    _gw_cache = _st.cache_data(ttl=300, show_spinner=False, max_entries=4)
except Exception:
    def _gw_cache(fn):
        return fn


# ==============================================================================
#  ■ 1. 관측소 목록 로드
# ==============================================================================
def load_station_list() -> list[dict]:
    """`0_JD관측망_정보.xlsx` 에서 (관측소명, siteCode) 목록을 추출.

    페이지 dropdown 의 siteCode 와 엑셀의 '허가번호' 가 동일함을 프로토타입에서 확인:
      JW연동 → Y199310639, JD고산1 → W200710004 등.
    """
    xlsx_path = config.find_jd_network_file()
    if xlsx_path is None or not Path(xlsx_path).exists():
        raise FileNotFoundError(
            f"JD관측망 정보 엑셀을 찾을 수 없습니다.\n"
            f"  기대 경로: data/{config.JD_NETWORK_FILENAME}"
        )

    df = pd.read_excel(xlsx_path)
    if "관측소명" not in df.columns or "허가번호" not in df.columns:
        raise ValueError(
            f"엑셀 컬럼 부족: 관측소명/허가번호 필요. 현재: {df.columns.tolist()}"
        )

    stations = []
    for _, row in df.iterrows():
        name = str(row["관측소명"]).strip() if pd.notna(row["관측소명"]) else ""
        code = str(row["허가번호"]).strip() if pd.notna(row["허가번호"]) else ""
        if not name or not code or code.lower() == "nan":
            continue
        stations.append({
            "name": name,
            "siteCode": code,
            "operating": (str(row.get("운영현황", "")).strip()
                          if "운영현황" in df.columns else ""),
        })
    return stations


# ==============================================================================
#  ■ 2. 세션 및 SSL 처리
# ==============================================================================
def open_session() -> tuple[requests.Session, bool]:
    """페이지 GET 으로 JSESSIONID 발급. SSL 실패 시 verify=False 폴백.

    Returns: (session, verify_mode)
    """
    session = requests.Session()
    session.headers.update(HEADERS_HTML)
    try:
        r = session.get(PAGE_URL, timeout=15, verify=True)
        r.raise_for_status()
        return session, True
    except requests.exceptions.SSLError:
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        r = session.get(PAGE_URL, timeout=15, verify=False)
        r.raise_for_status()
        return session, False


# ==============================================================================
#  ■ 3. 단일 호출 (재시도 없음)
# ==============================================================================
def fetch_one(session: requests.Session, verify: bool,
              site_code: str, s_date: str, e_date: str,
              measure: str) -> tuple[str, list | None]:
    """단일 POST 호출. 상태 문자열 + (성공 시 list 배열) 반환.

    상태:
      SUCCESS         : 정상 (list 반환, 빈 리스트도 SUCCESS)
      FATAL_HTTP_4xx  : 재시도 무의미한 클라이언트 오류
      RETRY_*         : 재시도 가능
      NOT_JSON        : 응답이 JSON 이 아님
      INVALID         : JSON 인데 구조가 예상과 다름
    """
    payload = {
        "mesureUnit":  measure,
        "sDate":       s_date,
        "eDate":       e_date,
        "siteCode":    site_code,
        "mSns":        config.GW_REPRESENTATIVE_SENSOR,  # "S11"
        "isExcel":     "N",
        "pageIndex":   "1",
        "pageUnit":    "1000",        # dayAvg 366 + 여유, monAvg 12*N + 여유
        "awsRainChck": "false",
    }
    try:
        r = session.post(API_URL, data=payload, headers=HEADERS_API,
                         timeout=30, verify=verify)
    except requests.exceptions.Timeout:
        return "RETRY_TIMEOUT: 응답 시간 초과", None
    except requests.exceptions.ConnectionError as e:
        return f"RETRY_CONN: {type(e).__name__}", None
    except requests.exceptions.RequestException as e:
        return f"RETRY_REQ: {type(e).__name__}", None

    if r.status_code in (400, 401, 403, 404):
        return f"FATAL_HTTP_{r.status_code}: 재시도 무의미 (파라미터/세션 오류)", None
    if r.status_code >= 500:
        return f"RETRY_HTTP_{r.status_code}", None
    if r.status_code != 200:
        return f"HTTP_{r.status_code}", None

    try:
        data = r.json()
    except JSONDecodeError:
        return f"NOT_JSON: {r.text[:150]}", None

    if not isinstance(data, dict):
        return f"INVALID: 최상위가 dict 아님", None

    rows = data.get("list")
    if not isinstance(rows, list):
        return f"INVALID: list 키 없음 또는 list 아님", None

    return "SUCCESS", rows


def fetch_with_retry(session, verify, site_code, s_date, e_date, measure,
                     pbar: tqdm = None) -> tuple[list | None, bool]:
    """fetch_one 을 감싸 재시도 + 백오프. Returns (rows, fatal)."""
    for attempt in range(MAX_RETRIES):
        status, rows = fetch_one(session, verify, site_code, s_date, e_date, measure)
        if status == "SUCCESS":
            return rows, False

        # 치명적 — 즉시 중단
        if status.startswith("FATAL_"):
            msg = f"   ❌❌ [{site_code}] {status} (재시도 불가, 전체 중단)"
            (pbar.write if pbar else print)(msg)
            return None, True

        # 재시도 가능
        if status.startswith("RETRY") or status.startswith("HTTP_5"):
            if attempt < MAX_RETRIES - 1:
                delay = RETRY_BASE_DELAY * (2 ** attempt)
                msg = (f"   ⏳ [{site_code}] {status} → {delay}초 후 재시도 "
                       f"({attempt + 1}/{MAX_RETRIES})")
                (pbar.write if pbar else print)(msg)
                time.sleep(delay)
                continue

        # 그 외 — 1회 실패로 처리 (fatal 은 아님)
        msg = f"   ❌ [{site_code}] {status}"
        (pbar.write if pbar else print)(msg)
        return None, False

    return None, False


# ==============================================================================
#  ■ 4. JSON 행 → DataFrame
# ==============================================================================
def _normalize_month_date(s: str) -> str:
    """월평균 날짜를 'YYYY-MM-01' 표준으로 정규화.

    🛡️ (2026-06-01 오류5팀 권고) 다양한 포맷 모두 안전 처리:
      · 'YYYY-MM'              → 'YYYY-MM-01'
      · 'YYYY-MM-DD'           → 'YYYY-MM-01' (월 단위로 절삭)
      · 'YYYY-MM-DD HH:MM:SS'  → 'YYYY-MM-01'
      · ISO 8601 '...T00:00:00' → 'YYYY-MM-01'
      · 파싱 불가              → 원본 그대로 반환 (다운스트림 필터가 제외)
    """
    s = str(s).strip()
    if not s:
        return s
    try:
        dt = pd.to_datetime(s, errors="raise")
        return dt.strftime("%Y-%m-01")
    except Exception:
        # 폴백: 길이 기반 단순 규칙
        if len(s) == 7 and s[4] == "-":
            return f"{s}-01"
        return s


def parse_rows(rows: list, station_name: str,
               granularity: str = "day") -> pd.DataFrame:
    """API 응답의 list 배열을 CSV 컬럼 schema 로 변환.

    - JSON 키(dataTime, el, gl, wPress, wTemp, scond, wBaro, battery, mSn)
      → CSV 컬럼(날짜, 센서, EL, GL, Pressure, Temp, EC, Barometa, Battery)
    - 🆕 (2026-06-01) Month 모드: 날짜를 'YYYY-MM-DD' 형식(YYYY-MM-01)로 통일,
      '연월' 컬럼 추가. 검증 5팀 다면 분석 발견 — API 가 dataTime='YYYY-MM' 로
      반환하지만 기존 CSV 는 'YYYY-MM-01' 포맷이라 다운스트림 파서가 깨질 수 있음.
    - 숫자 컬럼은 to_numeric (errors='coerce') 으로 변환
    - 날짜 컬럼 유효성: NaN/빈 값 제거
    """
    if not rows:
        return pd.DataFrame(columns=CSV_COLUMNS)

    df = pd.DataFrame(rows)

    # 필요 컬럼만 추출 (없는 컬럼은 None 채움)
    for k in JSON_TO_CSV.keys():
        if k not in df.columns:
            df[k] = None
    df = df[list(JSON_TO_CSV.keys())].copy()
    df.columns = list(JSON_TO_CSV.values())

    # 숫자 변환
    for col in NUMERIC_COLS:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 🆕 Month 모드: 날짜 정규화 + 연월 컬럼 추가
    if granularity == "month":
        df["날짜"] = df["날짜"].astype(str).apply(_normalize_month_date)
        df["연월"] = df["날짜"].astype(str).str[:7]

    # 날짜 유효 행만
    df = df[df["날짜"].notna() & (df["날짜"].astype(str).str.strip() != "")]

    # 관측소명 부착
    df["관측소명"] = station_name

    # 컬럼 순서 — month 는 연월 추가
    cols = list(CSV_COLUMNS)
    if granularity == "month":
        cols = cols + ["연월"]
    return df[cols].reset_index(drop=True)


# ==============================================================================
#  ■ 5. CSV 저장 (증분 + atomic)
# ==============================================================================
def get_csv_path(station_name: str, granularity: str) -> Path:
    """granularity ∈ {'day', 'month'}"""
    if granularity == "day":
        return config.GW_STATION_DAY_DIR / f"{station_name}.csv"
    elif granularity == "month":
        return config.GW_STATION_MONTH_DIR / f"{station_name}.csv"
    else:
        raise ValueError(f"granularity must be 'day' or 'month', got {granularity!r}")


def get_save_paths(station_name: str, granularity: str) -> list[Path]:
    """🆕 (2026-06-01) 저장 대상 경로 목록.

    Month 모드는 두 경로에 미러 저장:
      · 신규: by_station_month/  (Build 1.2.01 정규 위치)
      · 레거시: by_station/      (04.지하수위 탭이 여기서 읽음)
    """
    primary = get_csv_path(station_name, granularity)
    if granularity == "month":
        legacy = config.GW_STATION_DIR / f"{station_name}.csv"
        return [primary, legacy]
    return [primary]


def get_last_date(csv_path: Path, granularity: str) -> date | None:
    """기존 CSV 의 마지막 날짜를 date 로 반환. 파일 없으면 None.

    날짜 형식:
      day  : 'YYYY-MM-DD'  → date 반환
      month: 'YYYY-MM' 또는 'YYYY-MM-DD' → date 반환 (혼합 안전)
    """
    if not csv_path.exists():
        return None
    try:
        df = pd.read_csv(csv_path, encoding="utf-8-sig", usecols=["날짜"])
        if df.empty:
            return None
        d_series = df["날짜"].astype(str).str.strip()
        if granularity == "day":
            parsed = pd.to_datetime(d_series, errors="coerce")
        else:
            # month: 'YYYY-MM' 행은 '-01' 보강, 'YYYY-MM-DD' 행은 그대로
            d_norm = d_series.apply(
                lambda x: f"{x}-01" if len(x) == 7 and x[4] == "-" else x
            )
            parsed = pd.to_datetime(d_norm, errors="coerce")
        valid = parsed.dropna()
        return valid.max().date() if not valid.empty else None
    except Exception:
        return None


def get_last_date_across_paths(station_name: str, granularity: str) -> date | None:
    """🆕 (2026-06-01) 미러 경로들의 최소 last_date 를 반환.

    Month 모드에서 by_station_month/ 와 by_station/ 중 더 stale 한 쪽 기준으로
    수집 윈도우를 결정해, 두 폴더 모두 같이 최신화되도록 보장.
    """
    paths = get_save_paths(station_name, granularity)
    dates = [get_last_date(p, granularity) for p in paths]
    valid = [d for d in dates if d is not None]
    if not valid:
        return None
    return min(valid)  # 가장 오래된 쪽 기준으로 fetch


def compute_window(last: date | None, granularity: str,
                   default_start: str, end_date: date) -> tuple[str, str] | None:
    """수집 구간을 결정. 이미 최신이면 None.

    granularity 'day':  sDate = last+1일, eDate = end_date
    granularity 'month': sDate = last 다음달 1일, eDate = end_date
                          (월평균 API 는 YYYY-MM-DD 형식 받지만 응답은 YYYY-MM)
    """
    if last is None:
        s_date = default_start
    else:
        if granularity == "day":
            nxt = last + timedelta(days=1)
        else:
            # 다음 달 1일
            if last.month == 12:
                nxt = date(last.year + 1, 1, 1)
            else:
                nxt = date(last.year, last.month + 1, 1)
        s_date = nxt.strftime("%Y-%m-%d")

    e_date = end_date.strftime("%Y-%m-%d")
    if s_date > e_date:
        return None
    return s_date, e_date


def save_atomic(df: pd.DataFrame, csv_path: Path) -> None:
    """tmp 에 쓴 뒤 os.replace 로 원자적 rename — Windows Excel 열림 상태 대응.

    🛡️ (2026-06-01 오류5팀 권고) os.replace 가 PermissionError 등으로 실패해도
    tmp 파일이 디스크에 남지 않도록 try/finally 정리.
    """
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = csv_path.with_suffix(csv_path.suffix + ".tmp")
    try:
        df.to_csv(tmp, index=False, encoding="utf-8-sig")
        os.replace(tmp, csv_path)
    except Exception:
        # tmp 잔존 방지 — 이후 같은 경로 재시도 시 stale tmp 가 방해되지 않게.
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        raise


def merge_and_save(new_df: pd.DataFrame, csv_path: Path,
                   granularity: str = "day") -> int:
    """기존 CSV 와 병합·중복 제거·날짜 정렬 후 저장. 신규 행 수 반환.

    🆕 (2026-06-01) Month 모드: 기존 CSV 의 잘못된 'YYYY-MM' 행을 'YYYY-MM-01'
    로 자동 정규화. 연월 컬럼이 비어있는 행도 채움. 정규화 후 dedup 으로
    중복 제거되어, 이전 빌드의 bad 행이 새 행으로 깨끗이 대체됨.
    """
    if new_df.empty:
        return 0

    if csv_path.exists():
        try:
            existing = pd.read_csv(csv_path, encoding="utf-8-sig")
        except Exception:
            existing = pd.DataFrame(columns=CSV_COLUMNS)

        # 🆕 Month 모드: 기존 행 정규화 (dedup 이전에)
        if granularity == "month" and "날짜" in existing.columns:
            existing["날짜"] = existing["날짜"].astype(str).apply(_normalize_month_date)
            if "연월" not in existing.columns:
                existing["연월"] = None
            # 연월 미설정인 행 채움
            empty_mask = existing["연월"].isna() | \
                         (existing["연월"].astype(str).str.strip().isin(["", "nan"]))
            existing.loc[empty_mask, "연월"] = existing.loc[empty_mask, "날짜"]\
                                                  .astype(str).str[:7]

        # 기존 + 신규 → drop_duplicates (같은 관측소·날짜는 신규 우선)
        combined = pd.concat([existing, new_df], ignore_index=True, sort=False)
        before = len(existing)
        combined = combined.drop_duplicates(
            subset=["관측소명", "날짜"], keep="last"
        )
        combined = combined.sort_values(by=["관측소명", "날짜"]).reset_index(drop=True)
        added = len(combined) - before
    else:
        combined = new_df.sort_values(by="날짜").reset_index(drop=True)
        added = len(combined)

    save_atomic(combined, csv_path)
    return max(added, 0)


# ==============================================================================
#  ■ 6. 관측소 단위 수집
# ==============================================================================
def collect_station(session, verify, station: dict, granularity: str,
                    force: bool, default_start: str, end_date: date,
                    pbar: tqdm = None) -> tuple[int, bool]:
    """단일 관측소·단일 granularity 수집. Returns (added_rows, fatal_flag)."""
    name = station["name"]
    site_code = station["siteCode"]
    measure = "dayAvg" if granularity == "day" else "monAvg"

    csv_path = get_csv_path(name, granularity)
    # 🆕 (2026-06-01) Month 모드는 by_station_month/ 와 by_station/ 양쪽 중 더
    # stale 한 쪽 기준으로 window 결정 → 두 폴더 모두 자동으로 같이 최신화됨.
    last = None if force else get_last_date_across_paths(name, granularity)
    window = compute_window(last, granularity, default_start, end_date)
    if window is None:
        return 0, False  # 이미 최신
    s_date, e_date = window

    # 너무 긴 구간은 분할 (초기 백필 시 부담 완화)
    fetched_rows: list = []
    fatal_flag = False
    cursor = datetime.strptime(s_date, "%Y-%m-%d").date()
    final_end = datetime.strptime(e_date, "%Y-%m-%d").date()

    while cursor <= final_end:
        if granularity == "day":
            chunk_end = min(cursor + timedelta(days=MAX_FETCH_WINDOW_DAYS - 1), final_end)
        else:
            # month 모드는 단번에 — 응답이 작음 (월별이라 12*N 행)
            chunk_end = final_end

        chunk_s = cursor.strftime("%Y-%m-%d")
        chunk_e = chunk_end.strftime("%Y-%m-%d")

        rows, fatal = fetch_with_retry(session, verify, site_code,
                                        chunk_s, chunk_e, measure, pbar=pbar)
        if fatal:
            fatal_flag = True
            break
        if rows:
            fetched_rows.extend(rows)
        cursor = chunk_end + timedelta(days=1)

    if fatal_flag:
        return 0, True

    new_df = parse_rows(fetched_rows, name, granularity)
    if new_df.empty:
        return 0, False

    # 🆕 (2026-06-01) Month 모드는 두 경로(신규 + 레거시)에 미러 저장
    # 🛡️ (2026-06-01 오류5팀 권고) 미러 중 하나만 실패해도 다른 경로는 살리고,
    #     실패한 경로는 다음 실행 시 get_last_date_across_paths 의 min() 로
    #     자가 치유됨.
    save_paths = get_save_paths(name, granularity)
    added_per_path: list[int] = []
    for p in save_paths:
        try:
            added_per_path.append(merge_and_save(new_df, p, granularity))
        except Exception as e:
            msg = f"   ⚠ [{name}] {p.name} 저장 실패 ({type(e).__name__}: {e}) — 다른 경로는 계속"
            if pbar:
                pbar.write(msg)
            else:
                print(msg)
            added_per_path.append(0)
    added = max(added_per_path) if added_per_path else 0
    return added, False


# ==============================================================================
#  ■ 7. 전체 수집 (오케스트레이션)
# ==============================================================================
def collect_all(granularity: str = "day", force: bool = False,
                only_station: str | None = None,
                default_start: str = DEFAULT_START_DATE,
                end_date: date | None = None) -> dict:
    """전체 관측소 수집. Returns 통계 dict."""
    if end_date is None:
        end_date = date.today() - timedelta(days=1)

    print("=" * 70)
    print(f"  💧 제주 지하수위 자동 수집 — {granularity.upper()} 모드")
    print(f"     모드:        {'dayAvg' if granularity == 'day' else 'monAvg'}")
    print(f"     최초 시작일: {default_start} (CSV 없을 때만 사용)")
    print(f"     종료일:      {end_date}")
    print(f"     강제 재수집: {force}")
    if only_station:
        print(f"     대상:        {only_station} (단일)")
    print("=" * 70)

    # 1) 관측소 목록
    try:
        stations = load_station_list()
    except Exception as e:
        print(f"❌ 관측소 목록 로드 실패: {e}")
        return {"total": 0, "added": 0, "fatal": True}

    if only_station:
        stations = [s for s in stations if s["name"] == only_station]
        if not stations:
            print(f"❌ 관측소 '{only_station}' 없음. xlsx 의 관측소명 확인하세요.")
            return {"total": 0, "added": 0, "fatal": False}

    print(f"📋 대상 관측소: {len(stations)}개")

    # 2) 세션
    print(f"\n[1/2] 세션 발급...")
    try:
        session, verify = open_session()
    except Exception as e:
        print(f"  ❌ 세션 실패: {type(e).__name__}: {e}")
        return {"total": len(stations), "added": 0, "fatal": True}
    print(f"  ✓ JSESSIONID 발급 완료 (verify={verify})")

    # 3) 수집 루프
    print(f"\n[2/2] 수집 시작 ({len(stations)}개소, granularity={granularity})\n")
    total_added = 0
    fatal_occurred = False
    failed_stations: list[str] = []
    skipped_uptodate = 0

    with tqdm(total=len(stations), desc="수집") as pbar:
        for st_idx, station in enumerate(stations):
            pbar.set_description(f"수집: {station['name']}")
            try:
                added, fatal = collect_station(
                    session, verify, station, granularity,
                    force, default_start, end_date, pbar=pbar,
                )
            except Exception as e:
                pbar.write(f"   ⚠ [{station['name']}] 예외: {type(e).__name__}: {e}")
                added, fatal = 0, False
                failed_stations.append(station["name"])

            if fatal:
                pbar.write("")
                pbar.write("=" * 70)
                pbar.write(f"  🛑 [{station['name']}] 치명적 오류로 전체 수집 중단")
                pbar.write(f"     이미 받은 데이터는 저장되었습니다.")
                pbar.write("=" * 70)
                fatal_occurred = True
                pbar.update(1)
                break

            if added == 0 and get_csv_path(station["name"], granularity).exists():
                skipped_uptodate += 1
            total_added += added

            pbar.update(1)
            # rate limit 보호 (jitter 포함)
            time.sleep(INTER_REQUEST_SLEEP + random.uniform(
                -INTER_REQUEST_JITTER, INTER_REQUEST_JITTER
            ))

    print(f"\n{'─' * 70}")
    print(f"  ✅ 신규 수집: {total_added:,}행 (총 {len(stations)}개소 중)")
    print(f"     이미 최신:   {skipped_uptodate}개소")
    if failed_stations:
        print(f"     ⚠ 실패:      {len(failed_stations)}개소 — {', '.join(failed_stations[:5])}{'...' if len(failed_stations) > 5 else ''}")
    if fatal_occurred:
        print(f"     🛑 치명적 중단 발생 — 위 메시지 확인 후 다시 실행하세요.")
    print(f"{'─' * 70}")

    # 🆕 (2026-06-01) Day 수집 후 parquet 통합 캐시 자동 재생성
    #   05.관측소 분석 탭과 anomaly_detection 등이 이 parquet 을 읽음.
    #   신규 행이 있거나 force 재수집인 경우 재생성. 평소엔 캐시 그대로.
    #   🛡️ 로직5팀 권고: force=True 면 added=0 이어도 재생성 (사용자 의도 우선)
    if granularity == "day" and (total_added > 0 or force) and not fatal_occurred:
        try:
            from src.collectors import gwlevel_day_parser
            print(f"\n  🗂  parquet 통합 캐시 재생성 중...")
            out = gwlevel_day_parser.build_day_parquet(verbose=False)
            print(f"  ✓ parquet 갱신: {out}")
        except Exception as e:
            print(f"  ⚠ parquet 재생성 실패 ({type(e).__name__}: {e})")
            print(f"     수동 재생성: python -c \"from src.collectors import gwlevel_day_parser; gwlevel_day_parser.build_day_parquet()\"")

    # 🆕 (2026-06-01) Month 수집 후 by_watershed/ 유역별 집계 자동 재생성
    #   04.지하수위 탭은 by_watershed/ 의 수역별 CSV (수역명.csv) 를 읽음.
    #   by_station/ 만 갱신하고 by_watershed/ 미갱신이면 탭에서 5월이 안 보임.
    #   🛡️ 로직5팀 권고: force=True 면 added=0 이어도 재집계 (사용자 의도 우선)
    if granularity == "month" and (total_added > 0 or force) and not fatal_occurred:
        try:
            from src.analysis import watershed_mapper
            print(f"\n  🗺️  by_watershed/ 유역별 집계 재생성 중...")
            watershed_mapper.run_watershed_pipeline(verbose=False)
            print(f"  ✓ 유역별 CSV 갱신: {config.GW_WATERSHED_DIR}")
        except Exception as e:
            print(f"  ⚠ 유역별 집계 실패 ({type(e).__name__}: {e})")
            print(f"     수동 재생성: python -c \"from src.analysis import watershed_mapper; watershed_mapper.run_watershed_pipeline()\"")

    return {
        "total": len(stations),
        "added": total_added,
        "skipped": skipped_uptodate,
        "failed": failed_stations,
        "fatal": fatal_occurred,
    }


# ==============================================================================
#  ■ 8. 대시보드용 헬퍼
# ==============================================================================
@_gw_cache
def load_station_day_csv(station_name: str) -> pd.DataFrame:
    """단일 관측소 일평균 CSV 로드 — 대시보드용 캐시."""
    csv_path = get_csv_path(station_name, "day")
    if not csv_path.exists():
        return pd.DataFrame(columns=CSV_COLUMNS)
    df = pd.read_csv(csv_path, encoding="utf-8-sig")
    if "날짜" in df.columns:
        df["날짜"] = pd.to_datetime(df["날짜"], errors="coerce")
    return df


# ==============================================================================
#  ■ 직접 실행
# ==============================================================================
if __name__ == "__main__":
    ap = argparse.ArgumentParser(
        description="제주 지하수정보관리시스템 자동 수집기 (water.jeju.go.kr)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
사용 예시:
  # 일평균 전체 — 부족분만 보강 (가장 일반적)
  python src/collectors/jeju_gwlevel_collector.py

  # 월평균 전체
  python src/collectors/jeju_gwlevel_collector.py --granularity month

  # 일+월 동시
  python src/collectors/jeju_gwlevel_collector.py --granularity both

  # 1개소 (테스트용)
  python src/collectors/jeju_gwlevel_collector.py --station JW연동

  # 강제 재수집 (기존 CSV 무시, 2015-01-01 부터)
  python src/collectors/jeju_gwlevel_collector.py --force --start 2026-01-01
""",
    )
    ap.add_argument("--granularity", choices=["day", "month", "both"],
                    default="day", help="수집 단위 (기본: day)")
    ap.add_argument("--force", action="store_true",
                    help="기존 CSV 무시하고 --start 부터 재수집")
    ap.add_argument("--station", default=None,
                    help="특정 관측소만 (예: JW연동) — 테스트용")
    ap.add_argument("--start", default=DEFAULT_START_DATE,
                    help=f"CSV 없을 때 시작일 (기본 {DEFAULT_START_DATE})")
    ap.add_argument("--end", default=None,
                    help="종료일 YYYY-MM-DD (기본: 어제)")
    args = ap.parse_args()

    end_d = (datetime.strptime(args.end, "%Y-%m-%d").date()
             if args.end else (date.today() - timedelta(days=1)))

    if args.granularity in ("day", "both"):
        collect_all("day", args.force, args.station, args.start, end_d)
    if args.granularity in ("month", "both"):
        if args.granularity == "both":
            print("\n")
        collect_all("month", args.force, args.station, args.start, end_d)
