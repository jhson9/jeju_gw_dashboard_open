# ==============================================================================
#  파일명: src/dashboard/tabs/tab02_rainfall.py
#  탭: ② 강수량 분석  —  Build 1.0 Final
# ==============================================================================

import streamlit as st
import pandas as pd
import plotly.graph_objects as go

import config
from src.analysis import effective_rainfall
from src.dashboard import theme


def _short(y, m):
    return f"{str(y)[2:]}년 {m}월"


# ==============================================================================
@st.fragment  # 21차 Step4: 위젯 변경 시 다른 탭 튕김 방지 (AGENT_GUIDE §6)
def render(asos_df: pd.DataFrame, periods: dict):
    # 안내 캡션 제거 — 헤더/탭 자체로 의미 전달

    if asos_df.empty:
        st.warning("⚠️ ASOS 데이터 없음. **⚙️ 데이터 관리** 탭에서 수집하세요.")
        return

    monthly = effective_rainfall.aggregate_monthly(asos_df)
    half    = effective_rainfall.aggregate_half_monthly(asos_df)
    ps_keys = ["M-2", "M-1", "M"]
    ps      = [periods[k] for k in ps_keys]
    n_rain  = config.RAINFALL_BASELINE_YEARS

    # 🆕 (2026-06-06) partial 모드 감지 — M 슬롯이 부분월(1~D-1)이면 partial_df 생성
    m_p = periods["M"]
    is_partial = m_p.get("partial", False)
    base_date = periods.get("base_date")
    partial_df = None
    if is_partial and base_date is not None:
        partial_df = effective_rainfall.aggregate_partial_monthly(asos_df, base_date)

    # 차트 X축 라벨: "11월 (M-2)" / partial 시 M: "6월 1~5일 (M)"
    def _xlabel(p, k):
        if p.get("partial"):
            return f"{p['month']}월 1~{p['end_date'].day}일 ({k})"
        return f"{p['month']}월 ({k})"
    xlabels = [_xlabel(p, k) for k, p in zip(ps_keys, ps)]

    # 하단 캡션용 기간 목록
    # 🆕 (2026-06-06 v3 사용자 요청) partial M 에 "(~5일)" 명시 — 비교 단위 명확화
    def _period_label_short(p):
        ym = f"{str(p['year'])[2:]}년 {p['month']}월"
        if p.get("partial"):
            ym += f"(~{p['end_date'].day}일)"
        return ym
    recent_months = ", ".join(_period_label_short(p) for p in ps)
    # baseline 은 월 평균 그대로 (강수량은 baseline 도 partial 윈도우로 비교됨 —
    #   aggregate_partial_monthly 가 동일 윈도우 처리. 단 캡션의 라벨은 "월" 유지
    #   하되 partial 시 "(~5일)" 부연 추가하여 사용자 인지)
    def _baseline_label_short(p):
        yr = f"{str(p['year']-n_rain)[2:]}~{str(p['year']-1)[2:]}년 {p['month']}월"
        if p.get("partial"):
            yr += f"(~{p['end_date'].day}일)"
        return yr
    baseline_rain_str = ", ".join(_baseline_label_short(p) for p in ps)
    # 차트 범례용 baseline 요약(M-2 기간 기준)
    _p0 = ps[0]
    _bl_r0 = list(range(_p0["year"] - n_rain, _p0["year"]))
    yr_r_short = f"{str(_bl_r0[0])[2:]}~{str(_bl_r0[-1])[2:]}"
    lbl_avg_rain = f"과거 {n_rain}년 해당월 평균"
    lbl_act_rain = "최근 강수량"
    lbl_avg_eff  = f"과거 {n_rain}년 해당월 평균"
    lbl_act_eff  = "최근 유효강수(일)"

    # 값 미리 계산 — 🆕 (2026-06-06) partial_df 전달 (M 슬롯이 partial 일 때 사용)
    D = {}
    for s in config.STATIONS_ASOS:
        sn = s["name"]
        D[sn] = {
            "rain_a": [effective_rainfall.get_period_value(monthly, half, p, sn, "월강수량(mm)", partial_df=partial_df) for p in ps],
            "rain_v": [effective_rainfall.get_baseline_average(monthly, half, p, sn, "월강수량(mm)", n_years=n_rain, partial_df=partial_df)[0] for p in ps],
            "eff_a":  [effective_rainfall.get_period_value(monthly, half, p, sn, "유효강수일수(일)", partial_df=partial_df) for p in ps],
            "eff_v":  [effective_rainfall.get_baseline_average(monthly, half, p, sn, "유효강수일수(일)", n_years=n_rain, partial_df=partial_df)[0] for p in ps],
        }

    # ── 요약 카드 4개 ─ ⑧ 통계 헬퍼 적용 (사용자 결정 2026-05-09)
    #   한 카드 = title (지점명) + 그룹 2개 (강수량 / 유효강수일수). 정보 손실
    #   없이 ⑧ 카드 스타일과 일관. 5년평균 기준 연도는 각 그룹 sub 에 포함.
    # 🆕 (2026-06-06) partial 시 카드 라벨에 "(1~Nday, N=N)" 부연
    # 🆕 (2026-06-06 v3 사용자 요청) 글자 길이 단축: 4자리 연도 → 2자리 (YY~YY년)
    bl_yr_text = f"{str(m_p['year']-n_rain)[2:]}~{str(m_p['year']-1)[2:]}년"
    m_rain_label = (f"강수량 — {m_p['year']}년 {m_p['month']}월"
                    + (f" (~{m_p['end_date'].day}일, N={m_p['n_days']})"
                       if is_partial else ""))
    card_cols = st.columns(4)
    for i, s in enumerate(config.STATIONS_ASOS):
        sn = s["name"]
        col = s["color"]
        ra = D[sn]["rain_a"][-1]
        rv = D[sn]["rain_v"][-1]
        ea = D[sn]["eff_a"][-1]
        ev = D[sn]["eff_v"][-1]

        # 강수량 값/편차
        rain_str = f"{ra:.0f} mm" if ra is not None else "–"
        if ra is not None and rv is not None:
            rd = ra - rv
            rc = theme.COLOR_SUCCESS if rd >= 0 else theme.COLOR_DANGER
            rs = "+" if rd >= 0 else ""
            rain_diff_html = (
                f'<span style="color:{rc};font-weight:500;">{rs}{rd:.0f}mm</span>'
            )
        else:
            rain_diff_html = "–"
        rv_mm = f"{rv:.0f}mm" if rv is not None else "–"

        # 유효강수 값/편차
        eff_str = f"{int(round(ea))}일" if ea is not None else "–"
        ev_days = f"{ev:.0f}일" if ev is not None else "–"
        if ea is not None and ev is not None:
            ed = ea - ev
            ec = theme.COLOR_SUCCESS if ed >= 0 else theme.COLOR_DANGER
            es = "+" if ed >= 0 else ""
            eff_diff_html = (
                f'<span style="color:{ec};font-weight:500;">{es}{ed:.0f}일</span>'
            )
        else:
            eff_diff_html = "–"

        groups = [
            (
                m_rain_label,  # 🆕 (2026-06-06) partial 시 "(1~Nday, N=N)" 부연 포함
                rain_str,
                f"5년평균({bl_yr_text}) {rv_mm} &nbsp;|&nbsp; 편차 {rain_diff_html}",
            ),
            (
                "유효강수일",
                eff_str,
                f"5년평균 {ev_days} &nbsp;|&nbsp; 편차 {eff_diff_html}",
            ),
        ]
        theme.render_period_kpi_card(
            title=f"{sn} ({s['id']})",
            groups=groups,
            accent=col,
            is_base=True,
            container=card_cols[i],
        )

    st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)

    caption_style = "font-size:14px;color:var(--color-text-secondary);margin:4px 0 0;"

    # ── 강수량 섹션 ───────────────────────────────────────────
    st.markdown(
        f'<p class="section-title" style="margin:0 0 4px;">'
        f'월별 강수량 : 4개 AWS (mm)</p>',
        unsafe_allow_html=True
    )
    _render_2x2_charts(xlabels, config.STATIONS_ASOS, D, "rain_a", "rain_v",
                       "mm", lbl_avg_rain, lbl_act_rain,
                       key_prefix="t2_rain", decimals=0)
    st.markdown(
        f'<p style="{caption_style}">'
        f'* 최근 월 강수량 : {recent_months}'
        f' &nbsp;|&nbsp; 과거 {n_rain}년 해당월 : {baseline_rain_str}</p>',
        unsafe_allow_html=True
    )

    st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)

    # ── 강수량 비교표 ─────────────────────────────────────────
    st.markdown(
        f'<p class="section-title" style="margin:0 0 4px;">'
        f'강수량 비교표 : 4개 AWS (mm)</p>',
        unsafe_allow_html=True
    )
    _render_mkptbl(ps, ps_keys, D, "rain_a", "rain_v", "mm",
                   decimals=0, metric="강수량")
    st.markdown(
        f'<p style="{caption_style}">'
        f'* 최근 월 강수량 : {recent_months}'
        f' &nbsp;|&nbsp; 과거 {n_rain}년 해당월 : {baseline_rain_str}</p>',
        unsafe_allow_html=True
    )

    st.markdown("<div style='height:16px;'></div>", unsafe_allow_html=True)

    # ── 농업유효 강수일수 섹션 ──────────────────────────────
    st.markdown(
        f'<p class="section-title" style="margin:0 0 4px;">'
        f'월별 농업유효 강수일수 (일)</p>'
        f'<p style="font-size:14px;color:var(--color-text-secondary);margin:0 0 6px;">'
        f'기준: 일강수량 {config.EFFECTIVE_RAINFALL_THRESHOLD_MM} mm 이상</p>',
        unsafe_allow_html=True
    )
    _render_2x2_charts(xlabels, config.STATIONS_ASOS, D, "eff_a", "eff_v",
                       "일", lbl_avg_eff, lbl_act_eff,
                       key_prefix="t2_eff", decimals=0)
    st.markdown(
        f'<p style="{caption_style}">'
        f'* 최근 월 유효강수일수 : {recent_months}'
        f' &nbsp;|&nbsp; 과거 {n_rain}년 해당월 : {baseline_rain_str}</p>',
        unsafe_allow_html=True
    )

    st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)

    # ── 유효강수일수 비교표 ────────────────────────────────────
    st.markdown(
        f'<p class="section-title" style="margin:0 0 4px;">'
        f'농업유효강수일수 비교표 : 4개 AWS (일)</p>',
        unsafe_allow_html=True
    )
    _render_mkptbl(ps, ps_keys, D, "eff_a", "eff_v", "일",
                   decimals=0, integer=True, metric="유효강수일수")
    st.markdown(
        f'<p style="font-size:14px;color:var(--color-text-secondary);margin:4px 0 0;">'
        f'* 최근 월 유효강수일수 : {recent_months}'
        f' &nbsp;|&nbsp; 과거 {n_rain}년 해당월 : {baseline_rain_str}</p>',
        unsafe_allow_html=True
    )

    # 🆕 (2026-06-06) M 슬롯 일별 시계열 차트
    # 🆕 (2026-06-06 v2 사용자 요청) 유효강수 binary 차트 삭제, 강수량 차트에
    #   일강수량 텍스트 라벨 + 5mm 수평 점선(유효강수 시각 임계) 추가.
    # 🆕 (2026-06-06 v4 사용자 요청) D=1 이어도 전월 전체 일별 표시.
    #   → is_partial 가드 제거. 모든 모드에서 _partial_window() 가 결정한
    #     윈도우(전월 전체 또는 당월 1~D-1)로 일별 차트 렌더.
    if base_date is not None and not asos_df.empty:
        # 🆕 (2026-06-06 v5) periods["M"] 슬롯 자체 기준 — partial/half/full 모두 처리
        # 🆕 (2026-06-06 v6 사용자 요청) 년/월 선택 위젯
        # 🆕 (2026-06-06 v7 사용자 요청) 위젯을 차트 아래로 이동 — UX 흐름 개선
        st.markdown("<div style='height:14px;'></div>", unsafe_allow_html=True)

        # 데이터의 가용 연도 범위 계산
        _data_years = pd.to_datetime(asos_df["일시"], errors="coerce").dt.year.dropna()
        _min_year = int(_data_years.min()) if not _data_years.empty else 2000
        _max_year = int(_data_years.max()) if not _data_years.empty else base_date.year
        _year_options = list(range(_max_year, _min_year - 1, -1))  # 최신 → 과거
        _month_options = list(range(1, 13))

        # 기본값: M 슬롯의 연/월 (현재 분석 윈도우 자동 반영)
        _default_year = m_p["year"]
        _default_month = m_p["month"]

        # session_state 초기화 (첫 진입 시 default 로 세팅)
        if "t1_daily_year" not in st.session_state:
            st.session_state["t1_daily_year"] = _default_year
        if "t1_daily_month" not in st.session_state:
            st.session_state["t1_daily_month"] = _default_month

        # 차트 그리기 전 현재 선택값 읽기 (위젯은 차트 아래에 렌더링)
        sel_year = st.session_state.get("t1_daily_year", _default_year)
        sel_month = st.session_state.get("t1_daily_month", _default_month)

        # 선택값이 M 슬롯과 일치하면 m_p 그대로(partial/half 정보 보존),
        # 다르면 임시 full-month 슬롯 생성
        if sel_year == _default_year and sel_month == _default_month:
            _active_slot = m_p
            _slot_origin = "M 슬롯"
        else:
            _active_slot = {"year": sel_year, "month": sel_month,
                            "partial": False, "half": False}
            _slot_origin = "사용자 선택"

        _ty, _tm, _sd, _ed, _label, _n_days = _m_slot_window(_active_slot)
        if _active_slot.get("partial"):
            _start_caption = f"M({_ty}-{_tm:02d}) 1~{_ed}일 (어제까지 partial 모드)"
        elif _active_slot.get("half"):
            _start_caption = f"M({_ty}년 {_tm}월) 1~15일 (반월 모드)"
        else:
            _start_caption = f"{_ty}년 {_tm}월 전체 1~{_ed}일"

        # 제목 + 캡션 (차트 위)
        st.markdown(
            f'<p class="section-title" style="margin:0 0 4px;">'
            f'{_slot_origin}({_label}) — 일별 강수량 (mm, N={_n_days}일)</p>'
            f'<p style="{caption_style}">'
            f'* 분석 기준일({base_date}) 기준 {_start_caption} 의 4개 AWS 일자별 강수량. '
            f'점선 = 유효강수 임계 {config.EFFECTIVE_RAINFALL_THRESHOLD_MM} mm. '
            f'본 데이터는 자동수집(water.jeju + 기상청) 결과로 D-1 까지 가용.</p>',
            unsafe_allow_html=True
        )
        # 차트
        _render_partial_daily_chart(asos_df, base_date, "rain", m_slot=_active_slot)

        # 🆕 (v7) 위젯을 차트 아래에 같은 행으로 배치
        _wc1, _wc2, _wc3 = st.columns([1, 1, 3])
        with _wc1:
            st.selectbox(
                "년도", options=_year_options, key="t1_daily_year",
            )
        with _wc2:
            st.selectbox(
                "월", options=_month_options, key="t1_daily_month",
            )
        with _wc3:
            st.markdown(
                f"<div style='padding-top:28px;font-size:13px;"
                f"color:var(--color-text-secondary);'>"
                f"기본값: M 슬롯({_default_year}년 {_default_month}월). "
                f"다른 월 선택 시 해당 월 전체 일별 표시.</div>",
                unsafe_allow_html=True,
            )

    st.markdown("<div style='height:18px;'></div>", unsafe_allow_html=True)

    # ── 연간 강수량 분석 ────────────────────────────────────
    st.markdown(
        f'<p class="section-title" style="margin:0 0 4px;">'
        f'연간 강수량 분석 — 5개 차트 (평균·제주·서귀포·성산·고산)</p>'
        f'<p style="{caption_style}">'
        f'* 막대(연 총 강수량, 우 Y축) + 선(월 강수량, 좌 Y축) · '
        f'완전한 12개월 자료가 있는 연도만 막대 표시</p>',
        unsafe_allow_html=True
    )
    _render_annual_rainfall(asos_df)

    st.markdown("<div style='height:8px;'></div>", unsafe_allow_html=True)
    theme.render_note_box(
        f"💡 <strong>분석 메모</strong>: 4개 ASOS 관측소 데이터, "
        f"기준일 {periods['base_date']}의 M-2·M-1·M 기간 집계. "
        f"직전 {n_rain}년 평균은 각 기간 연도 기준으로 독립 계산."
    )


