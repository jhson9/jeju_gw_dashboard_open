# ==============================================================================
#  제주도 농업용 지하수 분석 대시보드
#  파일명: src/dashboard/app.py
# ------------------------------------------------------------------------------
#  Build: 1.2.01
#  최종 수정일: 2026-04-26
# ------------------------------------------------------------------------------
#  Changelog:
#  - v0.1 ~ v0.9: (생략 - CHANGELOG.md 참조)
#  - v1.0 (2026-04-22): 정식 릴리스.
#                       * 사이드바 완전 제거
#                       * 기존 HTML처럼 상단 헤더에 날짜 입력 + [분석] 버튼
#                       * 분석 기간 배지 헤더 바로 아래 표시
#                       * 탭 구조 유지 (5개 탭)
#  - v1.2.01 (2026-04-26): 지도 분석 탭(④) 추가 → 총 6개 탭.
#                       * V-World 2D 타일(키 있을 때) + OSM 폴백
#                       * 관측정/AWS 마커 + 드롭다운 양방향 연동
#                       * 관측정: 일자료 시계열(10년/시작월) + 12개월 표·차트
#                       * AWS:    12개월 강수량/유효강수일수 + 10년 월별 강수
#                       * 일자료 파서(gwlevel_day_parser): wide HTML xls→long upsert
#                       * 디렉토리 분리: by_station_month / by_station_day
#                                       Row_Data/Month / Row_Data/Day
# ==============================================================================

import logging
import os
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[2]))


# ──────────────────────────────────────────────────────────────────
#  Streamlit static MIME 화이트리스트 패치 (2026-05-24 재추가)
#  -----------------------------------------------------------------
#  Cesium 의 Web Worker 는 same-origin 제약 — cross-origin worker 는
#  silent failure (Draco mesh 디코딩 멈춤 → tab33 b3dm 처리 안 됨).
#  CESIUM_BASE_URL 을 Streamlit static (same-origin) 으로 옮기려면 .js
#  가 application/javascript 로 응답돼야 함. Streamlit 1.47 의
#  AppStaticFileHandler 는 .js 를 force text/plain 응답하므로 화이트리스트
#  확장 + stderr 로 적용 확인 출력.
# ──────────────────────────────────────────────────────────────────
try:
    import mimetypes
    # Windows mimetypes 누락 보강.
    mimetypes.add_type("application/javascript", ".js")
    mimetypes.add_type("text/css", ".css")
    mimetypes.add_type("application/wasm", ".wasm")

    from streamlit.web.server import app_static_file_handler as _ash
    _before = set(_ash.SAFE_APP_STATIC_FILE_EXTENSIONS)
    _ash.SAFE_APP_STATIC_FILE_EXTENSIONS = tuple(
        _before | {".js", ".css", ".wasm", ".glb", ".gltf", ".bin", ".ktx2", ".ktx", ".svg"}
    )

    # 방어 심층 — set_extra_headers 메서드 자체를 교체. 상수 lookup 이 어떤
    # 이유로든 빗나가도 method override 가 Content-Type 강제를 제거함.
    # X-Content-Type-Options:nosniff 은 그대로 유지.
    # 2026-05-24 추가: Cache-Control: no-cache 강제 — Cesium 버전 교체 후
    # 브라우저가 이전 캐시 사용해 새 .js 안 받는 문제 우회. iframe srcdoc 안
    # 리소스는 Ctrl+Shift+R 도 우회 못 하므로 서버 측 헤더가 가장 확실.
    def _set_extra_headers(self, path):   # noqa: ANN001, ARG001
        self.set_header("X-Content-Type-Options", "nosniff")
        self.set_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.set_header("Pragma", "no-cache")
        self.set_header("Expires", "0")
    _ash.AppStaticFileHandler.set_extra_headers = _set_extra_headers

    print(
        f"[MIME-PATCH] OK · .js whitelisted={'.js' in _ash.SAFE_APP_STATIC_FILE_EXTENSIONS} "
        f"· method=overridden",
        file=sys.stderr, flush=True,
    )
except Exception as _e:   # noqa: BLE001
    import traceback
    print(f"[MIME-PATCH] FAILED · {_e}", file=sys.stderr, flush=True)
    traceback.print_exc()


# ──────────────────────────────────────────────────────────────────
#  Streamlit 의 fragment-id stale 디버그 로그 억제
#  -----------------------------------------------------------------
#  메시지 예: "Couldn't find fragment with id ... Usually this doesn't
#             happen or no action is required, so its mainly for debugging."
#  → 우리가 @st.fragment 안에서 st.rerun(scope="fragment") 사용 중인데도
#    streamlit-folium 의 비동기 height 변경 등으로 가끔 발생. 동작에는 영향
#    없는 디버그 메시지라 사용자 터미널을 어지럽히는 것만 막는다.
# ──────────────────────────────────────────────────────────────────
class _FragmentNoiseFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        return "Couldn't find fragment with id" not in msg


_FRAGMENT_NOISE_FILTER = _FragmentNoiseFilter()


def _attach_fragment_noise_filter(logger: logging.Logger) -> None:
    """logger 와 그 모든 handler 에 filter 부착 (이중 가드).

    streamlit 자식 logger 는 `propagate=False` 라 부모/root 의 filter 가
    호출되지 않으므로 자식 logger 자체에 부착이 필수. handler 에도 부착해
    streamlit 이 나중에 새 handler 를 추가하는 변종 대비.
    """
    logger.addFilter(_FRAGMENT_NOISE_FILTER)
    for h in logger.handlers:
        h.addFilter(_FRAGMENT_NOISE_FILTER)


# 명시적으로 알려진 streamlit logger 모두 가드.
#   - 실제 메시지 출처: streamlit/runtime/scriptrunner/script_runner.py:643
#     → logger 이름 = "streamlit.runtime.scriptrunner.script_runner"
#   - 자식 logger 는 propagate=False (streamlit/logger.py) 라 부모 filter
#     호출 안 됨 — 자식 이름 직접 등록 필수.
#   - 보조: app_session.py 의 유사 메시지(향후 추가될 변종 대비).
for _name in (
    "streamlit",
    "streamlit.runtime",
    "streamlit.runtime.scriptrunner",
    "streamlit.runtime.scriptrunner.script_runner",  # 메시지 실제 출처
    "streamlit.runtime.fragment",
    "streamlit.runtime.app_session",                 # 유사 메시지 보조
):
    _attach_fragment_noise_filter(logging.getLogger(_name))

# root 로거 + 핸들러 — propagate=False 우회는 못 막지만 향후 propagate=True
# 변종 또는 root 직접 출력 케이스 대비.
_attach_fragment_noise_filter(logging.getLogger())

# 방어적 sweep — 이미 생성된 모든 streamlit.* logger 에 일괄 부착.
# (logger 는 첫 get_logger 호출 시점 생성 — app.py import 직후 sweep 으로
#  현 시점의 logger 모두 처리. 명시 등록과 병행해 누락 위험 최소화.)
for _name, _lg in list(logging.Logger.manager.loggerDict.items()):
    if isinstance(_lg, logging.Logger) and _name.startswith("streamlit"):
        _attach_fragment_noise_filter(_lg)

