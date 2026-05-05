# ==============================================================================
#  파일명: src/dashboard/ag_well_helpers.py  —  Build 2.0
#  모듈: 농업용 공공관정 탭 4개에서 공유하는 UI 컴포넌트
# ------------------------------------------------------------------------------
#   - filter_widgets()      : 공통 필터 위젯 (관할·수역·용도)
#   - year_slider()         : 분석 연도 슬라이더 + 프리셋
#   - render_well_card()    : 단일 관정 카드 (Spec + 미니차트)
#   - build_search_map()    : folium 마커 지도 (414공)
# ==============================================================================

from __future__ import annotations

import inspect
import json
import re

import folium
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as _components

import config
from src.analysis import ag_well_loader, ag_well_metrics


# ------------------------------------------------------------------------------
#  ■ Fragment-only rerun 헬퍼 — 컨텍스트 가드 포함
# ------------------------------------------------------------------------------
#  st.rerun(scope="fragment") 는 호출자가 @st.fragment 안에 있어야 의미가 있다.
#  fragment 컨텍스트 외부에서 호출하면 streamlit 이 "Couldn't find fragment with
#  id ..." 디버그 로그를 출력하며 결국 full rerun 으로 폴백 → st.tabs 의
#  selected_index 가 0 으로 reset 되어 사용자가 "탭이 점프했다" 고 인지.
#
#  이 헬퍼는:
#    1) streamlit 빌드가 scope="fragment" 를 지원하는지 검사
#    2) 현재 호출 컨텍스트가 fragment 안인지 best-effort 로 판단
#    3) 둘 다 만족하면 fragment-only rerun, 아니면 일반 rerun 으로 폴백
# ------------------------------------------------------------------------------
_HAS_FRAGMENT_SCOPE = "scope" in inspect.signature(st.rerun).parameters


def _in_fragment_context() -> bool:
    """현재 호출 위치가 @st.fragment 함수 안인지 best-effort 판단.

    streamlit 의 ScriptRunContext.current_fragment_id 를 안전하게 조회.
    내부 API 라 버전마다 경로가 다를 수 있어 try/except 로 감쌈.
    """
    try:
        from streamlit.runtime.scriptrunner import get_script_run_ctx
        ctx = get_script_run_ctx()
        if ctx is None:
            return False
        # 다양한 streamlit 버전의 속성명 시도
        for attr in ("current_fragment_id", "fragment_storage", "fragment_id"):
            v = getattr(ctx, attr, None)
            if v:
                return True
        return False
    except Exception:
        return False


def fragment_rerun() -> None:
    """fragment-only rerun. 컨텍스트가 fragment 가 아니면 일반 rerun 으로 폴백."""
    if _HAS_FRAGMENT_SCOPE and _in_fragment_context():
        st.rerun(scope="fragment")
    else:
        st.rerun()


def maybe_recenter_to_selected_well(
    sel_permit: str | None,
    df_master: pd.DataFrame,
    *,
    fingerprint_key: str,
    center_key: str,
    zoom_key: str,
    target_zoom: int = 12,
) -> None:
    """관정이 선택되면 그 관정의 좌표로 지도 중심 이동 + zoom 12 (읍/면/동 사이즈).

    fingerprint 패턴: 같은 permit 으로 계속 호출되어도 한 번만 발동 →
    사용자가 줌 조작한 후 같은 관정을 재클릭해도 강제 zoom 안 됨.
    다른 permit 이 들어올 때만 다시 발동.

    Parameters
    ----------
    sel_permit : 현재 선택된 관정의 permit_no (None 이면 no-op)
    df_master  : permit/lat/lon 조회용 master DataFrame
    fingerprint_key : 탭별 fingerprint 키 (예: "_search_centered_permit")
    center_key      : 탭별 지도 중심 session_state 키 (예: "search_map_center")
    zoom_key        : 탭별 지도 줌 session_state 키 (예: "search_map_zoom")
    target_zoom     : 강제할 줌 레벨 (기본 12 = 읍/면/동 사이즈)

    호출 위치: build_*_map() 직전. session_state 만 갱신하므로 외부 rerun 흐름에 의존.
    """
    if not sel_permit:
        return
    last = st.session_state.get(fingerprint_key)
    if last == sel_permit:
        return  # 이미 그 관정으로 한 번 zoom-in 했음 — 사용자 조작 보존
    if df_master is None or df_master.empty:
        return
    if "permit_no" not in df_master.columns or "lat" not in df_master.columns:
        return
    info = df_master[df_master["permit_no"] == sel_permit]
    if info.empty:
        return
    lat = info.iloc[0].get("lat")
    lon = info.iloc[0].get("lon")
    if pd.notna(lat) and pd.notna(lon):
        st.session_state[center_key] = (float(lat), float(lon))
        st.session_state[zoom_key] = target_zoom
        st.session_state[fingerprint_key] = sel_permit


# ------------------------------------------------------------------------------
#  ■ 공통 필터 위젯
# ------------------------------------------------------------------------------
def filter_widgets(df: pd.DataFrame, key_prefix: str = "ag") -> dict:
    """관할·수역·읍면 필터 위젯 (다른 탭 ⑥⑦⑧ 공통).

    - 관할(시): 항상 ['전체', '제주시', '서귀포시']
    - 읍면 옵션: EUP_DROPDOWN_ORDER 기준 — 제주시 → 서귀포시 순으로 펼침
      (multiselect 라 옵션 표시 순서가 그대로 사용자에게 노출)
    """
    c1, c2, c3 = st.columns([1, 2, 2])

    with c1:
        auth = st.selectbox(
            "관할", options=["전체", "제주시", "서귀포시"],
            key=f"{key_prefix}_auth",
        )

    with c2:
        if "watershed" in df.columns:
            ws_opts = sorted([w for w in df["watershed"].dropna().unique() if w])
        else:
            ws_opts = []
        ws_sel = st.multiselect(
            "수역", options=ws_opts, key=f"{key_prefix}_ws",
            placeholder="(전체)",
        )

    with c3:
        # 공식 통계 순서: 제주시 6개 → 서귀포시 6개
        eup_opts: list[str] = []
        for si in SI_DROPDOWN_LIST:
            eup_opts.extend(EUP_DROPDOWN_ORDER.get(si, []))
        # 중복(동지역) 제거하면서 순서 유지
        seen, ordered = set(), []
        for o in eup_opts:
            if o not in seen:
                seen.add(o)
                ordered.append(o)
        eup_sel = st.multiselect(
            "읍면동", options=ordered, key=f"{key_prefix}_eup",
            placeholder="(전체)",
        )

    auth_key = (
        "seogwipo" if auth == "서귀포시"
        else "jeju" if auth == "제주시"
        else None
    )
    return {"authority": auth_key, "watersheds": ws_sel, "eup": eup_sel}


