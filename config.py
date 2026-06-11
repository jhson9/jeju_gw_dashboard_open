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
BUILD_VERSION = "2.0.0"

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

# ──────────────────────────────────────────────────────────────────────────
#  데이터 폴더 V3.0 레이아웃 (2026-05-25) — 도메인 번호 폴더 + 신규우선·구경로 폴백
#  탭 그룹과 정렬: 00_map(공통) / 01_rain_gwlevel / 02_well / 03_usage_quality
#                 / 04_drone / 05_ag_stat. 원자료는 00_source/<항목>/<연도> 보관.
#  _pick(new, old, ...): 존재하는 첫 경로(신규 우선) 반환. 없으면 신규 경로 반환
#  (생성 대상). → 마이그레이션 전·중·후 모두 앱이 정상 동작 (오류 0 목표).
# ──────────────────────────────────────────────────────────────────────────
def _pick(*candidates) -> Path:
    """신규 우선 + 구경로 자동 폴백. 존재하는 첫 경로, 없으면 candidates[0]."""
    for c in candidates:
        if Path(c).exists():
            return Path(c)
    return Path(candidates[0])

# 원자료 보관소(항목별·연도별) — 빌드 스크립트 입력 전용, 런타임 미사용
SOURCE_DIR        = DATA_DIR / "00_source"
# 도메인 루트 (신규우선·폴백)
MAP_DIR           = _pick(DATA_DIR / "00_map",          PROJECT_ROOT / "GIS_Map")
RAIN_GW_DIR       = DATA_DIR / "01_rain_gwlevel"
WELL_DIR          = _pick(DATA_DIR / "02_well",         PROJECT_ROOT / "data_ag_well")
USAGE_QUALITY_DIR = DATA_DIR / "03_usage_quality"
DRONE_DIR         = _pick(DATA_DIR / "04_drone",        PROJECT_ROOT / "data_drone")
AG_STAT_DIR       = _pick(DATA_DIR / "05_ag_stat",      DATA_DIR / "agri_stats")
# 06_landcover — 환경공간정보서비스(EGIS) WFS 시설재배지 빌드 산출물 (Build 2026-05-30)
LANDCOVER_DIR              = _pick(DATA_DIR / "06_landcover")
LANDCOVER_RAW_DIR          = LANDCOVER_DIR / "raw"
LANDCOVER_GREENHOUSE_YEARLY = LANDCOVER_DIR / "greenhouse_yearly.csv"
LANDCOVER_GREENHOUSE_REGION = LANDCOVER_DIR / "greenhouse_by_region.csv"
LANDCOVER_GREENHOUSE_RI     = LANDCOVER_DIR / "greenhouse_by_ri.csv"     # 법정리 177개 분해