from calendar import monthrange
from datetime import date, timedelta

import streamlit as st
import pandas as pd

import config

# ──────────────────────────────────────────────────────────────────
#  PDF 정적 서버 (Build 2.0, 2026-05-15)
#  -----------------------------------------------------------------
#  streamlit 의 /app/static/ 1GB hard limit 우회 — port 8766 localhost-only
#  데몬 스레드. data_well_card/(1.3GB) + data_drilling_log/(147MB) + 미래 자료
#  무제한 서빙. start_once() 가 hot-reload 중복 시작 방지 + 800MB 초과 경고.
# ──────────────────────────────────────────────────────────────────
from src.dashboard import pdf_server
pdf_server.start_once()

from src.collectors import asos_collector
from src.analysis import period_calculator, watershed_mapper, effective_rainfall
from src.dashboard import theme
from src.dashboard.tabs import (
    tab01_overview,
    tab02_watershed,
    tab03_rainfall,
    tab04_gwlevel,
    # tab99_admin,  # 외부 공개판: gitignore로 제외 (관리자 전용)
    tab05_map,
    tab11_ag_search,
    tab12_ag_usage,
    tab13_ag_quality,
    tab23_ag_usage_map,
    tab21_ag_stats,
    tab22_ag_usage_detail,
    # ── 드론영상 그룹 (31~35) — 2026-05-23 tab31_drone_viewer 분할 ──
    # tab31_drone_overview,  # ── M3 lazy: import 시점을 with tabs[N]: 블록 안으로 이동
    # tab32_drone_2d,  # ── M3 lazy: import 시점을 with tabs[N]: 블록 안으로 이동
    # tab33_drone_3d,  # ── M3 lazy: import 시점을 with tabs[N]: 블록 안으로 이동
    # tab34_drone_diff,  # ── M3 lazy: import 시점을 with tabs[N]: 블록 안으로 이동
    # tab35_drone_diff_3d,  # ── M3 lazy: import 시점을 with tabs[N]: 블록 안으로 이동
    # ── 농업통계 그룹 (41~50) — 2026-05-25 ──
    tab41_population,
    tab42_farm_household,
    tab43_greenhouse,
)


# ==============================================================================
#  페이지 설정
# ==============================================================================
# ──────────────────────────────────────────────────────────────────────
#  favicon — 사용자 요청 (2026-05-16): taskbar/title-bar 아이콘을
#  jeju_groundwater_dashboard.ico 로 통일.
#
#  메커니즘 (사용자 질문 답):
#    1) streamlit 시작 시 PIL.Image.open() 으로 .ico 파일을 한 번 메모리에
#       로드. 이후 매 페이지 로드마다 외부 URL 을 호출하지 않음.
#    2) streamlit 이 PIL.Image 를 base64 PNG 로 변환해 HTML <head> 안에
#       <link rel="icon" href="data:image/png;base64,..."> 형태로 inline 주입.
#    3) Edge 가 favicon 을 받아 캐시 → Edge --app 모드의 taskbar 아이콘으로
#       사용. taskbar 가 favicon 의 단일 해상도만 보고 자체 upscale 하므로
#       원본이 클수록 (256x256) 흐림 없음.
#
#  해상도 개선 (2026-05-16 v2):
#    .ico 안의 가장 큰 frame (256x256) 을 명시적으로 선택해 streamlit 의
#    inline favicon 도 256x256 로 인코딩되도록 보장. RGBA 모드 강제.
# ──────────────────────────────────────────────────────────────────────
_ICON_PATH = Path(__file__).resolve().parents[2] / "jeju_groundwater_dashboard.ico"
try:
    from PIL import Image  # Pillow — streamlit 가 이미 의존성으로 포함
    if _ICON_PATH.exists():
        _img = Image.open(_ICON_PATH)
        # .ico 는 multi-frame container — 가장 큰 frame 강제 선택
        if hasattr(_img, "ico"):
            _sizes = _img.ico.sizes()
            if _sizes:
                _largest = max(_sizes, key=lambda s: s[0] * s[1])
                if _img.size != _largest:
                    _img.size = _largest
                    _img.load()
        # RGBA 보장 — streamlit 의 PNG 인코딩이 alpha 채널 처리하도록
        if _img.mode != "RGBA":
            _img = _img.convert("RGBA")
        _PAGE_ICON = _img
    else:
        _PAGE_ICON = "💧"
except Exception:  # noqa: BLE001
    _PAGE_ICON = "💧"

st.set_page_config(
    # 사용자 요청 (2026-05-16): 윈도우 chrome 타이틀바 가독성 개선.
    # OS 폰트·배경색은 변경 불가 → 텍스트 내용 최적화로 가독성 확보.
    #   - "JeJu" 영문 대소문자 혼합 → 한글 사이에서 시각적 anchor
    #   - 가운데점(·) 으로 '관리' / '분석' 두 핵심 기능 분리
    #   - page_icon: .ico 파일 우선, 실패 시 💧 폴백.
    page_title="JeJu 농업용 지하수 관리·분석",
    page_icon=_PAGE_ICON,
    layout="wide",
    initial_sidebar_state="collapsed",   # 사이드바 숨김
)

