# ==============================================================================
#  제주도 지하수위·강수량 분석 대시보드
#  파일명: config.py
#  모듈: 전역 설정 (경로·관측소·수역·색상·기준값)
# ------------------------------------------------------------------------------
#  Build: 0.1
#  최종 수정일: 2026-04-21
# ------------------------------------------------------------------------------
#  Changelog:
#  - v0.1 (2026-04-21): 최초 생성.
#                       기존 HTML 대시보드(v8)의 AWS·WS 배열과 색상 코드를
#                       Python 구조로 이식. 경로·기준값·API 정보 통합.
# ------------------------------------------------------------------------------
#  【이 파일의 역할】
#  프로젝트 전체에서 공통으로 쓰이는 상수와 설정값을 한 곳에 모았습니다.
#  다른 모듈에서는 `from config import STATIONS_ASOS` 같은 식으로 불러씁니다.
#  → 색상 변경, 관측소 추가, 경로 변경 등 수정이 필요할 땐 이 파일만 고치면 됩니다.
# ==============================================================================

from pathlib import Path
import os
from dotenv import load_dotenv

# ------------------------------------------------------------------------------
#  빌드 버전 (대시보드 푸터에 표시)
#  수정 때마다 0.01 씩 증가시킵니다.
# ------------------------------------------------------------------------------
BUILD_VERSION = "1.2.07"

# ------------------------------------------------------------------------------
#  .env 파일 로드 (API 키 등 비밀 정보)
#  load_dotenv()를 호출하면 프로젝트 루트의 .env 파일을 자동으로 읽어서
#  os.getenv()로 접근 가능하게 만듭니다.
# ------------------------------------------------------------------------------
load_dotenv()


# ==============================================================================
#  ■ 1. 경로 설정
# ==============================================================================
#  Path(__file__): 이 config.py 파일의 절대 경로
#  .parent : config.py가 들어있는 폴더 (= 프로젝트 루트)
#  / "data": 그 아래 data 폴더를 가리킴
#
#  이렇게 Path 객체로 경로를 관리하면 Windows/Mac/Linux 어디서든 동작합니다.

PROJECT_ROOT = Path(__file__).parent.resolve()  # 프로젝트 최상위 폴더

DATA_DIR = PROJECT_ROOT / "data"                # 전체 데이터 저장 폴더
ASOS_DIR = DATA_DIR / "ASOS"                    # 기상 데이터 CSV 저장 위치
# 🆕 Build 1.2.01: 월별/일별 분리. 레거시 by_station 도 폴백으로 유지.
GW_STATION_DIR       = DATA_DIR / "GWlevel" / "by_station"        # (레거시) 월별
GW_STATION_MONTH_DIR = DATA_DIR / "GWlevel" / "by_station_month"  # 월별 (정규)
GW_STATION_DAY_DIR   = DATA_DIR / "GWlevel" / "by_station_day"    # 일별 (신규)
GW_WATERSHED_DIR     = DATA_DIR / "GWlevel" / "by_watershed"      # 수역별 월별 CSV
ROW_DATA_DIR         = DATA_DIR / "Row_Data"            # xls 원본 루트(레거시)
ROW_DATA_MONTH_DIR   = ROW_DATA_DIR / "Month"           # 월별 원본
ROW_DATA_DAY_DIR     = ROW_DATA_DIR / "Day"             # 일별 원본 (HTML-disguised .xls)

# JD관측망 정보 파일 (업로드한 엑셀)
# 🆕 Build 0.7: 탐색 우선순위를 data/ 폴더 중심으로 변경.
#   사용자가 파일을 data/ 에 두는 것을 권장하기 위함.
#   구버전(루트/Row_Data)도 하위 호환으로 계속 지원.
JD_NETWORK_FILENAME = "0_JD관측망_정보.xlsx"
JD_NETWORK_FILE_CANDIDATES = [
    DATA_DIR / JD_NETWORK_FILENAME,          # 🆕 권장 위치 (data/)
    PROJECT_ROOT / JD_NETWORK_FILENAME,      # 루트 (하위 호환)
    ROW_DATA_DIR / JD_NETWORK_FILENAME,      # Row_Data (하위 호환)
    # 과거 오타 파일명(언더바 없음)도 지원
    DATA_DIR / "0JD관측망_정보.xlsx",
    PROJECT_ROOT / "0JD관측망_정보.xlsx",
    DATA_DIR / "0JD관측망 정보.xlsx",
    PROJECT_ROOT / "0JD관측망 정보.xlsx",
]


# ==============================================================================
#  ■ 2. 기상청 API 설정
# ==============================================================================
# 우선순위: 환경변수(.env, 로컬) → Streamlit Cloud Secrets (외부 배포 시)
KMA_API_KEY = os.getenv("KMA_API_KEY", "")
if not KMA_API_KEY:
    try:
        import streamlit as st
        KMA_API_KEY = st.secrets.get("KMA_API_KEY", "")
    except Exception:
        pass

