# 📝 변경 이력 (Changelog)

모든 주요 변경사항을 이 파일에 기록합니다.  
버전은 **0.1씩 증가**하며, 1.0에 도달하면 정식 릴리스입니다.

---

## [Build 0.8.0] - 2026-04-22

### 🎨 4개 탭 UI 구조 전환 (구조 재편 1단계)

#### Problem (요구사항)
대시보드가 세로로 너무 길어져 (4페이지 PDF) 가독성 저하.
기존 HTML 대시보드(v8)처럼 탭 구조로 정리 필요.

#### Added (추가)
- **4개 탭 구조 도입**
  - `📊 대시보드 요약` (신규) : 기존 수집/상태/리포트 섹션 통합
  - `📋 수역별 현황` : HTML v8의 s0 섹션에 대응
  - `🌧️ 강수량 분석` : HTML v8의 s1 섹션에 대응
  - `💧 지하수위 분석` : HTML v8의 s2 섹션에 대응

- **탭 렌더러 함수 4개 분리**
  - `render_tab_summary()`, `render_tab_watershed()`,
    `render_tab_rainfall()`, `render_tab_gwlevel()`
  - 향후 별도 파일로 분리하기 쉽도록 구조 설계
  - 현재는 app.py 내부에 두되 함수 경계 명확히

- **캐시 데이터 로딩**
  - `@st.cache_data(ttl=60)` 로 ASOS, 수역 데이터 캐싱
  - 탭 전환 시 재로드 방지
  - 수집 버튼 클릭 시 `st.cache_data.clear()` 로 자동 무효화

- **분석 기간 배지 (HTML 원본 계승)**
  - 헤더 아래에 파란색 배지로 M-2/M-1/M 표시
  - M 배지는 빨간색으로 강조 (현재 기간 구분)
  - 규칙 모드 (1~15일 / 16일+) 명시

- **탭 스타일링 CSS**
  - 선택된 탭은 파란색 배경 + 흰 글씨
  - 비선택 탭은 흰 배경 + 테두리
  - 호버 효과

#### Changed (변경)
- 기존의 긴 세로 스크롤 → 탭별 분리
- 수집 버튼과 시스템 상태 → 탭 0 (대시보드 요약)
- ASOS 차트는 [📊 요약] 탭의 expander로 이동
- 헤더에 기준일 + 버전 표시 추가

#### Unchanged (보존)
- **모든 기존 기능은 100% 보존됨**:
  - 사이드바의 기준일 선택기
  - M-2·M-1·M 비교표 (강수량 + 유효강수)
  - 수역별 지하수위 차트 및 편차 차트
  - 리포트 생성 기능

#### Placeholder (다음 빌드 예정)
각 탭에 `📌 Build 0.8.X 에서 완전 구현 예정` 안내 표시:
- **Build 0.8.1**: 탭 1 (HTML s0) 완전 이식
  - 수역 버튼 + 요약 카드 + 강수량/지하수위 차트 나란히 + 표A/B
- **Build 0.8.2**: 탭 2 (HTML s1) 완전 이식
  - 지점별 요약 카드 4개 + 강수량 차트 2×2 + 유효강수 차트 2×2
- **Build 0.8.3**: 탭 3 (HTML s2) 완전 이식
  - 수역 선택 + M-2·M-1·M 카드 + 전체 수역 요약표

#### Technical (설계 원칙)
- **탭 1 방식 (모든 탭이 한 페이지에 있음)**: `st.tabs()` 는 내부적으로
  모든 탭 내용을 DOM에 렌더링하고 CSS로 숨기므로, 사용자가 원한 대로
  **"나중에 변경이 쉬운 구조"** 가 자동 달성됨.
- 향후 Build 0.9+ 에서 **탭 3 방식 (탭 전환 시에만 렌더)** 로 바꿔야 할 경우,
  `if` 분기와 `st.session_state` 로 구현 가능.
- 각 렌더러가 독립적이므로 파일 분리 시 함수만 옮기면 됨.

---

## [Build 0.9] - 2026-04-22

### 🎨 표 컬럼명 개선 + 강수량 표 레이아웃 전환

#### 요청 ④: 지하수위 수위 기준 EL(표고) 명시
- 모든 지하수위 관련 표 헤더에 "EL 실측 (m)" 표기
- 기존 "실측 (m)" → "EL 실측 (m)"
- 기존 "평균 (m)" → "직전 N년 평균 (m)"