def apply_filters(df: pd.DataFrame, filters: dict) -> pd.DataFrame:
    """filter_widgets 의 결과를 master DataFrame 에 적용.

    '동지역' 이 선택되면 well_eup 가 '동' 으로 끝나거나 비어있는 행을 모두 매칭.
    """
    out = df.copy()
    if filters.get("authority") and "authority" in out.columns:
        out = out[out["authority"] == filters["authority"]]
    if filters.get("watersheds") and "watershed" in out.columns:
        out = out[out["watershed"].isin(filters["watersheds"])]

    eup_list = filters.get("eup") or []
    if eup_list and "well_eup" in out.columns:
        eup_c = _eup_clean(out["well_eup"])
        wants_dong = "동지역" in eup_list
        explicit = [e for e in eup_list if e != "동지역"]
        mask = pd.Series(False, index=out.index)
        if explicit:
            mask = mask | eup_c.isin(explicit)
        if wants_dong:
            mask = mask | eup_c.str.endswith("동", na=False) | (eup_c == "")
        out = out[mask]
    return out


def _eup_clean(s: pd.Series) -> pd.Series:
    """well_eup 클린업: NaN/공백/'nan'/'None' → 빈 문자열."""
    return (
        s.astype(str).str.strip()
         .replace({"nan": "", "None": "", "NaN": "", "<NA>": ""})
    )


def cascading_location_filters(
    df: pd.DataFrame,
    key_prefix: str = "loc",
    si_label: str = "시",
) -> dict:
    """시 → 읍면동 → 리 의 단계적(cascading) 드롭다운 3 개.

    옵션 정렬 규칙 (드롭다운):
      - 시:   항상 ['전체', '제주시', '서귀포시'] (데이터 유무 무관)
      - 읍면: EUP_DROPDOWN_ORDER 의 공식 통계 순서
              제주시:  한림읍·애월읍·구좌읍·조천읍·한경면·동지역
              서귀포시:대정읍·남원읍·성산읍·안덕면·표선면·동지역
      - 리:   해당 (시, 읍면) 에 속한 리들을 가나다 순

    Parameters
    ----------
    si_label : str
        시 selectbox 의 라벨. 탭별로 '시' / '시 구분' 등 다른 라벨이 필요할 때 지정.

    Returns
    -------
    {'well_si': str|None, 'well_eup': str|None, 'well_ri': str|None}
        '전체' 또는 미선택은 None. '동지역' 은 그대로 문자열로 반환되며
        apply_cascading_filters 에서 '동' 끝나거나 빈 well_eup 으로 매칭.
    """
    work = df.copy() if not df.empty else df

    c1, c2, c3 = st.columns(3)

    # ── 1) 시 (항상 고정 옵션)
    with c1:
        si_opts = ["전체"] + SI_DROPDOWN_LIST
        si_sel = st.selectbox(si_label, si_opts, key=f"{key_prefix}_si")

    # ── 2) 읍/면/동 (시에 따라)
    with c2:
        if si_sel == "전체":
            eup_opts = ["전체"]
        else:
            eup_opts = ["전체"] + EUP_DROPDOWN_ORDER.get(si_sel, [])
        # 시 변경 시 기존 읍 선택이 옵션에 없으면 자동 리셋
        cur = st.session_state.get(f"{key_prefix}_eup", "전체")
        if cur not in eup_opts:
            st.session_state[f"{key_prefix}_eup"] = "전체"
        eup_sel = st.selectbox("읍/면/동", eup_opts, key=f"{key_prefix}_eup")

    # ── 3) 리 (시·읍면 으로 좁힌 데이터에서 추출)
    if not work.empty and si_sel != "전체":
        sub = work[work["well_si"].astype(str).str.strip() == si_sel]
        if eup_sel != "전체":
            eup_clean = _eup_clean(sub["well_eup"])
            if eup_sel == "동지역":
                sub = sub[eup_clean.str.endswith("동", na=False) | (eup_clean == "")]
            else:
                sub = sub[eup_clean == eup_sel]
        ri_opts = ["전체"] + sorted(
            v for v in sub["well_ri"].dropna().astype(str).str.strip().unique() if v
        )
    else:
        ri_opts = ["전체"]

    with c3:
        cur = st.session_state.get(f"{key_prefix}_ri", "전체")
        if cur not in ri_opts:
            st.session_state[f"{key_prefix}_ri"] = "전체"
        ri_sel = st.selectbox("리", ri_opts, key=f"{key_prefix}_ri")

    return {
        "well_si":  None if si_sel  == "전체" else si_sel,
        "well_eup": None if eup_sel == "전체" else eup_sel,
        "well_ri":  None if ri_sel  == "전체" else ri_sel,
    }


def apply_cascading_filters(df: pd.DataFrame, sel: dict) -> pd.DataFrame:
    """cascading_location_filters 의 결과를 master DataFrame 에 적용.

    '동지역' 은 well_eup 이 '동'으로 끝나거나 비어있는 행을 모두 매칭.
    """
    out = df.copy()

    si = sel.get("well_si")
    if si and "well_si" in out.columns:
        out = out[out["well_si"].astype(str).str.strip() == si]

    eup = sel.get("well_eup")
    if eup and "well_eup" in out.columns:
        eup_c = _eup_clean(out["well_eup"])
        if eup == "동지역":
            out = out[eup_c.str.endswith("동", na=False) | (eup_c == "")]
        else:
            out = out[eup_c == eup]

    ri = sel.get("well_ri")
    if ri and "well_ri" in out.columns:
        out = out[out["well_ri"].astype(str).str.strip() == ri]

    return out