ASOS_DIR = _pick(RAIN_GW_DIR / "ASOS", DATA_DIR / "ASOS")    # 기상 데이터 CSV
# 🆕 Build 1.2.01: 월별/일별 분리. 레거시 by_station 도 폴백으로 유지(요청 9·10).
_GW_BASE             = _pick(RAIN_GW_DIR / "GWlevel", DATA_DIR / "GWlevel")
GW_STATION_DIR       = _GW_BASE / "by_station"        # (레거시) 월별
GW_STATION_MONTH_DIR = _GW_BASE / "by_station_month"  # 월별 (정규)
GW_STATION_DAY_DIR   = _GW_BASE / "by_station_day"    # 일별 (신규)
GW_WATERSHED_DIR     = _GW_BASE / "by_watershed"      # 수역별 월별 CSV
# 🆕 (2026-06-11 로버스트-베이지안) 유역 대표값 사전계산 캐시 + 산정방법 설명 PDF
GW_ROBUST_DIR        = _GW_BASE / "robust"             # REF·A~F 7개 방식 parquet 캐시
GW_REF_DIR           = RAIN_GW_DIR / "Ref"             # 로버스트-베이지안 설명자료 PDF
ROW_DATA_DIR         = _pick(RAIN_GW_DIR / "Row_Data", DATA_DIR / "Row_Data")  # xls 원본 루트
ROW_DATA_MONTH_DIR   = ROW_DATA_DIR / "Month"          # 월별 원본
ROW_DATA_DAY_DIR     = ROW_DATA_DIR / "Day"            # 일별 원본 (HTML-disguised .xls)
# 관정 시설(02_well) 부속 — well_card / drilling_log
WELL_CARD_DIR        = _pick(WELL_DIR / "well_card",    PROJECT_ROOT / "data_well_card")
DRILLING_LOG_DIR     = _pick(WELL_DIR / "drilling_log", PROJECT_ROOT / "data_drilling_log")

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
#  ■ 1.5. Streamlit 서버 포트 (SSOT — 단일 진실 원천, 2026-05-29)
# ------------------------------------------------------------------------------
#  .env 의 STREAMLIT_PORT 로 override 가능. 미설정 시 18501 (private port range).
#  변경 영향 파일 (모두 본 상수를 참조):
#    - .streamlit/config.toml (streamlit 자체 — 정적 파일이라 PORT_CANDIDATES
#      첫 자리 변경 시 함께 수동 수정 필요)
#    - Run_JejuDashboard.bat (config.STREAMLIT_PORT 읽어 candidate 첫 자리 사용)
#    - _launch_browser.ps1 (bat 이 전달한 JEJU_PORT 환경변수 사용)
#    - src/dashboard/pdf_server.py (CORS 화이트리스트에 동적 추가)
#  WinError 10013 (Windows 예약 포트) 회피용 폴백 후보 4개도 함께 정의.
# ==============================================================================
STREAMLIT_PORT = int(os.getenv("STREAMLIT_PORT", "18501"))
# bat 자동 탐색용 폴백 후보 — 첫 자리가 STREAMLIT_PORT.
PORT_CANDIDATES = [STREAMLIT_PORT, 18502, 28501, 38501, 49001]


# ==============================================================================
#  ■ 2. 기상청 API 설정
# ==============================================================================
KMA_API_KEY = os.getenv("KMA_API_KEY", "")  # .env 파일에서 읽어옴
# 🆕 Build 1.2.01: V-World 2D 지도 API 키 (지도 분석 탭용).
# 미설정 시 OpenStreetMap + ESRI 위성으로 자동 폴백.
VWORLD_API_KEY = os.getenv("VWORLD_API_KEY", "")
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
#  ■ 4. 유역 정보 (16개: 기본 14 + 애월·안덕 추가) + 인근 AWS 매핑
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
    {"name": "애월",   "aws": "제주",   "color": "#6FAE5A"},   # 추가 — 제주시 서부
    # 남부
    {"name": "남원",   "aws": "성산",   "color": "#D4537E"},
    {"name": "동서귀", "aws": "서귀포", "color": "#639922"},
    {"name": "중서귀", "aws": "서귀포", "color": "#E24B4A"},
    {"name": "서서귀", "aws": "서귀포", "color": "#D85A30"},
    {"name": "안덕",   "aws": "고산",   "color": "#C2956F"},   # 추가 — 서귀포시 서부
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
ASOS_START_DATE = "20000101"   # 2000년 1월 1일부터 누적 (지하수위 관측정 시작 시점에 맞춰 확장)
# 종료일은 수집 시 '오늘' 날짜로 자동 결정됨 (asos_collector.py 참조)

# --- 기준 평균 산정 ---
RAINFALL_BASELINE_YEARS = 5    # 강수량: 직전 5년 평균
GWLEVEL_BASELINE_YEARS = 3     # 지하수위: 직전 3년 평균

