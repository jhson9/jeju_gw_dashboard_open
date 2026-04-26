# ==============================================================================
#  파일명: src/dashboard/theme.py  —  Build 1.0
# ==============================================================================
import streamlit as st

GLOBAL_CSS = """
<style>
  /* ==================================================
     CSS 변수 (기존 HTML 대시보드 v8과 동일)
     ================================================== */
  :root {
    --color-bg-primary:       #ffffff;
    --color-bg-secondary:     #f5f5f3;
    --color-bg-info:          #e6f1fb;
    --color-text-primary:     #1a1a18;
    --color-text-secondary:   #5f5e5a;
    --color-text-info:        #185fa5;
    --color-border-tertiary:  rgba(26,26,24,0.15);
    --color-border-secondary: rgba(26,26,24,0.30);
    --color-border-info:      #85b7eb;
    --color-success:          #1d9e75;
    --color-danger:           #e24b4a;
  }

  /* ==================================================
     전체 최대 너비 — 기존 HTML .dashboard-wrap (max-width:900px)
     ================================================== */
  .main .block-container {
    max-width: 940px !important;
    padding-left: 1.5rem !important;
    padding-right: 1.5rem !important;
    padding-top: 0.1rem !important;
  }
  /* Streamlit 기본 상단 헤더(‘Deploy’ 포함)와 툴바 완전 숨김 */
  header[data-testid="stHeader"],
  [data-testid="stToolbar"],
  [data-testid="stDecoration"] {
    display: none !important;
  }
  [data-testid="stAppViewContainer"] > .main {
    padding-top: 0 !important;
  }
  /* 본문 첫 블록의 상단 margin 제거 */
  .main .block-container > div:first-child,
  .main .block-container > div:first-child > div:first-child {
    margin-top: 0 !important;
    padding-top: 0 !important;
  }

  /* ==================================================
     Streamlit 탭 — 기존 HTML .tab / .tab.on 완전 이식
     padding:7px 16px, font-size:13px, font-weight:500
     radius:8px, 활성=파란 배경+파란 테두리
     ================================================== */
  .stTabs [data-baseweb="tab-list"] {
    gap: 6px !important;
    padding: 0 !important;
    margin-bottom: 1.25rem !important;
    flex-wrap: wrap !important;
    background: transparent !important;
    border-bottom: none !important;
  }
  .stTabs [data-baseweb="tab"] {
    display: inline-flex !important;
    align-items: center !important;
    gap: 6px !important;
    padding: 7px 16px !important;
    font-size: 13px !important;
    font-weight: 500 !important;
    border: 0.5px solid rgba(26,26,24,0.30) !important;
    border-radius: 8px !important;
    background: #f5f5f3 !important;
    color: #5f5e5a !important;
    cursor: pointer !important;
    transition: all .15s !important;
    white-space: nowrap !important;
    line-height: 1.4 !important;
    min-height: auto !important;
  }
  .stTabs [data-baseweb="tab"]:hover {
    background: #ffffff !important;
    color: #1a1a18 !important;
  }
  .stTabs [aria-selected="true"] {
    background: #e6f1fb !important;
    border-color: #85b7eb !important;
    color: #185fa5 !important;
    font-weight: 600 !important;
  }
  .stTabs [data-baseweb="tab-highlight"],
  .stTabs [data-baseweb="tab-border"] {
    display: none !important;
    background: transparent !important;
    height: 0 !important;
  }

  /* ==================================================
     수역 버튼 — 기존 HTML .wbtn (pill, radius:20px)
     font-size:11px, padding:4px 10px
     ================================================== */
  div[data-testid="stHorizontalBlock"] .stButton > button,
  .stButton > button {
    font-size: 11px !important;
    padding: 4px 10px !important;
    border-radius: 20px !important;
    line-height: 1.4 !important;
    height: auto !important;
    min-height: 0 !important;
  }
  .stButton > button[kind="secondary"] {
    border: 0.5px solid rgba(26,26,24,0.15) !important;
    background: #f5f5f3 !important;
    color: #5f5e5a !important;
    font-weight: 400 !important;
  }
  .stButton > button[kind="primary"] {
    font-weight: 600 !important;
  }

  /* ==================================================
     유역 선택 radio(horizontal) — pill 버튼 1.5배, 가운데 정렬
     ================================================== */
  div[data-testid="stRadio"] > label {
    display: none !important;   /* label_visibility=collapsed 보강 */
  }
  div[data-testid="stRadio"] [role="radiogroup"] {
    display: flex !important;
    gap: 5px !important;
    flex-wrap: wrap !important;          /* 폭 부족 시 자연스럽게 줄바꿈(예외용 폴백) */
    justify-content: center !important;  /* 가로 중앙 정렬 */
    width: 100% !important;
  }
  /* pill 본체 — 14개 유역이 한 줄에 들어오도록 폭 축소 */
  div[data-testid="stRadio"] [role="radiogroup"] label {
    flex: 1 1 68px !important;
    min-width: 68px !important;
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    gap: 0 !important;
    background: #f5f5f3 !important;
    border: 0.5px solid rgba(26,26,24,0.15) !important;
    border-radius: 24px !important;
    padding: 12px 7px !important;        /* 좌우 패딩 축소(10→7) */
    margin: 0 !important;
    cursor: pointer !important;
    transition: all .15s !important;
    white-space: nowrap !important;
    box-sizing: border-box !important;
  }
  div[data-testid="stRadio"] [role="radiogroup"] label:hover {
    background: #ffffff !important;
    border-color: rgba(26,26,24,0.30) !important;
  }
  /* 선택된 pill */
  div[data-testid="stRadio"] [role="radiogroup"] label:has(input:checked) {
    background: #e6f1fb !important;
    border-color: #85b7eb !important;
    color: #185fa5 !important;
  }
  /* 라디오 원형(첫 자식) 완전 제거 — 보이지 않고 폭도 차지하지 않게 */
  div[data-testid="stRadio"] [role="radiogroup"] label > div:first-child {
    display: none !important;
    width: 0 !important;
    margin: 0 !important;
    padding: 0 !important;
  }
  /* 텍스트 래퍼 — flex 컨테이너 자식으로 자동 중앙 정렬 */
  div[data-testid="stRadio"] [role="radiogroup"] label > div:last-child {
    margin: 0 !important;
    padding: 0 !important;
    text-align: center !important;
    line-height: 1 !important;
  }
  /* 유역 글자 — 카드 날짜("2025년 11월")와 동일한 15px / weight 600 */
  div[data-testid="stRadio"] [role="radiogroup"] label > div:last-child p {
    font-size: 15px !important;
    font-weight: 600 !important;
    color: inherit !important;
    margin: 0 !important;
    padding: 0 !important;
    text-align: center !important;
    line-height: 1 !important;
  }

  /* ==================================================
     편차 색상
     ================================================== */
  .dp { color: #1d9e75; font-weight: 500; }
  .dn { color: #e24b4a; font-weight: 500; }

  /* ==================================================
     인쇄 최적화
     ================================================== */
  @media print {
    section[data-testid="stSidebar"],
    header[data-testid="stHeader"],
    button,
    [data-testid="stStatusWidget"],
    .stDeployButton,
    [data-testid="stToolbar"] { display: none !important; }
    .main .block-container { max-width: 100% !important; padding: 0 !important; }
    .stTabs [data-baseweb="tab-list"] { display: none !important; }
  }
  @page { size: A4; margin: 15mm; }
</style>
"""


