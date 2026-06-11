# ==============================================================================
#  파일명: src/dashboard/tabs/_tab12_aws.py
#  6 이용량 분석 탭 - AWS 강수량 + 서브그룹 강수+이용량 결합 차트
#
#  Source 분리: tab12_ag_usage.py 2311줄 -> 그룹별 분리 6단계 (마지막) (2026-05-09).
#    - _select_aws_for_region            : 지역명 -> 인접 AWS 결정
#    - _render_aws_rainfall              : AWS 강수량 그래프
#    - _render_subgroup_rainfall_combined: 서브그룹 강수+이용량 결합 차트
#
#  외부 사용처: tab12_ag_usage.py 내부 전용.
# ==============================================================================
from __future__ import annotations

import calendar

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from plotly.subplots import make_subplots

import config
from src.analysis import effective_rainfall, ag_well_metrics
from src.dashboard import theme
from src.dashboard.tabs._tab12_helpers import (
    _LEVEL_TO_SUBGROUP_COL,
    _SUBGROUP_LINE_PALETTE,
    _cached_asos_data,
    _location_label,
    _nice_y_max,
    _normalize_group_values,
    _stats_filter_for_level,
    _yr_label,
)


def _select_aws_for_region(df_master_f: pd.DataFrame) -> str | None:
    """선택된 지역(관정 집합)에 가장 적합한 AWS 1개 결정.

    매핑 규칙: 관정 → watershed → AWS (config.WATERSHED_AWS_MAP).
    여러 watershed 가 섞여 있으면 빈도 가장 높은 watershed 의 AWS 선택.

    데이터의 watershed 표기는 "대정수역" 처럼 '수역' 접미사가 붙어 있을 수 있어
    config 의 키 ("대정") 와 맞지 않을 수 있다 → '수역' 제거 후에도 매칭 시도.
    """
    if df_master_f.empty or "watershed" not in df_master_f.columns:
        return None
    ws_counts = df_master_f["watershed"].dropna().value_counts()
    if ws_counts.empty:
        return None

    aws_tally: dict[str, int] = {}
    for ws, cnt in ws_counts.items():
        raw = str(ws).strip()
        # 1차: raw 매칭, 2차: '수역' 접미사 제거 후 매칭
        candidates = [raw]
        if raw.endswith("수역"):
            candidates.append(raw[:-2])
        elif not raw.endswith("수역"):
            candidates.append(raw + "수역")
        aws_name = None
        for cand in candidates:
            aws_name = config.WATERSHED_AWS_MAP.get(cand)
            if aws_name:
                break
        if aws_name:
            aws_tally[aws_name] = aws_tally.get(aws_name, 0) + int(cnt)

    if not aws_tally:
        return None
    return max(aws_tally.items(), key=lambda kv: kv[1])[0]


