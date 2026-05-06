# 📄 작업 보고서 — 태블릿 반응형 회귀 추적 & 해소 (2026-05-06)

> **작업 일자**: 2026-05-06
> **소요 시간**: 약 2시간 (8단계 빌드 + 문서/스킬/메모리)
> **최종 결과**: Build 2.8 배포 완료, Chrome / Samsung Internet 양쪽 검증 통과
> **작업 범위**: theme.py CSS 패치 + 문서 3건 + 스킬 1건 + 메모리 5건
> **커밋**: `60a3d67`, `f0d8ba9` (`origin/main` 동기화 완료)

---

## 1. Executive Summary

### 처음 들어온 요구
- Tab S10+ 가로 모드 22장 스크린샷 첨부
- "디자인 에이전트가 분석을 해서, 모바일 버전에서 글자크기 등 부자연스러운 부분 및 디자인을 전반적으로 업데이트"
- "검증에이전트 3팀을 두어서, 각기 다른 방향으로 오류를 검증"
- 향후 같은 실수 반복하지 않도록 **문서/스킬 보관**
- 휴대폰은 포기, **태블릿 중심**

### 결과적으로 해소한 회귀
1. **R-1** Build 2.0 — 940px 컨테이너 캡 누수 (Streamlit modern selector 미커버)
2. **R-2** Build 2.1 — 인라인 패턴 매칭이 tab7/tab8 KPI 22px → 18px 잘못 축소
3. **R-3** Build 2.1 — Folium iframe `min-height: 480 !important` 가 컴팩트 430px 강제 확장
4. **R-6** Build 2.5–2.8 — Samsung Internet 의 baseweb StyledSingleValue 한글 받침 클리핑

### 만들어진 자산
- 신규 미디어쿼리 2개 (태블릿 가로 1025–1499.99px / 데스크톱 가드 ≥1500px)
- 신규 문서 3건 (`work_report_2026-05-06.md`(현재) / `development_workflow.md` / `design_review_tab_s10.md`)
- 신규 스킬 1건 (`.claude/skills/responsive-development/SKILL.md` — gitignored, 다음 세션 자동 로드)
- 신규 메모리 5건 (3단계 파이프라인 / 휴대폰 비지원 / 3팀 검증 / Streamlit 셀렉터 / 브라우저 우선순위)

---

## 2. 시작 상황 (Build 2.0 이전)

### 코드 상태
- `theme.py` 의 `GLOBAL_CSS` 에 휴대폰(≤600px), 태블릿 세로(601–1024px), 데스크톱(≥1025px, max-width 940px) 3분기 존재
- 휴대폰/태블릿 세로 폼팩터 일부 대응
- 태블릿 가로 분기 **없음**

### 보고된 문제
- Tab S10+ 가로(약 1400~1500px CSS) 에서 콘텐츠가 작게 보이고 빈 공간이 큼
- 한글 받침 (전체 → 저췌) 가 잘려 보임
- 일부 위젯이 어색하게 정렬됨

### 진단 첫 가설 (틀렸음)
- "콘텐츠가 940px 로 묶여 있어 작아 보이는 것"
  - **사실**: 940px 룰이 modern Streamlit `[data-testid="stMain"]` 를 못 잡아 콘텐츠는 ~1380px 로 펼쳐지고 있었음. 폰트가 940 기준으로 설계되어 작아 보였던 것.

---

## 3. 작업 타임라인 (Build 2.2 → 2.8)

