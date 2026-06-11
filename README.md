# 🌊 제주도 지하수위·강수량 분석 대시보드

> **Build 0.1** · 최종 수정일: 2026-04-21  
> 제주도 JD 관측망 65개소의 지하수위와 4개 ASOS 기상관측소의 강수량을 연계 분석하는 Streamlit 기반 대시보드입니다.

---

## 📌 프로젝트 개요

이 프로젝트는 다음 3가지를 목표로 합니다:

1. **기상청 ASOS 일자료** 자동 수집·누적 저장 (2016년 1월 1일부터)
2. **제주도 JD 지하수위 관측망** 월별 데이터(S11 센서) 정리·누적 저장
3. **M-2 / M-1 / M 기간 비교 대시보드** — 직전 5년(강수량) / 직전 3년(지하수위) 평균과 비교

기존 HTML 대시보드(`jeju_groundwater_dashboard.html v8`)의 구성과 분석 로직을 계승하여 Python으로 이식하였으며, 향후 농업용 가뭄 분석까지 확장 가능한 구조로 설계되었습니다.

---

## 📁 디렉토리 구조

```
jeju_groundwater_dashboard/
│
├── README.md                    이 파일
├── requirements.txt             필요한 Python 패키지 목록
├── config.py                    전역 설정 (관측소·수역·색상·경로)
├── .env.example                 API 키 예시 (실제 키는 .env 에 입력)
├── .env                         실제 API 키 (Git 업로드 제외)
├── .gitignore                   Git 추적 제외 파일 목록
│
├── data/                        모든 데이터 저장소
│   ├── ASOS/                    기상청 강수량 CSV 누적 파일
│   ├── GWlevel/                 지하수위 가공 데이터
│   │   ├── by_station/          관측소별 S11 센서 CSV
│   │   └── by_watershed/        14개 수역별 월별 집계 CSV
│   └── Row_Data/                사용자가 xls 원본을 넣는 곳
│
├── src/                         Python 소스 코드
│   ├── collectors/              데이터 수집 모듈
│   │   ├── asos_collector.py    ASOS API 강수량 수집기
│   │   └── gwlevel_parser.py    xls → S11 추출기
│   ├── analysis/                분석 로직
│   │   ├── period_calculator.py M-2·M-1·M 기간 계산
│   │   ├── effective_rainfall.py 농업유효강수일수 (일 5mm 이상)
│   │   └── watershed_mapper.py  관측소 → 14개 수역 매핑
│   └── dashboard/               Streamlit 대시보드
│       ├── app.py               ⭐ 메인 실행 파일
│       ├── tab02_watershed.py    탭① 수역별 현황
│       ├── tab03_rainfall.py     탭② 강수량 분석
│       ├── tab04_gwlevel.py      탭③ 지하수위 분석
│       └── theme.py             색상·스타일 설정
│
├── docs/                        문서
│   └── CHANGELOG.md             버전별 변경이력
│
└── tests/                       테스트 코드 (선택)
```

---

## 🚀 설치 및 실행 방법 (초보자 가이드)

### 1️⃣ 사전 준비

- **Python 3.10 이상** 설치 ([python.org](https://www.python.org/downloads/))
  - 설치 시 **"Add Python to PATH" 반드시 체크**
- **VS Code** 설치 및 Python 확장 설치
- **공공데이터포털 API 키** 발급 ([data.go.kr](https://www.data.go.kr))
  - `기상청_지상(종관, ASOS) 일자료 조회서비스` 검색 후 활용신청

### 2️⃣ 프로젝트 설치

VS Code에서 이 폴더를 열고 터미널(`Ctrl+\``)에서:

```bash
# (1) Python 패키지 설치 (처음 한 번만)
pip install -r requirements.txt

# (2) API 키 설정
# .env.example 파일을 복사해서 .env로 이름을 바꾸고,
# 그 안에 발급받은 API 키를 입력하세요.
```

### 3️⃣ 데이터 준비

**① 기상(ASOS) 데이터 수집 (최초 1회 또는 주기적)**
```bash
python src/collectors/asos_collector.py
```
→ `data/ASOS/` 폴더에 CSV 누적 저장됩니다. (약 3~5분)

**② 지하수위 xls 파일 투입**
- 제주도 지하수정보관리시스템(water.jeju.go.kr)에서 다운로드한
  `JD간드락.xls`, `JD고산1.xls` 등의 파일을 **`data/Row_Data/` 폴더에 넣으세요**
- 대시보드가 자동으로 파싱하여 S11 센서 데이터만 추출합니다.

### 4️⃣ 대시보드 실행

```bash
streamlit run src/dashboard/app.py
```

→ 자동으로 브라우저가 열리며 대시보드가 표시됩니다 (`http://localhost:8501`)  
→ 종료: 터미널에서 `Ctrl + C`

---

## 📊 대시보드 구성

### 탭 ① 수역별 현황
수역 선택 → 강수량 차트 + 지하수위 차트 + 지하수위 현황표(직전 3년 기준) + 인근 AWS 강수량·유효강수일수표(직전 5년 기준)

### 탭 ② 강수량 분석
4개 AWS 지점(제주·서귀포·성산·고산) 차트 및 비교표  
- 강수량 (mm)
- 농업유효강수일수 (일) — 일강수량 5mm 이상 일수

### 탭 ③ 지하수위 분석
14개 수역 버튼 → 선택 수역 차트 + 상세 비교표 + 전체 수역 요약표 (직전 3년 기준)

---

## 🕒 M-2 / M-1 / M 기간 로직

| 기준일 | M-2 | M-1 | M |
|---|---|---|---|
| 매월 **1~15일** | 3개월 전 | 2개월 전(전월) | 전월 |
| 매월 **16일 이상** | 전전월 | 전월 | 당월 1~15일 |

※ 16일 이후 기준일의 M 기간은 '당월 1~15일'이며, 직전 평균에 **×0.5 계수**를 적용합니다.

---

## 📝 버전 히스토리

자세한 내용은 [docs/CHANGELOG.md](docs/CHANGELOG.md) 참조.

- **Build 0.1** (2026-04-21): 프로젝트 초기 구조, 기본 설정 파일

---

## ❓ 문제 해결

| 증상 | 해결 방법 |
|---|---|
| `ModuleNotFoundError` | `pip install -r requirements.txt` 재실행 |
| API 키 오류 | `.env` 파일의 `KMA_API_KEY` 확인 |
| xls 파일 못 읽음 | `pip install xlrd openpyxl` 확인 |
| 대시보드 안 열림 | `http://localhost:8501` 수동 입력 |

---

## 🤝 기여 / 문의

이 프로젝트는 Claude(Anthropic)와 협업하여 개발되었습니다.  
코드 수정·기능 추가는 Claude Code를 통해 진행하는 것을 권장합니다.