def apply_theme():
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)


def render_stat_card(label: str, value: str, sub: str = "",
                     color: str = None, container=None) -> None:
    border_color = color if color else "transparent"
    html = (
        f'<div style="background:#f5f5f3;border-radius:8px;'
        f'padding:0.75rem 0.875rem;border-left:2px solid {border_color};'
        f'margin-bottom:8px;">'
        f'<div style="font-size:10.5px;color:#5f5e5a;font-weight:500;">{label}</div>'
        f'<div style="font-size:16px;font-weight:600;color:#1a1a18;margin-top:2px;">{value}</div>'
        f'<div style="font-size:10px;color:#5f5e5a;margin-top:2px;">{sub}</div>'
        f'</div>'
    )
    target = container if container else st
    target.markdown(html, unsafe_allow_html=True)


def render_period_badges(periods: dict, current_key: str = "M") -> str:
    badges = []
    for key in ["M-2", "M-1", "M"]:
        if key not in periods:
            continue
        p = periods[key]
        if key == current_key:
            style = ("background:#185fa5;color:#fff;border:0.5px solid #185fa5;"
                     "padding:3px 10px;border-radius:14px;font-size:11px;"
                     "font-weight:500;margin-right:4px;display:inline-flex;"
                     "flex-direction:column;align-items:center;gap:1px;")
        else:
            style = ("background:#e6f1fb;color:#185fa5;border:0.5px solid #85b7eb;"
                     "padding:3px 10px;border-radius:14px;font-size:11px;"
                     "font-weight:500;margin-right:4px;display:inline-flex;"
                     "flex-direction:column;align-items:center;gap:1px;")
        badges.append(
            f'<span style="{style}">'
            f'<span style="font-size:11px;">{p["label"]}</span>'
            f'<span style="font-size:11px;font-weight:600;">{key}</span>'
            f'</span>'
        )
    return " ".join(badges)


def render_note_box(text: str) -> None:
    html = (
        f'<div style="margin-top:1rem;background:#f5f5f3;border-radius:8px;'
        f'padding:0.7rem 1rem;border-left:2px solid rgba(26,26,24,0.3);'
        f'font-size:11px;color:#5f5e5a;line-height:1.6;">{text}</div>'
    )
    st.markdown(html, unsafe_allow_html=True)


def format_diff_html(actual, avg, decimals: int = 1) -> str:
    import pandas as pd
    if (actual is None or (isinstance(actual, float) and pd.isna(actual))
            or avg is None or (isinstance(avg, float) and pd.isna(avg))):
        return "-"
    diff = actual - avg
    if abs(diff) < 0.05:
        return f"{diff:.{decimals}f}"
    color = "#1d9e75" if diff > 0 else "#e24b4a"
    sign = "+" if diff > 0 else ""
    return f'<span style="color:{color};font-weight:600;">{sign}{diff:.{decimals}f}</span>'