#### 요청 ⑤⑥: 표 컬럼명 기간명/평균명으로
- "실측" 열 → 기간 레이블 + 년도 약식 (예: "26년 1월")
- "평균" 열 → "직전 3년 평균" 또는 "직전 5년 평균"
- 전체 수역 요약표의 기간별 소계 헤더도 동일 처리

#### 요청 ⑦: 강수량 표 컬럼명도 기간명/직전 5년 평균으로
- tab1, tab2 AWS 강수량 + 유효강수 표 모두 적용
- "실측" → 기간 약식 레이블 (예: "25년 11월")
- "평균" → "직전 5년 평균"

#### 요청 ⑧: 강수량 비교표 가로세로 전환
- **이전**: 행=기간(M-2/M-1/M), 열=지점 (지점이 가로로 나열, 읽기 불편)
- **이후**: 행=지점, 열=기간(M-2/M-1/M) × [실측|직전5년평균|편차]
- 이점: 지점끼리 비교가 직관적, 기간이 열이라 M-2→M 진행을 좌→우로 읽기 편함

#### Technical
- `_short_label()` 헬퍼 추가: "2026년 1월" → "26년 1월" 변환
- `_render_comparison_table_html()`: 행/열 구조 완전 재설계
- `_render_all_watersheds_html()`: 기간별 컬럼에 기간명 표시

---

## [Build 0.8.2] - 2026-04-22

### 🐛 긴급 패치 2 (Build 0.8.1 버그 수정)

#### 문제 1: `StreamlitDuplicateElementId`
```
There are multiple plotly_chart elements with the same auto-generated ID.
Please pass a unique key argument to the plotly_chart element.
```
- **원인**: `st.tabs()` 는 모든 탭의 내용을 한 번에 렌더링합니다.
  동일한 파라미터로 생성된 차트는 Streamlit이 동일한 ID를 할당하여 충돌.
- **해결**: 모든 `st.plotly_chart()` 호출에 탭+역할+데이터를 조합한 고유 `key=` 추가.
  - `"tab0_ws_diff_bar"`, `"tab1_rain_제주"`, `"tab2_rain_서귀포"` 등
  - 수역/지점에 따라 동적으로 생성되어 수역 전환 시에도 항상 고유

#### 문제 2: HTML 테이블이 소스코드로 노출
```
<td style="padding:5px 8px;...">53.0</td>
```
- **원인**: Streamlit의 마크다운 파서는 **4칸 이상 들여쓰기된 텍스트를 코드 블록으로 처리**합니다.
  `head = """    <table...` 처럼 삼중따옴표 + 들여쓰기 HTML이 그대로 노출.
- **해결**: 모든 HTML 헤더/행을 **들여쓰기 없는 단일 행 문자열 연결** 로 교체.
  `head = ('<table...>' '<thead>...')` 형식

#### Fixed (수정 파일)
- **tab1_watershed.py**: `_render_gw_table_html`, `_render_aws_table_html` 삼중따옴표 → 단일 행
- **tab2_rainfall.py**: `_render_comparison_table_html` 헤더 + 본문 행 단일 행화
- **tab3_gwlevel.py**: `_render_detail_table`, `_render_all_watersheds_html` 단일 행화
- **tab0/1/2/3_*.py**: 모든 `st.plotly_chart()` 에 고유 `key=` 추가 (13개)

#### Verified (검증)
- 13개 plotly_chart key 중복 없음 확인
- 5개 HTML 테이블 생성 함수 들여쓰기 없음 확인
- 모든 파일 문법 검증 통과

#### Technical (교훈)
- Streamlit `st.markdown` 에 HTML 삽입 시 `"""..."""` 삼중따옴표 대신
  `('<tag...>' '<tag...>')` 괄호 안 문자열 연결 사용이 안전
- `st.tabs()` 사용 시 모든 `st.plotly_chart` 에 **탭명+역할** 조합 key 필수

---

## [Build 0.8.1] - 2026-04-22

### 🐛 긴급 패치 (Build 0.8 버그 수정)

#### Problem (문제)
Build 0.8 실행 시 다음 에러로 대시보드 중단:
```
TypeError: unsupported operand type(s) for +: 'int' and 'str'
  File "tab2_rainfall.py", line 180, in _render_station_rainfall_chart
    fig.add_vline(x=m_ym, line_dash="dot", ...)
```