# ------------------------------------------------------------------------------
#  ■ 분석 연도 슬라이더 (1 step = 1 년 폭 · max+1 트릭)
# ------------------------------------------------------------------------------
def year_slider(
    yr_min: int,
    yr_max: int,
    key: str = "ag_year_range",
    label: str = "분석 연도",
) -> tuple[int, int]:
    """공통 연도 슬라이더 — 1년 단위가 슬라이더 1칸 폭을 갖도록 max+1 트릭 사용.

    Build 2.3 (2026-05-02):
      - internal 슬라이더 max = yr_max + 1.  사용자가 (yr_max, yr_max+1) 을
        고르면 1년치(= 1칸 폭)로 빨간 영역이 「작은 선」으로 보임.
      - 데이터 필터 범위는 (val[0], val[1] - 1) 로 변환해서 반환.
      - tick label 은 yr_min ~ yr_max 만 표시 (마지막 +1 자리는 빈 칸).
      - Streamlit 자체의 빨간 thumb value 라벨과 양끝 min/max 라벨은 CSS 로 숨김
        — 우리가 caption 으로 「선택 기간: YYYY-01 ~ YYYY-12」 형식으로 표시.
      - 기본값: 최근 1년 (yr_max ~ yr_max+1).
    """
    if yr_min >= yr_max:
        st.caption(f"분석 연도: {yr_min}년 (단일 연도)")
        return (yr_min, yr_max)

    int_max = yr_max + 1

    # 기본값: 최근 1년 (yr_max ~ yr_max+1 → 데이터로는 yr_max 1년치)
    default = st.session_state.get(key, (yr_max, int_max))
    default = (max(yr_min, default[0]), min(int_max, default[1]))
    if default[0] >= default[1]:
        default = (default[0], min(int_max, default[0] + 1))

    # ── CSS: 양끝 min/max tick bar 라벨만 숨김 (yr_max+1 노출 방지).
    #   빨간 thumb value 라벨은 그대로 유지 — 아래 JS 로 텍스트만 「YYYY-01 / YYYY-12」 형식으로 교체.
    st.markdown("""
    <style>
    [data-testid="stSlider"] [data-testid="stTickBarMin"],
    [data-testid="stSlider"] [data-testid="stTickBarMax"] {
        display: none !important;
    }
    </style>
    """, unsafe_allow_html=True)

    val = st.slider(
        label, min_value=yr_min, max_value=int_max,
        value=default, step=1, key=key,
    )

    # ── 연도 텍스트 라벨 — 슬라이더 바로 아래에 표시 (트랙과 가까이 붙임)
    labels = [str(y) for y in range(yr_min, yr_max + 1)] + [""]
    tick_html = (
        '<div style="display:flex;justify-content:space-between;'
        'padding:0 12px;margin-top:-4px;margin-bottom:2px;'
        'font-size:10.5px;color:#5f5e5a;font-weight:500;'
        'pointer-events:none;">'
        + "".join(f'<span style="pointer-events:none;">{lbl}</span>'
                  for lbl in labels)
        + "</div>"
    )
    st.markdown(tick_html, unsafe_allow_html=True)

    # ── 연도 마커(빈 원) — JS 로 슬라이더 트랙 DOM 안에 직접 주입.
    #   설계 결정 (이전 시도들의 교훈):
    #     ① markdown overlay 음수 margin 방식 → left thumb 드래그 차단 발생 (폐기)
    #     ② [data-baseweb="slider"] 를 host 로 사용 → tick bar 영역 포함 폭이라
    #        % 환산이 어긋나 우측 마커 누락 현상 발생 (폐기)
    #     ③ 현재 채택: thumbs 의 실제 부모(trackHost) 를 host. thumbs 와 같은
    #        좌표계라 % 환산이 정확. 추가로 overflow:visible 강제로 우측 끝
    #        마커가 잘리지 않도록 보장.
    #
    #   특징:
    #     - 위치 계산: thumb 두 개의 BoundingClientRect 로 px/단위 캘리브레이션
    #       → BaseWeb 의 padding/margin 영향까지 흡수 (% 단순 계산보다 정확)
    #     - 빨간 thumb 위치(val[0], val[1])는 생략 → 빨간 원이 그대로 보임
    #     - 배경 transparent → 트랙 색이 원 안으로 비쳐 끊김 없음
    #     - top: calc(50% + 1px) → 사용자 요청: 트랙 중앙으로 살짝 내림
    #     - z-index: 2 → 회색/빨간 트랙 bar 위에 확실히 표시
    #     - pointer-events: none → 슬라이더 드래그 이벤트와 절대 충돌 없음
    #     - 200ms 폴링 + 즉시 inject → 슬라이더 rerun 후 빠른 마커 복원
    selected_positions = {int(val[0]), int(val[1])}
    years_to_mark = [
        y for y in range(yr_min, yr_max + 1) if y not in selected_positions
    ]
    _components.html(f"""
    <script>
    (function() {{
      const W = window.parent;
      const D = W.document;
      const SLIDER_KEY = {json.dumps(key)};
      const IV_KEY = '__yearMarkersIv_' + SLIDER_KEY;
      const MIN = {yr_min};
      const MAX = {int_max};
      const YEARS = {json.dumps(years_to_mark)};
      const MARKER_CLS = 'jeju-year-marker-' + SLIDER_KEY;

      function findOurSlider() {{
        const sliders = D.querySelectorAll('[data-testid="stSlider"]');
        for (const s of sliders) {{
          const thumbs = s.querySelectorAll('[role="slider"]');
          if (thumbs.length !== 2) continue;
          const tmin = parseInt(thumbs[0].getAttribute('aria-valuemin'), 10);
          const tmax = parseInt(thumbs[0].getAttribute('aria-valuemax'), 10);
          if (tmin === MIN && tmax === MAX) return s;
        }}
        return null;
      }}

      function inject() {{
        const slider = findOurSlider();
        if (!slider) return;
        const thumbs = slider.querySelectorAll('[role="slider"]');
        if (thumbs.length !== 2) return;

        // ── 호스트 = thumbs 의 직접 부모. thumbs 가 absolute 로 배치된 컨테이너.
        const trackHost = thumbs[0].parentElement;
        if (!trackHost || !trackHost.contains(thumbs[1])) return;

        // ── thumbs 의 실제 px 위치로 좌표계 캘리브레이션
        //   thumb at value v 의 center.x = minPx + (v - MIN) * pxPerUnit
        const v0 = parseInt(thumbs[0].getAttribute('aria-valuenow'), 10);
        const v1 = parseInt(thumbs[1].getAttribute('aria-valuenow'), 10);
        if (!Number.isFinite(v0) || !Number.isFinite(v1) || v0 === v1) return;
        const hostRect = trackHost.getBoundingClientRect();
        const r0 = thumbs[0].getBoundingClientRect();
        const r1 = thumbs[1].getBoundingClientRect();
        const c0 = (r0.left + r0.right) / 2 - hostRect.left;
        const c1 = (r1.left + r1.right) / 2 - hostRect.left;
        const pxPerUnit = (c1 - c0) / (v1 - v0);
        if (!Number.isFinite(pxPerUnit) || pxPerUnit === 0) return;
        const minPx = c0 - (v0 - MIN) * pxPerUnit;

        // ── host 가 position 컨텍스트 + overflow:visible 보장
        const cs = W.getComputedStyle(trackHost);
        if (cs.position === 'static') trackHost.style.position = 'relative';
        if (cs.overflow === 'hidden' || cs.overflowX === 'hidden') {{
          trackHost.style.overflow = 'visible';
        }}

        // ── 기존 마커 모두 제거 후 재생성 (val 변경 반영)
        trackHost.querySelectorAll('.' + MARKER_CLS).forEach(el => el.remove());

        YEARS.forEach(y => {{
          const cx = minPx + (y - MIN) * pxPerUnit;
          const m = D.createElement('span');
          m.className = MARKER_CLS;
          m.style.cssText =
            'position:absolute;'
            + 'left:' + (cx - 9) + 'px;'
            + 'top:calc(50% + 1px);'
            + 'transform:translateY(-50%);'
            + 'width:18px;height:18px;'
            + 'border-radius:50%;'
            + 'border:1.5px solid rgba(26,26,24,0.35);'
            + 'background:transparent;'
            + 'box-sizing:border-box;'
            + 'pointer-events:none;'
            + 'z-index:2;';
          trackHost.appendChild(m);
        }});
      }}

      if (W[IV_KEY]) clearInterval(W[IV_KEY]);
      inject();
      // 200ms 폴링 — Streamlit rerun / 드래그 후 슬라이더 DOM 재구성 시
      // 신속하게 마커 복원. pointer-events:none 이라 부하 거의 없음.
      W[IV_KEY] = setInterval(inject, 200);
    }})();
    </script>
    """, height=0)

    # ── JS: ① thumb 빨간 라벨 텍스트를 「YYYY-01 / YYYY-12」 로 실시간 교체
    #        ② baseweb 의 양 끝 native 라벨(yr_min·yr_max+1)을 hide
    # (CSS 셀렉터가 streamlit 버전마다 달라 안 먹는 케이스 대응 — JS 휴리스틱으로 4자리 숫자 자식 hide)
    _components.html("""
    <script>
    (function() {
      const W = window.parent;
      const D = W.document;

      function update() {
        const sliders = D.querySelectorAll('[data-testid="stSlider"]');
        sliders.forEach(slider => {
          const thumbs = slider.querySelectorAll('[role="slider"]');
          if (thumbs.length !== 2) return;
          const mn = parseInt(thumbs[0].getAttribute('aria-valuemin'), 10);
          const mx = parseInt(thumbs[0].getAttribute('aria-valuemax'), 10);
          // 휴리스틱: 연도 슬라이더 (2000~2035 범위) 만 처리
          if (!(mn >= 2000 && mn <= 2030 && mx <= 2035)) return;

          // ① thumb value 라벨 텍스트 변경
          const lo = parseInt(thumbs[0].getAttribute('aria-valuenow'), 10);
          const hi = parseInt(thumbs[1].getAttribute('aria-valuenow'), 10);
          const tvs = slider.querySelectorAll('[data-testid="stSliderThumbValue"]');
          if (tvs.length === 2 && Number.isFinite(lo) && Number.isFinite(hi)) {
            const loText = lo + '-01';
            const hiText = (hi - 1) + '-12';
            if (tvs[0].textContent !== loText) tvs[0].textContent = loText;
            if (tvs[1].textContent !== hiText) tvs[1].textContent = hiText;
          }

          // ② 양 끝 native min/max 라벨 hide — 4자리 연도 텍스트 가진 모든 div hide
          const candidates = slider.querySelectorAll(
            '[data-testid*="TickBar"], [data-baseweb="slider"] > div'
          );
          candidates.forEach(el => {
            // 직접 자식 또는 자기 자신의 텍스트가 정확히 4자리 숫자면 hide
            Array.from(el.children || []).forEach(c => {
              const t = (c.textContent || '').trim();
              if (/^\\d{4}$/.test(t) && c.style.display !== 'none') {
                c.style.display = 'none';
              }
            });
            const txt = (el.textContent || '').trim();
            if (/^\\d{4}$/.test(txt) && el.children.length === 0
                && el.style.display !== 'none') {
              el.style.display = 'none';
            }
          });
        });
      }

      if (W.__yearSliderIv) clearInterval(W.__yearSliderIv);
      update();
      W.__yearSliderIv = setInterval(update, 80);

      const thumbs = D.querySelectorAll('[data-testid="stSlider"] [role="slider"]');
      thumbs.forEach(t => {
        if (t.dataset.jejuYrSync) return;
        t.dataset.jejuYrSync = '1';
        new MutationObserver(update).observe(t, {
          attributes: true,
          attributeFilter: ['aria-valuenow']
        });
      });
    })();
    </script>
    """, height=0)

    # ── 데이터 필터 범위 변환 (caption 은 호출자가 지역/기간 라인으로 통합 표시)
    year_lo, year_hi = int(val[0]), int(val[1]) - 1
    if year_hi < year_lo:
        year_hi = year_lo

    return (year_lo, year_hi)


