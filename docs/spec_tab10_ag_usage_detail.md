# UI 스펙 — `tab22_ag_usage_detail` (⑥-2 이용량 세부 분석)

> 디자인 에이전트 산출물 / 작업지시서 §7 구조 준수 / 코드 에이전트가 그대로 구현 가능하도록 작성.
> 최종 갱신: 2026-05-07

---

## 0. 공통 규칙

### 0.1 입력 시그니처

```python
def render(asos_df=None, periods=None) -> None
```

- `tab12_ag_usage.render` 와 동일 패턴.
- 모든 데이터는 다음 우선순위로 로드:
  1. `docs/data/usage_detail_master.json` (12행 마스터)
  2. `docs/data/eup_geometry.csv`, `ri_centroids.csv` (공간)
  3. `docs/data/monthly_matrix_sample.csv` 등 캐시 — 런타임 계산이 가능하면 `ag_well_metrics` 헬퍼로 교체
- 캐시: `@st.cache_data(ttl=3600)` / 키 `(year_range, agg_unit, threshold)`.

### 0.2 색상 / 폰트 / 레이아웃 상수

```python
DIVERGING_USAGE = ["#2c7fb8", "#7fcdbb", "#ffffd9", "#fec44f", "#d7301f"]

EUP_GRID_LAYOUT = {
    "한림읍": (0, 0), "애월읍": (0, 1), "제주시 동지역": (0, 2), "조천읍": (0, 3),
    "한경면": (1, 0),                                              "구좌읍": (1, 3),
    "대정읍": (2, 0),                                              "성산읍": (2, 3),
    "안덕면": (3, 0), "서귀포시 동지역": (3, 1), "남원읍": (3, 2), "표선면": (3, 3),
}
HALLASAN_BLANK = [(1, 1), (1, 2), (2, 1), (2, 2)]

FONT_FAMILY = "Malgun Gothic, Noto Sans KR, sans-serif"
DEFAULT_RATIO_MID = 30.9   # 12개 읍/면/동 허가대비이용(%) 중앙값
DEFAULT_AVG_MID   = 7729   # 12개 읍/면/동 평균이용량(m³/월/공) 중앙값
```

> **위 grid 좌표는 `Reference/01_읍면동_마스터레퍼런스.csv` 의 `grid_row, grid_col` 값과 100% 일치 (`docs/data/spatial_warnings.md` PASS 확인).**
> 한라산 4셀 `(1,1)(1,2)(2,1)(2,2)` 는 항상 `add_trace` 생략 + `update_xaxes/yaxes(visible=False)`.

### 0.3 금지 (모든 섹션 공통)

- `(北)`, `(南)` 한자 출력 금지.
- "한라산", "한라산 국립공원" 텍스트 출력 금지 (코드 문자열에도 포함 금지).
- 가운데 2×2 영역에 사각형 박스 / 라벨 / shape 출력 금지.
- 한자/박스 대신 **한글 캡션** "위 = 제주시 / 아래 = 서귀포시" 만 차트 상단 또는 좌측 caption 으로 노출 가능.
- 모든 colorscale 은 `'RdBu_r'` 또는 `DIVERGING_USAGE` 만 허용. `cmid`/`zmid` 명시 의무.

---

## A. 컨트롤 영역 (탭 상단 1행)

### A.1 위젯 (Streamlit)

| 위젯 | type | 옵션 | 기본값 |
|---|---|---|---|
| 분석 연도 슬라이더 | `st.slider` | 2017 ~ 2025, step=1, range | (직전년도-1, 직전년도) — 단일 연도 선택 시 양 끝 동일 |
| 집계 단위 토글 | `st.radio(horizontal=True)` | `["시", "읍/면/동", "리"]` | `"읍/면/동"` |
| 표시값 토글 | `st.radio(horizontal=True)` | `["총량(m³)", "단위면적당(m³/ha)", "허가대비비율(%)"]` | `"허가대비비율(%)"` |
| 임계값 입력 | `st.number_input(min_value=0.0, step=1.0)` | 비우면 분석기간 중앙값 | `None` → 자동 |

### A.2 입력 검증

