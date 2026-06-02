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
    /* 사용자 요청 2026-05-09: 자주 쓰이는 hex 토큰화 */
    --color-text-tertiary:    #7f7f7f;
    --color-accent-darkred:   #C00000;
    --color-accent-blue-2:    #305496;
    --color-accent-blue-3:    #0a316e;
    --color-accent-quality-max: #A50026;
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
    flex-wrap: wrap !important;          /* 폭 부족 시 자연스럽게 줄바꿈 */
    justify-content: center !important;  /* 가로 중앙 정렬 */
    width: 100% !important;
  }
  /* pill 본체 — 14개 유역이 한 줄에 들어가는 선에서 적당한 크기로 조정 */
  div[data-testid="stRadio"] [role="radiogroup"] label {
    flex: 1 1 0 !important;              /* 균등 분배, 컨테이너 폭에 맞춰 자동 축소 */
    min-width: 58px !important;          /* 14×58 + 13×5 = 877px ≤ 892px(940-padding) */
    display: flex !important;
    align-items: center !important;
    justify-content: center !important;
    gap: 0 !important;
    background: #f5f5f3 !important;
    border: 0.5px solid rgba(26,26,24,0.15) !important;
    border-radius: 20px !important;
    padding: 10px 6px !important;
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
  /* 유역 글자 — 한 줄 fitting과 가독성의 균형으로 14px */
  div[data-testid="stRadio"] [role="radiogroup"] label > div:last-child p {
    font-size: 14px !important;
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
     타이포그래피 클래스 — 인라인 font-size 대체용
     모든 탭은 아래 클래스를 사용. 인라인 font-size 신규 도입 금지.
     5단계 계층 (사용자 요청 2026-05-09 디자인 통일):
       L1 .page-title       페이지 제목 (대시보드 전체)
       L2 .tab-title        탭 헤더 (⑤ 관정 검색 등)
       L3 .section-title    섹션 제목 (이모지 큰 사이즈 별도)
       L4 .subsection-title 서브섹션 / .chart-title (차트 위)
       L5 .caption-*        캡션·각주
     ================================================== */
  /* 사용자 요청 2026-05-10 (재조정): page-title 30 고정, 헤드 축소.
     이전 ×2 가 너무 컸음 → tab 27 / section 22 / subsection 20 / chart 18 /
     table-header 15. 내부 글자(table-cell 17.25, caption ×1.5)는 유지. */
  .page-title       { font-size: 30px !important; font-weight: 700;
                      color: #185fa5; line-height: 1.2;
                      margin: 0 0 6px; padding: 0; }
  .page-title .emoji { font-size: 28px !important; line-height: 1;
                       margin-right: 0.25em; vertical-align: -2px; }
  /* L1 탭 헤더 — 27 */
  .tab-title        { font-size: 27px !important; font-weight: 600;
                      color: #1a1a18; line-height: 1.25;
                      margin: 0 0 6px; padding: 0; }
  /* L2 섹션 제목 — 22, 이모지 28 (비례) */
  .section-title    { font-size: 22px !important; font-weight: 700;
                      color: #1a1a18; line-height: 1.3; margin: 0 0 6px; }
  .section-title .emoji { font-size: 28px !important; line-height: 1;
                          margin-right: 0.3em; vertical-align: -1px; }
  /* L3 .subsection-title — 20 */
  .subsection-title { font-size: 20px !important; font-weight: 700;
                      color: #1a1a18; margin: 0 0 4px; }
  /* L4 .chart-title — 18 */
  .chart-title      { font-size: 18px !important; font-weight: 700;
                      color: #1a1a18; margin: 0 0 3px; }
  /* 사용자 요청 2026-05-10 (재): 본문 클래스 +2~3px (헤더는 유지). */
  /* 표 헤더 — 15 → 18 */
  .table-header     { font-size: 18px; font-weight: 600; color: #1a1a18; background: #f5f5f3; }
  /* 표 셀 — 17.25 → 20 */
  .table-cell       { font-size: 20px; font-weight: 400; color: #1a1a18; }
  /* 캡션 — 15 → 17 / 13.5 → 15.5 (보수 +2) */
  .caption-sm       { font-size: 17px; color: #888; }
  .caption-xs       { font-size: 15.5px;  color: #888; }

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

  /* ==================================================
     지도 선택 마커 halo — 사용자 요청 2026-05-09
     -------------------------------------------------
     선택된 마커 위에 반투명 외곽 원을 추가해 시각 피드백 강화.
     pointer-events: none → halo 가 클릭을 가로채지 않음 (다음
     마커 클릭이 무반응되는 문제 방지).
     사용처: ag_map_builders.build_search_map / build_usage_map,
            _tab13_map._render_quality_map, map_helpers.add_station_markers.
     ================================================== */
  .leaflet-overlay-pane path.sel-halo {
    pointer-events: none !important;
  }

  /* ==================================================
     Dataframe selection 하이라이트 약화 (Phase 3 P2)
     -------------------------------------------------
     마커 클릭 후 selected_permit 와 표 selection 이 잠시
     다른 행을 가리킬 때의 시각 미스매치 완화. opacity 0.15
     로 정상 클릭 피드백은 유지하면서 stale 인지는 약화.
     셀렉터는 [data-testid="stDataFrame"] 한정 — tab4
     (selection 미사용), tab7/tab8 (HTML 테이블) 영향 없음.
     ※ glide-data-grid 가 canvas 기반이라 매칭 미보장 —
       매칭 안 되면 무동작(손해 없음).
     ※ row-pair-tight 보호 항목과는 셀렉터 분리되어 무관.
     ================================================== */
  [data-testid="stDataFrame"] [aria-selected="true"] {
    background-color: rgba(24, 95, 165, 0.15) !important;
  }
</style>
"""


def apply_theme():
    st.markdown(GLOBAL_CSS, unsafe_allow_html=True)


# ==============================================================================
#  디자인 토큰 — 인라인 hex 신규 도입 금지. 새 색이 필요하면 여기에 추가.
# ==============================================================================

COLOR_TEXT_PRIMARY   = "#1a1a18"
COLOR_TEXT_SECONDARY = "#5f5e5a"
COLOR_TEXT_TERTIARY  = "#7f7f7f"
COLOR_TEXT_INFO      = "#185fa5"
COLOR_BG_SECONDARY   = "#f5f5f3"
COLOR_BG_INFO        = "#e6f1fb"
COLOR_BORDER_INFO    = "#85b7eb"
COLOR_SUCCESS        = "#1d9e75"
COLOR_DANGER         = "#e24b4a"
# 사용자 요청 2026-05-09 (Plotly literal hex 정리): CSS 변수와 1:1
COLOR_ACCENT_DARKRED = "#C00000"   # PALETTE_ACCENT[4] alias
COLOR_ACCENT_BLUE_2  = "#305496"   # PALETTE_ACCENT[3] alias
COLOR_ACCENT_BLUE_3  = "#0a316e"
COLOR_ACCENT_NAVY    = "#1F3A5F"   # ri_dual_zone 클러스터·이용량 라벨
COLOR_QUALITY_MAX    = "#A50026"   # PALETTE_QUALITY_6TIER[5] alias

COLOR_AWS = {
    "제주":   "#378ADD",
    "서귀포": "#1D9E75",
    "성산":   "#E24B4A",
    "고산":   "#BA7517",
}

COLOR_REGION = {
    "동부": "#E24B4A",
    "서부": "#BA7517",
    "남부": "#1D9E75",
    "북부": "#378ADD",
}

REGION_OF_WATERSHED = {
    # config.WATERSHEDS 16개 유역 ↔ 4개 권역 매핑. 추가/변경 시 양쪽 동기화 필수.
    "구좌": "동부", "성산": "동부", "표선": "동부",
    "대정": "서부", "한경": "서부", "한림": "서부",
    "애월": "서부",                        # 2026-05-28 추가 — 제주시 서부 (config WATERSHEDS L169)
    "남원": "남부", "동서귀": "남부", "중서귀": "남부", "서서귀": "남부",
    "안덕": "남부",                        # 2026-05-28 추가 — 서귀포시 서부 → 남부 (config L175)
    "동제주": "북부", "중제주": "북부", "서제주": "북부", "조천": "북부",
}

REGION_REPRESENTATIVE_AWS = {
    "동부": "성산", "서부": "고산", "남부": "서귀포", "북부": "제주",
}

PERIOD_ALPHA = {"M-2": 0.35, "M-1": 0.65, "M": 1.0}

PALETTE_QUALITY_6TIER = [
    "#2C7BB6", "#67A9CF", "#A6D96A", "#FEE08B", "#F46D43", "#A50026",
]

PALETTE_ACCENT = [
    "#185fa5",  # 강조 파랑 (활성탭, 헤더)
    "#1d9e75",  # 양수/증가
    "#e24b4a",  # 음수/감소
    "#305496",  # 보조 파랑
    "#C00000",  # 다크레드 (변동 마커)
]


def standard_layout(
    height: int = 280,
    *,
    margin_t: int = 10,
    margin_b: int = 20,
    margin_l: int = 50,
    margin_r: int = 10,
    font_size: int = 14,
    showlegend: bool = False,
) -> dict:
    """Plotly figure 표준 layout dict.

    사용:
        fig.update_layout(**theme.standard_layout(height=240))

    탭마다 다른 마진/폰트를 박지 말고 이 함수를 사용. 정말 다른 값이 필요하면
    keyword arg 로 override.
    """
    return dict(
        height=height,
        margin=dict(t=margin_t, b=margin_b, l=margin_l, r=margin_r),
        font=dict(size=font_size, color=COLOR_TEXT_PRIMARY),
        plot_bgcolor="#ffffff",
        paper_bgcolor="#ffffff",
        showlegend=showlegend,
    )


def hex_alpha(hex_col: str, alpha: float) -> str:
    """HEX 색상에 alpha 채널을 더한 rgba() 문자열로 변환.

    예) hex_alpha("#1d9e75", 0.18) → "rgba(29,158,117,0.18)"
    """
    h = hex_col.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def render_stat_card(label: str, value: str, sub: str = "",
                     color: str = None, container=None) -> None:
    border_color = color if color else "transparent"
    html = (
        f'<div style="background:#f5f5f3;border-radius:8px;'
        f'padding:0.75rem 0.875rem;border-left:2px solid {border_color};'
        f'margin-bottom:8px;">'
        f'<div style="font-size:14px;color:#5f5e5a;font-weight:500;">{label}</div>'
        f'<div style="font-size:20px;font-weight:600;color:#1a1a18;margin-top:2px;">{value}</div>'
        f'<div style="font-size:14px;color:#5f5e5a;margin-top:2px;">{sub}</div>'
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
                     "padding:3px 10px;border-radius:14px;font-size:13px;"
                     "font-weight:500;margin-right:4px;display:inline-flex;"
                     "flex-direction:column;align-items:center;gap:1px;")
        else:
            style = ("background:#e6f1fb;color:#185fa5;border:0.5px solid #85b7eb;"
                     "padding:3px 10px;border-radius:14px;font-size:13px;"
                     "font-weight:500;margin-right:4px;display:inline-flex;"
                     "flex-direction:column;align-items:center;gap:1px;")
        badges.append(
            f'<span style="{style}">'
            f'<span style="font-size:13px;">{p["label"]}</span>'
            f'<span style="font-size:13px;font-weight:600;">{key}</span>'
            f'</span>'
        )
    return " ".join(badges)


def render_period_kpi_card(
    title: str,
    groups: list,
    *,
    accent: str = "#305496",
    is_base: bool = True,
    container=None,
) -> None:
    """⑧ 통계 요약 탭의 세로 누적 KPI 카드 패턴 (Build 2.2 검증된 디자인).

    한 카드 안에 title(상단 헤더) + groups(여러 개 KPI 그룹) 가 세로로 쌓이고,
    그룹 사이는 0.5px dashed 구분선. 그룹 하나는 (label, value, sub) 3줄 구조.

    Parameters
    ----------
    title : str
        카드 헤더 (예: "2025년" 또는 "2025-08").
    groups : list of tuple[str, str, str]
        [(label, value, sub), ...] — label 14px/600, value 18px/700/accent,
        sub 12px/500. value/sub 안에 HTML 허용.
    accent : str, optional
        카드 좌측 보더·VALUE 색상. 기본 #305496 (농업용 관정 컨텍스트).
    is_base : bool, optional
        기준 기간(가장 진한 톤). True 면 배경 0.08 alpha, False 면 0.04 alpha.
    container : streamlit container, optional
        st.columns(...)[i] 같은 컨테이너에 렌더링하려면 전달. 미전달 시 st.

    Example
    -------
    >>> theme.render_period_kpi_card(
    ...     "2025년",
    ...     [("총 이용량", "642,201,060 ㎥", "총 취수허가량 ..."),
    ...      ("관정별 평균 일이용량", "311.7 ㎥/일", "관정별 중앙값 ...")],
    ...     accent="#305496",
    ...     is_base=True,
    ... )
    """
    bg_tint = hex_alpha(accent, 0.08 if is_base else 0.04)
    bord_tint = hex_alpha(accent, 0.25)
    title_col = accent if is_base else COLOR_TEXT_SECONDARY

    # title 이 빈 문자열이면 헤더 영역 자체를 그리지 않음 (tab8 KPI 카드 같이
    # 카드 상단 헤더가 필요 없는 사용처용).
    parts: list = []
    if title:
        parts.append(
            f'<div style="font-size:18px;font-weight:700;color:{title_col};'
            f'padding:2px 0 4px;line-height:1.2;">{title}</div>'
        )
    for label, value, sub in groups:
        parts.append(
            f'<div style="padding:6px 0 4px;border-top:0.5px dashed {bord_tint};">'
            f'<div style="font-size:17px;color:{COLOR_TEXT_PRIMARY};'
            f'font-weight:600;line-height:1.15;margin:0;">{label}</div>'
            f'<div style="font-size:21px;font-weight:700;color:{accent};'
            f'line-height:1.15;margin:2px 0 0;">{value}</div>'
            f'<div style="font-size:15px;color:{COLOR_TEXT_SECONDARY};'
            f'font-weight:500;line-height:1.3;margin:1px 0 0;">{sub}</div>'
            f'</div>'
        )

    card_html = (
        f'<div style="background:{bg_tint};border-radius:8px;'
        f'padding:0.55rem 0.9rem 0.7rem;border-left:3px solid {accent};'
        f'margin-bottom:8px;">'
        + "".join(parts)
        + f'</div>'
    )
    target = container if container else st
    target.markdown(card_html, unsafe_allow_html=True)


def render_note_box(text: str) -> None:
    html = (
        f'<div style="margin-top:1rem;background:#f5f5f3;border-radius:8px;'
        f'padding:0.7rem 1rem;border-left:2px solid rgba(26,26,24,0.3);'
        f'font-size:14px;color:#5f5e5a;line-height:1.6;">{text}</div>'
    )
    st.markdown(html, unsafe_allow_html=True)


def format_diff_html(actual, avg, decimals: int = 1) -> str:
    """기준값과의 편차 표시 HTML (색깔+부호). NaN/None 안전."""
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
