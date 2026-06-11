# ==============================================================================
#  파일명: src/dashboard/tabs/tab03_gwlevel.py
#  탭: ③ 지하수위 분석  —  Build 1.0 Final
# ==============================================================================

import logging

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px

import config
from src.analysis import watershed_mapper, effective_rainfall, anomaly_detection
# 🆕 (2026-06-11) 로버스트-베이지안: 부분월 D(Biweight) 잠정치 계산용
from src.analysis import robust_aggregator
from src.collectors import gwlevel_parser
from src.dashboard import theme
# 🆕 (2026-06-11) F 표시·산정방식 비교표·설명 PDF 버튼 공용 헬퍼
from src.dashboard.tabs import _robust_helpers as rb
from plotly.subplots import make_subplots

# 🆕 (2026-06-06 Stage 2 M6) 표준 로거 — st.caption 사용자 알림과 병행해
# 운영자가 traceback 으로 원인을 추적할 수 있도록 logger.exception 추가.
logger = logging.getLogger(__name__)


def _short(y, m): return f"{str(y)[2:]}년 {m}월"


@st.cache_data(ttl=600)
def _load_station_data_cached():
    """개별 관측정 CSV 전체를 로드 후 연월 컬럼으로 정리."""
    df = gwlevel_parser.load_all_station_data()
    if df.empty or "연월" not in df.columns:
        return pd.DataFrame()
    return df


@st.cache_data(ttl=600)
def _load_ws_to_stations_cached():
    try:
        return watershed_mapper.get_watershed_to_stations_map()
    except Exception:
        return {}


# 관측정별 색상 팔레트 (qualitative, 모두 #hex 형식) —
# 바 차트와 추이 차트에서 동일한 매핑을 사용해 시각적 일관성 유지.
_STATION_PALETTE = (
    px.colors.qualitative.Plotly + px.colors.qualitative.Dark24
)


