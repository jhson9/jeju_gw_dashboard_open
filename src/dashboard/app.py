# ==============================================================================
#  제주도 지하수위·강수량 분석 대시보드
#  파일명: src/dashboard/app.py
# ------------------------------------------------------------------------------
#  Build: 1.2.07
#  최종 수정일: 2026-04-26
# ------------------------------------------------------------------------------
#  Changelog:
#  - v0.1 ~ v0.9: (생략 - CHANGELOG.md 참조)
#  - v1.0 (2026-04-22): 정식 릴리스.
#                       * 사이드바 완전 제거
#                       * 기존 HTML처럼 상단 헤더에 날짜 입력 + [분석] 버튼
#                       * 분석 기간 배지 헤더 바로 아래 표시
#                       * 탭 구조 유지 (5개 탭)
#  - v1.2.07 (2026-04-26): 외부 배포 버전에 ④ 공간 분석 탭 추가 → 6개 탭.
#                       * V-World 2D 타일 (키 있을 때) + OSM 폴백
#                       * 관측정/AWS 마커 + 영구 라벨 + 드롭다운 양방향 연동
#                       * 관측정: 일평균 변화 + 일강수량 (10년/시작월) + 12개월 분석
#                       * AWS:    12개월 강수량/유효강수일수 + 10년 월별 강수
#                       * 일자료 파서(gwlevel_day_parser): wide HTML xls→long upsert
#                       * 디렉토리 분리: by_station_month / by_station_day
#                                       Row_Data/Month / Row_Data/Day
#                       * 지도 인터랙션: 휠줌 비활성, +/- 버튼만; 미터 전용 스케일
#                       * 탭 상태 동기화 강화 (MutationObserver)
# ==============================================================================

import sys
from pathlib import Path
sys.path.append(str(Path(__file__).resolve().parents[2]))

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
    tab5_map,    # ④ 공간 분석 (Build 1.2.07 신규)
    tab_report,  # 외부 배포 버전: 데이터 관리 빼고 리포트 기능만 분리
    # tab4_admin은 외부 배포 버전에서 제외 (관리자 전용 기능)
)


# ==============================================================================
#  페이지 설정
# ==============================================================================
st.set_page_config(
    page_title="제주도 지하수위·강수량 대시보드",
    page_icon="🌊",
    layout="wide",
    initial_sidebar_state="collapsed",   # 사이드바 숨김
)

