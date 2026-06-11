# ==============================================================================
#  파일명: src/dashboard/ag_map_builders.py
#  농업용 관정 지도 빌더 — folium 기반 마커 지도 + 선택 관정 zoom-in 헬퍼.
#
#  Source 분리: ag_well_helpers.py 1366줄 → 그룹별 분리 4단계 (2026-05-09).
#    - maybe_recenter_to_selected_well : 관정 선택 시 지도 중심·줌 갱신 (fingerprint 패턴)
#    - build_search_map                 : 검색 탭 ⑥ 마커 지도 (414+ 공)
#    - build_usage_map                  : 이용량 탭 ⑦ 6단계 그라디언트 지도
#
#  호환성: ag_well_helpers.py 가 이 모듈에서 모두 re-export → 기존 호출처
#  (`ag_well_helpers.build_search_map(...)` 등) 그대로 동작.
#  외부 호출:
#    - maybe_recenter_to_selected_well : tab11_ag_search.py, tab12_ag_usage.py, tab13_ag_quality.py
#    - build_search_map                : tab11_ag_search.py
#    - build_usage_map                 : tab12_ag_usage.py (×2)
# ==============================================================================
from __future__ import annotations

import html
from functools import lru_cache

import folium
import pandas as pd
import streamlit as st

import config


@lru_cache(maxsize=1)
def _daily_usage_color_lut() -> "tuple[str, ...]":
    """Tab23(공간분석) 동그라미와 동일한 'per_well_daily' 색계조를 folium 마커에
    쓰기 위한 색 LUT (0~1600 ㎥/공·일을 101단계로 샘플).

    figures/_dual_zone_common/color.DAILY_USAGE_COLORSCALE 와 동일 stop 사용 →
    Tab12 이용량 지도 마커와 Tab23 동그라미가 같은 색 의미(800 navy 임계,
    1200 orange, 1600+ red)를 공유한다. (사용자 요청 2026-05-27)
    """
    from plotly.colors import sample_colorscale
    from src.dashboard.figures._dual_zone_common.color import (
        DAILY_USAGE_COLORSCALE,
    )
    ts = [i / 100.0 for i in range(101)]
    return tuple(sample_colorscale(DAILY_USAGE_COLORSCALE, ts))


# Tab23 와 동일한 절대 색 도메인 (per_well_daily)
_DAILY_USAGE_COLOR_VMAX: float = 1600.0


@lru_cache(maxsize=1)
def _dup_well_ids() -> "frozenset[str]":
    """master.csv 에서 중복된 well_id 집합 (tooltip 정확 식별용).
    중복 well_id 마커만 tooltip 에 |permit 을 덧붙여 클릭 해석을 보정한다."""
    try:
        from src.dashboard.permit_lookup import _well_id_lookup_data
        return _well_id_lookup_data()[1]
    except Exception:  # noqa: BLE001
        return frozenset()


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
        # Quantization — st_folium 이 returned_objects.center/zoom 을 round 4 로
        # 돌려주는 것과 정확히 같은 정밀도로 저장. 오류분석 에이전트(2026-05-12)
        # 진단: raw float vs round-4 mismatch 가 매 마커 클릭마다 folium.Map 새
        # 객체를 만들어 streamlit-folium iframe 재페인트(흰 깜박임) 의 가장 강한
        # 잔존 race. tab04_map.py:200-215, tab11_ag_search.py:285-294 와 동일 정책.
        st.session_state[center_key] = (
            round(float(lat), 4), round(float(lon), 4)
        )
        st.session_state[zoom_key] = round(float(target_zoom) * 2) / 2
        st.session_state[fingerprint_key] = sel_permit