# ==============================================================================
@st.fragment
def render(ws_data_all: dict, periods: dict, asos_df=None,
           robust_dict: "dict | None" = None):
    """지하수위 분석 탭.

    @st.fragment: 유역 라디오(`tab3_ws_radio`) 변경 시 fragment-only rerun
    → 다른 탭에 영향 없고 화면 transient 깜박임 최소화.

    🆕 (2026-06-11) 유역별 편차 = 로버스트-베이지안(F) 사전계산 캐시값.
    부분월(M partial)은 D(Tukey Biweight) 잠정치 실시간 계산. 캐시 미존재 시
    현행 단순평균(REF) 폴백 + "현행" 배지. 하단에 REF·A~F 비교표 + 설명 PDF.

    Parameters
    ----------
    robust_dict : dict, optional
        app.py 가 전달한 robust_aggregator.build_period_dict_cached 결과.
    """
    if not ws_data_all:
        st.warning("⚠️ 지하수위 데이터 없음. **⚙️ 데이터 관리** 탭에서 처리하세요.")
        return

    # ── 다중 컬럼 동시 이상으로 drop 된 행 요약 (parser 가 채움)
    _dropped = gwlevel_parser.get_last_dropped_summary()
    if _dropped:
        _caption_body = anomaly_detection.format_gwlevel_dropped_caption(_dropped)
        st.caption(
            f"⚠ 기기 이상으로 제외 {len(_dropped)}건 — {_caption_body}"
        )

    # ── (최상단) 유역별 편차 3-패널: M-2 · M-1 · M ───────────
    _render_diff_bar_row(ws_data_all, periods, robust_dict=robust_dict)

    st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

    # ── 유역 선택 (st.radio horizontal — deselect/탭 튕김 이슈 없음) ─
    ws_names = [w["name"] for w in config.WATERSHEDS]
    ws_color = {w["name"]: w["color"] for w in config.WATERSHEDS}

    if "tab3_ws_radio" not in st.session_state:
        st.session_state["tab3_ws_radio"] = ws_names[0]

    sel = st.radio(
        "유역 선택",
        options=ws_names,
        horizontal=True,
        key="tab3_ws_radio",
        label_visibility="collapsed",
    )
    st.session_state["tab3_ws"] = sel
    ws_col = ws_color.get(sel, theme.COLOR_TEXT_INFO)
    ws_df  = ws_data_all.get(sel, pd.DataFrame())
    n_gw   = config.GWLEVEL_BASELINE_YEARS

    ps_keys = ["M-2", "M-1", "M"]
    ps      = [periods[k] for k in ps_keys]
    # X축 라벨 축약
    xlabels = [f"{p['month']}월 ({k})" for k, p in zip(ps_keys, ps)]
    # 하단 캡션용 기간 목록
    # 🆕 (2026-06-06 v3 사용자 요청) partial M 에 "(~5일)" 명시
    def _p_lbl4(p):
        s = f"{str(p['year'])[2:]}년 {p['month']}월"
        if p.get("partial"):
            s += f"(~{p['end_date'].day}일)"
        return s
    def _bl_gw4(p):
        s = f"{str(p['year']-n_gw)[2:]}~{str(p['year']-1)[2:]}년 {p['month']}월"
        if p.get("partial"):
            s += f"(~{p['end_date'].day}일)"
        return s
    recent_months = ", ".join(_p_lbl4(p) for p in ps)
    baseline_gw_str = ", ".join(_bl_gw4(p) for p in ps)
    # 차트 범례용 (M-2 baseline 기준)
    _p0 = ps[0]
    _bl0 = list(range(_p0["year"] - n_gw, _p0["year"]))
    yr_g_short = f"{str(_bl0[0])[2:]}~{str(_bl0[-1])[2:]}"

    # ── M-2·M-1·M 요약 카드 (기존 HTML .card) ────────────────
    card_cols = st.columns(3)
    rows_data = []
    # 🆕 (2026-06-06 v2 자료5팀 권고) partial M 슬롯은 일자료 직접 계산 — 단위 일치
    # actual·baseline 둘 다 부분월(1~D-1) 동일 윈도우 비교로 거짓 라벨 제거
    base_date_for_partial = periods.get("base_date")
    for i, (pk, p) in enumerate(zip(ps_keys, ps)):
        ym = f"{p['year']}-{p['month']:02d}"
        bl = list(range(p["year"] - n_gw, p["year"]))
        actual = avg = None
        partial_robust = None   # 🆕 (2026-06-11) 부분월 D(Biweight) 잠정 편차
        partial_robust_n = 0

        # 🆕 partial M 인 경우 — 일자료 기반 재계산 (자료 정합성 보장)
        if p.get("partial") and pk == "M" and base_date_for_partial is not None:
            try:
                pres = _compute_partial_watershed_values(
                    sel, str(base_date_for_partial), n_gw
                )
                actual = pres.get("actual")
                avg = pres.get("baseline_avg")
                # 자료5팀: n_actual·n_baseline 도 카드에 표기 권장 — 표본수 투명
                p_n_act = pres.get("n_actual", 0)
                p_used_years = pres.get("used_years", [])
                # 🆕 (2026-06-11) 관측소 anomaly → Biweight 잠정 편차
                partial_robust = pres.get("robust_dev")
                partial_robust_n = pres.get("n_robust", 0)
            except Exception:
                # 실패 시 기존 월집계 폴백 (안전)
                if not ws_df.empty:
                    ra = ws_df[ws_df["연월"] == ym]
                    _av = ra["EL_평균"].iloc[0] if not ra.empty else None
                    actual = float(_av) if _av is not None and pd.notna(_av) else None
        else:
            # 기존 월집계 경로 (M-2, M-1, 또는 partial 비활성)
            if not ws_df.empty:
                ra = ws_df[ws_df["연월"] == ym]
                _av = ra["EL_평균"].iloc[0] if not ra.empty else None
                actual = float(_av) if _av is not None and pd.notna(_av) else None
                bv = []
                for y in bl:
                    _sub = ws_df[ws_df["연월"] == f"{y}-{p['month']:02d}"]
                    if not _sub.empty:
                        _v = _sub["EL_평균"].iloc[0]
                        if pd.notna(_v):
                            bv.append(float(_v))
                avg = sum(bv)/len(bv) if bv else None

        # 🆕 (2026-06-11) 편차 표시값 결정 — Hybrid 정책:
        #   완료월 = F(로버스트-베이지안, 캐시) / 부분월 = D(Biweight, 실시간)
        #   캐시·일자료 미존재 시 현행(실측−평균) 폴백 + "현행" 배지.
        raw_diff = round(actual - avg, 2) if (actual is not None and avg is not None) else None
        diff = raw_diff
        diff_src = "REF" if raw_diff is not None else None
        if p.get("partial") and pk == "M":
            if partial_robust is not None:
                diff = round(float(partial_robust), 2)
                diff_src = "D"
        else:
            _res = rb.resolve_dev(
                robust_dict,
                {"편차": raw_diff} if raw_diff is not None else None,
                sel, pk)
            if _res is not None:
                diff = round(_res[0], 2)
                diff_src = _res[3]
        # 🛡️ (2026-06-06 로직1팀 권고) avg ≈ 0 분모 폭발 가드
        pct  = round(diff/avg*100) if (diff is not None and avg is not None
                                        and abs(avg) >= 0.01) else None
        rows_data.append({"pk": pk, "p": p, "actual": actual, "avg": avg,
                           "diff": diff, "pct": pct, "bl": bl,
                           "diff_src": diff_src,
                           "n_robust": partial_robust_n})

        is_m = (pk == "M")

        # 짧은 연도
        yr_gw_s = f"{str(bl[0])[2:]}~{str(bl[-1])[2:]}"

        gw_str = f"{actual:.2f} m" if actual is not None else "–"
        gv_str = f"{avg:.2f} m"    if avg    is not None else "–"
        if diff is not None:
            c = theme.COLOR_SUCCESS if diff >= 0 else theme.COLOR_DANGER
            sg = "+" if diff >= 0 else ""
            # 🆕 (2026-06-11) 출처 미니 배지 — F(RB)/D(잠정·RB)/REF(현행)
            diff_html = (f'<span style="color:{c};font-weight:500;">{sg}{diff:.2f}m</span>'
                         + rb.src_badge_html(diff_src or ""))
        else:
            diff_html = '<span style="color:#999;">-</span>'

        # ⑧ 통계 헬퍼 적용 (사용자 결정 2026-05-09)
        #   title = "2025년 10월 (M-2)", 그룹 1개 = 지하수위. is_base 로 M(진함)/M-2,M-1(연함) 구분.
        # 🆕 (2026-06-06) partial 시 M 카드만 라벨에 "(1~Nday 일별 N=N)" 부연.
        # 🆕 (2026-06-06 v3 자료2팀 권고) sub 라인에 N_일·N_baseline 표본수 표기
        # 🆕 (2026-06-06 v3) 라벨 단축 — 글자 길이 줄임
        is_partial = p.get("partial", False)
        partial_tag = (f" (~{p['end_date'].day}일 평균, N={p['n_days']})"
                       if is_partial else "")
        # partial 모드면 sub 라인에 표본수 표기 — 사용자가 신뢰도 인지
        # 🆕 (2026-06-06 v3) "1~N일" → "~N일" 단축
        if is_partial and pk == "M":
            try:
                _n_act = p_n_act if 'p_n_act' in locals() else 0
                _used_yrs = p_used_years if 'p_used_years' in locals() else []
                _baseline_n_str = (f", baseline {len(_used_yrs)}년"
                                    if _used_yrs else "")
                _sample_html = (
                    f'<span style="color:var(--color-text-secondary);'
                    f'font-size:11px;">N_일={_n_act}{_baseline_n_str}</span>'
                )
            except Exception:
                _sample_html = ""
            sub_main = (
                f"{gv_str} ({yr_gw_s}년 ~{p['end_date'].day}일 평균) "
                f"&nbsp;|&nbsp; 편차 {diff_html} "
                f"&nbsp;|&nbsp; {_sample_html}"
            )
        else:
            sub_main = (
                f"{gv_str} ({yr_gw_s}년 {p['month']}월 평균) "
                f"&nbsp;|&nbsp; 편차 {diff_html}"
            )
        groups = [
            (
                f"지하수위 ({sel}){partial_tag}",
                gw_str,
                sub_main,
            ),
        ]
        card_title = f"{p['year']}년 {p['month']}월 ({pk})"
        if is_partial:
            # 🆕 (2026-06-06 v3 사용자 요청) "1~5일" → "~5일"
            card_title = f"{p['year']}년 {p['month']}월(~{p['end_date'].day}일) ({pk})"
        theme.render_period_kpi_card(
            title=card_title,
            groups=groups,
            accent=ws_col,
            is_base=is_m,
            container=card_cols[i],
        )

    # 🆕 (2026-06-06 자료2팀 권고) partial 모드 시 자료 품질 안내
    # (2026-06-11 검증1팀) Biweight 잠정치 가용 여부에 따라 문구 분기 —
    # 일자료 미존재 폴백(현행 평균) 시 배너가 거짓 설명하지 않도록.
    _m_row = next((r for r in rows_data if r["pk"] == "M"), None)
    _m_is_biweight = bool(_m_row and _m_row.get("diff_src") == "D")
    if periods["M"].get("partial") and not _m_is_biweight:
        st.markdown(
            '<p style="font-size:13px;color:var(--color-text-secondary);'
            'margin:6px 0 0;padding:6px 10px;background:rgba(250,200,80,0.08);'
            'border-left:3px solid rgba(250,200,80,0.6);border-radius:3px;">'
            'ℹ️ M 슬롯 (부분월) 은 일자료 미가용으로 <b>현행 평균 기반 '
            '폴백값</b>이 표시 중입니다. ⚙️ 데이터 관리 탭에서 일자료 수집 후 '
            '로버스트 잠정치로 자동 전환됩니다.'
            '</p>',
            unsafe_allow_html=True
        )
    elif periods["M"].get("partial"):
        st.markdown(
            '<p style="font-size:13px;color:var(--color-text-secondary);'
            'margin:6px 0 0;padding:6px 10px;background:rgba(250,200,80,0.08);'
            'border-left:3px solid rgba(250,200,80,0.6);border-radius:3px;">'
            'ℹ️ M 슬롯 (부분월) 의 수위·평균은 원본 일자료 평균, '
            '<b>편차는 로버스트(Tukey Biweight) 잠정치</b>입니다 — 관측소별 '
            'anomaly(자기 3년 동기간 대비) 를 Biweight 로 집계해 결측·이상 '
            '관측소 영향을 차단합니다. 월 마감 후 로버스트-베이지안 메타분석(F) '
            '확정값으로 대체됩니다. ⚙️ 데이터 관리 탭에서 표본수(N) 확인 가능.'
            '</p>',
            unsafe_allow_html=True
        )

    st.markdown("<div style='height:12px;'></div>", unsafe_allow_html=True)

    # ── M-2·M-1·M 막대 차트 (유역별 현황 탭과 동일 포맷) ────
    lbl_avg = f"과거 {n_gw}년 해당월 평균"
    lbl_act = "최근 지하수위"
    st.markdown(
        f'<p class="section-title" style="margin:0 0 4px;">지하수위(EL)</p>'
        f'<div style="font-size:15px;color:var(--color-text-secondary);margin:0 0 4px;">'
        f'<span style="display:inline-flex;align-items:center;gap:4px;margin-right:14px;">'
        f'<span style="width:10px;height:10px;border-radius:2px;border:1.5px solid {ws_col};display:inline-block;"></span>'
        f'{lbl_avg}</span>'
        f'<span style="display:inline-flex;align-items:center;gap:4px;">'
        f'<span style="width:10px;height:10px;border-radius:2px;background:{ws_col};display:inline-block;"></span>'
        f'{lbl_act}</span>'
        f'</div>',
        unsafe_allow_html=True
    )
    act_v = [r["actual"] for r in rows_data]
    avg_v = [r["avg"]    for r in rows_data]
    all_v = [v for v in act_v + avg_v if v is not None]
    y_min = min(all_v) * 0.96 if all_v else 0

    def _fmt2(v):
        return "" if v is None else f"{v:.2f}"

    fig = go.Figure()
    fig.add_trace(go.Bar(
        name=lbl_avg, x=xlabels, y=avg_v,
        marker=dict(color=theme.hex_alpha(ws_col, 0.18), line=dict(color=ws_col, width=1.5)),
        text=[_fmt2(v) for v in avg_v],
        textposition="outside",
        textfont=dict(size=14, color=theme.COLOR_TEXT_SECONDARY),
        cliponaxis=False,
        hovertemplate=f"%{{x}}<br>{lbl_avg}: %{{y:.2f}} m<extra></extra>",
    ))
    fig.add_trace(go.Bar(
        name=lbl_act, x=xlabels, y=act_v,
        marker=dict(color=ws_col),
        text=[_fmt2(v) for v in act_v],
        textposition="outside",
        textfont=dict(size=14, color=theme.COLOR_TEXT_PRIMARY),
        cliponaxis=False,
        hovertemplate=f"%{{x}}<br>{lbl_act}: %{{y:.2f}} m<extra></extra>",
    ))
    # tab1 의 _grouped_bar 와 동일한 layout (height=220, margin l=38)
    fig.update_layout(
        barmode="group", height=220,
        xaxis_title="", yaxis_title="m",
        xaxis=dict(tickfont=dict(size=15)),
        yaxis=dict(range=[y_min, None]),
        bargap=0.35, bargroupgap=0.18,
        margin=dict(t=14, b=4, l=38, r=8),
        showlegend=False, font=dict(size=14),
    )
    st.plotly_chart(fig, use_container_width=True, key=f"t3_bar_{sel}")

    st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

    # 🆕 (2026-06-06) M 슬롯이 partial 일 때만 — 일별 라인 차트 (유역 평균)
    m_p_part = periods["M"]
    if m_p_part.get("partial") and periods.get("base_date") is not None:
        # 🆕 (2026-06-06 v9 사용자 요청) inline font-size 22px 명시 — 01~04탭 일별
        #   차트 제목 통일. 연간 강수량 분석 제목과 같은 크기.
        st.markdown(
            f'<p class="section-title" '
            f'style="margin:0 0 4px;font-size:22px !important;'
            f'font-weight:700;line-height:1.2;">'
            f'M({m_p_part["short_label"]}) — {sel}유역 일별 지하수위 추이 '
            f'(N={m_p_part["n_days"]}일)</p>'
            f'<p style="font-size:13px;color:var(--color-text-secondary);margin:0 0 6px;">'
            f'* 유역 내 관측정 일자료 평균 (by_station_day). 자동수집(water.jeju API) 으로 D-1 까지 가용.</p>',
            unsafe_allow_html=True
        )
        _render_watershed_partial_daily(sel, periods["base_date"], ws_col)
        st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)

    # ── 상세 비교표 (유역별 현황 탭의 '지하수위(EL) 현황' 표와 동일 포맷) ─
    st.markdown(
        f'<p class="section-title" style="margin:0;">'
        f'지하수위(EL) 현황 : {sel}유역 — 로버스트-베이지안 메타분석</p>',
        unsafe_allow_html=True
    )
    st.markdown("<div style='height:4px;'></div>", unsafe_allow_html=True)
    _render_detail_table(rows_data)
    st.markdown(
        f'<p style="font-size:14px;color:var(--color-text-secondary);margin:4px 0 0;">'
        f'* 최근 월 수위 : {recent_months}'
        f' &nbsp;|&nbsp; 과거 {n_gw}년 해당월 : {baseline_gw_str}</p>',
        unsafe_allow_html=True
    )

    st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)

    # ── 유역 지하수위 추이 차트 (월별, 상세표 이후) ──────────
    # Build 1.1 (2026-05-09): HTML section-title 과 Plotly iframe 이 같은 좌표를
    # 점유해 fragment-only rerun 시 잔상이 남는 문제 → Plotly 차트의 title 로
    # 통합해 단일 entity 로 렌더.
    if not ws_df.empty:
        plot_df = ws_df.copy()
        if len(plot_df) > 60:
            plot_df = plot_df.tail(60)
        fig2 = go.Figure()
        fig2.add_trace(go.Scatter(
            x=plot_df["연월"], y=plot_df["EL_평균"],
            mode="lines+markers",
            line=dict(color=ws_col, width=2),
            marker=dict(size=4),
            hovertemplate="%{x}<br>EL: %{y:.2f} m<extra></extra>",
        ))
        m_ym = f"{periods['M']['year']}-{periods['M']['month']:02d}"
        m_row = plot_df[plot_df["연월"] == m_ym]
        if not m_row.empty:
            fig2.add_trace(go.Scatter(
                x=m_row["연월"], y=m_row["EL_평균"],
                mode="markers+text",
                marker=dict(color=theme.COLOR_DANGER, size=10, line=dict(color="white", width=2)),
                text=["M"], textposition="top center",
                textfont=dict(color=theme.COLOR_DANGER, size=14),
                showlegend=False,
                hovertemplate="M 기간<br>%{x}<br>EL: %{y:.2f} m<extra></extra>",
            ))
        fig2.update_layout(
            height=300, xaxis_title="", yaxis_title="지하수위 EL (m)",
            title=dict(
                text=f"지하수위(EL) 추이 : {sel} 유역",
                x=0.0, xanchor="left",
                font=dict(size=20, color=theme.COLOR_TEXT_PRIMARY),
                pad=dict(t=2, b=4),
            ),
            margin=dict(t=40, b=8, l=50, r=10),
            showlegend=False, font=dict(size=14),
        )
        st.plotly_chart(fig2, use_container_width=True, key=f"t3_trend_{sel}")

    st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)

    # ── 유역 내 관측정별 지하수위 (차트 + 표) ────────────────
    _render_stations_section(sel, ws_col, periods, ps_keys, ps, n_gw, asos_df,
                              recent_months, baseline_gw_str)

    # ── 🆕 (2026-06-11 사용자 요청) 하단 — 산정방식 비교표 (REF·A~F)
    #    + 로버스트-베이지안 설명 PDF chip 버튼 (pdf_server :8766 새 탭)
    st.divider()
    rb.render_method_comparison(robust_dict, periods, key_prefix="t3")