# --- 농업유효강수일수 기준 ---
# 🆕 (2026-06-06 Stage 2 P1) docstring 추가 — 임계값 출처·기준 명시
EFFECTIVE_RAINFALL_THRESHOLD_MM = 5.0
"""농업유효강수일수 산정 임계값 (단위: mm).

일강수량이 이 값 이상인 날을 "농업유효강수일"로 카운트한다.
강우 일수보다 농업 영향이 큰 강우 빈도를 반영하는 지표로 사용.

기준 및 출처:
    - 5 mm/day 는 한국 농업·기상 분야에서 통용되는 농업유효강우 임계값.
      (참고: 농촌진흥청 농업기상 관측 가이드, 농어촌공사 수자원조사 일반편)
    - 본 대시보드는 제주 농업용 지하수 분석 목적으로 5.0 채택.
    - 향후 작물별·계절별 차등 임계값 도입 시 본 상수 대신 별도 dict 활용 권장.

사용처:
    - effective_rainfall.aggregate_monthly / aggregate_half_monthly
      → '유효강수일수(일)' 컬럼 생성 시 사용
    - tab01_overview, tab02 (구) , tab03_rainfall 등 카드·차트의 라벨 캡션
"""

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
# 라이트 모드 색상.
# P5-3 (2026-05-29): 단일 진실 원천(SSOT)은 src/dashboard/theme.py 의 COLOR_*
# 상수. 본 THEME_LIGHT 는 deprecated — src/ 내 호출처 0건이지만 외부 호출
# (HTML 템플릿·전처리 스크립트) 가능성 대비 backward compat 보존.
# 신규 코드는 `from src.dashboard import theme` 후 `theme.COLOR_*` 사용.
THEME_LIGHT = {
    "bg_primary":    "#ffffff",
    "bg_secondary":  "#f5f5f3",   # ↔ theme.COLOR_BG_SECONDARY
    "bg_info":       "#e6f1fb",   # ↔ theme.COLOR_BG_INFO
    "text_primary":  "#1a1a18",   # ↔ theme.COLOR_TEXT_PRIMARY
    "text_secondary":"#5f5e5a",   # ↔ theme.COLOR_TEXT_SECONDARY
    "text_info":     "#185fa5",   # ↔ theme.COLOR_TEXT_INFO
    "border_tertiary": "rgba(26,26,24,0.15)",
    "border_info":   "#85b7eb",   # ↔ theme.COLOR_BORDER_INFO
}


# ==============================================================================
#  ■ 8. 유틸리티 함수
# ==============================================================================
# ==============================================================================
#  ■ 10. 드론 영상 모듈 (data_drone/) — Build 2.0 (tab31)
# ------------------------------------------------------------------------------
#  DJI Terra 산출물(저수조·관정·수원지 항공 측량)을 대시보드 tab31 에서 표시.
#  자료는 data_drone/{mission_id}/ 안에 미션별로 격리:
#    map/result.tif       — 정사사진 (UTM52N, GSD 1~5cm)
#    map/dsm.tif          — DSM
#    models/pc/0/terra_b3dms/tileset.json — 3D Tiles (ECEF)
#    derived/preview.png  — Folium ImageOverlay 용 다운샘플 (자동 생성·캐시)
#
#  registry.json 1개 + 미션별 meta.json 1개씩 — 미션 추가 시 두 파일만 갱신.
# ==============================================================================
DRONE_DATA_ROOT      = Path(os.getenv("DRONE_DATA_ROOT", str(DRONE_DIR)))  # V3: data/04_drone (폴백: data_drone)
DRONE_REGISTRY_FILE  = DRONE_DATA_ROOT / "registry.json"
DRONE_MASTER_FILE    = DRONE_DATA_ROOT / "master_drone.csv"

# 드론 데이터 소스 폴더 (DJI Terra 결과물 원본)
# .env 에서 DRONE_SOURCE_DIR=C:\path\to\Jeju_Drone 으로 설정 가능
# 비어 있으면 데이터 관리 탭 UI에서 매번 직접 지정
DRONE_SOURCE_DIR: Path | None = (
    Path(os.getenv("DRONE_SOURCE_DIR"))
    if os.getenv("DRONE_SOURCE_DIR")
    else None
)

# 지도 기본값 — 4개 미션 중심 ≈ 제주 동·서부 평균
DRONE_MAP_DEFAULT_CENTER = (33.40, 126.55)
DRONE_MAP_DEFAULT_ZOOM   = 10

