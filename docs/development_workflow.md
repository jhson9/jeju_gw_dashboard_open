# 🛠 제주 지하수 대시보드 — 개발 워크플로 & 반응형 설계 규칙

> **작성일**: 2026-05-06
> **버전**: 1.0 (Build 2.2 — Tab S10+ 대응 회귀로 추출)
> **목적**: 같은 실수를 반복하지 않기 위한 **체크리스트성 문서**. 새 작업 시작 전, 반응형 코드를 만질 때, 배포 전 반드시 통과해야 할 항목들.

---

## 📑 목차

1. [3단계 개발 파이프라인](#1-3단계-개발-파이프라인)
2. [태블릿 우선, 휴대폰 비공식 정책](#2-태블릿-우선-휴대폰-비공식-정책)
3. [반응형 CSS 설계 원칙 (반드시 지킬 것)](#3-반응형-css-설계-원칙-반드시-지킬-것)
4. [Streamlit 셀렉터 함정 모음](#4-streamlit-셀렉터-함정-모음)
5. [3팀 검증 프로토콜](#5-3팀-검증-프로토콜)
6. [PR/배포 전 체크리스트](#6-pr배포-전-체크리스트)
7. [부록: 알려진 회귀와 해결법](#7-부록-알려진-회귀와-해결법)

---

## 1. 3단계 개발 파이프라인

```
┌──────────────────────────┐    완성 후 이전    ┌────────────────────────┐    배포 후 검토    ┌──────────────────────┐
│ PC 개발 본판             │ ─────────────────► │ OPEN (외부 공개판)       │ ─────────────────► │ 모바일/태블릿 적응    │
│ C:\python\               │                    │ C:\python\              │                    │ (CSS 반응형만 추가)   │
│   jeju_groundwater_      │                    │   jeju_gw_dashboard_open │                    │                       │
│   dashboard              │                    │ (GitHub + Streamlit Cloud) │                  │                       │
└──────────────────────────┘                    └────────────────────────┘                    └──────────────────────┘
```

### 1-1. PC 개발 본판 (`jeju_groundwater_dashboard`)
- **무엇**: 새 기능, 새 탭, 새 분석 로직의 **실험실**.
- **언제**: 모든 신규 작업의 **출발점**.
- **하지 말 것**:
  - ❌ PC 개발 단계에서 모바일/태블릿 CSS 를 미리 만들지 않는다. 디자인이 흔들리는 동안 미디어쿼리 유지 비용이 큼.
  - ❌ 데이터 파이프라인을 두 폴더에서 동시에 만지지 않는다 (drift 발생).
- **할 것**:
  - ✅ PC 940px 디자인 기준 완성도부터.
  - ✅ 데이터 파일 / API 키 / 로컬 캐시는 PC 본판에서만.

### 1-2. OPEN (외부 공개판, `jeju_gw_dashboard_open`)
- **무엇**: PC 본판에서 검증된 코드를 **외부 공개에 적합한 형태**로 정리한 git 연계 버전.
- **언제**: PC 본판에서 한 버전(예: v3) 이 안정화되면 OPEN 으로 통합 배포.
- **하지 말 것**:
  - ❌ OPEN 폴더에서 "임시" 기능을 추가하지 않는다 (PC 본판 누락 → drift).
  - ❌ Quit/Diagnostics 등 운영 전용 UI 노출.
- **할 것**:
  - ✅ 운영 보호: API 키 환경변수, `pages/` 노출 제한, Streamlit Cloud secrets.
  - ✅ 외부 사용자가 마주칠 빈 데이터/에러 케이스 graceful handling.
  - ✅ 외부배포_운영_가이드.md 의 절차 준수.

### 1-3. 모바일/태블릿 적응 (CSS 반응형만)
- **무엇**: OPEN 의 같은 코드베이스 위에 **순수 CSS @media query 만 추가**.
- **언제**: OPEN 가 v3 등으로 안정화된 직후, **PC 와 분리해서**.
- **하지 말 것**:
  - ❌ 모바일을 위해 Python 로직 분기를 추가하지 않는다 (`if is_mobile():`). CSS 로 해결.
  - ❌ 별도 "모바일 전용 탭" 을 만들지 않는다.
  - ❌ 휴대폰(<768px) 을 위한 신규 디자인 작업 금지 — 정책상 비지원 (아래 §2).
- **할 것**:
  - ✅ `theme.py` 의 `GLOBAL_CSS` 안에서만 변경.
  - ✅ 최소 1팀 이상의 검증 에이전트 통과.

---

## 2. 태블릿 우선, 휴대폰 비공식 정책

| 폼팩터 | 정책 | CSS 분기 |
|---|---|---|
| **PC 데스크톱** (≥1500px) | 🟢 **1차 타깃**. 940px 고정 디자인. | `@media (min-width: 1500px)` |
| **태블릿 가로** (1025~1499.99px, 10~13") | 🟢 **2차 타깃**. 1280px 컨테이너로 확장. Tab S10+ 포함. | `@media (min-width: 1025px) and (max-width: 1499.99px)` |
| **태블릿 세로 / 작은 태블릿** (601~1024px) | 🟡 graceful fallback. 깨지지 않을 정도만. | `@media (min-width: 601px) and (max-width: 1024px)` |
| **휴대폰** (≤600px) | 🔴 **공식 비지원**. 코드는 남기되 우선순위 최하. | `@media (max-width: 600px)` |

**왜 휴대폰을 포기했나**: 10탭 × 다중차트 × 16열 표 같은 정보 밀도를 5인치 화면에 욱여넣으면 핵심 가치(공간 비교, 시계열 패턴)가 소실됨. 태블릿 가로(≥1024px) 부터 본 디자인의 의도가 살아남음.

### 🌐 브라우저 우선순위 (Build 2.8 추가)

| 우선순위 | 브라우저 | 정책 |
|---|---|---|
| **1차** | **Chrome** (PC 및 태블릿/모바일) | 표준 렌더링 기준. 모든 디자인 결정의 기준점. |
| 2차 | Samsung Internet (Tab S10+ 등) | 사용자 다수. quirk 발견 시 **Samsung 한정 추가 셀렉터** 로 보강. |
| 3차 | Firefox, Safari, 기타 | 큰 문제 없으면 OK. |

**원칙**:
- Chrome 에서 잘 보이도록 **먼저** 설계.
- Samsung 에서 깨지면 **추가 보강**. 단, Chrome 렌더링은 무영향이어야 함.
- **Samsung 의 비표준 동작에 맞춰 Chrome 디자인을 굽히지 않는다**.

**Samsung Internet 캐시 주의**: 배포 후 Samsung Internet 사용자는 **하드 리프레시** (캐시 삭제) 필요할 수 있음. 새 CSS 가 안 보이면 캐시 의심.

---

## 3. 반응형 CSS 설계 원칙 (반드시 지킬 것)

### 3-1. 컨테이너 너비는 **여러 셀렉터로 동시 선언**

🚫 **잘못된 예** (실제 회귀 사례, Build 2.0 이전):
```css
.main .block-container { max-width: 940px !important; }
```
→ Streamlit 최신 빌드의 `[data-testid="stMain"] .block-container` 를 못 잡아 사실상 무력화.

✅ **올바른 예**:
```css
.main .block-container,
[data-testid="stMain"] .block-container,
section.main > div.block-container {
  max-width: 940px !important;
  padding-left: 1.5rem !important;
  padding-right: 1.5rem !important;
  padding-top: 0.1rem !important;
}
```

### 3-2. 미디어쿼리 경계는 **분수 px** 까지 막는다

🚫 `(min-width: 1025px) and (max-width: 1366px)` → DPR 스케일링으로 `1366.5px` 인 기기는 어느 분기에도 안 잡힘.

✅ `(min-width: 1025px) and (max-width: 1366.99px)` → 갭 0.

### 3-3. `!important` 는 신중하게

`!important` 가 의도된 인라인 스타일을 덮으면 회귀 발생.
- ❌ Folium iframe 에 `height: 60vh !important` 를 걸면 Python `st_folium(..., height=430)` 의 컴팩트 모드를 강제로 480px 로 늘림.
- ❌ `[style*="background:#f5f5f3"] > div:nth-child(2) { font-size: 18px !important }` 는 너무 광범위 — tab7/tab8 의 인라인 22px KPI 카드까지 18px 로 축소.

규칙:
1. `!important` 셀렉터는 **클래스 hook (`.stat-card`)** 으로 좁힌다. 인라인 스타일 패턴 매칭 금지.
2. Python 측 명시 픽셀(예: `height=430`) 은 **CSS 로 덮지 않는다**. 정말 필요하면 클래스 hook 으로 특정 인스턴스만.

### 3-4. 한국어 가독성 폰트 하한

| 위치 | 최소 폰트 |
|---|---|
| 본문(p, li) | **14px** (PC) / 14px (태블릿) |
| 표 셀 | **12px** (PC) / 13px (태블릿) |
| caption | **11px** |
| 차트 axis | **11px** |
| 절대 금지 | < 10.5px (한자/한글 구별 불가) |

### 3-5. 터치 타깃

- 태블릿 분기에서 입력 위젯 `min-height ≥ 40px`.
- Primary 버튼은 ≥ 44px (Apple HIG).
- pill 라디오는 36px 까지 허용 (한 줄 fitting 우선).

### 3-6. cascade 순서 — `apply_theme()` 와 `app.py` 인라인 `<style>` 의 관계

`theme.py` 의 `GLOBAL_CSS` 가 먼저, `app.py` 의 인라인 `<style>` 이 **나중에** 로드됨. 같은 specificity 의 `!important` 라면 **app.py 이 이김**.

→ 새로운 미디어쿼리에서 탭/라디오 스타일을 손대려 한다면 **먼저 app.py 인라인 `<style>` 에 동일 셀렉터가 있는지** 확인. 있다면:
- 옵션 A: app.py 인라인을 데스크톱(`@media (min-width: 1367px)`) 으로 스코프.
- 옵션 B: theme.py 의 셀렉터를 더 구체화 (`body .stTabs ...`).
- 옵션 C: 그 규칙을 theme.py 에서 빼고 인라인이 모든 분기에 적용되도록.

### 3-7. PC 디자인을 **모바일 작업으로 깨지 않는다**

✅ 모바일 분기는 항상 `@media (max-width: ...)` 또는 `(min-width: x) and (max-width: y)` 로 **상한이 있어야** 한다.
✅ 데스크톱(≥1367) 가드는 항상 마지막에, max-width 를 940 으로 **다시 못박는다**.
❌ `:root` 변수만 바꿔서 "모든 분기에 영향" 같은 매크로 변경 금지.

---

## 4. Streamlit 셀렉터 함정 모음

| 어떤 요소 | 잘못된 셀렉터 | 올바른 셀렉터 |
|---|---|---|
| 본문 컨테이너 | `.main .block-container` 단독 | `.main .block-container, [data-testid="stMain"] .block-container, section.main > div.block-container` |
| 탭 리스트 | `.stTabs > div` | `.stTabs [data-baseweb="tab-list"]` |
| 개별 탭 | `.stTabs button` | `.stTabs [data-baseweb="tab"]` (active: `[aria-selected="true"]`) |
| 라디오 그룹 | `.stRadio` | `div[data-testid="stRadio"] [role="radiogroup"]` |
| 컬럼 블록 | `.row-widget` | `[data-testid="stHorizontalBlock"] > [data-testid="column"]` |
| 메트릭 위젯 값 | `.metric-value` | `[data-testid="stMetricValue"]` |
| 데이터프레임 | `.dataframe` | `[data-testid="stDataFrame"]` |
| Folium iframe | `iframe` | `iframe[title^="streamlit_folium"]` |
| 사용자 마크다운 div | `[style*="..."]` 패턴 매칭 | **클래스 hook 추가**: `<div class="stat-card" style="...">` 후 `.stat-card` |

### 위험: 인라인 스타일 패턴 매칭

`[style*="background:#f5f5f3"]` 같은 attribute selector 는 다음 모두 매치:
- `theme.render_stat_card` (의도)
- `theme.render_note_box` (의도 안 함, 다행히 자식 div 가 없어 `:nth-child(2)` 로 추가 필터링하면 빠짐)
- `tab7:362`, `tab8:898` 의 인라인 KPI 카드 (의도 안 함, 자식 div 3개 있어 매치됨!) — **회귀 발생 지점**

**규칙**: 의도된 컴포넌트를 노릴 때는 **반드시 클래스 hook** 을 붙인다.

---

## 5. 3팀 검증 프로토콜

반응형/디자인 변경 후 **반드시** 3팀 병렬 검증 통과:

### 팀 A — 기능 회귀 (Functional Regression)
**보는 것**:
- PC 데스크톱 분기 미변경 여부
- cascade & specificity 충돌
- JS 의존 셀렉터(예: `st.tabs` 활성탭 보존 hack) 미변경
- print stylesheet 미오염
- Python 측 명시 height/width 와 CSS 충돌

### 팀 B — 레이아웃 정확성 (Layout & Responsive)
**보는 것**:
- 미디어쿼리 갭/오버랩 (분수 px 포함)
- 14-pill, 10-tab 등 고정 요소 fit 산수
- 컨테이너 너비 수식: `min(width%, max-width)`
- 터치 타깃 ≥ 권고치 audit
- 휴대폰 분기 cascading 안전성

### 팀 C — 데이터/로직 무결성 (Data & Logic)
**보는 것**:
- 셀렉터의 **의도 외 매치** (`render_note_box`, 인라인 KPI 카드)
- 표 셀 truncation/overflow
- Plotly width override 가 axis 범위에 영향 주는지
- 캐시 무관성, 리포트 생성기 무관성
- selection state, 활성탭 보존 등 상태 흐름

### 합의 규칙
- 🔴 가 1개라도 있으면 **무조건 수정 후 재검증**.
- 🟡 가 2팀 이상에서 동일 항목으로 나오면 **수정 권장**.
- VERDICT 가 SHIP/SAFE/LAYOUT-OK 로 모두 통과해야 PR 머지.

---

## 6. PR/배포 전 체크리스트

새 반응형 작업 직전:
- [ ] PC 본판에서 해당 기능이 **이미 안정화** 되어 있는가? (drift 방지)
- [ ] 변경 범위가 `theme.py` 의 `GLOBAL_CSS` + 클래스 hook 추가 정도로 국한되는가?
- [ ] Python 로직(`if is_mobile()`) 분기를 추가하지 않았는가?

작업 중:
- [ ] 새 미디어쿼리는 **분수 px** 까지 막혀 있는가?
- [ ] 새 `!important` 셀렉터는 **클래스 hook** 으로 좁혀졌는가?
- [ ] Python 측 명시 픽셀(`height=`) 을 CSS 로 덮지 않았는가?
- [ ] 컨테이너 너비는 **3중 셀렉터** 로 선언했는가?
- [ ] 한국어 본문 폰트가 14px 이상 유지되는가?

배포 전:
- [ ] 3팀 검증 통과 (A 🟢 / B 🟢 / C 🟢)?
- [ ] `python -c "import ast; ast.parse(open('src/dashboard/theme.py').read())"` 통과?
- [ ] PC 모니터(≥1367px) 에서 940px 디자인 그대로 인가?
- [ ] Tab S10+ 가로(≈1400px) 에서 콘텐츠가 1280px 컨테이너로 확장되는가?
- [ ] git diff 가 **CSS-only** 이거나 명확한 클래스 hook 추가 정도인가?

---

## 7. 부록: 알려진 회귀와 해결법

### R-1. Build 2.0 — Tab S10 에서 글자가 작게 보임
- **원인**: `.main .block-container { max-width: 940px }` 가 Streamlit 최신 빌드의 `[data-testid="stMain"]` 를 못 잡아 콘텐츠는 1380px 로 펼쳐졌으나 폰트는 940px 기준으로 설계되어 있어 시각적으로 작아 보임.
- **해결 (Build 2.2)**: 1025~1366px 분기 신설 + 컨테이너 1280px + 폰트 일괄 +1~2pt + 데스크톱(≥1367) 가드 재선언.

### R-2. Build 2.1 — 인라인 KPI 카드가 18px 로 축소
- **원인**: `[style*="background:#f5f5f3"] > div:nth-child(2) {font-size:18px !important}` 가 의도(`render_stat_card`) 외에 tab7:362, tab8:898 의 22px KPI 인라인 카드까지 매치.
- **해결 (Build 2.2)**: `render_stat_card` 에 `class="stat-card"` 추가, 셀렉터를 `.stat-card > div:nth-child(2)` 로 좁힘.

### R-3. Build 2.1 — Folium 컴팩트 지도가 강제로 늘어남
- **원인**: `iframe[title^="streamlit_folium"] { min-height: 480px !important }` 가 Python `st_folium(..., height=430)` 컴팩트 모드를 480px 로 강제 확장.
- **해결 (Build 2.2)**: 태블릿 분기에서 iframe height 오버라이드 자체를 제거. Python 측 명시 픽셀 신뢰.

### R-4. Build 1.x — 농업용 관정 탭 AttributeError
- **원인**: 데이터 스키마 변경 후 OPEN 폴더 동기화 누락.
- **해결**: PC 본판 안정화 후 OPEN 으로 일괄 이전, drift 검사 자동화 (TODO).

### R-5. Build 2.x — st.tabs 활성탭 초기화
- **원인**: Streamlit 1.49 미만에서 `st.tabs(key=)` 미지원.
- **해결**: try/except 폴백 + JavaScript 로 `aria-selected` 추적해서 rerun 시 클릭 복원 (`app.py:480-600`).

### R-6. Build 2.5–2.8 — Samsung Internet 의 selectbox 한글 받침 클리핑
- **현상**: Samsung Internet 브라우저(Tab S10+) 에서 `st.selectbox` 닫힌 상태 표시값의 한글 받침이 잘려 "전체 → 저췌", "2월 → 2윌" 처럼 보임. **Chrome 에서는 멀쩡**.
- **잘못된 가설(Build 2.5–2.6)**: line-height 부족. → 1.45→1.6→1.8 점진 증가, 컨테이너 높이 64px 까지 증가 → 효과 없음.
- **잘못된 가설(Build 2.7)**: `:not(input)` 으로 input element 제외해서 표시값에 cascade 안 닿음. → input 명시 룰 추가 → **부분 효과**.
- **진짜 원인 (Build 2.8, 에이전트 진단)**: baseweb 의 닫힌 상태 표시값은 `<input>` 도 `<input>` 의 value 도 아닌 **sibling `<div id$="-singleValue">` (StyledSingleValue)**. 이 셀렉터가 모든 빌드에서 누락되어 있었음.
- **해결**: 4중 셀렉터(input + `[role="combobox"]` + `div[id$="-singleValue"]` + `[data-baseweb="select-control"] > div > div`) + padding 0 + overflow:visible 의 조합으로 baseweb 의 어떤 마이너 빌드에서도 표시값에 닿도록 보장.
- **교훈**: baseweb / Streamlit 의 DOM 구조는 마이너 버전마다 변함. CSS 셀렉터 작성 시 **superset 4중 보강** 이 안전. 또한 같은 코드도 브라우저에 따라 다른 element 가 visible 할 수 있음 — Samsung Internet 캐시는 매우 공격적이라 배포 후 하드 리프레시 필요.

---

> 이 문서는 **살아있는 문서**. 새 회귀가 생기면 §7 에 추가하고, 새 규칙이 필요하면 §3 에 보강하세요.