| Build | 핵심 변경 | 결과 |
|---|---|---|
| 2.2 | 디자인 에이전트의 22장 스크린샷 분석 → 신규 미디어쿼리 2개 추가 (1025–1366.99 태블릿 가로 / ≥1367 데스크톱 가드) + 컨테이너 1280px / 폰트 일괄 보강 / 14-pill 78px / KPI 26px | 디자인 적용. 검증 에이전트 3팀 병렬로 검토 |
| 2.2-fix | 3팀 검증에서 🔴 2건 / 🟡 4건 발견 → **stat-card 클래스 hook**, **Folium iframe override 제거**, **분수 px 갭 보정**, **데스크톱 가드 padding 추가**, **app.py 인라인 cascade 충돌 회피** | 검증 통과. 첫 PR-ready 상태 |
| 2.3 | "전체 → 저췌" 한글 받침 클리핑 보고 → 모든 반응형 분기에 selectbox font-size 13px + line-height 1.45 추가 | 부분 효과 |
| 2.4 | Tab S10+ 가 1367px 이상 보고 가능성 발견 → 태블릿 가로 상한 **1366.99 → 1499.99** 확장, 데스크톱 가드 **≥1367 → ≥1500** 으로 후퇴. 셀렉터에 `*:not(svg):not(path):not(input)` universal 적용 | 일부 viewport 만 fix |
| 2.5 | 여전히 클리핑 → 더 강한 조합: font 12px + line-height 1.8 + min-height 46px + overflow:visible | 닫힌 상태는 여전히 클리핑 |
| 2.6 | 사용자 요청 "버튼 높이 1.4배" → min-height 64px / primary 버튼 62px | 너무 컸다고 환원 요청 |
| 2.7 | 진단: `:not(input)` 으로 input 제외해서 closed-state 표시값에 안 닿는 가설. height 64 → 48px 환원, `:not(input)` 제거 + 명시적 `.stSelectbox input` 룰 | 부분 효과. 진단 에이전트 추가 의뢰 |
| 2.8 | **에이전트 진단**: 닫힌 상태 표시값은 `<input>` 이 아니라 sibling **`<div id$="-singleValue">`** (StyledSingleValue) 가 carry. 4중 셀렉터 superset (`input` + `[role=combobox]` + `div[id$="-singleValue"]` + `[data-baseweb="select-control"] > div > div`) + padding 0 + overflow:visible | ✅ Chrome / Samsung Internet 양쪽 클리핑 해소 |

### 사용자 검증 결과 (Build 2.8 배포 후)
- ✅ Chrome (PC, 태블릿) — 클리핑 없음, 940px 데스크톱 무영향
- ✅ Samsung Internet (Tab S10+) — 하드 리프레시 후 클리핑 해소
- 추가 발견: **Chrome 은 좁게(탭 줄바꿈) / Samsung 은 넓게** 렌더 → viewport 보고 차이로 자연스러운 동작
- 결론적 정책: **Chrome 1차, Samsung 2차** 우선순위 설정

---

## 4. 핵심 기술 변경 사항

### theme.py — Build 2.8 최종 형태

#### 신규 미디어쿼리 1: 태블릿 가로 (1025–1499.99px)
```css
@media (min-width: 1025px) and (max-width: 1499.99px) {
  /* 컨테이너 — 3중 셀렉터로 modern Streamlit 누수 차단 */
  .main .block-container,
  [data-testid="stMain"] .block-container,
  section.main > div.block-container {
    max-width: 1280px !important;
    width: 96% !important;
    padding-left: 1.5rem !important;
    padding-right: 1.5rem !important;
    padding-top: 0.1rem !important;
  }
  /* 제목 위계 */
  h1 { font-size: 24px !important; line-height: 1.25 !important; }
  h2 { font-size: 19px !important; }
  h3 { font-size: 17px !important; }
  /* 본문, KPI, 라디오, 표, Plotly — 일괄 14px 기준 */
  /* ... (생략, theme.py:415–510 참조) */

  /* selectbox 한글 클리핑 해소 — 4중 superset */
  .stSelectbox div[data-baseweb="select"] input,
  .stSelectbox div[data-baseweb="select"] input[role="combobox"],
  .stSelectbox div[data-baseweb="select"] [role="combobox"],
  .stSelectbox div[data-baseweb="select"] div[id$="-singleValue"],
  .stSelectbox div[data-baseweb="select"] [data-baseweb="select-control"] > div > div {
    font-size: 12px !important;
    line-height: 1.8 !important;
    height: auto !important;
    min-height: 0 !important;
    padding-top: 0 !important;
    padding-bottom: 0 !important;
    overflow: visible !important;
  }
}
```

#### 신규 미디어쿼리 2: 데스크톱 가드 (≥1500px)
```css
@media (min-width: 1500px) {
  /* PC 940px 디자인 못박음 (Streamlit modern selector 누수 차단) */
  [data-testid="stMain"] .block-container,
  section.main > div.block-container {
    max-width: 940px !important;
    padding-left: 1.5rem !important;
    padding-right: 1.5rem !important;
    padding-top: 0.1rem !important;
  }
}
```

#### 태블릿 세로 (601–1024px) — selectbox 부분만 강화
태블릿 가로와 동일한 4중 셀렉터 패턴 추가 (split-screen / DeX 등에서 viewport 가 1024 이하로 떨어지는 케이스 대비).