# ------------------------------------------------------------------------------
#  ■ 단일 관정 카드 (Spec + 5년 미니차트)
# ------------------------------------------------------------------------------
# master.csv 28개 필드를 5개 섹션으로 그룹핑한 카드 표시 사양
_CARD_SECTIONS: list[tuple[str, list[tuple[str, str, str]]]] = [
    ("기본 정보", [
        ("permit_no",     "허가번호",   ""),
        ("well_id",       "관정명",     ""),
        ("active",        "운영",       ""),
        ("water_management","수리계",   ""),
        ("watershed",     "수역",       ""),
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
        f'<div style="font-size:14px;font-weight:600;color:#185fa5;'
        f'padding:6px 0;border-top:1px solid rgba(26,26,24,0.15);'
        f'margin-top:8px;">{title}</div>',
        unsafe_allow_html=True,
    )

    # ── 5개 섹션을 가로 5칼럼으로 배치 (각 섹션 = 한 컬럼)
    cols = st.columns(len(_CARD_SECTIONS))
    for col, (section_title, fields) in zip(cols, _CARD_SECTIONS):
        with col:
            html = [
                f'<div style="font-size:11px;font-weight:600;color:#185fa5;'
                f'border-bottom:0.5px solid #85b7eb;padding-bottom:2px;'
                f'margin-bottom:4px;">{section_title}</div>',
                '<div style="font-size:11.5px;line-height:1.6;">',
            ]
            for key, label, unit in fields:
                v_text = _format_card_value(key, info.get(key))
                if v_text not in ("-", "") and unit:
                    v_text = f"{v_text} {unit}"
                html.append(
                    f'<div><span style="color:#5f5e5a;display:inline-block;'
                    f'width:84px;">{label}</span>'
                    f'<span style="color:#1a1a18;font-weight:500;">{v_text}</span></div>'
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
                marker_color="#305496",
                text=[f"{int(v):,}" if pd.notna(v) else ""
                      for v in summary["volume_m3"]],
                textposition="outside", textfont=dict(size=9),
            ))
            fig.update_layout(
                title=f"연 이용량 — 최근 {last_n_years}년 (㎥)",
                title_font_size=11,
                height=210, margin=dict(l=10, r=10, t=30, b=20),
                yaxis_title=None, xaxis_title=None,
                showlegend=False, plot_bgcolor="white",
            )
            fig.update_xaxes(tickvals=summary["year"], tickfont=dict(size=10))
            fig.update_yaxes(tickfont=dict(size=9))
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
                title_font_size=11,
                height=210, margin=dict(l=10, r=10, t=30, b=20),
                showlegend=False, plot_bgcolor="white",
            )
            fig.update_xaxes(tickfont=dict(size=8), tickangle=-45)
            fig.update_yaxes(tickfont=dict(size=9))
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
                mode="lines+markers", line=dict(color="#C00000", width=2),
                marker=dict(size=6),
            ))
            std = config.WATER_QUALITY_STANDARDS["nitrate_n"].get("max")
            if std is not None:
                fig.add_hline(y=std, line_dash="dot", line_color="#7F7F7F",
                              annotation_text=f"기준 ≤ {std}",
                              annotation_font_size=9)
            fig.update_layout(
                title="수질 NO3 — 보유 기간 전체 (mg/L)",
                title_font_size=11,
                height=210, margin=dict(l=10, r=10, t=30, b=20),
                showlegend=False, plot_bgcolor="white",
            )
            fig.update_xaxes(tickfont=dict(size=8), tickangle=-45)
            fig.update_yaxes(tickfont=dict(size=9))
            st.plotly_chart(fig, use_container_width=True)


