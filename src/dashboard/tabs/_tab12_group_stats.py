# ==============================================================================
#  파일명: src/dashboard/tabs/_tab12_group_stats.py
#  6 이용량 분석 탭 - 집계 단위별 통계 표 + 박스 플롯
#
#  Source 분리: tab12_ag_usage.py 2311줄 -> 그룹별 분리 5단계 (2026-05-09).
#    - _render_group_stats       : 집계 단위별 그룹 통계 (메인)
#    - _build_stats_table_html   : 통계 표 HTML 빌더
#    - _render_monthly_box       : 그룹별 월별 이용량 박스 플롯
#    - _render_month_box         : 그룹별 한 달의 박스 플롯
#
#  외부 사용처: tab12_ag_usage.py 내부 전용.
# ==============================================================================
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import config
from src.analysis import ag_well_metrics
from src.dashboard import theme
from src.dashboard.tabs._tab12_helpers import (
    _LEVEL_TO_GROUP,
    _fmt_int,
    _normalize_group_values,
    _stats_filter_for_level,
    _stats_title_scope,
    _yr_label,
)


# ------------------------------------------------------------------------------
def _render_group_stats(
    merged: pd.DataFrame,
    level: str,
    n_days: int,
    n_months: int,
    yr_range: tuple[int, int],
) -> None:
    """집계 단위에 따라 하위 그룹별 통계 표를 렌더.

    도전체 → 제주시 / 서귀포시 단위 (authority)
    시      → 선택된 시의 읍면 단위 (well_eup)
    읍면동  → 선택된 읍면의 리 단위 (well_ri)
    리      → 선택된 리의 관정 단위 (well_id)
    유역    → 유역 단위 (watershed)

    각 그룹별 9 컬럼:
      관정 수 / 총 이용량 / 월평균 / 일평균 / 관정당 일평균
      + 최대사용월 / 최대월 사용량 / 최대월 일평균 / 최대월 관정당 일평균

    모든 수치는 정수로 반올림해서 표시.
    """
    grp_info = _LEVEL_TO_GROUP.get(level)
    if grp_info is None:
        return
    group_col, group_label = grp_info

    if group_col not in merged.columns:
        st.caption(f"'{group_col}' 컬럼이 없어 표를 생성할 수 없습니다.")
        return

    # 동지역 처리 — well_eup 의 '○○동' → '동지역', well_ri NaN 은 동으로 fallback
    sub = _normalize_group_values(merged, group_col)
    sub = sub[sub[group_col].notna()]
    sub[group_col] = sub[group_col].astype(str).str.strip()
    sub = sub[sub[group_col] != ""]

    if sub.empty:
        st.caption("표시할 자료가 없습니다.")
        return

    # ── 그룹별 기본 집계 (관정수 / 총 이용량)
    # 사용자 요청 2026-05-19: n_wells 분모를 "분석 기간 내 이용량>0 관정"
    # 으로 한정. 분자(volume sum)는 그대로 — 0 이용량 관정의 0 기여는 무영향.
    _active_set = ag_well_metrics.active_user_permits(sub)
    _n_per = (sub[sub["permit_no"].astype(str).isin(_active_set)]
              .groupby(group_col, dropna=False)["permit_no"].nunique()
              .rename("n_wells"))
    _vol_per = (sub.groupby(group_col, dropna=False)["volume_m3"]
                .sum().rename("volume"))
    agg = (pd.concat([_n_per, _vol_per], axis=1)
           .fillna({"n_wells": 0})
           .reset_index())
    agg["n_wells"] = agg["n_wells"].astype(int)

    # ── 그룹별 (year, month) 합계 → 그룹별 최대/최소 사용월 추출
    monthly = (
        sub.groupby([group_col, "year", "month"], dropna=False)["volume_m3"]
           .sum().reset_index()
    )
    monthly = monthly[monthly["volume_m3"] > 0]
    if not monthly.empty:
        max_idx = monthly.groupby(group_col)["volume_m3"].idxmax()
        min_idx = monthly.groupby(group_col)["volume_m3"].idxmin()
        max_df = monthly.loc[max_idx, [group_col, "year", "month", "volume_m3"]].rename(
            columns={"year": "max_year", "month": "max_month", "volume_m3": "max_volume"}
        )
        min_df = monthly.loc[min_idx, [group_col, "year", "month", "volume_m3"]].rename(
            columns={"year": "min_year", "month": "min_month", "volume_m3": "min_volume"}
        )
    else:
        max_df = pd.DataFrame(columns=[group_col, "max_year", "max_month", "max_volume"])
        min_df = pd.DataFrame(columns=[group_col, "min_year", "min_month", "min_volume"])

    # authority 영문 코드 → 한국어 (3개 DataFrame 모두)
    if group_col == "authority":
        agg[group_col] = agg[group_col].map(ag_well_metrics.AUTHORITY_KOR).fillna(agg[group_col])
        if not max_df.empty:
            max_df[group_col] = max_df[group_col].map(ag_well_metrics.AUTHORITY_KOR).fillna(max_df[group_col])
        if not min_df.empty:
            min_df[group_col] = min_df[group_col].map(ag_well_metrics.AUTHORITY_KOR).fillna(min_df[group_col])

    agg = agg.merge(max_df, on=group_col, how="left")
    agg = agg.merge(min_df, on=group_col, how="left")

    agg = agg[agg["volume"] > 0]
    if agg.empty:
        st.caption("표시할 자료가 없습니다.")
        return

    # ── 분석기간 평균
    agg["월평균"] = agg["volume"] / n_months if n_months else 0
    agg["일평균"] = agg["volume"] / n_days if n_days else 0
    agg["관정당일평균"] = agg["일평균"] / agg["n_wells"].replace(0, pd.NA)

    # ── 최대/최소 사용월 파생값 (벡터화 — apply(axis=1) 4회 → 함수 호출 2회)
    #   기존 calendar.monthrange + f-string 라벨을 pd.to_datetime 기반 벡터로 대체.
    #   대량 행(수만 단위)에서 Python 루프 비용 제거.
    def _vectorized_period(
        yr_col: pd.Series, mo_col: pd.Series,
    ) -> tuple[pd.Series, pd.Series]:
        """년·월 컬럼 → (days_in_month float64, 'YYYY-MM' 라벨) 벡터화.

        days 를 Int64(nullable int) 가 아니라 float64(NaN) 로 반환하는 이유:
        - 합계 행 추가(agg.loc[len(agg)] = dict) 가 내부적으로 concat 사용
        - Int64 컬럼에 NA 가 들어가면 pandas 2.2+ 에서 'all-NA entries' 라는
          FutureWarning 발생 (터미널 7회 반복)
        - float64 + NaN 은 pandas concat 이 자유롭게 처리 → 경고 없음
        - 화면 표시는 _fmt_int() 가 float→int 변환 후 콤마 포맷이라 UI 동일
        """
        yr = pd.to_numeric(yr_col, errors="coerce")
        mo = pd.to_numeric(mo_col, errors="coerce")
        valid = yr.notna() & mo.notna()
        days = pd.Series(float("nan"), index=yr_col.index, dtype="float64")
        label = pd.Series("-", index=yr_col.index, dtype="object")
        if valid.any():
            yi = yr[valid].astype(int)
            mi = mo[valid].astype(int)
            ymd = yi.astype(str) + "-" + mi.astype(str).str.zfill(2)
            dts = pd.to_datetime(ymd + "-01")
            days.loc[valid] = dts.dt.days_in_month.values.astype(float)
            label.loc[valid] = ymd.values
        return days, label

    agg["max_days"], agg["max_label"] = _vectorized_period(
        agg["max_year"], agg["max_month"],
    )
    agg["max_daily"] = agg["max_volume"] / agg["max_days"].replace(0, pd.NA)
    agg["max_per_well_daily"] = agg["max_daily"] / agg["n_wells"].replace(0, pd.NA)

    agg["min_days"], agg["min_label"] = _vectorized_period(
        agg["min_year"], agg["min_month"],
    )
    agg["min_daily"] = agg["min_volume"] / agg["min_days"].replace(0, pd.NA)
    agg["min_per_well_daily"] = agg["min_daily"] / agg["n_wells"].replace(0, pd.NA)

    agg = agg.sort_values("volume", ascending=False).reset_index(drop=True)

    # ── 합계 행
    #   agg.loc[len(agg)] = dict 는 pandas 내부적으로 concat 을 호출. 합계
    #   행에는 의미상 NA 인 컬럼(max_year/max_month/max_volume 등) 이 다수
    #   존재해 그 행 자체가 'all-NA' 로 분류 → pandas 2.2+ FutureWarning
    #   ('concatenation with empty or all-NA entries') 발생.
    #   - 동작은 의도와 정확히 일치 (미래 버전의 dtype 추론 변경 예고)
    #   - 모든 컬럼을 dict 에 명시해도 NA 가 있는 한 같은 경고가 발생
    #   → context manager 로 이 한 줄에서만 그 메시지 억제. pandas 업그레이드
    #     시점에 다시 검토.
    import warnings
    # 사용자 요청 2026-05-19: 합계 행도 사용 관정 기준. agg.n_wells.sum() 은
    # 그룹간 중복 가능 (예: 1관정이 여러 리에 row 가 있는 경우는 없지만
    # authority/eup/ri 계층 변경 시 안전 ↑). _active_set 크기로 직접 사용.
    total_wells = int(
        sub[sub["permit_no"].astype(str).isin(_active_set)]["permit_no"].nunique()
    )
    total_vol = float(agg["volume"].sum())
    total_row: dict = {col: pd.NA for col in agg.columns}
    total_row.update({
        group_col: "합계",
        "n_wells": total_wells,
        "volume": total_vol,
        "월평균": total_vol / n_months if n_months else 0,
        "일평균": total_vol / n_days if n_days else 0,
        "관정당일평균": (total_vol / n_days / total_wells) if (n_days and total_wells) else 0,
        "max_label": "-",
        "min_label": "-",
    })
    with warnings.catch_warnings():
        warnings.filterwarnings(
            "ignore",
            category=FutureWarning,
            message=r".*concatenation with empty or all-NA entries.*",
        )
        agg.loc[len(agg)] = total_row

    # ── HTML 테이블 렌더 (multi-level header + 콤마 + 우측 정렬)
    st.markdown(
        _build_stats_table_html(agg, group_col, group_label, yr_range),
        unsafe_allow_html=True,
    )


