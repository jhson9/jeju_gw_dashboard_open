# 제주 행정구역·시설재배 작업 가이드 (필수 준수)

> **모든 에이전트(로직개발·오류분석·검증·디자인·자료분석)는 tab41/42/43 또는 행정구역 관련 코드를 작성·수정할 때 본 가이드를 반드시 읽고 따른다.** 본 문서는 누적된 라운드(4~12차)에서 반복 발생한 실수를 영구 기록·재발 방지하기 위한 표준이다.

작성: 2026-05-31 (12차 라운드)
위치: `docs/AGENT_GUIDE_jeju_admin.md`

---

## 1. 동명이리(同名異里) — 가장 흔한 함정

같은 리명이 두 시군에 동시에 존재한다. **반드시 (시군, 리명) 페어를 키로 사용**한다. 단일 리명만 키로 쓰면 잘못된 행을 매칭한다.

### 확인된 동명이리 (4쌍)

| 리명 | 제주시 소속 | 서귀포시 소속 |
|---|---|---|
| 수산리 | 애월읍 수산리 | 성산읍 수산리 |
| 세화리 | 구좌읍 세화리 | 표선면 세화리 |
| 고성리 | 애월읍 고성리 | 성산읍 고성리 |
| 신흥리 | 조천읍 신흥리 | 남원읍 신흥리 |

### 필수 패턴

```python
# ❌ 잘못: 단일 키 매칭 — 동명이리 충돌
mapping = {row["법정리"]: row["면적_ha"] for _, row in df.iterrows()}

# ✅ 옳음: (시군, 리명) 페어 키
mapping = {(row["시군"], row["법정리"]): row["면적_ha"] for _, row in df.iterrows()}
```

CSV 빌드 결과(`greenhouse_by_ri.csv` 등)에는 **항상 시군 컬럼이 포함**되어야 한다. 시군 없이 리명만 저장하면 동명이리 구분 불가.

---

## 2. 동(洞)지역 = 리(里)와 같은 단계로 계산

행정 계층:
- 시군 > 읍·면 > 리 (읍/면 안에 리들이 들어감)
- 시군 > 동 (직속, 읍/면 없음)

**동은 읍/면이 아니라 리와 같은 단계**다. 따라서 통계 집계 시:

| 단위 | 의미 |
|---|---|
| 읍·면 (구좌읍, 한경면 등) | "리" 단계의 집합 |
| 동(洞) | 직접 면적 보유 — 리와 동일 단계 |

**우리 코드 규약**: 모든 동을 시군별로 통합한 가상 단위로 처리:
- `제주동` = 제주시 동지역 (일도1동·이도1동·노형동 등 40여 동의 합)
- `서귀포동` = 서귀포시 동지역 (서귀동·동홍동·중문동 등 22여 동의 합)

### 표준 EUP_ORDER (12개, 추자/우도 제외)

```python
EUP_ORDER = ["제주동", "구좌읍", "애월읍", "조천읍", "한림읍", "한경면",
             "서귀포동", "남원읍", "대정읍", "성산읍", "안덕면", "표선면"]
```

이 순서가 모든 표·차트의 표준 행정 순서(보고서 표2-20 기준). 추자면·우도면은:
- **인구·농가 통계**: 포함 (tab41)
- **시설재배 분석**: 제외 (tab43) — EUP GeoJSON 12 features에 미포함

---

## 3. 읍면동↔리 매핑 — 반드시 spatial join

리경계.geojson(177 features)의 `법정리이름` 필드에 **읍/면 정보가 없다**(175/177이 "시군+리명"만, 2개만 "납읍/성읍"으로 "읍" 글자 포함). 텍스트 추출로 읍면동을 도출하면 매핑이 모두 비어 버린다.

### 필수 패턴

```python
# ❌ 잘못: 텍스트 추출 — 0개 매칭됨
def derive_eup(full_name):
    # "제주시고내리" → "?"  (읍/면 텍스트가 풀네임에 없음)
    ...

# ✅ 옳음: spatial join (리 representative_point ⊂ 읍면동 polygon)
import geopandas as gpd
ri_gdf = gpd.read_file("data/00_map/리경계.geojson").set_crs("EPSG:4326")
eup_gdf = gpd.read_file("data/00_map/읍면동경계.geojson").set_crs("EPSG:4326")
ri_pts = ri_gdf.copy()
ri_pts["geometry"] = ri_gdf.geometry.representative_point()
joined = gpd.sjoin(ri_pts, eup_gdf[["NAME","geometry"]],
                   how="left", predicate="within")
# NAME 정규화: "제주시 동지역" → "제주동", "서귀포시 동지역" → "서귀포동"
```