# 미션 분류 → 마커 색상 (theme 토큰과 조화)
DRONE_SITE_TYPE_COLORS = {
    "저수조":   "#185fa5",
    "관정":     "#1d9e75",
    "수원지":   "#8E24AA",
    "기타":     "#FB8C00",
}

# 다운샘플 preview.png 의 최대 변 길이(px) — Folium ImageOverlay 성능 기준
DRONE_PREVIEW_MAX_SIDE = 2048


# ==============================================================================
#  ■ 9. 농업용 공공관정 모듈 (data_ag_well/) — Build 2.0
# ==============================================================================
#  서귀포시 414개 농업용 공공관정의 사후관리 자료(이용량·수질).
#  외부 ETL이 갱신한 CSV만 read-only 로 읽는다.

# ── GIS 경계 (Build 2.x — tab8-2 이용량 지도분석) ──
#  .shp 원본은 EPSG:5186. GeoJSON 은 Phase 0 에서 WGS84 로 사전 변환된 산출물.
#  shp 직접 로드 금지(라이브러리 의존성 0개 원칙). 변환 스크립트는 _작업지시서 §부록 E.
GIS_MAP_DIR          = MAP_DIR    # V3: data/00_map (폴백: GIS_Map)
RI_BOUNDARY_GEOJSON  = GIS_MAP_DIR / "리경계.geojson"
EUP_BOUNDARY_GEOJSON = GIS_MAP_DIR / "읍면동경계.geojson"

# 관정 시설(master)은 02_well, 이용량·수질은 03_usage_quality 로 분리 (V3.0).
AG_WELL_DIR             = WELL_DIR    # V3: data/02_well (폴백: data_ag_well)
AG_MASTER_FILE          = _pick(WELL_DIR / "master.csv", PROJECT_ROOT / "data_ag_well" / "master.csv")
AG_MASTER_YEARLY_DIR    = _pick(WELL_DIR / "master_yearly", PROJECT_ROOT / "data_ag_well" / "master_yearly")
AG_USAGE_DIR            = _pick(USAGE_QUALITY_DIR / "usage", PROJECT_ROOT / "data_ag_well" / "usage")
AG_QUALITY_DIR          = _pick(USAGE_QUALITY_DIR / "water_quality", PROJECT_ROOT / "data_ag_well" / "water_quality")
AG_QUALITY_SEMIANNUAL   = AG_QUALITY_DIR / "water_quality_semiannual.csv"
# 정기검사 15항목 CSV — 실제 파일명은 water_quality_agricultural.csv (농업용 정기검사).
# 과거 코드에서 "regular"라는 이름으로 참조하므로 상수명은 호환을 위해 유지.
AG_QUALITY_REGULAR      = AG_QUALITY_DIR / "water_quality_agricultural.csv"
# 농업통계(05_ag_stat) — tab41~45 데이터셋
AGRI_STATS_DIR          = AG_STAT_DIR

# 사후관리(AG) 자료 보유 연도 — Tab 11~29(농업관정·이용량·수질·통계) 전용 범위.
# 정책: AG 데이터는 2025년까지 검증 완료된 자료만 사용. 2026 자료는 검증 후 별도 결정.
# 강수량/지하수위(Tab 01~10)는 본 상수와 무관 — ASOS·GW level 은 데이터 파일에서
# 자동으로 최신 연월까지 사용하며 별도 상한 없음(asos_collector smart end date).
AG_USAGE_YEAR_RANGE   = (2017, 2025)   # usage_montly_YYYY.csv
AG_QUALITY_YEAR_RANGE = (2015, 2025)   # water_quality_semiannual.csv

# --- 사후관리: 반기 수질 5항목 기준치 (먹는물공동시설 기준) ---
WATER_QUALITY_STANDARDS = {
    "ammonia_n": {"kor": "암모니아성 질소", "unit": "mg/L",  "max": 0.5},
    "nitrate_n": {"kor": "질산성질소",      "unit": "mg/L",  "max": 20.0},
    "pH":        {"kor": "수소이온농도",    "unit": "-",     "min": 6.0, "max": 8.5},
    "chloride":  {"kor": "염소이온",        "unit": "mg/L",  "max": 250.0},
    "EC":        {"kor": "전기전도도",      "unit": "μS/cm"},  # 참고치
}

