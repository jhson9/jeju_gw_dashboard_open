# ==============================================================================
#  파일명: src/dashboard/tabs/tab01_overview.py
#  탭: 01.유역별현황 (대시보드 요약 + 유역별 상세 통합)
# ------------------------------------------------------------------------------
#  Build: 1.0  (2026-06-06 v3 Stage 2 — tab02_watershed 완전 흡수)
# ------------------------------------------------------------------------------
#  【이 탭의 역할】
#  현재 기준일에 대한 M-2·M-1·M 요약을 한눈에 보여주는 관리자용 대시보드.
#  Stage 1 (2026-06-06): tab01(대시보드 요약) + tab02(유역별 현황) 단일 탭 통합.
#  Stage 2 (2026-06-06 v3): tab02_watershed 의 모든 콘텐츠·헬퍼를 본 모듈로
#  이식하여 단일 파일로 흡수. tab02_watershed.py 삭제 예정.
#
#  【섹션 구성】
#  Section 1 (전체) : AWS 지점별 강수량 카드 4지점 × 3기간
#  Section 2 (전체) : 유역별 지하수위(EL) 변동 그룹드 바 차트
#  ── st.divider() ──
#  Section 3 (상세) : 유역 선택 라디오 + 유역명 헤더
#  Section 4 (상세) : 선택 유역 M-2/M-1/M 카드 (강수량 + 지하수위)
#  Section 5 (상세) : 강수량 + 지하수위 2열 grouped bar 차트
#  Section 6 (상세) : 강수량 + 유효강수일수 표 (AWS)
#  Section 7 (상세) : 지하수위 표 (유역 관측정 목록 포함)
# ==============================================================================

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

import config
from src.analysis import effective_rainfall, watershed_mapper
from src.dashboard import theme


PERIOD_KEYS = ["M-2", "M-1", "M"]


# ==============================================================================
#  ■ 캐싱된 유역→관측정 매핑 (Stage 2 이식 — 구 tab02_watershed)
# ==============================================================================
@st.cache_data(ttl=600)
def _ws_to_stations() -> dict:
    """유역명 → 관측정 목록 매핑 (캐싱).

    JD관측망_정보.xlsx 의 유역명 컬럼 기반 — config.WATERSHEDS 의 14개 유역에
    매칭되는 관측정만 포함. 누락 유역명(31개) 은 매핑에서 제외.
    """
    try:
        return watershed_mapper.get_watershed_to_stations_map(verbose=False)
    except Exception:
        return {}


