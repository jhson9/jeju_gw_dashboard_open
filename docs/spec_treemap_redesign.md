# 트리맵 재설계 통합 명세서 (행정구역별 + 리 단위)

> 데이터분석 에이전트 → 로직 개발 에이전트 인계 문서
> 최종 갱신: 2026-05-07
> 본 문서는 기존 `docs/spec_tab22_ag_usage_detail.md` §B 섹션을 **대체** (해당 파일은 보존, 본 문서가 우선).

---

## 0. 변경 배경 — 사용자 요청 요약

1. 현재 `_render_treemap()` 의 단순 dual-zone (위/아래 2-bar) 구현은 **잘못됨** → 폐기.
2. 사용자 PPT 원본은 **2행 × 6열 가변폭 stacked grid** + 행 사이 한라산 캡션 형식.
3. 셀 폭 = 농지면적 비율 (시간 불변), 색 = 단위면적당 이용량 (연도별 변화).
4. 셀 라벨 4줄: 이름 / ha · 공 / ㎥/ha / 강수.
5. 셀 순서 절대 변경 금지 (PPT 그대로 — 서→동, 단 서귀포 행은 PPT 순서 그대로).
6. 리 단위도 동일 형식 — 부모 슬롯 안에서 squarify 분할.
7. 분석 연도 컨트롤도 PPT 형식 (점 슬라이더 2017~2025, 양 끝 핸들 yyyy-mm).

---

## A. plotly 구현 방식 — 옵션 비교 및 권장

| 옵션 | 방법 | 장점 | 단점 | 추천 |
|---|---|---|---|---|
| **1** | `go.Bar(orientation='h')` × 2 (제주시/서귀포시 각 1 trace, stacked) | 단순, 폭 정확, 라벨은 `text`/`hovertext` | 다중 라벨(4줄) 표시 까다로움, 셀 내 위치 제어 약함 | △ |
| **2** | `go.Treemap` + path/values 강제 | plotly 네이티브 | squarify 알고리즘이 행 분할을 비결정적으로 수행, 좌→우 순서 강제 어려움, 한라산 캡션 삽입 불가 | ✗ |
| **3** | `go.Heatmap` | 2D 격자 | 등폭만 지원, 가변폭 셀 구현 불가 | ✗ |
| **4** | `add_shape(type='rect')` + `add_annotation()` 직접 그리기 | **100% 좌표 제어, 라벨 4줄 자유 배치, 한라산 캡션 임의 위치, 색상 직접 매핑** | 보일러플레이트 코드 다소 길어짐, hover tooltip 별도 구현 필요 (`add_trace(go.Scatter, hovertext=…, mode='markers', opacity=0)`) | ✓ **권장** |

### A.1 권장: 옵션 4 (Custom shape + annotation)

**이유**:
- PPT 픽셀 단위 재현이 사용자의 명시적 요구. 옵션 4 가 유일하게 좌표 100% 제어 가능.
- 4줄 라벨, 셀 내부 위치 미세조정, 한라산 캡션 정확 위치, 색상값-셀 매핑 명시적.
- 리 단위 squarify 도 동일 framework 안에서 `add_shape` 반복 호출로 처리 가능 (`squarify` 라이브러리 사용 권장).

### A.2 옵션 4 구현 골격 (의사코드)

