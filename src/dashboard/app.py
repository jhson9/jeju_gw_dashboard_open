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
#  - v1.3.00 (2026-06-11): 2단 네비게이션 (v19) — 19개 탭 1줄 → 한글(HWP)
#                       리본 스타일 그룹 메뉴(7개) + 하위 탭. 선택 그룹만
#                       렌더 (그룹 게이팅). 51.지하수챗봇 그룹 신설.
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
# [공개판] Streamlit Community Cloud 실행 여부 — UI 게이팅용 단일 플래그.
#   (드론 helpers 의 is_cloud_env() 와 동일 판정이나, app.py 초기 구간에서
#    무거운 import 없이 쓰기 위해 경량 버전을 별도 정의)
from pathlib import Path as _Path
IS_CLOUD = _Path("/mount/src").exists()

try:
    import mimetypes
    # Windows mimetypes 누락 보강.
    mimetypes.add_type("application/javascript", ".js")
    mimetypes.add_type("text/css", ".css")
    mimetypes.add_type("application/wasm", ".wasm")

    # streamlit 1.56+ (starlette 서버) 는 확장자 화이트리스트가 제거되어
    # 이 패치가 불필요 — 모듈 없으면 조용히 건너뜀 (Cloud 로그 소음 방지).
    from streamlit.web.server import app_static_file_handler as _ash
    if not hasattr(_ash, "SAFE_APP_STATIC_FILE_EXTENSIONS"):
        raise ImportError("modern streamlit — MIME patch 불필요")
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
    if "MIME patch 불필요" not in str(_e):
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
    # 동작에 영향 없는 무해한 콘솔 노이즈만 제거.
    _DROP = (
        "Couldn't find fragment with id",      # streamlit fragment stale 디버그
        "WebSocketClosedError",                # 브라우저(앱) 창 닫힘 시 tornado write
        "Stream is closed",
        "Task exception was never retrieved",   # asyncio: 닫힌 ws future GC 시
        "Future exception was never retrieved",
    )

    def filter(self, record: logging.LogRecord) -> bool:
        # 예외 traceback 이 WebSocketClosedError 인 레코드 제거
        if record.exc_info and record.exc_info[1] is not None:
            if "WebSocketClosedError" in type(record.exc_info[1]).__name__:
                return False
        try:
            msg = record.getMessage()
        except Exception:
            return True
        return not any(s in msg for s in self._DROP)


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
    "asyncio",                                       # 'Task exception was never retrieved'
    "tornado",
    "tornado.application",
    "tornado.general",
    "tornado.access",
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
import time   # 🛡️ (2026-06-06) _render_partial_data_banner 의 time.sleep 용
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
# 🆕 (2026-06-11) 로버스트-베이지안 유역 대표값 — 사전계산 캐시 로더
from src.analysis import robust_aggregator
from src.dashboard import theme
from src.dashboard.tabs import (
    tab01_overview,
    # tab02_watershed 는 Stage 2 (2026-06-06 v3) 에서 tab01_overview 로 흡수됨.
    tab02_rainfall,
    tab03_gwlevel,
    tab99_admin,
    tab04_map,
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
#  Jeju_dashboard_island.ico 로 통일 (2026-06-07 이름 변경, 제주도 dashboard 의미 강조).
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
_ICON_PATH = Path(__file__).resolve().parents[2] / "Jeju_dashboard_island.ico"  # 2026-06-07 제주도 섬 아이콘
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
    padding-top: 0.35rem !important;   /* 🆕 (2026-06-11) 최대 압축 */
}
/* ─── 2단 네비게이션 v19 (2026-06-11 — 사용자 요청) ─────────────────
 * 기존 19개 탭 1줄 압축 배치 → 한글(HWP)/Word 리본 메뉴 스타일 2단 구조.
 *   1단(그룹 메뉴): st.radio (key=main_group_nav) — 메뉴바 모양으로 변환.
 *      theme.py 의 전역 pill-radio CSS 를 덮어써야 하므로
 *      .st-key-main_group_nav 로 범위 한정 + 동등 이상 명시도 확보.
 *   2단(하위 탭): 선택 그룹의 st.tabs — theme.py 기본 pill 스타일 복원.
 *      (font-size 13px·pill — 19탭 압축용 10px 강제 규칙 전부 제거)
 * ──────────────────────────────────────────────────────────────── */
/* 1단 그룹 메뉴바 컨테이너 — 하단 구분선으로 리본 느낌 */
.st-key-main_group_nav div[data-testid="stRadio"] [role="radiogroup"] {
    gap: 2px !important;
    justify-content: flex-start !important;
    flex-wrap: nowrap !important;
    border-bottom: 1px solid rgba(26,26,24,0.18) !important;
    padding: 0 2px !important;
    margin: 0 !important;
}
/* 그룹 항목 — pill 해제, 텍스트 메뉴 + 활성 밑줄.
   🛡️ (검증팀 MAJOR-1) theme.py 전역 radio 의 flex:1 1 0 누수 차단 —
   flex-grow 1 이면 7개 항목이 전폭 균등 분할되어 좌측 정렬 의도 무력화. */