# ==============================================================================
#  ■ 🆕 (2026-06-06 v2) partial 모드 일자료 기반 actual/baseline 계산
#     자료 검증 5팀 발견: tab04 카드의 actual 은 ws_df 월전체값을 그대로 쓰면서
#     라벨엔 "1~Nday 평균" 표기 → 거짓 라벨. partial 모드 시 일자료에서 직접
#     계산해야 단위 일치 + 사용자 라벨 정합.
# ==============================================================================
# 🚀 (2026-06-06 v3 성능 개선)
#   기존: _compute_partial_watershed_values 가 유역별 16번 호출 → parquet 16번 로드.
#   신규: _compute_all_partial_watersheds 가 한 번에 16개 유역 모두 계산. parquet
#         1회 로드 + 유역 매핑 1회 + groupby 1회. 캐시 키 1개로 통합.
#   효과: 첫 진입 ~20초 → ~5초 단축 예상.
@st.cache_data(ttl=600, show_spinner=False, max_entries=4)
def _compute_all_partial_watersheds(base_date_str: str,
                                     n_years: int) -> dict:
    """🚀 (2026-06-06 v3) 모든 유역의 partial 값 한 번에 계산.

    Returns
    -------
    dict {유역명: {actual, baseline_avg, n_actual, used_years, n_baseline, err}}
    """
    from datetime import date as _date
    import pandas as _pd
    out: dict = {}
    try:
        base_date = _pd.to_datetime(base_date_str).date()
    except Exception:
        return out
    if base_date.day < 2:
        return out

    try:
        from src.collectors import gwlevel_day_parser
        from src.analysis import watershed_mapper
    except Exception:
        return out

    try:
        station_map = watershed_mapper.load_station_to_watershed_map(verbose=False)
    except Exception:
        return out
    if not station_map:
        return out

    # parquet 1회 로드 (가장 비용 큰 작업)
    try:
        pq_path = gwlevel_day_parser.GWLEVEL_DAY_PARQUET
        if not pq_path.exists():
            return out
        all_df = _pd.read_parquet(pq_path)
    except Exception:
        return out
    required = {"관측소명", "날짜", "EL"}
    if not required.issubset(set(all_df.columns)):
        return out

    # 전처리 1회
    all_df = all_df.copy()
    all_df["날짜"] = _pd.to_datetime(all_df["날짜"], errors="coerce")
    all_df = all_df.dropna(subset=["날짜", "EL"])
    all_df["station_ws"] = all_df["관측소명"].map(station_map)

    end_day = base_date.day - 1
    target_month = base_date.month
    baseline_years = list(range(base_date.year - n_years, base_date.year))

    # 🆕 (2026-06-11) 관측소별 부분월 anomaly → 유역 Biweight(D) 잠정 편차.
    #   유역 평균(관측소 구성 변화에 취약) 대신 자기 baseline 대비 변화량을
    #   로버스트 집계 — N_drop·이상치 왜곡 차단 (검토보고서 V2 Hybrid 정책).
    try:
        from src.analysis import robust_aggregator as _ra
        _robust_map = _ra.partial_month_biweight(
            all_df, station_map, base_date, n_years)
    except Exception:
        _robust_map = {}

    # 같은 월·day<=end_day 마스크 1회 (모든 연도 포함)
    month_day_mask = ((all_df["날짜"].dt.month == target_month)
                      & (all_df["날짜"].dt.day <= end_day))
    masked = all_df[month_day_mask]

    # 유역별로 그룹핑
    for ws_name in set(station_map.values()):
        ws_df = masked[masked["station_ws"] == ws_name]
        _rb_rec = _robust_map.get(ws_name) or {}
        if ws_df.empty:
            out[ws_name] = {"actual": None, "baseline_avg": None,
                             "n_actual": 0, "used_years": [], "n_baseline": 0,
                             "robust_dev": _rb_rec.get("dev"),
                             "n_robust": _rb_rec.get("n", 0),
                             "err": None}
            continue

        # actual: 현재 연도
        cur = ws_df[ws_df["날짜"].dt.year == base_date.year]
        actual = None
        n_actual = 0
        if not cur.empty:
            daily_avg = cur.groupby(cur["날짜"].dt.date)["EL"].mean()
            if len(daily_avg) > 0:
                actual = float(daily_avg.mean())
                n_actual = int(len(daily_avg))

        # baseline: 과거 N년
        yearly_means = []
        used_years = []
        n_baseline = 0
        for y in baseline_years:
            y_df = ws_df[ws_df["날짜"].dt.year == y]
            if y_df.empty:
                continue
            daily = y_df.groupby(y_df["날짜"].dt.date)["EL"].mean()
            if len(daily) == 0:
                continue
            yearly_means.append(float(daily.mean()))
            used_years.append(y)
            n_baseline += int(len(daily))
        baseline_avg = (float(sum(yearly_means) / len(yearly_means))
                        if yearly_means else None)

        out[ws_name] = {
            "actual": actual,
            "baseline_avg": baseline_avg,
            "n_actual": n_actual,
            "used_years": used_years,
            "n_baseline": n_baseline,
            # 🆕 (2026-06-11) 로버스트(D Biweight) 잠정 편차 + 표본 관측소 수
            "robust_dev": _rb_rec.get("dev"),
            "n_robust": _rb_rec.get("n", 0),
            "err": None,
        }

    return out