# 공통 CSS (사이드바 완전 숨김 포함)
# 사용자 요청 2026-05-10: 이전 _theme_applied 가드(세션당 1회 주입)는
# rerun 시 streamlit 이 markdown 자리의 DOM 노드를 빈 element 로 다시 그려
# 모든 커스텀 CSS 가 사라지는 문제(페이지 제목·탭·헤더 숨김 모두 풀림)를
# 일으켰음. 매 rerun 재주입은 30~50ms paint 비용이지만 7KB CSS 는 브라우저
# 캐시되므로 실제 부담 적음. 시각 일관성 우선.
theme.apply_theme()
# ──────────────────────────────────────────────────────────────────────
#  통합 CSS — v18 (2026-05-16)
#  -----------------------------------------------------------------
#  이전 분리된 3개 st.markdown(<style>) 호출(헤더 숨김 / block-container
#  padding 0 / 탭 폭) 을 하나로 통합. 각 호출이 빈 element-container 를
#  만들고 stVerticalBlock 의 flex `gap: 1rem` 이 사이마다 16px 공백을
#  렌더 → "A영역 4줄" 현상의 직접 원인 (사용자 보고 2026-05-16).
#
#  안전망: empty style-only element-container 에 `display: none` 적용 →
#  flex 자식에서 완전히 제외돼 gap 도 사라짐. v17 의 height:0 은 gap
#  차단 불가 (CSS Grid/Flex spec: size 무관 gap 적용).
# ──────────────────────────────────────────────────────────────────────
st.markdown("""
<style>
/* 사이드바 완전 숨김 */
section[data-testid="stSidebar"] { display: none !important; }
[data-testid="collapsedControl"]  { display: none !important; }

/* ─── 최상단 공백 0 처리 ───────────────────────────────────────────
 * Streamlit 의 기본 상단 영역(헤더·툴바·데코·iframe 빈공간)을 모두 제거.
 * .block-container 의 padding-top 이 가장 큰 여백 — 0 으로.
 */
header,
[data-testid="stHeader"],
header[data-testid="stHeader"],
[data-testid="stToolbar"],
[data-testid="stDecoration"] {
    display: none !important;
    visibility: hidden !important;
    height: 0 !important;
    min-height: 0 !important;
}

/* block-container — A=0 (v12 사용자 요청, 완전 0) */
.main > .block-container,
section.main > .block-container,
section[data-testid="stMain"] > .block-container,
[data-testid="stMain"] > .main > .block-container,
[data-testid="stAppViewBlockContainer"],
div[data-testid="stAppViewBlockContainer"],
.main .block-container,
[data-testid="stAppViewContainer"] > .main,
[data-testid="stMain"] .block-container,
section.main > div.block-container {
    padding-top: 0 !important;
    margin-top: 0 !important;
}

/* 모든 상위 wrapper container 의 padding/margin 0 */
html, body, #root,
[data-testid="stApp"],
[data-testid="stAppViewContainer"],
[data-testid="stMain"],
.main,
section.main {
    padding-top: 0 !important;
    margin-top: 0 !important;
}

/* 첫 자식 element 의 위 margin 도 0 */
section.main > div:first-child,
[data-testid="stMain"] > div:first-child,
[data-testid="stAppViewBlockContainer"] > div:first-child,
.block-container > div:first-child,
.block-container > div:first-child > div:first-child {
    margin-top: 0 !important;
    padding-top: 0 !important;
}

/* stTabs container 자체 */
.stTabs,
div[data-testid="stTabs"] {
    margin-top: 0 !important;
    padding-top: 0 !important;
}

/* 빈 components.html iframe 이 height=0 이어도 1px 차지하는 문제 우회 */
iframe[height="0"] { display: block; height: 0 !important; }

/* ─── 탭과 tab-title 사이 공간 — 1rem (사용자 만족 유지) ───────── */
.stTabs [data-baseweb="tab-panel"] {
    padding-top: 1rem !important;
}
.stTabs [data-baseweb="tab-list"] {
    margin-bottom: 0 !important;
    gap: 4px !important;
    max-width: 95% !important;
    margin-left: auto !important;
    margin-right: auto !important;
    justify-content: center !important;
}
.stTabs [data-baseweb="tab-list"] [data-baseweb="tab"] {
    flex: 1 1 0 !important;
    min-width: 0 !important;
    text-align: center !important;
    justify-content: center !important;
    font-size: 15.4px !important;
    padding: 9px 11px !important;
}
/* 그룹 시작점 앞 추가 여백 — 도메인 그룹 시각 분리.
   nth-child 인덱스는 1-based, app.py:tab_names 순서와 일치.
   2026-05-25: tab35(3D 시계열) 추가 → 데이터 관리 16→17 로 shift.
   6  = 11.관정 관리       (기상·지하수 ↔ 지하수시설물)
   9  = 21.이용량 통계     (지하수시설물 ↔ 지하수이용)
   12 = 31.드론영상 현황    (지하수이용 ↔ 드론영상)
   17 = ⚙️ 데이터 관리      (드론영상 ↔ 관리) */
.stTabs [data-baseweb="tab-list"] [data-baseweb="tab"]:nth-child(6),
.stTabs [data-baseweb="tab-list"] [data-baseweb="tab"]:nth-child(9),
.stTabs [data-baseweb="tab-list"] [data-baseweb="tab"]:nth-child(12),
.stTabs [data-baseweb="tab-list"] [data-baseweb="tab"]:nth-child(17),
.stTabs [data-baseweb="tab-list"] [data-baseweb="tab"]:nth-child(20) {
    margin-left: 26px !important;
}
.tab-title {
    margin: 0 0 12px 0 !important;
    padding: 0 !important;
}

/* streamlit RUNNING/로딩 표시 (우측 상단) — 큼직하게 + 강조색 */
[data-testid="stStatusWidget"] {
    transform: scale(1.7) !important;
    transform-origin: top right !important;
    z-index: 1000 !important;
}
[data-testid="stStatusWidget"] svg {
    color: #1976D2 !important;
}

/* ─── A 영역 완전 제거 (v18, 2026-05-16) ─────────────────────────────
 * Module-level st.markdown(<style>) 호출들이 element-container 를 차지
 * → stVerticalBlock 의 flex `gap: 1rem` 이 사이마다 16px 공백 (= "A영역
 * 4줄"). v17 의 height: 0 만으론 gap 차단 불가 — flex/grid spec 상
 * size 와 무관하게 자식 사이마다 gap 그려짐.
 *
 * 해결 (v18): display: none 으로 flex 자식에서 완전히 제외 → gap 도
 * 사라짐. visible content 있으면 :not(:has(...)) 로 매칭 안 됨 → 영향 0.
 *
 * 안전성:
 *  - JS 없음 (v8~v14 회귀 패턴 모두 회피)
 *  - :has() 미지원 브라우저는 silent fail (변경 전과 동일)
 * Edge 105+ (2022.09), Chrome 105+, Safari 15.4+, Firefox 121+ 지원.
 * ──────────────────────────────────────────────────────────────────── */
/* style-only stMarkdown 을 포함하는 element-container 를 layout 에서 제외 */
.element-container:has([data-testid="stMarkdown"]:has(style):not(:has(p, h1, h2, h3, h4, h5, h6, span, table, img, svg, button, code, pre, ul, ol, hr, blockquote, a))) {
    display: none !important;
}
/* 빈 components.html iframe wrapper element-container 도 layout 에서 제외 */
.element-container:has(iframe[height="0"]) {
    display: none !important;
}
</style>
""", unsafe_allow_html=True)


# ==============================================================================
#  데이터 로드 (캐싱)
# ==============================================================================
def load_asos_cached():
    # decorator 제거 — asos_collector.load_asos_data 자체가 캐시됨. wrapper 별
    # 캐시가 따로 있으면 wrapper 마다 다른 객체가 반환되어 hash_funcs={DF:id}
    # 캐시가 wrapper 수만큼 분리되던 문제를 해결.
    return asos_collector.load_asos_data()

@st.cache_data(ttl=300)
def load_watersheds_cached():
    return watershed_mapper.load_watershed_data()


# 사용자 요청 2026-05-09: 매 rerun 마다 compute_gwlevel_diff_dict 가 재계산
# (30 유역 × 3 기간) → 탭 전환 시 체감 지연. wrapper 로 5분 캐시.
# DataFrame value 는 id 기반 hash (load_watersheds_cached 가 같은 객체 반환).
@st.cache_data(ttl=600, show_spinner=False,
               hash_funcs={pd.DataFrame: id})
def _cached_gwlevel_diff_dict(ws_data_all: dict, periods: dict,
                              n_years: int) -> dict:
    return watershed_mapper.compute_gwlevel_diff_dict(
        ws_data_all, periods, n_years
    )