# ==============================================================================
#  ■ 🆕 (2026-06-06 v5) M 슬롯 일별 강수 차트 윈도우 헬퍼
#     사용자 요청: M 슬롯 자체를 기준으로 윈도우 결정 — base_date 가 아닌
#     periods["M"] 의 year/month/partial/end_date 를 그대로 사용.
#
#     [동작 매트릭스]
#     기준일 (D)  | partial 옵션 | periods["M"]            | 차트 윈도우
#     ─────────────┼──────────────┼─────────────────────────┼──────────────
#     2026-06-01  | OFF/ON       | full: 2026-05 (전월)    | 5월 1~31일
#     2026-06-06  | OFF          | full: 2026-05 (전월)    | 5월 1~31일
#     2026-06-06  | ON           | partial: 2026-06 (~5일) | 6월 1~5일
#     2026-06-20  | OFF          | half: 2026-06(1~15일)   | 6월 1~15일
#     2026-06-20  | ON           | partial: 2026-06 (~19일)| 6월 1~19일
# ==============================================================================
def _m_slot_window(m_slot: dict):
    """periods["M"] dict 로부터 일별 차트 윈도우를 반환.

    Returns
    -------
    tuple : (target_year, target_month, start_day, end_day, label_str, n_days)
    """
    import calendar as _cal
    ty = m_slot["year"]
    tm = m_slot["month"]
    if m_slot.get("partial"):
        # partial: 1 ~ end_date.day (보통 base_date.day - 1)
        end_d = m_slot.get("end_date")
        ed = end_d.day if end_d is not None else _cal.monthrange(ty, tm)[1]
        return ty, tm, 1, ed, f"{ty}-{tm:02d}(~{ed}일)", ed
    if m_slot.get("half"):
        # half: 1 ~ 15일 (반월 모드)
        return ty, tm, 1, 15, f"{ty}-{tm:02d}(1~15일)", 15
    # full: 1 ~ 말일 (전월 전체)
    ed = _cal.monthrange(ty, tm)[1]
    return ty, tm, 1, ed, f"{ty}-{tm:02d}", ed