def _build_stats_table_html(
    agg: pd.DataFrame,
    group_col: str,
    group_label: str,
    yr_range: tuple[int, int],
) -> str:
    """집계 통계 표 — 2단 헤더 (평균 · 최대 · 최소) HTML 테이블.

    스타일:
      - 첫 행 카테고리: 평균/최대/최소 (분석기간 포함)
      - 둘째 행: 단축 컬럼명
      - 그룹 라벨 컬럼·관정 수: 중앙정렬
      - 수치 컬럼: 콤마 + 우측 정렬
    """
    yr_label = _yr_label(yr_range)

    css = """
    <style>
    .ag-stats {
        width: 100%; border-collapse: collapse;
        font-size: 15px; color: var(--color-text-primary);
        border: 0.5px solid rgba(26,26,24,0.18);
        margin: 4px 0 8px;
    }
    .ag-stats th, .ag-stats td {
        padding: 5px 8px;
        border: 0.5px solid rgba(26,26,24,0.10);
        white-space: nowrap;
    }
    .ag-stats thead tr.cat-row th {
        background: var(--color-text-info); color: var(--color-bg-primary);
        font-weight: 600; font-size: 16px;
        text-align: center;
    }
    .ag-stats thead tr.col-row th {
        background: var(--color-bg-info); color: var(--color-text-info);
        font-weight: 600; text-align: center;
    }
    .ag-stats td.num {
        text-align: right;
        font-variant-numeric: tabular-nums;
    }
    .ag-stats td.cnt {
        /* 관정 수 — 중앙정렬 */
        text-align: center;
        font-variant-numeric: tabular-nums;
    }
    .ag-stats td.lbl {
        text-align: center;
    }
    .ag-stats td.grp {
        /* 리/읍면 등 그룹 이름 — 중앙정렬 */
        text-align: center;
        font-weight: 500;
    }
    .ag-stats tbody tr:nth-child(even) { background: #fafaf8; }
    .ag-stats tbody tr.total-row {
        background: #d7e6f5 !important;
        font-weight: 700; color: var(--color-text-info);
    }
    .ag-stats tbody tr.total-row td.num,
    .ag-stats tbody tr.total-row td.cnt { color: var(--color-text-info); }
    /* 카테고리 경계선 강조 */
    .ag-stats th.sep, .ag-stats td.sep {
        border-left: 2px solid #185fa5 !important;
    }
    </style>
    """

    body_rows = []
    for _, r in agg.iterrows():
        is_total = (str(r.get(group_col, "")) == "합계")
        cls = "total-row" if is_total else ""
        body_rows.append(f'<tr class="{cls}">')
        # 그룹 라벨 — 중앙정렬
        body_rows.append(f'<td class="grp">{r.get(group_col, "")}</td>')
        # 관정 수 — 중앙정렬
        body_rows.append(f'<td class="cnt">{_fmt_int(r.get("n_wells"))}</td>')
        # ── 평균 4컬럼 — 우측정렬
        body_rows.append(f'<td class="num sep">{_fmt_int(r.get("volume"))}</td>')
        body_rows.append(f'<td class="num">{_fmt_int(r.get("월평균"))}</td>')
        body_rows.append(f'<td class="num">{_fmt_int(r.get("일평균"))}</td>')
        body_rows.append(f'<td class="num">{_fmt_int(r.get("관정당일평균"))}</td>')
        # ── 최대 4컬럼
        body_rows.append(f'<td class="lbl sep">{r.get("max_label", "-")}</td>')
        body_rows.append(f'<td class="num">{_fmt_int(r.get("max_volume"))}</td>')
        body_rows.append(f'<td class="num">{_fmt_int(r.get("max_daily"))}</td>')
        body_rows.append(f'<td class="num">{_fmt_int(r.get("max_per_well_daily"))}</td>')
        # ── 최소 4컬럼
        body_rows.append(f'<td class="lbl sep">{r.get("min_label", "-")}</td>')
        body_rows.append(f'<td class="num">{_fmt_int(r.get("min_volume"))}</td>')
        body_rows.append(f'<td class="num">{_fmt_int(r.get("min_daily"))}</td>')
        body_rows.append(f'<td class="num">{_fmt_int(r.get("min_per_well_daily"))}</td>')
        body_rows.append("</tr>")

    table = (
        css
        + '<table class="ag-stats">'
        + "<thead>"
        # 1행: 카테고리 (rowspan=2 셀: 그룹라벨, 관정 수) + 기간 포함
        + '<tr class="cat-row">'
        + f'<th rowspan="2" style="vertical-align:middle;background:var(--color-accent-blue-3);">{group_label}</th>'
        + '<th rowspan="2" style="vertical-align:middle;background:var(--color-accent-blue-3);">관정 수</th>'
        + f'<th colspan="4" class="sep">평균 ({yr_label})</th>'
        + f'<th colspan="4" class="sep">최대 사용월 ({yr_label})</th>'
        + f'<th colspan="4" class="sep">최소 사용월 ({yr_label})</th>'
        + "</tr>"
        # 2행: 단축 컬럼명
        + '<tr class="col-row">'
        + '<th class="sep">총량 (㎥)</th>'
        + '<th>월평균 (㎥)</th>'
        + '<th>일평균 (㎥)</th>'
        + '<th>관정당 (㎥)</th>'
        + '<th class="sep">월</th>'
        + '<th>사용량 (㎥)</th>'
        + '<th>일평균 (㎥)</th>'
        + '<th>관정당 (㎥)</th>'
        + '<th class="sep">월</th>'
        + '<th>사용량 (㎥)</th>'
        + '<th>일평균 (㎥)</th>'
        + '<th>관정당 (㎥)</th>'
        + "</tr>"
        + "</thead>"
        + "<tbody>" + "".join(body_rows) + "</tbody>"
        + "</table>"
    )
    return table