@st.cache_data(ttl=600, show_spinner=False)
def _build_gw_summary_df(gwlevel_diff_dict: dict, periods: dict,
                        n_years: int) -> "pd.DataFrame":
    """gwlevel_diff_dict → tab99_admin wide-format DataFrame.

    매 rerun 마다 반복 변환되던 로직을 캐시 함수로 분리 (사용자 요청 2026-05-09).
    """
    rows = []
    for pk in ["M-2", "M-1", "M"]:
        if pk not in periods:
            continue
        p = periods[pk]
        bl = list(range(p["year"] - n_years, p["year"]))
        row = {"기간": pk, "연월": p["label"],
               "기준연도": f"{bl[0]}~{bl[-1]}"}
        for w_info in config.WATERSHEDS:
            wn = w_info["name"]
            rec = gwlevel_diff_dict.get(wn, {}).get(pk)
            row[f"{wn}_실측"] = rec["실측"] if rec else None
            row[f"{wn}_평균"] = rec["평균"] if rec else None
        rows.append(row)
    return pd.DataFrame(rows)


# ==============================================================================
#  세션 상태 / 데이터 / 기간 (헤더·탭 출력 이전에 미리 준비)
# ==============================================================================
# 🆕 (2026-06-01) Default 기준일 = 오늘이 속한 달의 1일.
#   예: 오늘이 2026-06-15 → DEFAULT_BASE_DATE = 2026-06-01.
#   기존엔 고정값(2026-02-01)이었으나, 시간이 흐르면 stale 해지므로 동적 계산.
_today = date.today()
DEFAULT_BASE_DATE = date(_today.year, _today.month, 1)
if "base_date" not in st.session_state:
    st.session_state["base_date"] = DEFAULT_BASE_DATE
if "report_requested" not in st.session_state:
    st.session_state["report_requested"] = False

asos_df     = load_asos_cached()
ws_data_all = load_watersheds_cached()

BASE_DATE = st.session_state["base_date"]
periods   = period_calculator.compute_periods(base_date=BASE_DATE)


# ==============================================================================
#  헤더 1행 — 제목 (단독)
#  -------------------------------------------------------------------
#  v1.2.x: 메인 제목을 탭 서브헤더(st.subheader, ~28px) 크기·스타일로
#  키움. 탭별 서브헤더는 22px 로 축소(아래 탭 5~8 참조) — 제목·서브
#  헤더의 시각적 위계를 정상화.
# ==============================================================================
def _shutdown_and_exit() -> None:
    """전역 Quit 버튼 핸들러 — 브라우저 안내 + delayed os._exit.

    이전 버전 (2026-05-16) 의 문제:
      ① return  # 외부 공개판: os._exit 비활성 (2026-06-01) 즉시 호출 → streamlit 이 클라이언트에 응답 못 보냄
         → 브라우저에 'Connection error' 다이얼로그 표시
      ② 브라우저 탭 자체는 streamlit 이 닫을 권한 없음 (보안 제약)
      ③ 사용자가 새 streamlit 띄우면 이전 탭이 같은 URL 로 자동 재연결
         → 새 streamlit 페이지를 받아 헤더가 두 번 노출되는 부작용

    재설계 (2026-05-16 v2):
      1) 페이지 본체를 "종료됨" 메시지로 교체 (Connection error 위에 노출)
      2) components.html JS 로 window.close() 시도 (autoOpen 탭이면 성공)
      3) 실패 시 about:blank 로 redirect (Connection error 회피)
      4) 별도 thread 에서 0.8s 후 os._exit (응답 전송 시간 확보)
    """
    import threading
    import time as _time
    import streamlit.components.v1 as _components

    # 1) 종료 메시지 + Connection error 다이얼로그 차단 CSS.
    #    streamlit 의 disconnect 위젯·modal·alertdialog 를 CSS 로 즉시 숨김.
    #    이전 (2026-05-16 v2) 의 about:blank fallback 만으로는 components
    #    iframe sandbox 의 top-navigation 제약 때문에 다이얼로그가 그대로
    #    노출되는 문제 발생 → CSS + MutationObserver 3중 보호로 강화.
    st.markdown(
        '<style>'
        'section[data-testid="stConnectionStatus"],'
        '[data-testid="stStatusWidget"],'
        'div[data-baseweb="modal"],'
        'div[role="alertdialog"],'
        'div[role="dialog"] { display: none !important; }'
        '</style>'
        '<div style="text-align:center;padding:120px 20px;">'
        '<h1 style="font-size:32px;margin:0 0 16px;color:#1a1a18;">'
        '🛑 대시보드를 종료했습니다</h1>'
        '<p style="font-size:17px;color:#666;line-height:1.6;">'
        '이 탭은 자동으로 닫힙니다.<br/>'
        '닫히지 않으면 직접 닫아주세요. (<kbd>Ctrl</kbd>+<kbd>W</kbd> '
        '또는 탭 우측 상단 ×)</p>'
        '</div>',
        unsafe_allow_html=True,
    )

    # 2) JS 3중 보호:
    #    (a) parent (streamlit main page) 의 다이얼로그 즉시 제거
    #    (b) MutationObserver 로 새로 추가되는 다이얼로그 자동 제거
    #    (c) window.close → parent.location.replace('about:blank') 시도
    _components.html(
        """
        <script>
            (function() {
                var DIALOG_SEL = 'section[data-testid="stConnectionStatus"],'
                    + '[data-testid="stStatusWidget"],'
                    + 'div[data-baseweb="modal"],'
                    + 'div[role="alertdialog"],'
                    + 'div[role="dialog"]';

                // (a)(b) parent document 의 다이얼로그 차단 (즉시 + observer)
                try {
                    var pdoc = window.parent.document;
                    var nuke = function() {
                        pdoc.querySelectorAll(DIALOG_SEL).forEach(function(el) {
                            try { el.remove(); } catch (e) {}
                        });
                    };
                    nuke();
                    var obs = new window.parent.MutationObserver(nuke);
                    obs.observe(pdoc.body, { childList: true, subtree: true });
                } catch (e) {}

                // (c) 100ms 후 window.close → 실패 시 200ms 더 후 about:blank
                setTimeout(function() {
                    try { window.parent.close(); } catch (e) {}
                    try { window.close(); } catch (e) {}
                    setTimeout(function() {
                        try {
                            if (window.parent && !window.parent.closed) {
                                window.parent.location.replace('about:blank');
                            }
                        } catch (e) {
                            try { window.top.location.replace('about:blank'); }
                            catch (e2) {}
                        }
                    }, 200);
                }, 100);
            })();
        </script>
        """,
        height=0,
    )

    # 3) 별도 thread 에서 1.2s 후 종료. CSS/JS 다이얼로그 차단 + redirect
    #    가 클라이언트에 도착할 시간 충분히 확보. pdf_server 데몬 정리.
    def _delayed_exit() -> None:
        _time.sleep(1.2)
        try:
            from src.dashboard import pdf_server
            pdf_server._shutdown()
        except Exception:  # noqa: BLE001
            pass
        return  # 외부 공개판: os._exit 비활성 (2026-06-01)

    threading.Thread(target=_delayed_exit, daemon=True).start()

    # 4) 현재 rerun 사이클은 종료 메시지만 표시하고 중단 (다른 위젯 렌더 X)
    st.stop()