#### `render_stat_card` — 클래스 hook 추가
```python
html = (
    f'<div class="stat-card" style="background:#f5f5f3;border-radius:8px;...">'
    # 인라인 패턴 매칭 회귀 차단 (R-2)
)
```
CSS 셀렉터를 `.stMarkdown div.stat-card > div:nth-child(2)` 로 좁힘.

### 변경하지 않은 것 (의도적 보존)
- **app.py 인라인 `<style>`** (line 226–239): 탭 폰트 15.4px / padding 9px 11px — cascade 순서로 어차피 이김. 새 룰은 충돌 회피 위해 탭 font-size 미설정.
- **Folium iframe height**: Python `st_folium(..., height=N)` 의 의도를 CSS 로 덮지 않음 (R-3 회귀 방지).
- **휴대폰 분기(≤600px)**: 사용자 미언급, 공식 비지원이라 손대지 않음 (Build 2.3 상태 유지).
- **PC 데스크톱(≥1500px)**: 940px 디자인 보존, selectbox CSS 변경 없음.

---

## 5. 발견된 이슈와 해결 (R-1 ~ R-6)

### R-1 — Streamlit modern selector 누수 (Build 2.0)
- **현상**: `.main .block-container { max-width: 940px }` 단독 셀렉터가 Streamlit 최신 빌드의 `[data-testid="stMain"] .block-container` 를 못 잡아 데스크톱에서도 콘텐츠 ~1380px 누수.
- **해결**: 3중 셀렉터로 동시 선언 — `.main .block-container, [data-testid="stMain"] .block-container, section.main > div.block-container`.
- **교훈**: Streamlit 의 DOM 셀렉터는 마이너 버전마다 변함. 컨테이너 너비 같은 핵심 룰은 superset 셀렉터 사용.

### R-2 — 인라인 패턴 매칭 의도 외 매치 (Build 2.1)
- **현상**: `.stMarkdown div[style*="background:#f5f5f3"] > div:nth-child(2) { font-size: 18px !important }` 가 tab7/tab8 의 인라인 KPI 카드(`tab7_ag_usage.py:362`, `tab8_ag_quality.py:898`)의 의도된 22px 값을 18px 로 잘못 축소.
- **해결**: `render_stat_card` 에 `class="stat-card"` 추가, 셀렉터를 `.stMarkdown div.stat-card > div:nth-child(2)` 로 좁힘.
- **교훈**: `[style*="..."]` 같은 attribute selector 는 의도 외 컴포넌트에 매치되기 쉬움. **반드시 클래스 hook 사용**.

### R-3 — Folium iframe Python 픽셀 강제 덮어쓰기 (Build 2.1)
- **현상**: `iframe[title^="streamlit_folium"] { height: 60vh !important; min-height: 480px !important }` 가 `tab6_ag_search.py:73` 의 컴팩트 모드 `_MAP_H_COMPACT = 430` 을 480px 로 강제 확장.
- **해결**: 태블릿 분기에서 iframe height 오버라이드 자체 제거. Python 측 명시 픽셀 신뢰.
- **교훈**: Python 에서 `height=N` 처럼 명시적으로 넘긴 픽셀은 CSS `!important` 로 덮지 않는다.

### R-6 — Samsung Internet baseweb StyledSingleValue 클리핑 (Build 2.5–2.8)
- **현상**: 닫힌 상태 selectbox 표시값(예: "전체", "2026년") 의 한글 받침이 Samsung Internet 에서 잘림. Chrome 에서는 멀쩡.
- **잘못된 가설들** (Build 2.5–2.7):
  - line-height 부족 → 1.45 → 1.6 → 1.8 점진 증가 → 효과 없음
  - 컨테이너 높이 부족 → 46 → 64px → 효과 없음
  - `:not(input)` 으로 input 제외 → 표시값에 cascade 안 닿음 → 명시적 `.stSelectbox input` 룰 추가 → 부분 효과
- **진짜 원인** (에이전트 진단, Build 2.8): 닫힌 상태 표시값은 `<input>` 도 `<input>` 의 value 도 아닌 **sibling `<div id$="-singleValue">` (baseweb StyledSingleValue)**. 이 셀렉터가 모든 빌드에서 누락.
- **해결**: 4중 셀렉터 superset (`input` + `[role="combobox"]` + `div[id$="-singleValue"]` + `[data-baseweb="select-control"] > div > div`) + padding 0 + overflow:visible.
- **교훈**:
  1. baseweb / Streamlit DOM 은 마이너 버전마다 다름 → 4중 superset 안전
  2. 같은 코드도 브라우저마다 다른 element 가 visible 일 수 있음
  3. **Samsung Internet 캐시는 매우 공격적** → 배포 후 사용자 하드 리프레시 안내 필수
  4. **Chrome 1차 / Samsung 2차** 우선순위 정책