# (호환) 구 _partial_window — 다른 모듈/탭이 호출할 수 있으므로 alias 유지
def _partial_window(base_date):
    """DEPRECATED: 호환용 유지. 신규 코드는 `_m_slot_window(periods['M'])` 사용."""
    import calendar as _cal
    if base_date.day == 1:
        if base_date.month == 1:
            ty, tm = base_date.year - 1, 12
        else:
            ty, tm = base_date.year, base_date.month - 1
        end_day = _cal.monthrange(ty, tm)[1]
        return ty, tm, 1, end_day, f"{ty}-{tm:02d}", end_day
    end_day = base_date.day - 1
    return (base_date.year, base_date.month, 1, end_day,
            f"{base_date.year}-{base_date.month:02d}(~{end_day}일)", end_day)


# ==============================================================================
#  ■ 🆕 (2026-06-06) M 슬롯 일별 강수 차트
#     사용자 요청: 분석 기준일(D)로 분석 시, M 윈도우의 일자별 막대.
# ==============================================================================
def _render_partial_daily_chart(asos_df: pd.DataFrame, base_date,
                                 metric: str = "rain", m_slot: dict = None):
    """4지점 × 일자별 강수량 막대 차트.

    Parameters
    ----------
    asos_df  : pd.DataFrame
    base_date: datetime.date — 분석 기준일 (plotly key 의 uniqueness 용)
    metric   : "rain" (강수량 mm 누적·평균표시 X) | "eff" (유효강수일 binary)
    m_slot   : dict, optional — periods["M"] 슬롯. 주어지면 슬롯 기반 윈도우 사용.
               미주어지면 base_date 기반(_partial_window) 폴백.
    """
    if asos_df.empty or base_date is None:
        return
    # 🆕 (2026-06-06 v5) m_slot 우선, 미주어지면 base_date 폴백
    if isinstance(m_slot, dict):
        ty, tm, sd, ed, _label, _n_days = _m_slot_window(m_slot)
    else:
        ty, tm, sd, ed, _label, _n_days = _partial_window(base_date)
    df = asos_df.copy()
    df["일시"] = pd.to_datetime(df["일시"], errors="coerce")
    df = df.dropna(subset=["일시"])
    df = df[(df["일시"].dt.year == ty)
            & (df["일시"].dt.month == tm)
            & (df["일시"].dt.day >= sd)
            & (df["일시"].dt.day <= ed)].copy()
    if df.empty:
        st.caption(f"⚠ M({ty}-{tm:02d}) {sd}~{ed}일 자료 없음 "
                   "— ⚙️ 데이터 관리 탭의 '🔄 지금 모두 업데이트' 실행 권장")
        return

    df["날짜"] = df["일시"].dt.strftime("%m-%d")
    threshold = config.EFFECTIVE_RAINFALL_THRESHOLD_MM

    fig = go.Figure()
    _max_y = 0.0  # 🆕 (2026-06-06) y축 범위 + 5mm 점선 위치 계산용
    for s in config.STATIONS_ASOS:
        sn = s["name"]
        d_s = df[df["지점명"] == sn].sort_values("일시")
        if d_s.empty:
            continue
        if metric == "rain":
            y_vals = d_s["일강수량(mm)"].fillna(0).tolist()
            hover = [f"{sn} · {nd}<br>{v:.1f} mm" for nd, v in zip(d_s["날짜"], y_vals)]
            _max_y = max(_max_y, max(y_vals) if y_vals else 0)
        else:  # eff
            y_vals = [(1 if (v >= threshold) else 0)
                       for v in d_s["일강수량(mm)"].fillna(0)]
            hover = [f"{sn} · {nd}<br>{'유효강수' if v else '미충족'} ({mm:.1f} mm ≥ {threshold})"
                     for nd, v, mm in zip(d_s["날짜"], y_vals, d_s["일강수량(mm)"].fillna(0))]
        # 🆕 (2026-06-06 사용자 요청) 일강수량 텍스트 라벨 추가 (rain 모드만)
        text_labels = [(f"{v:.1f}" if v > 0.05 else "") for v in y_vals] \
                       if metric == "rain" else None
        fig.add_trace(go.Bar(
            x=d_s["날짜"].tolist(),
            y=y_vals,
            name=sn,
            marker_color=s["color"],
            text=text_labels,
            textposition="outside",
            textfont=dict(size=10, color=s["color"]),
            cliponaxis=False,
            hovertemplate="%{customdata}<extra></extra>",
            customdata=hover,
        ))

    # 🆕 (2026-06-06 사용자 요청) 5 mm 수평 점선 — 유효강수 임계 시각 표시
    if metric == "rain" and _max_y > 0:
        fig.add_hline(
            y=threshold,
            line=dict(color="rgba(220, 50, 50, 0.65)", width=1.5, dash="dash"),
            annotation_text=f"유효강수 {threshold:.0f}mm",
            annotation_position="top right",
            annotation_font=dict(size=11, color="rgba(180, 30, 30, 0.85)"),
        )
        # 라벨이 잘리지 않도록 y 상한 약간 확장
        _y_top = max(_max_y * 1.18, threshold * 2)
    else:
        _y_top = None

    y_title = "일강수량 (mm)" if metric == "rain" else f"유효강수 (1=충족 / 0=미충족)"
    fig.update_layout(
        barmode="group",
        height=280,
        margin=dict(l=10, r=10, t=30, b=30),
        plot_bgcolor="white",
        xaxis=dict(title="날짜", type="category"),
        yaxis=dict(title=y_title,
                   range=[0, 1.1] if metric == "eff"
                          else ([0, _y_top] if _y_top else None)),
        legend=dict(orientation="h", y=1.14, font=dict(size=11)),
    )
    st.plotly_chart(fig, use_container_width=True,
                    key=f"t3_partial_{metric}_{base_date}_{ty}{tm:02d}")