```python
import plotly.graph_objects as go
import squarify  # 리 단위 사용 시

def render_eup_treemap(cells_df, year, color_metric_fn):
    fig = go.Figure()
    fig.update_layout(
        xaxis=dict(range=[0, 1], visible=False, fixedrange=True),
        yaxis=dict(range=[0, 1], visible=False, fixedrange=True),
        margin=dict(l=10, r=80, t=40, b=40),  # r 여유 = colorbar
        height=420,
        font=dict(family="Malgun Gothic, Noto Sans KR, sans-serif"),
        showlegend=False,
        plot_bgcolor="white",
    )

    # 행1 (제주시): y in [0.55, 1.0]
    # 캡션 영역: y in [0.45, 0.55]
    # 행2 (서귀포시): y in [0.0, 0.45]
    ROW1_Y = (0.55, 1.00)
    ROW2_Y = (0.00, 0.45)

    # 헤더 캡션
    fig.add_annotation(x=0.5, y=1.02, text="제주시", showarrow=False,
                       font=dict(size=14, color="#333"), xref="paper", yref="paper")
    fig.add_annotation(x=0.5, y=-0.06, text="서귀포시", showarrow=False,
                       font=dict(size=14, color="#333"), xref="paper", yref="paper")
    # 한라산 캡션
    fig.add_annotation(x=0.5, y=0.50, text="▲ 한라산 국립공원 (농업용 관정 없음)",
                       showarrow=False, font=dict(size=11, color="#666"),
                       xref="paper", yref="paper")

    for zone, y_lo, y_hi in [("제주시", *ROW1_Y), ("서귀포시", *ROW2_Y)]:
        zone_df = cells_df[cells_df["zone"] == zone].sort_values("cell_order")
        x_cur = 0.0
        for _, row in zone_df.iterrows():
            w = row["width_pct"] / 100.0
            x0, x1 = x_cur, x_cur + w
            color_val = color_metric_fn(row["eup_dong"], year)  # 동적 산출
            fill_color = sample_colorscale("YlOrRd", normalize(color_val, 1100, 2300))

            # 사각형
            fig.add_shape(type="rect", x0=x0, y0=y_lo, x1=x1, y1=y_hi,
                          fillcolor=fill_color, line=dict(color="white", width=2))

            # 4줄 라벨
            cx, cy = (x0 + x1) / 2, (y_lo + y_hi) / 2
            text_color = "white" if color_val > 1700 else "#222"
            label = (
                f"<b>{row['label_line1']}</b><br>"
                f"<span style='font-size:10px'>{row['label_line2']}</span><br>"
                f"<span style='font-size:10px'>{int(color_val):,} ㎥/ha</span><br>"
                f"<span style='font-size:9px;color:#aaa'>{row['label_line4']}</span>"
            )
            fig.add_annotation(x=cx, y=cy, text=label, showarrow=False,
                               font=dict(color=text_color, size=11),
                               align="center", xref="x", yref="y")

            # Hover (투명 scatter)
            fig.add_trace(go.Scatter(
                x=[cx], y=[cy], mode="markers",
                marker=dict(size=1, opacity=0),
                hovertext=f"{row['eup_dong']}<br>{int(color_val):,} ㎥/ha",
                hoverinfo="text", showlegend=False,
            ))
            x_cur = x1

    # 컬러바 (별도 dummy heatmap)
    fig.add_trace(go.Heatmap(
        z=[[1100, 2300]], colorscale="YlOrRd", zmin=1100, zmax=2300,
        showscale=True, opacity=0,
        colorbar=dict(title="단위면적당 연간이용량<br>(㎥/ha)",
                      tickvals=[1200, 1400, 1600, 1800, 2000, 2200],
                      thickness=12, len=0.85, x=1.02),
    ))
    return fig
```

> 코드 에이전트는 위 골격을 바탕으로 `usage_detail_helpers.py` 에 헬퍼 4개, `tab22_ag_usage_detail.py` 에 render 함수 2개를 작성.

---

## B. 분석 연도 컨트롤 — 권장 위젯

### B.1 PPT 형식 분석
- 점 슬라이더 (2017, 2018, ..., 2025) — 9개 점
- 양 끝 핸들 (start, end) — 빨간색 점 + 라벨 "2025-01" / "2025-12"
- 즉 **연·월 단위 dual-handle range slider**

### B.2 Streamlit 1.47.1 구현 (project_streamlit_version 메모리 준수)

**권장 = 방식 1 (월 단위 dual handle)**:
```python
import datetime as dt

months = [dt.date(y, m, 1) for y in range(2017, 2026) for m in range(1, 13)]
start, end = st.select_slider(
    "분석 연도",
    options=months,
    value=(dt.date(2025, 1, 1), dt.date(2025, 12, 1)),
    format_func=lambda d: d.strftime("%Y-%m"),
)
year_min, year_max = start.year, end.year
month_min, month_max = start.month, end.month
```

**대안 = 방식 2 (연 단위 dual handle, 단순)**:
```python
year_range = st.slider(
    "분석 연도",
    min_value=2017, max_value=2025, value=(2025, 2025), step=1,
)
```

**최종 권장**: **방식 2 (연 단위 dual handle)** — 사용자 메모리 (단순/명확), 월 단위는 옵션으로 separate `st.slider("월 범위", 1, 12, (1, 12))` 추가.

### B.3 컨트롤 영역 레이아웃 (탭 상단 1행)
```
┌─────────────────────────────────────────────────────────────────────┐
│ [집계 단위 ▾]   분석 연도: ●---●---●---●---●---●---●---●---●        │
│                          2017 18  19  20  21  22  23  24 [25-01•25-12]│
└─────────────────────────────────────────────────────────────────────┘
```