# ==============================================================================
#  탭 navigation (페이지 최상단)
#  -----------------------------------------------------------------------------
#  v18 (2026-05-16): 페이지 상단 헤더 + 탭 CSS 를 module-level 통합 CSS
#  블록(line 145)으로 이동. 빈 element-container 분리에 따른 flex gap
#  공백 ("A영역 4줄") 제거.
#
#  v13 (2026-05-16) JS 회귀 사고 기록:
#    forceZero JS + MutationObserver 가 streamlit-folium 의 Leaflet 마커
#    DOM mutation 마다 호출 → 페이지 freeze → WebSocket backlog → 지도 3분
#    대기. JS 완전 제거 후 CSS-only 처리로 모든 회귀 해결.
# ==============================================================================
# 사용자 요청 (2026-05-16): 탭 제목 1~10 + 데이터 관리.
# 사용자 요청 (2026-05-23): tab31 "드론 영상" 5번째 그룹 첫 탭 — ⚙️ 데이터 관리 앞에 삽입.
# 사용자 요청 (2026-05-23): 탭 번호 그룹 체계로 전면 재편 — 기상·지하수(01~05) /
#   지하수시설물(11~13) / 지하수이용(21~23) / 드론영상(31) / 데이터 관리.
tab_names = [
    # ── 기상·지하수 그룹 (01~05) ──
    "01.대시보드 요약",
    "02.유역별 현황",
    "03.강수량",
    "04.지하수위",
    "05.관측소 분석",
    # ── 지하수시설물 그룹 (11~13) ──
    "11.관정 관리",
    "12.이용량 분석",
    "13.수질 분석",
    # ── 지하수이용 그룹 (21~23) ──
    "21.이용량 통계",
    "22.이용량 경향분석",
    "23.이용량 공간분석",
    # ── 드론영상 그룹 (31~35) ──
    "31.드론영상 현황",
    "32.정사영상 분석",
    "33.3D영상 분석",
    "34.시계열 분석(2D)",
    "35.시계열 분석(3D)",
    # ── 관리 (그룹 외) ──
    # ── 농업통계 그룹 (41~50) ──
    "41.농가현황",
    "42.농경지현황",
    "43.시설재배현황",
    # ── 관리 (그룹 외) ──
    "⚙️ 데이터 관리",
]
# 탭 폭/정렬 CSS 는 line 145 통합 블록(v18)으로 이동.
# Streamlit 1.49+ 에서 st.tabs 가 key 인자를 지원하면 selected_index 가
# session_state["main_tabs"] 에 보존되어 full rerun 후에도 활성 탭 유지.
# 미지원 버전(< 1.49)에서는 TypeError 가 나므로 try/except 로 폴백.
try:
    tabs = st.tabs(tab_names, key="main_tabs")
except TypeError:
    tabs = st.tabs(tab_names)

# ==============================================================================
#  Quit 버튼 — 탭별로 다른 위치 (사용자 요청 2026-05-16 v5)
# ------------------------------------------------------------------------------
#  설계:
#    - 01~05 탭 (기상·지하수, period_controls 있음): 분석 버튼 옆 sub[4] 에 Quit
#    - 11~13, 21~23, 31 탭 (period_controls 없음): 각 탭 모듈의 tab-title 우측에 Quit
#      (각 모듈에서 st.session_state["_quit_requested"]=True 트리거)
#  app.py 의 module-level 첫 부분에서 _quit_requested 감지 후 shutdown 실행.
# ==============================================================================

# 각 탭 모듈에서 Quit 버튼 클릭 시 session_state["_quit_requested"]=True 설정.
# 그 rerun 사이클의 이 module-level 코드에서 감지해 즉시 shutdown.
if st.session_state.get("_quit_requested"):
    st.session_state["_quit_requested"] = False
    _shutdown_and_exit()


# ==============================================================================
#  분석기간 컨트롤 + 과거 수위자료 안내 (탭 01~05 전용)
#  -------------------------------------------------------------------
#  Streamlit 의 st.tabs 는 모든 탭의 with-블록을 매 렌더마다 실행한다.
#  같은 widget key 를 5번 만들면 DuplicateWidgetID 에러 → 탭별 suffix 로 회피.
#  selectbox 의 default index 는 매번 session_state["base_date"] 에서 동기화 →
#  탭을 옮겨다녀도 값이 일치한다. 분석 버튼 클릭 시에만 base_date 갱신.
# ==============================================================================
def _build_badge_html(periods: dict) -> str:
    html = (
        '<div style="display:flex;align-items:center;gap:8px;flex-wrap:wrap;'
        'margin-top:2px;">'
    )
    for key in ["M-2", "M-1", "M"]:
        p = periods[key]
        is_m = (key == "M")
        bg = theme.COLOR_TEXT_INFO if is_m else theme.COLOR_BG_SECONDARY
        fg = "#ffffff" if is_m else theme.COLOR_TEXT_SECONDARY
        bd = theme.COLOR_TEXT_INFO if is_m else "rgba(26,26,24,0.3)"
        is_half = (periods.get("mode") == "half")
        tip = (
            "비교 기준 연도는 각 기간(M-2·M-1·M)별로 독립 적용. "
            "기간 열에 해당 기준 연도가 표시됩니다."
            + (" / M 기간 평균 ×½ 적용" if (is_m and is_half) else "")
        )
        html += (
            f'<span title="{tip}" '
            f'style="display:inline-flex;flex-direction:column;align-items:center;'
            f'justify-content:center;padding:4px 12px;border-radius:8px;gap:1px;'
            f'min-width:130px;border:0.5px solid {bd};background:{bg};">'
            f'<span style="font-size:16px;font-weight:500;color:{fg};'
            f'line-height:1.15;">{p["label"]}</span>'
            f'<span style="font-size:10px;font-weight:500;color:{fg};'
            f'line-height:1.15;">({key})</span>'
            f'</span>'
        )
    html += '</div>'
    return html


def render_period_controls(suffix: str) -> None:
    """탭 01~05 콘텐츠 첫 줄 — 분석기간 배지(좌) + 날짜 + 분석 + Quit (우).

    suffix : 탭 식별자(t0~t4). 위젯 key 충돌 방지용.
    """
    cols = st.columns([1.4, 1.6])
    with cols[0]:
        st.markdown(_build_badge_html(periods), unsafe_allow_html=True)
    with cols[1]:
        cur = st.session_state["base_date"]
        # 사용자 요청 2026-05-09: 올해부터 표시 (최근 → 과거 역순)
        _this_year = date.today().year
        year_opts  = list(range(_this_year, 2009, -1))
        month_opts = list(range(1, 13))
        day_opts   = list(range(1, 32))
        # 사용자 요청 (2026-05-16 v4): 1~5 탭 (period_controls 있음) 에서
        # Quit 버튼을 분석 버튼 오른쪽 sub[4] 에 배치. 6~11 탭은 별도 헬퍼
        # _render_tab_quit() 가 with tabs[i] 시작 부분에 표시.
        sub = st.columns([1.0, 0.8, 0.8, 1.2, 0.9])
        with sub[0]:
            year = st.selectbox(
                "연도", year_opts,
                index=year_opts.index(cur.year)
                if cur.year in year_opts else len(year_opts) - 1,
                key=f"by_{suffix}", label_visibility="collapsed",
                format_func=lambda y: f"{y}년",
            )
        with sub[1]:
            month = st.selectbox(
                "월", month_opts, index=cur.month - 1,
                key=f"bm_{suffix}", label_visibility="collapsed",
                format_func=lambda m: f"{m}월",
            )
        with sub[2]:
            day = st.selectbox(
                "일", day_opts, index=min(cur.day - 1, 30),
                key=f"bd_{suffix}", label_visibility="collapsed",
                format_func=lambda d: f"{d}일",
            )
        with sub[3]:
            if st.button("분석 ↗", type="primary",
                         use_container_width=True, key=f"go_{suffix}"):
                max_d = monthrange(year, month)[1]
                st.session_state["base_date"] = date(year, month, min(day, max_d))
                st.rerun()
        with sub[4]:
            # 외부 공개판 보안 패치 (2026-06-01): 누구나 클릭해
            # 서버를 다운시킬 수 없도록 Quit 버튼 미표시.
            st.empty()
    st.markdown(
        '<hr style="margin:6px 0 10px;border:none;'
        'border-top:0.5px solid rgba(26,26,24,0.15);">',
        unsafe_allow_html=True
    )