#### 근본 원인 분석
1. **Plotly `add_vline` 타입 에러**
   - `add_vline(x="2026-02")` 문자열 x값을 넘겼을 때,
     Plotly 내부에서 `_mean(X)` 계산 시 `sum(x)` 가 int+str 에러 발생
   - Plotly 버전에 따라 문자열 x축에서 이 함수가 작동하지 않음
2. **카드 HTML 중첩 버그**
   - `<span class="stat-card">` 를 span 안에서 또 감싸 `</div>` 텍스트 노출
3. **Streamlit CSS 변수 미적용**
   - `st.markdown(..., unsafe_allow_html=True)` 로 삽입된 인라인 스타일에서
     `var(--color-bg-info)` 같은 CSS 변수가 루트 컨텍스트를 찾지 못함
   - 결과: 카드 배경색/테두리 색이 깨져서 보임

#### Fixed (수정)
- **tab2_rainfall.py**: `add_vline` 제거 → M 기간 막대를 빨간색으로 강조
- **tab3_gwlevel.py**: `add_vline` 제거 → M 기간 지점에 큰 빨간 마커 + 'M' 텍스트
- **tab0_overview.py, tab1_watershed.py, tab2_rainfall.py, tab3_gwlevel.py**:
  모든 카드의 `class="stat-card"` / CSS 변수 → **인라인 스타일로 완전 교체**
- **theme.py**: `render_stat_card()`, `render_period_badges()`, `render_note_box()`,
  `format_diff_html()` 헬퍼를 모두 인라인 스타일 반환으로 수정
- **app.py**: 헤더의 `var(--color-text-secondary)` 등 → 고정 색상값

#### Technical (교훈)
- Streamlit 의 `unsafe_allow_html=True` 로 삽입되는 HTML 은 독립된 컨텍스트로
  처리될 수 있어, **인라인 스타일이 가장 안전**
- Plotly 의 `add_vline` 은 x값 타입에 따라 버그가 있으므로,
  **데이터의 색상 속성으로 강조**하는 방식이 더 견고

#### Verified (검증)
- 4개 AWS 지점 Plotly 차트 생성 테스트 통과
- 모든 8개 dashboard 모듈 문법 검증 통과
- 실제 사용자 데이터(14,612 ASOS + 1 수역)로 E2E 렌더링 경로 검증

---

## [Build 0.8] - 2026-04-22

### 🎨 탭형 UI 재구성 (기존 HTML 대시보드 스타일 이식)

#### Problem (배경)
Build 0.7.2까지는 모든 섹션이 한 페이지에 세로로 늘어섰습니다.
대시보드가 길어져 PDF 인쇄 시 4페이지가 나왔고, 정보 찾기가 어려웠습니다.

사용자 요청: **기존 HTML 대시보드(jeju_groundwater_dashboard.html v8)를 최대한 반영**.

#### Added (신규 파일)
- **`src/dashboard/theme.py`** : 공통 CSS/테마 (신규)
  - 기존 HTML의 CSS 변수 (색상, 여백, 반경) 이식
  - `.stat-card`, `.panel-box`, `.period-badge`, `.note-box` 스타일
  - Streamlit 탭 커스터마이징 (파란 배경 활성 탭)
  - 인쇄 최적화 CSS (@media print)
  - `apply_theme()`, `render_stat_card()`, `render_period_badges()`,
    `render_note_box()`, `format_diff_html()` 헬퍼