def _compute_partial_watershed_values(sel_watershed: str, base_date_str: str,
                                       n_years: int) -> dict:
    """🚀 (2026-06-06 v3 성능 개선) 일괄 함수에서 lookup만.
    원래 16번 호출되며 parquet 도 16번 로드되던 것을 1번으로 단축.

    Parameters
    ----------
    sel_watershed : str — 유역명 (예: "구좌")
    base_date_str : str — 분석 기준일 (YYYY-MM-DD), 캐시 키용
    n_years       : int — baseline 연도 수

    Returns
    -------
    dict — _compute_all_partial_watersheds 의 해당 유역 항목.
    """
    all_results = _compute_all_partial_watersheds(base_date_str, n_years)
    return all_results.get(sel_watershed, {
        "actual": None, "baseline_avg": None, "n_actual": 0,
        "used_years": [], "n_baseline": 0,
        "robust_dev": None, "n_robust": 0,
        "err": f"{sel_watershed} 유역 결과 없음"
    })


# 🆕 (2026-06-06 v3) 미사용 본문 — 일괄 함수가 본 작업 대체.
# 아래 함수는 원본 보존용 (호출처 없음). 향후 PR 에서 완전 제거 예정.
def _DEPRECATED_compute_partial_watershed_values_orig(sel_watershed, base_date_str, n_years):
    """Legacy 함수 — 호출 시 즉시 동일 결과 반환 (안전한 본문)."""
    return _compute_partial_watershed_values(sel_watershed, base_date_str, n_years)


# (아래 dead-code 는 향후 PR 에서 정리 — 들여쓰기 오류 방지용 주석 처리 영역)
def _DEPRECATED_unused_block_below() -> dict:
    """이 함수는 dead-code 보호용. 원래 _compute_partial_watershed_values 본문이
    바로 아래에 이어졌지만 _compute_all_partial_watersheds 로 대체됨.
    아래 코드 블록은 무의미하게 실행되지 않지만 syntax 유지 위해 본 wrapper 안에 둠."""
    result = {"actual": None, "baseline_avg": None, "n_actual": 0,
              "used_years": [], "n_baseline": 0, "err": None}
    try:
        base_date = _pd.to_datetime(base_date_str).date()
    except Exception as e:
        result["err"] = f"base_date 파싱 실패: {e}"
        return result
    if base_date.day < 2:
        result["err"] = "base_date.day < 2 (partial 의미 없음)"
        return result

    try:
        from src.collectors import gwlevel_day_parser
        from src.analysis import watershed_mapper
    except Exception as e:
        result["err"] = f"모듈 import 실패: {type(e).__name__}: {e}"
        return result

    # 유역 ↔ 관측정 매핑
    try:
        station_map = watershed_mapper.load_station_to_watershed_map(verbose=False)
    except Exception as e:
        result["err"] = f"매핑 로드 실패: {type(e).__name__}: {e}"
        return result
    stations_in_ws = [s for s, w in station_map.items() if w == sel_watershed]
    if not stations_in_ws:
        result["err"] = f"{sel_watershed} 유역 관측정 0건"
        return result

    # 일자료 parquet 로드
    try:
        pq_path = gwlevel_day_parser.GWLEVEL_DAY_PARQUET
        if not pq_path.exists():
            result["err"] = "parquet 미생성"
            return result
        all_df = _pd.read_parquet(pq_path)
    except Exception as e:
        result["err"] = f"parquet 로드 실패: {type(e).__name__}: {e}"
        return result
    required = {"관측소명", "날짜", "EL"}
    if not required.issubset(set(all_df.columns)):
        result["err"] = f"parquet 컬럼 누락: {sorted(required - set(all_df.columns))}"
        return result

    # 유역 내 관측정 + 같은 월·1~D-1 (연도 무관) 필터
    df = all_df[all_df["관측소명"].isin(stations_in_ws)].copy()
    df["날짜"] = _pd.to_datetime(df["날짜"], errors="coerce")
    df = df.dropna(subset=["날짜"])
    df = df.dropna(subset=["EL"])  # 결측 EL 제외
    end_day = base_date.day - 1
    target_month = base_date.month

    # actual: 같은 연도의 1~end_day
    cur_df = df[(df["날짜"].dt.year == base_date.year)
                & (df["날짜"].dt.month == target_month)
                & (df["날짜"].dt.day <= end_day)]
    if not cur_df.empty:
        # 일별 유역 평균 → 그 평균
        daily_avg = cur_df.groupby(cur_df["날짜"].dt.date)["EL"].mean()
        if len(daily_avg) > 0:
            result["actual"] = float(daily_avg.mean())
            result["n_actual"] = int(len(daily_avg))

    # baseline: 과거 N년의 같은 월·1~end_day
    baseline_years = list(range(base_date.year - n_years, base_date.year))
    yearly_means = []
    used_years = []
    n_baseline = 0
    for y in baseline_years:
        y_df = df[(df["날짜"].dt.year == y)
                  & (df["날짜"].dt.month == target_month)
                  & (df["날짜"].dt.day <= end_day)]
        if y_df.empty:
            continue
        daily = y_df.groupby(y_df["날짜"].dt.date)["EL"].mean()
        if len(daily) == 0:
            continue
        yearly_means.append(float(daily.mean()))
        used_years.append(y)
        n_baseline += int(len(daily))
    if yearly_means:
        result["baseline_avg"] = float(sum(yearly_means) / len(yearly_means))
        result["used_years"] = used_years
        result["n_baseline"] = n_baseline

    return result


# ==============================================================================
#  ■ 🆕 (2026-06-06) M 슬롯 부분월(1~D-1) — 유역 평균 일별 라인 차트
#     by_station_day/{관측소}.csv 를 유역별로 묶어 일별 평균 EL 표시.
#     사용자 요청: tab03/04/05 의 M 슬롯만 D-1 일별 분석.
# ==============================================================================
def _render_watershed_partial_daily(sel: str, base_date, ws_color: str):
    """선택된 유역 내 관측정들의 1~D-1 일별 평균 EL 라인 차트.

    Parameters
    ----------
    sel       : str - 유역명 (예: "구좌")
    base_date : datetime.date - 분석 기준일. 1~(base_date.day-1) 일자 표시.
    ws_color  : str - 라인 색상 (유역 컬러)
    """
    if base_date is None or base_date.day < 2:
        st.caption(f"⚠ 분석 기준일({base_date}) 이 매월 1일이라 부분월 표시 불가")
        return
    try:
        from src.collectors import gwlevel_day_parser
        from src.analysis import watershed_mapper
    except Exception as e:  # noqa: BLE001
        # 🆕 (2026-06-06 Stage 2 M6) logger.exception 병행 — 운영자 진단용 traceback
        logger.exception("_render_watershed_partial_daily: 모듈 import 실패")
        st.caption(f"⚠ 모듈 로드 실패: {type(e).__name__}: {e}")
        return

    try:
        station_map = watershed_mapper.load_station_to_watershed_map(verbose=False)
    except Exception:
        station_map = {}
    stations_in_ws = [s for s, w in station_map.items() if w == sel]
    if not stations_in_ws:
        st.caption(f"⚠ {sel}유역 관측정 매핑 없음 — watershed_mapper 점검 필요")
        return

    # 일자료 통합 로드 — gwlevel_day_parser 의 캐시된 parquet 직접 읽기
    try:
        parquet_path = gwlevel_day_parser.GWLEVEL_DAY_PARQUET
        if not parquet_path.exists():
            st.caption("⚠ 일자료 parquet 없음 — ⚙️ 데이터 관리 탭의 "
                       "'🔄 지금 모두 업데이트' 실행 권장")
            return
        all_df = pd.read_parquet(parquet_path)
    except ImportError:
        # pyarrow 미설치는 환경 문제 — traceback 불필요, warning 만 기록.
        logger.warning("_render_watershed_partial_daily: pyarrow 미설치")
        st.caption("⚠ pyarrow 미설치 — `pip install pyarrow` 권장")
        return
    except Exception as e:  # noqa: BLE001
        # 🆕 (2026-06-06 Stage 2 M6) logger.exception 병행 — parquet 로드 실패 진단
        logger.exception("_render_watershed_partial_daily: parquet 로드 실패: %s", parquet_path)
        st.caption(f"⚠ 일자료 로드 실패: {type(e).__name__}: {e}")
        return
    if all_df is None or all_df.empty:
        st.caption("⚠ 일자료 비어있음")
        return

    # 🛡️ (2026-06-06 자료2팀 권고) parquet schema 검증 — 컬럼 누락 시 KeyError 방지
    required_cols = {"관측소명", "날짜", "EL"}
    missing_cols = required_cols - set(all_df.columns)
    if missing_cols:
        st.caption(f"⚠ 일자료 parquet 컬럼 누락: {sorted(missing_cols)} "
                   "— ⚙️ 데이터 관리 탭에서 parquet 재생성 권장")
        return

    # 유역 내 관측정 + base_date 의 같은 월·1~D-1 필터
    df = all_df[all_df["관측소명"].isin(stations_in_ws)].copy()
    if df.empty:
        st.caption(f"⚠ {sel}유역의 일자료 0건")
        return
    df["날짜"] = pd.to_datetime(df["날짜"], errors="coerce")
    df = df.dropna(subset=["날짜"])
    end_day = base_date.day - 1
    df = df[(df["날짜"].dt.year == base_date.year)
            & (df["날짜"].dt.month == base_date.month)
            & (df["날짜"].dt.day <= end_day)].copy()
    if df.empty:
        st.caption(f"⚠ {sel}유역의 {base_date.year}-{base_date.month:02d}-01~"
                   f"{end_day:02d} 일자료 0건 — ⚙️ 데이터 관리 탭에서 수집")
        return

    # 일별 유역 평균 (관측정 평균)
    daily = (df.groupby(df["날짜"].dt.day)["EL"]
               .mean().reset_index().rename(columns={"날짜": "일",
                                                     "EL": "EL_평균"}))
    daily = daily.sort_values("일")

    # 🛡️ (2026-06-06 자료2팀 권고) 결측일 사용자 인지 — 예상 일수와 실제 데이터 비교
    expected_days = set(range(1, end_day + 1))
    actual_days = set(daily["일"].tolist())
    missing_days = sorted(expected_days - actual_days)
    if missing_days:
        st.caption(
            f"ℹ️ 자료 결측일: {missing_days} "
            f"({len(actual_days)}/{end_day}일 표시)"
        )

    # 라인 차트
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=daily["일"].astype(str).tolist(),
        y=daily["EL_평균"].round(2).tolist(),
        mode="lines+markers+text",
        line=dict(color=ws_color, width=2.5),
        marker=dict(size=8, color=ws_color),
        text=[f"{v:.2f}" for v in daily["EL_평균"]],
        textposition="top center",
        textfont=dict(size=11, color=theme.COLOR_TEXT_PRIMARY),
        hovertemplate=f"{base_date.month}월 %{{x}}일<br>EL: %{{y:.2f}} m<extra></extra>",
        cliponaxis=False,
    ))
    fig.update_layout(
        height=240,
        plot_bgcolor="white",
        xaxis=dict(title=f"{base_date.month}월 일자", type="category",
                   tickfont=dict(size=14)),
        yaxis=dict(title="EL (m)"),
        margin=dict(l=38, r=8, t=14, b=4),
        showlegend=False,
        font=dict(size=13),
    )
    st.plotly_chart(fig, use_container_width=True,
                    key=f"t4_part_daily_{sel}_{base_date}")


