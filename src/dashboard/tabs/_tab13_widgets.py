# ==============================================================================
#  파일명: src/dashboard/tabs/_tab13_widgets.py
#  ⑦ 수질 분석 탭 — 반기 슬라이더 위젯 (int 기반 + JS overlay)
#
#  Source 분리: tab13_ag_quality.py 2101줄 → 그룹별 분리 2단계 (2026-05-09).
#    - _half_year_slider : 반기 단위 슬라이더 — 빈 원 마커 + YYYY-상/하 라벨
#
#  외부 사용처: tab13_ag_quality.py 내부 전용.
# ==============================================================================
from __future__ import annotations

import json

import streamlit as st
import streamlit.components.v1 as _components


# ==============================================================================
#  반기 슬라이더 — int 기반 (max 호환성, 외부 React 컴포넌트 의존 X)
# ==============================================================================
def _half_year_slider(
    yr_min: int, yr_max: int, key: str = "qty_yh_range_int",
) -> "tuple[tuple[int, str], tuple[int, str]]":
    """반기 단위 슬라이더 — 이용량 탭의 year_slider 시각 스타일을 차용.

    구성:
      - st.slider(int): 0~N-1 (각 단위 = 1반기)
      - 트랙 위 빈 원 마커 (선택 안 된 위치) — JS 주입
      - 썸 라벨을 「YYYY-상 / YYYY-하」 로 교체 — JS
      - 트랙 아래 연도 라벨 (상 위치에 연도 표시, 하 위치는 작은 "하")
      - 양 끝 native min/max 라벨 숨김 — CSS

    설계 결정 — select_slider(tuple options) 는 BaseWeb 슬라이더의 null
    참조 에러를 일으켜 사용 불가. primitive int 슬라이더 + JS overlay 로 우회.
    """
    n = (yr_max - yr_min + 1) * 2
    if n <= 0:
        return ((yr_min, "상"), (yr_min, "상"))

    def idx_to_yh(i: int) -> "tuple[int, str]":
        i = max(0, min(n - 1, int(i)))
        return (yr_min + i // 2, "상" if i % 2 == 0 else "하")

    # default = 최근 6 반기 (3년)
    default_lo = max(0, n - 6)
    default_hi = n - 1

    cur = st.session_state.get(key)
    valid = (
        isinstance(cur, (tuple, list)) and len(cur) == 2
        and all(isinstance(x, int) and 0 <= x < n for x in cur)
        and cur[0] <= cur[1]
    )
    if not valid:
        if key in st.session_state:
            del st.session_state[key]
        st.session_state[key] = (default_lo, default_hi)

    # ── CSS: native min/max tick bar 라벨 숨김 (요청 #3 — "0 / 23" 제거)
    #
    # ── 위치 fix (v3, 2026-05-16) — 사용자 보고:
    #   1) slider widget label 이 selectbox label 보다 아래에 위치 → row
    #      baseline 어긋남. 원인: thumb-value 라벨이 트랙 위 absolute 로
    #      떠 있어 widget 컨테이너 위쪽에 16-20px 빈 공간 존재.
    #      해결: element-container 음수 margin(-0.8rem) 으로 끌어올림.
    #
    #   2) 트랙 아래 연도 라벨(2014~2026) 이 next row "리" 와 겹침. 원인:
    #      c3 (slider) 의 vertical 끝(tick_html bottom) 이 c1/c2 (selectbox)
    #      끝보다 아래. row-pair-tight 의 -2.0rem 이 c1/c2 기준이라 부족.
    #      해결: tick_html margin-top -6 → -12px 로 트랙에 더 가깝게 끌어
    #      올림 → c3 끝이 c1/c2 끝과 일치 → cascading row 안 겹침.
    #
    #   race fix 는 JS 폴링 가속(30→10ms) + mouseup listener 로 별도 처리
    #   — CSS 는 BaseWeb native 좌표 건드리지 않아 부작용 0.
    st.markdown("""
    <style>
    [data-testid="stSlider"] [data-testid="stTickBarMin"],
    [data-testid="stSlider"] [data-testid="stTickBarMax"],
    [data-testid="stSlider"] [data-testid="stSliderTickBarMin"],
    [data-testid="stSlider"] [data-testid="stSliderTickBarMax"],
    [data-testid="stSlider"] [class*="TickBarMin"],
    [data-testid="stSlider"] [class*="TickBarMax"] {
        display: none !important;
    }
    [data-testid="stElementContainer"]:has([data-testid="stSlider"]) {
        margin-top: -0.8rem !important;
    }
    /* v9 final (2026-05-17) — 마지막 시도, year_slider.py 와 100% 동일 패턴.
       이전 v4~v8 의 color:transparent + overlay span 모두 제거. native
       textContent 직접 override 만 사용. */
    </style>
    """, unsafe_allow_html=True)

    val = st.slider(
        "분석 기간 (반기)",
        min_value=0, max_value=n - 1,
        step=1, key=key,
    )

    if isinstance(val, (tuple, list)) and len(val) == 2:
        lo_i, hi_i = int(val[0]), int(val[1])
    else:
        lo_i = hi_i = int(val)

    # ── 트랙 아래 라벨: 사용자 요청 #1 — 상반기 자리에 "YYYY", 하반기 자리는 빈칸.
    #   빈 원 마커가 위치를 알려주므로 라벨은 연도만 충분.
    labels: list[str] = []
    for i in range(n):
        y, h = idx_to_yh(i)
        labels.append(str(y) if h == "상" else "")
    # margin-top -20px (이전 -12px, 더 이전 -6px) — tick label 을 trackbar
    # 와 거의 붙도록 더 강한 음수. markdown element-container 의 effective
    # box bottom 이 위로 → cascading row 의 widget label 과 거리 확보.
    # (사용자 보고 2026-05-16: '리' 라벨이 tick label '2020' 과 같은 vertical
    # level 로 겹쳐 보이던 문제 — c3 의 visual bottom 을 위로 올려 해소.)
    tick_html = (
        '<div style="display:flex;justify-content:space-between;'
        'padding:0 12px;margin-top:-20px;margin-bottom:2px;'
        'font-size:14px;color:var(--color-text-secondary);font-weight:500;'
        'pointer-events:none;">'
        + "".join(f'<span style="pointer-events:none;">{lbl}</span>'
                  for lbl in labels)
        + "</div>"
    )
    st.markdown(tick_html, unsafe_allow_html=True)

    # ── JS ① 트랙 위 빈 원 마커 (선택 영역 외 모든 위치)
    selected = {lo_i, hi_i}
    marker_indices = [i for i in range(n) if i not in selected]
    _components.html(f"""
    <script>
    (function() {{
      const W = window.parent;
      const D = W.document;
      const SLIDER_KEY = {json.dumps(key)};
      const IV_KEY = '__halfYrMarkersIv_' + SLIDER_KEY;
      const N = {n};
      const MARKER_CLS = 'jeju-half-yr-marker-' + SLIDER_KEY;
      const POSITIONS = {json.dumps(marker_indices)};

      function findOurSlider() {{
        const sliders = D.querySelectorAll('[data-testid="stSlider"]');
        for (const s of sliders) {{
          const thumbs = s.querySelectorAll('[role="slider"]');
          if (thumbs.length !== 2) continue;
          const tmin = parseInt(thumbs[0].getAttribute('aria-valuemin'), 10);
          const tmax = parseInt(thumbs[0].getAttribute('aria-valuemax'), 10);
          if (tmin === 0 && tmax === N - 1) return s;
        }}
        return null;
      }}

      function inject() {{
        const slider = findOurSlider();
        if (!slider) return;
        const thumbs = slider.querySelectorAll('[role="slider"]');
        if (thumbs.length !== 2) return;
        const trackHost = thumbs[0].parentElement;
        if (!trackHost || !trackHost.contains(thumbs[1])) return;

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
        const minPx = c0 - v0 * pxPerUnit;

        const cs = W.getComputedStyle(trackHost);
        if (cs.position === 'static') trackHost.style.position = 'relative';
        if (cs.overflow === 'hidden' || cs.overflowX === 'hidden') {{
          trackHost.style.overflow = 'visible';
        }}

        trackHost.querySelectorAll('.' + MARKER_CLS).forEach(el => el.remove());
        POSITIONS.forEach(i => {{
          const cx = minPx + i * pxPerUnit;
          const m = D.createElement('span');
          m.className = MARKER_CLS;
          m.style.cssText =
            'position:absolute;'
            + 'left:' + (cx - 7) + 'px;'
            + 'top:calc(50% + 1px);'
            + 'transform:translateY(-50%);'
            + 'width:14px;height:14px;'
            + 'border-radius:50%;'
            + 'border:1.5px solid rgba(26,26,24,0.30);'
            + 'background:transparent;'
            + 'box-sizing:border-box;'
            + 'pointer-events:none;'
            + 'z-index:2;';
          trackHost.appendChild(m);
        }});
      }}

      if (W[IV_KEY]) clearInterval(W[IV_KEY]);
      inject();
      W[IV_KEY] = setInterval(inject, 200);
    }})();
    </script>
    """, height=0)

    # ── JS ② 썸 라벨 교체 + native min/max 라벨 숨김 + 견고한 폴링.
    #   사용자 요청 #3·#4: 모든 위치에서 thumb 라벨이 "YYYY-상/하" 로 보이고,
    #   양 끝 "0 / 23" 라벨이 사라져야 함. CSS 가 못 잡는 케이스를 위해 JS 도 동원.
    _components.html(f"""
    <script>
    (function() {{
      const W = window.parent;
      const D = W.document;
      const N = {n};
      const YR_MIN = {yr_min};
      const IV_KEY = '__halfYrThumbIv_{key}';

      // 사용자 요청 (2026-05-16): thumb value 라벨을 앞 탭(year_slider)의
      // 'YYYY-MM' 형식과 통일.
      //   상반기(1~6월) → '-06' (상반기 마지막 달)
      //   하반기(7~12월) → '-12' (하반기 마지막 달)
      // Python idx_to_yh 함수의 '상'/'하' 는 데이터 처리·caption 용도라
      // 그대로 유지. 슬라이더 트랙 위 표시만 변경.
      function idxToYh(i) {{
        const y = YR_MIN + Math.floor(i / 2);
        const m = (i % 2 === 0) ? '06' : '12';
        return y + '-' + m;
      }}

      function findOurSlider() {{
        const sliders = D.querySelectorAll('[data-testid="stSlider"]');
        for (const s of sliders) {{
          const thumbs = s.querySelectorAll('[role="slider"]');
          if (thumbs.length !== 2) continue;
          const mn = parseInt(thumbs[0].getAttribute('aria-valuemin'), 10);
          const mx = parseInt(thumbs[0].getAttribute('aria-valuemax'), 10);
          if (mn === 0 && mx === N - 1) return s;
        }}
        return null;
      }}

      function hideMinMaxLabels(slider) {{
        // testid 가 버전마다 달라 JS 휴리스틱으로 숨김:
        // 슬라이더의 자손 중 텍스트가 정확히 "0" 또는 "{n - 1}" 인 단순 노드 hide.
        // 단, thumb 라벨(stSliderThumbValue)·thumb(role=slider) 자손은 제외 —
        // 처음 렌더 시 textContent 가 native int 값("23" 등)으로 표시되다가 JS 가
        // "YYYY-상/하" 로 교체하기 전에 숨겨지면 오른쪽 끝 라벨이 영영 안 나타남.
        const targetTexts = new Set(["0", String(N - 1)]);
        const candidates = slider.querySelectorAll('span, div');
        candidates.forEach(el => {{
          if (el.closest('[data-testid="stSliderThumbValue"]')) return;
          if (el.closest('[role="slider"]')) return;
          if (el.children.length > 0) return;   // 단말 노드만
          const t = (el.textContent || '').trim();
          if (targetTexts.has(t) && el.style.display !== 'none') {{
            el.style.display = 'none';
          }}
        }});
      }}

      function update() {{
        try {{
          const slider = findOurSlider();
          if (!slider) return;

          hideMinMaxLabels(slider);

          const thumbs = slider.querySelectorAll('[role="slider"]');
          if (thumbs.length !== 2) return;

          // ── v9 final (2026-05-17) — year_slider.py 와 100% 동일 패턴 ──
          // 누적 시도 v1~v8 모두 실패. 단순한 native textContent override 만.
          // year_slider 가 안정적으로 작동 → 그 코드 그대로 차용.
          //   - color:transparent / overlay span / trackHost 모두 제거
          //   - thumb-value 의 textContent 직접 override 만
          //   - BaseWeb race 는 폴링 10ms 가 회복
          const tvs = slider.querySelectorAll('[data-testid="stSliderThumbValue"]');
          if (tvs.length !== 2) return;

          const lo = parseInt(thumbs[0].getAttribute('aria-valuenow'), 10);
          const hi = parseInt(thumbs[1].getAttribute('aria-valuenow'), 10);
          if (Number.isFinite(lo) && Number.isFinite(hi)) {{
            const loText = idxToYh(lo);
            const hiText = idxToYh(hi);
            if (tvs[0].textContent !== loText) tvs[0].textContent = loText;
            if (tvs[1].textContent !== hiText) tvs[1].textContent = hiText;
          }}

          // 즉시 반응성: thumb 의 aria-valuenow 변경 시 update().
          // year_slider 와 동일 — thumb 에만 observer.
          thumbs.forEach((t) => {{
            if (t.dataset.qty_yh_observed === '1') return;
            t.dataset.qty_yh_observed = '1';
            new MutationObserver(update).observe(t, {{
              attributes: true,
              attributeFilter: ['aria-valuenow']
            }});
          }});
        }} catch (e) {{
          // surface JS errors silently — never let polling crash
          if (W.console && W.console.warn) W.console.warn('halfYrSlider:', e);
        }}
      }}

      if (W[IV_KEY]) clearInterval(W[IV_KEY]);
      update();
      // 30 → 10ms 폴링 가속. drag 시 native int "8/18/20" 등 노출 시간이
      // 한 frame(16ms) 미만 → 사용자 눈에 안 보임.
      W[IV_KEY] = setInterval(update, 10);

      // drag 종료 즉시 update — streamlit fragment rerun 의 100-500ms 공백
      // 동안 native int 잔존 차단. mouseup/pointerup/touchend 시점에서
      // BaseWeb 의 자체 처리 이전(capture:true)에 우리 update 강제.
      // window.parent 에 등록 — iframe 재마운트 무관하게 살아있음.
      if (!W.__halfYrEvtsBound) {{
        W.__halfYrEvtsBound = true;
        ['mouseup', 'pointerup', 'touchend'].forEach(ev => {{
          W.addEventListener(ev, update, {{ passive: true, capture: true }});
        }});
      }}
    }})();
    </script>
    """, height=0)

    return idx_to_yh(lo_i), idx_to_yh(hi_i)
