# data_ag_well_Clean — 제주 농업용 공공관정 통합 DB (정리본)

> **이 폴더가 최종 사용용 깨끗한 버전**입니다. 작업 중 임시 파일·중간 분석·검증 보고서는 모두 제외하고 **실제 분석에 사용할 데이터와 핵심 문서만** 포함되어 있습니다.

작성일: 2026-05-05  
버전: v3.0 (최종 마무리)

---

## 폴더 구성

```
data_ag_well_Clean/
├── master.csv / master.xlsx              ← 마스터 (902공)
│
├── master_yearly/                         ← 연도별 시점 메타정보 (9개년)
│   ├── master_2017.csv ~ master_2025.csv  (9개)
│   └── master_2017.xlsx ~ master_2025.xlsx (9개)
│
├── usage/                                 ← 월별 사용량 (9개년)
│   ├── usage_montly_2017.csv ~ 2025.csv   (9개)
│   ├── usage_montly_2017.xlsx ~ 2025.xlsx (9개)
│   ├── _제주시_보정이력.csv               (참고: 65건)
│   └── _제주시_분기측정값_최종보정.json   (참고: 분기 측정값)
│
├── water_quality/                         ← 수질 데이터
│   ├── water_quality_semiannual.csv/xlsx  (5항목, 21,222행)
│   └── water_quality_agricultural.csv/xlsx (15항목, 1,554행)
│
├── _data_lineage.json                     ← 출처 메타 (시트별 컬럼 매핑)
├── _history.csv                           ← 모든 변경 이력 (130+ 건)
└── _README.md                             ← 본 파일
```

---

## 데이터 사용 가이드

### 1. master.csv (관정 마스터, 902공)
모든 관정의 메타정보. 분석 시 \"이 관정이 어디 있는지, 시설은 어떤지\"를 알기 위해 참조.

**주요 컬럼:**
- `permit_no` — 허가번호 (PK, 예: Y199510077)
- `well_id` — 관정명 (예: F-088, 89동광1)
- `well_si` / `well_eup` / `well_ri` / `well_bunji` — 관정 위치
- `tank_si`/`tank_eup`/`tank_ri`/`tank_bunji` — 배수지 위치
- `coord_x` / `coord_y` — TM 좌표 (EPSG:5186)
- `install_date` — 시설년도, `elevation_m` — 표고
- `drill_depth_m` — 굴착심도, `casing_diameter_mm` — 케이싱구경
- `capacity_m3d` — 양수능력 (㎥/일)
- `permit_m3m` — 취수허가량 (㎥/월)
- `natural_water_level_m` / `stable_water_level_m` — 자연/안정수위
- `voltage_v` / `motor_hp` — 전압 / 모터마력
- `active` — 활성 여부 (true/false)
- `superseded_by` — 폐기·갱신된 경우 새 permit_no
- `authority` — 관리주체 (서귀포시 / 제주시) ← v3.0 신규

### 2. master_yearly/ (연도별 마스터, 9개년)
**그 해 시점의** 시설·허가량 정보. 매년 변경된 값이 있으므로 시계열 분석에 필수.

각 파일 = master.csv와 같은 컬럼 + 그 해 측정값.

### 3. usage/ (월별 사용량)

#### usage_montly_YYYY.csv (9개년, 총 약 7,000행)

**컬럼:** `permit_no, well_id, year, Jan~Dec, capacity_m3d, permit_m3m, remark, source`

**서귀포 (429공)** — 원본 직접 측정값 (변경 없음)  
**제주시 (472공)** — 분기→월 변환 (베이지안 가중치 적용)

**xlsx 색상:**
- 🟦 연파랑 = 서귀포 (변경 없음)
- 🟨 연노랑 = 제주시 일반 (분기→월 변환)
- 🟧 진주황 = 제주시 자동 보정 (옵션A)
- 🟨 노랑 = Flagging (수동 검토 권장)
- 🟢 연두 = 사용자 수동 보정
- ⚪ 회색 = 무효 처리 (F-586 9분기)

#### _제주시_보정이력.csv (65건)
적용된 모든 보정의 상세 이력 (관정·연도·분기·원본값·보정값·방법).

#### _제주시_분기측정값_최종보정.json
제주시 분기 측정값 (보정 적용 후). 분기→월 재계산이 필요할 때 활용.

### 4. water_quality/ (수질 데이터)

#### water_quality_semiannual.csv (21,222행)
**5항목 반기별** (2014~2025): NH4, NO3, pH, Cl, EC

**컬럼:** `permit_no, well_id, year, half, sampling_date, ammonia_n, nitrate_n, pH, chloride, EC, remark, source`

#### water_quality_agricultural.csv (1,554행)
**15항목 정밀 검사** (2018~2025): pH, Cl, NO3, Cd, As, CN, Hg, 다이아지논, 파라티온, Phenol, Pb, Cr, TCE, PCE, TCA_111, 판정, 초과항목

### 5. _data_lineage.json
각 csv가 어느 원본 시트의 어느 컬럼에서 추출됐는지 추적.

### 6. _history.csv (130+ 건)
모든 변경 이력 (timestamp, file, action, before, after, reason).

---

## 핵심 통계

| 항목 | 값 |
|---|---|
| 총 관정 | **902공** (서귀포 429 / 제주시 473) |
| 연도 범위 | 2014~2025 (수질) / 2017~2025 (사용량) |
| 월별 사용량 행 | 약 7,000 (8년 × 평균 873공) |
| 수질 데이터 (5항목) | 21,222행 |
| 수질 데이터 (15항목) | 1,554행 |
| 보정 적용 (제주시) | 56건 (자동 44 + 사용자 12) |
| 무효 처리 | 9분기 (F-586) |
| 검증 결과 | 서귀포 100% 무결성, 제주시 5/5 정책 PASS |

---

## 시정 권한 (서귀포 vs 제주시)

| 시 | 사용량 데이터 | 처리 방식 |
|---|---|---|
| **서귀포 (429공)** | 원본 직접 측정 | **변경 없음** — 100% 무결성 유지 |
| **제주시 (472공)** | 분기 측정값 | 분기→월 변환 + 보정 |

`master.csv`의 `authority` 컬럼으로 관리주체 구분 가능. 향후 \"농어촌공사\", \"제주도\" 추가 가능.

---

## 새 데이터 추가 시 (예: 2026년)

1. `_data_lineage.json` 참조하여 시트 구조 확인
2. (`_skill_groundwater_db_integration/` 폴더 별도 위치에 SKILL.md + 스크립트 보관)
3. 처리 후 `_history.csv`에 변경 이력 추가
4. 백업 폴더 만들고 진행

---

## 폴더 외부 참고 자료 (별도 보관)

이 폴더 외에 같은 부모 디렉토리(jeju_groundwater_dashboard/)에:
- `_skill_groundwater_db_integration/` — SKILL.md v2.1 + 재사용 스크립트 + 체크리스트

이는 데이터가 아니라 \"향후 작업 도구\"이므로 별도 위치에 둠.