# ==============================================================================
#  ■ 상세 비교표
# ==============================================================================
def _render_detail_table(rows_data):
    """유역별 현황 탭의 _render_gw_table 과 동일한 포맷 (table-layout:fixed,
    13px 글자, 기간 colwidth=360px, colgroup 균등 분배)."""
    n = config.GWLEVEL_BASELINE_YEARS

    colgroup = (
        '<colgroup>'
        '<col style="width:360px;">'
        '<col><col><col>'
        '</colgroup>'
    )
    th_base = (
        'padding:6px 8px;background:var(--color-bg-secondary);text-align:center;'
        'border-bottom:1.5px solid #ccc;'
    )

    head = (
        '<table style="width:100%;border-collapse:collapse;'
        'table-layout:fixed;font-size:16px;">'
        + colgroup
        + '<thead><tr>'
        + f'<th style="{th_base}">기간</th>'
        + f'<th style="{th_base}">최근 월 수위 (m)</th>'
        + f'<th style="{th_base}">과거 {n}년 해당월 평균 (m)</th>'
        + f'<th style="{th_base}">지하수위 편차 (m)</th>'
        + '</tr></thead><tbody>'
    )
    body = ""
    for r in rows_data:
        a = r["actual"]; v = r["avg"]; d = r["diff"]
        _src = r.get("diff_src") or ""
        a_s = (f'<span class="subsection-title">{a:.2f}</span>'
               if a is not None else "–")
        v_s = f"{v:.2f}" if v is not None else "–"
        def _dc(val, src=_src):
            if val is None: return "–"
            c = theme.COLOR_SUCCESS if val >= 0 else theme.COLOR_DANGER
            sg = "+" if val >= 0 else ""
            # 🆕 (2026-06-11) 편차 출처 배지 — F(RB)/D(잠정·RB)/REF(현행)
            return (f'<span style="color:{c};font-weight:500;">{sg}{val}</span>'
                    + rb.src_badge_html(src))
        body += (
            '<tr>'
            f'<td style="padding:6px 8px;border-bottom:0.5px solid #eee;text-align:center;">'
            f'<div style="font-size:16px;font-weight:500;">{r["p"]["month"]}월</div>'
            f'<div style="font-size:15px;color:var(--color-text-secondary);">({r["pk"]})</div>'
            f'</td>'
            f'<td style="padding:6px 8px;border-bottom:0.5px solid #eee;text-align:center;">{a_s}</td>'
            f'<td style="padding:6px 8px;border-bottom:0.5px solid #eee;text-align:center;">{v_s}</td>'
            f'<td style="padding:6px 8px;border-bottom:0.5px solid #eee;text-align:center;">{_dc(d)}</td>'
            '</tr>'
        )
    st.markdown(head + body + "</tbody></table>", unsafe_allow_html=True)


# ==============================================================================
#  ■ 전체 유역 요약표 (기존 HTML gwAllTbl 이식)
# ==============================================================================
def _render_all_table(ws_data_all, periods, ps_keys):
    n = config.GWLEVEL_BASELINE_YEARS
    ps = [periods[k] for k in ps_keys]

    head = '<table style="width:100%;border-collapse:collapse;font-size:16px;"><thead>'
    head += '<tr style="background:var(--color-bg-secondary);">'
    head += '<th style="padding:6px 8px;border-bottom:1.5px solid #ccc;text-align:center;min-width:60px;">유역</th>'
    head += '<th style="padding:6px 8px;border-bottom:1.5px solid #ccc;text-align:center;min-width:48px;">AWS</th>'
    for pk, p in zip(ps_keys, ps):
        head += (
            f'<th style="padding:6px 8px;border-bottom:1.5px solid #ccc;text-align:center;">'
            f'{p["month"]}월<br>'
            f'<span style="font-size:15px;font-weight:400;color:var(--color-text-secondary);">({pk})</span>'
            f'</th>'
        )
    head += '</tr></thead><tbody>'

    body = ""
    ws_aws = {w["name"]: w["aws"] for w in config.WATERSHEDS}
    ws_col = {w["name"]: w["color"] for w in config.WATERSHEDS}

    for w in config.WATERSHEDS:
        wn   = w["name"]
        col  = ws_col[wn]
        df_w = ws_data_all.get(wn, pd.DataFrame())
        row  = (
            f'<tr>'
            f'<td style="padding:6px 8px;border-bottom:0.5px solid #eee;text-align:center;'
            f'color:{col};font-weight:500;">{wn}</td>'
            f'<td style="padding:6px 8px;border-bottom:0.5px solid #eee;text-align:center;'
            f'font-size:15px;color:var(--color-text-secondary);">{ws_aws.get(wn, "")}</td>'
        )
        for pk, p in zip(ps_keys, ps):
            ym = f"{p['year']}-{p['month']:02d}"
            bl = list(range(p["year"] - n, p["year"]))
            actual = avg = None
            if not df_w.empty:
                ra = df_w[df_w["연월"] == ym]
                _av = ra["EL_평균"].iloc[0] if not ra.empty else None
                actual = float(_av) if _av is not None and pd.notna(_av) else None
                bv = []
                for y in bl:
                    _sub = df_w[df_w["연월"] == f"{y}-{p['month']:02d}"]
                    if not _sub.empty:
                        _v = _sub["EL_평균"].iloc[0]
                        if pd.notna(_v):
                            bv.append(float(_v))
                avg = sum(bv)/len(bv) if bv else None
            diff = round(actual - avg, 2) if (actual is not None and avg is not None) else None
            a_s  = f"{actual:.2f}" if actual is not None else "–"
            v_s  = f"({avg:.2f})"  if avg    is not None else ""
            if diff is not None:
                c = theme.COLOR_SUCCESS if diff >= 0 else theme.COLOR_DANGER; sg = "+" if diff >= 0 else ""
                d_s = f'<div style="font-size:15px;color:{c};font-weight:500;">{sg}{diff}</div>'
            else: d_s = ""
            row += (
                f'<td style="padding:6px 8px;border-bottom:0.5px solid #eee;text-align:center;">'
                f'<div style="font-size:16px;font-weight:500;">{a_s}</div>'
                f'<div style="font-size:15px;color:var(--color-text-secondary);">{v_s}</div>'
                f'{d_s}</td>'
            )
        row += "</tr>"
        body += row

    st.markdown(head + body + "</tbody></table>", unsafe_allow_html=True)