.st-key-main_group_nav div[data-testid="stRadio"] [role="radiogroup"] label {
    /* 🆕 (2026-06-11 v2 사용자 피드백) 그룹탭 폭 1.5배 — 좌우 패딩 확대.
       균등분할(flex:1) 은 radiogroup 이 inline-flex 라 의도대로 동작하지
       않아 컴팩트+넓은 패딩 방식으로 변경. 줄간격(상하 패딩)은 최소 유지. */
    flex: 0 0 auto !important;
    min-width: 0 !important;
    display: flex !important;
    justify-content: center !important;
    text-align: center !important;
    background: transparent !important;
    border: none !important;
    border-bottom: 2.5px solid transparent !important;
    border-radius: 6px 6px 0 0 !important;
    padding: 3px 22px 2px !important;
    margin: 0 !important;
    cursor: pointer !important;
    transition: all .15s !important;
}
/* (2026-06-11 v2) A 줄간격 추가 압축 — 신형 컨테이너 클래스 + 네비 행 끌어올림 */
div.stMainBlockContainer,
[data-testid="stMainBlockContainer"] {
    padding-top: 0 !important;
    margin-top: 0 !important;
}
div[data-testid="stHorizontalBlock"]:has(.st-key-main_group_nav) {
    margin-top: -22px !important;   /* (v4) 직전 수준 복원 — -34 는 과압축 */
}
/* 상단 Quit 버튼 — 그룹 메뉴바와 같은 높이의 컴팩트 버튼 */
.st-key-main_quit_top button {
    padding: 2px 8px !important;
    min-height: 28px !important;
    height: 28px !important;
    font-size: 13.5px !important;
    font-weight: 600 !important;
    color: #b3261e !important;
    border: 1px solid rgba(179,38,30,0.45) !important;
    border-radius: 6px !important;
    background: #ffffff !important;
}
.st-key-main_quit_top button:hover {
    background: #fdecea !important;
    border-color: #b3261e !important;
}
/* 네비 줄(컬럼 행) 자체의 하단 여백 제거 — 최대 압축 */
div[data-testid="stHorizontalBlock"]:has(.st-key-main_group_nav) {
    margin-bottom: 0 !important;
    gap: 0.4rem !important;
}
/* radio 동그라미 숨김 */
.st-key-main_group_nav div[data-testid="stRadio"] [role="radiogroup"] label > div:first-child {
    display: none !important;
}
.st-key-main_group_nav div[data-testid="stRadio"] [role="radiogroup"] label > div:last-child p {
    font-size: 14.5px !important;
    font-weight: 600 !important;
    color: #5f5e5a !important;
    line-height: 1.3 !important;
}
.st-key-main_group_nav div[data-testid="stRadio"] [role="radiogroup"] label:hover {
    background: #f5f5f3 !important;
}
.st-key-main_group_nav div[data-testid="stRadio"] [role="radiogroup"] label:has(input:checked) {
    background: #e6f1fb !important;
    border-bottom-color: #185fa5 !important;
}
.st-key-main_group_nav div[data-testid="stRadio"] [role="radiogroup"] label:has(input:checked) > div:last-child p {
    color: #185fa5 !important;
}
/* 2단 하위 탭 — theme.py 기본 pill 스타일 사용. 그룹 메뉴와의 간격만 조정 */
.stTabs [data-baseweb="tab-list"] {
    margin-top: -8px !important;   /* (v4) B 줄간격 — 그룹탭과의 간격 축소 */
    margin-bottom: 0 !important;
    gap: 5px !important;
    flex-wrap: wrap !important;
}
/* 🆕 (2026-06-11 v3 사용자 피드백) 하위탭 pill — 높이↑·폭 동일(170px)·글자 14px */
.stTabs [data-baseweb="tab-list"] button[data-baseweb="tab"] {
    padding: 3px 14px !important;
    min-height: 32px !important;
    height: 32px !important;
    width: 170px !important;            /* 가장 큰 탭 기준 동일 폭 */
    justify-content: center !important;
}
.stTabs [data-baseweb="tab-list"] button[data-baseweb="tab"] p,
.stTabs [data-baseweb="tab-list"] button[data-baseweb="tab"] div {
    font-size: 14px !important;
    line-height: 1.2 !important;
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
    # ⚠️ 의도적 미사용 데코레이터 — DO NOT ADD `@st.cache_data` HERE.
    # 사유: asos_collector.load_asos_data() 가 모듈 레벨에서 이미 캐시됨.
    #   wrapper 별 캐시를 따로 두면 wrapper 마다 다른 DataFrame 객체가 반환되어
    #   hash_funcs={pd.DataFrame: id} 를 쓰는 하위 캐시 (_cached_gwlevel_diff_dict
    #   등) 가 wrapper 수만큼 분리됨 → 캐시 키 안정성 깨짐.
    # 본 함수는 단순 pass-through 로 동작하며 id-안정성을 유지한다.
    # (2026-06-06 Stage 2 M7 — 검증20팀의 데코레이터 추가 권고는 의도 미인지로 미반영)
    return asos_collector.load_asos_data()

@st.cache_data(ttl=600)
def load_watersheds_cached():
    return watershed_mapper.load_watershed_data()


# 사용자 요청 2026-05-09: 매 rerun 마다 compute_gwlevel_diff_dict 가 재계산
# (30 유역 × 3 기간) → 탭 전환 시 체감 지연. wrapper 로 5분 캐시.
# DataFrame value 는 id 기반 hash (load_watersheds_cached 가 같은 객체 반환).
#
# 🆕 (2026-06-06 Stage 2 H5+M2) periods dict 캐시 키 안정화:
#   기존 문제: periods dict 를 직접 인자로 받으면 Streamlit 의 default dict 해시
#             가 nested datetime.date · None · 가변 키 조합에서 잠재 불안정 (또는
#             dict identity 만 비교되어 내용 변경을 못 잡을 수 있음).
#   해결    : periods 의 핵심 필드(year, month, partial, n_days, end_date) 만
#             추출해 stable str key 로 변환 후, 실제 periods dict 는 `_` prefix
#             인자로 전달 (Streamlit 은 `_` 인자를 hash 에서 제외 — 공식 규약).
#   효과    : 캐시 키는 str key + ws_data_all(id) + n_years 만 결정 → 안정성↑.
def _make_periods_key(periods: dict) -> str:
    """periods dict → 캐시 키용 stable str.

    periods 의 top-level 키는 ``base_date``(date), ``mode``(str), 그리고
    슬롯 ``M-2``/``M-1``/``M``(dict) 가 섞여 있다 — period_calculator.compute_periods
    docstring 참조. 본 키는 슬롯 dict 만 순회해 핵심 식별 필드(year, month,
    partial, n_days, end_date) 를 추출한다. base_date / mode 는 슬롯에서 이미
    반영되므로 별도 합치지 않는다.
    """
    parts = []
    slot_keys = ("M-2", "M-1", "M")  # 🛡️ dict 가 아닌 키(base_date/mode) 자동 제외
    for k in slot_keys:
        p = periods.get(k)
        if not isinstance(p, dict):
            continue
        end_d = p.get("end_date")
        end_s = end_d.isoformat() if hasattr(end_d, "isoformat") else str(end_d or "")
        parts.append(
            f"{k}:{p.get('year')}-{p.get('month'):02d}"
            f"-p{int(bool(p.get('partial')))}"
            f"-n{p.get('n_days') or 0}"
            f"-e{end_s}"
        )
    # base_date / mode 는 partial 모드 결정에 영향을 주므로 명시적으로 포함
    bd = periods.get("base_date")
    parts.append(f"base:{bd.isoformat() if hasattr(bd, 'isoformat') else bd}")
    parts.append(f"mode:{periods.get('mode')}")
    return "|".join(parts)


@st.cache_data(ttl=600, show_spinner=False,
               hash_funcs={pd.DataFrame: id})
def _cached_gwlevel_diff_dict(ws_data_all: dict, periods_key: str,
                              n_years: int, _periods: dict) -> dict:
    """캐시 키: ws_data_all(id) + periods_key(str) + n_years(int).
    `_periods` 는 `_` prefix 로 Streamlit hash 제외 — 사용용으로만 전달.
    """
    return watershed_mapper.compute_gwlevel_diff_dict(
        ws_data_all, _periods, n_years
    )


@st.cache_data(ttl=600, show_spinner=False)
def _build_gw_summary_df(gwlevel_diff_key: str, n_years: int,
                         _gwlevel_diff_dict: dict, _periods: dict) -> "pd.DataFrame":
    """gwlevel_diff_dict → tab99_admin wide-format DataFrame.

    매 rerun 마다 반복 변환되던 로직을 캐시 함수로 분리 (사용자 요청 2026-05-09).
    🆕 캐시 키: gwlevel_diff_key(str — periods_key 와 동일) + n_years.
    `_gwlevel_diff_dict`, `_periods` 는 `_` prefix 로 hash 제외.
    """
    rows = []
    for pk in ["M-2", "M-1", "M"]:
        if pk not in _periods:
            continue
        p = _periods[pk]
        bl = list(range(p["year"] - n_years, p["year"]))
        row = {"기간": pk, "연월": p["label"],
               "기준연도": f"{bl[0]}~{bl[-1]}"}
        for w_info in config.WATERSHEDS:
            wn = w_info["name"]
            rec = _gwlevel_diff_dict.get(wn, {}).get(pk)
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
# 🆕 (2026-06-06) tab03/04/05 의 D-1 부분월 분석을 위해 partial_month=True 활성.
#   tab01/02 는 period["M"]["partial"] 키를 무시하므로 영향 없음 (월별 표시 유지).
#   base_date.day == 1 이면 partial 자동 비활성 (period_calculator 내부 가드).
periods   = period_calculator.compute_periods(base_date=BASE_DATE,
                                              partial_month=True)


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
      ① os._exit(0) 즉시 호출 → streamlit 이 클라이언트에 응답 못 보냄
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
        os._exit(0)

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
# 사용자 요청 (2026-05-23): 탭 번호 그룹 체계로 전면 재편.
# 사용자 요청 (2026-06-11 v19): 19개 탭 1줄 배치 → 한글(HWP)/Word 리본 스타일
#   2단 네비게이션으로 전면 개편.
#     · 1단 (그룹 메뉴, st.radio): 7개 그룹 — 항상 렌더. radio 는 매 rerun
#       렌더되는 위젯이라 key 만으로 선택 상태가 자동 보존 (JS 불필요).
#     · 2단 (하위 탭, st.tabs): **선택된 그룹의 탭만 생성·렌더** — 매 rerun
#       19개 탭 전체를 그리던 기존 비용을 그룹당 ≤5개로 축소 (성능 개선).
#     · 트레이드오프: 그룹 전환 시 해당 그룹 첫 렌더 비용 1회 발생. 미렌더
#       그룹의 위젯 상태는 streamlit 이 폐기하나, base_date 등 핵심 상태는
#       session_state 별도 보존이라 영향 없음.
#     · 51.지하수챗봇 그룹 신설 (src/chatbot/render.py 연결).
GROUPS: "list[tuple[str, list[str]]]" = [
    # (그룹 라벨, 하위 탭 라벨 목록) — 사용자 확정 2026-06-11
    ("강수량/지하수위", [
        "01.유역별현황", "02.강수량", "03.지하수위", "04.관측소 분석",
    ]),
    ("관정별 자료", [
        "11.관정 관리", "12.이용량 분석", "13.수질 분석",
    ]),
    ("이용량 분석", [
        "21.이용량 통계", "22.이용량 경향분석", "23.이용량 공간분석",
    ]),
    ("드론영상분석", [
        # [공개판] 2D 기능만 노출 — 3D(33·35)·현황(31) 탭은 대용량 자료
        # (point cloud·Cesium lib) 의존이라 공개 배포에서 제외.
        "32.정사영상 분석", "34.시계열 분석(2D)",
    ]),
    ("제주농업일반", [
        "41.농가현황", "42.농경지현황", "43.시설재배현황",
    ]),
    ("지하수챗봇", [
        "51.지하수챗봇",
    ]),
    ("데이터 관리", [
        "⚙️ 데이터 관리",
    ]),
]
# [공개판] Cloud: 데이터 관리 그룹 숨김 — 컨테이너 파일시스템이 휘발성이라
# 수집/갱신이 의미 없고, 외부 API 대량 호출 위험만 있음. 로컬은 그대로.
if IS_CLOUD:
    GROUPS = [g for g in GROUPS if g[0] != "데이터 관리"]
_GROUP_NAMES = [g[0] for g in GROUPS]

# 🛡️ (검증팀 MINOR-2) Quit 체크를 radio/tabs 렌더 **이전**으로 이동 —
# 종료 화면 위에 네비게이션이 잔존하지 않도록. 각 탭 모듈의 Quit 버튼이
# session_state["_quit_requested"]=True 설정 후 st.rerun(scope="app") 트리거.
if st.session_state.get("_quit_requested"):
    st.session_state["_quit_requested"] = False
    _shutdown_and_exit()

# 1단 그룹 메뉴 — st.radio. 메뉴바 모양 CSS 는 통합 CSS v19 블록 참조
# (.st-key-main_group_nav 범위 한정 — theme.py 전역 pill radio 와 충돌 없음).
# 🆕 (2026-06-11 사용자 요청) 그룹 메뉴 우측 끝에 Quit 통합 배치.
#   [그룹 radio (균등분할)] | [빈탭 간격] | [Quit] — 기존 탭별 Quit 전부 제거.
_nav_cols = st.columns([11.0, 1.1, 1.3])
with _nav_cols[0]:
    active_group = st.radio(
        "메인 메뉴", _GROUP_NAMES, index=0, horizontal=True,
        key="main_group_nav", label_visibility="collapsed",
    )
with _nav_cols[2]:
    # [공개판] Cloud: Quit 무의미 (서버 종료 권한 없음 + 다중 사용자) → 숨김.
    if not IS_CLOUD:
        if st.button("⏹ Quit", use_container_width=True, key="main_quit_top",
                     help="서버 종료 + 터미널 종료. 누르면 즉시 빠져나갑니다."):
            _shutdown_and_exit()
GROUP_IDX = _GROUP_NAMES.index(active_group)
_sub_tab_names = GROUPS[GROUP_IDX][1]

# 2단 하위 탭 — 선택 그룹의 탭만 생성.
# Streamlit 1.49.1 의 st.tabs 는 key 인자 미지원 (signature 확인 2026-06-11)
# → 활성 하위 탭 보존은 페이지 하단의 sessionStorage JS (그룹별 key) 담당.
# 미래 버전이 key 를 지원하면 try 분기가 자동 사용됨.
try:
    tabs = st.tabs(_sub_tab_names, key=f"main_tabs_g{GROUP_IDX}")
except TypeError:
    tabs = st.tabs(_sub_tab_names)

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
# 감지·shutdown 은 radio 렌더 직전 (위 v19 블록) 으로 이동 (검증팀 MINOR-2).


# ==============================================================================
#  분석기간 컨트롤 + 과거 수위자료 안내 (그룹 0 — 탭 01~04 전용)
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
    """탭 01~04 콘텐츠 첫 줄 — 분석기간 배지(좌) + 날짜 + 분석 + Quit (우).

    suffix : 탭 식별자(t0~t3). 위젯 key 충돌 방지용.
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
        # (2026-06-11) Quit 상단 통합 — sub[4] 제거, 4컬럼으로
        sub = st.columns([1.0, 0.8, 0.8, 1.2])
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
        # (2026-06-11) Quit 버튼은 상단 그룹 메뉴 우측으로 통합 — sub[4] 제거
    st.markdown(
        '<hr style="margin:6px 0 10px;border:none;'
        'border-top:0.5px solid rgba(26,26,24,0.15);">',
        unsafe_allow_html=True
    )
    # 🆕 (2026-06-06) base_date 가 부분월 모드 (오늘 외 다른 날짜로 변경) 일 때만
    #   D-1 까지의 자료가 있는지 확인하고 부족하면 업데이트 버튼 표시.
    #   🛡️ (2026-06-06 v2) suffix 전달 — 5탭 동시 호출 시 key 중복 방지
    _render_partial_data_banner(periods, asos_df, BASE_DATE, suffix=suffix)


def _render_partial_data_banner(periods: dict, asos_df, base_date,
                                 suffix: str = "") -> None:
    """🆕 (2026-06-06) base_date 가 부분월 모드일 때 자료 부족 알림 + 수동 업데이트.

    동작:
      · periods["M"]["partial"]=False → 아무것도 안 함 (월별 분석, 기존 자료 OK)
      · partial=True → ASOS / GWlevel 일자료 마지막 일자가 (base_date - 1) 인지 확인
      · 부족하면 상단 warning + "🔄 지금 D-1 까지 업데이트" 버튼 표시
      · 버튼 클릭 시 ASOS latest + GWlevel day 부족분만 수집 (보통 1~5분)

    설계 원칙:
      · 부팅 자동수집 (launch_dashboard) 은 31일 임계 그대로 — 매번 수집 X
      · base_date 변경 (예: 6/1 → 6/5) 시점에만 자료 확인 + 사용자 명시 클릭 시 수집
    """
    m_p = periods.get("M", {})
    if not m_p.get("partial"):
        return  # 월별 분석이면 배너 불필요
    # [공개판] Cloud: 수집 자료가 컨테이너 휘발성 → 재부팅 시 소실되고
    # 기상청/water.jeju API 대량 호출 부담만 발생 → 배너·버튼 비표시.
    if IS_CLOUD:
        st.caption("ℹ️ 공개판은 저장소에 동봉된 자료(최종 수집일)까지 표시합니다 — 실시간 갱신은 로컬 설치판 전용.")
        return

    import pandas as _pd
    from datetime import date as _date

    target_end = m_p.get("end_date")
    if target_end is None:
        return

    # 🛡️ (2026-06-06 로직2팀 권고) session_state 60초 캐시 — 5탭 진입마다
    # CSV I/O 반복 회피. cache key = (base_date, target_end).
    import time as _time
    _cache_key = f"_partial_banner_cache_{base_date}_{target_end}"
    _now = _time.time()
    _cached = st.session_state.get(_cache_key)
    if _cached and (_now - _cached["ts"] < 60):
        asos_last   = _cached["asos_last"]
        gw_day_last = _cached["gw_day_last"]
    else:
        # ASOS 마지막 일자
        asos_last = None
        try:
            if asos_df is not None and not asos_df.empty:
                asos_last = _pd.to_datetime(asos_df["일시"]).max().date()
        except Exception:  # noqa: BLE001
            # 🆕 (2026-06-06 Stage 2 H2) 무음 예외 → logger.exception.
            # None 폴백 = "ASOS 최신 일자 알 수 없음" → missing 리스트에 표기.
            logging.getLogger(__name__).exception("ASOS asos_last 산출 실패")

        # GWlevel 일자료 마지막 (JW연동 대표 — 빠름)
        gw_day_last = None
        try:
            gw_path = config.GW_STATION_DAY_DIR / "JW연동.csv"
            if gw_path.exists():
                df_gw = _pd.read_csv(gw_path, encoding="utf-8-sig", usecols=["날짜"])
                gw_day_last = _pd.to_datetime(df_gw["날짜"], errors="coerce").max().date()
        except Exception:  # noqa: BLE001
            # 🆕 (2026-06-06 Stage 2 H2) 무음 예외 → logger.exception.
            # None 폴백 = "GWlevel 최신 일자 알 수 없음" → missing 리스트에 표기.
            logging.getLogger(__name__).exception("GWlevel gw_day_last 산출 실패")

        st.session_state[_cache_key] = {
            "ts": _now,
            "asos_last": asos_last,
            "gw_day_last": gw_day_last,
        }

    missing = []
    if asos_last is None or asos_last < target_end:
        missing.append(f"ASOS({asos_last or '없음'} → 필요 {target_end})")
    if gw_day_last is None or gw_day_last < target_end:
        missing.append(f"GWlevel 일({gw_day_last or '없음'} → 필요 {target_end})")

    if not missing:
        return   # 자료 충분

    c1, c2 = st.columns([5, 1.2])  # 🛡️ 디자인1팀 권고 — 버튼 폭 약간 확대
    with c1:
        st.warning(
            f"⚠️ 분석 기준일 **{base_date}** (M = {m_p.get('label', '')}) 에 "
            f"필요한 자료 부족 — {' · '.join(missing)}"
        )
    with c2:
        if st.button("🔄 D-1 업데이트",
                     type="primary", use_container_width=True,
                     key=f"partial_update_btn_{base_date}_{suffix}",
                     help="ASOS + 지하수위 일자료 + parquet 자동 재생성 (1~5분)"):
            # 🛡️ (2026-06-06 오류1팀 권고) 인터넷 체크 — 오프라인 5분 hang 차단
            import socket as _sk
            def _ck_net(t=1.5):
                for h in [("8.8.8.8", 53), ("1.1.1.1", 53)]:
                    try:
                        with _sk.socket(_sk.AF_INET, _sk.SOCK_STREAM) as s:
                            s.settimeout(t); s.connect(h); return True
                    except Exception:
                        continue
                return False
            if not _ck_net():
                st.error("❌ 인터넷 연결 없음 — 수집 진행 불가. "
                         "네트워크 연결 후 다시 시도하세요.")
                # 캐시 무효화 — 사용자가 인터넷 연결 후 즉시 재시도 가능
                st.session_state.pop(_cache_key, None)
                return

            asos_ok = False
            gw_ok = False
            with st.status("부족분 수집 중...", expanded=True) as _status:
                _status.update(label="ASOS latest 모드 수집 중...", state="running")
                try:
                    asos_collector.collect_asos_data(mode="latest")
                    try:
                        asos_collector.load_asos_data.clear()
                    except Exception:
                        pass
                    st.write("  ✓ ASOS 완료")
                    asos_ok = True
                except Exception as e:
                    st.write(f"  ⚠ ASOS 실패: {type(e).__name__}: {e}")
                _status.update(label="GWlevel 일자료 수집 중 (직전달 재검증 포함)...",
                               state="running")
                try:
                    from src.collectors import jeju_gwlevel_collector
                    # 🆕 (2026-06-06 v3) 직전달 1일부터 force 재수집 — 서버 수정 반영
                    this_first = _date(base_date.year, base_date.month, 1)
                    prev_last  = this_first - __import__('datetime').timedelta(days=1)
                    prev_first = prev_last.replace(day=1)
                    jeju_gwlevel_collector.collect_all(
                        granularity="day",
                        force=True,
                        default_start=prev_first.strftime("%Y-%m-%d"),
                    )
                    try:
                        jeju_gwlevel_collector.load_station_day_csv.clear()
                    except Exception:
                        pass
                    st.write(f"  ✓ GWlevel 일 완료 "
                             f"(직전달 {prev_first.strftime('%Y-%m')} 재검증 포함)")
                    gw_ok = True
                except Exception as e:
                    st.write(f"  ⚠ GWlevel 일 실패: {type(e).__name__}: {e}")

                # 🛡️ (2026-06-06 로직3팀 권고) GWlevel 수집 성공 시 parquet 자동 재생성
                # tab04 의 _render_watershed_partial_daily 가 parquet 을 직접 읽으므로
                # 재생성 없으면 stale.
                if gw_ok:
                    _status.update(label="parquet 통합 캐시 재생성 중...",
                                   state="running")
                    try:
                        from src.collectors import gwlevel_day_parser
                        gwlevel_day_parser.build_day_parquet(verbose=False)
                        st.write("  ✓ parquet 재생성 완료")
                    except Exception as e:
                        st.write(f"  ⚠ parquet 재생성 실패: "
                                 f"{type(e).__name__}: {e}")

                # 🛡️ (2026-06-06 오류2팀 권고) 둘 다 실패 시 error state
                if not (asos_ok or gw_ok):
                    _status.update(label="❌ 모두 실패 — 콘솔 로그 확인",
                                   state="error", expanded=True)
                else:
                    _status.update(label="✅ 완료 — 페이지 새로고침",
                                   state="complete", expanded=False)

            # 캐시 무효화 — 갱신된 데이터 즉시 재검사
            st.session_state.pop(_cache_key, None)
            if asos_ok or gw_ok:
                st.toast("✅ D-1 자료 업데이트 완료", icon="✅")
                time.sleep(1.0)
                st.rerun()


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
# 🆕 (2026-06-06 Stage 2 H5+M2) periods → 안정 str key 변환 후 캐시 호출.
gwlevel_diff_dict: dict = {}
if ws_data_all:
    _periods_key = _make_periods_key(periods)
    gwlevel_diff_dict = _cached_gwlevel_diff_dict(
        ws_data_all, _periods_key,
        n_years=config.GWLEVEL_BASELINE_YEARS,
        _periods=periods,
    )
    # 위 dict 를 tab99_admin 이 받는 wide-format DataFrame 으로 변환 (캐시).
    gw_summary_df = _build_gw_summary_df(
        _periods_key, config.GWLEVEL_BASELINE_YEARS,
        _gwlevel_diff_dict=gwlevel_diff_dict, _periods=periods,
    )

# 🆕 (2026-06-11) 로버스트-베이지안(F) 사전계산 캐시 dict — tab01·tab03 공유.
#   {유역: {pk: {방법: {편차, ci_low, ci_high, n}}}}. 캐시 parquet 미존재 시 {}
#   → 각 탭이 REF(현행) 폴백 + "(현행)" 라벨로 동작 (하위 호환).
#   캐시 키: periods_key + parquet mtime (사전계산 재실행 시 자동 무효화).
gwlevel_robust_dict: dict = {}
if ws_data_all:
    try:
        gwlevel_robust_dict = robust_aggregator.build_period_dict_cached(
            _periods_key, robust_aggregator.cache_mtime(), _periods=periods,
        )
    except Exception:
        logging.getLogger(__name__).exception(
            "robust 캐시 로드 실패 — REF 폴백으로 계속")


# ------------------------------------------------------------------
# 각 탭 렌더링 — v19 (2026-06-11) 그룹 게이팅
#  - GROUP_IDX 에 해당하는 그룹의 하위 탭만 render() (성능 개선:
#    매 rerun 19개 탭 → 그룹당 ≤5개).
#  - 그룹 내부에서는 기존과 동일하게 st.tabs 가 모든 with-블록을 매
#    rerun 실행 (streamlit 구조 한계 — 그룹 단위 게이팅으로 비용 축소).
#  - 그룹 0 (강수량/지하수위): 분석기간 컨트롤 + 수위자료 경고 + 콘텐츠
#  - 나머지 그룹: 컨트롤 없이 콘텐츠만 (Quit 는 각 탭 모듈이 표시)
#
# (#7 활성 탭 게이팅 시도 v14 롤백 2026-05-16 — 기록 유지):
#   JS/URL (location.reload / history.replaceState) 기반 st.tabs 게이팅은
#   streamlit 구조적 한계로 회귀 발생 → 롤백된 바 있음.
#   v19 의 그룹 게이팅은 Python 위젯(radio) 분기 — JS 미개입이라 해당
#   회귀 패턴과 무관. 그룹 전환 = 정상 widget rerun 경로.
# ------------------------------------------------------------------
if GROUP_IDX == 0:
    # ── 그룹 0: 강수량/지하수위 (01~04) ──
    with tabs[0]:
        # tab01 + tab02 통합 모듈 (2026-06-06 v3 Stage 2) — 주석 이력 유지.
        render_period_controls("t0")
        render_gw_warning()
        tab01_overview.render(
            asos_df, ws_data_all, periods,
            gwlevel_diff_dict=gwlevel_diff_dict,
            robust_dict=gwlevel_robust_dict,
        )
    with tabs[1]:
        render_period_controls("t1")
        render_gw_warning()
        tab02_rainfall.render(asos_df, periods)
    with tabs[2]:
        render_period_controls("t2")
        render_gw_warning()
        tab03_gwlevel.render(ws_data_all, periods, asos_df=asos_df,
                             robust_dict=gwlevel_robust_dict)
    with tabs[3]:
        render_period_controls("t3")
        render_gw_warning()
        tab04_map.render(asos_df, periods, base_date=BASE_DATE)

elif GROUP_IDX == 1:
    # ── 그룹 1: 관정분석 (11~13) ──
    with tabs[0]:
        tab11_ag_search.render()
    with tabs[1]:
        tab12_ag_usage.render()
    with tabs[2]:
        tab13_ag_quality.render()

elif GROUP_IDX == 2:
    # ── 그룹 2: 이용량공간 (21~23) ──
    with tabs[0]:
        tab21_ag_stats.render(asos_df=asos_df)
    with tabs[1]:
        tab22_ag_usage_detail.render(asos_df=asos_df, periods=periods)
    with tabs[2]:
        tab23_ag_usage_map.render()

elif GROUP_IDX == 3:
    # ── 그룹 3: 드론영상 (31~35) ──
    # D2+D3 fix 2026-05-30 유지: lazy import + try/except 격리 —
    # 한 탭 fail 해도 그룹 내 다른 탭 동반 다운 차단 (사용자 보고 8팀 권고).
    def _render_drone_tab(tab_ctx, module_name: str, label: str) -> None:
        with tab_ctx:
            try:
                import importlib
                _mod = importlib.import_module(
                    f"src.dashboard.tabs.{module_name}")
                _mod.render()
            except Exception as e:  # noqa: BLE001
                import traceback as _tb
                st.error(f"❌ {label} 로드 실패: {type(e).__name__}: {e}")
                with st.expander("상세 traceback (운영자용)"):
                    st.code(_tb.format_exc(), language="python")

    # [공개판] 2D 기능만 — tab31/33/35 (현황·3D) 는 공개 배포 제외.
    _render_drone_tab(tabs[0], "tab32_drone_2d", "32.정사영상 분석")
    _render_drone_tab(tabs[1], "tab34_drone_diff", "34.시계열 분석(2D)")
    # ── 2026-06-06: 36/37 (실험적 DoD) 검증 완료 후 34/35 로 통합·승격.
    #    원본 tab34/35 (DoD 없음) 는 _archive/ 에 보관 (rollback 가능).

elif GROUP_IDX == 4:
    # ── 그룹 4: 제주농업 (41~43) — 2026-05-25 신설 그룹 ──
    with tabs[0]:
        tab41_population.render()
    with tabs[1]:
        tab42_farm_household.render()
    with tabs[2]:
        tab43_greenhouse.render()

elif GROUP_IDX == 5:
    # ── 그룹 5: 지하수챗봇 (51) — 2026-06-11 v19 신설 ──
    # src/chatbot/render.py 의 render_chatbot 이 Tab51 공유용으로 설계됨.
    # lazy import + try/except 격리 (드론 그룹과 동일 패턴). 챗봇 의존성
    # (RAG·LLM) 미설치 시 render_chatbot 내부 health_check 가 설치 안내 표시.
    with tabs[0]:
        try:
            from src.chatbot.render import render_chatbot
            # (2026-06-11 v2) show_title=False — 하위탭 pill 과 중복 제목 제거
            render_chatbot(show_title=False)
        except Exception as e:  # noqa: BLE001
            import traceback as _tb
            st.error(f"❌ 51.지하수챗봇 로드 실패: {type(e).__name__}: {e}")
            with st.expander("상세 traceback (운영자용)"):
                st.code(_tb.format_exc(), language="python")

else:
    # ── 그룹 6: 데이터관리 (99) ──
    with tabs[0]:
        tab99_admin.render(
            asos_df, ws_data_all, periods,
            rainfall_table=rainfall_table,
            eff_table=eff_table,
            gw_summary_df=gw_summary_df,
        )

# tab11 마커 실험 탭은 사용자 요청으로 삭제 (2026-05-09).


# ==============================================================================
#  하위 탭 선택 상태 보존 (Streamlit st.tabs 한계 우회) — v9 (2026-06-11 v19)
#  -------------------------------------------------------------------
#  st.button() 클릭 → Streamlit auto-rerun → st.tabs() 가 첫 탭으로 초기화되는
#  알려진 한계. 브라우저 sessionStorage 에 마지막 활성 하위 탭 인덱스를
#  저장하고 rerun 후 자동 복원한다.
#
#  v9 변경점 (2단 네비게이션 전환):
#   · 1단 그룹(radio) 은 widget key 로 streamlit 이 자동 보존 — JS 무관.
#   · sessionStorage key 를 그룹별로 분리 ('...-g{GROUP_IDX}') — 각 그룹이
#     마지막 활성 하위 탭을 독립 기억. 그룹 전환 후 복귀 시에도 복원.
#   · stale-iframe 오염 방지: full rerun 시 이전 주입분 iframe 의 click
#     listener 가 parent doc 에 남을 수 있음 — 닫힌 closure 의 옛 그룹 key
#     로 저장하면 다른 그룹 값이 오염된다. 모든 read/write 를
#     doc.documentElement.dataset.jejuSubtabKey (현재 그룹 key) 경유로 변경.
#   · URL query 't' 동기화 제거 — Python 측에서 읽는 곳 없음 (v14 게이팅
#     롤백 후 잔존 코드였음).
#  v8 이전 이력은 git/백업 (jeju_groundwater_dashboard_Backup_260611) 참조.
# ==============================================================================
import streamlit.components.v1 as _components
_SUBTAB_JS = """
<script>
(function() {
  const doc = window.parent.document;
  const ss = window.parent.sessionStorage;

  // 현재 활성 그룹의 sessionStorage key — dataset 경유 (stale iframe 안전).
  doc.documentElement.dataset.jejuSubtabKey = 'jeju-gw-subtab-v9-g__GROUP_IDX__';
  function KEY() {
    return doc.documentElement.dataset.jejuSubtabKey ||
           'jeju-gw-subtab-v9-g__GROUP_IDX__';
  }

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
    const v = ss.getItem(KEY());
    if (v === null) return -1;
    const n = parseInt(v, 10);
    return Number.isFinite(n) ? n : -1;
  }
  function saveIdx(idx) {
    ss.setItem(KEY(), String(idx));
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

  // ── 첫 페이지 로드 1회만 hideTabs 발동 (Build 1.2.12 가드 유지)
  try {
    const root = doc.documentElement;
    if (!root.dataset.jejuFirstLoadDone) {
      if (getSavedIdx() > 0) hideTabs();
      root.dataset.jejuFirstLoadDone = '1';
    }
  } catch (e) { /* cross-origin 등 안전 무시 */ }
  // safety: 1.5초 후엔 무조건 보이기 — 폴링/복원 실패해도 화면은 표시
  setTimeout(showTabs, 1500);

  // 우리가 click() 으로 일으킨 변경(intentional) vs Streamlit reset(rogue) 구분
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
    // 150ms — 회귀 보정 2026-05-12 (iframe paint + V-World 첫 청크 마진)
    setTimeout(() => { suppressRogue = false; }, 150);
    showTabs();
    return true;
  }

  // ── 탭 click 캡처 → sessionStorage 갱신 (capture-phase 로 가장 먼저).
  //    KEY() 가 dataset 경유라 stale listener 도 항상 현재 그룹 key 에 저장.
  doc.addEventListener('click', (e) => {
    const tab = e.target.closest('[data-baseweb="tab"]');
    if (!tab) return;
    if (suppressRogue) return;
    const tabs = getTabs();
    const idx = Array.from(tabs).indexOf(tab);
    if (idx >= 0) saveIdx(idx);
  }, true);

  // ── MutationObserver: 프로그램적 0번 reset 감지 → 복원
  const tablist = doc.querySelector('.stTabs [data-baseweb="tab-list"]');
  if (tablist) {
    const obs = new MutationObserver(() => {
      const tabs = getTabs();
      if (!tabs.length) return;
      if (suppressRogue) return;
      const active = getActiveIdx(tabs);
      const saved = getSavedIdx();
      // 0번으로 reset 됐는데 saved>0 면 즉시 복원
      if (active === 0 && saved > 0 && saved < tabs.length) {
        restore();
      }
    });
    obs.observe(tablist, { subtree: true, attributes: true,
                          attributeFilter: ['aria-selected'] });
  }

  // ── 폴링 (첫 마운트, fragment rerun, st_folium height change,
  //         그룹 전환 직후 새 tab-list 마운트 대응)
  let polls = 0;
  const interval = setInterval(() => {
    polls++;
    if (polls > 240) { clearInterval(interval); showTabs(); return; }
    const tabs = getTabs();
    if (!tabs.length) return;
    const saved = getSavedIdx();
    const active = getActiveIdx(tabs);
    if (saved >= 0 && saved < tabs.length && active !== saved) {
      restore();
    }
  }, 50);
})();
</script>
"""
_components.html(
    _SUBTAB_JS.replace("__GROUP_IDX__", str(GROUP_IDX)),
    height=0,
)