---

## C. 헤더 / 섹션 구조

```python
st.markdown("## 행정구역별 총 이용량 (기간내 평균)")
# (분석 연도 슬라이더 결과 표시)
st.caption(f"분석 기간: {year_min}-{month_min:02d} ~ {year_max}-{month_max:02d}")

# 트리맵 (옵션 4 구현)
fig_eup = build_eup_treemap(cells_df, year_range)
st.plotly_chart(fig_eup, use_container_width=True)

# 집계 단위 = '리' 일 때만 추가 표시
if agg_unit == "리":
    st.markdown("### 리(법정동) 단위 세부 트리맵")
    fig_ri = build_ri_treemap(ri_cells_df, year_range)
    st.plotly_chart(fig_ri, use_container_width=True)
```

---

## D. 금지 사항 (재확인)

### D.1 트리맵 (섹션 B)
- (北), (南) 한자 **금지** — 한글 "제주시"/"서귀포시" 만 허용
- 행 사이 캡션 = `"▲ 한라산 국립공원 (농업용 관정 없음)"` 만 허용 (이 외 텍스트 금지)
- 셀 순서 변경 금지 (`treemap_eup_cells.csv` 의 `cell_order` 절대 준수)
- 셀 폭 합계 = 100% (각 행) — 코드에서 정규화 의무

### D.2 4×4 미니 히트맵 그리드 (기존 섹션 D)
- 한라산 4셀 (1,1)(1,2)(2,1)(2,2) 에 텍스트/박스 출력 절대 금지 (기존 규칙 유지)
- 본 트리맵 재설계는 미니 히트맵 섹션을 **건드리지 않음**

### D.3 다른 섹션
- 섹션 C (월별 히트맵), D (4×4 미니 히트맵), E (관정별 dual-zone), F (리 드릴다운) 는 **수정 금지**
- 본 명세는 섹션 B만 재설계

---

## E. 로직 개발 에이전트 작업 범위

### E.1 수정 대상 파일

| 파일 | 변경 |
|---|---|
| `src/dashboard/usage_detail_helpers.py` | 신규 함수 추가 (아래 §E.2) |
| `src/dashboard/tabs/tab22_ag_usage_detail.py` | `_render_treemap()` 폐기 → 신규 `_render_eup_treemap()` + `_render_ri_treemap()` |

### E.2 신규 함수 시그니처

```python
# usage_detail_helpers.py 신규 추가

def build_eup_treemap_data(
    master_df: pd.DataFrame,
    year_range: tuple[int, int],
    *,
    cells_csv: str = "docs/data/treemap_eup_cells.csv",
) -> pd.DataFrame:
    """
    `treemap_eup_cells.csv` 12행을 로드 + 분석 연도별 color_value 동적 계산.
    Returns columns: zone, eup_dong, cell_order, width_pct,
                     color_value, label_line1..4 (color_value 만 동적)
    """
    ...

def build_ri_treemap_data(
    master_df: pd.DataFrame,
    year_range: tuple[int, int],
    *,
    cells_csv: str = "docs/data/treemap_ri_cells.csv",
    fallback_mode: str = "parent",  # 'parent' = 옵션A, 'split' = 옵션B
) -> pd.DataFrame:
    """
    `treemap_ri_cells.csv` 171행을 로드 + 색상 동적 계산.
    fallback_mode='parent' 면 부모 unit_area 를 모든 자식 리에 동일 적용.
    """
    ...

def compute_unit_area_usage(
    master_row: dict, year: int | None = None
) -> float:
    """
    공식: avg_monthly_usage_per_well × wells_public × 12 / farm_area_ha
    year=None 이면 master_row 의 다년 평균값 사용.
    """
    ...

def sample_colorscale_value(value: float, cmin: float, cmax: float,
                            colorscale: str = "YlOrRd") -> str:
    """plotly colors.sample_colorscale wrapper. 정규화 + clip + #RRGGBB 반환."""
    ...
```

### E.3 tab10 신규 render 함수

```python
# tab22_ag_usage_detail.py

def _render_eup_treemap(year_range, master_df):
    cells = build_eup_treemap_data(master_df, year_range)
    fig = _build_treemap_figure(cells, mode="eup")  # §A.2 골격 사용
    st.plotly_chart(fig, use_container_width=True)

def _render_ri_treemap(year_range, master_df):
    ri_cells = build_ri_treemap_data(master_df, year_range)
    fig = _build_treemap_figure(ri_cells, mode="ri")
    st.plotly_chart(fig, use_container_width=True)

def _build_treemap_figure(cells_df, mode: str):
    """공통 figure 빌더 — eup 모드: 셀 1개=읍/면/동, ri 모드: 부모슬롯 안에 squarify"""
    ...
```