# 공통 CSS (사이드바 완전 숨김 포함)
theme.apply_theme()
st.markdown("""
<style>
/* 사이드바 완전 숨김 */
section[data-testid="stSidebar"] { display: none !important; }
[data-testid="collapsedControl"]  { display: none !important; }
/* 최상단 공백 최소화 — Streamlit 기본 헤더/툴바/패딩 제거 */
[data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"] {
    display: none !important; height: 0 !important;
}
.main .block-container { padding-top: 0.5rem !important; }
[data-testid="stAppViewContainer"] > .main { padding-top: 0 !important; }
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
#  헤더: 기존 HTML 대시보드와 동일한 구조
#  - 좌측: 시스템명 + 제목
#  - 우측: 날짜 입력 + [분석] 버튼
# ==============================================================================
asos_df     = load_asos_cached()
ws_data_all = load_watersheds_cached()

today = date.today()
DEFAULT_BASE_DATE = date(2026, 2, 1)

# 세션 상태 초기화
if "base_date" not in st.session_state:
    st.session_state["base_date"] = DEFAULT_BASE_DATE
if "report_requested" not in st.session_state:
    st.session_state["report_requested"] = False

BASE_DATE = st.session_state["base_date"]

# --------------------------------------------------------------------------
# 헤더 행: 제목 + 날짜 입력 + 분석 버튼 (한 줄에 모두 배치)
# (외부 배포 버전: Quit 버튼 제외)
# --------------------------------------------------------------------------
hcol_left, hcol_right = st.columns([1.3, 1.7])

with hcol_left:
    st.markdown(
        '<p style="font-size:11px;color:#5f5e5a;margin:0 0 2px;letter-spacing:0.06em;">'
        '지하수위 통합 분석 시스템 · 제주도</p>'
        '<h1 style="font-size:22px;font-weight:500;margin:0;color:#1a1a18;">'
        '🌊 제주도 지하수위·강수량 분석 대시보드</h1>',
        unsafe_allow_html=True
    )

with hcol_right:
    st.markdown("<div style='height:4px;'></div>", unsafe_allow_html=True)
    _cur = st.session_state["base_date"]
    year_opts  = list(range(2020, 2031))
    month_opts = list(range(1, 13))
    day_opts   = list(range(1, 32))
    dc_y, dc_m, dc_d, dc_go = st.columns([1.0, 0.8, 0.8, 1.2])
    with dc_y:
        year = st.selectbox(
            "연도", year_opts,
            index=year_opts.index(_cur.year) if _cur.year in year_opts else len(year_opts)-1,
            key="base_year", label_visibility="collapsed",
            format_func=lambda y: f"{y}년",
        )
    with dc_m:
        month = st.selectbox(
            "월", month_opts, index=_cur.month - 1,
            key="base_month", label_visibility="collapsed",
            format_func=lambda m: f"{m}월",
        )
    with dc_d:
        day = st.selectbox(
            "일", day_opts, index=min(_cur.day - 1, 30),
            key="base_day", label_visibility="collapsed",
            format_func=lambda d: f"{d}일",
        )
    with dc_go:
        if st.button("분석 ↗", type="primary", use_container_width=True):
            max_d = monthrange(year, month)[1]
            st.session_state["base_date"] = date(year, month, min(day, max_d))
            st.rerun()

BASE_DATE = st.session_state["base_date"]

# --------------------------------------------------------------------------
# 구분선
# --------------------------------------------------------------------------
st.markdown(
    '<hr style="margin:8px 0;border:none;'
    'border-top:0.5px solid rgba(26,26,24,0.15);">',
    unsafe_allow_html=True
)

# --------------------------------------------------------------------------
# 분석 기간 배지 (표시 전용 · 아래 차트에서 세 기간 모두 한 번에 보여주므로 클릭 불필요)
# --------------------------------------------------------------------------
periods = period_calculator.compute_periods(base_date=BASE_DATE)

badge_html = (
    '<div id="period-info-block">'
    '<div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap;margin-bottom:4px;">'
    '<span style="font-size:11px;color:#5f5e5a;">분석 기간</span>'
)
for key in ["M-2", "M-1", "M"]:
    p = periods[key]
    is_m = (key == "M")
    bg = "#185fa5" if is_m else "#f5f5f3"
    fg = "#ffffff" if is_m else "#5f5e5a"
    bd = "#185fa5" if is_m else "rgba(26,26,24,0.3)"
    badge_html += (
        f'<span style="display:inline-flex;flex-direction:column;align-items:center;'
        f'justify-content:center;padding:6px 28px;border-radius:10px;gap:2px;'
        f'min-width:180px;border:0.5px solid {bd};background:{bg};">'
        f'<span style="font-size:20px;font-weight:500;color:{fg};line-height:1.2;">{p["label"]}</span>'
        f'<span style="font-size:11px;font-weight:500;color:{fg};line-height:1.2;">({key})</span>'
        f'</span>'
    )
badge_html += '</div>'

is_half = (periods["mode"] != "normal")
note_text = "※ M 기간 평균 ×½ 적용" if is_half else ""
badge_html += (
    f'<div style="margin:6px 0 12px;">'
    f'<span style="font-size:11px;color:#5f5e5a;">'
    f'※ 비교 기준 연도는 각 기간(M-2·M-1·M)별로 독립 적용됩니다. '
    f'기간 열에 해당 기준 연도가 표시됩니다.</span>'
    + (f'&nbsp;&nbsp;<span style="font-size:11px;color:#e24b4a;">{note_text}</span>' if note_text else "")
    + '</div>'
    + '</div>'   # close #period-info-block
)
st.markdown(badge_html, unsafe_allow_html=True)

# 리포트(마지막 = 6번째) 탭이 활성화되면 분석 기간 박스 영역 숨김
# (CSS :has 셀렉터로 stTabs 의 마지막 탭 aria-selected 상태를 감지)
st.markdown("""
<style>
  /* 6개 탭 중 마지막(분석 리포트) 탭이 선택되면 #period-info-block 숨김 */
  body:has(.stTabs [data-baseweb="tab-list"] [data-baseweb="tab"]:nth-child(6)[aria-selected="true"])
    #period-info-block {
    display: none !important;
  }