# ------------------------------------------------------------------------------
def _render_monthly_box(merged: pd.DataFrame, level: str) -> None:
    """그룹별 월별 이용량 분포 박스 플롯.

    각 박스: (그룹) × (분석기간의 모든 월). y = volume_m3.
    """
    grp_info = _LEVEL_TO_GROUP.get(level)
    if grp_info is None:
        return
    group_col, group_label = grp_info

    if group_col not in merged.columns:
        return

    # 동지역 처리 — well_eup 그룹은 '동지역', well_ri 는 동으로 fallback
    sub = _normalize_group_values(merged, group_col)
    sub = sub[sub["volume_m3"].notna() & (sub["volume_m3"] > 0)]
    sub = sub[sub[group_col].notna()]
    sub[group_col] = sub[group_col].astype(str).str.strip()
    sub = sub[sub[group_col] != ""]
    if group_col == "authority":
        sub[group_col] = (
            sub[group_col].map(ag_well_metrics.AUTHORITY_KOR).fillna(sub[group_col])
        )
    if sub.empty:
        st.caption("박스 플롯에 표시할 자료가 없습니다.")
        return

    # 그룹 정렬: 이용량 합 내림차순 (상위 30 만 표시 — 그룹 너무 많으면 가독성 ↓)
    order = (
        sub.groupby(group_col)["volume_m3"].sum()
           .sort_values(ascending=False)
           .head(30).index.tolist()
    )
    sub = sub[sub[group_col].isin(order)]

    fig = go.Figure()
    for grp_val in order:
        g = sub[sub[group_col] == grp_val]
        fig.add_trace(go.Box(
            y=g["volume_m3"],
            name=str(grp_val),
            boxpoints="outliers",
            marker=dict(size=4),
            line=dict(width=1.2),
        ))
    fig.update_layout(
        height=320,
        margin=dict(l=10, r=10, t=20, b=80),
        plot_bgcolor="white",
        showlegend=False,
    )
    fig.update_xaxes(title=group_label, tickfont=dict(size=13), tickangle=-30)
    fig.update_yaxes(title="월별 이용량 (㎥)", tickfont=dict(size=13))
    st.plotly_chart(fig, use_container_width=True)