- 슬라이더 우측 < 좌측이면 swap.
- 집계 단위 = "리" 일 때만 섹션 F 활성화 / 섹션 D 는 읍/면/동 단위 유지.
- 임계값 입력이 비어있을 때 `compute_midpoint(matrix)` 로 중앙값 산출 → `cmid`/`zmid` 에 사용.

### A.3 캐시 키

`(year_min, year_max, agg_unit, display_metric, threshold_or_none)` 5-튜플.

---

## B. 섹션 1 — 행정구역별 총 이용량 트리맵 (PPTX 슬라이드 1 좌)

### B.1 입력 데이터

```python
master_df = load_master_json("docs/data/usage_detail_master.json")  # 12행
# 필수 컬럼: eup_dong, farm_area_ha, wells_total, avg_monthly_usage_m3, usage_ratio_pct
```

### B.2 차트 객체

- `plotly.express.treemap` (단일 트리맵, dual-zone 분리는 path 첫 단계로 구현):

```python
import plotly.express as px
master_df["zone"] = master_df["eup_dong"].map(
    lambda x: "위 = 제주시" if EUP_GRID_LAYOUT[x][0] <= 1 else "아래 = 서귀포시"
)
fig = px.treemap(
    master_df,
    path=["zone", "eup_dong"],
    values="avg_monthly_usage_m3",          # 또는 farm_area_ha — 표시값 토글 따라
    color="usage_ratio_pct",
    color_continuous_scale=DIVERGING_USAGE, # 또는 'RdBu_r'
    color_continuous_midpoint=DEFAULT_RATIO_MID,
    hover_data=["farm_area_ha", "wells_total", "avg_monthly_usage_m3"],
)
```

### B.3 라벨 / 캡션

- 셀 라벨 (texttemplate):
  `"{label}<br>농지 %{customdata[0]} ha · %{customdata[1]} 공<br>%{customdata[2]} m³/월/공"`
- `fig.update_traces(textinfo="label+text")`
- `colorbar.title = "허가대비이용(%)"`, `colorbar.title.side = "right"`.
- 차트 상단 caption: `"위 = 제주시 / 아래 = 서귀포시"` (st.caption 또는 fig.add_annotation, x=0.5 y=1.05).

### B.4 금지 재확인

- `path` 첫 단계의 zone 라벨에 `(北)`/`(南)` 한자 절대 사용 금지. 위/아래 한글만.
- 한라산 행은 master_df 에 존재하지 않음 — 트리맵에 자동 미포함.

---

## C. 섹션 2 — 월별 총 이용량 히트맵 (신규 핵심)

### C.1 입력 데이터

표시값 토글에 따라:

| 표시값 | 매트릭스 | 단위 | 색상 midpoint |
|---|---|---|---|
| 총량(m³) | `monthly_matrix` | `m³/월` | 분석기간 중앙값 또는 `threshold` |
| 단위면적당(m³/ha) | `unit_area_matrix` = monthly / farm_area_ha | `m³/ha` | 분석기간 중앙값 |
| 허가대비비율(%) | `ratio_matrix` = monthly / (permit_m3day × 30) × 100 | `%` | `30.9` (DEFAULT_RATIO_MID) 또는 사용자 임계값 |

샘플 데이터:
- `docs/data/monthly_matrix_sample.csv`
- `docs/data/ratio_matrix_sample.csv`
- `docs/data/unit_area_matrix_sample.csv`

런타임 계산 헬퍼: `usage_detail_helpers.build_monthly_heatmap_df(master_df, year_range, agg_unit)`.

### C.2 차트 객체

```python
import plotly.graph_objects as go
fig = go.Figure(go.Heatmap(
    z=matrix.values,                        # shape (n_region, 12)
    x=[f"{m}월" for m in range(1, 13)],
    y=matrix.index.tolist(),
    colorscale="RdBu_r",
    zmid=midpoint,
    zauto=False,
    colorbar=dict(title=dict(text=unit_label, side="right")),
    hovertemplate="%{y} · %{x}<br>값=%{z:.1f}<extra></extra>",
))
fig.update_layout(font=dict(family=FONT_FAMILY), height=420)
```

### C.3 핫스팟/저이용 마커