def _earliest_gw_ym(ws_data: dict) -> str | None:
    earliest = None
    for df_w in (ws_data or {}).values():
        if df_w is None or df_w.empty or "연월" not in df_w.columns:
            continue
        ym_min = df_w["연월"].dropna().min()
        if ym_min and (earliest is None or ym_min < earliest):
            earliest = ym_min
    return earliest


def render_gw_warning() -> None:
    """과거 수위자료 누락 안내 (지하수위 비교 baseline 부족 시)."""
    earliest = _earliest_gw_ym(ws_data_all)
    if not earliest:
        return
    n_gw = config.GWLEVEL_BASELINE_YEARS
    missing = []
    for pk in ["M-2", "M-1", "M"]:
        p = periods[pk]
        bl_first_ym = f"{p['year'] - n_gw}-{p['month']:02d}"
        if bl_first_ym < earliest:
            missing.append(f"{pk}({p['year']-n_gw}~{p['year']-1}년 {p['month']}월)")
    if missing:
        st.markdown(
            f'<div style="margin:0 0 8px;padding:8px 12px;border-radius:6px;'
            f'background:#fdecea;border-left:3px solid var(--color-danger);'
            f'font-size:12px;color:var(--color-text-secondary);">'
            f'⚠️ 과거 수위자료 없음 — 보유 수위자료 시작: <b>{earliest}</b>. '
            f'다음 기간의 비교 기준연도가 보유 범위를 벗어납니다: '
            f'<b>{", ".join(missing)}</b>. '
            f'해당 기간의 과거 평균·편차는 "–" 로 표시됩니다.'
            f'</div>',
            unsafe_allow_html=True
        )


# ------------------------------------------------------------------
# 공통 데이터 준비 (모든 탭 공유)
# ------------------------------------------------------------------
rainfall_table = None
eff_table      = None
gw_summary_df  = None

if not asos_df.empty:
    rainfall_table = effective_rainfall.build_comparison_table(
        asos_df, periods, metric="월강수량(mm)"
    )
    eff_table = effective_rainfall.build_comparison_table(
        asos_df, periods, metric="유효강수일수(일)"
    )

# 유역 × 기간 (실측·평균·편차) dict — 단일 진실 원천. tab0 도 같은 dict 사용.
gwlevel_diff_dict: dict = {}
if ws_data_all:
    gwlevel_diff_dict = _cached_gwlevel_diff_dict(
        ws_data_all, periods, n_years=config.GWLEVEL_BASELINE_YEARS,
    )
    # 위 dict 를 tab99_admin 이 받는 wide-format DataFrame 으로 변환 (캐시).
    gw_summary_df = _build_gw_summary_df(
        gwlevel_diff_dict, periods, config.GWLEVEL_BASELINE_YEARS,
    )


# ------------------------------------------------------------------
# 각 탭 렌더링
#  - 탭 0~4 (자원 모니터링): 분석기간 컨트롤 + 수위자료 경고 + 콘텐츠
#  - 탭 5~9 (사후관리·데이터): 컨트롤 없이 콘텐츠만
#
# (#7 활성 탭 게이팅 시도 v14 롤백 2026-05-16):
#   v14 의 location.reload() 트리거가 streamlit 전체 재부팅을 야기 →
#   첫 진입 비용 (cache 워밍, 데이터 로드, folium iframe 그리기) 매 탭
#   전환마다 발생 → 1분+ 대기 + 깜박임 회귀. 즉시 롤백.
#   2026-05-11 의 history.replaceState() 시도도 회귀로 롤백된 바 있음 →
#   탭 게이팅은 streamlit 1.47.1 의 구조적 한계로 현재 적용 불가.
#   효과 포기 + 안정성 우선 — 모든 탭 매 rerun 마다 render().
# ------------------------------------------------------------------
with tabs[0]:
    render_period_controls("t0")
    render_gw_warning()
    tab01_overview.render(
        asos_df, ws_data_all, periods,
        gwlevel_diff_dict=gwlevel_diff_dict,
    )

with tabs[1]:
    render_period_controls("t1")
    render_gw_warning()
    tab02_watershed.render(
        asos_df, ws_data_all, periods,
        gwlevel_diff_dict=gwlevel_diff_dict,   # SSOT (2026-05-28 P2-4)
    )

with tabs[2]:
    render_period_controls("t2")
    render_gw_warning()
    tab03_rainfall.render(asos_df, periods)

with tabs[3]:
    render_period_controls("t3")
    render_gw_warning()
    tab04_gwlevel.render(ws_data_all, periods, asos_df=asos_df)

with tabs[4]:
    render_period_controls("t4")
    render_gw_warning()
    tab05_map.render(asos_df, periods, base_date=BASE_DATE)

with tabs[5]:
    tab11_ag_search.render()

with tabs[6]:
    tab12_ag_usage.render()

with tabs[7]:
    # 13. 수질 분석
    tab13_ag_quality.render()

with tabs[8]:
    # 21. 이용량 통계
    tab21_ag_stats.render(asos_df=asos_df)

with tabs[9]:
    # 22. 이용량 경향분석
    tab22_ag_usage_detail.render(asos_df=asos_df, periods=periods)

with tabs[10]:
    # 23. 이용량 공간분석 (구 ⑧-2, 행정구역 choropleth)
    tab23_ag_usage_map.render()

with tabs[11]:
    # 31.드론영상 현황
    # D2+D3 fix 2026-05-30: lazy import + try/except 격리 + alias 제거.
    # 이 탭 fail 해도 다른 탭(tab32~99) 동반 다운 차단 — 사용자 보고 8팀 권고.
    try:
        from src.dashboard.tabs import tab31_drone_overview
        tab31_drone_overview.render()
    except Exception as e:  # noqa: BLE001
        import traceback as _tb
        st.error(f"❌ 31.드론영상 현황 로드 실패: {type(e).__name__}: {e}")
        with st.expander("상세 traceback (운영자용)"):
            st.code(_tb.format_exc(), language="python")