# --- 정기검사 15항목 기준치 (mg/L) ---
WATER_QUALITY_REGULAR_STANDARDS = {
    "pH":         {"kor": "수소이온농도",        "unit": "-",    "min": 6.0, "max": 8.5},
    "chloride":   {"kor": "염소이온",            "unit": "mg/L", "max": 250.0},
    "nitrate_n":  {"kor": "질산성질소",          "unit": "mg/L", "max": 20.0},
    "cadmium":    {"kor": "카드뮴",              "unit": "mg/L", "max": 0.01},
    "arsenic":    {"kor": "비소",                "unit": "mg/L", "max": 0.05},
    "cyanide":    {"kor": "시안",                "unit": "mg/L", "max": 0.01},
    "mercury":    {"kor": "수은",                "unit": "mg/L", "max": 0.001},
    "organic_p":  {"kor": "유기인",              "unit": "mg/L", "max": 0.0005},
    "diazinon":   {"kor": "다이아지논",          "unit": "mg/L", "max": 0.02},
    "parathion":  {"kor": "파라티온",            "unit": "mg/L", "max": 0.06},
    "phenol":     {"kor": "페놀",                "unit": "mg/L", "max": 0.005},
    "lead":       {"kor": "납",                  "unit": "mg/L", "max": 0.1},
    "chromium":   {"kor": "크롬",                "unit": "mg/L", "max": 0.05},
    "TCE":        {"kor": "트리클로로에틸렌",    "unit": "mg/L", "max": 0.03},
    "PCE":        {"kor": "테트라클로로에틸렌",  "unit": "mg/L", "max": 0.01},
    "TCA_111":    {"kor": "1,1,1-트리클로로에탄","unit": "mg/L", "max": 0.3},
}

# --- 농업용 관정 색상 팔레트 ---
AG_PALETTE = {
    "seogwipo":     "#C65911",   # 서귀포시 (관할)
    "jeju":         "#305496",   # 제주시 (관할)
    "agriculture":  "#548235",   # 농업용
    "household":    "#305496",   # 생활용
    "fisheries":    "#5B9BD5",   # 어업용
    "industrial":   "#C00000",   # 공업용
}

# --- 관리주체별 4색 (master.csv 의 authority_kor 한글값 기반) ---
# 사용자 요청 (2026-05-16): tab5 관정 검색 지도 마커를 관리주체 4종으로 구분.
# 영문 authority (jeju/seogwipo 2종) 로는 4-way 식별 불가 — 농어촌공사·제주
# 특별자치도는 well_si 가 어느 시인지에 따라 영문 변환되어 잃어버림.
# 별도 범례 불요 (tab5 결과 표의 '관리주체' 컬럼이 implicit 범례).
# 색맹 친화: 파/주/cyan/보라 조합 — 명도·채도 모두 분산.
AG_AUTHORITY_PALETTE = {
    "제주시":          "#1976D2",   # 파랑 (Material Blue 700)
    "서귀포시":        "#FB8C00",   # 주황 (Material Orange 600)
    "농어촌공사":      "#00ACC1",   # cyan (Material Cyan 700)
    "제주특별자치도":  "#8E24AA",   # 보라 (Material Purple 600)
}
AG_QUALITY_PALETTE = {
    "normal":   "#548235",   # 적합
    "exceed":   "#C00000",   # 부적합
    "missing":  "#7F7F7F",   # 측정안됨/누락
    "below_dl": "#9DC3E6",   # 불검출
}


def ensure_directories():
    """
    필수 디렉토리들이 없으면 자동으로 생성합니다.
    프로그램 최초 실행 시 호출됩니다.
    """
    for d in [DATA_DIR, ASOS_DIR,
              GW_STATION_DIR, GW_STATION_MONTH_DIR, GW_STATION_DAY_DIR,
              GW_WATERSHED_DIR, GW_ROBUST_DIR,
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