- `docs/data/hotspots.json` 의 `hot` (남원읍·서귀포시 동지역·성산읍) → 행 라벨 좌측에 ▲ 마커, 또는 해당 행 모든 셀 위에 `fig.add_annotation(x=month, y=eup, text="▲", showarrow=False)`.
- `cold` (대정읍·한경면·구좌읍) → ▽ 마커.
- 핫/콜드 동시 강조 시 우측 범례 `st.caption`: `"▲ 핫스팟 (상위 3 읍/면/동, 60.7~41.6%) · ▽ 저이용 (하위 3, 20.1~25.2%)"`.

### C.4 X축 / 정렬

- `tickvals = list(range(12))`, `ticktext = ["1","2",...,"12"]` — **`"1월"` 도 허용하지만 4×4 미니 히트맵(섹션 D)과 맞추려면 정수 1~12 권장.**
- y축은 `usage_ratio_pct` 내림차순 정렬 (집계 단위 = 읍/면/동 일 때).
- 집계 단위 = "시" 일 때 y축은 `["제주시","서귀포시"]` 2행만.

---

## D. 섹션 3 — 읍/면/동 4×4 미니 히트맵 그리드 (지리 배치)

### D.1 입력

`monthly_matrix` (또는 ratio/unit_area). 12행 × 12개월. Index = `eup_dong`.

### D.2 차트 객체

```python
from plotly.subplots import make_subplots

fig = make_subplots(
    rows=4, cols=4,
    horizontal_spacing=0.02, vertical_spacing=0.04,
    subplot_titles=[None]*16,   # 위치별 후처리
)

for eup, (r, c) in EUP_GRID_LAYOUT.items():
    z = matrix.loc[eup].values.reshape(1, 12)   # shape (1, 12)
    fig.add_trace(
        go.Heatmap(
            z=z,
            x=list(range(1, 13)),
            y=[eup],
            coloraxis="coloraxis",
            showscale=False,
            hovertemplate=f"{eup} · %{{x}}월<br>값=%{{z:.1f}}<extra></extra>",
        ),
        row=r+1, col=c+1,
    )
    # subplot 제목 후처리
    n_well = master_df.loc[master_df.eup_dong == eup, "wells_total"].iat[0]
    avg    = matrix.loc[eup].mean()
    fig.layout.annotations[r*4 + c].update(
        text=f"{eup}  n={n_well}  평균 {avg:,.0f} m³",
        font=dict(size=10),
    )
    # 모든 미니 히트맵 X축
    fig.update_xaxes(
        tickvals=list(range(1, 13)),
        ticktext=[str(m) for m in range(1, 13)],
        row=r+1, col=c+1,
    )
    fig.update_yaxes(visible=False, row=r+1, col=c+1)

# 한라산 4셀: add_trace 생략 + axes 완전 숨김
for r, c in HALLASAN_BLANK:
    fig.update_xaxes(visible=False, showgrid=False, zeroline=False, row=r+1, col=c+1)
    fig.update_yaxes(visible=False, showgrid=False, zeroline=False, row=r+1, col=c+1)
    # subplot annotation 도 빈 문자열로 (한자/한라산 텍스트 금지)
    fig.layout.annotations[r*4 + c].update(text="")

fig.update_layout(
    coloraxis=dict(
        colorscale="RdBu_r",
        cmid=midpoint,
        colorbar=dict(title=dict(text=unit_label, side="right"), len=0.85),
    ),
    font=dict(family=FONT_FAMILY),
    height=620, width=None,
    margin=dict(l=20, r=20, t=40, b=20),
)
```

### D.3 캡션 (한자/박스 금지)

- 차트 위에 `st.caption("위 = 제주시 / 아래 = 서귀포시")`.
- 가운데 2×2 영역에는 어떤 `add_shape`/`add_annotation` 호출도 하지 말 것.

### D.4 검증 포인트 (코드 에이전트가 자체 점검)

- `len(EUP_GRID_LAYOUT) == 12`
- `set(EUP_GRID_LAYOUT.keys()) == set(master_df.eup_dong)`
- `HALLASAN_BLANK` 4셀에 대해 `add_trace` 호출 0회.
- 모든 미니 히트맵 X축 `tickvals == [1..12]`, `ticktext == ["1".."12"]`.

---

