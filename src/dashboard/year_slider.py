# ==============================================================================
#  파일명: src/dashboard/year_slider.py
#  분석 연도 슬라이더 — 1 step = 1 년 폭, max+1 트릭 + 빈 원 마커 + 라벨 교체.
#
#  Source 분리: ag_well_helpers.py 1366줄 → 그룹별 분리 3단계 (2026-05-09).
#    - year_slider(yr_min, yr_max, key, label) -> tuple[int, int]
#
#  호환성: ag_well_helpers.py 가 이 모듈에서 re-export → 기존 호출처
#  (`ag_well_helpers.year_slider(...)`) 그대로 동작.
#  외부 호출: tab12_ag_usage.py, tab22_ag_usage_detail.py 2곳.
# ==============================================================================
from __future__ import annotations

import json

import streamlit as st
import streamlit.components.v1 as _components


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

    # ── CSS v5 (2026-05-16) — v4 의 ::after attr() Edge webview2 버그 해결:
    #
    # v4 실패 원인: `::after content: attr(data-jeju-label)` 가 Edge --app
    #   모드 webview2 에서 attr 변경 시 paint cache 로 update 안 표시.
    #   setAttribute 자체는 성공하지만 화면에 stuck 라벨 ('2021-상~2026-하').
    #   사용자 보고 (2026-05-16): slider 변경 시 라벨이 그대로.
    #
    # v5 해결: ::after attr() 의존 제거. JS 가 thumb-value element 안에
    #   별도 span 을 append + textContent 직접 set → attr() 의존 0.
    st.markdown("""
    <style>
    [data-testid="stSlider"] [data-testid="stTickBarMin"],
    [data-testid="stSlider"] [data-testid="stTickBarMax"] {
        display: none !important;
    }
    [data-testid="stElementContainer"]:has([data-testid="stSlider"]) {
        margin-top: -0.8rem !important;
    }
    /* native text 안 보이게 (color only, layout 영향 0) — JS 가 별도 span
       을 append 해서 우리 라벨 표시. ::after content: attr() 의 Edge
       webview2 paint cache 버그 우회. */
    [data-testid="stSlider"] [data-testid="stSliderThumbValue"] {
        color: transparent !important;
        overflow: visible !important;
    }
    </style>
    """, unsafe_allow_html=True)

    val = st.slider(
        label, min_value=yr_min, max_value=int_max,
        value=default, step=1, key=key,
    )

    # ── 연도 텍스트 라벨 — 슬라이더 바로 아래에 표시.
    # margin-top -10px (이전 -4px) — tick label 을 trackbar 에 더 가깝게.
    # markdown element-container 의 effective box bottom 이 위로 → cascading
    # row 와 거리 확보 (사용자 보고 2026-05-16: '읍/면/동' 라벨이 tick label
    # '2018' 과 같은 vertical level 로 겹쳐 보이던 문제 해소).
    labels = [str(y) for y in range(yr_min, yr_max + 1)] + [""]
    tick_html = (
        '<div style="display:flex;justify-content:space-between;'
        'padding:0 12px;margin-top:-10px;margin-bottom:2px;'
        'font-size:10.5px;color:var(--color-text-secondary);font-weight:500;'
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

          // ① thumb value 라벨 텍스트 변경 — v5: JS overlay span 방식.
          //   v4 의 `::after content: attr(data-jeju-label)` 가 Edge --app
          //   webview2 에서 attr 변경 시 paint update 안 됨 (cache 버그).
          //   v5 는 thumb-value 안에 우리 span 을 append + span.textContent
          //   직접 set → attr() 의존 0.
          const lo = parseInt(thumbs[0].getAttribute('aria-valuenow'), 10);
          const hi = parseInt(thumbs[1].getAttribute('aria-valuenow'), 10);
          const tvs = slider.querySelectorAll('[data-testid="stSliderThumbValue"]');
          if (tvs.length === 2 && Number.isFinite(lo) && Number.isFinite(hi)) {
            const loText = lo + '-01';
            const hiText = (hi - 1) + '-12';
            setOverlayLabel(tvs[0], loText);
            setOverlayLabel(tvs[1], hiText);
          }

          function setOverlayLabel(tv, text) {
            // React 가 children 을 re-mount 할 수 있어 매번 querySelector
            // 로 확인 + 없으면 새로 append. 매 10ms 폴링이 회복.
            let span = tv.querySelector(':scope > span.jeju-thumb-label');
            if (!span) {
              span = D.createElement('span');
              span.className = 'jeju-thumb-label';
              span.style.cssText =
                'position:absolute;'
                + 'left:50%;top:50%;'
                + 'transform:translate(-50%,-50%);'
                + 'color:rgb(255,75,75);'
                + 'white-space:nowrap;'
                + 'font-family:inherit;'
                + 'font-size:inherit;'
                + 'font-weight:600;'
                + 'pointer-events:none;';
              tv.appendChild(span);
            }
            if (span.textContent !== text) span.textContent = text;
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

      // P4-4 (2026-05-29): 폴링 interval/이벤트 바인딩을 SLIDER_KEY 별 namespace
      // 로 분리. 이전엔 전역 W.__yearSliderIv 였어서 두 슬라이더 동시 표시 시
      // 후자가 전자의 interval 을 clearInterval → 첫 슬라이더 라벨 동결 회귀.
      const SLIDER_IV_KEY = '__yearSliderIv_' + SLIDER_KEY;
      const SLIDER_EVT_KEY = '__yearSliderEvtsBound_' + SLIDER_KEY;
      // 폴링 80 → 10ms 가속. drag 시 native int 노출 시간 < 한 frame(16ms).
      if (W[SLIDER_IV_KEY]) clearInterval(W[SLIDER_IV_KEY]);
      update();
      W[SLIDER_IV_KEY] = setInterval(update, 10);

      // drag 종료 즉시 update — streamlit fragment rerun 의 ~100-500ms
      // 공백 동안 native int 가 보이지 않도록 mouseup/pointerup 시 강제 호출.
      // capture: true 로 BaseWeb 의 자체 mouseup 처리 이전에 우리 update.
      if (!W[SLIDER_EVT_KEY]) {
        W[SLIDER_EVT_KEY] = true;
        ['mouseup', 'pointerup', 'touchend'].forEach(ev => {
          W.addEventListener(ev, update, { passive: true, capture: true });
        });
      }

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