@st.fragment  # 21차 Step4: 위젯 변경 시 다른 탭 튕김 방지 (AGENT_GUIDE §6)
def render(
    asos_df: pd.DataFrame,
    ws_data_all: dict,
    periods: dict,
    *,
    gwlevel_diff_dict: "dict | None" = None,
):
    """
    01.유역별현황 탭 렌더링 (Stage 2 통합본).

    - AWS 지점별 강수량: 3개 기간(M-2, M-1, M) 각 행으로 집약
    - 유역별 지하수위(EL) 변동: 유역당 M-2·M-1·M 3개 막대 그룹
    - st.divider() 로 분리 후 유역별 상세 (구 tab02 콘텐츠) 출력
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
                            f' ({bl_short}년 {p["month"]}월 평균)</span>'
                        )
                    else:
                        avg_html = (
                            f'<span style="font-size:15px;color:{theme.COLOR_TEXT_SECONDARY};">'
                            f'- ({bl_short}년 {p["month"]}월 평균)</span>'
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
        diff_table = watershed_mapper.compute_gwlevel_diff_dict(
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

    # 🆕 (2026-06-06 v3 Stage 2) tab02_watershed 완전 흡수 — 유역별 상세 섹션
    st.divider()  # 디자인3팀 권고 — 두 섹션 명확 분리
    _render_watershed_details(
        asos_df, ws_data_all, periods,
        gwlevel_diff_dict=gwlevel_diff_dict,
    )


# ==============================================================================
#  ■ 유역별 상세 (Stage 2 이식 — 구 tab02_watershed.render 본문)
# ==============================================================================
def _render_watershed_details(
    asos_df: pd.DataFrame,
    ws_data_all: dict,
    periods: dict,
    gwlevel_diff_dict: "dict | None" = None,
):
    """유역별 현황 상세 섹션.

    Parameters
    ----------
    gwlevel_diff_dict : dict, optional
        app.py 가 계산한 ``compute_gwlevel_diff_dict`` 결과 (Tab01 Section 2 와
        동일한 단일 진실 원천). 주어지면 카드의 baseline 평균을 여기서 lookup.
        미주어지면 기존 인라인 계산(폴백)으로 동작 — 하위 호환 보장.

    참고: 본 함수는 부모 render() 의 @st.fragment 안에서 호출되므로 별도의
    fragment 데코레이터는 불필요. 라디오 변경 시 부모 fragment 가 재실행되며,
    Section 1·2 (AWS 카드 + 유역 EL 차트) 도 함께 재렌더링되지만 사용자가
    이미 단일 탭에서 통합 시각화를 요청했으므로 의도된 동작.
    """
    # ── 유역 선택 ──────────
    # st.radio(horizontal=True): deselect 이슈가 없고 widget key 로 상태 관리됨.
    # segmented_control 의 "한 박자 늦은 반영 + 탭 튕김" 복합 버그를 해소.
    ws_names = [w["name"] for w in config.WATERSHEDS]
    ws_color = {w["name"]: w["color"] for w in config.WATERSHEDS}
    ws_aws   = {w["name"]: w["aws"]   for w in config.WATERSHEDS}

    if "tab1_ws_radio" not in st.session_state:
        st.session_state["tab1_ws_radio"] = ws_names[0]

    sel = st.radio(
        "유역 선택",
        options=ws_names,
        horizontal=True,
        key="tab1_ws_radio",
        label_visibility="collapsed",
    )
    # 하위 호환: 기존에 tab1_ws 를 참조하는 곳이 있을 수 있어 같이 동기화
    st.session_state["tab1_ws"] = sel
    nearby    = ws_aws.get(sel, "제주")
    ws_col    = ws_color.get(sel, theme.COLOR_TEXT_INFO)
    aws_col   = config.AWS_COLOR_MAP.get(nearby, theme.COLOR_AWS["제주"])
    aws_code  = config.AWS_CODE_MAP.get(nearby, "")

    st.markdown(
        f'<p class="section-title">'
        f'<span style="color:{ws_col};">●</span>&nbsp;{sel} 유역 현황'
        f'&nbsp;&nbsp;<span style="font-size:13px;font-weight:400;color:var(--color-text-secondary);">'
        f'(강수량 AWS: <strong>{nearby}</strong>)</span>'
        f'</p>',
        unsafe_allow_html=True
    )

    # ── 데이터 준비 ───────────────────────────────────────────
    has_asos = not asos_df.empty
    ws_df    = ws_data_all.get(sel) if ws_data_all else None
    has_ws   = (ws_df is not None and not ws_df.empty)

    if has_asos:
        monthly = effective_rainfall.aggregate_monthly(asos_df)
        half    = effective_rainfall.aggregate_half_monthly(asos_df)

    ps_keys = ["M-2", "M-1", "M"]
    ps      = [periods[k] for k in ps_keys]
    # 차트 X축 라벨 (축약): "11월 (M-2)"
    xlabels = [f"{p['month']}월 ({k})" for k, p in zip(ps_keys, ps)]
    n_rain  = config.RAINFALL_BASELINE_YEARS
    n_gw    = config.GWLEVEL_BASELINE_YEARS

    # ── M-2·M-1·M 요약 카드 (기존 HTML .card 스타일) ─────────
    card_cols = st.columns(3)
    for i, (pk, p) in enumerate(zip(ps_keys, ps)):
        ym = f"{p['year']}-{p['month']:02d}"
        bl = list(range(p["year"] - n_gw, p["year"]))

        rain_a = rain_v = gw_a = gw_v = None
        if has_asos:
            rain_a  = effective_rainfall.get_period_value(monthly, half, p, nearby, "월강수량(mm)")
            rain_v, _ = effective_rainfall.get_baseline_average(monthly, half, p, nearby, "월강수량(mm)", n_years=n_rain)
        if has_ws:
            # 단일 진실 원천(SSOT) 우선 — app.py 가 미리 계산한 dict 가
            # 있으면 거기서 조회 (Section 2 와 동일 값 보장). 없으면 인라인 계산.
            ssot = (gwlevel_diff_dict or {}).get(sel, {}).get(pk)
            if ssot is not None:
                gw_a = ssot.get("실측")
                gw_v = ssot.get("평균")
            else:
                ra = ws_df[ws_df["연월"] == ym]
                gw_a = float(ra["EL_평균"].iloc[0]) if not ra.empty else None
                bv = [float(ws_df[ws_df["연월"] == f"{y}-{p['month']:02d}"]["EL_평균"].iloc[0])
                      for y in bl
                      if not ws_df[ws_df["연월"] == f"{y}-{p['month']:02d}"].empty
                      and pd.notna(ws_df[ws_df["연월"] == f"{y}-{p['month']:02d}"]["EL_평균"].iloc[0])]
                gw_v = sum(bv)/len(bv) if bv else None

        def _diff(a, v, unit, dec=1):
            if a is None or v is None: return ""
            d = a - v
            c = theme.COLOR_SUCCESS if d >= 0 else theme.COLOR_DANGER
            s = "+" if d >= 0 else ""
            return f'<span style="color:{c};font-weight:500;">{s}{d:.{dec}f}{unit}</span>'

        is_m = (pk == "M")
        bg   = theme.COLOR_BG_INFO if is_m else theme.COLOR_BG_SECONDARY
        bd   = "2px" if is_m else "1px"
        bd_c = ws_col if is_m else ws_col + "80"

        # 짧은 연도 (YY)
        yy_m      = str(p["year"])[2:]
        bl_r      = list(range(p["year"] - n_rain, p["year"]))
        yr_rain_s = f"{str(bl_r[0])[2:]}~{str(bl_r[-1])[2:]}"
        yr_gw_s   = f"{str(bl[0])[2:]}~{str(bl[-1])[2:]}"

        ra_str   = f"{rain_a:.0f} mm" if rain_a is not None else "–"
        rv_str   = f"{rain_v:.0f} mm" if rain_v is not None else "–"
        gw_str   = f"{gw_a:.2f} m"    if gw_a    is not None else "–"
        gv_str   = f"{gw_v:.2f} m"    if gw_v    is not None else "–"

        date_col = ws_col if is_m else theme.COLOR_TEXT_PRIMARY

        html = (
            f'<div style="background:{bg};border:0.5px solid {ws_col}40;'
            f'border-left:{bd} solid {bd_c};border-radius:8px;padding:10px 12px;">'
            # 기간 헤더 — "2025년 11월 (M-2)" 중앙 정렬
            f'<p style="margin:0 0 8px;text-align:center;">'
            f'<span class="section-title" style="color:{date_col};">'
            f'{p["year"]}년 {p["month"]}월</span>'
            f'&nbsp;&nbsp;<span style="font-size:15px;color:var(--color-text-secondary);">({pk})</span>'
            f'</p>'
            # 강수량 / 지하수위 그리드
            f'<div style="display:grid;grid-template-columns:1fr 8px 1fr;gap:6px;">'
            # ── 강수량 ──
            f'<div>'
            f'<p style="font-size:16px;color:var(--color-text-secondary);margin:0 0 2px;">강수량 ({nearby})</p>'
            # 실측 + 월 레이블
            f'<p style="margin:0;">'
            f'<span style="font-size:18px;font-weight:500;">{ra_str}</span>'
            f'&nbsp;<span style="font-size:14px;color:var(--color-text-secondary);">{yy_m}년 {p["month"]}월 합</span>'
            f'</p>'
            # 직전 5년 같은 달의 평균 + 기간 레이블 + 편차
            f'<p style="margin:2px 0 0;">'
            f'<span style="font-size:15px;font-weight:500;color:var(--color-text-secondary);">{rv_str}</span>'
            f'&nbsp;<span style="font-size:14px;color:var(--color-text-secondary);">{yr_rain_s}년 {p["month"]}월 평균</span>'
            f'&nbsp;<span style="font-size:14px;color:var(--color-text-secondary);">|</span>'
            f'&nbsp;<span style="font-size:14px;">{_diff(rain_a, rain_v, "mm")}</span>'
            f'</p>'
            f'</div>'
            f'<div style="background:rgba(26,26,24,0.12);"></div>'
            # ── 지하수위 (강수량과 동일 구조) ──
            f'<div>'
            f'<p style="font-size:16px;color:var(--color-text-secondary);margin:0 0 2px;">지하수위 ({sel})</p>'
            # 실측 + 월 레이블
            f'<p style="margin:0;">'
            f'<span style="font-size:18px;font-weight:500;">{gw_str}</span>'
            f'&nbsp;<span style="font-size:14px;color:var(--color-text-secondary);">{yy_m}년 {p["month"]}월 평균</span>'
            f'</p>'
            # 직전 3년 평균 + 기간 레이블 + 편차
            f'<p style="margin:2px 0 0;">'
            f'<span style="font-size:15px;font-weight:500;color:var(--color-text-secondary);">{gv_str}</span>'
            f'&nbsp;<span style="font-size:14px;color:var(--color-text-secondary);">{yr_gw_s}년 {p["month"]}월 평균</span>'
            f'&nbsp;<span style="font-size:14px;color:var(--color-text-secondary);">|</span>'
            f'&nbsp;<span style="font-size:14px;">{_diff(gw_a, gw_v, "m", 2)}</span>'
            f'</p>'
            f'</div>'
            f'</div>'
            f'</div>'
        )
        with card_cols[i]:
            st.markdown(html, unsafe_allow_html=True)

    st.markdown("<div style='height:12px;'></div>", unsafe_allow_html=True)

    # ── 2열 차트: 강수량 + 지하수위 (나란히/grouped) ──────────
    ch1, ch2 = st.columns(2)

    # 차트용 데이터
    rain_act = rain_avg_v = eff_act = eff_avg_v = None
    gw_act_v = gw_avg_v = None
    if has_asos:
        rain_act   = [effective_rainfall.get_period_value(monthly, half, p, nearby, "월강수량(mm)") for p in ps]
        rain_avg_v = [effective_rainfall.get_baseline_average(monthly, half, p, nearby, "월강수량(mm)", n_years=n_rain)[0] for p in ps]

    if has_ws:
        gw_act_v = []
        gw_avg_v = []
        for p in ps:
            ym = f"{p['year']}-{p['month']:02d}"
            bl = list(range(p["year"] - n_gw, p["year"]))
            ra = ws_df[ws_df["연월"] == ym]
            gw_act_v.append(float(ra["EL_평균"].iloc[0]) if not ra.empty else None)
            bv = [float(ws_df[ws_df["연월"] == f"{y}-{p['month']:02d}"]["EL_평균"].iloc[0])
                  for y in bl
                  if not ws_df[ws_df["연월"] == f"{y}-{p['month']:02d}"].empty]
            gw_avg_v.append(sum(bv)/len(bv) if bv else None)

    # 범례/캡션용 문자열 — 차트와 표에서 공용으로 사용
    lbl_r_avg = f"과거 {n_rain}년 해당월 평균"
    lbl_r_act = "최근 강수량"
    lbl_g_avg = f"과거 {n_gw}년 해당월 평균"
    lbl_g_act = "최근 지하수위"

    # 🆕 (2026-06-06 v3 사용자 요청) partial M 에 "(~5일)" 명시 — 비교 단위 명확화
    def _p_lbl(p):
        s = f"{str(p['year'])[2:]}년 {p['month']}월"
        if p.get("partial"):
            s += f"(~{p['end_date'].day}일)"
        return s
    def _bl_rain(p):
        s = f"{str(p['year']-n_rain)[2:]}~{str(p['year']-1)[2:]}년 {p['month']}월"
        if p.get("partial"):
            s += f"(~{p['end_date'].day}일)"
        return s
    def _bl_gw(p):
        # 지하수위 baseline 은 일자료 직접 계산 시 partial 윈도우 (M-1·M-2 는 월)
        s = f"{str(p['year']-n_gw)[2:]}~{str(p['year']-1)[2:]}년 {p['month']}월"
        if p.get("partial"):
            s += f"(~{p['end_date'].day}일)"
        return s
    recent_months = ", ".join(_p_lbl(p) for p in ps)
    baseline_rain_str = ", ".join(_bl_rain(p) for p in ps)
    baseline_gw_str = ", ".join(_bl_gw(p) for p in ps)
    caption_style = 'font-size:14px;color:var(--color-text-secondary);margin:4px 0 0;'

    with ch1:
        st.markdown(
            '<p class="section-title">강수량(mm)</p>',
            unsafe_allow_html=True
        )
        _legend_row(lbl_r_avg, lbl_r_act, aws_col)
        if has_asos and rain_act:
            fig = _grouped_bar(xlabels, rain_avg_v, rain_act, aws_col,
                               lbl_r_avg, lbl_r_act, "mm", decimals=0)
            st.plotly_chart(fig, use_container_width=True, key=f"t1_rain_{sel}")
            st.markdown(
                f'<p style="{caption_style}">'
                f'* 최근 월 강수량 : {recent_months}'
                f' &nbsp;|&nbsp; 과거 {n_rain}년 해당월 : {baseline_rain_str}</p>',
                unsafe_allow_html=True
            )
        else:
            st.info("ASOS 데이터 없음")

    with ch2:
        st.markdown(
            '<p class="section-title">지하수위(EL)</p>',
            unsafe_allow_html=True
        )
        _legend_row(lbl_g_avg, lbl_g_act, ws_col)
        if has_ws and gw_act_v:
            all_v = [v for v in gw_act_v + gw_avg_v if v is not None]
            y_min = min(all_v) * 0.96 if all_v else 0
            fig = _grouped_bar(xlabels, gw_avg_v, gw_act_v, ws_col,
                               lbl_g_avg, lbl_g_act, "m", y_min=y_min, decimals=2)
            st.plotly_chart(fig, use_container_width=True, key=f"t1_gw_{sel}")
            st.markdown(
                f'<p style="{caption_style}">'
                f'* 최근 월 수위 : {recent_months}'
                f' &nbsp;|&nbsp; 과거 {n_gw}년 해당월 : {baseline_gw_str}</p>',
                unsafe_allow_html=True
            )
        else:
            st.info(f"{sel} 유역 지하수위 데이터 없음")

    st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

    # ── 표 A: 강수량 + 유효강수일수 ─────────────────────────
    st.markdown(
        f'<p class="section-title">'
        f'강수량 및 농업유효강수일수 : {nearby} ({aws_code})</p>'
        f'<p style="font-size:14px;color:var(--color-text-secondary);margin:0 0 8px;">'
        f'농업유효강수일수: 일강수량 {config.EFFECTIVE_RAINFALL_THRESHOLD_MM} mm 이상</p>',
        unsafe_allow_html=True
    )
    if has_asos:
        _render_aws_table(monthly, half, periods, nearby, ps_keys)
        st.markdown(
            f'<p style="font-size:14px;color:var(--color-text-secondary);margin:4px 0 0;">'
            f'* 최근 월 강수량 : {recent_months}'
            f' &nbsp;|&nbsp; 과거 {n_rain}년 해당월 : {baseline_rain_str}</p>',
            unsafe_allow_html=True
        )
    else:
        st.info("ASOS 데이터 없음")

    st.markdown("<div style='height:12px;'></div>", unsafe_allow_html=True)

    # ── 표 B: 유역 지하수위 현황 ──────────────────────────────
    st.markdown(
        f'<p class="section-title">지하수위(EL) 현황 : {sel}유역</p>',
        unsafe_allow_html=True
    )
    st.markdown("<div style='height:4px;'></div>", unsafe_allow_html=True)
    if has_ws:
        _render_gw_table(ws_df, periods, ps_keys)
        # 유역 내 관측정 목록 — JD관측망_정보.xlsx 의 유역명 매핑 기반
        ws_stations = _ws_to_stations().get(sel, [])
        stations_str = (
            ", ".join(ws_stations) if ws_stations else "(매핑된 관측정 없음)"
        )
        st.markdown(
            f'<p style="font-size:14px;color:var(--color-text-secondary);margin:4px 0 0;">'
            f'* 최근 월 수위 : {recent_months}'
            f' &nbsp;|&nbsp; 과거 {n_gw}년 해당월 : {baseline_gw_str}</p>'
            f'<p style="font-size:14px;color:var(--color-text-secondary);margin:2px 0 0;">'
            f'* 유역 내 관측정 ({len(ws_stations)}공) : {stations_str}</p>',
            unsafe_allow_html=True
        )
    else:
        st.info("지하수위 데이터 없음")


# ==============================================================================
#  ■ 차트 헬퍼 (Stage 2 이식 — 구 tab02_watershed)
# ==============================================================================
def _legend_row(label_avg: str, label_act: str, color: str):
    """평균(외곽선) + 실측(채움) 범례를 한 줄로 렌더링."""
    box_avg = (f'<span style="width:10px;height:10px;border-radius:2px;'
               f'border:1.5px solid {color};display:inline-block;"></span>')
    box_act = (f'<span style="width:10px;height:10px;border-radius:2px;'
               f'background:{color};display:inline-block;"></span>')
    st.markdown(
        f'<div style="font-size:15px;color:var(--color-text-secondary);margin:0 0 4px;">'
        f'<span style="display:inline-flex;align-items:center;gap:4px;margin-right:14px;">'
        f'{box_avg} {label_avg}</span>'
        f'<span style="display:inline-flex;align-items:center;gap:4px;">'
        f'{box_act} {label_act}</span>'
        f'</div>',
        unsafe_allow_html=True
    )


def _grouped_bar(xlabels, avg_vals, act_vals, color, avg_name, act_name, unit,
                 y_min=None, decimals=1):
    """평균=투명+테두리, 실측=채움, grouped. 실측 바 위에 값 라벨 표시."""
    def _fmt(v):
        return "" if v is None else f"{v:.{decimals}f}"

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name=avg_name, x=xlabels, y=avg_vals,
        marker=dict(color=theme.hex_alpha(color, 0.18), line=dict(color=color, width=1.5)),
        text=[_fmt(v) for v in avg_vals],
        textposition="outside",
        textfont=dict(size=14, color=theme.COLOR_TEXT_SECONDARY),
        cliponaxis=False,
        hovertemplate=f"%{{x}}<br>{avg_name}: %{{y:.2f}} {unit}<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        name=act_name, x=xlabels, y=act_vals,
        marker=dict(color=color),
        text=[_fmt(v) for v in act_vals],
        textposition="outside",
        textfont=dict(size=14, color=theme.COLOR_TEXT_PRIMARY),
        cliponaxis=False,
        hovertemplate=f"%{{x}}<br>{act_name}: %{{y:.2f}} {unit}<extra></extra>",
    ))
    layout = dict(
        barmode="group", height=220,
        xaxis_title="", yaxis_title=unit,
        xaxis=dict(tickfont=dict(size=15)),      # X축 라벨 1사이즈 확대
        bargap=0.35,                              # 기간 그룹 간격
        bargroupgap=0.18,                         # 평균/실측 바 사이 간격
        margin=dict(t=14, b=4, l=38, r=8),
        showlegend=False, font=dict(size=14),
    )
    if y_min is not None:
        layout["yaxis"] = dict(range=[y_min, None])
    fig.update_layout(**layout)
    return fig


# ==============================================================================
#  ■ 표 렌더링 (Stage 2 이식 — 구 tab02_watershed)
# ==============================================================================
def _th(text, width="", extra=""):
    w = f"width:{width};" if width else ""
    return (f'<th style="padding:6px 8px;border-bottom:1px solid #ccc;'
            f'background:var(--color-bg-secondary);{w}{extra}">{text}</th>')

def _td(text, extra=""):
    return f'<td style="padding:6px 8px;border-bottom:0.5px solid #eee;{extra}">{text}</td>'

def _diff_str(a, v, unit, dec=1):
    if a is None or v is None: return "–"
    d = a - v
    c = theme.COLOR_SUCCESS if d >= 0 else theme.COLOR_DANGER
    s = "+" if d >= 0 else ""
    return (f'<span style="color:{c};font-weight:500;">'
            f'{s}{d:.{dec}f}{unit}</span>')


def _render_gw_table(ws_df, periods, ps_keys):
    """기간=행, 지표=열 구조.
    열: 기간 | 최근 월 수위 (m) | 과거 N년 해당월 평균 (m) | 지하수위 편차 (m)
    table-layout:fixed 로 열 폭을 균등 분배."""
    ps = [periods[k] for k in ps_keys]
    n  = config.GWLEVEL_BASELINE_YEARS

    # colgroup: 기간 = 공용 120px, 데이터 3열 = 균등 분배(33% 씩)
    colgroup = (
        '<colgroup>'
        '<col style="width:360px;">'
        '<col><col><col>'
        '</colgroup>'
    )

    head = (
        '<table style="width:100%;border-collapse:collapse;'
        'table-layout:fixed;font-size:16px;">'
        + colgroup
        + '<thead><tr style="background:var(--color-bg-secondary);">'
        + _th("기간", extra="text-align:center;border-bottom:1.5px solid #ccc;")
        + _th("최근 월 수위 (m)", extra="text-align:center;border-bottom:1.5px solid #ccc;")
        + _th(f"과거 {n}년 해당월 평균 (m)", extra="text-align:center;border-bottom:1.5px solid #ccc;")
        + _th("지하수위 편차 (m)", extra="text-align:center;border-bottom:1.5px solid #ccc;")
        + '</tr></thead><tbody>'
    )

    body = ""
    for pk, p in zip(ps_keys, ps):
        ym = f"{p['year']}-{p['month']:02d}"
        bl = list(range(p["year"] - n, p["year"]))
        ra = ws_df[ws_df["연월"] == ym]
        actual = float(ra["EL_평균"].iloc[0]) if not ra.empty else None
        bv = [float(ws_df[ws_df["연월"] == f"{y}-{p['month']:02d}"]["EL_평균"].iloc[0])
              for y in bl
              if not ws_df[ws_df["연월"] == f"{y}-{p['month']:02d}"].empty]
        avg = sum(bv)/len(bv) if bv else None
        diff = round(actual - avg, 2) if (actual is not None and avg is not None) else None

        a_s = f'<span class="subsection-title">{actual:.2f}</span>' if actual is not None else "–"
        v_s = f'{avg:.2f}' if avg is not None else "–"
        d_s = _diff_cell(diff, "") if diff is not None else "–"

        body += (
            '<tr>'
            f'<td style="padding:6px 8px;border-bottom:0.5px solid #eee;text-align:center;">'
            f'<div style="font-size:16px;font-weight:500;">{p["month"]}월</div>'
            f'<div style="font-size:15px;color:var(--color-text-secondary);">({pk})</div>'
            f'</td>'
            f'<td style="padding:6px 8px;border-bottom:0.5px solid #eee;text-align:center;">{a_s}</td>'
            f'<td style="padding:6px 8px;border-bottom:0.5px solid #eee;text-align:center;">{v_s}</td>'
            f'<td style="padding:6px 8px;border-bottom:0.5px solid #eee;text-align:center;">{d_s}</td>'
            '</tr>'
        )
    st.markdown(head + body + "</tbody></table>", unsafe_allow_html=True)


def _diff_cell(val, unit, is_pct=False):
    if val is None: return "–"
    c = theme.COLOR_SUCCESS if val >= 0 else theme.COLOR_DANGER
    s = "+" if val >= 0 else ""
    return f'<span style="color:{c};font-weight:500;">{s}{val}{unit}</span>'


def _render_aws_table(monthly, half, periods, station, ps_keys):
    """기간=행, 지표=열 구조.
    열: 기간 | 최근 월 강수량 | 과거 5년 평균 | 강수량 편차 |
         금년 해당월 유효강수일 | 과거 5년 해당월 유효강수일 | 유효강수일수 편차"""
    ps    = [periods[k] for k in ps_keys]
    n_r   = config.RAINFALL_BASELINE_YEARS

    # 2단 헤더: 1행은 그룹(강수량 / 농업유효 강수일수), 2행은 하위 열
    # table-layout:fixed + colgroup 으로 6개 데이터 열은 균등 폭으로 표시
    group_th_base = (
        'padding:6px 8px;background:var(--color-bg-secondary);text-align:center;'
        'border-bottom:1px solid #ddd;font-weight:600;'
    )
    sub_th_base = (
        'padding:5px 6px;background:var(--color-bg-secondary);text-align:center;'
        'border-bottom:1.5px solid #ccc;font-size:15px;font-weight:500;color:var(--color-text-secondary);'
    )

    colgroup = (
        '<colgroup>'
        '<col style="width:360px;">'      # 기간
        '<col><col><col>'                 # 강수량 3열 (균등)
        '<col><col><col>'                 # 유효강수 3열 (균등)
        '</colgroup>'
    )

    head = (
        '<table style="width:100%;border-collapse:collapse;'
        'table-layout:fixed;font-size:16px;">'
        + colgroup
        + '<thead>'
        # ── 1행: 그룹 헤더
        '<tr>'
        f'<th rowspan="2" style="padding:6px 8px;background:var(--color-bg-secondary);text-align:center;'
        f'vertical-align:middle;border-bottom:1.5px solid #ccc;">기간</th>'
        f'<th colspan="3" style="{group_th_base}">강수량 (mm)</th>'
        f'<th colspan="3" style="{group_th_base}border-left:1px solid #ddd;">'
        f'농업유효 강수일수 (일)</th>'
        '</tr>'
        # ── 2행: 하위 열
        '<tr>'
        f'<th style="{sub_th_base}">최근 월 강수량</th>'
        f'<th style="{sub_th_base}">과거 {n_r}년 해당월 평균</th>'
        f'<th style="{sub_th_base}">편차</th>'
        f'<th style="{sub_th_base}border-left:1px solid #ddd;">최근 유효강수일</th>'
        f'<th style="{sub_th_base}">과거 {n_r}년 해당월 평균</th>'
        f'<th style="{sub_th_base}">편차</th>'
        '</tr>'
        '</thead><tbody>'
    )

    body = ""
    for pk, p in zip(ps_keys, ps):
        ra   = effective_rainfall.get_period_value(monthly, half, p, station, "월강수량(mm)")
        rv,_ = effective_rainfall.get_baseline_average(monthly, half, p, station, "월강수량(mm)", n_years=n_r)
        ea   = effective_rainfall.get_period_value(monthly, half, p, station, "유효강수일수(일)")
        ev,_ = effective_rainfall.get_baseline_average(monthly, half, p, station, "유효강수일수(일)", n_years=n_r)

        ra_s = f'<span class="subsection-title">{ra:.0f}</span>' if ra is not None else "–"
        rv_s = f"{rv:.0f}" if rv is not None else "–"
        rd_s = _diff_str(ra, rv, "", dec=0) if (ra is not None and rv is not None) else "–"
        ea_s = f'<span class="subsection-title">{int(round(ea))}</span>' if ea is not None else "–"
        ev_s = f"{ev:.1f}" if ev is not None else "–"
        ed_s = _diff_str(ea, ev, "", dec=0) if (ea is not None and ev is not None) else "–"

        base_td = 'padding:6px 8px;border-bottom:0.5px solid #eee;text-align:center;'
        body += (
            '<tr>'
            f'<td style="{base_td}">'
            f'<div style="font-size:16px;font-weight:500;">{p["month"]}월</div>'
            f'<div style="font-size:15px;color:var(--color-text-secondary);">({pk})</div>'
            f'</td>'
            f'<td style="{base_td}">{ra_s}</td>'
            f'<td style="{base_td}">{rv_s}</td>'
            f'<td style="{base_td}">{rd_s}</td>'
            f'<td style="{base_td}border-left:1px solid #ddd;">{ea_s}</td>'
            f'<td style="{base_td}">{ev_s}</td>'
            f'<td style="{base_td}">{ed_s}</td>'
            '</tr>'
        )
    st.markdown(head + body + "</tbody></table>", unsafe_allow_html=True)