## E. 섹션 4 — 관정별 이용량 (월별 / 일평균 산술·중앙값)

### E.1 입력

`ag_well_loader.load_master()` + `ag_well_metrics` 의 관정 단위 산출 결과를
`build_well_panel_df(year_range)` 헬퍼로 정리:

```
columns: well_id, eup_dong, well_type(공공/사설), m1..m12, daily_avg, daily_median, ratio_pct
```

### E.2 4-패널 dual-zone 레이아웃 (PPTX 슬라이드 2~3)

```python
fig = make_subplots(
    rows=2, cols=2,
    subplot_titles=[
        "월별 이용량 — 위 = 제주시",
        "월별 이용량 — 아래 = 서귀포시",
        "일평균 산술 — 위 = 제주시",
        "일평균 산술 — 아래 = 서귀포시",
    ],
    specs=[[{"type":"heatmap"}, {"type":"heatmap"}],
           [{"type":"heatmap"}, {"type":"heatmap"}]],
    horizontal_spacing=0.05, vertical_spacing=0.10,
)
```

- 제주시 권역 = `EUP_GRID_LAYOUT[eup][0] <= 1` 인 6개 읍/면/동.
- 서귀포시 권역 = `EUP_GRID_LAYOUT[eup][0] >= 2` 인 6개 읍/면/동.
- 각 패널은 관정 단위 row, x=1..12 month, color=`coloraxis="coloraxis"`.

### E.3 색상

`coloraxis = dict(colorscale='RdBu_r', cmid=daily_avg.median(), colorbar=...)` — 4개 패널 공유.

### E.4 라벨 규칙

- 패널 제목에 `(北)`/`(南)`/"한라산" 절대 사용 금지. 위 코드의 한글 라벨만 허용.
- y축에는 `well_id` 표시, hover 에 `well_type` (공공/사설) 추가.

---

## F. 섹션 5 — 리 단위 드릴다운 (집계 단위 = 리 일 때만)

### F.1 입력

- `docs/data/ri_centroids.csv` (172행: `eup_dong, 법정리명, area_km2, lon, lat, parent_grid_row, parent_grid_col`)
- `ri_monthly_matrix` (172 × 12) — `usage_detail_helpers.build_ri_monthly_matrix(year_range)` 가 반환.

### F.2 small multiples — 읍/면/동 별 그룹

```python
parent_eup = st.selectbox("읍/면/동 선택", master_df["eup_dong"])
ri_subset = ri_df[ri_df["eup_dong"] == parent_eup]
# 좌측: scatter_mapbox or scatter_geo (lon, lat) 미니 지도
# 우측: line chart x=1..12, 각 line = 리, y=월이용량
```

### F.3 좌측 미니 지도

- `plotly.express.scatter_map` 또는 기존 `map_helpers` 재사용.
- 마커 size = area_km2, color = 12월 평균 이용량 (RdBu_r, cmid=중앙값).
- 한라산 영역에는 어떤 마커/박스 출력 금지 — ri_centroids.csv 에 한라산 리가 없으므로 자동 제외됨.

### F.4 우측 라인 차트

```python
fig = px.line(
    ri_long, x="month", y="usage_m3", color="법정리명",
    line_shape="spline",
)
fig.update_xaxes(tickvals=list(range(1, 13)), ticktext=[str(m) for m in range(1, 13)])
fig.update_layout(font=dict(family=FONT_FAMILY))
```

### F.5 캡션

- 선택된 읍/면/동에 대해 `st.caption(f"{parent_eup} · 리 {n}개 · 총 면적 {area_km2:.1f} km²")`.
- "위/아래" 한글 캡션은 부모 zone 에 따라 자동 (제주시/서귀포시).

---

## G. 코드 에이전트 인계 — 헬퍼 시그니처