# ==============================================================================
#  ■ 편차 막대 차트 — 3-패널 한 줄 (M-2 / M-1 / M)
# ==============================================================================
def _render_diff_bar_row(ws_data_all, periods, robust_dict=None):
    """M-2, M-1, M 세 기간의 유역별 편차 차트를 한 줄에 3개 패널로 렌더링.
    각 바에 편차 숫자 라벨을 부호에 따라 + 는 위쪽 / - 는 아래쪽에 표시.

    🆕 (2026-06-11) 편차 = 로버스트-베이지안(F, 캐시) 우선 + 95% CI error bar.
    부분월(M partial)은 D(Biweight) 잠정치. 둘 다 없으면 현행 단순평균 폴백."""
    n = config.GWLEVEL_BASELINE_YEARS
    ps_keys = ["M-2", "M-1", "M"]
    ps_list = [periods[k] for k in ps_keys]
    ws_col_map = {w["name"]: w["color"] for w in config.WATERSHEDS}
    base_date = periods.get("base_date")

    st.markdown(
        f'<p class="section-title">'
        f'유역별 지하수위(EL) 변동 — 최근 3개월 '
        f'(과거 {n}년 동일월 대비, 로버스트-베이지안(Robust Bayesian) 메타분석)</p>',
        unsafe_allow_html=True
    )

    cols = st.columns(3)
    for col_idx, (pk, p) in enumerate(zip(ps_keys, ps_list)):
        ym = f"{p['year']}-{p['month']:02d}"
        bl = list(range(p["year"] - n, p["year"]))
        is_partial = bool(p.get("partial")) and pk == "M"

        # 부분월 — 일자료 기반 D(Biweight) 잠정치 dict (캐시 함수 1회)
        partial_all = {}
        if is_partial and base_date is not None:
            try:
                partial_all = _compute_all_partial_watersheds(
                    str(base_date), n)
            except Exception:
                partial_all = {}

        names, diffs, colors = [], [], []
        err_plus, err_minus = [], []
        src_used = set()
        for w in config.WATERSHEDS:
            wn = w["name"]
            v = ci = None
            src = None
            if is_partial:
                pres = partial_all.get(wn) or {}
                if pres.get("robust_dev") is not None:
                    v, src = float(pres["robust_dev"]), "D"
                elif (pres.get("actual") is not None
                      and pres.get("baseline_avg") is not None):
                    v, src = pres["actual"] - pres["baseline_avg"], "REF"
            else:
                f_rec = rb.get_f_dev(robust_dict, wn, pk)
                if f_rec is not None and f_rec.get("편차") is not None:
                    v, src = float(f_rec["편차"]), "F"
                    if f_rec.get("ci_low") is not None:
                        ci = (f_rec["ci_low"], f_rec["ci_high"])
            if v is None:
                # 폴백 — 현행 유역 절대수위 단순평균 편차 (기존 로직 보존)
                df_w = ws_data_all.get(wn, pd.DataFrame())
                if df_w.empty or "EL_평균" not in df_w.columns:
                    continue
                ra = df_w[df_w["연월"] == ym]
                if ra.empty or pd.isna(ra["EL_평균"].iloc[0]):
                    continue
                actual = float(ra["EL_평균"].iloc[0])
                bv = []
                for y in bl:
                    _sub = df_w[df_w["연월"] == f"{y}-{p['month']:02d}"]
                    if not _sub.empty and pd.notna(_sub["EL_평균"].iloc[0]):
                        bv.append(float(_sub["EL_평균"].iloc[0]))
                if not bv:
                    continue
                v, src = actual - sum(bv) / len(bv), "REF"
            names.append(wn)
            diffs.append(round(v, 2))
            colors.append(ws_col_map.get(wn, "#888"))
            if ci is not None:
                err_plus.append(max(ci[1] - v, 0.0))
                err_minus.append(max(v - ci[0], 0.0))
            else:
                err_plus.append(0.0)
                err_minus.append(0.0)
            src_used.add(src)

        with cols[col_idx]:
            short_m  = f"{str(p['year'])[2:]}년 {p['month']}월"
            bl_short = f"{str(bl[0])[2:]}~{str(bl[-1])[2:]}"
            # 패널 산정방식 태그 — F(확정)/D(잠정)/현행 혼용 시 우선순위 표기
            # (2026-06-11 v4) F 태그는 섹션 제목과 중복 → 생략.
            # 잠정(D)·현행 폴백일 때만 표기해 사용자 오해 방지.
            if is_partial and "D" in src_used:
                tag = "잠정 · 로버스트(Biweight)"
            elif "F" in src_used:
                tag = ""
            else:
                tag = "현행 단순평균"
            _tag_html = (f' <span style="font-size:13px;font-weight:400;'
                         f'color:var(--color-text-secondary);">— {tag}</span>'
                         if tag else "")
            sub_title = f"{pk} · {short_m}  (기준 {bl_short}년){_tag_html}"
            st.markdown(
                f'<p style="font-size:16px;font-weight:500;color:var(--color-text-primary);margin:0 0 2px;">'
                f'{sub_title}</p>',
                unsafe_allow_html=True
            )
            if not names:
                st.info("데이터 부족")
                continue

            # 편차 라벨: 부호에 따라 위/아래 위치 자동 배치
            text_vals = [f"{'+' if v > 0 else ''}{v:.2f}" for v in diffs]
            _has_ci = any(e > 0 for e in err_plus + err_minus)
            # 양수 바는 '상단(outside)' = 위쪽, 음수 바는 'outside' = 아래쪽 — Plotly 기본 동작
            fig = go.Figure()
            fig.add_trace(go.Bar(
                x=names, y=diffs,
                marker=dict(color=colors, line=dict(color="rgba(255,255,255,1)", width=1)),
                text=text_vals,
                textposition="outside",          # + 위, - 아래 자동
                textfont=dict(size=12, color=theme.COLOR_TEXT_PRIMARY),
                cliponaxis=False,
                # (2026-06-11 v4) CI error bar(레인지 선) 제거 — 사용자 요청.
                #   신뢰구간은 하단 '유역별 산정비교' 표에서 확인.
                hovertemplate="%{x}<br>편차: %{y:.2f} m<extra></extra>",
            ))
            fig.add_hline(y=0, line_dash="dash", line_color="rgba(26,26,24,0.3)", line_width=1)
            fig.update_layout(
                height=280,
                xaxis_title="",
                xaxis=dict(categoryorder="array", categoryarray=names,
                           tickfont=dict(size=14)),
                yaxis_title="편차 (m)",
                yaxis=dict(range=[-5, 5], zeroline=True),
                margin=dict(t=6, b=20, l=40, r=6),
                showlegend=False,
                font=dict(size=14),
            )
            st.plotly_chart(fig, use_container_width=True,
                            key=f"t3_diff_row_{pk}")


# ==============================================================================
#  ■ (legacy) 편차 막대 차트 1-패널 버전 — 참조용, 현재 미사용
# ==============================================================================
def _render_diff_bar(ws_data_all, periods):
    m_p = periods["M"]
    ym  = f"{m_p['year']}-{m_p['month']:02d}"
    n   = config.GWLEVEL_BASELINE_YEARS
    bl  = list(range(m_p["year"] - n, m_p["year"]))

    # 유역 순서대로 (config.WATERSHEDS 순)
    ws_col = {w["name"]: w["color"] for w in config.WATERSHEDS}
    names = []; diffs = []; colors = []
    for w in config.WATERSHEDS:
        wn   = w["name"]
        df_w = ws_data_all.get(wn, pd.DataFrame())
        if df_w.empty or "EL_평균" not in df_w.columns: continue
        ra = df_w[df_w["연월"] == ym]
        if ra.empty: continue
        _av = ra["EL_평균"].iloc[0]
        if pd.isna(_av): continue
        actual = float(_av)
        bv = []
        for y in bl:
            _sub = df_w[df_w["연월"] == f"{y}-{m_p['month']:02d}"]
            if not _sub.empty:
                _v = _sub["EL_평균"].iloc[0]
                if pd.notna(_v):
                    bv.append(float(_v))
        if not bv: continue
        avg = sum(bv)/len(bv)
        names.append(wn)
        diffs.append(round(actual - avg, 2))
        colors.append(ws_col.get(wn, "#888"))

    if not names:
        st.info("편차 계산 데이터 부족")
        return

    short_m  = f"{str(m_p['year'])[2:]}년 {m_p['month']}월"
    bl_short = f"{str(bl[0])[2:]}~{str(bl[-1])[2:]}"

    chart_title = (
        f"유역별 지하수위(EL) 변동 "
        f"(과거{n}년({bl_short}년) {m_p['month']}월 평균 - {short_m})"
    )
    yaxis_title = f"과거 {n}년 대비 {m_p['month']}월 지하수위 현황"

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=names, y=diffs,
        marker=dict(color=colors),
        hovertemplate="%{x}<br>편차: %{y:.2f} m<extra></extra>",
    ))
    fig.add_hline(y=0, line_dash="dash", line_color="rgba(26,26,24,0.3)", line_width=1)
    fig.update_layout(
        title=dict(
            text=chart_title,
            font=dict(size=12), x=0.01
        ),
        height=300,
        xaxis_title="",
        xaxis=dict(categoryorder="array", categoryarray=names),
        yaxis_title=yaxis_title,
        yaxis=dict(range=[-5, 5], zeroline=True),
        margin=dict(t=30, b=20, l=60, r=10),
        showlegend=False,
        font=dict(size=14),
    )
    st.plotly_chart(fig, use_container_width=True, key="t3_diff_bar")


