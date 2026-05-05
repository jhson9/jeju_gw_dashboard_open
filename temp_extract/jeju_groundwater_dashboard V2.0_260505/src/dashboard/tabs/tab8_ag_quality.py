# ==============================================================================
#  파일명: src/dashboard/tabs/tab8_ag_quality.py  —  Build 2.5
#  탭: ⑦ 수질 분석 (반기 5항목)
# ------------------------------------------------------------------------------
#  설계 (이용량 분석 탭과 일관된 구조):
#   - 1줄: 수질 항목(드롭다운) · 집계 단위 · 분석 기간(반기 슬라이더 — int 기반)
#   - 2줄: 시 구분 → 읍/면/동 → 리 (cascading)
#   - KPI 카드 5개 · 지도(6단계 색상 + 6단계 크기) · 관정 클릭 시 상세
#  Build 2.5 변경:
#   - 슬라이더: select_slider(tuple options) → st.slider(int) — BaseWeb 슬라이더의
#     null current 에러를 원천 차단.
#   - 관정 선택바에 검색 입력 추가 (이용량 탭과 동일 UX).
#   - 관정 상세: 선택 항목 단일 막대(라벨·시기 표시·Y=기준×1.5) + 강수량(½ 높이,
#     Y=200) + 5항목 표 (시기 포함 6컬럼).
#   - 지도 마커 크기: 색상과 동일 6단계 (1/3, 2/3, 1, 4/3, 5/3, 2).
# ==============================================================================

from __future__ import annotations

import json

import folium
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
import streamlit.components.v1 as _components
from plotly.subplots import make_subplots
from streamlit_folium import st_folium

import config
from src.analysis import ag_well_loader
from src.collectors import asos_collector
from src.dashboard import ag_well_helpers
from src.dashboard.map_helpers import make_map


# 공용 fragment-only rerun 헬퍼 (컨텍스트 가드 포함). ag_well_helpers 참조.
_fragment_rerun = ag_well_helpers.fragment_rerun


# 표시 순서 (사용자 요청): 질산성질소 → 염소이온 → 전기전도도 → 수소이온농도 → 암모니아성 질소
QUALITY_ITEM_ORDER = ["nitrate_n", "chloride", "EC", "pH", "ammonia_n"]

# 항목별 표시 소수점 자릿수 (사용자 요청 #1):
#   - 질산성질소·염소이온·암모니아성 질소·수소이온농도(pH) → 소수 1자리
#   - 전기전도도(EC) → 소수점 없음 (정수)
_ITEM_DECIMALS: dict[str, int] = {
    "nitrate_n": 1,
    "chloride":  1,
    "ammonia_n": 1,
    "pH":        1,
    "EC":        0,
}


def _fmt_item(v, item: str) -> str:
    """항목별 소수점 자릿수에 맞춘 표시 문자열. 결측은 '-'."""
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "-"
    try:
        d = _ITEM_DECIMALS.get(item, 1)
        return f"{float(v):,.{d}f}"
    except (TypeError, ValueError):
        return str(v)


def _hex_to_rgba(hex_col: str, alpha: float) -> str:
    """#RRGGBB → rgba(r,g,b,a). Plotly 의 fillcolor 는 8자리 hex(#RRGGBBAA) 를
    받지 않으므로 알파를 분리해 rgba() 형태로 반환.
    """
    try:
        h = hex_col.lstrip("#")
        if len(h) >= 6:
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            return f"rgba({r},{g},{b},{alpha})"
    except (ValueError, TypeError):
        pass
    # fallback — invalid input 이면 그대로 반환 (Plotly 가 다시 검증)
    return hex_col


def _clean_no_data_rows(df: pd.DataFrame) -> pd.DataFrame:
    """pH 가 0 또는 NaN 인 행을 '측정 없음' 으로 처리 (사용자 요청 #3).

    이유: 원본 CSV 에서 측정 자료가 없는 시기는 pH=0 (혹은 빈 값) 으로 들어와
    있어 5개 항목·_exceed 플래그까지 모두 0/False 로 잘못 표시됨.
    pH=0 은 물리적으로 불가능 → 「측정 없음」 의 가장 신뢰성 높은 마커.

    Returns: 영향받는 행의 5개 항목 값을 NaN, _exceed 를 False 로 치환한 사본.
    """
    if df.empty or "pH" not in df.columns:
        return df
    no_data = df["pH"].isna() | (df["pH"] == 0)
    if not no_data.any():
        return df
    out = df.copy()
    for col in QUALITY_ITEM_ORDER:
        if col in out.columns:
            out.loc[no_data, col] = pd.NA
        exc_col = f"{col}_exceed"
        if exc_col in out.columns:
            out.loc[no_data, exc_col] = False
    return out


# 6단계 색상 — 푸른색(낮음) → 빨간색(높음). 기준값(100%) = 4·5번째 단계 경계.
_QUALITY_PALETTE = [
    "#2C7BB6",   # 0  ~  25%
    "#67A9CF",   # 25 ~  50%
    "#A6D96A",   # 50 ~  75%
    "#FEE08B",   # 75 ~ 100%
    "#F46D43",   # 100~ 125%
    "#A50026",   # 125~ 150%+
]
_NO_DATA_COLOR = "#BFC6CB"

# 마커 크기 배율 — 색상과 같은 6단계.
#   bin 0(0~25%) 은 사용자 요청 #2: 1/3 → 0.6 으로 키워 클릭 가능한 크기 확보.
#   (5~10 사이즈와는 색상으로 구분되므로 살짝만 작게 = 0.6 vs 0.667.)
_SIZE_MULTIPLIERS = [0.6, 2/3, 1.0, 4/3, 5/3, 2.0]
_BASE_RADIUS = 6.0   # bin 2 (50~75%) 기준 반지름

_AGG_LABELS = ["제주도 전역", "시", "읍면동", "리", "유역"]

_LEVEL_TO_LOC_COL: dict[str, tuple[str, str]] = {
    "제주도 전역": ("well_si", "시"),
    "시":          ("well_eup", "읍/면/동"),
    "읍면동":      ("well_ri", "리"),
    "리":          ("well_id", "관정명"),
    "유역":        ("watershed", "유역"),
}


# ==============================================================================
#  공용 유틸
# ==============================================================================
def _yh_idx(y, h) -> int:
    """(year, half) → 정수 인덱스 (단일값)."""
    if y is None or (isinstance(y, float) and pd.isna(y)) or pd.isna(y):
        return -1
    try:
        y = int(y)
    except (TypeError, ValueError):
        return -1
    return y * 2 + (0 if str(h).strip() == "상" else 1)


def _yh_idx_series(year_s: pd.Series, half_s: pd.Series) -> pd.Series:
    """벡터화 (year, half) → 정수 인덱스. NaN year → -1.

    19K+ 행 데이터에서 apply(axis=1) 가 너무 느려 벡터화 필수.
    """
    y = pd.to_numeric(year_s, errors="coerce")
    h_offset = (
        half_s.astype(str).str.strip().ne("상").astype(int)
    )
    idx = y * 2 + h_offset
    return idx.where(y.notna(), -1).astype("int64")


def _yh_label(y, h) -> str:
    return f"{int(y)}-{h}" if pd.notna(y) else "-"


def _yh_to_date(y, h) -> pd.Timestamp:
    """반기를 datetime 으로 변환 — 상=3월 15일, 하=9월 15일 (사용자 요청 #4)."""
    if pd.isna(y):
        return pd.NaT
    y = int(y)
    return pd.Timestamp(year=y, month=3 if str(h).strip() == "상" else 9, day=15)


def _fmt_val(v, decimals: int = 2) -> str:
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return "-"
    try:
        f = float(v)
        if abs(f) >= 1000 and decimals <= 2:
            return f"{f:,.0f}"
        return f"{f:,.{decimals}f}"
    except (TypeError, ValueError):
        return str(v)


def _color_score(value, std: dict, fallback_max: float | None = None) -> float | None:
    """기준값 대비 비율(0~1.5+).

    - max·min 둘 다 있음(pH): |v - mid| / half_range
    - max 만:  v / max
    - max 없음: fallback_max 사용
    """
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if "max" in std and "min" in std:
        mid = (std["max"] + std["min"]) / 2.0
        half = (std["max"] - std["min"]) / 2.0
        if half <= 0:
            return 0.0
        return abs(v - mid) / half
    if "max" in std and std["max"] > 0:
        return v / std["max"]
    if fallback_max is not None and fallback_max > 0:
        return v / fallback_max
    return None


def _bin_index(score: float | None) -> int | None:
    """score(0~1.5+) → 6단계 인덱스(0~5). None 이면 None."""
    if score is None or (isinstance(score, float) and pd.isna(score)):
        return None
    pct = score * 100.0
    if pct < 25:    return 0
    if pct < 50:    return 1
    if pct < 75:    return 2
    if pct < 100:   return 3
    if pct < 125:   return 4
    return 5


def _color_from_score(score: float | None) -> str:
    idx = _bin_index(score)
    return _NO_DATA_COLOR if idx is None else _QUALITY_PALETTE[idx]


def _radius_from_score(score: float | None) -> float:
    """6단계 마커 반지름. None 이면 절반 크기 회색 마커."""
    idx = _bin_index(score)
    if idx is None:
        return _BASE_RADIUS * 0.5
    return _BASE_RADIUS * _SIZE_MULTIPLIERS[idx]


