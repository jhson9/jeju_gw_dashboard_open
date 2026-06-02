# 제주 지하수·농업 대시보드 — 데이터 관리 작업지침서 (V3.0)

**최종 갱신**: 2026-05-25
**대상**: `C:\python\jeju_groundwater_dashboard`(운영) · `C:\COWORK_SPACE\jeju_groundwater_dashboard`(작업)
**핵심 원칙**: 원자료(00_source)는 보존만, 코드는 정제 결과(01~05)만 소비. 경로는 `config.py`가 신규우선+폴백으로 관리.

---

## 1. 폴더 구조 (V3.0)

```
data/
├── 00_source/        ★ 원자료 보관소 (사람이 인터넷에서 받아 연도별로 저장)
│   ├── stat/             통계연보·주요행정통계·농업용수종합계획 등 (농업통계 원천)
│   ├── rain_gwlevel/     기상(ASOS)·지하수위 원천
│   ├── well/             관정 master·시추이력 원천
│   ├── usage_quality/    이용량·수질 원천
│   ├── drone/            드론 촬영 원천(원본 보관용)
│   └── map/              GIS 경계 원천(shp 등)
├── 00_map/           GIS 경계(읍면동·리·유역 geojson/shp) — 코드가 직접 사용
├── 01_rain_gwlevel/  ASOS + GWlevel(by_station…) + Row_Data(원본 xls)
├── 02_well/          관정 master·master_yearly + well_card + drilling_log
├── 03_usage_quality/ usage(이용량) + water_quality(수질)
├── 04_drone/         드론 정사·DSM·3D Tiles (registry.json)
└── 05_ag_stat/       농업통계 정제 CSV 7종 + _meta.json (tab41~45)
```

`00_source`(원자료)와 `01~05`(정제·운영 자료)를 분리한 이유: 매년 원자료만 교체하고 빌드/갱신하면 되므로, 몇 년 뒤에도 "무엇이 원천이고 어떻게 만들어졌는지"가 명확합니다.

---

## 2. 도메인별 데이터 출처·갱신 (연 1회 기준)

### 00_map (GIS 경계) — 갱신 거의 없음
- 내용: `읍면동경계.geojson`(12), `리경계.geojson`(177), `유역경계`, `제주도전체`.
- 출처: 제주도 행정경계 shp → WGS84 GeoJSON 사전 변환.
- 갱신: 행정구역 개편 시에만. 원본 shp는 `00_source/map/`에 보관.

### 01_rain_gwlevel (기상·지하수위)
- ASOS(강수): 기상청 ASOS 일자료 → `01_rain_gwlevel/ASOS/jeju_asos_daily.csv`.
- 지하수위: 원본 xls를 `01_rain_gwlevel/Row_Data/Month|Day/`에 두고 파서 실행 → `GWlevel/by_station*`.
- 원천 보관: `00_source/rain_gwlevel/<연도>/`.

### 02_well (관정 시설)
- master.csv / master_yearly: 농업용 공공관정 마스터(외부 ETL CSV).
- well_card / drilling_log: 관정카드·시추주상도 PDF.
- 원천 보관: `00_source/well/<연도>/`.

### 03_usage_quality (이용량·수질)
- usage: 이용량 월자료 CSV. water_quality: 반기 수질 CSV.
- 원천 보관: `00_source/usage_quality/<연도>/`.

### 04_drone (드론)
- 미션별 폴더 + `registry.json` + `master_drone.csv`. 신규 미션은 registry에 1건 추가.
- 원천(원본 tif 등) 보관: `00_source/drone/<미션ID>/`.

### 05_ag_stat (농업통계 — tab41~45)  ★ 매년 갱신 핵심
- 정제 CSV 7종: population_by_eupmyeon / population_yearly_total / farm_household_yearly /
  farmland_area_yearly / farm_size_distribution / crop_cultivation_area / data_dictionary (+ _meta.json).
- 1차 출처: **제주통계연보(3.인구, 6.농림수산업) + 주요행정통계 + 농업용수 종합계획 보고서**.
- 갱신 절차는 §4 참조.

---

## 3. 데이터가 어떻게 만들어졌나 (농업통계 05_ag_stat)

1. 통계연보 `3.인구.xlsx`(읍면동별 세대·인구), `6.농림수산업.xlsx`(농가·경지·작물·경지규모) 에서 표 추출.
2. 주요행정통계 p.23(연도별 인구·세대) 병합.
3. 읍면동 인구를 12개 읍면동경계 NAME으로 집계(동→'시 동지역', 추자·우도는 지도 제외).
4. 출처는 `data_dictionary.csv`의 `출처`·`출처_페이지` 컬럼에 셀 단위로 기록 → 모든 수치 역추적 가능.
5. 보고서 본문 PDF(약 660MB)는 OCR 글리프 손상으로 직접 추출 제외(동일 원자료가 통계연보에 정제됨). PDF는 §5 색인으로만 관리.

---

## 4. 연 1회 농업통계 갱신 절차

1. 새 통계연보·주요행정통계 파일을 `00_source/stat/<새연도>/`에 저장.
2. 빌드 스크립트(`data/05_ag_stat/_build_agri_stats.py`) 실행 → 7종 CSV·_meta.json 재생성.
   (스크립트의 `YEARBOOK_EDITION`·경로·`base_year`만 새 연도로 변경)
3. 앱 재시작 → tab41~45에 새 연도가 KPI·추이·표에 자동 반영.
4. **2013 등 과거 비교**: 각 `*_yearly.csv`에 `연도=2013` 행을 추가만 하면 추이 그래프가 자동 연장(코드 수정 불필요).

> 빌드 스크립트가 유실된 경우 `_build_agri_stats.py`를 다시 두거나, baseline(`jeju_agri_baseline_proposal`) CSV + 통계연보로 재생성하면 됩니다.

---

## 5. 대용량 원자료 색인 (00_source/stat)

용량이 커서 복사하지 않고 위치만 기록하는 자료:

| 파일 | 위치 | 용량 | 용도 |
|---|---|---|---|
| 농업용수 종합계획 본문 PDF | C:\COWORK_SPACE\보고서\01.…(본문).pdf | ~200MB | 농업통계 맥락·검증 |
| 농업용수 종합계획 부록 PDF | C:\COWORK_SPACE\보고서\02.…(부록).pdf | ~460MB | 상세표 검증 |
| 제65회 통계연보(전체) | C:\COWORK_SPACE\보고서\2024년…통계연보(게시용) | ~4MB×18 | 1차 원천(소용량은 stat에 복사 권장) |

소용량 원천(통계연보 3.인구·6.농림수산업 등)은 `00_source/stat/<연도>/`에 복사 보관 권장.

---

## 6. 경로 관리 (config.py)

- 모든 데이터 경로는 `config.py`가 `_pick(신규, 구)`로 관리 → 폴더를 옮겨도 자동 인식, 안 옮겨도 폴백.
- 폴더를 다시 재배치할 때는 `Run_DataMigration_V3.bat`(= `data/_migrate_to_v3_layout.py`) 실행. rename 기반·삭제 없음·멱등(여러 번 안전).

---

## 7. 백업·이관

- 운영본은 `C:\python\jeju_groundwater_dashboard`, 작업본은 `C:\COWORK_SPACE\…`. 백업: `C:\python\jeju_groundwater_dashboard V3.0_260525`.
- 이관 시 폴더 전체 복사 후 `Run_JejuDashboard.bat`로 구동 확인.