### E.4 fragment 패턴 준수
- 기존 tab5/6/7/8 의 단일 fragment 패턴 (memoty: project_fragment_pattern) 동일 적용
- `render()` 전체에 `@st.fragment` 데코레이터 유지

---

## F. 검증 체크리스트 (로직 개발 후 확인)

- [ ] **F1.** 셀 폭 비율이 `treemap_eup_cells.csv` 의 `width_pct` 와 ±0.1% 이내 일치
- [ ] **F2.** 셀 순서 12개가 §`treemap_eup_layout.md` §1.2 와 100% 일치
- [ ] **F3.** colorscale = `'YlOrRd'`, cmin=1100, cmax=2300
- [ ] **F4.** 컬러바 제목 = `"단위면적당 연간이용량 (m³/ha)"`
- [ ] **F5.** 각 셀 라벨 4줄 모두 표시 (라인1 이름 / 라인2 ha·공 / 라인3 ㎥/ha / 라인4 강수)
- [ ] **F6.** 행 사이 캡션 = `"▲ 한라산 국립공원 (농업용 관정 없음)"` 정확 표기, (北)/(南) 0건
- [ ] **F7.** 리 트리맵 — 추자면 제외, 171개 리 모두 부모 슬롯 안에 정확히 배치
- [ ] **F8.** 부모 슬롯 폭 합계 (각 행) = 100% ± 0.01%
- [ ] **F9.** 분석 연도 변경 시 폭 불변, 색만 변화 (snapshot 비교 테스트)
- [ ] **F10.** `tab22_ag_usage_detail.py` 외 파일 git diff 0
- [ ] **F11.** 다른 섹션 (C/D/E/F) 미변경 확인
- [ ] **F12.** ruff/lint 통과

---

## G. 산출물 인덱스

| 파일 | 용도 |
|---|---|
| `docs/spec_treemap_redesign.md` (본 파일) | 통합 명세 (메인) |
| `docs/data/treemap_eup_layout.md` | 읍/면/동 레이아웃 상세 |
| `docs/data/treemap_eup_cells.csv` | 12행 셀 데이터 (코드에서 직접 로드) |
| `docs/data/treemap_ri_layout.md` | 리 단위 레이아웃 상세 |
| `docs/data/treemap_ri_cells.csv` | 171행 리 셀 데이터 |
| `docs/spec_tab22_ag_usage_detail.md` (보존) | 기존 통합 명세, 본 명세가 §B 덮어씀 |

---

## H. 색상 매핑 변수 결정 근거

**선택**: `unit_area_annual_usage` (㎥/ha/year) — 단위면적당 연간 이용량

**비교**:
| 후보 | 단위 | PPT 컬러바와 일치? | 결정 |
|---|---|---|---|
| 평균이용량_월공 | ㎥/월/공 | 컬러바 단위 "㎥/ha" 와 불일치 | ✗ |
| 취수허가량 | ㎥/일 | 자릿수 다름 | ✗ |
| 허가대비비율 | % | 단위 무관 | ✗ |
| **단위면적당 연간이용량** | **㎥/ha** | **PPT 컬러바 라벨 "(단위면적당 연간이용량 m³/ha)" 와 일치** | **✓** |

**산식**:
```
unit_area = 평균이용량_월공_m3 × 공공관정 × 12 / 농지면적_ha
```
- 분자: 월·공 단위 × 공공관정 수 × 12개월 = 연간 총이용량 (㎥/year)
- 분모: 농지면적 (ha)
- 결과: 연간 농지 단위면적당 이용량 (㎥/ha/year)

**범위**: 1100 ~ 2300 (PPT 컬러바 직접 판독)

---

## I. 강수관측소 매핑 (PPT 직접 판독)

12개 행정구역 → 4개 관측소:

| 관측소 | 연강수량 | 매핑 읍/면/동 |
|---|---:|---|
| 고산 | 1,265mm | 한경면, 한림읍, 대정읍, 안덕면 |
| 제주 | 1,413mm | 애월읍, 제주시 동지역, 조천읍 |
| 서귀(포) | 1,953mm | 서귀포시 동지역, 남원읍 |
| 성산 | 2,093mm | 구좌읍, 표선면, 성산읍 |