---

## 6. 미래 작업 플레이북 — PC → OPEN 동기화 시

> 사용자가 PC 본판(`C:\python\jeju_groundwater_dashboard`) 에서 v3 등을 완성한 후 OPEN(이 폴더) 으로 이전할 때의 표준 절차.

### 단계 1: 사전 점검 (작업 시작 전)
```bash
# 이 워크스페이스에서
git pull origin main                # 동료 변경사항 동기화
git status                          # working tree clean 인지 확인
python -c "import ast; ast.parse(open('src/dashboard/app.py').read())"  # 문법 baseline 확인
```

### 단계 2: PC 본판 변경사항 가져오기
- PC 본판은 외부 폴더 (`C:\python\jeju_groundwater_dashboard`) 라 이 워크스페이스에서 직접 접근 불가.
- 사용자가 변경된 파일을 이 폴더로 복사 또는 ZIP 으로 가져옴.
- 이전 패턴: `jeju_groundwater_dashboard V2.0_260505.zip` 같이 버전별 ZIP.

### 단계 3: OPEN 보호 항목 보존 (필수!)
PC 본판이 덮어쓸 때 다음 OPEN 전용 항목들을 보호:

| 항목 | 위치 | 보존 이유 |
|---|---|---|
| Quit 버튼 제거 | `app.py` | 외부 공개 — 운영자 전용 UI 노출 금지 |
| Admin 탭 제거 | `app.py` (`tab_admin` 미import) | 외부 공개 — 데이터 파이프라인 UI 미노출 |
| `.gitignore` 데이터 제외 주석 처리 | `.gitignore` | 외부 공개판은 데이터 파일 동봉 가능 |
| `config.py` `.env` + `st.secrets` 양쪽 호환 | `config.py` | Streamlit Cloud Secrets 호환 |
| **태블릿 반응형 미디어쿼리 2개** | `theme.py` (1025–1499.99 + ≥1500) | 본 보고서의 핵심 산물 |
| **`render_stat_card` 의 `class="stat-card"`** | `theme.py` 함수 | R-2 회귀 차단 |

복사 전 위 6개 항목을 별도 백업 → 복사 후 재적용. 또는 `git diff` 로 차이 확인 후 선택적 머지.

### 단계 4: 반응형 변경 시 3팀 검증 (의무)
PC 본판에서 새 탭/UI 가 추가되었거나 `theme.py` 가 변경되었다면:

```
팀 A — 기능 회귀: PC 분기 미변경, JS 셀렉터, Python 픽셀 충돌
팀 B — 레이아웃: 미디어쿼리 갭, fit 산수, 컨테이너 수식
팀 C — 데이터/로직: 셀렉터 의도 외 매치, 표 truncation, 상태 흐름
```

3팀 모두 SHIP/SAFE/LAYOUT-OK 통과해야 푸시.

### 단계 5: 배포 검증 절차
```bash
git push origin main           # Streamlit Cloud 자동 배포
```
1~2분 대기 후 사용자 측 검증:
- [ ] **Chrome PC** (940px 데스크톱) — 디자인 무영향
- [ ] **Chrome 태블릿** — 1280px 컨테이너로 펼쳐짐
- [ ] **Samsung Internet Tab S10+** (하드 리프레시 후) — 한글 받침 정상
- [ ] 모든 selectbox 닫힌 상태 표시값 정상

### 단계 6: 회귀 발견 시 대응
- 단순 CSS 회귀 → `theme.py` 의 적절한 미디어쿼리에서 fix
- DOM 변경 회귀 → 4중 셀렉터 superset 패턴 적용
- 브라우저별 차이 → Chrome 우선, Samsung 보강

---

## 7. 만들어진 자산

### 문서 (git tracked)
| 파일 | 역할 |
|---|---|
| `docs/work_report_2026-05-06.md` | **이 보고서** — 1회성 작업 기록 |
| `docs/development_workflow.md` | 영구 워크플로 가이드 — 폼팩터/브라우저/셀렉터/검증 |
| `docs/design_review_tab_s10.md` | 디자인 에이전트의 1회성 분석 보고서 |

