# ==============================================================================
#  파일명: src/dashboard/tabs/tab01_overview.py
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


@st.fragment  # 21차 Step4: 위젯 변경 시 다른 탭 튕김 방지 (AGENT_GUIDE §6)
def render(
    asos_df: pd.DataFrame,
    ws_data_all: dict,
    periods: dict,
    *,
    gwlevel_diff_dict: "dict | None" = None,
):
    """
    대시보드 요약 탭 렌더링.
    - AWS 지점별 강수량: 3개 기간(M-2, M-1, M) 각 행으로 집약
    - 유역별 지하수위(EL) 변동: 유역당 M-2·M-1·M 3개 막대 그룹
    """
    n_gw = config.GWLEVEL_BASELINE_YEARS

    # --------------------------------------------------------------------------
    # Section 1: AWS 지점별 강수량 (지점별 카드 × 3개 기간 행)
    # --------------------------------------------------------------------------
    st.markdown(
        '<p class="section-title">'
        '<span class="emoji">🌧️</span>AWS 지점별 강수량 (M-2 · M-1 · M)</p>',
        unsafe_allow_html=True,
    )

    if asos_df.empty:
        st.info("ASOS 데이터를 먼저 수집하세요. (⚙️ 데이터 관리 탭)")
    else:
        monthly = effective_rainfall.aggregate_monthly(asos_df)
        half = effective_rainfall.aggregate_half_monthly(asos_df)

        cols = st.columns(4)
        for i, station in enumerate(config.STATIONS_ASOS):
            with cols[i]:
                st_col = station["color"]
                bg_tint   = theme.hex_alpha(st_col, 0.08)
                bord_tint = theme.hex_alpha(st_col, 0.25)
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
                        d_color = theme.COLOR_SUCCESS if diff >= 0 else theme.COLOR_DANGER
                        diff_html = (
                            f'<span style="font-size:16px;color:{d_color};font-weight:600;">'
                            f'{d_sign}{d_abs:.1f}mm</span>'
                        )
                    else:
                        diff_html = '<span style="font-size:15px;color:#999;">-</span>'

                    if actual is None:
                        # 기간 자료 자체가 없음 — 어느 달에 자료가 없는지 명확히 표기
                        rows_html += (
                            f'<div style="padding:7px 0;border-top:0.5px dashed {bord_tint};">'
                            f'<div style="font-size:17px;color:{theme.COLOR_TEXT_PRIMARY};font-weight:600;">'
                            f'{p["label"]} <span style="font-size:15px;color:{theme.COLOR_TEXT_SECONDARY};font-weight:400;">({key})</span></div>'
                            f'<div style="font-size:16px;font-style:italic;color:{theme.COLOR_DANGER};margin-top:3px;">'
                            f'※ {p["label"]} 자료 없음</div>'
                            f'</div>'
                        )
                        continue

                    actual_str = f"{actual:.1f} mm"
                    if avg is not None:
                        avg_html = (
                            f'<span style="font-size:16px;color:{theme.COLOR_TEXT_PRIMARY};font-weight:600;">'
                            f'{avg:.1f}mm</span>'
                            f'<span style="font-size:15px;color:{theme.COLOR_TEXT_SECONDARY};">'
                            f' ({bl_short}년 {p["month"]}월 월합 평균)</span>'
                        )
                    else:
                        avg_html = (
                            f'<span style="font-size:15px;color:{theme.COLOR_TEXT_SECONDARY};">'
                            f'- ({bl_short}년 {p["month"]}월 월합 평균)</span>'
                        )

                    rows_html += (
                        f'<div style="padding:7px 0;border-top:0.5px dashed {bord_tint};">'
                        f'<div style="font-size:17px;color:{theme.COLOR_TEXT_PRIMARY};font-weight:600;">'
                        f'{p["label"]} <span style="font-size:15px;color:{theme.COLOR_TEXT_SECONDARY};font-weight:400;">({key})</span></div>'
                        f'<div style="font-size:15px;font-weight:700;color:{st_col};margin-top:2px;">'
                        f'{actual_str}</div>'
                        f'<div style="margin-top:2px;">'
                        f'{avg_html} <span style="font-size:15px;color:{theme.COLOR_TEXT_SECONDARY};">|</span> {diff_html}</div>'
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
            '<div style="font-size:14px;color:#888;margin:2px 0 0;text-align:right;">'
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
    st.markdown(
        f'<p class="section-title">'
        f'<span class="emoji">💧</span>{section_title}</p>',
        unsafe_allow_html=True,
    )

    if not ws_data_all:
        st.info("지하수위 데이터를 먼저 처리하세요. (⚙️ 데이터 관리 탭)")
        return

    # 유역별·기간별 편차 — app.py 가 전달한 단일 진실 원천 dict 우선 사용.
    # 인자가 없으면 watershed_mapper.compute_gwlevel_diff_dict 로 폴백 (자체
    # 계산은 더이상 안 함 — 분석팀 권고 2026-05-08, 중복 제거).
    if gwlevel_diff_dict is not None:
        diff_table = gwlevel_diff_dict
    else:
        from src.analysis import watershed_mapper as _wsm
        diff_table = _wsm.compute_gwlevel_diff_dict(
            ws_data_all, periods, n_years=n_gw,
        )

    if not diff_table:
        st.info("유역별 실측 데이터가 부족합니다.")
        return

    ws_order = [w["name"] for w in config.WATERSHEDS if w["name"] in diff_table]

    # 권역 매핑·색상·대표 AWS·기간 alpha 는 theme.py 토큰 사용 (탭 간 일관성)
    region_map = theme.REGION_OF_WATERSHED
    region_color = theme.COLOR_REGION
    region_station = theme.REGION_REPRESENTATIVE_AWS
    period_alpha = theme.PERIOD_ALPHA

    fig = go.Figure()
    for key in PERIOD_KEYS:
        y_vals, txt, colors = [], [], []
        for w in ws_order:
            rec = diff_table[w].get(key)
            v = rec["편차"] if rec else None
            y_vals.append(v)
            txt.append(f"{'+' if (v is not None and v > 0) else ''}{v:.2f}" if v is not None else "")
            base = region_color[region_map.get(w, "북부")]
            colors.append(theme.hex_alpha(base, period_alpha[key]))
        fig.add_trace(go.Bar(
            name=key,
            x=ws_order, y=y_vals,
            marker=dict(color=colors, line=dict(color="rgba(255,255,255,1)", width=1)),
            text=txt,
            textposition="outside",
            textfont=dict(size=12),
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
        font=dict(size=14),
    )

    # 커스텀 범례
    #  - 권역: 권역별 기본 색상
    #  - 기준월: 기간별 톤 그라데이션을 4권역 색상으로 각각 표시
    region_legend_items = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:6px;margin-right:14px;font-size:15px;color:{theme.COLOR_TEXT_PRIMARY};">'
        f'<span style="display:inline-block;width:14px;height:14px;border-radius:3px;'
        f'background:{region_color[r]};"></span>'
        f'{r} ({region_station[r]})</span>'
        for r in ["동부", "서부", "남부", "북부"]
    )

    def _tone_strip(hex_color: str) -> str:
        # M-2 → M-1 → M 톤 3칸을 가로로 붙여 1셋트의 그라데이션 스와치
        segs = "".join(
            f'<span style="display:inline-block;width:10px;height:14px;'
            f'background:{theme.hex_alpha(hex_color, period_alpha[k])};"></span>'
            for k in PERIOD_KEYS
        )
        return (
            f'<span style="display:inline-flex;border-radius:3px;overflow:hidden;'
            f'border:0.5px solid rgba(26,26,24,0.2);">{segs}</span>'
        )

    period_legend_items = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:6px;margin-right:10px;font-size:15px;color:{theme.COLOR_TEXT_PRIMARY};">'
        f'<span style="display:inline-block;width:12px;height:12px;border-radius:2px;'
        f'background:{theme.hex_alpha(theme.COLOR_AWS["제주"], period_alpha[k])};'
        f'border:0.5px solid rgba(26,26,24,0.2);"></span>'
        f'{k} ({month_labels_full[i]})</span>'
        for i, k in enumerate(PERIOD_KEYS)
    )
    legend_html = (
        f'<div style="margin:0 0 6px;line-height:1.9;">'
        f'<span style="font-size:15px;color:{theme.COLOR_TEXT_SECONDARY};margin-right:6px;">권역</span>{region_legend_items}'
        f'&nbsp;&nbsp;<span style="font-size:15px;color:{theme.COLOR_TEXT_SECONDARY};margin-right:6px;">기준월</span>{period_legend_items}'
        f'<span class="caption-sm" style="margin-left:8px;">'
        f'(M-2 옅음 → M 진함 — 권역색상에 톤 적용)</span>'
        f'</div>'
    )
    st.markdown(legend_html, unsafe_allow_html=True)

    st.plotly_chart(fig, use_container_width=True, key="tab0_ws_diff_bar")

    st.markdown(
        '<div style="font-size:14px;color:#888;margin:-6px 0 8px;text-align:right;">'
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
