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


for _name in (
    "streamlit",
    "streamlit.runtime",
    "streamlit.runtime.scriptrunner",
    "streamlit.runtime.fragment",
):
    logging.getLogger(_name).addFilter(_FragmentNoiseFilter())

from calendar import monthrange
from datetime import date, timedelta

import streamlit as st
import pandas as pd

import config
from src.collectors import asos_collector
from src.analysis import period_calculator, watershed_mapper, effective_rainfall
from src.dashboard import theme
from src.dashboard.tabs import (
    tab0_overview,
    tab1_watershed,
    tab2_rainfall,
    tab3_gwlevel,
    tab4_admin,
    tab5_map,
    tab6_ag_search,
    tab7_ag_usage,
    tab8_ag_quality,
    tab9_ag_stats,
)


# ==============================================================================
#  페이지 설정
# ==============================================================================
st.set_page_config(
    page_title="제주도 농업용 지하수 분석 대시보드",
    page_icon="🌊",
    layout="wide",
    initial_sidebar_state="collapsed",   # 사이드바 숨김
)

# ==============================================================================
#  Streamlit Cloud stale-cache 방지 (commit 1435fa9 의 패턴을 일반화)
#  ----------------------------------------------------------------------------
#  배포 환경에서 이전 실행의 .pyc / @st.cache_data 결과가 남아 신규 코드와
#  뒤섞이며 AttributeError 가 발생한 사례가 있어, 앱 시작 시점에 모든
#  cache_data 항목을 무조건 비운다. 빈 캐시 비우기는 비용 거의 0.
# ==============================================================================
try:
    st.cache_data.clear()
except Exception:
    pass

# 공통 CSS (사이드바 완전 숨김 포함)
theme.apply_theme()
st.markdown("""
<style>
/* 사이드바 완전 숨김 */
section[data-testid="stSidebar"] { display: none !important; }
[data-testid="collapsedControl"]  { display: none !important; }

/* ─── 최상단 공백 0 처리 ───────────────────────────────────────────
 * Streamlit 의 기본 상단 영역(헤더·툴바·데코·iframe 빈공간)을 모두 제거.
 * .block-container 의 padding-top 이 가장 큰 여백 — 0 으로.
 * margin-top 도 0 으로 강제 (Streamlit 기본 ~6rem 마진 우회).
 */
[data-testid="stHeader"],
[data-testid="stToolbar"],
[data-testid="stDecoration"],
[data-testid="stStatusWidget"] {
    display: none !important;
    height: 0 !important;
    min-height: 0 !important;
    visibility: hidden !important;
}

.main .block-container,
[data-testid="stAppViewContainer"] > .main,
[data-testid="stMain"] .block-container,
section.main > div.block-container {
    padding-top: 0 !important;
    margin-top: 0 !important;
}

[data-testid="stAppViewContainer"],
[data-testid="stMain"] {
    padding-top: 0 !important;
    margin-top: 0 !important;
}

/* 첫 자식 요소도 마진 제거 — 일부 위젯이 자체 마진 가짐 */
.block-container > div:first-child,
.block-container > div:first-child > div:first-child {
    margin-top: 0 !important;
    padding-top: 0 !important;
}

/* 빈 components.html iframe 이 height=0 이어도 1px 차지하는 문제 우회 */
iframe[height="0"] { display: block; height: 0 !important; }
</style>
""", unsafe_allow_html=True)


# ==============================================================================
#  데이터 로드 (캐싱)
# ==============================================================================
@st.cache_data(ttl=300)
def load_asos_cached():
    return asos_collector.load_asos_data()

@st.cache_data(ttl=300)
def load_watersheds_cached():
    return watershed_mapper.load_watershed_data()