# 🆕 Build 1.2.01: V-World 2D 지도 API 키 (공간 분석 탭용).
#   동일한 우선순위: .env → Streamlit Cloud Secrets.
#   미설정 시 OpenStreetMap + ESRI 위성으로 자동 폴백.
VWORLD_API_KEY = os.getenv("VWORLD_API_KEY", "")
if not VWORLD_API_KEY:
    try:
        import streamlit as st
        VWORLD_API_KEY = st.secrets.get("VWORLD_API_KEY", "")
    except Exception:
        pass
# 🆕 Build 0.3: HTTPS 전환 (공공데이터포털이 2024년부터 HTTPS 강제)
KMA_API_URL = "https://apis.data.go.kr/1360000/AsosDalyInfoService/getWthrDataList"
# 🆕 Build 0.3: 진단용 폴백 URL (HTTPS 실패 시 HTTP로 테스트)
KMA_API_URL_FALLBACK = "http://apis.data.go.kr/1360000/AsosDalyInfoService/getWthrDataList"
KMA_API_TIMEOUT = 30       # 🆕 Build 0.3: 60초 → 30초 (빠른 실패 감지)
KMA_API_MAX_RETRIES = 3    # 🆕 Build 0.3: 5회 → 3회 (무의미한 재시도 감소)
KMA_API_RETRY_DELAY = 5    # 🆕 Build 0.3: 10초 → 5초