캐시 필수: `@st.cache_data(ttl=3600)` (geopandas import + sjoin은 5초 이상 걸림).

---

## 4. 표 소계 행 — 도전체/시군/읍면동

사용자 요구(12차): 다년도 비교표에 합계·소계 행을 prepend해 전반적 추세를 즉시 파악.

### 전체 모드 (도전체)

```
| 시군   | 지역    | 2013 | 2018 | ... | Δ      | Δ%      |
| 제주도 | 합계    | ...  | ...  | ... | +1,890 | +35.8%  |  ← prepend
| 제주시 | 소계    | ...  | ...  | ... | +xxx   | +x%     |  ← prepend
| 서귀포시| 소계   | ...  | ...  | ... | +xxx   | +x%     |  ← prepend
| 제주시 | 제주동  | 298  | 302  | ... | +35    | +12%    |
| (빈)  | 구좌읍  | 60   | 66   | ... | +44    | +74%    |
| (빈)  | 애월읍  | ...
| 서귀포시| 서귀포동 | 1134 | 1133 | ... |
| (빈)  | 남원읍  | ...
```

### Focus 모드 (특정 읍면동 — 예: 남원읍)

```
| 시군 | 지역         | 2013 | 2018 | ... | Δ    | Δ% |
| (빈) | 남원읍 소계  | xxx  | xxx  | ... | xxx  | xx% |  ← prepend
| 남원읍 | 의귀리      | ...
| (빈)  | 위미리      | ...
```

### 시군 컬럼은 그룹 첫 행만 표시 (반복 제거)

```python
_prev_sg = None
_sgun_vals = []
for _v in disp["시군"].tolist():
    _sgun_vals.append("" if _v == _prev_sg else _v)
    _prev_sg = _v
disp["시군"] = _sgun_vals
```

---

## 5. % 포맷 함정 — 콤마(`,`) 플래그 금지

Python의 구식 `%` 포매팅은 천단위 콤마를 **지원하지 않는다**. `ValueError: unsupported format character ',' (0x2c)`.

```python
# ❌ 잘못 — ValueError
("%+,d" % 1234)        # FAIL
("%+,.0f" % 1234.5)    # FAIL
("%,d" % 1234)         # FAIL

# ✅ 옳음
format(1234, "+,d")        # '+1,234'
format(1234.5, "+,.0f")    # '+1,234'
f"{1234:+,d}"              # '+1,234'
```

이 패턴은 **4·5·7·8·9·10차에 걸쳐 반복 재발**했다. 새 코드 작성 시 `%-format`과 `,`를 함께 쓰면 **즉시 의심**. 패치 후 다음 grep으로 검증:

```bash
grep -rnE '"%[+\-0-9]*,[^"]*[dfeg]"' src/
# 0건이어야 통과
```

---

## 6. fragment 패턴 — 탭 튕김 방지

모든 탭 render() 함수에 `@st.fragment` 데코레이터를 붙인다. 안 붙이면 위젯 변경 시 full rerun → 탭 selected_index 0으로 리셋되어 사용자가 다른 탭으로 튕긴다.

```python
@st.fragment
def render() -> None:
    ...
```

검증: 새 탭 추가 시 `grep "^@st.fragment" src/dashboard/tabs/tab*.py | wc -l`로 누락 확인.

---

## 7. bash 마운트 한글 truncation — 컴파일 신뢰 금지

WSL/sandbox 환경의 bash 마운트는 한글이 많은 .py 파일을 특정 멀티바이트 경계에서 잘라 읽는 알려진 버그가 있다. `python3 -m py_compile` 결과의 "SyntaxError" 가 실제 파일에는 없는 경우가 많다.

### 검증 절차

1. py_compile 에러가 한글 문자열 한가운데서 잘리거나 의미 없는 위치면 → **truncation 의심**
2. Read 도구(파일 도구)로 해당 라인 정밀 확인 → 정상이면 무시
3. 진짜 syntax 에러는 Streamlit 런타임에서 즉시 traceback으로 드러남

---

## 8. 변수명 리팩토링 시 사용처 전수 검색

10·11차에서 `ri_full` ↔ `ri_full_pre` 변경 시 한 곳을 놓쳐 NameError 발생. 변수명 변경 시:

```bash
# 변경 전 모든 사용처 확인
grep -n "ri_full\b" src/dashboard/tabs/tab43_greenhouse.py
# 한글 truncation 우려시 Python으로:
python3 -c "import re; [print(i,l) for i,l in enumerate(open('FILE',encoding='utf-8').read().split('\n')) if re.search(r'\bri_full\b', l)]"
```

