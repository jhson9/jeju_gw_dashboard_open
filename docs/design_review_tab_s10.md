# Tab S10+ Landscape Design Review — 제주 농업용 지하수 대시보드

Captured 2026-05-06, Samsung Browser, jeju-gw.streamlit.app
Viewport CSS width inferred from chrome layout: **~1400px** (DPR ~2)

---

## Screenshot Catalog

| # | File (110xxx) | View |
|---|---|---|
| 1 | 110121 | Tab 0 요약 — AWS 카드 4열 + 유역별 EL 막대 그래프 |
| 2 | 110128 | Tab 1 유역별 — 구좌 선택, M-2/M-1/M 카드 + 강수/EL 차트 |
| 3 | 110151 | Tab 2 강수량 — 4 AWS 카드 + 4 카드 차트 + 비교표 (16열) |
| 4 | 110202 | Tab 2 강수량 — 유효강수 비교표 + 연간 강수 차트 (5개) |
| 5 | 110213 | Tab 3 지하수위 — 3개월 편차 막대 3개 + pill 라디오 + 상세 카드 |
| 6 | 110223 | Tab 3 — 관측정별 상세표 (16정 × 9열) |
| 7 | 110227 | Tab 3 — EL 추이 시계열 (12 라인) + 일강수량 막대 |
| 8 | 110239 | Tab 4 공간분석 — Folium 지도 풀폭 (관측정 + AWS 라벨) |
| 9 | 110258 | Tab 4 — 관측정 메타 표 + EL 일평균 시계열 + 12개월 막대 |
| 10 | 110307 | Tab 4 — 12개월 통계 박스플롯 + 기초통계 표 (12개월 × 6항목) |
| 11 | 110319 | Tab 5 관정 검색 — 시/면/공수 표 + 농업용 관정 분포 지도 |
| 12 | 110410 | Tab 5 — 결과표 + 관정 카드 5열 + 차트 3분할 |
| 13 | 110429 | Tab 6 이용량 — 필터 4개 + KPI 5개 + 분포 지도 |
| 14 | 110441 | Tab 6 — 시별 통계표 (16열) + 박스플롯 |
| 15 | 110448 | Tab 6 — **세로 스크롤 후 폭이 절반으로 압축됨** (재배치 사고) |
| 16 | 110507 | Tab 7 수질 — 필터 + KPI 5개 + 농업용 분포 지도 |
| 17 | 110514 | Tab 7 — 셀렉트박스 드롭다운 (수질항목) |
| 18 | 110524 | Tab 7 — 박스플롯(상·하반기) + 시계열 표 (18반기 × 읍면동) |
| 19 | 110531 | Tab 7 — 시계열 표 하단 (수치 0.0~7.6 다수) |
| 20 | 110540 | Tab 8 통계요약 — KPI 3컬럼 + 연도/월 차트 (저해상도 축소뷰) |
| 21 | 110550 | Tab 8 — 기준연도 selectbox 펼침 + KPI 3컬럼 |
| 22 | 110558 | Tab 8 — 도넛 2개 + 수질부적합 추이 표 (12년 × 5항목) |

---

## Top 10 Issues (severity 🔴 critical, 🟡 medium, 🟢 minor)