# ==============================================================================
#  세션 상태 / 데이터 / 기간 (헤더·탭 출력 이전에 미리 준비)
# ==============================================================================
DEFAULT_BASE_DATE = date(2026, 2, 1)
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
st.markdown(
    '<h1 style="font-size:28px;font-weight:700;margin:0 0 6px;padding:0;'
    'color:#1a1a18;line-height:1.2;">'
    '🌊 제주도 농업용 지하수 분석 대시보드</h1>',
    unsafe_allow_html=True
)


# ==============================================================================
#  탭 navigation (제목 바로 아래)
# ==============================================================================
tab_names = [
    "📋 대시보드 요약",
    "① 유역별 현황",
    "② 강수량 분석",
    "③ 지하수위 분석",
    "④ 공간 분석",
    "⑤ 관정 검색",
    "⑥ 이용량 분석",
    "⑦ 수질 분석",
    "⑧ 통계·요약",
    "⚙️ 데이터 및 리포트",
]
# v1.2.03: 탭 목록 폭을 화면의 ~2/3 로 축약 + 중앙 정렬, 모든 탭 동일 폭
st.markdown("""
<style>
.stTabs [data-baseweb="tab-list"] {
    gap: 4px !important;
    max-width: 95% !important;          /* 폰트 10% 확대로 10탭 한 줄 보장 */
    margin: 0 auto !important;
    justify-content: center !important;
}
.stTabs [data-baseweb="tab-list"] [data-baseweb="tab"] {
    flex: 1 1 0 !important;
    min-width: 0 !important;
    text-align: center !important;
    justify-content: center !important;
    font-size: 15.4px !important;       /* 14 → 15.4px (10% 확대) */
    padding: 9px 11px !important;       /* 기본 8px 10px → 10% 확대 */
}
/* ⑤ 관정 검색(6번째 탭) 앞에 추가 여백 — ④ 공간 분석과 데이터 성격이 다른
   사후관리 그룹의 시작점임을 시각적으로 분리 */
.stTabs [data-baseweb="tab-list"] [data-baseweb="tab"]:nth-child(6) {
    margin-left: 26px !important;
}
</style>
""", unsafe_allow_html=True)
# Streamlit 1.49+ 에서 st.tabs 가 key 인자를 지원하면 selected_index 가
# session_state["main_tabs"] 에 보존되어 full rerun 후에도 활성 탭 유지.
# 미지원 버전(< 1.49)에서는 TypeError 가 나므로 try/except 로 폴백.
try:
    tabs = st.tabs(tab_names, key="main_tabs")
except TypeError:
    tabs = st.tabs(tab_names)


# ==============================================================================
#  분석기간 컨트롤 + 과거 수위자료 안내 (탭 1~5 전용)
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
        bg = "#185fa5" if is_m else "#f5f5f3"
        fg = "#ffffff" if is_m else "#5f5e5a"
        bd = "#185fa5" if is_m else "rgba(26,26,24,0.3)"
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
    """탭 1~5 콘텐츠 첫 줄 — 분석기간 배지(좌) + 날짜 + 분석 + Quit (우).

    suffix : 탭 식별자(t0~t4). 위젯 key 충돌 방지용.
    """
    cols = st.columns([1.4, 1.6])
    with cols[0]:
        st.markdown(_build_badge_html(periods), unsafe_allow_html=True)
    with cols[1]:
        cur = st.session_state["base_date"]
        year_opts  = list(range(2010, 2031))
        month_opts = list(range(1, 13))
        day_opts   = list(range(1, 32))
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
            if st.button("⏹ Quit", use_container_width=True,
                         help="서버를 종료하고 터미널을 빠져나갑니다.",
                         key=f"qt_{suffix}"):
                os._exit(0)
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
            f'background:#fdecea;border-left:3px solid #e24b4a;'
            f'font-size:12px;color:#5f5e5a;">'
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