# ------------------------------------------------------------------------------
#  ■ 검색 지도 (414공 마커 + MarkerCluster)
# ------------------------------------------------------------------------------
def build_search_map(
    df: pd.DataFrame,
    selected_permit: str | None = None,
    height: int = 480,
    zoom: int = 11,
    center: tuple[float, float] = (33.42, 126.55),
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

        # 마커 hit-area 개선 (사용자 요청 #4) — radius 비선택 5→7, 선택 9→12.
        # 농업용·관측소(map_helpers.py) 모두 선택=12 로 통일.
        # weight 1.2→2 도 함께 올려 stroke 절반이 외측 hit-area 로 추가됨
        # (시각 차이는 미미하나 클릭 정밀도 큰 개선).
        radius = 12 if is_sel else 7
        # 사용자 요청 (2026-05-16): 영문 authority (jeju/seogwipo 2종) 대신
        # authority_kor (제주시/서귀포시/농어촌공사/제주특별자치도 4종) 사용.
        # 농어촌공사 13공 + 제주특별자치도 7공이 별도 색으로 식별됨.
        auth_kor = r.get("authority_kor") or ""
        color = config.AG_AUTHORITY_PALETTE.get(auth_kor, "#7F7F7F")
        edge  = "#C00000" if is_sel else color

        # 2줄 구성: 관정명(굵게) / 읍면 리
        loc_parts = [_clean(r.get("well_eup")), _clean(r.get("well_ri"))]
        loc = " ".join(p for p in loc_parts if p)
        loc_line = (
            f'<br><span style="color:var(--color-text-primary);font-size:11px;">{loc}</span>'
            if loc else ""
        )

        # 숨김 span 으로 permit_no 를 popup HTML 에 포함 → 클릭 시 파싱용
        # (사용자에게는 보이지 않음, parse_clicked_popup 정규식이 추출)
        # G2 fix 2026-05-30: XSS/HTML 깨짐 방어 — well_id/permit html.escape().
        # permit_no 는 영숫자만이라 parse_clicked_popup 정규식 그대로 호환.
        _eid = html.escape(str(well_id))
        _eperm = html.escape(str(permit))
        popup_html = (
            f'<div style="font-size:12px;line-height:1.45;min-width:130px;">'
            f'<b>{_eid}</b>{loc_line}'
            f'<span style="display:none;">{_eperm}</span></div>'
        )
        # 선택 마커는 halo (반투명 외곽 원) 를 먼저 깔아 시각 피드백 강화.
        # class_name=sel-halo 가 pointer-events:none 으로 클릭 가로채기 방지.
        if is_sel:
            folium.CircleMarker(
                location=[r["lat"], r["lon"]],
                radius=int(radius * 1.7),
                color="transparent", weight=0,
                fill=True, fill_color="#e24b4a", fill_opacity=0.18,
                class_name="sel-halo",
            ).add_to(m)
        folium.CircleMarker(
            location=[r["lat"], r["lon"]],
            radius=radius,
            color=edge, weight=3 if is_sel else 2,
            fill=True, fill_color=color,
            fill_opacity=0.85 if is_sel else 0.7,
            # tooltip = well_id 만. 허가번호는 사용자에게 노출하지 않음.
            # well_id 결측 row 는 master.csv 에 0건이지만 안전 fallback 유지.
            tooltip=((str(well_id).strip() + "|" + str(permit))
                     if (permit and str(well_id).strip() in _dup_well_ids())
                     else (well_id or permit)),
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
    center: tuple[float, float] = (33.42, 126.55),
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
    # 사용자 요청 (Phase 1-B, 2026-05-14): 4px 가 여전히 클릭 어려움 → 7px floor.
    #   multiplier 시퀀스를 한 칸 더 위로 + BASE_RADIUS 6→7.
    #   이전: [2/3, 1, 4/3, 5/3, 2, 7/3] × 6  → 가장 작은 = 4.0px,  최대 = 14.0px
    #   현재: [1, 4/3, 5/3, 2, 7/3, 8/3] × 7  → 가장 작은 = 7.0px,  최대 ≈ 18.7px
    #   tab8 (_tab13_helpers._SIZE_MULTIPLIERS / _BASE_RADIUS) 와 동기 조정.
    LEGEND_MIN = 0.0
    LEGEND_MAX = 1200.0
    BIN_BOUNDS = [200.0, 400.0, 600.0, 800.0, 1000.0, 1200.0]   # 6 buckets

    SIZE_MULTIPLIERS = [1.0, 4/3, 5/3, 2.0, 7/3, 8/3]
    BASE_RADIUS = 7.0
    NO_DATA_COLOR = "#CDD8DF"

    # 색상: Tab23(공간분석) 동그라미와 동일한 navy→gold→red 계조 (800 임계 강조)
    # 로 통일 (사용자 요청 2026-05-27). 절대 도메인 0~1600 ㎥/공·일.
    # ※ 마커 '크기' 는 기존 6단계 binning(BIN_BOUNDS) 유지 — 색만 교체.
    _COLOR_LUT = _daily_usage_color_lut()
    _COLOR_VMAX = _DAILY_USAGE_COLOR_VMAX

    def _bin_idx(d: float) -> int | None:
        if d is None or d <= 0:
            return None
        for i, b in enumerate(BIN_BOUNDS):
            if d < b:
                return i
        return 5   # ≥ 1000 → 가장 큰 크기

    def _radius(d: float) -> float:
        idx = _bin_idx(d)
        if idx is None:
            return BASE_RADIUS * 0.5    # 자료 없음 — 작은 회색 점
        return BASE_RADIUS * SIZE_MULTIPLIERS[idx]

    def _color(d: float) -> str:
        if d is None or d <= 0:
            return NO_DATA_COLOR
        t = min(1.0, max(0.0, float(d) / _COLOR_VMAX))
        return _COLOR_LUT[int(round(t * 100))]

    def _clean(v) -> str:
        if v is None or (isinstance(v, float) and pd.isna(v)):
            return ""
        s = str(v).strip()
        return "" if s in ("nan", "None", "NaN", "<NA>") else s

    # Phase 1-C (2026-05-14): z-order 정렬. 큰 마커(높은 daily_avg) 를 먼저
    # 그려서 작은 마커가 SVG layer 상단에 오도록 → 이웃이 겹칠 때 작은 마커의
    # hit-area 가 큰 마커에 가려지지 않음. NaN/0(자료 없음) 마커도 layer 위로
    # 올라가 클릭 가능. 색상 그라디언트로 큰 사용량 강조 의도는 보존.
    df_xy = df_xy.sort_values("daily_avg", ascending=False, na_position="last")

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
            f'<br><span style="color:var(--color-text-primary);font-size:11px;">{loc}</span>'
            if loc else ""
        )
        if vol > 0:
            stat_line = (
                f'<br><span style="color:var(--color-text-info);font-size:11px;">'
                f'기간 합계: {vol:,.0f} ㎥</span>'
                f'<br><span style="color:var(--color-text-info);font-size:11px;">'
                f'평균 일 사용량: {daily:,.0f} ㎥/일</span>'
            )
        else:
            stat_line = (
                '<br><span style="color:var(--color-text-tertiary);font-size:11px;">자료 없음</span>'
            )

        # G2 fix 2026-05-30: XSS 방어 — well_id/permit html.escape().
        _eid = html.escape(str(well_id))
        _eperm = html.escape(str(permit))
        popup_html = (
            f'<div style="font-size:12px;line-height:1.45;min-width:160px;">'
            f'<b>{_eid}</b>{loc_line}{stat_line}'
            f'<span style="display:none;">{_eperm}</span></div>'
        )
        # 선택 마커 halo (반투명 외곽 원) — class_name=sel-halo + pointer-events:none.
        if is_sel:
            folium.CircleMarker(
                location=[r["lat"], r["lon"]],
                radius=int(radius * 1.7),
                color="transparent", weight=0,
                fill=True, fill_color="#e24b4a", fill_opacity=0.18,
                class_name="sel-halo",
            ).add_to(m)
        folium.CircleMarker(
            location=[r["lat"], r["lon"]],
            radius=radius,
            color=edge, weight=5 if is_sel else 1.0,
            fill=True, fill_color=fill,
            fill_opacity=0.92,   # 색상 그라디언트가 더 선명하게 드러나도록 ↑
            tooltip=((str(well_id).strip() + "|" + str(permit))
                     if (permit and str(well_id).strip() in _dup_well_ids())
                     else (well_id or permit)),
            popup=folium.Popup(popup_html, max_width=220),
        ).add_to(m)

    # ── Legend (좌하단) — Tab23 동그라미와 동일한 연속 색 막대 (0~1600 ㎥/공·일).
    #   navy(800 임계)에서 gold 로 색 단절 → "800 이상 다량 사용 관정" 강조.
    gradient_css = (
        "linear-gradient(to right,"
        "rgb(245,245,245) 0%,"
        "rgb(135,206,235) 25%,"
        "rgb(8,48,107) 50%,"
        "rgb(255,235,100) 50.01%,"
        "rgb(255,140,0) 75%,"
        "rgb(211,47,47) 100%)"
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
        color: var(--color-text-primary);
    ">
      <div style="font-weight:600;margin-bottom:4px;color:var(--color-text-info);">{legend_unit}</div>
      <div style="width:192px;height:12px;background:{gradient_css};
                  border:0.5px solid rgba(0,0,0,0.18);"></div>
      <div style="display:flex;font-size:10px;color:var(--color-text-secondary);
                  width:192px;justify-content:space-between;margin-top:1px;">
        <span>0</span>
        <span>400</span>
        <span>800</span>
        <span>1,200</span>
        <span>1,600+</span>
      </div>
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend_html))

    return m