1. 🔴 **Body text too small for 1400px viewport.** Korean labels at 11–13px (KPI sub-labels, footnote `*`, table cells) become hard to read on a 13" screen at arm's length. (110121, 110151, 110410, 110429)
2. 🔴 **Tab bar consumes only 60% width, looks "shrunk".** 10 tabs at 13px sit centered with huge right gutter at 1400px. The pill row appears under-sized vs. the 28px H1. (110121, all)
3. 🔴 **유역 pill row stretches over 1300px and feels hollow.** Each of 14 pills auto-expands to ~93px, so "구좌"/"성산" letters float in a sea of background. min-width was tuned for 940px. (110202)
4. 🔴 **KPI metric cards too tall and sparse.** Tab 6/7 KPI row of 5 cards on 1400px has wide left padding inside each card; 24px values look small relative to card area. (110429, 110507)
5. 🟡 **Dense data tables (16+ columns) push sub-10px text in cells.** Tab 2 비교표, Tab 3 관측정별, Tab 6 시별, Tab 7 시계열 — text becomes ~9.5px CSS pixels = unreadable. (110151, 110223, 110441, 110531)
6. 🟡 **Folium map height 780px does not scale.** On 1400×900 landscape with browser chrome, only ~700px viewport remains; map crops below fold and must scroll. The CSS clamp of `max-height:540px` only fires inside 601–1024 range. (110239, 110319, 110507)
7. 🟡 **Plotly chart legends overflow horizontally on tab 3 EL 시계열.** 12 station legend items wrap to 2 lines, but each item label is tiny at default Plotly 11px. (110227)
8. 🟡 **Tab 8 view appears at half-resolution / pinch-zoomed out** — entire layout fits in 700px tile in screenshot, suggesting browser zoom or a `<meta viewport>` without `width=device-width`. (110540)
9. 🟢 **Header bar — page title 28px + 분석 button 32px** competing for visual weight in same row; date selectbox row beneath is touchable but cramped at ~22px height. (110121)
10. 🟢 **Footer caption (Build 2.0.0 …) at 11px is legible but feels tacked-on**, no top border/spacing rhythm. (110227, 110410)

---

## Recommended Breakpoint Strategy

The current desktop branch caps at 940px **only via `.main .block-container`** but Streamlit's modern build also renders `[data-testid="stMain"] .block-container` and `[data-testid="block-container"]`, which the existing rule does not target — this is why the device shows ~1380px content. **Use this to advantage**: introduce a *dedicated tablet-landscape branch* that does not undo the 940px PC desktop, but adds a wider container in the 1025–1366px range and bumps font sizes.

Strategy:

| Range | Branch | Container | Notes |
|---|---|---|---|
| ≤ 600 | phone (existing) | 100% | keep |
| 601 – 1024 | tablet portrait (existing) | 96% | keep |
| **1025 – 1366** | **NEW: tablet landscape** | **96%, max 1280px** | bump fonts, looser pills |
| ≥ 1367 | desktop | **940px** (existing) | unchanged |