# ------------------------------------------------------------------------------
def _render_month_box(df: pd.DataFrame) -> None:
    """1월~12월 월별 이용량 분포 박스 플롯.

    각 박스: 그 월(예: 7월)에 대한 (관정 × 연도) 합집합의 volume 분포.
    분석기간 동안 계절성 패턴을 한눈에 확인.
    """
    if df.empty:
        return
    sub = df[df["volume_m3"].notna() & (df["volume_m3"] > 0)].copy()
    sub = sub[sub["month"].between(1, 12)]
    if sub.empty:
        st.caption("월별 분포에 표시할 자료가 없습니다.")
        return

    fig = go.Figure()
    for m in range(1, 13):
        gm = sub[sub["month"] == m]
        if gm.empty:
            continue
        fig.add_trace(go.Box(
            y=gm["volume_m3"],
            name=f"{m}월",
            boxpoints="outliers",
            marker=dict(size=4, color=theme.COLOR_ACCENT_BLUE_2),
            line=dict(width=1.2, color=theme.COLOR_ACCENT_BLUE_2),
            fillcolor="#9DC3E6",
        ))
    # 좌우 모두 같은 이용량(㎥) 스케일 표시 — 아래 dual-axis 그래프와 plot 영역 폭 정렬
    fig.update_layout(
        height=320,
        margin=dict(l=10, r=10, t=10, b=40),
        plot_bgcolor="white",
        showlegend=False,
        yaxis=dict(
            title=dict(text="이용량 (㎥)", font=dict(size=14)),
            tickfont=dict(size=13),
            side="left", rangemode="tozero",
        ),
        yaxis2=dict(
            title=dict(text="이용량 (㎥)", font=dict(size=14)),
            tickfont=dict(size=13),
            side="right", overlaying="y", matches="y",
            showgrid=False,
        ),
    )
    fig.update_xaxes(title=None, tickfont=dict(size=13))
    st.plotly_chart(fig, use_container_width=True)


