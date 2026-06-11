# 신규 관측소 데이터를 대시보드에 반영하기 — 권장 적용 절차

업데이트(2026-05-01)로 관측망 데이터가 65→**177**행, 일자료 CSV 가 59→**177**개로 늘어났습니다.
정보 파일과 일자료 CSV 는 1:1 로 정확히 일치합니다.

다만 **현재 코드는 아직 65개 JD 관측소만 인식**하므로 아래 절차대로 적용해야 새 데이터가 대시보드에 반영됩니다.

---

## 0. 추천 시나리오 (가장 안전)

```
1단계  config 의 WATERSHEDS 보강 (애월·안덕만 추가)  → 5분
2단계  파서 glob 패턴 확장                          → 5분
3단계  python process_gwlevel.py 실행               → 1분
4단계  대시보드 새로고침 / 재실행                   → 즉시
```

---

## 1단계 — `config.py` 의 수역 목록 보강 (필수)

`config.WATERSHEDS` 에 **2개만** 추가합니다 (추자유역은 본 데이터셋에 없으므로 추가 불필요):

```python
# 신규 정보에서 추가로 등장한 유역
{"name": "애월",  "aws": "제주",  "color": "#9370DB"},
{"name": "안덕",  "aws": "고산",  "color": "#FF8C42"},
```

또한 `watershed_mapper.py` 의 `load_station_to_watershed_map` 에서 "유역" 접미사만 제거하던 부분을 다음과 같이 보강해 "수역" 표기 차이도 흡수하세요(조천수역·남원수역 1건씩 존재):

```python
df["수역"] = (df["유역명"].astype(str)
              .str.replace("유역", "", regex=False)
              .str.replace("수역", "", regex=False)   # 신규: 표기 차이 흡수
              .str.strip())
```

이 두 가지를 적용하면 **JM신엄(애월), JR/JQ 안덕유역, 조천·남원수역** 표기들이 제대로 집계됩니다.

> 참고: 31건은 정보 파일의 `유역명` 자체가 비어 있어 수역별 집계에서 자동 제외됩니다(개별 관측정 차트는 정상 표시). 향후 정보 갱신으로 채워지면 자동 반영됩니다.

---

## 2단계 — 파서 glob 패턴을 `JD*` → `*` 로 확장 (필수)

수정해야 할 위치(현재 `JD*.xls` 만 읽음):

| 파일 | 라인 | 현재 | 권장 |
|---|---|---|---|
| `src/collectors/gwlevel_parser.py` | 149~150 | `glob("JD*.xls")` | `glob("[A-Z][A-Z]*.xls")` |
| `src/collectors/gwlevel_day_parser.py` | 218 | `glob("JD*.xls")` | `glob("[A-Z][A-Z]*.xls")` |
| `src/dashboard/tabs/tab99_admin.py` | 94, 160~161 | `glob("JD*.xls")` | `glob("[A-Z][A-Z]*.xls")` |

> `[A-Z][A-Z]*.xls` 패턴은 JD/JH/JI/JM/JP/JQ/JR/JW/PW 등 **알파벳 2자 이상 prefix**를 모두 포함하면서, 임시 파일(`~$xxx.xls`)은 자연스럽게 제외합니다.

---

## 3단계 — 처리 파이프라인 재실행

```bash
cd C:\COWORK_SPACE\jeju_groundwater_dashboard
python process_gwlevel.py
```

이 명령은 다음을 수행합니다:
- `data/Row_Data/Day/*.xls` 177개 일괄 파싱 (이미 CSV 가 있으면 upsert)
- `data/GWlevel/by_station_day/` 갱신
- `data/0_JD관측망_정보.xlsx` 의 유역 매핑으로 **수역별 집계 재계산**
- `data/GWlevel/by_watershed/*.csv` 재생성

> 본 업데이트에서는 코드 패치 없이 데이터/CSV 만 채워두었으므로, 위 단계 후에야 대시보드에서 신규 관측소가 보입니다.

---

## 4단계 — 대시보드 새로고침

```bash
streamlit run src/dashboard/app.py
```

이미 실행 중이라면 브라우저 새로고침(Ctrl/Cmd+R)으로 충분합니다.

---

## 검증 체크리스트

업데이트 후 다음을 확인하세요:

- [ ] 좌측 관측정 선택 드롭다운에 JR·JQ 등 신규 prefix 가 표시되는가
- [ ] `Tab 4 (관리)` 에서 일자료 xls 파일 수가 **177** 로 표시되는가
- [ ] `data/GWlevel/by_watershed/` 에 14개(또는 보강 시 16개) csv 가 모두 갱신 시간이 최신인가
- [ ] 지도 탭(Tab 5)에 새 관측정 포인트가 찍히는가

---

## 롤백 절차 (문제 발생 시)

```bash
cd C:\COWORK_SPACE\jeju_groundwater_dashboard\data
# 1) 관측망 정보 롤백 (최초 65행)
copy /Y 0_JD관측망_정보_backup_20260501_091402.xlsx 0_JD관측망_정보.xlsx
# 2) Row_Data 롤백 (PowerShell)
Remove-Item -Recurse Row_Data\Day\*
Copy-Item -Recurse Row_Data\Day_backup_20260501_091012\* Row_Data\Day\
# 3) CSV 재생성
cd ..
python process_gwlevel.py
```

---

## 부록 — 월자료에 대한 보충

기존 시스템은 두 종류의 원본을 분리 보관합니다.

| 폴더 | 형식 | 내용 |
|---|---|---|
| `Row_Data/Month/JD*.xls` | 진짜 xlsx (S11~S25 시트) | 월별 다센서 원본 |
| `Row_Data/Day/JD*.xls`   | HTML 디스가이즈 (wide YxYY-MM-DD) | 일별 EL 원본 |

이번에 받은 `Day/26_05/` 는 **일자료** 만 포함합니다. 월자료(`Row_Data/Month/`) 는 신규 관측소 분이 없으므로:

- ✅ **현재 처리**: 신규 관측소의 월별 csv 는 *일자료를 월평균으로 집계*해 생성. 다센서 정보는 NA.
- ⏳ **추후 보강**: 월별 다센서(GL/Pressure/Temp/EC/Barometa/Battery) 가 필요하면, 같은 도구에서 *월자료* 를 받아 `Row_Data/Month/` 에 추가하고 `gwlevel_parser.run_full_pipeline()` 을 다시 실행하면 됩니다.

대시보드의 월별 EL 차트는 신규 관측소도 정상 표시됩니다.