- **`src/dashboard/tabs/` 패키지 (신규)**
  - `tab0_overview.py` : 📋 대시보드 요약
    - 4개 AWS 지점별 M 기간 강수량 카드
    - 수역별 편차 막대 차트 (직전 3년 평균)
    - 분석 메모 자동 생성
  - `tab1_watershed.py` : ① 수역별 현황
    - 14개 수역 버튼 (선택 가능)
    - M-2·M-1·M 요약 카드 (강수량+지하수위 결합)
    - 2열 차트 (인근 AWS 강수량 / 선택 수역 지하수위)
    - 수역 지하수위 현황표 (직전 3년)
    - AWS 강수량+유효강수일수 표 (직전 5년)
  - `tab2_rainfall.py` : ② 강수량 분석
    - 4개 지점 M 기간 요약 카드
    - 지점별 강수량 차트 2×2 그리드 (M 기간 강조선 포함)
    - 강수량 비교표 (실측/평균/편차 색상 강조)
    - 유효강수일수 차트 2×2 + 비교표
  - `tab3_gwlevel.py` : ③ 지하수위 분석
    - 14개 수역 버튼
    - M-2·M-1·M 요약 카드
    - 선택 수역 차트 (60개월, M 기간 강조)
    - 선택 수역 상세 비교표
    - 전체 14개 수역 요약표 (3개 기간 × 3개 값 = 9열)
    - M 기간 편차 막대 차트
  - `tab4_admin.py` : ⚙️ 데이터 관리
    - ASOS 수집 현황 4개 메트릭 카드
    - 지하수위 파이프라인 현황 4개 메트릭 카드
    - [🔄 xls 파싱 + 수역 집계 실행] 버튼
    - 시스템 상태 체크리스트 (2열)
    - 🧾 분석 리포트 생성 (Build 0.7.2 기능 유지)

#### Changed (수정)
- **`src/dashboard/app.py`** : 전면 재작성
  - 기존 세로 나열 → 4개 탭 구조 (st.tabs)
  - 사이드바에 기준일 선택 + 데이터 요약 카드
  - @st.cache_data 로 CSV 로드 성능 최적화
  - 탭 5개로 확장: 요약 + 수역별 + 강수량 + 지하수위 + 데이터 관리

#### Technical (설계 결정)
- **탭별 파일 분리** : 유지보수성 확보 (탭 하나 수정 시 다른 탭 영향 없음)
- **HTML 테이블 직접 렌더링** : 편차 색상 강조를 위해 st.dataframe 대신 HTML 사용
- **session_state** : 수역 선택·리포트 요청 상태를 탭 간 공유 없이 탭별로 관리
- **나중의 페이지 분리 대비** : 각 탭의 render() 함수는 독립적이라 추후 별도 페이지 전환 쉬움

#### Verified (검증)
- 모든 9개 모듈 문법 검증 통과
- E2E 테스트: ASOS 14,612개 + 수역 집계 + M-2/M-1/M 계산 + 비교표 생성 모두 정상

---

## [Build 0.7.2] - 2026-04-22

### 🧾 PDF 출력 기능

#### Problem (요구사항)
"대시보드 내용을 PDF로 저장할 수 있으면 좋겠다" — 사용자 요청.

#### Added (추가)
- **`src/dashboard/report_generator.py`** : HTML 리포트 생성 모듈
  - `build_report_html()` : 전체 리포트 HTML 생성
  - `save_report_to_file()` : data/reports/ 에 자동 저장
  - A4 인쇄 최적화 CSS (@page 규칙, 페이지 넘김 방지)
  - 편차 자동 색상 처리 (양수=초록, 음수=빨강)
  - 수역 14개를 7개×2 그룹으로 분할하여 가독성 확보

- **app.py 업데이트**
  - 전역 인쇄 최적화 CSS 주입 (@media print로 사이드바/버튼 숨김)
  - 사이드바에 "📄 리포트 · PDF" 섹션 추가
    - 방식 A (빠른 인쇄): 안내
    - 방식 B (정리된 리포트): 안내
  - 본문 하단에 "🧾 분석 리포트 생성" 섹션
  - [🧾 리포트 생성] 파란색 버튼
  - [⬇️ HTML 리포트 다운로드] 버튼
  - 리포트 미리보기 (접을 수 있는 expander)

#### Technical (설계)
- **두 가지 방식 제공**
  - 방식 A (Ctrl+P): 대시보드 그대로 인쇄, 추가 라이브러리 불필요
  - 방식 B (HTML 다운로드): 정리된 리포트, 브라우저에서 Ctrl+P → PDF

- **외부 라이브러리 불필요**: reportlab/weasyprint 안 씀 → 설치 단순
- **한글 폰트**: Malgun Gothic + Apple SD Gothic Neo fallback
- 리포트는 `data/reports/report_{base_date}_{timestamp}.html` 로 자동 저장 (이력 관리)

#### Verified (검증)
- 실제 사용자 데이터로 E2E 생성 성공
- LibreOffice로 PDF 변환 시 한글/표/색상 모두 정상
- 2페이지 구성: 1페이지=헤더/기간, 2페이지부터=비교표