# ==============================================================================
#  ■ 연간 강수량 분석 — 막대(연 총합) + 선(월별), 이중 Y축
# ==============================================================================
def _render_annual_rainfall(asos_df: pd.DataFrame):
    df = asos_df.copy()
    df["일시"] = pd.to_datetime(df["일시"], errors="coerce")
    df = df.dropna(subset=["일시"])
    df["연도"] = df["일시"].dt.year
    df["월"]   = df["일시"].dt.month

    # 지점×연-월 월합계
    monthly = (
        df.groupby(["지점명", "연도", "월"])["일강수량(mm)"]
          .sum().reset_index()
          .rename(columns={"일강수량(mm)": "월강수량"})
    )
    # 4개 지점 평균 (월별)
    avg_monthly = (
        monthly.groupby(["연도", "월"])["월강수량"]
               .mean().reset_index()
    )
    avg_monthly["지점명"] = "평균"
    monthly_all = pd.concat(
        [monthly[["지점명", "연도", "월", "월강수량"]],
         avg_monthly[["지점명", "연도", "월", "월강수량"]]],
        ignore_index=True,
    )

    chart_list = [{"name": "평균", "color": theme.COLOR_TEXT_SECONDARY, "id": ""}] + [
        {"name": s["name"], "color": theme.COLOR_AWS[s["name"]], "id": str(s["id"])}
        for s in config.STATIONS_ASOS
    ]

    for chart in chart_list:
        sn  = chart["name"]
        col = chart["color"]
        sub = monthly_all[monthly_all["지점명"] == sn].copy()
        if sub.empty:
            continue
        sub = sub.sort_values(["연도", "월"]).reset_index(drop=True)
        sub["dt"] = pd.to_datetime(
            sub["연도"].astype(str) + "-"
            + sub["월"].astype(str).str.zfill(2) + "-15"
        )

        # 12개월 자료가 모두 있는 연도만 연 총합 계산
        cnt_per_year = sub.groupby("연도")["월"].nunique()
        full_years = cnt_per_year[cnt_per_year == 12].index.tolist()
        annual = (
            sub[sub["연도"].isin(full_years)]
              .groupby("연도")["월강수량"].sum()
              .reset_index().rename(columns={"월강수량": "연강수량"})
        )
        annual["dt"] = pd.to_datetime(annual["연도"].astype(str) + "-07-01")

        title_id = (
            f' <span style="font-size:15px;font-weight:500;color:var(--color-text-secondary);">'
            f'({chart["id"]})</span>' if chart["id"] else ""
        )
        st.markdown(
            f'<p class="subsection-title" style="margin:10px 0 0;color:{col};">'
            f'{sn}{title_id}</p>',
            unsafe_allow_html=True
        )

        # 막대 폭: ~340일 (mid-year 위치라 양쪽으로 ~5.5개월씩)
        bar_width_ms = 340 * 24 * 3600 * 1000
        # Y축 상한 — 이중축이라 따로 계산해 막대 라벨이 위 외부에 보이도록 여유
        y2_max = (annual["연강수량"].max() * 1.18) if not annual.empty else 1
        y1_max = (sub["월강수량"].max() * 1.20) if not sub.empty else 1

        fig = go.Figure()
        fig.add_trace(go.Bar(
            x=annual["dt"], y=annual["연강수량"],
            name="연 총 강수량",
            marker=dict(color=theme.hex_alpha(col, 0.30),
                        line=dict(color=col, width=1)),
            text=[f"{v:,.0f}" for v in annual["연강수량"]],
            textposition="outside",
            textfont=dict(size=14, color=col),
            cliponaxis=False,
            width=bar_width_ms,
            yaxis="y2",
            hovertemplate="%{x|%Y}<br>연 총 강수량: %{y:.0f} mm<extra></extra>",
        ))
        fig.add_trace(go.Scatter(
            x=sub["dt"], y=sub["월강수량"],
            mode="lines+markers",
            name="월 강수량",
            line=dict(color=col, width=1.6),
            marker=dict(size=4, color=col),
            yaxis="y",
            hovertemplate="%{x|%Y-%m}<br>월 강수량: %{y:.0f} mm<extra></extra>",
        ))
        fig.update_layout(
            height=300,
            xaxis=dict(
                tickformat="%Y",
                dtick="M12",
                tickfont=dict(size=14),
                showgrid=True, gridcolor="rgba(0,0,0,0.06)",
            ),
            yaxis=dict(
                title=dict(text="월 강수량 (mm)", font=dict(size=14)),
                side="left",
                range=[0, y1_max],
                tickfont=dict(size=12),
            ),
            yaxis2=dict(
                title=dict(text="연 총 강수량 (mm)", font=dict(size=14)),
                overlaying="y", side="right",
                showgrid=False,
                range=[0, y2_max],
                tickfont=dict(size=12),
            ),
            margin=dict(t=10, b=18, l=50, r=55),
            showlegend=True,
            legend=dict(
                orientation="h", yanchor="bottom", y=1.0,
                xanchor="right", x=1,
                font=dict(size=14),
                bgcolor="rgba(255,255,255,0.5)",
            ),
            font=dict(size=14),
            bargap=0.0,
            plot_bgcolor="white",
        )
        st.plotly_chart(fig, use_container_width=True,
                        key=f"t2_annual_{sn}")