### 스킬 (gitignored, 다음 세션 자동 로드)
- `.claude/skills/responsive-development/SKILL.md`
  - 반응형/CSS/디자인 작업 시 **자동 트리거**
  - Hard rules / Streamlit selector 함정 / 3팀 검증 / 알려진 회귀 / Chrome 우선

### 메모리 (다음 세션 자동 로드)
- `project_dev_pipeline.md` — 3단계 개발 파이프라인 (PC → OPEN → 태블릿)
- `feedback_responsive_policy.md` — 폼팩터 정책 (휴대폰 비지원)
- `feedback_three_team_verification.md` — 3팀 검증 프로토콜
- `feedback_streamlit_selectors.md` — Streamlit 셀렉터 함정
- `feedback_browser_priority.md` — Chrome 1차 / Samsung 2차

---

## 8. 측정 결과

| 측정 항목 | 값 |
|---|---|
| 작성한 코드 | theme.py +207 라인, -1 라인 |
| 작성한 문서 | 3건 (총 ~30,000 자 한글) |
| 호출한 Agent | 디자인 1 + 검증 3(병렬) + 진단 1 = **5회** |
| 발견한 회귀 | 4건 (R-1, R-2, R-3, R-6) |
| 빌드 횟수 | 8 (2.0 → 2.8) |
| 사용자 실기 검증 | Chrome ✅ / Samsung Internet ✅ |

### Token / 효율 메모
- 5회 에이전트 호출 모두 백그라운드 + 병렬 가능한 것은 병렬 실행
- 단일 검증 실패 시 즉시 가설 수정 → 다음 빌드로 진입 (평균 1회 빌드당 약 10–15분)
- 같은 패턴이 반복되면 **메모리/스킬 로 박아 다음 세션에 자동 로드**

---

## 9. 기술 부채 & 후속 항목

### 단기 (다음 작업 시 검토)
- [ ] 태블릿 세로 분기(601–1024) 의 selectbox 4중 셀렉터가 split-screen / DeX 환경에서 작동하는지 실기 확인
- [ ] Tab S10+ 가 실제로 보고하는 viewport CSS px 측정 (`window.innerWidth`) → 1499.99 상한이 정말 안전한지 확인
- [ ] PC 본판 (`jeju_groundwater_dashboard`) 에 동일 변경 역이전 — drift 방지

### 중기
- [ ] PC 본판과 OPEN 의 자동 drift 검출 스크립트 (`git diff` 기반 차이 리포트)
- [ ] 휴대폰(<600px) 분기의 코드 정리 — 공식 비지원 명시 후 더 graceful 한 fallback 만 남기고 신경 안 쓰기
- [ ] Folium iframe 의 viewport-aware 높이 정책 (Python 측에서 viewport 감지해 height 결정?)

### 장기
- [ ] Streamlit + baseweb 의 DOM 셀렉터 안정성 모니터링 — 마이너 버전 업데이트 시 R-1 / R-6 같은 회귀가 되살아나는지
- [ ] 3팀 검증 자동화 (CI 에서 PR 시 자동 트리거)
- [ ] 디자인 시스템 토큰화 (현재 `:root` 변수 일부만 사용 → 완전한 토큰 system 으로)

---

## 10. 다음 세션 빠른 시작 (사용자용)

### "이어서 작업하자" 한마디면 가능
- 메모리가 자동 로드 → 3단계 파이프라인 / Chrome 우선 / 3팀 검증 등 정책 자동 인지
- 스킬이 자동 로드 → CSS / @media / Streamlit 셀렉터 작업 시 자동 트리거
- `docs/TODO_다음작업.md` 상단 체크포인트로 직전 상태 즉시 파악

### PC 본판에서 v3 완성 후 OPEN 동기화 시
1. 사용자: "PC 본판 v3 변경사항을 OPEN 으로 이전해줘"
2. 저(Claude): 메모리/스킬 자동 로드 → §6 플레이북 자동 적용 → OPEN 보호 항목 6개 보존 → PC 변경사항 머지 → 3팀 검증 → 배포

이 보고서(`docs/work_report_2026-05-06.md`) 를 명시 참조하라고 하면 더 빠르게 진행됩니다:
> "이전에 작성한 work_report_2026-05-06.md 를 참고해서 PC 본판 변경사항 이전해줘"

---

**작성**: 2026-05-06
**다음 업데이트**: PC 본판 v3 완성 후 OPEN 동기화 시점