# ──────────────────────────────────────────────────────────────────
#  G3 fix 2026-05-30: zoom/center 보존 헬퍼 — 3탭(11/12/13) 중복 해소.
#  이전엔 tab11/_tab12_map/_tab13_map 3곳에서 quantization 로직 복제:
#    - zoom round(*2)/2 (0.5 step)
#    - center round(lat,4)/round(lng,4) (~11m)
#  픽셀 미세 변동 quantize 로 folium props identity 안정화 → iframe 흰깜빡임 차단.
#  헬퍼는 click 만 받아 session_state 키 2개 갱신, 비정형 입력에서 예외/오염 없음.
# ──────────────────────────────────────────────────────────────────
def persist_zoom_center(click, *, zoom_key, center_key):
    """folium click dict 의 zoom/center 를 quantize 후 session_state 저장."""
    if not isinstance(click, dict):
        return
    z = click.get("zoom")
    c = click.get("center")
    if z is not None:
        try:
            st.session_state[zoom_key] = round(float(z) * 2) / 2
        except (TypeError, ValueError):
            pass
    if isinstance(c, dict) and "lat" in c and "lng" in c:
        try:
            st.session_state[center_key] = (
                round(float(c["lat"]), 4), round(float(c["lng"]), 4),
            )
        except (TypeError, ValueError):
            pass