def _render_aws_rainfall(
    aws_name: str | None,
    yr_range: tuple[int, int],
    merged: pd.DataFrame,
    usage_y_max: float | None = None,
    daily_permit_by_year: dict[int, float] | None = None,
) -> None:
    """이중 그래프: AWS 월강수량(막대) + 선택 지역 일평균 이용량(선).

    Build 2.7 (2026-05-02):
      - 좌측 강수량 Y축: 0 ~ 200 mm 고정, **dtick=25 → 8칸**
      - 우측 일평균 이용량 Y축:
          · usage_y_max 지정 시 → 그 값을 max 로 + dtick = max/8 (8칸)
          · 미지정 시 → 데이터 max × 1.05 를 max 로, 동일하게 8칸
        둘 다 8 등분이라 좌우 보조선 위치가 일치 (gridline 정렬).
      - 우측 line: 일평균(㎥/일) — 그달 실제 일수로 나눔
      - 막대 두께 약 1/3 (bargap=0.7), 높이 ↑
      - X축 한글 라벨: 연도 변경시 'YY년 M월', 그 외 'M월'
    """
    if not aws_name:
        st.caption("선택 지역에 매핑되는 AWS 가 없어 강수량을 표시할 수 없습니다.")
        return

    asos_df = _cached_asos_data()
    if asos_df is None or asos_df.empty:
        st.caption("ASOS 강수량 자료를 찾을 수 없습니다.")
        return

    sub = asos_df[asos_df["지점명"] == aws_name].copy()
    if sub.empty:
        st.caption(f"{aws_name} AWS 자료가 없습니다.")
        return

    sub["일시"] = pd.to_datetime(sub["일시"], errors="coerce")
    sub = sub.dropna(subset=["일시"]).copy()
    sub = sub[
        (sub["일시"].dt.year >= yr_range[0])
        & (sub["일시"].dt.year <= yr_range[1])
    ]
    if sub.empty:
        st.caption(f"{aws_name} AWS — 선택 기간 자료가 없습니다.")
        return

    # ── 1) 강수량 월별 합계 (AWS)
    sub["_year"] = sub["일시"].dt.year
    sub["_month"] = sub["일시"].dt.month
    rain = (
        sub.groupby(["_year", "_month"])["일강수량(mm)"]
           .sum().reset_index()
    )
    rain.columns = ["year", "month", "rainfall"]
    rain["period"] = pd.to_datetime(
        rain["year"].astype(str) + "-"
        + rain["month"].astype(str).str.zfill(2) + "-01",
        errors="coerce",
    )
    rain = rain.sort_values("period")

    # ── 2) 이용량 월별 합계 → 일평균(㎥/일) 환산 (그달 실제 일수)
    use = (
        merged.groupby(["year", "month"], dropna=False)["volume_m3"]
              .sum().reset_index()
    )
    use["period"] = pd.to_datetime(
        use["year"].astype(str) + "-"
        + use["month"].astype(str).str.zfill(2) + "-01",
        errors="coerce",
    )
    use["days"] = use.apply(
        lambda r: calendar.monthrange(int(r["year"]), int(r["month"]))[1]
        if pd.notna(r["year"]) and pd.notna(r["month"]) else None,
        axis=1,
    )
    use["daily_avg"] = use["volume_m3"] / use["days"]
    use = use.sort_values("period")

    # ── 3) 한글 X축 tick — 연도 변경 시에만 'YY년 M월'
    all_periods = sorted(set(rain["period"]).union(use["period"]))
    tick_vals = list(all_periods)
    tick_text: list[str] = []
    prev_year = None
    for p in tick_vals:
        yr = p.year
        mo = p.month
        if yr != prev_year:
            tick_text.append(f"{yr % 100}년 {mo}월")
            prev_year = yr
        else:
            tick_text.append(f"{mo}월")

    # 강수량 막대는 AWS 지점 색 무관하게 푸른 계열로 통일 (대시보드 톤 일관성)
    aws_color = "#5B9BD5"
    use_color = theme.COLOR_ACCENT_DARKRED

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=rain["period"], y=rain["rainfall"],
        marker_color=aws_color,
        name=f"{aws_name} 월강수량 (mm)",
        yaxis="y",
        text=[f"{v:.0f}" for v in rain["rainfall"]],
        textposition="outside", textfont=dict(size=13),
    ))
    fig.add_trace(go.Scatter(
        x=use["period"], y=use["daily_avg"],
        mode="lines+markers",
        name="일평균 이용량 (㎥/일)",
        line=dict(color=use_color, width=2.5),
        marker=dict(size=6, color=use_color),
        yaxis="y2",
    ))

    # ── 연도별 「취수허가량 ÷ 30(㎥/일)」 점선 — 단일 관정 호출 시에만 인자 제공.
    #   각 연도마다 1/1 ~ 12/31 구간을 가로 점선으로, 자료가 없는 연도는 NaN 으로
    #   끊어서(connectgaps=False) 「자료 없음 → 점선 없음」을 보장.
    if daily_permit_by_year:
        permit_x: list = []
        permit_y: list = []
        for y in sorted(daily_permit_by_year.keys()):
            v = daily_permit_by_year[y]
            if v is None or pd.isna(v):
                continue
            try:
                yi = int(y)
            except (TypeError, ValueError):
                continue
            if yi < yr_range[0] or yi > yr_range[1]:
                continue
            permit_x.extend([
                pd.Timestamp(year=yi, month=1, day=1),
                pd.Timestamp(year=yi, month=12, day=31),
                None,
            ])
            permit_y.extend([float(v), float(v), None])

        if permit_x:
            fig.add_trace(go.Scatter(
                x=permit_x, y=permit_y,
                mode="lines",
                name="취수허가량 ÷ 30 (㎥/일)",
                line=dict(color=theme.COLOR_TEXT_TERTIARY, width=1.5, dash="dot"),
                yaxis="y2",
                connectgaps=False,
                hovertemplate="허가량/30: %{y:,.0f} ㎥/일<extra></extra>",
            ))

    # ── y축 (강수량) — 0 ~ 200 mm 고정, dtick=25 → 8칸
    yaxis_kwargs = dict(
        title=dict(text="월강수량 (mm)", font=dict(color=aws_color, size=14)),
        tickfont=dict(color=aws_color, size=13),
        range=[0, 200], dtick=25,
    )

    # ── y2축 (이용량 일평균) — 항상 8칸으로 분할되도록 dtick 산출
    #   → 좌우 Y축 보조선이 같은 픽셀 위치에 그려져 그래프가 깔끔.
    if usage_y_max is None:
        # 데이터 max 기반 자동 산출 (5% 여유) — dtick 을 'nice number' 로 round-up
        import math as _math
        data_max = float(use["daily_avg"].max()) if not use.empty else 1000.0
        if not data_max or pd.isna(data_max):
            data_max = 1000.0
        target = data_max * 1.05
        step_raw = target / 8.0
        if step_raw > 0:
            # 1, 2, 5, 10 × 10^n 중 step_raw 보다 큰 가장 가까운 값
            exp = _math.floor(_math.log10(step_raw))
            base = 10 ** exp
            f = step_raw / base
            if f <= 1: nice = 1
            elif f <= 2: nice = 2
            elif f <= 2.5: nice = 2.5
            elif f <= 5: nice = 5
            else: nice = 10
            step = nice * base
        else:
            step = 1
        usage_y_max_eff = step * 8
    else:
        usage_y_max_eff = float(usage_y_max)

    yaxis2_kwargs = dict(
        title=dict(text="일평균 이용량 (㎥/일)",
                   font=dict(color=use_color, size=14)),
        tickfont=dict(color=use_color, size=13),
        overlaying="y", side="right",
        range=[0, usage_y_max_eff],
        dtick=usage_y_max_eff / 8,
    )

    fig.update_layout(
        height=420,
        margin=dict(l=10, r=10, t=10, b=70),
        plot_bgcolor="white",
        bargap=0.7,
        legend=dict(
            font=dict(size=14), orientation="h",
            yanchor="bottom", y=1.0, xanchor="right", x=1.0,
        ),
        yaxis=yaxis_kwargs,
        yaxis2=yaxis2_kwargs,
    )
    # ── X축 좌·우 여백 최소화: 첫/마지막 막대가 plot 영역 가장자리에 가깝게 붙도록
    #   범위를 첫 period 의 약 ½ 막대 앞 ~ 마지막 period 의 약 ½ 막대 뒤로 명시.
    #   (plotly 기본 auto-range 는 5~10% 의 양쪽 padding 을 자동으로 추가함)
    x_pad = pd.Timedelta(days=12)
    x_range = [all_periods[0] - x_pad, all_periods[-1] + x_pad]

    fig.update_xaxes(
        tickvals=tick_vals,
        ticktext=tick_text,
        tickangle=-45,
        tickfont=dict(size=13),
        title=None,
        range=x_range,
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_subgroup_rainfall_combined(
    level: str,
    loc_sel: dict,
    aws_name: str | None,
    yr_range: tuple[int, int],
    merged: pd.DataFrame,
) -> None:
    """집계단위별 하위그룹 「월별 강수량 · 이용량 비교」 — 1개 통합 차트.

    좌Y축: AWS 월강수량 막대 (0~500mm 고정).
    우Y축: 하위그룹별 일평균 이용량 라인 (그룹 = 다른 색).

    레벨별 분해 규칙:
      - 시:       선택된 시 안의 모든 읍/면/동 (동→'동지역' 통합)
      - 읍면동:   선택된 읍 안의 모든 리/동
      - 리:       선택된 리 안의 모든 관정 (12공 초과 시 상위 12공)
      - 제주도:   전체 시 (제주시·서귀포시)
      - 유역:     전체 watershed
    """
    if merged.empty or level not in _LEVEL_TO_SUBGROUP_COL:
        return
    group_col = _LEVEL_TO_SUBGROUP_COL[level]
    if group_col not in merged.columns:
        return

    # 동지역 정규화 (well_eup / well_ri 케이스)
    work = _normalize_group_values(merged, group_col)

    # 그룹 목록 — 빈/None 제외, 이용량 합 내림차순
    grp_totals = (
        work.groupby(group_col, dropna=False)["volume_m3"]
            .sum().reset_index()
    )
    grp_totals = grp_totals[grp_totals[group_col].notna()]
    grp_totals = grp_totals[grp_totals[group_col].astype(str).str.strip() != ""]
    grp_totals = grp_totals.sort_values("volume_m3", ascending=False)
    if grp_totals.empty:
        return

    truncated = False
    if level == "리" and len(grp_totals) > 12:
        grp_totals = grp_totals.head(12)
        truncated = True

    groups = grp_totals[group_col].tolist()

    # ── 제목 빌드
    si = loc_sel.get("well_si") or ""
    eup = loc_sel.get("well_eup") or ""
    ri = loc_sel.get("well_ri") or ""
    yr_label = _yr_label(yr_range)
    aws_label = aws_name or "(매핑 AWS 없음)"

    if level == "시":
        title_prefix = si if si else "제주도 전역"
        title_suffix = "읍면동"
    elif level == "읍면동":
        title_prefix = " ".join(p for p in (si, eup) if p) or "제주도 전역"
        title_suffix = "리별"
    elif level == "리":
        title_prefix = " ".join(p for p in (si, eup, ri) if p) or "제주도 전역"
        title_suffix = "관정별"
    elif level in ("제주도 전역", "도전역"):
        title_prefix, title_suffix = "제주도 전역", "시별"
    elif level == "유역":
        title_prefix, title_suffix = "제주도 전역", "유역별"
    else:
        title_prefix, title_suffix = "", level

    extra_note = ' <span style="font-size:15px;color:#7a7a76;">(상위 12공)</span>' if truncated else ""
    st.markdown(
        f'<div class="subsection-title" style="color:var(--color-text-info);'
        f'margin-top:14px;">{title_prefix} {title_suffix} 월별 강수량 · 이용량 비교 '
        f'(적용 AWS: <span style="color:var(--color-accent-darkred);">{aws_label}</span>) '
        f'({yr_label}){extra_note}</div>',
        unsafe_allow_html=True,
    )

    # ── 강수량 (AWS) 데이터
    if not aws_name:
        st.caption("선택 지역에 매핑되는 AWS 가 없어 강수량을 표시할 수 없습니다.")
        return
    asos_df = _cached_asos_data()
    if asos_df is None or asos_df.empty:
        st.caption("ASOS 강수량 자료를 찾을 수 없습니다.")
        return
    ras = asos_df[asos_df["지점명"] == aws_name].copy()
    ras["일시"] = pd.to_datetime(ras["일시"], errors="coerce")
    ras = ras.dropna(subset=["일시"])
    ras = ras[
        (ras["일시"].dt.year >= yr_range[0])
        & (ras["일시"].dt.year <= yr_range[1])
    ]
    if ras.empty:
        st.caption(f"{aws_name} AWS — 선택 기간 자료가 없습니다.")
        return
    ras["_year"] = ras["일시"].dt.year
    ras["_month"] = ras["일시"].dt.month
    rain = (
        ras.groupby(["_year", "_month"])["일강수량(mm)"]
           .sum().reset_index()
    )
    rain.columns = ["year", "month", "rainfall"]
    rain["period"] = pd.to_datetime(
        rain["year"].astype(str) + "-"
        + rain["month"].astype(str).str.zfill(2) + "-01",
        errors="coerce",
    )
    rain = rain.sort_values("period")

    # ── 그룹별 일평균 이용량 시계열 빌드
    label_map: dict = {}
    eup_map: dict = {}
    if level == "리":
        if "well_id" in work.columns:
            label_map = (
                work.drop_duplicates("permit_no")
                    .set_index("permit_no")["well_id"].to_dict()
            )
        if "well_eup" in work.columns:
            eup_map = (
                work.drop_duplicates("permit_no")
                    .set_index("permit_no")["well_eup"].to_dict()
            )

    use_traces: list[tuple[str, str, pd.DataFrame]] = []
    use_max = 0.0
    for i, g in enumerate(groups):
        sub_g = work[work[group_col] == g]
        use_g = (
            sub_g.groupby(["year", "month"], dropna=False)["volume_m3"]
                 .sum().reset_index()
        )
        if use_g.empty:
            continue
        use_g["days"] = use_g.apply(
            lambda r: calendar.monthrange(int(r["year"]), int(r["month"]))[1]
            if pd.notna(r["year"]) and pd.notna(r["month"]) else None,
            axis=1,
        )
        use_g["daily_avg"] = use_g["volume_m3"] / use_g["days"]
        use_g["period"] = pd.to_datetime(
            use_g["year"].astype(str) + "-"
            + use_g["month"].astype(str).str.zfill(2) + "-01",
            errors="coerce",
        )
        use_g = use_g.sort_values("period")

        if use_g["daily_avg"].notna().any():
            use_max = max(use_max, float(use_g["daily_avg"].max()))

        if level == "리":
            display_label = label_map.get(g, str(g))
        else:
            display_label = str(g)
        color = _SUBGROUP_LINE_PALETTE[i % len(_SUBGROUP_LINE_PALETTE)]
        use_traces.append((display_label, color, use_g))

    if not use_traces:
        st.caption("표시할 하위 그룹 이용량 자료가 없습니다.")
        return

    # ── X축 tick (한글) — 모든 기간 union
    all_periods_set: set = set(rain["period"])
    for _, _c, ug in use_traces:
        all_periods_set.update(ug["period"])
    all_periods = sorted(p for p in all_periods_set if pd.notna(p))
    tick_text: list[str] = []
    prev_year: int | None = None
    for p in all_periods:
        yr, mo = p.year, p.month
        if yr != prev_year:
            tick_text.append(f"{yr % 100}년 {mo}월")
            prev_year = yr
        else:
            tick_text.append(f"{mo}월")

    aws_color = "#5B9BD5"

    # ── Plotly 차트 빌드
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=rain["period"], y=rain["rainfall"],
        marker_color=aws_color,
        name=f"{aws_name} 월강수량 (mm)",
        yaxis="y",
    ))
    for label, color, ug in use_traces:
        fig.add_trace(go.Scatter(
            x=ug["period"], y=ug["daily_avg"],
            mode="lines+markers",
            name=label,
            line=dict(color=color, width=1.6),
            marker=dict(size=4, color=color),
            yaxis="y2",
            hovertemplate=f"<b>{label}</b><br>%{{x|%Y-%m}}: %{{y:,.0f}} ㎥/일<extra></extra>",
        ))

    # ── y축 (강수량) — 0 ~ 500 mm 고정, dtick=50 → 10 ticks
    yaxis_kwargs = dict(
        title=dict(text="월강수량 (mm)", font=dict(color=aws_color, size=14)),
        tickfont=dict(color=aws_color, size=13),
        range=[0, 500], dtick=50,
    )

    # ── y2축 (이용량) — 데이터 max 기반 nice scale, 10 ticks 정렬
    nice_max = _nice_y_max(use_max, n_ticks=10) if use_max > 0 else 100.0
    yaxis2_kwargs = dict(
        title=dict(text="일평균 이용량 (㎥/일)",
                   font=dict(color=theme.COLOR_TEXT_PRIMARY, size=14)),
        tickfont=dict(color=theme.COLOR_TEXT_PRIMARY, size=13),
        overlaying="y", side="right",
        range=[0, nice_max],
        dtick=nice_max / 10,
    )

    fig.update_layout(
        height=620,
        margin=dict(l=10, r=10, t=10, b=80),
        plot_bgcolor="white",
        bargap=0.7,
        legend=dict(
            font=dict(size=14), orientation="h",
            yanchor="bottom", y=1.0, xanchor="left", x=0.0,
        ),
        yaxis=yaxis_kwargs,
        yaxis2=yaxis2_kwargs,
        hovermode="x unified",
    )

    x_pad = pd.Timedelta(days=12)
    x_range = [all_periods[0] - x_pad, all_periods[-1] + x_pad]
    fig.update_xaxes(
        tickvals=all_periods,
        ticktext=tick_text,
        tickangle=-45,
        tickfont=dict(size=13),
        title=None,
        range=x_range,
    )
    st.plotly_chart(fig, use_container_width=True)