---

## [Build 0.7.1] - 2026-04-22

### 🐛 버그 수정 + 기준일 선택 기능

#### Fixed (수정)
- **KeyError 'baseline_date' 버그 수정**
  - `period_calculator.compute_periods()` 의 실제 키는 `base_date`인데,
    `app.py`에서 `baseline_date`로 잘못 조회하여 KeyError 발생.
  - 모든 참조를 `base_date`로 통일.

#### Added (추가)
- **사이드바에 분석 기준일 선택기 추가**
  - 날짜 피커 위젯으로 임의의 날짜 선택 가능
  - 빠른 선택 버튼 3개:
    - `[오늘]` : 오늘 날짜 (기본)
    - `[26-02-01]` : 2026-02-01 (지하수위 데이터가 2026-01까지 있을 때 최적)
    - `[어제]` : 어제 날짜
  - 사이드바에 현재 기준일의 M-2/M-1/M 미리보기 표시
  - Streamlit session_state로 상태 유지 (페이지 새로고침에도 보존)

- **수역별 지하수위 M-2·M-1·M 비교 패널 추가**
  - 14개 수역별 실측 vs 직전 3년 평균 비교표
  - M 기간의 편차(실측-평균) 수역별 막대 차트
  - 0 기준선(평균선) 표시로 초과/부족 한눈에 파악

#### Why (왜 이 기능이 필요했나)
지하수위 데이터는 **월 단위**라 현재 시점(4월 22일)에 M=4월(1~15)로 설정되면
지하수위 M 기간은 빈 값(월이 아직 안 끝남). 사용자가 기준일을
**2026-02-01**로 설정하면 M=2026년 1월이 되어 **최신 지하수위 데이터(26년 1월)로
실측값과 직전 3년 평균을 비교** 가능해짐.

#### Verified (검증)
- 실제 사용자 ASOS 데이터(14,612개)로 E2E 검증
- 기준일 2026-02-01 → M=2026년 1월, M-1=2025년 12월, M-2=2025년 11월 정상
- 강수량 비교표 실측값 정상 조회 (예: 2025년 12월 제주 16.0mm vs 직전 5년 평균 35.2mm)

---

## [Build 0.7] - 2026-04-22

### 📅 M-2·M-1·M 기간 분석 + 파일 정리

#### Added (추가)
- **`src/analysis/effective_rainfall.py`** : 강수량/유효강수 분석 모듈
  - `aggregate_monthly()` : 일 → 월 집계 (강수합, 유효강수일수, 기온 통계)
  - `aggregate_half_monthly()` : 반월(1~15일) 집계
  - `get_period_value()` : 특정 기간·지점의 실측값 조회
  - `get_baseline_average()` : 직전 N년 동월 평균
  - `build_comparison_table()` : M-2·M-1·M 비교표 전체 생성
  - `summary_for_station()` : 지점별 카드형 요약

- **`cleanup_files.py`** (루트) : JD관측망 파일 위치 정리 스크립트
  - 루트/Row_Data/data 에 흩어진 중복 파일 검색
  - 가장 최신 파일을 `data/0_JD관측망_정보.xlsx` 로 이동
  - 나머지 중복 자동 삭제 (확인 프롬프트 포함)

- **대시보드 (app.py) 업데이트**
  - Build 0.7 기간 분석 패널 추가:
    - 기준일 / M-2 / M-1 / M 정보 카드 (반월 표시 포함)
    - 강수량 비교표 (실측 vs 직전 5년 평균)
    - 유효강수일수 비교표 (5mm 기준)
    - 지점별 M-2·M-1·M 막대 차트 (실측 vs 평균)

#### Changed (변경)
- **config.py**
  - `JD_NETWORK_FILE_CANDIDATES` 탐색 우선순위를 `data/` 폴더로 변경
  - 오타 파일명(`0JD관측망_정보.xlsx`, 공백 버전 등)도 호환 지원
- **.gitignore**
  - `data/*.xlsx` 및 `*.xlsx` 추가 (개인 데이터 Git 업로드 방지)

#### Technical (설계 결정)
- 반월 집계는 별도 DataFrame으로 분리 관리 (월 집계와 명확히 구분)
- `pd.isna()` 체크로 결측 안전 처리
- 기간 라벨은 period_calculator 모듈에서 일관되게 생성

