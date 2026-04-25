# ==============================================================================
#  파일명: src/dashboard/tabs/tab0_overview.py
#  탭: 대시보드 요약
# ------------------------------------------------------------------------------
#  Build: 0.9
# ------------------------------------------------------------------------------
#  【이 탭의 역할】
#  현재 기준일에 대한 M-2·M-1·M 요약을 한눈에 보여주는 관리자용 대시보드.
#  강수량·유효강수일수·지하수위를 각각 카드/그래프로 집약.
# ==============================================================================

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

import config
from src.analysis import effective_rainfall
from src.dashboard import theme


PERIOD_KEYS = ["M-2", "M-1", "M"]


def _rgba_hex(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def render(asos_df: pd.DataFrame, ws_data_all: dict, periods: dict):
    """
    대시보드 요약 탭 렌더링.
    - AWS 지점별 강수량: 3개 기간(M-2, M-1, M) 각 행으로 집약
    - 유역별 지하수위(EL) 변동: 유역당 M-2·M-1·M 3개 막대 그룹
    """
    n_gw = config.GWLEVEL_BASELINE_YEARS

    # --------------------------------------------------------------------------
    # Section 1: AWS 지점별 강수량 (지점별 카드 × 3개 기간 행)
    # --------------------------------------------------------------------------
    st.markdown("#### 🌧️ AWS 지점별 강수량 (M-2 · M-1 · M)")

    if asos_df.empty:
        st.info("ASOS 데이터를 먼저 수집하세요. (⚙️ 데이터 관리 탭)")
    else:
        monthly = effective_rainfall.aggregate_monthly(asos_df)
        half = effective_rainfall.aggregate_half_monthly(asos_df)

        cols = st.columns(4)
        for i, station in enumerate(config.STATIONS_ASOS):
            with cols[i]:
                st_col = station["color"]
                bg_tint   = _rgba_hex(st_col, 0.08)
                bord_tint = _rgba_hex(st_col, 0.25)
                rows_html = ""
                for key in PERIOD_KEYS:
                    p = periods[key]
                    actual = effective_rainfall.get_period_value(
                        monthly, half, p, station["name"], "월강수량(mm)"
                    )
                    avg, used_years = effective_rainfall.get_baseline_average(
                        monthly, half, p, station["name"], "월강수량(mm)"
                    )
                    if used_years:
                        bl_short = f"{str(used_years[0])[2:]}~{str(used_years[-1])[2:]}"
                    else:
                        bl = list(range(p["year"] - config.RAINFALL_BASELINE_YEARS, p["year"]))
                        bl_short = f"{str(bl[0])[2:]}~{str(bl[-1])[2:]}"

                    if actual is not None and avg is not None:
                        diff = actual - avg
                        d_sign = "+" if diff >= 0 else "- "
                        d_abs  = abs(diff)
                        d_color = "#1d9e75" if diff >= 0 else "#e24b4a"
                        diff_html = (
                            f'<span style="font-size:13px;color:{d_color};font-weight:600;">'
                            f'{d_sign}{d_abs:.1f}mm</span>'
                        )
                    else:
                        diff_html = '<span style="font-size:11px;color:#999;">-</span>'

                    if actual is None:
                        # 기간 자료 자체가 없음 — 어느 달에 자료가 없는지 명확히 표기
                        rows_html += (
                            f'<div style="padding:7px 0;border-top:0.5px dashed {bord_tint};">'
                            f'<div style="font-size:14px;color:#1a1a18;font-weight:600;">'
                            f'{p["label"]} <span style="font-size:11px;color:#5f5e5a;font-weight:400;">({key})</span></div>'
                            f'<div style="font-size:13px;font-style:italic;color:#e24b4a;margin-top:3px;">'
                            f'※ {p["label"]} 자료 없음</div>'
                            f'</div>'
                        )
                        continue

                    actual_str = f"{actual:.1f} mm"
                    if avg is not None:
                        avg_html = (
                            f'<span style="font-size:13px;color:#1a1a18;font-weight:600;">'
                            f'{avg:.1f}mm</span>'
                            f'<span style="font-size:11px;color:#5f5e5a;">'
                            f' ({bl_short}년 {p["month"]}월 평균)</span>'
                        )
                    else:
                        avg_html = (
                            f'<span style="font-size:11px;color:#5f5e5a;">'
                            f'- ({bl_short}년 {p["month"]}월 평균)</span>'
                        )

                    rows_html += (
                        f'<div style="padding:7px 0;border-top:0.5px dashed {bord_tint};">'
                        f'<div style="font-size:14px;color:#1a1a18;font-weight:600;">'
                        f'{p["label"]} <span style="font-size:11px;color:#5f5e5a;font-weight:400;">({key})</span></div>'
                        f'<div style="font-size:15px;font-weight:700;color:{st_col};margin-top:2px;">'
                        f'{actual_str}</div>'
                        f'<div style="margin-top:2px;">'
                        f'{avg_html} <span style="font-size:11px;color:#5f5e5a;">|</span> {diff_html}</div>'
                        f'</div>'
                    )

                card_html = (
                    f'<div style="background:{bg_tint};border-radius:8px;'
                    f'padding:0.55rem 0.9rem 0.7rem;border-left:3px solid {st_col};'
                    f'margin-bottom:8px;">'
                    f'<div style="font-size:16px;font-weight:700;color:{st_col};padding:2px 0 4px;">'
                    f'{station["name"]} ({station["id"]})</div>'
                    f'{rows_html}'
                    f'</div>'
                )
                st.markdown(card_html, unsafe_allow_html=True)

        st.markdown(
            '<div style="font-size:10px;color:#888;margin:2px 0 0;text-align:right;">'
            '출처: 기상청 기상자료개방포털 API (ASOS 일자료)</div>',
            unsafe_allow_html=True
        )

    st.markdown("")

    # --------------------------------------------------------------------------
    # Section 2: 유역별 지하수위(EL) 변동
    #  - 유역당 M-2·M-1·M 3개 막대 (그룹드 바)
    # --------------------------------------------------------------------------
    month_labels = []         # "25년 11월", "25년 12월", "26년 1월"
    month_labels_full = []    # "2025년 11월" 형식
    for key in PERIOD_KEYS:
        p = periods[key]
        month_labels.append(f"{str(p['year'])[2:]}년 {p['month']}월")
        month_labels_full.append(p["label"])

    section_title = (
        f"유역별 지하수위(EL) 변동 - "
        f"최근 3개월({', '.join(month_labels)})과 "
        f"과거 {n_gw}년간 동일 월의 평균값과 현황"
    )
    yaxis_title = f"지하수위(EL) 변동(현재 - 과거{n_gw}년 평균(m))"
    st.markdown(f"#### 💧 {section_title}")

    if not ws_data_all:
        st.info("지하수위 데이터를 먼저 처리하세요. (⚙️ 데이터 관리 탭)")
        return

    # 유역별·기간별 편차 계산
    # diff_table[ws_name][period_key] = {"실측","평균","편차"} or None
    diff_table = {}
    for w_info in config.WATERSHEDS:
        ws_name = w_info["name"]
        df_ws = ws_data_all.get(ws_name)
        if df_ws is None or df_ws.empty:
            continue
        per_period = {}
        for key in PERIOD_KEYS:
            p = periods[key]
            ym_str = f"{p['year']}-{p['month']:02d}"
            bl_years = list(range(p["year"] - n_gw, p["year"]))

            actual_row = df_ws[df_ws["연월"] == ym_str]
            if actual_row.empty:
                per_period[key] = None
                continue
            actual = float(actual_row["EL_평균"].iloc[0])

            base_vals = []
            for y in bl_years:
                ym_b = f"{y}-{p['month']:02d}"
                base_row = df_ws[df_ws["연월"] == ym_b]
                if not base_row.empty:
                    v = float(base_row["EL_평균"].iloc[0])
                    if pd.notna(v):
                        base_vals.append(v)

            if not base_vals:
                per_period[key] = None
                continue
            avg = sum(base_vals) / len(base_vals)
            per_period[key] = {
                "실측": round(actual, 2),
                "평균": round(avg, 2),
                "편차": round(actual - avg, 2),
            }
        # 적어도 한 기간이라도 값이 있으면 포함
        if any(v is not None for v in per_period.values()):
            diff_table[ws_name] = per_period

    if not diff_table:
        st.info("유역별 실측 데이터가 부족합니다.")
        return

    ws_order = [w["name"] for w in config.WATERSHEDS if w["name"] in diff_table]

    # 권역 매핑 (동부/서부/남부/북부) 및 권역별 기본 색상(해당 AWS 지점 색상)
    region_map = {
        "구좌": "동부", "성산": "동부", "표선": "동부",
        "대정": "서부", "한경": "서부", "한림": "서부",
        "남원": "남부", "동서귀": "남부", "중서귀": "남부", "서서귀": "남부",
        "동제주": "북부", "중제주": "북부", "서제주": "북부", "조천": "북부",
    }
    region_color = {
        "동부": "#E24B4A",  # 성산(188)
        "서부": "#BA7517",  # 고산(185)
        "남부": "#1D9E75",  # 서귀포(189)
        "북부": "#378ADD",  # 제주(184)
    }
    region_station = {"동부": "성산", "서부": "고산", "남부": "서귀포", "북부": "제주"}
    # 기간별 톤(불투명도) — M-2(연함) → M(진함)
    period_alpha = {"M-2": 0.35, "M-1": 0.65, "M": 1.0}

    fig = go.Figure()
    for key in PERIOD_KEYS:
        y_vals, txt, colors = [], [], []
        for w in ws_order:
            rec = diff_table[w].get(key)
            v = rec["편차"] if rec else None
            y_vals.append(v)
            txt.append(f"{'+' if (v is not None and v > 0) else ''}{v:.2f}" if v is not None else "")
            base = region_color[region_map.get(w, "북부")]
            colors.append(_rgba_hex(base, period_alpha[key]))
        fig.add_trace(go.Bar(
            name=key,
            x=ws_order, y=y_vals,
            marker=dict(color=colors, line=dict(color="rgba(255,255,255,1)", width=1)),
            text=txt,
            textposition="outside",
            textfont=dict(size=9),
            cliponaxis=False,
            width=0.22,
            hovertemplate=f"{key}<br>%{{x}}<br>편차: %{{y:.2f}} m<extra></extra>",
            showlegend=False,
        ))

    fig.add_hline(y=0, line_dash="dash", line_color="gray")
    fig.update_layout(
        height=480,
        barmode="group",
        bargap=0.25,
        bargroupgap=0.18,          # 동일 유역 내 M-2/M-1/M 간 얇은 간격
        xaxis_title="",
        xaxis=dict(categoryorder="array", categoryarray=ws_order),
        yaxis_title=yaxis_title,
        yaxis=dict(range=[-5, 5], zeroline=True),
        showlegend=False,
        margin=dict(t=10, b=20, l=60, r=20),
        font=dict(size=11),
    )

    # 커스텀 범례
    #  - 권역: 권역별 기본 색상
    #  - 기준월: 기간별 톤 그라데이션을 4권역 색상으로 각각 표시
    region_legend_items = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:6px;margin-right:14px;font-size:11px;color:#1a1a18;">'
        f'<span style="display:inline-block;width:14px;height:14px;border-radius:3px;'
        f'background:{region_color[r]};"></span>'
        f'{r} ({region_station[r]})</span>'
        for r in ["동부", "서부", "남부", "북부"]
    )

    def _tone_strip(hex_color: str) -> str:
        # M-2 → M-1 → M 톤 3칸을 가로로 붙여 1셋트의 그라데이션 스와치
        segs = "".join(
            f'<span style="display:inline-block;width:10px;height:14px;'
            f'background:{_rgba_hex(hex_color, period_alpha[k])};"></span>'
            for k in PERIOD_KEYS
        )
        return (
            f'<span style="display:inline-flex;border-radius:3px;overflow:hidden;'
            f'border:0.5px solid rgba(26,26,24,0.2);">{segs}</span>'
        )

    period_legend_items = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:6px;margin-right:10px;font-size:11px;color:#1a1a18;">'
        f'<span style="display:inline-block;width:12px;height:12px;border-radius:2px;'
        f'background:{_rgba_hex("#378ADD", period_alpha[k])};'
        f'border:0.5px solid rgba(26,26,24,0.2);"></span>'
        f'{k} ({month_labels_full[i]})</span>'
        for i, k in enumerate(PERIOD_KEYS)
    )
    legend_html = (
        f'<div style="margin:0 0 6px;line-height:1.9;">'
        f'<span style="font-size:11px;color:#5f5e5a;margin-right:6px;">권역</span>{region_legend_items}'
        f'&nbsp;&nbsp;<span style="font-size:11px;color:#5f5e5a;margin-right:6px;">기준월</span>{period_legend_items}'
        f'<span style="font-size:10px;color:#888;margin-left:8px;">'
        f'(M-2 옅음 → M 진함 — 권역색상에 톤 적용)</span>'
        f'</div>'
    )
    st.markdown(legend_html, unsafe_allow_html=True)

    st.plotly_chart(fig, use_container_width=True, key="tab0_ws_diff_bar")

    st.markdown(
        '<div style="font-size:10px;color:#888;margin:-6px 0 8px;text-align:right;">'
        '출처: 제주특별자치도 지하수정보관리시스템(water.jeju.go.kr)</div>',
        unsafe_allow_html=True
    )

    # 요약 — M 기간 기준으로 계산 (종합 요약이므로 최신 기간만 표시)
    m_key = "M"
    m_rows = [r for r in diff_table.values() if r.get(m_key) is not None]
    if m_rows:
        n_above = sum(1 for r in m_rows if r[m_key]["편차"] > 0)
        n_below = sum(1 for r in m_rows if r[m_key]["편차"] < 0)
        theme.render_note_box(
            f"💡 <strong>{periods['M']['label']} 기준 {len(m_rows)}개 유역 분석 결과</strong>: "
            f"직전 {n_gw}년 평균 대비 "
            f"<span class='tbl-pos'>높은 유역 {n_above}개</span>, "
            f"<span class='tbl-neg'>낮은 유역 {n_below}개</span>."
        )
