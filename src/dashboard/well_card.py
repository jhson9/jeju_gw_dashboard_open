# ==============================================================================
#  파일명: src/dashboard/well_card.py
#  단일 관정 카드 — master 28개 필드 5섹션 + 미니차트 3개 (이용량/수질).
#
#  Source 분리: ag_well_helpers.py → 그룹별 분리 5단계 (2026-05-09).
#    - _CARD_SECTIONS         : 28개 필드를 5개 섹션으로 그룹핑한 표시 사양
#    - _format_card_value     : 카드 값 포맷터 (단위·날짜·bool 처리)
#    - render_well_card       : 카드 + 미니차트 래퍼
#    - build_mini_charts      : 연·월 이용량 + 수질 NO3 미니차트 3개
#
#  호환성: ag_well_helpers.py 가 이 모듈에서 모두 re-export → 기존 호출처
#  (`ag_well_helpers.render_well_card(...)`) 그대로 동작.
#  외부 호출: tab11_ag_search.py:239 (1곳).
# ==============================================================================
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import config
from src.analysis import ag_well_loader, ag_well_metrics
from src.dashboard import theme


# master.csv 28개 필드를 5개 섹션으로 그룹핑한 카드 표시 사양
_CARD_SECTIONS: list[tuple[str, list[tuple[str, str, str]]]] = [
    ("기본 정보", [
        ("permit_no",     "허가번호",   ""),
        ("well_id",       "관정명",     ""),
        ("active",        "운영",       ""),
        ("water_management","수리계",   ""),
        ("watershed",     "수역",       ""),
        # 사용자 요청 (2026-05-16): master.csv 의 한글 authority_kor 표시.
        # 결측 0건. tab5 결과 표 '관리주체' 컬럼과 동일 데이터 소스.
        ("authority_kor", "관리주체",   ""),
    ]),
    ("관정 위치", [
        ("well_si",          "시",        ""),
        ("well_eup",         "읍/면/동",  ""),
        ("well_ri",          "리",        ""),
        ("well_bunji",       "번지",      ""),
        ("well_bunji_check", "번지 확인", ""),
        ("coord_x",          "X좌표(TM)", ""),
        ("coord_y",          "Y좌표(TM)", ""),
    ]),
    ("배수조 위치", [
        ("tank_count", "배수조 수",       "개"),
        ("tank_si",    "배수조 시",       ""),
        ("tank_eup",   "배수조 읍/면/동", ""),
        ("tank_ri",    "배수조 리",       ""),
        ("tank_bunji", "배수조 번지",     ""),
    ]),
    ("시설·수위 제원", [
        ("install_date",          "시설년도",   ""),
        ("elevation_m",           "표고",       "m"),
        ("drill_depth_m",         "굴착심도",   "m"),
        ("casing_diameter_mm",    "케이싱 구경","mm"),
        ("discharge_diameter_mm", "토출구경",   "mm"),
        ("natural_water_level_m", "자연수위",   "m"),
        ("stable_water_level_m",  "안정수위",   "m"),
    ]),
    ("운영·펌프", [
        ("capacity_m3d", "양수능력",     "㎥/일"),
        ("permit_m3m",   "취수허가량",   "㎥/월"),
        ("voltage_v",    "전압",         "V"),
        ("motor_hp",     "수중모터 마력","HP"),
        ("pump_depth_m", "수중펌프 심도","m"),
    ]),
]


def _format_card_value(key: str, val) -> str:
    """카드 값 포맷터 — 컬럼별 단위·날짜·bool 처리."""
    if val is None:
        return "-"
    if isinstance(val, float) and pd.isna(val):
        return "-"
    if key == "active":
        return "활성" if bool(val) else "비활성"
    if key == "install_date":
        try:
            return pd.to_datetime(val).strftime("%Y-%m-%d")
        except Exception:
            return str(val)
    if key in ("coord_x", "coord_y"):
        try:
            return f"{float(val):,.2f}"
        except (TypeError, ValueError):
            return str(val)
    return str(val).strip() or "-"


def render_well_card(permit_no: str, last_n_years: int = 5) -> None:
    """선택된 관정 카드 — master 전체 필드(28개) + 미니차트 3개."""
    info = ag_well_loader.get_well_info(permit_no)
    if info is None:
        st.warning(f"관정 정보를 찾을 수 없습니다: {permit_no}")
        return

    title = f"관정 카드 — {info.get('well_id') or permit_no} ({permit_no})"
    st.markdown(
        f'<div class="subsection-title" style="color:var(--color-text-info);'
        f'padding:6px 0;border-top:1px solid rgba(26,26,24,0.15);'
        f'margin-top:8px;">{title}</div>',
        unsafe_allow_html=True,
    )

    # ── 5개 섹션을 가로 5칼럼으로 배치 (각 섹션 = 한 컬럼)
    # 사용자 요청 2026-05-10: 카드 글자 2단계 크게 (+4px). 라벨 width 도 비례.
    #   section title 11→15, field row 11.5→15.5, label width 84→112.
    cols = st.columns(len(_CARD_SECTIONS))
    for col, (section_title, fields) in zip(cols, _CARD_SECTIONS):
        with col:
            html = [
                f'<div style="font-size:15px;font-weight:600;color:var(--color-text-info);'
                f'border-bottom:0.5px solid #85b7eb;padding-bottom:3px;'
                f'margin-bottom:6px;">{section_title}</div>',
                '<div style="font-size:15.5px;line-height:2.4;">',
            ]
            for key, label, unit in fields:
                v_text = _format_card_value(key, info.get(key))
                if v_text not in ("-", "") and unit:
                    v_text = f"{v_text} {unit}"
                html.append(
                    f'<div><span style="color:var(--color-text-secondary);display:inline-block;'
                    f'width:112px;">{label}</span>'
                    f'<span style="color:var(--color-text-primary);font-weight:500;">{v_text}</span></div>'
                )
            html.append("</div>")
            st.markdown("\n".join(html), unsafe_allow_html=True)

    # ── 차트: 가로로 3개
    st.markdown(
        '<div style="height:8px;"></div>', unsafe_allow_html=True
    )
    build_mini_charts(permit_no, last_n_years=last_n_years)