</style>
""", unsafe_allow_html=True)


# ==============================================================================
#  탭 구조 (6개) — 외부 배포 버전: 관리자 탭(⚙️) 제외, 리포트 탭(🧾)만 유지
#  v1.2.07: ④ 공간 분석 탭 추가
# ==============================================================================
tab_names = [
    "📋 대시보드 요약",
    "① 유역별 현황",
    "② 강수량 분석",
    "③ 지하수위 분석",
    "④ 공간 분석",
    "🧾 분석 리포트",
]
# v1.2.03: 탭 목록 폭을 화면의 ~2/3 로 축약 + 중앙 정렬, 모든 탭 동일 폭
st.markdown("""
<style>
.stTabs [data-baseweb="tab-list"] {
    gap: 4px !important;
    max-width: 67% !important;
    margin: 0 auto !important;
    justify-content: center !important;
}
.stTabs [data-baseweb="tab-list"] [data-baseweb="tab"] {
    flex: 1 1 0 !important;
    min-width: 0 !important;
    text-align: center !important;
    justify-content: center !important;
    font-size: 14px !important;
}
</style>
""", unsafe_allow_html=True)
tabs = st.tabs(tab_names)

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
# ------------------------------------------------------------------
with tabs[0]:
    tab0_overview.render(asos_df, ws_data_all, periods)

with tabs[1]:
    tab1_watershed.render(asos_df, ws_data_all, periods)

with tabs[2]:
    tab2_rainfall.render(asos_df, periods)

with tabs[3]:
    tab3_gwlevel.render(ws_data_all, periods, asos_df=asos_df)

with tabs[4]:
    tab5_map.render(asos_df, periods, base_date=BASE_DATE)

with tabs[5]:
    tab_report.render(
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
  const KEY = 'jeju-gw-active-tab-idx';
  const doc = window.parent.document;

  function setup() {
    const tablist = doc.querySelector('.stTabs [data-baseweb="tab-list"]');
    const tabs = doc.querySelectorAll('.stTabs [data-baseweb="tab-list"] [data-baseweb="tab"]');
    if (!tabs.length || !tablist) { setTimeout(setup, 80); return; }

    // 1) 저장된 인덱스로 복원 — 탭 안에서 button/selectbox/map-click 등으로
    //    rerun 발생 시 Streamlit 이 첫 탭(0)으로 되돌리는 문제 방지.
    const saved = window.parent.sessionStorage.getItem(KEY);
    if (saved !== null) {
      const idx = parseInt(saved, 10);
      const activeIdx = Array.from(tabs).findIndex(
        t => t.getAttribute('aria-selected') === 'true'
      );
      if (idx >= 0 && idx < tabs.length && idx !== activeIdx) {
        tabs[idx].click();
      }
    }

    // 2) 사용자 클릭 시 즉시 기록
    tabs.forEach((tab, i) => {
      if (tab.dataset.jejuTabSync) return;
      tab.dataset.jejuTabSync = '1';
      tab.addEventListener('click', () => {
        window.parent.sessionStorage.setItem(KEY, String(i));
      });
    });

    // 3) aria-selected 변화도 감지 (프로그램적 탭 전환 포함) → sessionStorage 동기화
    if (!tablist.dataset.jejuObserver) {
      tablist.dataset.jejuObserver = '1';
      const obs = new MutationObserver(() => {
        const liveTabs = doc.querySelectorAll(
          '.stTabs [data-baseweb="tab-list"] [data-baseweb="tab"]'
        );
        const activeIdx = Array.from(liveTabs).findIndex(
          t => t.getAttribute('aria-selected') === 'true'
        );
        if (activeIdx >= 0) {
          window.parent.sessionStorage.setItem(KEY, String(activeIdx));
        }
      });
      tabs.forEach(t => obs.observe(t,
        { attributes: true, attributeFilter: ['aria-selected'] }));
    }
  }
  setup();
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
    f'제주도 지하수위·강수량 분석 대시보드 Build {config.BUILD_VERSION} &nbsp;|&nbsp; '
    f'기준일: {BASE_DATE} &nbsp;|&nbsp; '
    f'데이터 출처: 기상청 ASOS / 제주도 지하수정보관리시스템 &nbsp;|&nbsp; '
    f'개발자 : jhson9@gmail.com'
    f'</div>',
    unsafe_allow_html=True
)