```python
# src/dashboard/usage_detail_helpers.py

DIVERGING_USAGE = ["#2c7fb8", "#7fcdbb", "#ffffd9", "#fec44f", "#d7301f"]
EUP_GRID_LAYOUT = {
    "한림읍": (0, 0), "애월읍": (0, 1), "제주시 동지역": (0, 2), "조천읍": (0, 3),
    "한경면": (1, 0),                                              "구좌읍": (1, 3),
    "대정읍": (2, 0),                                              "성산읍": (2, 3),
    "안덕면": (3, 0), "서귀포시 동지역": (3, 1), "남원읍": (3, 2), "표선면": (3, 3),
}
HALLASAN_BLANK = [(1, 1), (1, 2), (2, 1), (2, 2)]

def load_master_json(path: str = "docs/data/usage_detail_master.json") -> pd.DataFrame: ...
def load_ri_centroids(path: str = "docs/data/ri_centroids.csv") -> pd.DataFrame: ...
def load_hotspots(path: str = "docs/data/hotspots.json") -> dict: ...

def grid_from_centroids(shp_path: str | None = None) -> dict[str, tuple[int, int]]:
    """shapefile 이 없으면 EUP_GRID_LAYOUT 그대로 반환 (오프라인 호환)."""

def build_monthly_heatmap_df(master_df, year_range, agg_unit) -> pd.DataFrame:
    """index=region, columns=1..12, values=월이용량 (m³)."""

def build_ratio_matrix(master_df, year_range) -> pd.DataFrame:
    """monthly / (permit_m3day × 30) × 100. zmid=DEFAULT_RATIO_MID."""

def build_unit_area_matrix(master_df, year_range) -> pd.DataFrame:
    """monthly / farm_area_ha. 단위 m³/ha."""

def build_ri_monthly_matrix(year_range) -> pd.DataFrame:
    """index=법정리명, columns=1..12."""

def annotate_hotspots(df, hotspots_json) -> pd.DataFrame:
    """df 에 'is_hot', 'is_cold' 열 추가."""

def compute_midpoint(matrix: pd.DataFrame, percentile: float = 50.0) -> float: ...
```

---

## H. 검증 체크리스트 (코드 에이전트 자체 점검)

| ID | 항목 | 기대 |
|---|---|---|
| H1 | `len(EUP_GRID_LAYOUT) == 12` | True |
| H2 | `HALLASAN_BLANK == [(1,1),(1,2),(2,1),(2,2)]` | True |
| H3 | `len(DIVERGING_USAGE) == 5` 모든 항목 `#RRGGBB` | True |
| H4 | 4×4 subplot 한라산 4셀 add_trace 호출 0회 | True |
| H5 | 모든 미니 히트맵 X축 tickvals == [1..12], ticktext == ["1".."12"] | True |
| H6 | 코드/spec 어디에도 `(北)`, `(南)`, `한라산`, `한라산 국립공원` 텍스트 없음 | True |
| H7 | 모든 colorscale 이 `'RdBu_r'` 또는 `DIVERGING_USAGE`, `cmid`/`zmid` 명시 | True |
| H8 | `usage_detail_master.json` 의 12행 농지면적·관정수·평균이용량이 §1.1 표와 ±0.1% 일치 | True (`docs/data/discrepancy_report.md` PASS) |
| H9 | `EUP_GRID_LAYOUT` 의 키 == `master_df.eup_dong` 12개 | True |
| H10 | 4×4 그리드 정합성 | `docs/data/spatial_warnings.md` PASS |

---

## I. 산출물 인덱스 (이 spec 이 참조하는 파일)

| 경로 | 용도 |
|---|---|
| `docs/data/usage_detail_master.json` | 12행 마스터 (모든 섹션 입력) |
| `docs/data/discrepancy_report.md` | §1.1 표 ↔ master CSV 일치 보고 (PASS) |
| `docs/data/eup_geometry.csv` | 12행 + 한라산 1행 = 13행 (centroid + grid) |
| `docs/data/ri_centroids.csv` | 172행 (섹션 F 입력) |
| `docs/data/spatial_warnings.md` | 4×4 grid 정합성 보고 (PASS) |
| `docs/data/monthly_matrix_sample.csv` | 시뮬레이션 샘플 (스키마 가이드) |
| `docs/data/ratio_matrix_sample.csv` | 시뮬레이션 샘플 |
| `docs/data/unit_area_matrix_sample.csv` | 시뮬레이션 샘플 |
| `docs/data/hotspots.json` | hot/cold 라벨 |

---

PPT 원본의 한자 표기 / 가운데 박스 / "한라산 국립공원" 텍스트는 본 스펙에서 모두 제거됨에 유의.