# ==============================================================================
#  ■ NEW: 유역 내 관측정별 지하수위 (차트 + 표)
# ==============================================================================
def _render_stations_section(sel, ws_col, periods, ps_keys, ps, n_gw, asos_df,
                              recent_months, baseline_gw_str):
    """선택된 유역에 속한 관측정들의 M-2·M-1·M EL 값을 시각화/표 렌더링.

    - 차트: 대시보드 요약의 '유역별 지하수위(EL) 변동' 과 동일한 패턴으로
            관측정별 3개 막대(기간별 톤)를 그린다. Y축은 절대 EL 값.
    - 표:  관측정 × (M-2, M-1, M, 과거 N년 평균(M기준), 편차) 형식.
    """
    station_df = _load_station_data_cached()
    ws_to_stations = _load_ws_to_stations_cached()
    stations_all = ws_to_stations.get(sel, [])

    # station_df 가 비었거나 매핑이 없으면 안내만 표시
    if station_df.empty or not stations_all:
        st.markdown(
            f'<p class="section-title" style="margin:0 0 4px;">'
            f'관측정별 지하수위 : {sel} 유역</p>'
            f'<p style="font-size:15px;color:var(--color-text-secondary);margin:0;">'
            f'관측정 데이터가 없습니다. 관측망 정보 파일(0_JD관측망_정보.xlsx)과 '
            f'관측정별 CSV(data/GWlevel/by_station/) 를 확인하세요.</p>',
            unsafe_allow_html=True
        )
        return

    # 이 유역에 실제 데이터가 존재하는 관측정만 추림
    stations = [s for s in stations_all
                if s in station_df["관측소명"].unique().tolist()]
    if not stations:
        st.markdown(
            f'<p class="section-title" style="margin:0 0 4px;">'
            f'관측정별 지하수위 : {sel} 유역</p>'
            f'<p style="font-size:15px;color:var(--color-text-secondary);margin:0;">'
            f'{sel} 유역에 매핑된 관측정이 있으나 월별 데이터가 로드되지 않았습니다.</p>',
            unsafe_allow_html=True
        )
        return

    # 관측정별 기간값 / baseline 계산
    # stn_data[station][pk] = {"actual":.., "avg":..}
    stn_data = {}
    for stn in stations:
        df_s = station_df[station_df["관측소명"] == stn]
        if df_s.empty or "EL" not in df_s.columns:
            stn_data[stn] = {pk: {"actual": None, "avg": None} for pk in ps_keys}
            continue
        per_period = {}
        for pk, p in zip(ps_keys, ps):
            ym = f"{p['year']}-{p['month']:02d}"
            bl_years = list(range(p["year"] - n_gw, p["year"]))
            ra = df_s[df_s["연월"] == ym]
            actual = float(ra["EL"].iloc[0]) if not ra.empty else None
            base_vals = []
            for y in bl_years:
                ymb = f"{y}-{p['month']:02d}"
                # (2026-06-11 검증1팀) 변수명 rb → _row_b: 모듈 별칭
                # `rb`(_robust_helpers) 가림 방지.
                _row_b = df_s[df_s["연월"] == ymb]
                if not _row_b.empty:
                    v = float(_row_b["EL"].iloc[0])
                    if pd.notna(v):
                        base_vals.append(v)
            avg = sum(base_vals)/len(base_vals) if base_vals else None
            per_period[pk] = {"actual": actual, "avg": avg}
        stn_data[stn] = per_period

    # ── 관측정별 공용 색상 팔레트 (추이 차트와 동일) ─────
    # 두 차트가 같은 관측정에 동일 색을 쓰도록 한 곳에서 정의.
    palette = _STATION_PALETTE
    station_colors = {stn: palette[i % len(palette)] for i, stn in enumerate(stations)}

    # ── 차트 헤더 ────────────────────────────────────────
    st.markdown(
        f'<p class="section-title" style="margin:0 0 4px;">'
        f'관측정별 지하수위(EL) : {sel} 유역 ({len(stations)}개 관측정)</p>',
        unsafe_allow_html=True
    )
    # 범례 — 관측정 색상 리스트 (추이 차트와 매칭). 기간 톤 안내 문구는
    # 차트 아래쪽에 별도로 배치(요청 3).
    period_alpha = {"M-2": 0.35, "M-1": 0.65, "M": 1.0}
    station_legend = "".join(
        f'<span style="display:inline-flex;align-items:center;gap:5px;'
        f'margin-right:16px;margin-bottom:2px;">'
        f'<span style="width:12px;height:12px;border-radius:2px;'
        f'background:{station_colors[stn]};'
        f'border:0.5px solid rgba(26,26,24,0.2);"></span>'
        f'<span style="font-size:16px;color:var(--color-text-primary);">{stn}</span>'
        f'</span>'
        for stn in stations
    )
    st.markdown(
        f'<div style="margin:0 0 6px;line-height:2.0;">'
        f'<span style="font-size:16px;color:var(--color-text-secondary);margin-right:8px;">관측정</span>'
        f'{station_legend}</div>',
        unsafe_allow_html=True
    )

    # ── 그래프 ───────────────────────────────────────────
    fig = go.Figure()
    for pk in ps_keys:
        ys = []
        txt = []
        colors = []
        for stn in stations:
            v = stn_data[stn][pk]["actual"]
            ys.append(v)
            txt.append(f"{v:.2f}" if v is not None else "")
            colors.append(theme.hex_alpha(station_colors[stn], period_alpha[pk]))
        fig.add_trace(go.Bar(
            name=pk,
            x=stations, y=ys,
            marker=dict(color=colors,
                        line=dict(color="rgba(255,255,255,1)", width=1)),
            text=txt,
            textposition="outside",
            textfont=dict(size=12, color=theme.COLOR_TEXT_PRIMARY),
            cliponaxis=False,
            width=0.22,
            hovertemplate=f"{pk}<br>%{{x}}<br>EL: %{{y:.2f}} m<extra></extra>",
            showlegend=False,
        ))
    # Y축 범위: 관측정 EL 값의 min/max 기준 여유 공간 포함
    all_vals = [stn_data[s][pk]["actual"] for s in stations for pk in ps_keys
                if stn_data[s][pk]["actual"] is not None]
    if all_vals:
        y_min = min(all_vals)
        y_max = max(all_vals)
        pad = max((y_max - y_min) * 0.12, 0.5)
        y_range = [y_min - pad, y_max + pad]
    else:
        y_range = None
    fig.update_layout(
        height=360,
        barmode="group",
        bargap=0.25,
        bargroupgap=0.18,
        xaxis_title="",
        yaxis_title="EL (m)",
        xaxis=dict(categoryorder="array", categoryarray=stations,
                   tickfont=dict(size=14)),
        yaxis=dict(range=y_range) if y_range else dict(),
        showlegend=False,
        margin=dict(t=10, b=20, l=50, r=20),
        font=dict(size=14),
    )
    st.plotly_chart(fig, use_container_width=True, key=f"t3_stn_bar_{sel}")

    # 차트 아래쪽 안내 문구 (요청 3) — 동적 월
    st.markdown(
        f'<p style="font-size:15px;color:var(--color-text-secondary);margin:2px 0 0;">'
        f'* 각 그래프는 각각 최근 {ps[0]["month"]}월(M-2), '
        f'최근 {ps[1]["month"]}월(M-1), 최근 {ps[2]["month"]}월(M)로 '
        f'각 관측정 별로 표시 됨</p>',
        unsafe_allow_html=True
    )

    # ── 표 ───────────────────────────────────────────────
    st.markdown(
        f'<p class="section-title" style="margin:10px 0 4px;">'
        f'관측정별 상세 : {sel} 유역</p>',
        unsafe_allow_html=True
    )
    _render_stations_table(stations, stn_data, ps_keys, ps, n_gw)
    st.markdown(
        f'<p style="font-size:14px;color:var(--color-text-secondary);margin:4px 0 0;">'
        f'* 최근 월 수위 : {recent_months}'
        f' &nbsp;|&nbsp; 과거 {n_gw}년 해당월 : {baseline_gw_str}</p>',
        unsafe_allow_html=True
    )

    # ── 관측정별 시계열 추이 차트 + 인근 AWS 강수량 막대 ──
    st.markdown("<div style='height:12px;'></div>", unsafe_allow_html=True)
    _render_stations_trend(stations, station_df, sel, ws_col, periods, asos_df)