with tabs[12]:
    # 32.정사영상 분석
    # D2+D3 fix 2026-05-30: lazy import + try/except 격리 + alias 제거.
    # 이 탭 fail 해도 다른 탭(tab32~99) 동반 다운 차단 — 사용자 보고 8팀 권고.
    try:
        from src.dashboard.tabs import tab32_drone_2d
        tab32_drone_2d.render()
    except Exception as e:  # noqa: BLE001
        import traceback as _tb
        st.error(f"❌ 32.정사영상 분석 로드 실패: {type(e).__name__}: {e}")
        with st.expander("상세 traceback (운영자용)"):
            st.code(_tb.format_exc(), language="python")

with tabs[13]:
    # 33.3D영상 분석
    # D2+D3 fix 2026-05-30: lazy import + try/except 격리 + alias 제거.
    # 이 탭 fail 해도 다른 탭(tab32~99) 동반 다운 차단 — 사용자 보고 8팀 권고.
    try:
        from src.dashboard.tabs import tab33_drone_3d
        tab33_drone_3d.render()
    except Exception as e:  # noqa: BLE001
        import traceback as _tb
        st.error(f"❌ 33.3D영상 분석 로드 실패: {type(e).__name__}: {e}")
        with st.expander("상세 traceback (운영자용)"):
            st.code(_tb.format_exc(), language="python")

with tabs[14]:
    # 34.시계열 분석(2D)
    # D2+D3 fix 2026-05-30: lazy import + try/except 격리 + alias 제거.
    # 이 탭 fail 해도 다른 탭(tab32~99) 동반 다운 차단 — 사용자 보고 8팀 권고.
    try:
        from src.dashboard.tabs import tab34_drone_diff
        tab34_drone_diff.render()
    except Exception as e:  # noqa: BLE001
        import traceback as _tb
        st.error(f"❌ 34.시계열 분석(2D) 로드 실패: {type(e).__name__}: {e}")
        with st.expander("상세 traceback (운영자용)"):
            st.code(_tb.format_exc(), language="python")

with tabs[15]:
    # 35.시계열 분석(3D)
    # D2+D3 fix 2026-05-30: lazy import + try/except 격리 + alias 제거.
    # 이 탭 fail 해도 다른 탭(tab32~99) 동반 다운 차단 — 사용자 보고 8팀 권고.
    try:
        from src.dashboard.tabs import tab35_drone_diff_3d
        tab35_drone_diff_3d.render()
    except Exception as e:  # noqa: BLE001
        import traceback as _tb
        st.error(f"❌ 35.시계열 분석(3D) 로드 실패: {type(e).__name__}: {e}")
        with st.expander("상세 traceback (운영자용)"):
            st.code(_tb.format_exc(), language="python")

# ── 농업통계 그룹 (41~50) — 2026-05-25 ──
with tabs[16]:
    tab41_population.render()

with tabs[17]:
    tab42_farm_household.render()

with tabs[18]:
    tab43_greenhouse.render()

with tabs[19]:
    # 외부 공개판: tab99_admin (관리자 데이터 관리) 비활성
    try:
        from src.dashboard.tabs import tab99_admin
        tab99_admin.render(
        asos_df, ws_data_all, periods,
        rainfall_table=rainfall_table,
        eff_table=eff_table,
        gw_summary_df=gw_summary_df,
    )
    except ImportError:
        st.info("⚠️ 데이터 관리 탭은 운영자 전용 환경에서만 표시됩니다.")
# tab11 마커 실험 탭은 사용자 요청으로 삭제 (2026-05-09).