if ws_data_all:
    gw_rows = []
    for pk in ["M-2", "M-1", "M"]:
        p  = periods[pk]
        ym = f"{p['year']}-{p['month']:02d}"
        bl = list(range(p["year"] - config.GWLEVEL_BASELINE_YEARS, p["year"]))
        row = {"기간": pk, "연월": p["label"],
               "기준연도": f"{bl[0]}~{bl[-1]}"}
        for w_info in config.WATERSHEDS:
            wn   = w_info["name"]
            df_w = ws_data_all.get(wn)
            if df_w is None or df_w.empty:
                row[f"{wn}_실측"] = None
                row[f"{wn}_평균"] = None
                continue
            ra = df_w[df_w["연월"] == ym]
            actual = float(ra["EL_평균"].iloc[0]) if not ra.empty else None
            bvals  = []
            for y in bl:
                ymb = f"{y}-{p['month']:02d}"
                rb  = df_w[df_w["연월"] == ymb]
                if not rb.empty:
                    v = float(rb["EL_평균"].iloc[0])
                    if pd.notna(v):
                        bvals.append(v)
            avg = sum(bvals) / len(bvals) if bvals else None
            row[f"{wn}_실측"] = round(actual, 2) if actual is not None else None
            row[f"{wn}_평균"] = round(avg,    2) if avg    is not None else None
        gw_rows.append(row)
    gw_summary_df = pd.DataFrame(gw_rows)


# ------------------------------------------------------------------
# 각 탭 렌더링
#  - 탭 0~4 (자원 모니터링): 분석기간 컨트롤 + 수위자료 경고 + 콘텐츠
#  - 탭 5~9 (사후관리·데이터): 컨트롤 없이 콘텐츠만
# ------------------------------------------------------------------
with tabs[0]:
    render_period_controls("t0")
    render_gw_warning()
    tab0_overview.render(asos_df, ws_data_all, periods)

with tabs[1]:
    render_period_controls("t1")
    render_gw_warning()
    tab1_watershed.render(asos_df, ws_data_all, periods)

with tabs[2]:
    render_period_controls("t2")
    render_gw_warning()
    tab2_rainfall.render(asos_df, periods)

with tabs[3]:
    render_period_controls("t3")
    render_gw_warning()
    tab3_gwlevel.render(ws_data_all, periods, asos_df=asos_df)

with tabs[4]:
    render_period_controls("t4")
    render_gw_warning()
    tab5_map.render(asos_df, periods, base_date=BASE_DATE)

with tabs[5]:
    tab6_ag_search.render()

with tabs[6]:
    tab7_ag_usage.render()

with tabs[7]:
    tab8_ag_quality.render()

with tabs[8]:
    tab9_ag_stats.render(asos_df=asos_df)

with tabs[9]:
    tab4_admin.render(
        asos_df, ws_data_all, periods,
        rainfall_table=rainfall_table,
        eff_table=eff_table,
        gw_summary_df=gw_summary_df,
    )


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
  const KEY = 'jeju-gw-active-tab-idx';
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
  function saveIdx(idx) { ss.setItem(KEY, String(idx)); }

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
    setTimeout(() => { suppressRogue = false; showTabs(); }, 60);
    return false;
  }

  function attachClickListeners() {
    const tabs = getTabs();
    tabs.forEach((tab, i) => {
      if (tab.dataset.jejuTabSync) return;
      tab.dataset.jejuTabSync = '1';
      tab.addEventListener('click', () => { saveIdx(i); }, true);
    });
  }

  function attachObserver() {
    const tablist = doc.querySelector('.stTabs [data-baseweb="tab-list"]');
    if (!tablist || tablist.dataset.jejuObserver) return;
    tablist.dataset.jejuObserver = '1';
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
  }

  function tick() {
    if (!getTabs().length) return;
    attachClickListeners();
    attachObserver();
    restore();
  }

  tick();
  // 50ms × 12s 폴링 — 빠른 복원으로 깜박임 최소화
  const startTs = Date.now();
  const iv = setInterval(() => {
    if (Date.now() - startTs > 12000) { clearInterval(iv); showTabs(); return; }
    tick();
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