def _render_stations_trend(stations, station_df, sel, ws_col, periods, asos_df=None):
    """유역 내 모든 관측정의 EL 시계열(line)을 상단에, 인접 AWS 월강수량(bar)을
    하단에 공유 X축으로 쌓은 2-row subplot 렌더링."""
    # 인접 AWS 조회
    ws_aws_map = {w["name"]: w["aws"] for w in config.WATERSHEDS}
    nearby = ws_aws_map.get(sel, "제주")
    aws_code = config.AWS_CODE_MAP.get(nearby, "")
    aws_col  = config.AWS_COLOR_MAP.get(nearby, theme.COLOR_AWS["제주"])

    # 헤더 — AWS 정보 포함 제목 (sub-title 제거)
    aws_label = f"{nearby}AWS({aws_code})" if aws_code else f"{nearby}AWS"
    st.markdown(
        f'<p class="section-title" style="margin:0 0 4px;">'
        f'지하수위(EL) 추이 : {sel} 유역 관측정별 + {aws_label} 월강수량</p>',
        unsafe_allow_html=True
    )

    palette = _STATION_PALETTE

    # 관측정 중 가장 긴 기간을 가진 것(= 가장 이른 시작 연월)을 X축 범위 기준으로 사용.
    # 모든 관측정과 강수량을 이 범위에 맞춰 정렬해 시각 비교가 가능하도록 필터링.
    all_months = set()
    well_ranges = {}
    for stn in stations:
        df_s = station_df[station_df["관측소명"] == stn]
        if df_s.empty:
            continue
        months = df_s["연월"].dropna().tolist()
        if not months:
            continue
        well_ranges[stn] = (min(months), max(months), len(months))
        all_months.update(months)
    if all_months:
        x_min = min(all_months)
        x_max = max(all_months)
    else:
        x_min = x_max = None
    # X축 기준 기간 산출 (가장 긴 기간 관측정 — 내부 사용 only, 헤더에 노출 X)

    # 2-row 서브플롯: 상단 line, 하단 bar, X축 공유.
    # EL 영역은 v1.0.26 기준의 1.5배(346→519px), 강수량은 그대로(134px).
    fig = make_subplots(
        rows=2, cols=1,
        shared_xaxes=True,
        vertical_spacing=0.05,
        row_heights=[0.80, 0.20],
    )

    # 상단: 관측정별 EL 라인
    for i, stn in enumerate(stations):
        df_s = station_df[station_df["관측소명"] == stn].sort_values("연월")
        if df_s.empty:
            continue
        color = palette[i % len(palette)]
        fig.add_trace(
            go.Scatter(
                x=df_s["연월"], y=df_s["EL"],
                name=stn,
                mode="lines+markers",
                line=dict(color=color, width=1.5),
                marker=dict(size=3, color=color),
                hovertemplate=(
                    f"<b>{stn}</b><br>%{{x}}<br>EL: %{{y:.2f}} m<extra></extra>"
                ),
            ),
            row=1, col=1
        )

    # 하단: 인접 AWS 월강수량 막대 (관측정 기간에 맞춰 필터)
    if asos_df is not None and not asos_df.empty and x_min is not None:
        monthly = effective_rainfall.aggregate_monthly(asos_df)
        rain_df = monthly[monthly["지점명"] == nearby].sort_values("연월")
        # 관측정 기간 범위로 제한
        rain_df = rain_df[(rain_df["연월"] >= x_min) & (rain_df["연월"] <= x_max)]
        if not rain_df.empty:
            # 강우 = 진한 블루 톤 (AWS 색상 대신 통일된 비/물 느낌)
            rain_fill = "#1f6fd8"     # deep blue
            rain_edge = "#103a78"     # darker outline
            fig.add_trace(
                go.Bar(
                    x=rain_df["연월"], y=rain_df["월강수량(mm)"],
                    name=f"월강수량 ({nearby})",
                    marker=dict(color=rain_fill,
                                line=dict(color=rain_edge, width=0.5)),
                    showlegend=False,      # 관측정 범례와 분리 — 별도 색상 표시만
                    hovertemplate=(
                        f"<b>{nearby} 강수량</b><br>%{{x}}<br>"
                        f"%{{y:.0f}} mm<extra></extra>"
                    ),
                ),
                row=2, col=1
            )

    # M 기간 세로선 — 두 subplot 에 각각 추가 (paper y ref 는 subplot 경계 때문에 불안정)
    m_p = periods["M"]
    m_ym = f"{m_p['year']}-{m_p['month']:02d}"
    for r, xref, yref in [(1, "x", "y domain"), (2, "x2", "y2 domain")]:
        fig.add_shape(
            type="line", xref=xref, yref=yref,
            x0=m_ym, x1=m_ym, y0=0, y1=1,
            line=dict(dash="dash", color="rgba(26,26,24,0.35)", width=1),
            row=r, col=1,
        )
    fig.add_annotation(
        x=m_ym, xref="x", yref="y domain", y=1.0, yanchor="bottom",
        text=f"M ({m_p['year']}년 {m_p['month']}월)",
        showarrow=False,
        font=dict(size=13, color=theme.COLOR_TEXT_SECONDARY),
        row=1, col=1,
    )

    # 축 제목 (요청 4·5)
    fig.update_yaxes(title_text="지하수위(EL) (m)", row=1, col=1,
                     tickfont=dict(size=14))
    fig.update_yaxes(title_text="월강수량(mm)", row=2, col=1,
                     tickfont=dict(size=14))
    # X축: 영문 월명("Jan") 대신 숫자 포맷("2021-01") 사용
    fig.update_xaxes(tickfont=dict(size=14), tickformat="%Y-%m",
                     row=2, col=1)
    # X축 범위를 관측정 가장 긴 기간에 맞춤 (양쪽 subplot 공유)
    if x_min is not None and x_max is not None:
        fig.update_xaxes(range=[x_min, x_max], row=1, col=1)
        fig.update_xaxes(range=[x_min, x_max], row=2, col=1)

    fig.update_layout(
        height=653,              # v1.0.26 대비 EL 영역 1.5배 (346×1.5 + 134)
        barmode="group",
        bargap=0.15,
        margin=dict(t=10, b=80, l=50, r=10),
        legend=dict(
            orientation="h", yanchor="top", y=-0.15,
            xanchor="center", x=0.5,
            font=dict(size=14),
        ),
        font=dict(size=14),
    )
    st.plotly_chart(fig, use_container_width=True, key=f"t3_stn_trend_{sel}")


def _render_stations_table(stations, stn_data, ps_keys, ps, n_gw):
    """유역 내 관측정별 표 — 3기간 × 3지표(최근수위/과거평균/편차) 그리드.

    2단 헤더:
      1행: 관측정(rowspan=2) | 11월(M-2) colspan=3 | 12월(M-1) colspan=3 | 1월(M) colspan=3
      2행:                   | 최근수위 | 과거평균 | 편차 | ... (반복)
    """

    # colgroup: 관측정 + 3기간 × 3열 = 10열
    colgroup = (
        '<colgroup>'
        '<col style="width:140px;">'                # 관측정
        '<col><col><col>'                           # M-2 (수위 / 평균 / 편차)
        '<col><col><col>'                           # M-1
        '<col><col><col>'                           # M
        '</colgroup>'
    )

    group_th = ('padding:6px 8px;background:var(--color-bg-secondary);text-align:center;'
                'border-bottom:1px solid #ddd;font-weight:600;font-size:16px;')
    sub_th   = ('padding:5px 4px;background:var(--color-bg-secondary);text-align:center;'
                'border-bottom:1.5px solid #ccc;font-size:15px;font-weight:500;'
                'color:var(--color-text-secondary);')

    # 1행: 기간 그룹 헤더
    group_cells = ""
    for i, (pk, p) in enumerate(zip(ps_keys, ps)):
        left_border = "border-left:1px solid #ddd;" if i > 0 else ""
        group_cells += (
            f'<th colspan="3" style="{group_th}{left_border}">'
            f'{p["month"]}월 ({pk})</th>'
        )

    # 2행: 하위 열
    sub_cells = ""
    for i, pk in enumerate(ps_keys):
        left_border = "border-left:1px solid #ddd;" if i > 0 else ""
        sub_cells += (
            f'<th style="{sub_th}{left_border}">최근 수위 (m)</th>'
            f'<th style="{sub_th}">과거 {n_gw}년 평균 (m)</th>'
            f'<th style="{sub_th}">편차 (m)</th>'
        )

    head = (
        '<table style="width:100%;border-collapse:collapse;table-layout:fixed;'
        'font-size:16px;">'
        + colgroup
        + '<thead>'
        '<tr>'
        f'<th rowspan="2" style="padding:6px 8px;background:var(--color-bg-secondary);'
        f'text-align:center;vertical-align:middle;border-bottom:1.5px solid #ccc;">'
        f'관측정</th>'
        + group_cells
        + '</tr>'
        '<tr>' + sub_cells + '</tr>'
        '</thead><tbody>'
    )

    base_td = 'padding:6px 4px;border-bottom:0.5px solid #eee;text-align:center;'
    body = ""
    for stn in stations:
        row = (
            '<tr>'
            f'<td style="{base_td}font-size:16px;font-weight:500;">{stn}</td>'
        )
        for i, pk in enumerate(ps_keys):
            left_border = "border-left:1px solid #ddd;" if i > 0 else ""
            actual = stn_data[stn][pk]["actual"]
            avg    = stn_data[stn][pk]["avg"]
            a_s = f"{actual:.2f}" if actual is not None else "–"
            v_s = f"{avg:.2f}"    if avg    is not None else "–"
            if actual is not None and avg is not None:
                d = actual - avg
                c = theme.COLOR_SUCCESS if d >= 0 else theme.COLOR_DANGER
                sg = "+" if d >= 0 else ""
                d_s = f'<span style="color:{c};font-weight:500;">{sg}{d:.2f}</span>'
            else:
                d_s = "–"
            row += (
                f'<td style="{base_td}{left_border}font-size:16px;font-weight:500;">{a_s}</td>'
                f'<td style="{base_td}color:var(--color-text-secondary);">{v_s}</td>'
                f'<td style="{base_td}">{d_s}</td>'
            )
        row += '</tr>'
        body += row

    st.markdown(head + body + '</tbody></table>', unsafe_allow_html=True)