# ==============================================================================
#  ■ 공통 헬퍼
# ==============================================================================
def _legend_row(color, avg_label, act_label):
    def _box(col, outline):
        if outline:
            return f'<span style="width:10px;height:10px;border-radius:2px;border:1.5px solid {col};display:inline-block;"></span>'
        return f'<span style="width:10px;height:10px;border-radius:2px;background:{col};display:inline-block;"></span>'
    return st.markdown(
        f'<span style="font-size:14px;color:var(--color-text-secondary);">'
        f'{_box(color, True)} {avg_label}&nbsp;&nbsp;'
        f'{_box(color, False)} {act_label}</span>',
        unsafe_allow_html=True
    )


def _render_2x2_charts(xlabels, stations, D, act_key, avg_key,
                        unit, avg_name, act_name, key_prefix, decimals=1):
    """4개 지점 차트를 1×4 (한 줄)로 나란히 배치.
    모든 지점 차트의 Y축 범위를 통일 — 지점 간 비교가 가능하도록."""
    def _fmt(v):
        return "" if v is None else f"{v:.{decimals}f}"

    # 전체 지점 값에서 공용 y_max 계산 (약간의 여유 공간 포함)
    all_vals = []
    for s in stations:
        for v in D[s["name"]][act_key] + D[s["name"]][avg_key]:
            if v is not None:
                all_vals.append(v)
    y_max = (max(all_vals) * 1.20) if all_vals else 1

    row = st.columns(len(stations))
    for i, s in enumerate(stations):
        sn  = s["name"]
        col = s["color"]
        target = row[i]
        with target:
            # 제목 15px bold + 1줄 범례
            st.markdown(
                f'<p class="section-title" style="margin:0 0 2px;color:{col};">'
                f'{sn} <span style="font-size:15px;font-weight:500;color:var(--color-text-secondary);">({s["id"]})</span></p>'
                f'<div style="font-size:15px;color:var(--color-text-secondary);margin:0 0 4px;">'
                f'<span style="display:inline-flex;align-items:center;gap:4px;margin-right:12px;">'
                f'<span style="width:10px;height:10px;border-radius:2px;border:1.5px solid {col};display:inline-block;"></span>'
                f'{avg_name}</span>'
                f'<span style="display:inline-flex;align-items:center;gap:4px;">'
                f'<span style="width:10px;height:10px;border-radius:2px;background:{col};display:inline-block;"></span>'
                f'{act_name}</span>'
                f'</div>',
                unsafe_allow_html=True
            )
            fig = go.Figure()
            fig.add_trace(go.Bar(
                name=avg_name, x=xlabels, y=D[sn][avg_key],
                marker=dict(color=theme.hex_alpha(col, 0.18), line=dict(color=col, width=1.5)),
                text=[_fmt(v) for v in D[sn][avg_key]],
                textposition="outside",
                textfont=dict(size=14, color=theme.COLOR_TEXT_SECONDARY),
                cliponaxis=False,
                hovertemplate=f"%{{x}}<br>{avg_name}: %{{y:.1f}} {unit}<extra></extra>",
            ))
            fig.add_trace(go.Bar(
                name=act_name, x=xlabels, y=D[sn][act_key],
                marker=dict(color=col),
                text=[_fmt(v) for v in D[sn][act_key]],
                textposition="outside",
                textfont=dict(size=14, color=theme.COLOR_TEXT_PRIMARY),
                cliponaxis=False,
                hovertemplate=f"%{{x}}<br>{act_name}: %{{y:.1f}} {unit}<extra></extra>",
            ))
            fig.update_layout(
                barmode="group", height=220,
                xaxis_title="", yaxis_title=unit,
                xaxis=dict(tickfont=dict(size=14)),
                yaxis=dict(range=[0, y_max]),   # 4개 지점 Y축 공용 범위
                bargap=0.3, bargroupgap=0.15,
                margin=dict(t=14, b=4, l=30, r=4),
                showlegend=False, font=dict(size=14),
            )
            st.plotly_chart(fig, use_container_width=True, key=f"{key_prefix}_{sn}")