def build_mini_charts(
    permit_no: str,
    last_n_years: int = 5,
    monthly_n_years: int = 3,
) -> None:
    """카드 하단 — 미니차트 3개:
       (1) 연 이용량 (최근 5년 막대)
       (2) 월별 이용량 (최근 3년 막대)
       (3) 수질 NO3 (반기, 전체 ~10년 라인)
    """
    df_usage = ag_well_loader.load_usage_long()
    df_qual  = ag_well_loader.load_quality_semiannual()

    summary = ag_well_metrics.well_yearly_summary(
        df_usage, permit_no, last_n_years=last_n_years
    )

    c1, c2, c3 = st.columns(3)

    # ── (1) 연 이용량 (최근 5년)
    with c1:
        if summary.empty:
            st.caption(f"연 이용량 (최근 {last_n_years}년): 자료 없음")
        else:
            fig = go.Figure(go.Bar(
                x=summary["year"], y=summary["volume_m3"],
                marker_color=theme.COLOR_ACCENT_BLUE_2,
                text=[f"{int(v):,}" if pd.notna(v) else ""
                      for v in summary["volume_m3"]],
                textposition="outside", textfont=dict(size=13),
            ))
            fig.update_layout(
                title=f"연 이용량 — 최근 {last_n_years}년 (㎥)",
                title_font_size=15,
                height=210, margin=dict(l=10, r=10, t=30, b=20),
                yaxis_title=None, xaxis_title=None,
                showlegend=False, plot_bgcolor="white",
            )
            fig.update_xaxes(tickvals=summary["year"], tickfont=dict(size=14))
            fig.update_yaxes(tickfont=dict(size=13))
            st.plotly_chart(fig, use_container_width=True)

    # ── (2) 월별 이용량 (최근 3년)
    with c2:
        sub = df_usage[df_usage["permit_no"] == permit_no].copy()
        if not sub.empty and "year" in sub.columns:
            yr_max = int(sub["year"].max())
            sub = sub[sub["year"] >= yr_max - monthly_n_years + 1]
        sub = sub.dropna(subset=["volume_m3"]).sort_values(["year", "month"])

        if sub.empty:
            st.caption(f"월별 이용량 (최근 {monthly_n_years}년): 자료 없음")
        else:
            sub["ym"] = (
                sub["year"].astype(int).astype(str)
                + "-" + sub["month"].astype(int).astype(str).str.zfill(2)
            )
            fig = go.Figure(go.Bar(
                x=sub["ym"], y=sub["volume_m3"],
                marker_color="#548235",
            ))
            fig.update_layout(
                title=f"월별 이용량 — 최근 {monthly_n_years}년 (㎥)",
                title_font_size=15,
                height=210, margin=dict(l=10, r=10, t=30, b=20),
                showlegend=False, plot_bgcolor="white",
            )
            fig.update_xaxes(tickfont=dict(size=12), tickangle=-45)
            fig.update_yaxes(tickfont=dict(size=13))
            st.plotly_chart(fig, use_container_width=True)

    # ── (3) 수질 NO3 — 전체 보유 기간 (~10년) 반기 라인
    with c3:
        sub_q = df_qual[df_qual["permit_no"] == permit_no].copy()
        if (sub_q.empty
                or "nitrate_n" not in sub_q.columns
                or sub_q["nitrate_n"].notna().sum() == 0):
            st.caption("수질 NO3: 자료 없음")
        else:
            sub_q = sub_q.dropna(subset=["nitrate_n"]).sort_values(["year", "half"])
            sub_q["xlab"] = (
                sub_q["year"].astype(str) + "-" + sub_q["half"].astype(str)
            )
            fig = go.Figure(go.Scatter(
                x=sub_q["xlab"], y=sub_q["nitrate_n"],
                mode="lines+markers", line=dict(color=theme.COLOR_ACCENT_DARKRED, width=2),
                marker=dict(size=6),
            ))
            std = config.WATER_QUALITY_STANDARDS["nitrate_n"].get("max")
            if std is not None:
                fig.add_hline(y=std, line_dash="dot", line_color=theme.COLOR_TEXT_TERTIARY,
                              annotation_text=f"기준 ≤ {std}",
                              annotation_font_size=13)
            fig.update_layout(
                title="수질 NO3 — 보유 기간 전체 (mg/L)",
                title_font_size=15,
                height=210, margin=dict(l=10, r=10, t=30, b=20),
                showlegend=False, plot_bgcolor="white",
            )
            fig.update_xaxes(tickfont=dict(size=12), tickangle=-45)
            fig.update_yaxes(tickfont=dict(size=13))
            st.plotly_chart(fig, use_container_width=True)