def _std_label(std: dict) -> str:
    unit = std.get("unit", "")
    if "max" in std and "min" in std:
        return f"{std['min']}~{std['max']} {unit}"
    if "max" in std:
        return f"≤ {std['max']} {unit}"
    if "min" in std:
        return f"≥ {std['min']} {unit}"
    return f"({unit})" if unit else "-"


# ==============================================================================
#  반기 슬라이더 — int 기반 (max 호환성, 외부 React 컴포넌트 의존 X)
# ==============================================================================
def _half_year_slider(
    yr_min: int, yr_max: int, key: str = "qty_yh_range_int",
) -> tuple[tuple[int, str], tuple[int, str]]:
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

    def idx_to_yh(i: int) -> tuple[int, str]:
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
    #   Streamlit 버전마다 testid 가 다를 수 있어 여러 후보 모두 셀렉터에 포함.
    #   추가로 JS-based hide 도 아래에서 fallback 으로 적용.
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
    tick_html = (
        '<div style="display:flex;justify-content:space-between;'
        'padding:0 12px;margin-top:-6px;margin-bottom:2px;'
        'font-size:10.5px;color:#5f5e5a;font-weight:500;'
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

      function idxToYh(i) {{
        const y = YR_MIN + Math.floor(i / 2);
        const h = (i % 2 === 0) ? '상' : '하';
        return y + '-' + h;
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

          // 즉시 반응성: aria-valuenow / textContent 변경 시 update().
          thumbs.forEach((t) => {{
            if (t.dataset.qty_yh_observed === '1') return;
            t.dataset.qty_yh_observed = '1';
            new MutationObserver(update).observe(t, {{
              attributes: true,
              attributeFilter: ['aria-valuenow']
            }});
          }});
          tvs.forEach((tv) => {{
            if (tv.dataset.qty_yh_observed === '1') return;
            tv.dataset.qty_yh_observed = '1';
            new MutationObserver(update).observe(tv, {{
              childList: true, characterData: true, subtree: true
            }});
          }});
        }} catch (e) {{
          // surface JS errors silently — never let polling crash
          if (W.console && W.console.warn) W.console.warn('halfYrSlider:', e);
        }}
      }}

      if (W[IV_KEY]) clearInterval(W[IV_KEY]);
      update();
      // 30ms 폴링 — drag 중에도 시각적으로 끊김 없이 라벨 즉시 갱신.
      W[IV_KEY] = setInterval(update, 30);
    }})();
    </script>
    """, height=0)

    return idx_to_yh(lo_i), idx_to_yh(hi_i)


def _maybe_recenter_map(loc_sel: dict, df_master_f: pd.DataFrame) -> None:
    """위치 필터(시/읍면동/리)가 변경되면 지도 중심·줌을 그 지역 관정 centroid 로 이동.

    동작 규칙:
      - fingerprint(=loc_sel 값 튜플) 가 직전 호출과 다를 때만 갱신.
        → 사용자가 마커 클릭으로 지도를 조작한 뒤에는 그 위치를 보존.
      - 줌 단계: 리 14, 읍면동 12, 시 11, 전체 11.
      - lat/lon 결측 시 무시.
    """
    fp = (loc_sel.get("well_si"), loc_sel.get("well_eup"), loc_sel.get("well_ri"))
    last_fp = st.session_state.get("_qty_loc_fingerprint")
    if fp == last_fp:
        return
    st.session_state["_qty_loc_fingerprint"] = fp

    if df_master_f.empty:
        return
    if "lat" not in df_master_f.columns or "lon" not in df_master_f.columns:
        return
    coords = df_master_f.dropna(subset=["lat", "lon"])
    if coords.empty:
        return

    cy = float(coords["lat"].mean())
    cx = float(coords["lon"].mean())
    st.session_state["qty_map_center"] = (cy, cx)

    if loc_sel.get("well_ri"):
        st.session_state["qty_map_zoom"] = 14
    elif loc_sel.get("well_eup"):
        st.session_state["qty_map_zoom"] = 12
    elif loc_sel.get("well_si"):
        st.session_state["qty_map_zoom"] = 11
    else:
        st.session_state["qty_map_zoom"] = 11


def _location_label(loc_sel: dict) -> str:
    parts = [loc_sel.get(k) for k in ("well_si", "well_eup", "well_ri")]
    parts = [p for p in parts if p]
    return " > ".join(parts) if parts else "제주도 전역"


def _yh_period_label(lo: tuple[int, str], hi: tuple[int, str]) -> str:
    n_half = _yh_idx(*hi) - _yh_idx(*lo) + 1
    n_year = n_half / 2.0
    n_year_label = (f"{int(n_year)}년" if n_year.is_integer()
                    else f"{n_year:.1f}년")
    return f"{lo[0]}-{lo[1]} ~ {hi[0]}-{hi[1]} (총 {n_half}반기 · {n_year_label})"


# ==============================================================================
#  메인 render
# ==============================================================================
@st.fragment
def render() -> None:
    st.markdown(
        '<h2 style="font-size:22px;font-weight:500;margin:0 0 6px;padding:0;'
        'color:#1a1a18;line-height:1.2;">'
        '⑦ 수질 분석 — 농업용 공공관정</h2>',
        unsafe_allow_html=True,
    )

    df_master = ag_well_loader.load_master(active_only=False)
    df_qual   = ag_well_loader.load_quality_semiannual()

    if df_qual.empty:
        st.warning(
            "수질 자료를 찾을 수 없습니다 (water_quality_semiannual.csv)."
        )
        return

    available_items = [
        k for k in QUALITY_ITEM_ORDER
        if k in config.WATER_QUALITY_STANDARDS and k in df_qual.columns
    ]
    if not available_items:
        st.warning("수질 자료에 표시 가능한 항목이 없습니다.")
        return

    # 첫 진입 default — 이용량 탭과 동일 (시 / 서귀포시).
    if "qty_level" not in st.session_state:
        st.session_state["qty_level"] = "시"
    if "qty_loc_si" not in st.session_state:
        st.session_state["qty_loc_si"] = "전체"
    cur_item = st.session_state.get("qty_item")
    if cur_item not in available_items:
        st.session_state["qty_item"] = (
            "nitrate_n" if "nitrate_n" in available_items else available_items[0]
        )

    # ── 컨트롤 두 줄(수질항목/집계단위/연도 → 시구분/읍면동/리) 사이 공백 ~8~10mm 안전 압축.
    #     두 row 사이 공백 ~100px 의 구성:
    #       (a) row 1 slider 자체 padding-bottom (≈28px)
    #       (b) Streamlit vertical block flex gap (≈16px)
    #       (c) row 2 selectbox stWidgetLabel padding-top (≈8px)
    #     세 요소를 동시 압축. -2.0rem(-32px) 은 row 1 의 시각 끝(tick label "2014")
    #     과 row 2 라벨("시 구분") 사이 안전 거리 ≈ 12mm 를 보장하는 한계점.
    #     -2.5rem 이상부터 라벨 겹침 위험.
    st.markdown("""
    <style>
    /* (1) marker stMarkdown / stElementContainer 자체 0 압축 + slider padding 흡수 */
    [data-testid="stMarkdown"]:has(.row-pair-tight),
    [data-testid="stElementContainer"]:has(.row-pair-tight) {
        height: 0 !important;
        min-height: 0 !important;
        max-height: 0 !important;
        margin: -0.8rem 0 0 0 !important;
        padding: 0 !important;
        line-height: 0 !important;
        overflow: hidden !important;
    }
    /* (2) marker 다음 element 의 margin-top 음수 — flex gap 상쇄 + 추가 압축
         marker 가 두 위치(컨트롤 row 사이 / 정보박스 위)에 같은 클래스로 재사용되므로
         다음 element 가 stHorizontalBlock(컨트롤 row) 또는 stMarkdown(정보박스) 모두 매치 */
    [data-testid="stMarkdown"]:has(.row-pair-tight) + [data-testid="stHorizontalBlock"],
    [data-testid="stMarkdown"]:has(.row-pair-tight) + [data-testid="stMarkdown"],
    [data-testid="stElementContainer"]:has(.row-pair-tight) + [data-testid="stHorizontalBlock"],
    [data-testid="stElementContainer"]:has(.row-pair-tight) + [data-testid="stElementContainer"],
    [data-testid="stElementContainer"]:has(.row-pair-tight) + [data-testid="stMarkdown"] {
        margin-top: -2.0rem !important;
    }
    /* (3) row 2 의 selectbox 라벨 위 패딩 0 — (c) 요소 제거 */
    [data-testid="stMarkdown"]:has(.row-pair-tight) + [data-testid="stHorizontalBlock"] [data-testid="stWidgetLabel"],
    [data-testid="stElementContainer"]:has(.row-pair-tight) + [data-testid="stHorizontalBlock"] [data-testid="stWidgetLabel"],
    [data-testid="stElementContainer"]:has(.row-pair-tight) + [data-testid="stElementContainer"] [data-testid="stWidgetLabel"],
    [data-testid="stMarkdown"]:has(.row-pair-tight) ~ [data-testid="stHorizontalBlock"]:first-of-type [data-testid="stWidgetLabel"] {
        margin-top: 0 !important;
        padding-top: 0 !important;
    }
    </style>
    """, unsafe_allow_html=True)

    # ── 컨트롤 1줄
    c1, c2, c3 = st.columns([1.4, 1.2, 4.0])
    with c1:
        item = st.selectbox(
            "수질 항목",
            options=available_items,
            format_func=lambda k: (
                f"{config.WATER_QUALITY_STANDARDS[k]['kor']} ({k})"
            ),
            key="qty_item",
        )
    with c2:
        level = st.selectbox(
            "집계 단위", _AGG_LABELS, key="qty_level",
        )
    with c3:
        yr_min = (
            int(df_qual["year"].dropna().min())
            if df_qual["year"].notna().any() else 2015
        )
        yr_max = (
            int(df_qual["year"].dropna().max())
            if df_qual["year"].notna().any() else 2025
        )
        if yr_min > yr_max:
            yr_min = yr_max
        # ⚠ key 변경 — 이전 select_slider 의 stale 위젯 상태와 충돌 회피.
        yh_lo, yh_hi = _half_year_slider(yr_min, yr_max, key="qty_yh_range_int")

    # ── 컨트롤 2줄: 시 → 읍면동 → 리
    #     marker — 위 CSS 가 다음 horizontal block 을 위로 끌어올림
    st.markdown(
        '<div class="row-pair-tight"></div>',
        unsafe_allow_html=True,
    )
    loc_sel = ag_well_helpers.cascading_location_filters(
        df_master, key_prefix="qty_loc", si_label="시 구분",
    )
    df_master_f = ag_well_helpers.apply_cascading_filters(df_master, loc_sel)

    if df_master_f.empty:
        st.info("선택한 지역 조건에 해당하는 관정이 없습니다.")
        return

    # 사용자 요청 #5: 시/읍면동/리 선택 변경 시 지도 중심을 그 지역 관정 중심으로 이동.
    # fingerprint 가 바뀐 첫 rerun 에만 적용 → 마커 클릭 후 줌 변경한 사용자의 뷰는 보존.
    _maybe_recenter_map(loc_sel, df_master_f)

    # ── qf 필터링 (지역 + 반기 범위)
    permit_set = set(df_master_f["permit_no"].dropna().unique())
    qf = df_qual.copy()
    qf = qf[qf["permit_no"].isin(permit_set)].copy()

    if "year" in qf.columns and "half" in qf.columns:
        lo_idx = _yh_idx(*yh_lo)
        hi_idx = _yh_idx(*yh_hi)
        qf["_yh"] = _yh_idx_series(qf["year"], qf["half"])
        qf = qf[(qf["_yh"] >= lo_idx) & (qf["_yh"] <= hi_idx)].copy()

    # 사용자 요청 #3: 측정 자료가 없는 행(pH=0 또는 NaN)을 NaN 으로 정리.
    qf = _clean_no_data_rows(qf)

    loc_keep_cols = [
        c for c in ("well_id", "well_si", "well_eup", "well_ri", "watershed",
                    "lat", "lon")
        if c in df_master_f.columns
    ]
    qf = qf.merge(
        df_master_f[["permit_no"] + loc_keep_cols].drop_duplicates("permit_no"),
        on="permit_no", how="left", suffixes=("", "_m"),
    )

    region_label = _location_label(loc_sel)
    period_label = _yh_period_label(yh_lo, yh_hi)
    # cascading filter row 와 정보 박스 사이는 Streamlit 기본 gap 을 유지해
    # 라벨("리")이 정보박스 윗변에 닿지 않도록 한다.
    # (이전 row-pair-tight 마커는 라벨 겹침을 유발해 제거.)
    st.markdown(
        f'<div style="margin:0 0 6px;padding:8px 14px;'
        f'background:#f5f5f3;border-left:3px solid #185fa5;'
        f'border-radius:4px;font-size:13px;color:#1a1a18;">'
        f'<b style="color:#185fa5;">지역</b>&nbsp;: '
        f'<span style="font-weight:600;">{region_label}</span>'
        f'&nbsp;&nbsp;|&nbsp;&nbsp;'
        f'<b style="color:#185fa5;">선택 기간</b>&nbsp;: '
        f'<span style="font-weight:600;">{period_label}</span>'
        f'</div>',
        unsafe_allow_html=True,
    )

    if qf.empty or item not in qf.columns:
        st.info("선택 조건에 해당하는 수질 측정 자료가 없습니다.")
        return

    _render_kpi_cards(qf, item, level)

    st.markdown(
        '<hr style="margin:10px 0;border:none;'
        'border-top:0.5px solid rgba(26,26,24,0.15);">',
        unsafe_allow_html=True,
    )
    _render_map(qf, df_master_f, item, available_items)

    # ── 사용자 요청 #5·#6·#7: 그룹별 박스 플롯 + 시계열 표
    st.markdown(
        '<hr style="margin:14px 0;border:none;'
        'border-top:0.5px solid rgba(26,26,24,0.15);">',
        unsafe_allow_html=True,
    )
    _render_group_section(qf, item, level, loc_sel, yh_lo, yh_hi)


# ==============================================================================
#  KPI 카드 5개
# ==============================================================================
def _render_kpi_cards(qf: pd.DataFrame, item: str, level: str) -> None:
    """5개 KPI 카드 (사용자 요청 #6·#7·#8):
       1) 산술 평균    — 분석기간 전체 측정값의 평균
       2) 중앙값       — 별도 박스
       3) 최대값(그룹평균) — 집계 단위의 한 단계 아래(loc_col)별 평균 中 최대
       4) 최소값(그룹평균) — 동일 그룹별 평균 中 최소
       5) 기준 초과    — 초과 관정 수 + 초과 측정 횟수
    """
    std = config.WATER_QUALITY_STANDARDS.get(item, {})
    unit = std.get("unit", "")
    item_kor = std.get("kor", item)
    std_text = _std_label(std)

    sub = qf.dropna(subset=[item]).copy()
    n_meas = int(len(sub))
    n_wells = int(sub["permit_no"].nunique()) if not sub.empty else 0

    if sub.empty:
        avg_v = med_v = None
    else:
        avg_v = float(sub[item].mean())
        med_v = float(sub[item].median())

    exc_col = f"{item}_exceed"
    if exc_col in qf.columns:
        exc_mask = qf[exc_col].fillna(False).astype(bool)
        n_exc_meas = int(exc_mask.sum())
        n_exc_wells = int(qf.loc[exc_mask, "permit_no"].nunique())
    else:
        n_exc_meas = 0
        n_exc_wells = 0

    # 그룹별 평균 — 집계 단위(level)에 따른 한 단계 아래 컬럼
    #   예: level=읍면동 → loc_col=well_ri, 리별 평균. 평균이 가장 높은 리 / 가장 낮은 리.
    loc_col, loc_label_kor = _LEVEL_TO_LOC_COL.get(level, ("well_id", "관정명"))
    max_grp_label = min_grp_label = "-"
    max_grp_val = min_grp_val = None
    # 사용자 요청 #3: 측정 횟수 대신 「max·min 측정이 발생한 시기」 표시.
    max_peak_period = min_peak_period = "-"

    def _period_text(yr, hf) -> str:
        if pd.isna(yr) or pd.isna(hf):
            return "-"
        try:
            return f"[{int(yr)}년-{str(hf).strip()}반기]"
        except (TypeError, ValueError):
            return "-"

    if not sub.empty and loc_col in sub.columns:
        sub_loc = sub.dropna(subset=[loc_col]).copy()
        sub_loc[loc_col] = sub_loc[loc_col].astype(str).str.strip()
        sub_loc = sub_loc[sub_loc[loc_col] != ""]
        sub_loc = sub_loc[~sub_loc[loc_col].str.lower().isin(["nan", "none"])]
        if not sub_loc.empty:
            grp = (
                sub_loc.groupby(loc_col)[item]
                .agg(mean="mean")
                .reset_index()
            )
            if not grp.empty:
                max_row = grp.loc[grp["mean"].idxmax()]
                min_row = grp.loc[grp["mean"].idxmin()]
                max_grp_label = str(max_row[loc_col])
                min_grp_label = str(min_row[loc_col])
                max_grp_val = float(max_row["mean"])
                min_grp_val = float(min_row["mean"])

                # 그 그룹 안에서 가장 높은(낮은) 측정값이 발생한 시기
                max_grp_data = sub_loc[sub_loc[loc_col] == max_grp_label]
                if not max_grp_data.empty:
                    peak_idx = max_grp_data[item].idxmax()
                    max_peak_period = _period_text(
                        max_grp_data.loc[peak_idx].get("year"),
                        max_grp_data.loc[peak_idx].get("half"),
                    )
                min_grp_data = sub_loc[sub_loc[loc_col] == min_grp_label]
                if not min_grp_data.empty:
                    valley_idx = min_grp_data[item].idxmin()
                    min_peak_period = _period_text(
                        min_grp_data.loc[valley_idx].get("year"),
                        min_grp_data.loc[valley_idx].get("half"),
                    )

    cards: list[tuple[str, str, str]] = [
        # 1) 산술 평균 — 부제에서 중앙값 제거 (요청 #7), 측정수·관정수 표기
        (
            "산술 평균",
            f"{_fmt_item(avg_v, item)} {unit}",
            f"전체 측정 {n_meas:,}회 · {n_wells:,}공 · 항목: {item_kor}",
        ),
        # 2) 중앙값 (별도 박스, 요청 #8)
        (
            "중앙값",
            f"{_fmt_item(med_v, item)} {unit}",
            f"분석기간 전체 측정값 기준",
        ),
        # 3) 최대값 - 그룹평균 (요청 #6) + 사용자 요청 #3: 최대 측정 시기
        (
            f"최대값 — {loc_label_kor}별 평균",
            f"{_fmt_item(max_grp_val, item)} {unit}",
            f"{max_grp_label} · {max_peak_period}",
        ),
        # 4) 최소값 - 그룹평균 (요청 #6) + 사용자 요청 #3: 최소 측정 시기
        (
            f"최소값 — {loc_label_kor}별 평균",
            f"{_fmt_item(min_grp_val, item)} {unit}",
            f"{min_grp_label} · {min_peak_period}",
        ),
        # 5) 기준 초과
        (
            "기준 초과",
            f"{n_exc_wells:,}공",
            f"초과 {n_exc_meas:,}회 · 기준 {std_text}",
        ),
    ]

    cols = st.columns(5)
    accent_colors = ["#185fa5", "#185fa5", "#C00000", "#305496", "#C00000"]
    for i, (col, (title, big, sub_text)) in enumerate(zip(cols, cards)):
        accent = accent_colors[i]
        with col:
            # 글자 크기 통일 (사용자 호소 #3) — 값(big)은 h2 헤더(22px)와 동일.
            # 헤더 11→14, 값 18→22 / weight 600→500, 부제 10.5→12.
            html = (
                f'<div style="background:#f5f5f3;border-radius:8px;'
                f'padding:10px 14px;border-left:3px solid {accent};'
                f'margin-bottom:6px;min-height:92px;">'
                f'<div style="font-size:14px;font-weight:600;color:#5f5e5a;'
                f'line-height:1.25;">{title}</div>'
                f'<div style="font-size:22px;font-weight:500;color:{accent};'
                f'line-height:1.2;margin-top:4px;white-space:nowrap;'
                f'overflow:hidden;text-overflow:ellipsis;">{big}</div>'
                f'<div style="font-size:12px;color:#5f5e5a;margin-top:3px;'
                f'line-height:1.35;">{sub_text}</div>'
                f'</div>'
            )
            st.markdown(html, unsafe_allow_html=True)


# ==============================================================================
#  지도 + 관정 클릭 → 상세
# ==============================================================================
def _render_map(
    qf: pd.DataFrame,
    df_master_f: pd.DataFrame,
    item: str,
    all_items: list[str],
) -> None:
    std = config.WATER_QUALITY_STANDARDS.get(item, {})
    unit = std.get("unit", "")
    item_kor = std.get("kor", item)
    std_text = _std_label(std)

    if qf.empty or item not in qf.columns:
        st.info("지도에 표시할 자료가 없습니다.")
        return

    qf_with_idx = qf.dropna(subset=[item]).copy()
    if qf_with_idx.empty:
        st.info(f"{item_kor} 측정값이 있는 관정이 없습니다.")
        return

    if "_yh" not in qf_with_idx.columns:
        qf_with_idx["_yh"] = _yh_idx_series(
            qf_with_idx["year"], qf_with_idx["half"]
        )
    qf_latest = (
        qf_with_idx.sort_values("_yh")
                   .groupby("permit_no").tail(1)
    )

    if "lat" not in qf_latest.columns or "lon" not in qf_latest.columns:
        st.info("지도에 표시할 좌표 정보가 없습니다.")
        return
    merged = qf_latest.dropna(subset=["lat", "lon"])
    if merged.empty:
        st.info("지도에 표시할 좌표 보유 관정이 없습니다.")
        return

    # max 가 없는 항목(EC 등) — 분석기간 내 P95 를 fallback 기준.
    fallback_max = None
    if "max" not in std:
        try:
            fallback_max = float(qf[item].dropna().quantile(0.95))
        except Exception:
            fallback_max = None

    # 사용자 요청 #9: 기준치/마커 안내 보조문구 삭제. 제목만 유지.
    st.markdown(
        f'<div style="font-size:13px;font-weight:600;color:#185fa5;'
        f'margin-top:6px;margin-bottom:6px;">'
        f'관정별 {item_kor} 분포 — 분석기간 내 마지막 측정값'
        f'</div>',
        unsafe_allow_html=True,
    )

    sel = st.session_state.get("qty_selected_permit")

    # 관정 선택 시 그 관정 중심으로 zoom 12 (읍/면/동 사이즈) — fingerprint 패턴.
    ag_well_helpers.maybe_recenter_to_selected_well(
        sel, df_master_f,
        fingerprint_key="_qty_centered_permit",
        center_key="qty_map_center",
        zoom_key="qty_map_zoom",
    )

    saved_zoom = st.session_state.get("qty_map_zoom", 11)
    saved_center = st.session_state.get("qty_map_center", (33.38, 126.55))
    m = make_map(center=tuple(saved_center), zoom=saved_zoom)

    for _, r in merged.iterrows():
        v = float(r[item]) if pd.notna(r[item]) else None
        score = _color_score(v, std, fallback_max=fallback_max)
        color = _color_from_score(score)
        radius = _radius_from_score(score)

        permit = r["permit_no"]
        well_id = r.get("well_id") or permit
        is_sel = (permit == sel)
        is_exc = bool(r.get(f"{item}_exceed", False))

        if is_sel:
            radius = max(radius, _BASE_RADIUS) * 1.3
        # 선택 관정: 두꺼운 검정 외곽선 (사용자 요청 #1)
        edge = "#000000" if is_sel else color

        date_text = _yh_label(r.get("year"), r.get("half"))
        verdict = (
            "⚠ 부적합" if is_exc
            else ("불검출" if (v is not None and v == 0) else "적합")
        )
        popup_html = (
            f'<div style="font-size:12px;line-height:1.5;min-width:160px;">'
            f'<b>{well_id}</b><br>{permit}<br>'
            f'{item_kor}: <b>{_fmt_val(v)} {unit}</b><br>'
            f'시기: {date_text}<br>판정: {verdict}'
            f'<span style="display:none;">{permit}</span>'
            f'</div>'
        )
        folium.CircleMarker(
            location=[r["lat"], r["lon"]],
            radius=radius,
            color=edge, weight=5 if is_sel else 1.0,
            fill=True, fill_color=color, fill_opacity=0.92,
            tooltip=str(well_id) if well_id else str(permit),
            popup=folium.Popup(popup_html, max_width=240),
        ).add_to(m)

    legend_max = std.get("max") if "max" in std else fallback_max
    if legend_max is None:
        legend_max = 1.0
    m.get_root().html.add_child(folium.Element(
        _build_color_legend(item_kor, std, legend_max, unit)
    ))

    # 관정 선택 시 height 1/2 축소 — 단일 key 유지하며 height props 만 변경.
    map_h = 430 if sel else 780
    click = st_folium(
        m, width=None, height=map_h,
        returned_objects=[
            "last_object_clicked_tooltip",
            "last_object_clicked_popup",
            "zoom",
            "center",
        ],
        key="qty_map",
    )

    if click:
        z = click.get("zoom")
        c = click.get("center")
        if z is not None:
            try:
                st.session_state["qty_map_zoom"] = int(z)
            except (TypeError, ValueError):
                pass
        if isinstance(c, dict) and "lat" in c and "lng" in c:
            try:
                st.session_state["qty_map_center"] = (
                    float(c["lat"]), float(c["lng"])
                )
            except (TypeError, ValueError):
                pass
        clicked_permit = ag_well_helpers.lookup_permit_by_well_id(
            click.get("last_object_clicked_tooltip"), df_master_f
        )
        if not clicked_permit:
            clicked_permit = ag_well_helpers.parse_clicked_popup(
                click.get("last_object_clicked_popup")
            )
        if clicked_permit and clicked_permit != sel:
            st.session_state["qty_selected_permit"] = clicked_permit
            _fragment_rerun()

    sel = st.session_state.get("qty_selected_permit")
    # 검색은 414공 전체 master 에서 — 현재 cascading 으로 좁힌 df_master_f 가 아닌
    # 전체에서 찾도록 (이용량 탭과 동일 동작).
    df_master_full = ag_well_loader.load_master(active_only=False)
    _render_well_selection_bar(df_master_full, sel)
    if sel:
        _render_well_detail(sel, df_master_f, item)


def _build_color_legend(
    item_kor: str, std: dict, ref_max: float, unit: str,
) -> str:
    """지도 좌하단 6단계 색상 범례.

    사용자 요청 #1: 거리 범례(scale bar) 와 부딪히지 않게 위로 올림 (bottom 80px).
    사용자 요청 #2: 제목에서 "— 6단계 색상 + 크기" 제거.
    사용자 요청 #3: 경계값을 정수로 표시 (5.00 → 5).
    사용자 요청 #4: 기준치/100% 안내문 완전 삭제.
    """
    breaks_pct = [25, 50, 75, 100, 125, 150]
    # 정수 라벨 (요청 #3)
    boundaries = [f"{int(round(ref_max * (p / 100.0)))}" for p in breaks_pct]
    swatches = "".join(
        f'<div style="display:inline-block;width:32px;height:12px;'
        f'background:{c};border:0.5px solid rgba(0,0,0,0.18);"></div>'
        for c in _QUALITY_PALETTE
    )
    pct_labels = (
        '<div style="display:flex;font-size:10px;color:#5f5e5a;'
        'gap:0;width:192px;justify-content:space-between;'
        'margin-top:1px;">'
        f'<span>0</span>'
        f'<span>{boundaries[0]}</span>'
        f'<span>{boundaries[1]}</span>'
        f'<span>{boundaries[2]}</span>'
        f'<span style="color:#C00000;font-weight:700;">{boundaries[3]}</span>'
        f'<span>{boundaries[4]}</span>'
        f'<span>{boundaries[5]}+</span>'
        '</div>'
    )
    return f"""
    <div style="
        position: absolute; bottom: 80px; left: 60px; z-index: 1000;
        background: rgba(255, 255, 255, 0.95);
        padding: 8px 12px; border-radius: 6px;
        border: 0.5px solid rgba(0, 0, 0, 0.18);
        box-shadow: 0 1px 4px rgba(0,0,0,0.12);
        font-size: 11px; color: #1a1a18;
    ">
      <div style="font-weight:600;margin-bottom:4px;color:#185fa5;">
        {item_kor} ({unit})
      </div>
      <div style="display:flex;gap:0;width:192px;">{swatches}</div>
      {pct_labels}
    </div>
    """


# ==============================================================================
#  관정 선택 바 (+ 검색)
# ==============================================================================
def _render_well_selection_bar(
    df_master: pd.DataFrame, selected_permit: str | None,
) -> None:
    """선택된 관정 표시 + 검색 입력 + 선택 해제 — 이용량 탭과 동일 UX."""
    h_left, h_search, h_right = st.columns([4, 2.2, 1])

    with h_left:
        if selected_permit:
            info = ag_well_loader.get_well_info(selected_permit)
            well_id = (
                (info.get("well_id") if info else selected_permit)
                or selected_permit
            )
            addr_parts: list[str] = []
            for k in ("well_si", "well_eup", "well_ri", "well_bunji"):
                v = info.get(k) if info else None
                if v is None or (isinstance(v, float) and pd.isna(v)):
                    continue
                s = str(v).strip()
                if s and s.lower() not in ("nan", "none"):
                    addr_parts.append(s)
            addr = " ".join(addr_parts) if addr_parts else "주소 미상"
            inner = (
                f'선택 관정: {well_id} '
                f'<span style="font-weight:400;color:#5f5e5a;font-size:12px;">'
                f'({addr} · {selected_permit})</span>'
            )
        else:
            inner = (
                '선택 관정: '
                '<span style="font-weight:400;color:#7a7a76;font-size:12px;">'
                '(미선택 — 지도 마커 클릭 또는 우측 검색창에 관정명 입력)</span>'
            )
        st.markdown(
            f'<div style="font-size:14px;font-weight:600;color:#185fa5;'
            f'padding:10px 0 4px;border-top:1px solid rgba(26,26,24,0.15);'
            f'margin-top:10px;">{inner}</div>',
            unsafe_allow_html=True,
        )

    with h_search:
        st.markdown('<div style="margin-top:10px;"></div>', unsafe_allow_html=True)
        _render_well_search_input(df_master)

    with h_right:
        st.markdown('<div style="margin-top:14px;"></div>', unsafe_allow_html=True)
        if selected_permit and st.button(
            "선택 해제", key="qty_clear_sel", use_container_width=True,
        ):
            st.session_state.pop("qty_selected_permit", None)
            _fragment_rerun()


def _render_well_search_input(df_master: pd.DataFrame) -> None:
    """관정명 검색 — Enter 시 매칭 관정 선택 + 지도 중심 이동.

    매칭 우선순위: well_id 정확 일치 → 부분 일치 1건 → 다수 매칭 안내 → 일치 없음.
    이용량 탭의 _render_well_search_input 과 동일 UX.
    """
    keyword = st.text_input(
        "관정명 검색",
        value="",
        key="qty_well_search",
        placeholder="관정명 입력 후 Enter (예: F-273)",
        label_visibility="collapsed",
    )

    last_kw = st.session_state.get("_qty_well_search_last", "")
    if keyword == last_kw:
        return
    st.session_state["_qty_well_search_last"] = keyword

    if not keyword.strip():
        return
    if df_master.empty or "well_id" not in df_master.columns:
        st.warning("관정 자료를 찾을 수 없습니다.")
        return

    kw = keyword.strip().lower()
    well_ids = df_master["well_id"].astype(str)

    exact = df_master[well_ids.str.lower() == kw]
    if not exact.empty:
        match = exact.iloc[0]
    else:
        partial = df_master[well_ids.str.lower().str.contains(kw, na=False)]
        if partial.empty:
            st.warning(f"'{keyword}' 와(과) 일치하는 관정이 없습니다.")
            return
        if len(partial) > 1:
            ids = ", ".join(partial["well_id"].astype(str).head(5).tolist())
            tail = " ..." if len(partial) > 5 else ""
            st.info(
                f"매칭 관정 {len(partial)}개: {ids}{tail}. 더 정확한 이름을 입력하세요."
            )
            return
        match = partial.iloc[0]

    permit_no = match.get("permit_no")
    if not permit_no:
        st.warning("관정 정보를 찾을 수 없습니다.")
        return

    st.session_state["qty_selected_permit"] = permit_no
    # zoom·center 는 maybe_recenter_to_selected_well 이 다음 build 직전에
    # fingerprint 패턴으로 zoom 12 + 그 관정 중심으로 처리.
    _fragment_rerun()


# ==============================================================================
#  관정 상세 — 항목 단일 막대 + 강수량(½) + 5항목 표
# ==============================================================================
def _select_aws_for_well(info: dict) -> str | None:
    """관정의 watershed 로 인접 AWS 1개 결정. 매핑 실패 시 None."""
    if not info:
        return None
    ws = info.get("watershed")
    if not ws or (isinstance(ws, float) and pd.isna(ws)):
        return None
    raw = str(ws).strip()
    candidates = [raw]
    if raw.endswith("수역"):
        candidates.append(raw[:-2])
    else:
        candidates.append(raw + "수역")
    for cand in candidates:
        aws = config.WATERSHED_AWS_MAP.get(cand)
        if aws:
            return aws
    return None


def _render_well_detail(
    permit_no: str, df_master_f: pd.DataFrame, item: str,
) -> None:
    """선택 관정 상세:
       (1) 선택 항목 단일 막대 (Y=기준×2, 매 바마다 상/하·연도 X 라벨)
       (2) AWS 반기강수량 막대 (½ 높이, Y=0~1000, 동일 X 축)
       (3) 5항목 시계열 표 — 행=항목, 열=(연도/반기) 2단 헤더
    """
    df_qual_all = ag_well_loader.load_quality_semiannual()
    sub = df_qual_all[df_qual_all["permit_no"] == permit_no].copy()
    # 사용자 요청 #3: 측정 자료 없는 행 정리 (pH=0 → 모두 NaN)
    sub = _clean_no_data_rows(sub)
    if sub.empty:
        st.caption("선택된 관정의 수질 자료가 없습니다.")
        return

    sub["_yh"] = _yh_idx_series(sub["year"], sub["half"])
    sub = sub.sort_values("_yh").reset_index(drop=True)

    sub["_date"] = sub.apply(
        lambda r: _yh_to_date(r["year"], r["half"]), axis=1
    )
    sub = sub.dropna(subset=["_date"])
    if sub.empty:
        st.caption("선택된 관정의 시기 정보가 누락되어 표시할 수 없습니다.")
        return

    info = ag_well_loader.get_well_info(permit_no)
    aws_name = _select_aws_for_well(info or {})
    well_id = (info.get("well_id") if info else permit_no) or permit_no

    # ── 두 차트가 공유할 X tick · 범위 (사용자 요청 #10·#11)
    yh_min = int(sub["_yh"].min())
    yh_max = int(sub["_yh"].max())
    tick_dates: list[pd.Timestamp] = []
    tick_text: list[str] = []
    for i in range(yh_min, yh_max + 1):
        y = i // 2
        h = "상" if i % 2 == 0 else "하"
        d = _yh_to_date(y, h)
        tick_dates.append(d)
        # 매 바마다 "상/하" + 연도 모두 표시 (요청 #10)
        tick_text.append(f"{h}<br>{y}")
    x_min = tick_dates[0] - pd.Timedelta(days=120)
    x_max = tick_dates[-1] + pd.Timedelta(days=120)

    # ── (1) 선택 항목 단일 막대 (제목에 well_id 포함, 요청 #7)
    _render_quality_bar(sub, item, tick_dates, tick_text, x_min, x_max,
                         well_id=well_id)

    # ── (2) AWS 반기강수량 막대 (Y=0~1000, 동일 X 축)
    _render_rainfall_bar(aws_name, tick_dates, tick_text, x_min, x_max)

    # ── (3) 5항목 시계열 표 (행=항목, 열=시기) + well_id 제목
    _render_quality_table(sub, well_id)


# 반기별 막대 색상 — 4 가지 조합 (상/하 × 정상/부적합).
#   사용자 요청: 부적합일 때도 상/하 가 색깔로 구분되어야 함.
#   - 상 정상: 라이트 그린 / 하 정상: 다크 그린
#   - 상 부적합: 라이트 레드 / 하 부적합: 다크 레드
#   라이트(연한)/다크(짙은) 의 톤 차이로 부적합 안에서도 상/하 구분 가능.
_BAR_COLOR_HALF = {"상": "#9CCC65", "하": "#33691E"}
_BAR_COLOR_EXCEED_HALF = {"상": "#EF9A9A", "하": "#B71C1C"}
# 레거시 호환: 단색 부적합 색상 (다른 곳에서 import 했을 때 깨지지 않게)
_BAR_COLOR_EXCEED = "#C00000"


def _bar_color(half: str, exceed: bool) -> str:
    """막대 색상: (반기, 부적합) 조합으로 4가지."""
    h = str(half).strip()
    if exceed:
        return _BAR_COLOR_EXCEED_HALF.get(h, "#C00000")
    return _BAR_COLOR_HALF.get(h, "#9CCC65")


def _render_quality_bar(
    sub: pd.DataFrame, item: str,
    tick_dates: list, tick_text: list,
    x_min: pd.Timestamp, x_max: pd.Timestamp,
    well_id: str = "",
) -> None:
    """선택 항목의 시계열 막대.

    - Y 축: 기준값 × 2 (사용자 요청 #13 — 질산성질소 기준 30 → 40).
            기준 없는 EC 는 데이터 max × 1.3.
    - 바 위 라벨: 측정값.
    - X 축: 호출자가 빌드한 tick_dates/tick_text 사용 — 매 바 아래 "상/하 + YYYY"
            (요청 #10), 강수량 차트와 X 축 공유 (요청 #11).
    - 바 색상: 상=라이트그린, 하=다크그린, 부적합=빨강.
    """
    std = config.WATER_QUALITY_STANDARDS.get(item, {})
    item_kor = std.get("kor", item)
    unit = std.get("unit", "")

    if item not in sub.columns:
        st.caption(f"{item_kor} 자료가 없습니다.")
        return
    ys = sub[item]
    if ys.dropna().empty:
        st.caption(f"{item_kor} 측정값이 없습니다.")
        return

    # Y 축 max — 기준값 × 2 (요청 #13)
    if "max" in std:
        y_top = float(std["max"]) * 2.0
    else:
        data_max = float(ys.dropna().max())
        y_top = max(data_max * 1.3, 1.0)

    # 사용자 요청 #1: 항목별 소수점 자릿수 고정.
    text_labels = [
        "" if pd.isna(v) else _fmt_item(v, item)
        for v in ys
    ]

    exc_col = f"{item}_exceed"
    excs = (
        sub[exc_col].fillna(False).astype(bool).tolist()
        if exc_col in sub.columns else [False] * len(sub)
    )
    halves = [str(h).strip() for h in sub["half"].tolist()]
    # 사용자 요청 #3: 부적합 시에도 상/하 색상 구분 (4가지 조합)
    bar_colors = [_bar_color(h, e) for e, h in zip(excs, halves)]

    x_dates = sub["_date"].tolist()

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=x_dates, y=ys,
        marker_color=bar_colors,
        text=text_labels,
        textposition="outside",
        textfont=dict(size=10, color="#1a1a18"),
        cliponaxis=False,
        width=1000 * 60 * 60 * 24 * 90,  # 90 days in ms
        hovertemplate=f"<b>%{{x|%Y-%m}}</b><br>{item_kor}: %{{y:.2f}} {unit}<extra></extra>",
        name=item_kor,
    ))

    if "max" in std:
        fig.add_hline(
            y=std["max"], line_dash="dash", line_color="#A50026",
            line_width=1.2, opacity=0.7,
            annotation_text=f"기준 ≤ {std['max']} {unit}",
            annotation_position="top right",
            annotation_font=dict(size=10, color="#A50026"),
        )
    if "min" in std:
        fig.add_hline(
            y=std["min"], line_dash="dash", line_color="#A50026",
            line_width=1.2, opacity=0.6,
            annotation_text=f"기준 ≥ {std['min']} {unit}",
            annotation_position="bottom right",
            annotation_font=dict(size=10, color="#A50026"),
        )

    # 사용자 요청 #7: 선택 관정명을 제목에 포함
    title_prefix = f"{well_id} " if well_id else ""
    st.markdown(
        f'<div style="font-size:13px;font-weight:600;color:#185fa5;'
        f'margin-top:10px;margin-bottom:0;">'
        f'{title_prefix}{item_kor} 시계열 ({unit})'
        f'</div>',
        unsafe_allow_html=True,
    )
    fig.update_layout(
        height=320,
        margin=dict(l=10, r=10, t=24, b=64),
        plot_bgcolor="white",
        showlegend=False,
        bargap=0.2,
    )
    fig.update_yaxes(
        range=[0, y_top], tickfont=dict(size=10),
        title=dict(text=unit, font=dict(size=10)),
    )
    # X 축 — 호출자가 빌드한 공유 tick 사용 (강수량 차트와 동일)
    fig.update_xaxes(
        tickvals=tick_dates, ticktext=tick_text,
        range=[x_min, x_max],
        tickangle=0, tickfont=dict(size=10),
        title=None,
    )
    st.plotly_chart(fig, use_container_width=True)


# 강수량 막대 색상 — 사용자 요청 #12: 푸른 계열, 상/하 색상 차별화.
_RAIN_COLOR_HALF = {"상": "#9CC3D5", "하": "#1F4E79"}


def _render_rainfall_bar(
    aws_name: str | None,
    tick_dates: list, tick_text: list,
    x_min: pd.Timestamp, x_max: pd.Timestamp,
) -> None:
    """반기강수량 막대 (½ 높이, Y=0~1000).

    - 6개월 합계: 1~6월 → 상, 7~12월 → 하.
    - Y 축: 0 ~ 1000 mm, dtick=250 (요청 #4).
    - X 축: 수질 차트와 동일 tickvals/ticktext 사용 (요청 #11).
    - 색상: 상=라이트블루, 하=다크블루 (요청 #12).
    """
    if not aws_name:
        st.caption("적용 AWS 가 매핑되지 않아 강수량 그래프를 생략합니다.")
        return

    asos_df = asos_collector.load_asos_data()
    if asos_df is None or asos_df.empty:
        st.caption("ASOS 강수량 자료를 찾을 수 없습니다.")
        return

    sub = asos_df[asos_df["지점명"] == aws_name].copy()
    if sub.empty:
        st.caption(f"{aws_name} AWS 자료가 없습니다.")
        return

    sub["일시"] = pd.to_datetime(sub["일시"], errors="coerce")
    sub = sub.dropna(subset=["일시"])
    sub = sub[(sub["일시"] >= x_min) & (sub["일시"] <= x_max)]
    if sub.empty:
        st.caption(f"{aws_name} AWS — 해당 기간 자료가 없습니다.")
        return

    # 반기 합계
    sub["_y"] = sub["일시"].dt.year
    sub["_half"] = sub["일시"].dt.month.apply(lambda m: "상" if m <= 6 else "하")
    rain = (
        sub.groupby(["_y", "_half"])["일강수량(mm)"]
           .sum().reset_index()
    )
    rain.columns = ["year", "half", "rainfall"]
    rain["period"] = rain.apply(
        lambda r: _yh_to_date(r["year"], r["half"]), axis=1
    )
    rain = rain.dropna(subset=["period"]).sort_values("period")

    if rain.empty:
        st.caption(f"{aws_name} AWS — 반기 합계 자료가 없습니다.")
        return

    # 색상 — 푸른 계열 (요청 #12)
    bar_colors = [
        _RAIN_COLOR_HALF.get(str(h), "#5B9BD5") for h in rain["half"]
    ]

    st.markdown(
        f'<div style="font-size:13px;font-weight:600;color:#185fa5;'
        f'margin-top:6px;margin-bottom:0;">'
        f'{aws_name} AWS 반기강수량 (mm)'
        f'</div>',
        unsafe_allow_html=True,
    )
    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=rain["period"], y=rain["rainfall"],
        marker_color=bar_colors,
        width=1000 * 60 * 60 * 24 * 90,
        text=[f"{v:.0f}" for v in rain["rainfall"]],
        textposition="outside",
        textfont=dict(size=9),
        cliponaxis=False,
        hovertemplate=(
            "%{x|%Y-%m}<br>반기 강수량: %{y:,.0f} mm<extra></extra>"
        ),
    ))
    fig.update_layout(
        height=160,
        margin=dict(l=10, r=10, t=10, b=64),
        plot_bgcolor="white",
        showlegend=False,
        bargap=0.2,
    )
    fig.update_yaxes(
        range=[0, 1000], dtick=250,
        tickfont=dict(size=9),
        title=dict(text="mm", font=dict(size=10)),
    )
    # X 축 — 수질 차트와 동일 (요청 #11)
    fig.update_xaxes(
        tickvals=tick_dates, ticktext=tick_text,
        range=[x_min, x_max],
        tickangle=0, tickfont=dict(size=10),
        title=None,
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_quality_table(sub: pd.DataFrame, well_id: str) -> None:
    """5항목 시계열 표 (행=항목, 열=시기).

    헤더 2단 (요청 #9):
      - 1행: 항목(rowspan=2) + 연도(colspan=2) ...
      - 2행: 상 / 하 / 상 / 하 ...
    제목: "{well_id} 수질 5항목 시계열 표" (요청 #7).
    부적합 셀 빨강 + 굵게.
    """
    items = QUALITY_ITEM_ORDER

    # ── 시기 컬럼 결정 — sub 에 존재하는 모든 (year, half) 페어를 정렬해 그대로 사용.
    #   같은 (year, half) 가 중복되면 가장 마지막 행 채택 (sub 는 _yh 기준 정렬됨).
    sub_v = sub.dropna(subset=["year"]).copy()
    if sub_v.empty:
        st.caption("표시할 시기 자료가 없습니다.")
        return
    sub_v["_yint"] = sub_v["year"].astype("Int64").astype(int)
    sub_v["_hstr"] = sub_v["half"].astype(str).str.strip()

    # 데이터에 등장하는 모든 (year, half) → 한 셀당 한 행 dict 매핑
    row_by_yh: dict[tuple[int, str], pd.Series] = {}
    for _, r in sub_v.iterrows():
        row_by_yh[(int(r["_yint"]), r["_hstr"])] = r

    # 컬럼 시기 = 가용한 모든 연도 × (상, 하) — 데이터에 한 쪽만 있어도 양쪽 컬럼 생성해
    # year colspan=2 가 깨지지 않도록 (요청 #9).
    years_present = sorted(sub_v["_yint"].unique().tolist())
    period_cols: list[tuple[int, str]] = [
        (y, h) for y in years_present for h in ("상", "하")
    ]
    if not period_cols:
        st.caption("표시할 시기 자료가 없습니다.")
        return

    css = """
    <style>
    .qty-table-wrap {
        width: 100%;
        overflow-x: auto;
        margin: 10px 0 8px;
    }
    .qty-table {
        border-collapse: collapse;
        font-size: 11.5px; color: #1a1a18;
        border: 0.5px solid rgba(26,26,24,0.18);
        min-width: 100%;
    }
    .qty-table th, .qty-table td {
        padding: 4px 6px;
        border: 0.5px solid rgba(26,26,24,0.10);
        text-align: center;
        font-variant-numeric: tabular-nums;
        white-space: nowrap;
    }
    .qty-table thead th.year-th {
        background: #185fa5; color: #ffffff;
        font-weight: 700; font-size: 12px;
    }
    .qty-table thead th.half-th {
        background: #e6f1fb; color: #185fa5;
        font-weight: 600; font-size: 11px;
    }
    .qty-table thead th.item-th {
        background: #0a316e; color: #ffffff;
        font-weight: 700; vertical-align: middle;
        text-align: left; padding-left: 10px;
    }
    .qty-table td.item-cell {
        background: #f5f5f3;
        color: #185fa5; font-weight: 600;
        text-align: left; padding-left: 10px;
        min-width: 110px;
    }
    .qty-table td.exceed {
        background: #fdecea;
        color: #C00000; font-weight: 700;
    }
    .qty-table tbody tr:nth-child(even) td:not(.item-cell):not(.exceed) {
        background: #fafaf8;
    }
    /* 연도 경계선 (홀수 컬럼 = 새 연도 시작) */
    .qty-table th.year-sep, .qty-table td.year-sep {
        border-left: 2px solid #185fa5 !important;
    }
    </style>
    """

    # ── 1행 헤더: 항목(rowspan=2) + 연도(colspan=2) 반복
    head1 = ['<tr><th class="item-th" rowspan="2">항목</th>']
    for i, y in enumerate(years_present):
        sep_cls = " year-sep" if i > 0 else ""
        head1.append(f'<th class="year-th{sep_cls}" colspan="2">{y}</th>')
    head1.append("</tr>")

    # ── 2행 헤더: 상반기 / 하반기 반복 (사용자 요청 #5)
    head2 = ["<tr>"]
    for i, _y in enumerate(years_present):
        sep_cls = " year-sep" if i > 0 else ""
        head2.append(f'<th class="half-th{sep_cls}">상반기</th>')
        head2.append('<th class="half-th">하반기</th>')
    head2.append("</tr>")

    head = "<thead>" + "".join(head1) + "".join(head2) + "</thead>"

    def _cell(v, exceed: bool, item: str, sep: bool) -> str:
        sep_cls = " year-sep" if sep else ""
        if v is None or (isinstance(v, float) and pd.isna(v)):
            # 사용자 요청 #3: 측정값 없으면 '0' 도 안 적고 '-' 표시
            return f'<td class="{sep_cls.strip()}">-</td>' if sep_cls else '<td>-</td>'
        text = _fmt_item(v, item)
        cls = ("exceed" + sep_cls).strip() if exceed else sep_cls.strip()
        if cls:
            return f'<td class="{cls}">{text}</td>'
        return f'<td>{text}</td>'

    body_rows = []
    for it in items:
        std = config.WATER_QUALITY_STANDARDS.get(it, {})
        item_label = (
            f'{std.get("kor", it)} '
            f'<span style="font-weight:400;opacity:0.85;font-size:10.5px;">'
            f'({std.get("unit", "")})</span>'
        )

        cells = [f'<td class="item-cell">{item_label}</td>']
        for col_idx, (y, h) in enumerate(period_cols):
            r = row_by_yh.get((y, h))
            v = r.get(it) if (r is not None and it in r.index) else None
            exc = bool(r.get(f"{it}_exceed")) if r is not None else False
            # 새 연도의 첫 컬럼(=상)에 좌측 경계선
            sep = (h == "상" and col_idx > 0)
            cells.append(_cell(v, exc, it, sep))
        body_rows.append("<tr>" + "".join(cells) + "</tr>")

    table = (
        css
        + '<div class="qty-table-wrap">'
        + '<table class="qty-table">'
        + head
        + "<tbody>" + "".join(body_rows) + "</tbody>"
        + "</table></div>"
    )
    # 요청 #7: 제목에 well_id 포함
    st.markdown(
        f'<div style="font-size:13px;font-weight:600;color:#185fa5;'
        f'margin-top:8px;margin-bottom:0;">'
        f'{well_id} 수질 5항목 시계열 표</div>',
        unsafe_allow_html=True,
    )
    st.markdown(table, unsafe_allow_html=True)


# ==============================================================================
#  그룹별 박스 플롯 + 시계열 표 (사용자 요청 #5·#6·#7)
# ==============================================================================
def _region_label_short(loc_sel: dict) -> str:
    """그룹 분석 제목용 짧은 지역명. 가장 좁은 cascading 단계 우선."""
    return (
        loc_sel.get("well_ri")
        or loc_sel.get("well_eup")
        or loc_sel.get("well_si")
        or "제주도 전역"
    )


def _render_group_section(
    qf: pd.DataFrame,
    item: str,
    level: str,
    loc_sel: dict,
    yh_lo: tuple[int, str],
    yh_hi: tuple[int, str],
) -> None:
    """집계 단위(level) 의 한 단계 아래 그룹(loc_col) 단위로 분석:
       (1) 박스 플롯 (분석기간 마지막 연도) — 그룹별 분포
       (2) 박스 플롯 (전 분석기간) — 상/하반기 분포
       (3) 시계열 표 — 행=그룹, 열=시기 평균값
    """
    if qf.empty or item not in qf.columns:
        return

    loc_col, loc_label_kor = _LEVEL_TO_LOC_COL.get(level, (None, None))
    if not loc_col or loc_col not in qf.columns:
        return

    std = config.WATER_QUALITY_STANDARDS.get(item, {})
    item_kor = std.get("kor", item)
    unit = std.get("unit", "")
    region = _region_label_short(loc_sel)

    # ── 그룹 컬럼 정리 (빈 문자열·nan 제거)
    work = qf.dropna(subset=[item, loc_col]).copy()
    work[loc_col] = work[loc_col].astype(str).str.strip()
    work = work[work[loc_col] != ""]
    work = work[~work[loc_col].str.lower().isin(["nan", "none"])]
    if work.empty:
        st.caption("그룹별 분석에 사용할 자료가 없습니다.")
        return

    # ── (1) 마지막 연도 그룹별 박스 플롯
    _render_group_box_latest(work, item, loc_col, loc_label_kor,
                              region, item_kor, unit)

    # ── (2) 상/하반기 박스 플롯 (분석기간 전체)
    _render_half_box(work, item, region, item_kor, unit, yh_lo, yh_hi)

    # ── (3) 그룹 × 시기 시계열 표
    _render_group_timeseries_table(work, item, loc_col, loc_label_kor,
                                    region, item_kor, unit)


def _render_group_box_latest(
    work: pd.DataFrame, item: str, loc_col: str, loc_label_kor: str,
    region: str, item_kor: str, unit: str,
) -> None:
    """그룹별 박스 플롯 — 분석기간 내 가장 최근 연도 데이터."""
    if "year" not in work.columns or work["year"].dropna().empty:
        return
    latest_year = int(work["year"].dropna().max())
    sub = work[work["year"] == latest_year]
    if sub.empty:
        return

    # 그룹 정렬 — 평균값 내림차순 (이용량 탭과 동일)
    order = (
        sub.groupby(loc_col)[item].mean()
           .sort_values(ascending=False).index.tolist()
    )
    if not order:
        return

    std = config.WATER_QUALITY_STANDARDS.get(item, {})
    fig = go.Figure()
    for g in order:
        gv = sub[sub[loc_col] == g][item].dropna()
        if gv.empty:
            continue
        fig.add_trace(go.Box(
            y=gv, name=str(g),
            boxpoints="outliers",
            marker=dict(size=4, color="#305496"),
            line=dict(width=1.2, color="#305496"),
            fillcolor="#9DC3E6",
        ))
    # 기준선
    if "max" in std:
        fig.add_hline(
            y=std["max"], line_dash="dash", line_color="#A50026",
            line_width=1.0, opacity=0.7,
            annotation_text=f"기준 ≤ {std['max']}",
            annotation_font=dict(size=9, color="#A50026"),
        )
    if "min" in std:
        fig.add_hline(
            y=std["min"], line_dash="dash", line_color="#A50026",
            line_width=1.0, opacity=0.6,
        )
    fig.update_layout(
        height=320,
        margin=dict(l=10, r=10, t=10, b=70),
        plot_bgcolor="white",
        showlegend=False,
    )
    fig.update_xaxes(title=loc_label_kor,
                     tickfont=dict(size=10), tickangle=-30)
    fig.update_yaxes(title=f"{item_kor} ({unit})", tickfont=dict(size=9))

    st.markdown(
        f'<div style="font-size:13px;font-weight:600;color:#185fa5;'
        f'margin-top:14px;margin-bottom:0;">'
        f'{region} {item_kor} 현황 ({latest_year}년)'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_half_box(
    work: pd.DataFrame, item: str,
    region: str, item_kor: str, unit: str,
    yh_lo: tuple[int, str], yh_hi: tuple[int, str],
) -> None:
    """기간 내 (연도, 반기) 별 박스 플롯 (사용자 요청 #4·#5).

    각 박스 = 한 (연도, 반기) 시점의 「관정별 측정값 분포」.
    분석 기간 슬라이더 범위에 포함된 모든 (year, half) 쌍을 시간 순서로 나열.
    상=라이트 그린, 하=다크 그린.
    """
    if "half" not in work.columns or "year" not in work.columns:
        return
    sub = work.dropna(subset=[item, "year", "half"]).copy()
    sub["half"] = sub["half"].astype(str).str.strip()
    sub = sub[sub["half"].isin(["상", "하"])]
    if sub.empty:
        return

    sub["_yint"] = sub["year"].astype("Int64").astype(int)

    # 슬라이더 범위 내 모든 (year, half) 페어
    lo_idx = _yh_idx(*yh_lo)
    hi_idx = _yh_idx(*yh_hi)
    periods: list[tuple[int, str]] = []
    for i in range(lo_idx, hi_idx + 1):
        y = i // 2
        h = "상" if i % 2 == 0 else "하"
        periods.append((y, h))

    std = config.WATER_QUALITY_STANDARDS.get(item, {})
    color_map = {"상": "#9CCC65", "하": "#33691E"}

    fig = go.Figure()
    for y, h in periods:
        gv = sub[(sub["_yint"] == y) & (sub["half"] == h)][item].dropna()
        if gv.empty:
            continue
        c = color_map.get(h, "#305496")
        fig.add_trace(go.Box(
            y=gv, name=f"{y}-{h}",
            boxpoints="outliers",
            marker=dict(size=4, color=c),
            line=dict(width=1.2, color=c),
            fillcolor=_hex_to_rgba(c, 0.25),
            hovertemplate=(
                f"<b>{y}-{h}</b><br>"
                f"{item_kor}: %{{y:.2f}} {unit}<br>"
                f"관정별 측정값<extra></extra>"
            ),
        ))
    if "max" in std:
        fig.add_hline(
            y=std["max"], line_dash="dash", line_color="#A50026",
            line_width=1.0, opacity=0.7,
            annotation_text=f"기준 ≤ {std['max']}",
            annotation_font=dict(size=9, color="#A50026"),
        )
    if "min" in std:
        fig.add_hline(
            y=std["min"], line_dash="dash", line_color="#A50026",
            line_width=1.0, opacity=0.6,
        )
    fig.update_layout(
        height=320,
        margin=dict(l=10, r=10, t=10, b=40),
        plot_bgcolor="white",
        showlegend=False,
    )
    fig.update_xaxes(title=None, tickfont=dict(size=10), tickangle=-30)
    fig.update_yaxes(title=f"{item_kor} ({unit})", tickfont=dict(size=9))

    st.markdown(
        f'<div style="font-size:13px;font-weight:600;color:#185fa5;'
        f'margin-top:14px;margin-bottom:0;">'
        f'{region} 상·하반기별 {item_kor} 현황 (Box Plot) '
        f'({yh_lo[0]}년 ~ {yh_hi[0]}년)'
        f'</div>'
        f'<div style="font-size:11px;color:#5f5e5a;margin:0 0 4px;">'
        f'각 박스 = 해당 (연도-반기) 의 관정별 측정값 분포'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.plotly_chart(fig, use_container_width=True)


def _render_group_timeseries_table(
    work: pd.DataFrame, item: str, loc_col: str, loc_label_kor: str,
    region: str, item_kor: str, unit: str,
) -> None:
    """그룹 × 시기 평균값 표 (사용자 요청 #7).

    구조 (well 5항목 표와 동일 형식):
      - 행: 그룹 (예: 리)
      - 열: 시기(연도-반기) 2단 헤더 (위=연도 colspan=2, 아래=상/하)
      - 값: 그룹×시기의 item 평균
      - 기준 초과 셀 빨강 강조.
    """
    sub_v = work.dropna(subset=["year", "half", item]).copy()
    sub_v["_yint"] = sub_v["year"].astype("Int64").astype(int)
    sub_v["_hstr"] = sub_v["half"].astype(str).str.strip()
    sub_v = sub_v[sub_v["_hstr"].isin(["상", "하"])]
    if sub_v.empty:
        return

    years_present = sorted(sub_v["_yint"].unique().tolist())
    period_cols = [(y, h) for y in years_present for h in ("상", "하")]

    # 그룹 정렬 — 전체 평균 내림차순
    order = (
        sub_v.groupby(loc_col)[item].mean()
             .sort_values(ascending=False).index.tolist()
    )

    # 그룹 × (year, half) 평균
    grp_avg = (
        sub_v.groupby([loc_col, "_yint", "_hstr"])[item]
             .mean().reset_index()
    )
    val_lookup: dict[tuple[str, int, str], float] = {
        (r[loc_col], int(r["_yint"]), str(r["_hstr"])): float(r[item])
        for _, r in grp_avg.iterrows()
    }

    std = config.WATER_QUALITY_STANDARDS.get(item, {})
    std_max = std.get("max")
    std_min = std.get("min")

    def _is_exceed(v: float) -> bool:
        if v is None or pd.isna(v):
            return False
        if std_max is not None and v > std_max:
            return True
        if std_min is not None and v < std_min:
            return True
        return False

    css = """
    <style>
    .qty-grp-table-wrap { width:100%; overflow-x:auto; margin: 8px 0 8px; }
    .qty-grp-table {
        border-collapse: collapse;
        font-size: 11.5px; color: #1a1a18;
        border: 0.5px solid rgba(26,26,24,0.18);
        min-width: 100%;
    }
    .qty-grp-table th, .qty-grp-table td {
        padding: 4px 6px;
        border: 0.5px solid rgba(26,26,24,0.10);
        text-align: center;
        font-variant-numeric: tabular-nums;
        white-space: nowrap;
    }
    .qty-grp-table thead th.year-th {
        background: #185fa5; color: #ffffff;
        font-weight: 700; font-size: 12px;
    }
    .qty-grp-table thead th.half-th {
        background: #e6f1fb; color: #185fa5;
        font-weight: 600; font-size: 11px;
    }
    .qty-grp-table thead th.item-th {
        background: #0a316e; color: #ffffff;
        font-weight: 700; vertical-align: middle;
        text-align: center;
    }
    .qty-grp-table td.item-cell {
        background: #f5f5f3;
        color: #185fa5; font-weight: 600;
        text-align: center;
        min-width: 100px;
    }
    .qty-grp-table td.exceed {
        background: #fdecea;
        color: #C00000; font-weight: 700;
    }
    .qty-grp-table tbody tr:nth-child(even)
        td:not(.item-cell):not(.exceed) {
        background: #fafaf8;
    }
    .qty-grp-table th.year-sep, .qty-grp-table td.year-sep {
        border-left: 2px solid #185fa5 !important;
    }
    </style>
    """

    head1 = [f'<tr><th class="item-th" rowspan="2">{loc_label_kor}</th>']
    for i, y in enumerate(years_present):
        sep = " year-sep" if i > 0 else ""
        head1.append(f'<th class="year-th{sep}" colspan="2">{y}</th>')
    head1.append("</tr>")

    # 사용자 요청 #5: 상 / 하 → 상반기 / 하반기
    head2 = ["<tr>"]
    for i, _y in enumerate(years_present):
        sep = " year-sep" if i > 0 else ""
        head2.append(f'<th class="half-th{sep}">상반기</th>')
        head2.append('<th class="half-th">하반기</th>')
    head2.append("</tr>")

    head = "<thead>" + "".join(head1) + "".join(head2) + "</thead>"

    body_rows = []
    for grp in order:
        # 사용자 요청 #4: 리 셀 중앙정렬 (CSS 의 .item-cell 이 처리)
        cells = [f'<td class="item-cell">{grp}</td>']
        for col_idx, (y, h) in enumerate(period_cols):
            v = val_lookup.get((grp, y, h))
            sep = (h == "상" and col_idx > 0)
            sep_cls = " year-sep" if sep else ""
            if v is None or pd.isna(v):
                cells.append(
                    f'<td class="{sep_cls.strip()}">-</td>' if sep_cls
                    else '<td>-</td>'
                )
            else:
                text = _fmt_item(v, item)
                exc = _is_exceed(v)
                cls = ("exceed" + sep_cls).strip() if exc else sep_cls.strip()
                if cls:
                    cells.append(f'<td class="{cls}">{text}</td>')
                else:
                    cells.append(f'<td>{text}</td>')
        body_rows.append("<tr>" + "".join(cells) + "</tr>")

    table = (
        css
        + '<div class="qty-grp-table-wrap">'
        + '<table class="qty-grp-table">'
        + head
        + "<tbody>" + "".join(body_rows) + "</tbody>"
        + "</table></div>"
    )

    st.markdown(
        f'<div style="font-size:13px;font-weight:600;color:#185fa5;'
        f'margin-top:14px;margin-bottom:0;">'
        f'{region} {loc_label_kor}별 {item_kor} 시계열 표 '
        f'<span style="font-size:11px;font-weight:400;color:#5f5e5a;">'
        f'(셀 값 = 해당 {loc_label_kor}·시기 평균)</span>'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.markdown(table, unsafe_allow_html=True)