# ==============================================================================
#  탭 선택 상태 보존 (Streamlit st.tabs 한계 우회)
#  -------------------------------------------------------------------
#  st.button() 클릭 → Streamlit auto-rerun → st.tabs() 가 첫 탭으로 초기화되는
#  알려진 한계. 브라우저 sessionStorage 에 마지막 활성 탭 인덱스를 저장하고
#  rerun 후 자동 복원한다. sessionStorage 라 새 탭/창은 항상 첫 탭으로 시작.
# ==============================================================================
import streamlit.components.v1 as _components
_components.html("""
<script>
(function() {
  // ────────────────────────────────────────────────────────────────────
  //  탭 활성 인덱스 보존 (Streamlit st.tabs 한계 우회 — Build 1.2.11)
  //  -------------------------------------------------------------------
  //  문제: 탭 안에서 button/selectbox/slider/map-click 으로 rerun 이
  //        발생하면 Streamlit 이 자주 탭 0(대시보드 요약)으로 되돌린다.
  //
  //  Build 1.2.11 강화점:
  //   - 페이지 첫 로드 시 saved>0 이면 .stTabs 자체를 잠깐 visibility:hidden
  //     처리 → 0번 탭이 깜박이는 것을 사용자가 보지 못하게 함.
  //   - 폴링 50ms × 12s — 첫 마운트, fragment rerun, st_folium height
  //     change 등 모든 케이스에서 즉시 복원.
  //   - capture-phase click 으로 가장 먼저 sessionStorage 갱신.
  //   - MutationObserver 로 「프로그램적 0번 reset」도 감지해 재복원.
  // ────────────────────────────────────────────────────────────────────
  // v4: 2026-05-25 tab35 (시계열 분석 3D) 추가. 탭 총 개수 16→17 으로 변경,
  //     데이터 관리 탭 인덱스가 15→16 으로 이동. v3 sessionStorage 값 폐기.
  // v3: 2026-05-23 드론 31번 → 31/32/33/34 4개 탭으로 분할. 탭 총 개수 13→16
  //     으로 변경, 데이터 관리 탭 인덱스가 12→15 로 이동. 기존 v2 sessionStorage
  //     값을 폐기시키기 위해 v3 으로 bump. 사용자 첫 진입 시 1번 탭에서 시작.
  // v2: 2026-05-23 탭 번호 재편 (1~10 → 01~05/11~13/21~23/31) 후 인덱스 의미 변경.
  const KEY = 'jeju-gw-active-tab-idx-v6';
  const doc = window.parent.document;
  const ss = window.parent.sessionStorage;

  function getTabsRoot() {
    return doc.querySelector('.stTabs');
  }
  function getTabs() {
    return doc.querySelectorAll('.stTabs [data-baseweb="tab-list"] [data-baseweb="tab"]');
  }
  function getActiveIdx(tabs) {
    return Array.from(tabs).findIndex(
      t => t.getAttribute('aria-selected') === 'true'
    );
  }
  function getSavedIdx() {
    const v = ss.getItem(KEY);
    if (v === null) return -1;
    const n = parseInt(v, 10);
    return Number.isFinite(n) ? n : -1;
  }
  // saveIdx — sessionStorage + URL query 동기 저장. URL 은 replaceState 라
  // rerun trigger 안 함. Python 측은 다음 rerun 에 query_params 에서 읽어
  // 활성 탭만 render() — 무거운 탭(tab10 등) 의 비활성 시 호출 차단 (L1 P0).
  function saveIdx(idx) {
    ss.setItem(KEY, String(idx));
    try {
      const url = new URL(window.parent.location);
      if (url.searchParams.get('t') !== String(idx)) {
        url.searchParams.set('t', String(idx));
        window.parent.history.replaceState(null, '', url);
      }
    } catch (e) { /* cross-origin 등 안전 무시 */ }
  }

  // ── 첫 로드 시 잠시 hide (saved 가 0번이 아니면 깜박임 방지)
  let firstHidden = false;
  function hideTabs() {
    const root = getTabsRoot();
    if (root) { root.style.visibility = 'hidden'; firstHidden = true; }
  }
  function showTabs() {
    if (!firstHidden) return;
    const root = getTabsRoot();
    if (root) { root.style.visibility = 'visible'; firstHidden = false; }
  }

  // ── 첫 페이지 로드 1회만 hideTabs 발동 (Build 1.2.12 가드)
  //  full rerun 마다 이 IIFE 가 재주입 → 매번 hideTabs() 가 발동되면
  //  사용자가 보고 있던 탭이 50~200ms 동안 가려지며 흰 깜박임 발생.
  //  document 의 dataset 에 플래그를 저장하면 페이지 reload(F5) 시 DOM 과
  //  함께 폐기되어 새 첫 로드는 다시 발동, full rerun 에서는 미발동.
  try {
    const root = doc.documentElement;
    if (!root.dataset.jejuFirstLoadDone) {
      if (getSavedIdx() > 0) hideTabs();
      root.dataset.jejuFirstLoadDone = '1';
    }
  } catch (e) { /* cross-origin 등 안전 무시 */ }
  // safety: 1.5초 후엔 무조건 보이기 — 만약 폴링/복원이 실패해도 화면은 표시
  setTimeout(showTabs, 1500);

  // 우리가 click() 으로 일으킨 변경(intentional) vs Streamlit 의 reset(rogue) 구분
  let suppressRogue = false;

  function restore() {
    const tabs = getTabs();
    if (!tabs.length) return false;
    const saved = getSavedIdx();
    if (saved < 0 || saved >= tabs.length) { showTabs(); return false; }
    const active = getActiveIdx(tabs);
    if (saved === active) { showTabs(); return true; }
    suppressRogue = true;
    tabs[saved].click();
    // 250→150ms (회귀 보정 2026-05-12): 250ms 가 사용자 체감 지연.
    // iframe paint 1프레임(16ms) + V-World 첫 청크 평균(~80ms) 마진 두고
    // 150ms 가 안전·응답성 균형. 사용자 인지 한계(~100ms) 근처.
    setTimeout(() => { suppressRogue = false; showTabs(); }, 150);
    return false;
  }

  function attachClickListeners() {
    // 2026-05-23 수정: 개별 탭 노드에 listener 부착 + dataset 가드 방식은
    // rerun 으로 iframe 이 재생성되면 closure 가 dead 상태가 되어
    // sessionStorage 업데이트가 끊긴다. tablist 에 단일 delegate listener
    // 로 변경 + window.parent 에 참조 보관하여 매 rerun 마다 안전 재부착.
    const tablist = doc.querySelector('.stTabs [data-baseweb="tab-list"]');
    if (!tablist) return;
    try {
      if (window.parent._jejuTabClickHandler) {
        tablist.removeEventListener('click', window.parent._jejuTabClickHandler, true);
      }
    } catch (e) { /* */ }
    const handler = (e) => {
      const target = e.target.closest && e.target.closest('[data-baseweb="tab"]');
      if (!target) return;
      const tabs = Array.from(getTabs());
      const idx = tabs.indexOf(target);
      if (idx >= 0) saveIdx(idx);
    };
    tablist.addEventListener('click', handler, true);
    try { window.parent._jejuTabClickHandler = handler; } catch (e) { /* */ }
  }

  function attachObserver() {
    // 2026-05-23 수정: 매 rerun 마다 새 iframe → 이전 observer 의 callback
    // closure 가 GC 됨 (iframe window 사망). 기존 코드는 tablist.dataset
    // 플래그로 재부착을 막아 observer 가 사실상 없는 상태가 되어 32/33
    // 탭의 selectbox rerun 시 0번 탭 reset 을 감지 못함. parent window 에
    // observer 참조 보관 + 매번 disconnect 후 재부착으로 항상 살아있는
    // observer 보장.
    const tablist = doc.querySelector('.stTabs [data-baseweb="tab-list"]');
    if (!tablist) return;
    try {
      if (window.parent._jejuTabObserver) {
        window.parent._jejuTabObserver.disconnect();
      }
    } catch (e) { /* cross-origin 등 안전 무시 */ }
    const obs = new MutationObserver(() => {
      const tabs = getTabs();
      if (!tabs.length) return;
      if (suppressRogue) return;
      const active = getActiveIdx(tabs);
      const saved = getSavedIdx();
      if (active < 0) return;
      if (saved < 0) { saveIdx(active); return; }
      if (active !== saved) restore();
    });
    getTabs().forEach(t => obs.observe(t,
      { attributes: true, attributeFilter: ['aria-selected'] }));
    try { window.parent._jejuTabObserver = obs; } catch (e) { /* */ }
    tablist.dataset.jejuObserver = '1';
  }

  function tick() {
    const tabs = getTabs();
    if (!tabs.length) return false;
    attachClickListeners();
    attachObserver();
    const restored = restore();
    // listener·observer attach 완료 + saved==active 안정 → 폴링 종료 신호.
    // 2026-05-23: delegate listener / parent-window observer 전환 후 가드 갱신.
    const tablist = doc.querySelector('.stTabs [data-baseweb="tab-list"]');
    let obsDone = false, listenersDone = false;
    try {
      obsDone = !!(tablist && tablist.dataset.jejuObserver && window.parent._jejuTabObserver);
      listenersDone = !!(tablist && window.parent._jejuTabClickHandler);
    } catch (e) { /* */ }
    return restored && obsDone && listenersDone;
  }

  tick();
  // 50ms × 4s 폴링 — 첫 성공 tick 에서 즉시 종료 (코딩 에이전트 권장
  // 2026-05-12). 평균 2~4회 만에 안정화. 4s 는 안전망 한도.
  const startTs = Date.now();
  const iv = setInterval(() => {
    if (Date.now() - startTs > 4000) { clearInterval(iv); showTabs(); return; }
    if (tick()) { clearInterval(iv); showTabs(); }
  }, 50);
})();
</script>
""", height=0)


# ==============================================================================
#  푸터
# ==============================================================================
st.markdown(
    f'<div style="margin-top:24px;padding-top:10px;'
    f'border-top:0.5px solid rgba(26,26,24,0.15);'
    f'text-align:center;font-size:10px;color:#888;">'
    f'제주도 농업용 지하수 분석 대시보드 Build {config.BUILD_VERSION} &nbsp;|&nbsp; '
    f'기준일: {BASE_DATE} &nbsp;|&nbsp; '
    f'데이터 출처: 기상청 ASOS / 제주도 지하수정보관리시스템 &nbsp;|&nbsp; '
    f'개발자 : jhson9@gmail.com'
    f'</div>',
    unsafe_allow_html=True
)