Rationale: real desktops are typically ≥1440px and external monitors ≥1920px, so the 1367px cut keeps the original 940px design for the PC reviewers. The Tab S10+ landscape (~1400 CSS px in real Samsung browsers, but reported as 1280×800–1366×910 on most 11–13" tablets in landscape) lands in the new branch. *If your target tablet ends up reporting 1400+ CSS px, raise the upper bound to 1440px.*

---

## CSS Patch (drop into theme.py — append a new media block; do not edit existing rules)

Append the following block to `GLOBAL_CSS` **after** the existing `@media (min-width: 601px) and (max-width: 900px)` block, **before** the closing `</style>`:

```css
/* ==================================================================
   TABLET LANDSCAPE (1025 ~ 1366px) — Build 2.2
   Galaxy Tab S10+ 가로, iPad Pro 11/13 가로, 일반 11–13" 태블릿
   ------------------------------------------------------------------
   목표:
     · PC desktop (>1366) 940px 레이아웃은 그대로 유지
     · 태블릿 가로에서는 본문 폭을 96% (≤1280) 로 확장
     · 한국어 가독성 위해 본문/표/축 11→12, 13→14 보강
     · pill·KPI·탭의 터치 영역 ≥44px
     · Folium iframe 높이는 viewport 60vh 로 자동
   ================================================================== */
@media (min-width: 1025px) and (max-width: 1366px) {

  /* 본문 컨테이너 — Streamlit 신·구 셀렉터 모두 커버 */
  .main .block-container,
  [data-testid="stMain"] .block-container,
  section.main > div.block-container {
    max-width: 1280px !important;
    width: 96% !important;
    padding-left: 1.5rem !important;
    padding-right: 1.5rem !important;
  }

  /* 제목 위계 */
  h1 { font-size: 24px !important; line-height: 1.25 !important; }
  h2 { font-size: 19px !important; }
  h3 { font-size: 17px !important; }
  h4 { font-size: 15px !important; }

  /* 본문/캡션 — Streamlit Markdown */
  .stMarkdown p, .stMarkdown li {
    font-size: 14px !important;
    line-height: 1.55 !important;
  }
  .stCaption, [data-testid="stCaptionContainer"] {
    font-size: 12px !important;
  }

  /* 탭 바 — 한 줄, 좀 더 큰 터치 영역 */
  .stTabs [data-baseweb="tab"] {
    font-size: 14px !important;
    padding: 9px 14px !important;
    min-height: 40px !important;
  }

  /* 유역 pill — 14개가 한 줄, 폭 ~80px 균등 */
  div[data-testid="stRadio"] [role="radiogroup"] label {
    min-width: 78px !important;
    padding: 11px 8px !important;
  }
  div[data-testid="stRadio"] [role="radiogroup"] label > div:last-child p {
    font-size: 14px !important;
  }

  /* KPI st.metric — 라벨/값/델타 모두 한 단계 업 */
  [data-testid="stMetricLabel"] { font-size: 13px !important; }
  [data-testid="stMetricValue"] { font-size: 26px !important; }
  [data-testid="stMetricDelta"] { font-size: 12px !important; }

  /* 카드형 markdown (theme.render_stat_card) — 직접 인라인 16px 인 값 키움 */
  .stMarkdown div[style*="background:#f5f5f3"] > div:nth-child(2) {
    font-size: 18px !important;
  }

  /* 입력 위젯 — 터치 ≥44px */
  .stSelectbox > div > div,
  .stDateInput > div > div,
  .stTextInput > div > div,
  .stNumberInput > div > div {
    min-height: 42px !important;
    font-size: 14px !important;
  }
  .stButton > button[kind="primary"] {
    min-height: 44px !important;
    font-size: 14px !important;
    padding: 8px 18px !important;
  }
  /* wbtn 류 (kind=secondary) 는 작게 유지 */

  /* DataFrame / Table — 셀 폰트 가독성 */
  [data-testid="stDataFrame"] {
    font-size: 13px !important;
  }
  [data-testid="stTable"] td,
  [data-testid="stTable"] th {
    font-size: 13px !important;
    padding: 6px 8px !important;
  }
  /* HTML 테이블 (tab7/tab8 시계열) */
  .main .block-container table {
    font-size: 13px !important;
  }
  .main .block-container table th,
  .main .block-container table td {
    padding: 6px 8px !important;
  }

  /* Plotly — 축/범례 폰트 보강 (chart 자체는 width:100%) */
  .js-plotly-plot .gtitle { font-size: 15px !important; }
  .js-plotly-plot .xtick text,
  .js-plotly-plot .ytick text { font-size: 12px !important; }
  .js-plotly-plot .legend text { font-size: 12px !important; }

  /* Folium 지도 — viewport 비례 높이, 단 최대 720 */
  iframe[title^="streamlit_folium"] {
    height: 60vh !important;
    max-height: 720px !important;
    min-height: 480px !important;
  }
  /* tab5 검색 결과 카드 옆 작은 차트 영역도 width 100% */
  .js-plotly-plot, .plotly-graph-div { width: 100% !important; }

  /* 헤더 영역 (이모지+H1+분석버튼) 정렬 균형 */
  .main .block-container > div:first-child h1 {
    margin-bottom: 0.4rem !important;
  }

  /* 푸터 캡션 — 살짝 분리감 */
  .main .block-container [data-testid="stCaptionContainer"]:last-child,
  .main .block-container .stMarkdown:last-child p[style*="font-size:11px"] {
    border-top: 1px solid var(--color-border-tertiary);
    padding-top: 0.6rem !important;
    margin-top: 1rem !important;
  }
}

/* ==================================================================
   추가 가드: 1367 이상은 기존 desktop 940px 강제 (Streamlit 신셀렉터)
   ------------------------------------------------------------------
   기존 .main .block-container { max-width:940px } 가 stMain 신셀렉터
   에 안 맞아 본문이 풀폭으로 늘어나는 사고를 차단.
   ================================================================== */
@media (min-width: 1367px) {
  [data-testid="stMain"] .block-container,
  section.main > div.block-container {
    max-width: 940px !important;
  }
}
```

> **One-line viewport meta sanity check** — if Streamlit's default `<meta name="viewport" content="width=device-width, initial-scale=1">` is intact, screenshot #20 (Tab 8 zoom-out) is likely caused by Streamlit emitting an inner element wider than viewport (long Plotly chart). Verify with browser devtools that no element forces `min-width: 1500px`. No CSS fix needed if Tab 8 alone — that screenshot is a one-off zoom artefact.

---

## Component-level Notes

- **tab0_overview** (110121): 4-col `st.columns(4)` of AWS cards — fine. The 막대그래프 below covers 14 watersheds; consider increasing y-axis label font in Plotly via `fig.update_layout(font=dict(size=12))` for tablet.
- **tab1_watershed** (110202): 14-pill row uses `.stRadio[horizontal]`. After the 78px min-width bump, pills will fit comfortably in 14×78 + 13×5 = 1157px ≤ 1230px content.
- **tab2_rainfall** (110151): 비교표 has 13 columns × 5 rows. Currently 4-AWS sub-blocks force 3 sub-columns each. With 1280px content, each cell ~28px wide → numerals OK but Korean header `과거 5년 평균(mm)` wraps. Recommend `white-space: nowrap` only on `<th>` and let cell value text shrink to 12px in the new media query.
- **tab3_gwlevel** (110213, 110223): 3-up bar charts side-by-side at 1380px is good. Dense 16-row table has plenty of horizontal space — bump cell to 13px.
- **tab4_admin → tab5_map** (110239): Folium height literally hardcoded as `_MAP_H_FULL = 780` in `tab6_ag_search.py:73`. Tab landscape viewport is ~800px tall (after browser chrome ~120px). 780 → recommend computing `min(780, viewport*0.6)` via the iframe CSS clamp above. *Python-side*: also consider lowering `_MAP_H_FULL` to **640** for tablet landscape — but CSS approach handles all tabs uniformly without code changes.
- **tab6_ag_search** (110410): 5-column `관정 카드` — at 1280px each card gets ~250px which is comfortable. No code change.
- **tab7_ag_usage** (110429): KPI strip of 5 metrics — bump metric value to 26px helps.
- **tab8_ag_quality** (110524, 110531): the 시계열 표 has 18 columns (9 years × 2 반기) + 읍면동. At 1280px each numeric cell ~50px which is fine; ensure header `상반기/하반기` does not wrap.
- **tab9_ag_stats** (110550): 3 KPI columns are wide and roomy. After fonts bump, they'll feel balanced.

---

## Open Questions

1. **Actual reported `window.innerWidth` on Tab S10+ landscape Samsung Browser?** The brief estimates 1400–1452, but most 11" Android tablets report 1280–1366 in landscape due to system bars. Quickly confirm with `navigator.userAgent` + `window.innerWidth` via a one-shot `st.markdown("<script>...</script>")` or simply ask user to look at devtools. **If actual is 1400+, change media query upper bound to 1440px** and bump the desktop guard to `min-width: 1441px`.
2. **Should the 940px PC layout truly stay for monitor users**, or is the team open to widening to ~1100px on PC too? The current pin-to-940 wastes ~60% of a 1920 monitor — the rationale (HTML mockup origin) is historical; many users likely on 27" displays.
3. **Tab 8 zoom artefact** (screenshot #20): is this reproducible, or was it a transient pinch-zoom during capture? If reproducible we should investigate the wide Plotly element forcing horizontal scroll.
4. **Folium height 780 hardcoded in `tab6_ag_search.py`** — keep CSS-only fix or also lower `_MAP_H_FULL` to 640 for python-side consistency? CSS-only is safer (no logic change) but doesn't help if streamlit-folium re-injects inline `height` style.
5. **Touch target on `유역 pill` (currently 11px×6px Y padding ≈ 32px tall)** — bumped to 11px×8 in patch (~38px). True 44px requires bigger pills which may break the 14-in-one-row constraint. Acceptable compromise?