def _fmt_num(v, unit: str = "") -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "-"
    try:
        f = float(v)
        if f.is_integer():
            return f"{int(f):,} {unit}".strip()
        return f"{f:,.1f} {unit}".strip()
    except (TypeError, ValueError):
        return f"{v} {unit}".strip()


# ------------------------------------------------------------------------------
#  ■ 검색 지도 (414공 마커 + MarkerCluster)
# ------------------------------------------------------------------------------
def build_search_map(
    df: pd.DataFrame,
    selected_permit: str | None = None,
    height: int = 480,
    zoom: int = 11,
    center: tuple[float, float] = (33.38, 126.55),
) -> folium.Map:
    """관정 마커 지도.

    Build 2.x: zoom·center 인자를 받아 사용자가 마지막으로 본 위치를 복원
    (tab7/tab8 패턴과 일관). 호출자가 session_state 에 보존된 값을 전달.
    """
    from src.dashboard.map_helpers import make_map

    m = make_map(center=center, zoom=zoom)

    if df.empty:
        return m

    # 좌표 보유 관정만
    df_xy = df.dropna(subset=["lat", "lon"]).copy()
    if df_xy.empty:
        return m

    # NOTE: MarkerCluster 사용 시 외부 leaflet.markercluster 플러그인이
    # CDN 에서 로드되어야 하는데, 일부 환경에서 실패해 마커가 보이지 않는
    # 문제가 있어 제거. 887개 정도면 Leaflet 본체로 충분히 처리됨.
    # ── popup HTML 은 2줄 — 관정명 / 읍면 리. 허가번호는 생략(상세는 하단 카드).
    def _clean(v) -> str:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return ""
        s = str(v).strip()
        return "" if s in ("nan", "None", "NaN", "<NA>") else s

    for _, r in df_xy.iterrows():
        permit = r.get("permit_no") or ""
        well_id = r.get("well_id") or permit
        is_sel = (permit == selected_permit) if selected_permit else False

        # 마커 hit-area 개선 (사용자 호소 #4) — radius 비선택 5→7, 선택 9→12.
        # 농업용·관측소(map_helpers.py) 모두 선택=12 로 통일.
        # weight 1.2→2 도 함께 올려 stroke 절반이 외측 hit-area 로 추가됨
        # (시각 차이는 미미하나 클릭 정밀도 큰 개선).
        radius = 12 if is_sel else 7
        auth = r.get("authority") or ""
        palette = getattr(config, "AG_PALETTE", {"seogwipo": "#C65911", "jeju": "#305496"})
        color = palette.get(auth, "#7F7F7F")
        edge  = "#C00000" if is_sel else color

        # 2줄 구성: 관정명(굵게) / 읍면 리
        loc_parts = [_clean(r.get("well_eup")), _clean(r.get("well_ri"))]
        loc = " ".join(p for p in loc_parts if p)
        loc_line = (
            f'<br><span style="color:#1a1a18;font-size:11px;">{loc}</span>'
            if loc else ""
        )

        # 숨김 span 으로 permit_no 를 popup HTML 에 포함 → 클릭 시 파싱용
        # (사용자에게는 보이지 않음, parse_clicked_popup 정규식이 추출)
        popup_html = (
            f'<div style="font-size:12px;line-height:1.45;min-width:130px;">'
            f'<b>{well_id}</b>{loc_line}'
            f'<span style="display:none;">{permit}</span></div>'
        )
        folium.CircleMarker(
            location=[r["lat"], r["lon"]],
            radius=radius,
            color=edge, weight=3 if is_sel else 2,
            fill=True, fill_color=color,
            fill_opacity=0.85 if is_sel else 0.7,
            # tooltip = well_id 만. 허가번호는 사용자에게 노출하지 않음.
            # well_id 결측 row 는 master.csv 에 0건이지만 안전 fallback 유지.
            tooltip=well_id or permit,
            popup=folium.Popup(popup_html, max_width=180),
        ).add_to(m)

    return m