#### Verified (검증)
- 실제 사용자 ASOS 데이터(14,612개, 2016-2025) 로드 테스트 성공
- 월별 집계 480개 레코드 생성 확인
- 직전 5년 평균 계산 정상 (예: 2026-02 → 2021~2025)

---

## [Build 0.6] - 2026-04-22

### 💧 지하수위 xls 파서 + 수역 매핑

#### Added (추가)
- **`src/collectors/gwlevel_parser.py`** : 지하수위 xls 파서
  - `parse_single_xls()` : 단일 xls 파일에서 지정 센서 시트 추출
  - `parse_all_row_data()` : Row_Data 폴더 전체 일괄 파싱
  - `save_by_station()` : 관측소별 CSV 저장
  - `load_all_station_data()` : 대시보드용 통합 로더
  - 기본 센서: S11 (config에서 변경 가능)
  - 원본 xls 파일은 수정하지 않고 그대로 보존
  - `-` 결측치 토큰을 NaN으로 자동 변환

- **`src/analysis/watershed_mapper.py`** : 관측소 → 수역 매핑
  - `load_station_to_watershed_map()` : xlsx의 유역명으로 매핑 (65개소)
  - `get_watershed_to_stations_map()` : 역매핑 (수역별 관측소 목록)
  - `aggregate_by_watershed()` : 수역별 월별 EL 평균 계산
  - `save_watershed_csvs()` : 수역별 CSV 저장
  - `load_watershed_data()` : 대시보드용 로더
  - 14개 수역 모두 xlsx와 config.py에서 정확히 매칭 확인

- **`process_gwlevel.py`** (루트) : 원클릭 파이프라인 실행 스크립트
  - 사용자 편의를 위한 진입점
  - `python process_gwlevel.py` 한 줄로 전체 처리

- **대시보드 (app.py) 업데이트**
  - 지하수위 수집 상태 요약 카드 (xls 수, 파싱된 관측소, 집계된 수역)
  - "xls 파싱 + 수역 집계 실행" 파란색 버튼
  - 14개 수역 지하수위 추이 라인 차트 (Plotly)
  - 수역 선택 시 해당 수역의 관측소 목록 표시
  - 수역별 월별 데이터 표 (접을 수 있는 expander)

#### Technical (기술적 결정)
- 시트별 스캔이 아닌 **파일별 스캔**으로 효율성 확보
  (S11 한 시트만 읽음, 다른 센서 시트는 건너뜀)
- 날짜 "YYYY-MM" 문자열 → Period → CSV "연월" 컬럼으로 저장
- 관측소명은 파일 내 데이터 우선, 없으면 파일명(stem) 사용
- `encoding="utf-8-sig"` 로 Excel에서도 한글 깨짐 없이 열림

#### Verified (검증 완료)
- 실제 JD하모2.xls 파싱 → S11 61개월치 (2021-01~2026-01) 추출 성공
- 14개 수역 매핑 완전 일치 (xlsx ↔ config.py)
- 수역별 CSV 생성 (예: 대정.csv에 16개 관측소 평균)

---

## [Build 0.5] - 2026-04-22

### 🗓️ Smart 수집 모드 + 최신 데이터 수집 지원

#### Problem (문제)
Build 0.4 수집 결과 2025-12-31까지만 저장되었음.
- 원인: 현재 연도(2026) 요청 시 endDt=`20261231`이 미래 날짜여서
         기상청 API가 요청 전체를 거부 (code 99).
- 에러: `전날 자료까지 제공됩니다. 날짜 범위를 확인해주세요.`

#### Added (추가)
- **Smart 모드** (기본): M-2·M-1·M 분석에 필요한 데이터만 수집
  - 오늘 1~15일 → 전월 말일까지
  - 오늘 16~말일 → 당월 15일까지
  - (기존 HTML 대시보드 v8의 기간 로직과 일치)
- **Latest 모드**: 어제까지 모든 데이터 수집
- **CLI 옵션**
  - `--mode {smart,latest,y2025}` 수집 종료일 모드 선택
  - `--through YYYY` 특정 연도까지만 수집
- **대시보드 UI**
  - Smart 모드 기준일 안내 (예: "오늘 22일 → 당월 15일까지 수집됨")
  - 수집 버튼 3개로 분리: Smart / Latest / 전체 재수집