---

## 9. 작업 전·중·후 검증 체크리스트

### 작업 전 (Pre)

- [ ] 본 가이드 1~8장 모두 읽음
- [ ] 데이터 스키마 확인 (CSV/GeoJSON properties)
- [ ] 동명이리·동지역 처리 필요 여부 판단
- [ ] 검증 기준값 확인 (REFERENCE_HA 등)

### 작업 중 (Process)

- [ ] (시군, 리명) 페어 키 사용 (단일 키 금지)
- [ ] spatial join으로 읍면동↔리 매핑 (텍스트 추출 금지)
- [ ] `%-format`에 `,` 사용 금지 → `format()` / f-string
- [ ] @st.fragment 데코레이터 (새 탭)
- [ ] 소계 행 prepend (전체/시군/읍면동)
- [ ] 시군 컬럼 그룹 첫 행만 표시

### 작업 후 (Post)

- [ ] Python 정밀 grep: `"%+?,` 패턴 0건 확인
- [ ] py_compile (한글 truncation 에러 무시)
- [ ] Streamlit 런타임 테스트 (focus None / 특정 읍면동 둘 다)
- [ ] 추자/우도 데이터 시설재배에서 제외 확인
- [ ] 12 읍면동 + 4쌍 동명이리 회귀 테스트

---

## 10. 라운드별 누적 학습 (이력)

| 라운드 | 핵심 학습 | 발견 경로 |
|---|---|---|
| 4차 | `"%+,d"` 콤마 미지원 (tab41) | 사용자 발견 |
| 7차 | 같은 실수 재발 (tab43:328) | 사용자 발견 — agent E·F 놓침 |
| 9차 | `@st.fragment` 누락 → 탭 튕김 | 사용자 발견 |
| 10차 | 변수명 리팩토링 검색 누락 (ri_full) | 사용자 발견 |
| 11차 | EUP_COLORS / focus selector | 신규 |
| 12차 | spatial join 매핑 필수 (텍스트 추출 불가) | 매핑 결과 0개 진단 |
| 12차 | 표 소계 행 / 동명이리 가이드 | 신규 가이드 |
| 14차 | px.bar 카테고리 x축 실패 3회 → go.Bar 직접 호출 | x값 dtype/축 type 불일치로 numeric fallback |
| 15차 | EUP_COLORS 대비 12색 + 그룹바 추가 + 지도 zoom 9.0 + 41/42 표 통일 + 추자·우도 14구역 | 사용자 요청 5건 |
| 16차 | (1) timeseries 12 EUP stacked + (3) grouped-bar per-X per-year ramp + focus base color + helper _hex_ramp | 사용자 요청 4건 |
| 16차 | 에이전트 truncation 회귀 — _render_polygon_distribution 80줄 누락 후 pyc로 복구 | 작업중 검증 누락 |
| 16차 | tab41/42 파일 끝 truncation 재발 (L257/L449 SyntaxError) | Phase3 검증 발견 |

## 11. 에이전트 작업 중 파일 truncation/함수 누락 방지

15·16차에서 반복 발생: 에이전트가 Edit 도중 일부 함수 정의를 누락시키고 파일이 잘림.

### 원인
- Edit tool과 disk write 사이의 캐시 불일치 (Windows mount + Korean encoding)
- 큰 함수(80줄+) 또는 한글 다량 chunk를 단일 Edit으로 처리할 때 발생률 증가
- 한글 multi-byte 경계에서 파일이 잘리면 UnicodeDecodeError·SyntaxError 발생

### 필수 절차
1. 큰 함수 수정 시: `grep -n "^def "` 으로 작업 전/후 함수 개수 동일 확인
2. Edit 후 즉시 `wc -l` + `tail -c 100 | od -c` 로 디스크 끝부분 검증
3. `python3 -m py_compile` 통과 + `grep -n "_function_name"` 호출↔정의 짝 매칭
4. 실패 시: `__pycache__/*.pyc` 의 string consts dump 로 변수명·시그니처 복구
5. 백업: 작업 전 큰 함수는 outputs 디렉토리에 사본 보존 (bash cp)
6. Edit silent fail 의심 시: python open(..., 'wb') 로 직접 write

### 복구 패턴 (긴급 시)
```bash
python3 -c "import marshal,sys; f=open(sys.argv[1],'rb'); f.read(16); c=marshal.load(f); print([co.co_name for co in c.co_consts if hasattr(co,'co_name')])"
strings *.pyc | grep -iE "관련 키워드"
```

## Plotly 차트 표준 (14차 추가)