def build_usage_map(
    df_master: pd.DataFrame,
    df_usage_by_well: pd.DataFrame,
    selected_permit: str | None = None,
    height: int = 480,
    legend_unit: str = "관정별 일평균 사용량 (㎥/일)",
    zoom: int = 11,
    center: tuple[float, float] = (33.38, 126.55),
) -> folium.Map:
    """이용량 분석용 지도 — 크기는 총 이용량, 색상은 일평균 사용량 그라디언트.

    Build 2.4 (2026-05-02):
      - 마커 색상: authority 무관, 일평균 사용량(daily_avg) 기반
        하늘색(#AFDBF5) → 다크블루(#0A316E) 그라디언트 (sqrt 스케일).
      - 좌하단 Legend: 단위 명시 + min/max 값 표시.
      - zoom/center: 호출자가 마지막 줌·중심을 전달하면 그 위치로 마운트.
    """
    from src.dashboard.map_helpers import make_map

    m = make_map(center=center, zoom=zoom)

    if df_master.empty:
        return m

    df_xy = df_master.dropna(subset=["lat", "lon"]).copy()
    if df_xy.empty:
        return m

    # 이용량 left join
    use_cols = ["permit_no", "volume_m3"]
    if "daily_avg" in df_usage_by_well.columns:
        use_cols.append("daily_avg")
    if not df_usage_by_well.empty:
        df_xy = df_xy.merge(
            df_usage_by_well[use_cols], on="permit_no", how="left",
        )
    else:
        df_xy["volume_m3"] = 0
        df_xy["daily_avg"] = 0

    df_xy["volume_m3"] = pd.to_numeric(df_xy["volume_m3"], errors="coerce").fillna(0)
    if "daily_avg" in df_xy.columns:
        df_xy["daily_avg"] = pd.to_numeric(df_xy["daily_avg"], errors="coerce").fillna(0)
    else:
        df_xy["daily_avg"] = 0

    # 사용자 요청 #8 (Build 2.7): 마커 크기·색상을 「일평균 사용량 기준 6단계」.
    # 사용자 요청 (Build 2.8): 가장 작은 단계가 너무 작아 클릭하기 어려움 →
    #   모든 단계의 multiplier 를 한 단계씩 위로 올림.
    #   이전: [1/3, 2/3, 1, 4/3, 5/3, 2]   → 가장 작은 = 1/3 × 6 = 2.0px
    #   현재: [2/3, 1, 4/3, 5/3, 2, 7/3]   → 가장 작은 = 2/3 × 6 = 4.0px (한 단계 ↑)
    LEGEND_MIN = 0.0
    LEGEND_MAX = 1200.0
    BIN_BOUNDS = [200.0, 400.0, 600.0, 800.0, 1000.0, 1200.0]   # 6 buckets

    SIZE_MULTIPLIERS = [2/3, 1.0, 4/3, 5/3, 2.0, 7/3]
    BASE_RADIUS = 6.0
    NO_DATA_COLOR = "#CDD8DF"

    # 6단계 이산 색상 — 6BAED6 (라이트) → 08306B (다크) 사이를 균등 보간.
    LIGHT_RGB = (107, 174, 214)
    DARK_RGB = (8, 48, 107)
    BIN_COLORS: list[str] = []
    for i in range(6):
        t = i / 5.0   # 0, 0.2, 0.4, 0.6, 0.8, 1.0
        r = int(LIGHT_RGB[0] + (DARK_RGB[0] - LIGHT_RGB[0]) * t)
        g = int(LIGHT_RGB[1] + (DARK_RGB[1] - LIGHT_RGB[1]) * t)
        b = int(LIGHT_RGB[2] + (DARK_RGB[2] - LIGHT_RGB[2]) * t)
        BIN_COLORS.append(f"#{r:02X}{g:02X}{b:02X}")

    def _bin_idx(d: float) -> int | None:
        if d is None or d <= 0:
            return None
        for i, b in enumerate(BIN_BOUNDS):
            if d < b:
                return i
        return 5   # ≥ 1000 → 가장 진한 색

    def _radius(d: float) -> float:
        idx = _bin_idx(d)
        if idx is None:
            return BASE_RADIUS * 0.5    # 자료 없음 — 작은 회색 점
        return BASE_RADIUS * SIZE_MULTIPLIERS[idx]

    def _color(d: float) -> str:
        idx = _bin_idx(d)
        return NO_DATA_COLOR if idx is None else BIN_COLORS[idx]

    def _clean(v) -> str:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return ""
        s = str(v).strip()
        return "" if s in ("nan", "None", "NaN", "<NA>") else s

    for _, r in df_xy.iterrows():
        permit = r.get("permit_no") or ""
        well_id = r.get("well_id") or permit
        vol = float(r["volume_m3"])
        daily = float(r.get("daily_avg") or 0)
        is_sel = (permit == selected_permit) if selected_permit else False
        # 6단계 binning: 크기·색상 모두 일평균 사용량 기준 (요청 #8)
        radius = _radius(daily)
        if is_sel:
            radius = max(radius, BASE_RADIUS) * 1.3

        fill = _color(daily)
        # 사용자 요청: 선택 마커 = 두꺼운 검정 외곽선 (수질 탭과 일관성)
        edge = "#000000" if is_sel else fill

        loc_parts = [_clean(r.get("well_eup")), _clean(r.get("well_ri"))]
        loc = " ".join(p for p in loc_parts if p)
        loc_line = (
            f'<br><span style="color:#1a1a18;font-size:11px;">{loc}</span>'
            if loc else ""
        )
        if vol > 0:
            stat_line = (
                f'<br><span style="color:#185fa5;font-size:11px;">'
                f'기간 합계: {vol:,.0f} ㎥</span>'
                f'<br><span style="color:#185fa5;font-size:11px;">'
                f'평균 일 사용량: {daily:,.0f} ㎥/일</span>'
            )
        else:
            stat_line = (
                '<br><span style="color:#7F7F7F;font-size:11px;">자료 없음</span>'
            )

        popup_html = (
            f'<div style="font-size:12px;line-height:1.45;min-width:160px;">'
            f'<b>{well_id}</b>{loc_line}{stat_line}'
            f'<span style="display:none;">{permit}</span></div>'
        )
        folium.CircleMarker(
            location=[r["lat"], r["lon"]],
            radius=radius,
            color=edge, weight=5 if is_sel else 1.0,
            fill=True, fill_color=fill,
            fill_opacity=0.92,   # 색상 그라디언트가 더 선명하게 드러나도록 ↑
            tooltip=well_id or permit,
            popup=folium.Popup(popup_html, max_width=220),
        ).add_to(m)

    # ── Legend (좌하단) — 6단계 이산 bin (0~1200 ㎥/일).
    #   각 bin 색상 + 경계값 정수 라벨. 거리 범례와 안 부딪히게 bottom 위로.
    swatches = "".join(
        f'<div style="display:inline-block;width:32px;height:12px;'
        f'background:{c};border:0.5px solid rgba(0,0,0,0.18);"></div>'
        for c in BIN_COLORS
    )
    legend_html = f"""
    <div style="
        position: absolute;
        bottom: 80px; left: 60px;
        z-index: 1000;
        background: rgba(255, 255, 255, 0.95);
        padding: 8px 12px;
        border-radius: 6px;
        border: 0.5px solid rgba(0, 0, 0, 0.18);
        box-shadow: 0 1px 4px rgba(0,0,0,0.12);
        font-size: 11px;
        color: #1a1a18;
    ">
      <div style="font-weight:600;margin-bottom:4px;color:#185fa5;">{legend_unit}</div>
      <div style="display:flex;gap:0;width:192px;">{swatches}</div>
      <div style="display:flex;font-size:10px;color:#5f5e5a;
                  width:192px;justify-content:space-between;margin-top:1px;">
        <span>0</span>
        <span>200</span>
        <span>400</span>
        <span>600</span>
        <span>800</span>
        <span>1,000</span>
        <span>1,200+</span>
      </div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))

    return m


_PERMIT_RE = re.compile(r"([A-Z]\d{6,})")


# ------------------------------------------------------------------------------
#  ■ 시·구분별 관정 수 요약 표 (검색 탭 상단)
# ------------------------------------------------------------------------------
# ============================================================================
#  ■ 정렬 상수 — 프로그램 전체에서 공통 사용
# ----------------------------------------------------------------------------
#  두 가지 순서 규칙을 분리:
#   (A) 표(위치 기반, 서→동): 가로형 카운트 표·시각 분포에 사용
#   (B) 드롭다운(공식 통계 순): 셀렉트박스·다중선택 옵션 순서에 사용
# ============================================================================

# (A) 표: 위치 기반 (서 → 동, 해안선 따라)
WELL_COUNT_TABLE_STRUCTURE: list[tuple[str, str]] = [
    # 제주시 (북서 → 북동)
    ("제주시",   "한경면"),
    ("제주시",   "한림읍"),
    ("제주시",   "애월읍"),
    ("제주시",   "제주동지역"),
    ("제주시",   "조천읍"),
    ("제주시",   "구좌읍"),
    # 서귀포시 (남서 → 남동)
    ("서귀포시", "대정읍"),
    ("서귀포시", "안덕면"),
    ("서귀포시", "서귀포동지역"),
    ("서귀포시", "남원읍"),
    ("서귀포시", "표선면"),
    ("서귀포시", "성산읍"),
]

# (B) 드롭다운: 공식 통계 순서
SI_DROPDOWN_LIST: list[str] = ["제주시", "서귀포시"]
EUP_DROPDOWN_ORDER: dict[str, list[str]] = {
    "제주시":   ["한림읍", "애월읍", "구좌읍", "조천읍", "한경면", "동지역"],
    "서귀포시": ["대정읍", "남원읍", "성산읍", "안덕면", "표선면", "동지역"],
}


def compute_well_count_summary(df: pd.DataFrame) -> pd.DataFrame:
    """시·구분별 관정 수 — 12행 고정 long format + 시 소계 + 총합계.

    카운트는 _well_counts_dict 로 동적 산출.
    (가로 wide format 표는 render_well_count_table 에서 직접 렌더.)
    """
    counts = _well_counts_dict(df)

    rows: list[dict] = []
    prev_si: str | None = None
    for si, gubun in WELL_COUNT_TABLE_STRUCTURE:
        # 시 전환 시 직전 시의 소계 행 삽입
        if prev_si is not None and si != prev_si:
            sub = sum(c for (s, _g), c in counts.items() if s == prev_si)
            rows.append({"시": f"{prev_si} 소계", "구분": "", "관정 수": sub})
        rows.append({"시": si, "구분": gubun, "관정 수": counts[(si, gubun)]})
        prev_si = si

    if prev_si is not None:
        sub = sum(c for (s, _g), c in counts.items() if s == prev_si)
        rows.append({"시": f"{prev_si} 소계", "구분": "", "관정 수": sub})

    rows.append({"시": "총합계", "구분": "",
                 "관정 수": int(sum(counts.values()))})
    return pd.DataFrame(rows)


def _well_counts_dict(df: pd.DataFrame) -> dict[tuple[str, str], int]:
    """(시, 구분) → 관정 수 dict.

    매칭 규칙:
      - '동지역' 구분: 해당 시의 관정 중 well_eup 가
          (1) '동'으로 끝나거나 (예: 강정동, 동홍동 — 서귀포시 동지역)
          (2) 비어있음/NaN (예: 제주시 도심 동지역은 well_eup 미기재)
      - 그 외 (읍·면): well_eup 가 정확히 일치
    """
    counts: dict[tuple[str, str], int] = {}
    if df.empty or "well_si" not in df.columns:
        for si, gubun in WELL_COUNT_TABLE_STRUCTURE:
            counts[(si, gubun)] = 0
        return counts

    work = df.copy()
    work["well_si"] = work["well_si"].astype(str).str.strip()
    # NaN 보존을 위해 별도 클린 컬럼 사용 ('nan'/'None' 문자열도 빈값 처리)
    eup_clean = (
        work["well_eup"].astype(str).str.strip()
            .replace({"nan": "", "None": "", "NaN": ""})
    )

    for si, gubun in WELL_COUNT_TABLE_STRUCTURE:
        if gubun.endswith("동지역"):
            m = (work["well_si"] == si) & (
                eup_clean.str.endswith("동", na=False) | (eup_clean == "")
            )
        else:
            m = (work["well_si"] == si) & (eup_clean == gubun)
        counts[(si, gubun)] = int(m.sum())
    return counts


def render_well_count_table(df: pd.DataFrame) -> None:
    """시별로 한 줄 — 읍·면·동지역이 가로(컬럼) 방향으로 펼쳐지는 표.

    Build 3.x:
      - 모든 셀 숫자에 "공" 단위 부착
      - 표의 맨 끝 칸 (extra 컬럼) 추가:
          제주시 행: 「총합계 / 887공」
          서귀포시 행: 「기준년도 / 2025년」
      - 하단 별도 총합계 박스 제거 (표에 통합)
    """
    counts = _well_counts_dict(df)

    jeju_cols = [g for s, g in WELL_COUNT_TABLE_STRUCTURE if s == "제주시"]
    seog_cols = [g for s, g in WELL_COUNT_TABLE_STRUCTURE if s == "서귀포시"]

    jeju_sub = sum(counts[("제주시", g)] for g in jeju_cols)
    seog_sub = sum(counts[("서귀포시", g)] for g in seog_cols)
    grand = jeju_sub + seog_sub

    # 기준연도 — config 의 농업용 관정 사후관리 자료 마지막 연도
    base_year = getattr(config, "AG_USAGE_YEAR_RANGE", (2017, 2025))[1]

    def _render_one(
        si: str, columns: list[str], subtotal: int,
        extra_label: str, extra_value: str,
    ) -> str:
        # 폭 비율: 시 라벨 14% / 6 읍면 각 ~10.7% / 소계 10% / extra 12% = 100%
        n_cols = len(columns)
        eup_w = (100 - 14 - 10 - 12) / n_cols   # ≈ 10.67% (n_cols=6)
        colgroup = (
            "<colgroup>"
            '<col style="width:14%;">'
            + "".join(f'<col style="width:{eup_w:.4f}%;">' for _ in columns)
            + '<col style="width:10%;">'
            + '<col style="width:12%;">'
            + "</colgroup>"
        )

        # ── 헤더 행: 시 셀 rowspan=2
        thead = ['<thead><tr style="background:#e6f1fb;color:#185fa5;">']
        thead.append(
            f'<th rowspan="2" style="padding:6px 10px;text-align:center;'
            f'border:0.5px solid #85b7eb;font-weight:700;font-size:13px;'
            f'background:#f5f5f3;color:#185fa5;vertical-align:middle;">'
            f'{si}</th>'
        )
        for col in columns:
            thead.append(
                f'<th style="padding:6px 4px;text-align:center;'
                f'border:0.5px solid #85b7eb;font-weight:600;'
                f'white-space:nowrap;">{col}</th>'
            )
        thead.append(
            '<th style="padding:6px 8px;text-align:center;'
            'border:0.5px solid #85b7eb;font-weight:600;'
            'background:#d7e6f5;">소계</th>'
        )
        # extra 헤더 — 제주시는 "총합계", 서귀포시는 "기준년도"
        thead.append(
            f'<th style="padding:6px 8px;text-align:center;'
            f'border:0.5px solid #85b7eb;font-weight:700;'
            f'background:#185fa5;color:#fff;">{extra_label}</th>'
        )
        thead.append("</tr>")

        # ── 데이터 행
        tds = ["<tr>"]
        for col in columns:
            cnt = counts[(si, col)]
            text = "" if cnt == 0 else f"{cnt:,}공"
            tds.append(
                f'<td style="padding:6px 4px;text-align:center;'
                f'border:0.5px solid rgba(26,26,24,0.15);">{text}</td>'
            )
        sub_text = "" if subtotal == 0 else f"{subtotal:,}공"
        tds.append(
            f'<td style="padding:6px 8px;text-align:center;font-weight:700;'
            f'background:#e6f1fb;color:#185fa5;'
            f'border:0.5px solid rgba(26,26,24,0.15);">{sub_text}</td>'
        )
        # extra 데이터 — 제주시 행: 887공, 서귀포시 행: 2025년
        tds.append(
            f'<td style="padding:6px 8px;text-align:center;font-weight:700;'
            f'background:#185fa5;color:#fff;'
            f'border:0.5px solid rgba(26,26,24,0.15);">{extra_value}</td>'
        )
        tds.append("</tr></thead>")

        return (
            '<table style="width:100%;border-collapse:collapse;font-size:12px;'
            'table-layout:fixed;'
            'border:0.5px solid rgba(26,26,24,0.15);border-radius:6px;'
            'overflow:hidden;margin-bottom:8px;">'
            + colgroup + "".join(thead) + "".join(tds) + "</table>"
        )

    # 제주시 (위): 끝 칸 = 총합계 / 887공
    grand_text = "" if grand == 0 else f"{grand:,}공"
    st.markdown(
        _render_one("제주시", jeju_cols, jeju_sub,
                    extra_label="총합계", extra_value=grand_text),
        unsafe_allow_html=True,
    )
    # 서귀포시 (아래): 끝 칸 = 기준년도 / 2025년
    st.markdown(
        _render_one("서귀포시", seog_cols, seog_sub,
                    extra_label="기준년도", extra_value=f"{base_year}년"),
        unsafe_allow_html=True,
    )


def parse_clicked_popup(popup_html: str | None) -> str | None:
    """(폴백) popup HTML 에서 permit_no 추출 — tooltip 방식 실패 시 사용.

    주의: streamlit-folium 0.27.x 는 popup 컨텐츠를 .innerText 형식으로
          반환하는 것으로 보여, popup 안의 <span style='display:none;'>…</span>
          숨김 텍스트가 떨어져 나갈 수 있음. 따라서 신뢰도 낮은 폴백.
    """
    if not popup_html:
        return None
    m = _PERMIT_RE.search(str(popup_html))
    return m.group(1) if m else None


def lookup_permit_by_well_id(
    well_id: str | None,
    df: "pd.DataFrame | None",
) -> str | None:
    """tooltip 문자열에서 permit_no 추출.

    현재 tooltip 은 `well_id` 단독. 다만 well_id 결측 row 의 fallback 으로
    permit_no 가 들어올 수 있고, 구 형식 `{well_id}|{permit_no}` 도 호환.

    분기 순서 (우선순위):
      1) well_id 컬럼 정확 매칭 — 가장 일반적 경로 (master.csv 99%+ 의 클릭이 여기 처리)
      2) PERMIT 정규식 직접 매칭 — well_id 결측 row 의 fallback tooltip
      3) `|` split 마지막 토큰의 PERMIT 매칭 — 구 형식 호환
    """
    if not well_id:
        return None
    text = str(well_id).strip()
    if not text:
        return None

    # 새 tooltip 은 `|` 가 없는 well_id 단독. 구 형식 호환을 위해 분리해 둠.
    well_id_clean = text.split("|", 1)[0].strip() if "|" in text else text

    # (1) well_id 컬럼 매칭 — 1순위
    if (df is not None and not df.empty
            and "well_id" in df.columns and "permit_no" in df.columns
            and well_id_clean):
        match = df[df["well_id"].astype(str).str.strip() == well_id_clean]
        if len(match) >= 1:
            return str(match.iloc[0]["permit_no"])

    # (2) PERMIT 정규식 매칭 — well_id 결측 row 의 fallback tooltip
    m = _PERMIT_RE.search(text)
    if m:
        return m.group(1)

    # (3) `|` split 마지막 토큰 — 구 형식 호환
    if "|" in text:
        last = text.rsplit("|", 1)[-1].strip()
        m = _PERMIT_RE.fullmatch(last)
        if m:
            return m.group(1)

    return None