#### Changed (변경)
- `fetch_daily_weather_for_year()` 에 `end_dt_override` 파라미터 추가
- 연도별 endDt를 동적으로 결정 (과거 연도=12-31, 현재 연도=계산값)

#### Fixed (버그 수정)
- **일강수량 NaN → 0.0 자동 보정**
  - 기상청 API는 비 안 온 날 `sumRn`을 빈 문자열로 반환 → pd.to_numeric 후 NaN
  - 이전엔 NaN으로 저장되어 차트/집계에서 오류
  - Build 0.5부터: 신규 수집 + 기존 CSV 로드 시 모두 자동 보정
  - ※ 기온 계열은 NaN 유지 (0°C와 '측정 불가' 구분)

---

## [Build 0.4] - 2026-04-21

### 🛡️ User-Agent 헤더 추가 (403 Forbidden 해결)

#### Problem (문제)
공공데이터포털이 봇 방지를 위해 User-Agent 헤더가 없거나 `python-requests/*` 같은
기본 User-Agent를 가진 요청을 차단하기 시작함.

증상:
- HTTP 상태 코드: `403 Forbidden`
- 응답 본문: `Forbidden` (plain text, API 에러 XML 아님)
- Content-Type: `text/plain`
- API 서비스에 도달하기 전 방화벽(WAF) 레벨에서 차단

#### Changed (변경)
- **config.py**
  - `HTTP_HEADERS` 상수 추가 (User-Agent, Accept, Accept-Language)
  - 브라우저 User-Agent (Chrome 120) 로 위장
- **asos_collector.py**
  - `requests.get()` 호출 시 `headers=config.HTTP_HEADERS` 추가
- **diagnose_api.py**
  - User-Agent 유무 비교 테스트 추가
  - 403 Forbidden (plain text) 패턴 자동 감지 및 안내
  - WAF 차단 vs 네트워크 차단 구분

#### Result (결과)
정상적인 브라우저 요청처럼 인식되어 API 응답이 정상 반환됨.

---

## [Build 0.3] - 2026-04-21

### 🩺 ASOS 수집 안정화 + 진단 도구

#### Added (추가)
- `src/collectors/diagnose_api.py` : API 진단 전용 독립 스크립트
  - `.env` 파일 및 API 키 검증
  - HTTPS / HTTP 엔드포인트 개별 테스트
  - 응답 형식 분석 (JSON / XML / HTML / 텍스트)
  - 공공데이터포털 에러 코드 해석 테이블 (00~99)
  - 에러 유형별 구체적인 조치 방법 안내

#### Changed (변경)
- **config.py**
  - `KMA_API_URL` : `http://` → **`https://`** 전환 (2024년 이후 HTTPS 강제)
  - `KMA_API_URL_FALLBACK` : HTTP 폴백 URL 추가 (진단용)
  - `KMA_API_TIMEOUT` : 60초 → 30초 (빠른 실패)
  - `KMA_API_MAX_RETRIES` : 5회 → 3회 (무의미한 재시도 감소)
  - `KMA_API_RETRY_DELAY` : 10초 → 5초
- **asos_collector.py**
  - 에러 상세화: `RETRY` → `RETRY_TIMEOUT` / `RETRY_CONN` / `API_KEY_ERROR[XX]` / `HTTP_403` 등
  - XML 에러 응답에서 `returnReasonCode` 자동 추출
  - 키 문제(코드 20/30/31)는 재시도 없이 **즉시 전체 중단**
  - `fetch_with_retry()` 반환값에 `fatal_error` 플래그 추가
- **app.py**
  - 상단 안내에 진단 도구 실행법 추가

#### Fixed (버그 수정)
- 타임아웃·XML 에러를 구분 없이 `RETRY`로 처리하던 문제
  → 실제 에러 원인이 로그에 보이지 않아 사용자가 디버깅 불가능했음
- 키 문제로 인한 무한 재시도 → 5회 × 10초 × 44건 = 40분 낭비

---

## [Build 0.2] - 2026-04-21

### ✨ ASOS 기상 데이터 수집 모듈