def _render_mkptbl(ps, ps_keys, D, act_key, avg_key, unit, decimals=1, integer=False,
                   metric="강수량"):
    """각 지점을 3개 하위 열(최근/과거 N년 평균/편차)로 분리해 표기.
    metric: '강수량' 또는 '유효강수일수' 등 — 하위 열 레이블 접두사."""
    stations = config.STATIONS_ASOS
    n_rain   = config.RAINFALL_BASELINE_YEARS

    if metric == "강수량":
        sub_cols = [
            f"최근 강수량 ({unit})",
            f"과거 {n_rain}년 평균 ({unit})",
            f"강수량 편차 ({unit})",
        ]
    elif metric == "유효강수일수":
        # 표 제목에 (일) 이 이미 있으므로 하위 열에서는 단위 생략
        sub_cols = [
            "금년 유효강수",
            f"과거 {n_rain}년 유효강수",
            "유효강수일수 편차",
        ]
    else:
        sub_cols = [f"최근 ({unit})", f"과거 {n_rain}년 평균 ({unit})", f"편차 ({unit})"]

    # 헤더: 2단(지점 colspan=3 / 하위열)
    head = (
        '<table style="width:100%;border-collapse:collapse;font-size:17px;">'
        '<thead>'
        '<tr style="background:var(--color-bg-secondary);">'
        '<th rowspan="2" style="padding:6px 8px;border-bottom:1.5px solid #ccc;'
        'text-align:center;vertical-align:middle;min-width:90px;">기간</th>'
    )
    for s in stations:
        head += (
            f'<th colspan="3" style="padding:6px 8px;border-bottom:1px solid #ddd;'
            f'text-align:center;color:{s["color"]};font-size:17px;">'
            f'{s["name"]} <span style="font-size:16px;font-weight:400;color:var(--color-text-secondary);">'
            f'({s["id"]})</span></th>'
        )
    head += '</tr>'
    head += '<tr style="background:var(--color-bg-secondary);">'
    for _s in stations:
        for sc in sub_cols:
            head += (
                f'<th style="padding:4px 6px;border-bottom:1.5px solid #ccc;'
                f'text-align:center;font-size:15px;font-weight:500;color:var(--color-text-secondary);">'
                f'{sc}</th>'
            )
    head += '</tr></thead><tbody>'

    body = ""
    for i, (pk, p) in enumerate(zip(ps_keys, ps)):
        period_td = (
            f'<td style="padding:6px 8px;border-bottom:0.5px solid #eee;text-align:center;">'
            f'<div style="font-size:17px;font-weight:500;">{p["month"]}월</div>'
            f'<div style="font-size:16px;color:var(--color-text-secondary);">({pk})</div>'
            f'</td>'
        )
        row = "<tr>" + period_td
        for s in stations:
            sn  = s["name"]
            a   = D[sn][act_key][i]
            v   = D[sn][avg_key][i]
            a_s = f"{int(round(a))}" if (integer and a is not None) else (f"{a:.{decimals}f}" if a is not None else "–")
            v_s = f"{int(round(v))}" if (integer and v is not None) else (f"{v:.{decimals}f}" if v is not None else "–")
            if a is not None and v is not None:
                d = a - v
                c = theme.COLOR_SUCCESS if d >= 0 else theme.COLOR_DANGER; sg = "+" if d >= 0 else ""
                d_s = f'<span style="color:{c};font-weight:500;">{sg}{d:.{decimals}f}</span>'
            else:
                d_s = "–"
            # 세 개 하위 셀
            row += (
                f'<td style="padding:6px 6px;border-bottom:0.5px solid #eee;text-align:center;'
                f'font-size:17px;font-weight:500;">{a_s}</td>'
                f'<td style="padding:6px 6px;border-bottom:0.5px solid #eee;text-align:center;'
                f'font-size:16px;color:var(--color-text-secondary);">{v_s}</td>'
                f'<td style="padding:6px 6px;border-bottom:0.5px solid #eee;text-align:center;'
                f'font-size:16px;">{d_s}</td>'
            )
        row += "</tr>"
        body += row

    st.markdown(head + body + "</tbody></table>", unsafe_allow_html=True)