# 🆕 Build 0.4: User-Agent 헤더 추가
#   공공데이터포털이 봇 방지를 위해 User-Agent 없는 요청을 403 Forbidden으로
#   차단하기 시작함 (2024~2025년경 정책 변경).
#   브라우저인 척 하는 표준 User-Agent 를 사용하여 차단 회피.
HTTP_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/120.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/xml, */*",
    "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8",
}


# ==============================================================================
#  ■ 3. ASOS 기상관측소 정보 (4개 지점)
#      기존 HTML 대시보드의 AWS 배열과 동일한 구조·색상을 계승
# ==============================================================================
#  - id   : 기상청 지점코드 (API 호출 시 stnIds 파라미터로 사용)
#  - name : 표시 이름 (데이터 키로도 사용)
#  - color: 차트·표의 고유 색상 (HEX)
STATIONS_ASOS = [
    {"id": 184, "name": "제주",   "color": "#378ADD"},
    {"id": 189, "name": "서귀포", "color": "#1D9E75"},
    {"id": 188, "name": "성산",   "color": "#E24B4A"},
    {"id": 185, "name": "고산",   "color": "#BA7517"},
]

# 이름 → 색상을 바로 찾기 위한 딕셔너리 (차트에서 자주 씀)
AWS_COLOR_MAP = {s["name"]: s["color"] for s in STATIONS_ASOS}

# 이름 → 지점코드
AWS_CODE_MAP = {s["name"]: s["id"] for s in STATIONS_ASOS}


# ==============================================================================
#  ■ 4. 유역 정보 (14개) + 인근 AWS 매핑
#      요청 순서: 동부(구좌,성산,표선) → 서부(대정,한경,한림)
#               → 남부(남원,동서귀,중서귀,서서귀) → 북부(동제주,중제주,서제주,조천)
# ==============================================================================
WATERSHEDS = [
    # 동부
    {"name": "구좌",   "aws": "성산",   "color": "#7F77DD"},
    {"name": "성산",   "aws": "성산",   "color": "#F09595"},
    {"name": "표선",   "aws": "성산",   "color": "#85B7EB"},
    # 서부
    {"name": "대정",   "aws": "고산",   "color": "#888780"},
    {"name": "한경",   "aws": "고산",   "color": "#BA7517"},
    {"name": "한림",   "aws": "제주",   "color": "#1D9E75"},
    # 남부
    {"name": "남원",   "aws": "성산",   "color": "#D4537E"},
    {"name": "동서귀", "aws": "서귀포", "color": "#639922"},
    {"name": "중서귀", "aws": "서귀포", "color": "#E24B4A"},
    {"name": "서서귀", "aws": "서귀포", "color": "#D85A30"},
    # 북부
    {"name": "동제주", "aws": "제주",   "color": "#85B7EB"},
    {"name": "중제주", "aws": "제주",   "color": "#378ADD"},
    {"name": "서제주", "aws": "제주",   "color": "#185FA5"},
    {"name": "조천",   "aws": "제주",   "color": "#5DCAA5"},
]

# 유역명 → 색상
WATERSHED_COLOR_MAP = {w["name"]: w["color"] for w in WATERSHEDS}

# 유역명 → 인근 AWS 이름
WATERSHED_AWS_MAP = {w["name"]: w["aws"] for w in WATERSHEDS}


# ==============================================================================
#  ■ 5. 분석 파라미터
# ==============================================================================
# --- 데이터 수집 기간 ---
ASOS_START_DATE = "20160101"   # 2016년 1월 1일부터 누적
# 종료일은 수집 시 '오늘' 날짜로 자동 결정됨 (asos_collector.py 참조)

# --- 기준 평균 산정 ---
RAINFALL_BASELINE_YEARS = 5    # 강수량: 직전 5년 평균
GWLEVEL_BASELINE_YEARS = 3     # 지하수위: 직전 3년 평균

# --- 농업유효강수일수 기준 ---
EFFECTIVE_RAINFALL_THRESHOLD_MM = 5.0   # 일강수량 5mm 이상 → '유효강수일'로 카운트

# --- 반월(1~15일) 구분 기준 ---
HALF_MONTH_BOUNDARY_DAY = 15   # 15일 이하 / 16일 이상으로 M 기간 산정 방식이 달라짐
HALF_MONTH_M_COEFFICIENT = 0.5 # 반월 M 기간의 직전평균에 곱해지는 계수


# ==============================================================================
#  ■ 6. 지하수위 센서 설정
# ==============================================================================
GW_REPRESENTATIVE_SENSOR = "S11"  # 대표 센서 (다른 센서: S21, S22, S23, S24, S25)

# xls 시트에서 읽어들일 컬럼 정보
# (원본 파일의 컬럼 순서와 이름을 기준으로 함)
GW_COLUMNS = {
    "station": "관측소명",
    "date": "날짜",         # YYYY-MM 형식
    "sensor": "센서",
    "EL": "EL",            # 지하수위 (m)
    "GL": "GL",
    "pressure": "Pressure",
    "temp": "Temp",
    "ec": "EC",
    "barometa": "Barometa",
    "battery": "Battery",
}


# ==============================================================================
#  ■ 7. 대시보드 테마 (기존 HTML CSS 변수 계승)
# ==============================================================================
# 라이트 모드 색상
THEME_LIGHT = {
    "bg_primary":    "#ffffff",
    "bg_secondary":  "#f5f5f3",
    "bg_info":       "#e6f1fb",
    "text_primary":  "#1a1a18",
    "text_secondary":"#5f5e5a",
    "text_info":     "#185fa5",
    "border_tertiary": "rgba(26,26,24,0.15)",
    "border_info":   "#85b7eb",
}


# ==============================================================================
#  ■ 8. 유틸리티 함수
# ==============================================================================
def ensure_directories():
    """
    필수 디렉토리들이 없으면 자동으로 생성합니다.
    프로그램 최초 실행 시 호출됩니다.
    """
    for d in [DATA_DIR, ASOS_DIR,
              GW_STATION_DIR, GW_STATION_MONTH_DIR, GW_STATION_DAY_DIR,
              GW_WATERSHED_DIR,
              ROW_DATA_DIR, ROW_DATA_MONTH_DIR, ROW_DATA_DAY_DIR]:
        d.mkdir(parents=True, exist_ok=True)


def find_jd_network_file():
    """
    JD관측망 정보 엑셀 파일을 여러 후보 경로에서 찾습니다.
    찾지 못하면 None 반환.
    """
    for path in JD_NETWORK_FILE_CANDIDATES:
        if path.exists():
            return path
    return None


# ------------------------------------------------------------------------------
#  이 파일을 직접 실행(python config.py)하면 현재 설정을 확인할 수 있습니다.
# ------------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 60)
    print("  제주도 지하수위·강수량 분석 대시보드 - 설정 확인")
    print("=" * 60)
    print(f"프로젝트 루트: {PROJECT_ROOT}")
    print(f"데이터 폴더:  {DATA_DIR}")
    print(f"ASOS 지점:    {[s['name'] for s in STATIONS_ASOS]}")
    print(f"수역:         {[w['name'] for w in WATERSHEDS]} ({len(WATERSHEDS)}개)")
    print(f"수집 시작일:  {ASOS_START_DATE}")
    print(f"강수량 기준:  직전 {RAINFALL_BASELINE_YEARS}년")
    print(f"수위 기준:    직전 {GWLEVEL_BASELINE_YEARS}년")
    print(f"유효강수 기준: 일 {EFFECTIVE_RAINFALL_THRESHOLD_MM}mm 이상")
    print(f"대표 센서:    {GW_REPRESENTATIVE_SENSOR}")
    print(f"API 키 설정됨: {'Yes' if KMA_API_KEY else 'No (⚠️ .env 파일 확인)'}")
    print("=" * 60)
    ensure_directories()
    print("✅ 필수 디렉토리 확인/생성 완료")