#### Added (추가)
- `src/collectors/asos_collector.py` : 기상청 ASOS API 수집기
  - 기존 `Aws_day.py` (v3.0) 를 모듈화하여 이식
  - `fetch_daily_weather_for_year()` : 1년치 API 호출
  - `fetch_with_retry()` : 자동 재시도 로직 (최대 5회)
  - `collect_asos_data()` : 전체 수집 메인 함수
  - `load_asos_data()` : 대시보드에서 CSV 읽기용
- **증분 수집 기능**
  - 이미 저장된 연도(360일 이상)는 자동 건너뜀
  - 현재 연도는 항상 재수집 (최신 데이터 반영)
  - `--force` 옵션으로 전체 재수집 가능
- **대시보드 업데이트** (`src/dashboard/app.py`)
  - ASOS 수집 상태 요약 카드
  - 지점별·연도별 수집 현황 표
  - 월별 강수량 미리보기 차트 (Plotly)
  - 수집 버튼 (증분 / 전체 재수집)

#### Changed (변경)
- API 키를 하드코딩 대신 `.env` 파일에서 로드
- 수집 시작일을 2014년 → **2016-01-01** 로 변경
- 저장 파일명: `jeju_daily_weather_data_YYYY-YYYY.csv` → `jeju_asos_daily.csv` (고정)

#### Technical (기술적 결정)
- 중복 제거: `지점명 + 일시` 기준 (keep="last")
- 수치형 변환: `pd.to_numeric(errors="coerce")` 로 NaN 유지
- API 호출 간격: 1초 (서버 부하 방지)

---

## [Build 0.1] - 2026-04-21

### 🎉 최초 생성

#### Added (추가)
- 프로젝트 기초 디렉토리 구조 생성
  - `data/` : ASOS, GWlevel(by_station, by_watershed), Row_Data
  - `src/` : collectors, analysis, dashboard
  - `docs/`, `tests/`
- `README.md` : 프로젝트 개요·설치·실행 가이드
- `requirements.txt` : 필요 Python 패키지 목록
- `config.py` : 전역 설정 파일
  - 4개 ASOS 지점 정보 (제주·서귀포·성산·고산)
  - 14개 수역 정보 (색상 포함, 기존 HTML 대시보드 v8에서 계승)
  - 경로·API·기준값 설정
- `.env` / `.env.example` : API 키 분리 관리
- `.gitignore` : Git 추적 제외 설정

#### 기술적 결정
- **프레임워크**: Streamlit 선정 (초보자 친화적, 빠른 개발)
- **차트 라이브러리**: Plotly (Chart.js 대체, 인터랙티브)
- **API 키 관리**: .env 파일로 분리
- **수집 기간**: 2016-01-01부터 누적

---

## [Roadmap] 향후 계획

### Build 0.2 (예정)
- [ ] `src/collectors/asos_collector.py` : 기상청 API 수집 모듈
- [ ] `src/collectors/__init__.py`
- [ ] 수집 결과 CSV 누적 저장 로직
- [ ] 증분 수집 (이미 있는 날짜는 건너뛰기)

### Build 0.3 (예정)
- [ ] `src/collectors/gwlevel_parser.py` : xls → S11 추출 모듈
- [ ] `src/analysis/watershed_mapper.py` : 관측소→수역 매핑
- [ ] 65개 JD 관측소 일괄 파싱

### Build 0.4 (예정)
- [ ] `src/analysis/period_calculator.py` : M-2·M-1·M 계산
- [ ] `src/analysis/effective_rainfall.py` : 유효강수일수 계산

### Build 0.5 (예정)
- [ ] `src/dashboard/theme.py` : 색상·스타일
- [ ] `src/dashboard/app.py` : Streamlit 메인 앱 + 탭 스위칭

### Build 0.6 ~ 0.8 (예정)
- [ ] 탭 ① 수역별 현황
- [ ] 탭 ② 강수량 분석
- [ ] 탭 ③ 지하수위 분석

### Build 0.9 (예정)
- [ ] 전체 통합 테스트
- [ ] 문서 최종 정리
- [ ] `run_dashboard.bat` 바로가기 스크립트

### Build 1.0 (목표)
- [ ] 정식 릴리스
- [ ] 실제 데이터로 완전 동작 확인

### Build 1.x 이후 (확장)
- [ ] 제주도 지하수정보관리시스템 자동 스크래핑
- [ ] 농업용 가뭄 분석 (SPI, 증발산 등)
- [ ] PDF/엑셀 리포트 자동 생성
