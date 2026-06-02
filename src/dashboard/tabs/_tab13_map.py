# ==============================================================================
#  파일명: src/dashboard/tabs/_tab13_map.py
#  ⑦ 수질 분석 탭 — KPI 카드 + 지도 + 컬러 레전드 + 위치 헬퍼
#
#  Source 분리: tab13_ag_quality.py 2101줄 → 그룹별 분리 3단계 (2026-05-09).
#    [위치]
#      - _maybe_recenter_map : loc 변경 시 지도 중심·줌 갱신 (fingerprint 패턴)
#      - _location_label     : "제주시 > 한림읍 > 귀덕리" 라벨
#      - _yh_period_label    : "2024-상 ~ 2025-하 (총 4반기 · 2년)" 라벨
#    [메인]
#      - _render_kpi_cards   : 5개 KPI 카드 (산술평균/중앙값/최대/최소/기준 초과)
#      - _render_map         : 마커 지도 + 클릭 → 선택 + selection_bar/detail 호출
#      - _build_color_legend : 6단계 컬러 레전드 (좌하단)
#
#  외부 사용처: tab13_ag_quality.py 내부 전용.
#  순환 회피: _render_map 안에서 _render_well_selection_bar, _render_well_detail
#  를 lazy import (호출 시점에 본체 모듈에서 가져옴).
# ==============================================================================
from __future__ import annotations

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

import config
from src.analysis import ag_well_loader
from src.dashboard import ag_well_helpers, theme
from src.dashboard.ag_map_builders import persist_zoom_center  # G3 fix 2026-05-30
from src.dashboard.map_helpers import make_map
from src.dashboard.tabs._tab13_helpers import (
    _BASE_RADIUS,
    _LEVEL_TO_LOC_COL,
    _QUALITY_PALETTE,
    _bin_index,
    _color_from_score,
    _color_score,
    _fmt_item,
    _fmt_val,
    _radius_from_score,
    _std_label,
    _yh_idx,
    _yh_idx_series,
    _yh_label,
)


@st.cache_data(ttl=600, show_spinner=False, max_entries=8)
def _full_quality_p95(item: str) -> "float | None":
    """시기·지역 필터 무관 P95. 컬러 레전드 boundary 를 절대값으로 고정하기 위함.

    EC 처럼 std 에 max 가 없는 항목에서, 필터를 바꿔도 같은 색 = 같은 농도
    의미가 유지되도록 마스터 전체 데이터의 P95 를 캐시.
    """
    df = ag_well_loader.load_quality_semiannual()
    if df.empty or item not in df.columns:
        return None
    s = df[item].dropna()
    if s.empty:
        return None
    return float(s.quantile(0.95))


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


def _yh_period_label(lo: "tuple[int, str]", hi: "tuple[int, str]") -> str:
    n_half = _yh_idx(*hi) - _yh_idx(*lo) + 1
    n_year = n_half / 2.0
    n_year_label = (f"{int(n_year)}년" if n_year.is_integer()
                    else f"{n_year:.1f}년")
    return f"{lo[0]}-{lo[1]} ~ {hi[0]}-{hi[1]} (총 {n_half}반기 · {n_year_label})"


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
    # 사용자 결정 (2026-05-08): ⑧ 통계 요약 탭의 KPI 카드 스타일로 통일.
    # 기존 인라인 HTML → theme.render_period_kpi_card 헬퍼 호출로 교체.
    # 단일 그룹 카드 (헤더 없음) — title="" 으로 헤더 영역 생략.
    accent_colors = [
        theme.COLOR_TEXT_INFO,           # 1) 산술 평균 — 정보 파랑
        theme.COLOR_TEXT_INFO,           # 2) 중앙값 — 정보 파랑
        theme.PALETTE_ACCENT[4],         # 3) 최대값 — 다크레드 (#C00000)
        theme.PALETTE_ACCENT[3],         # 4) 최소값 — 보조 파랑 (#305496)
        theme.PALETTE_ACCENT[4],         # 5) 기준 초과 — 다크레드
    ]
    for i, (col, (title, big, sub_text)) in enumerate(zip(cols, cards)):
        theme.render_period_kpi_card(
            title="",
            groups=[(title, big, sub_text)],
            accent=accent_colors[i],
            is_base=True,
            container=col,
        )


# ==============================================================================
#  지도 + 관정 클릭 → 상세
# ==============================================================================
def _render_map(
    qf: pd.DataFrame,
    df_master_f: pd.DataFrame,
    item: str,
    all_items: list[str],
) -> None:
    # 본체 함수 lazy import — 순환 import 회피.
    from src.dashboard.tabs.tab13_ag_quality import (
        _render_well_selection_bar,
        _render_well_detail,
    )
    # 2026-05-17: 검색 input 을 지도 헤더 라인으로 옮기는 헬퍼도 lazy import.
    from src.dashboard.tabs._tab13_well_detail import (
        _render_map_header_with_search,
    )
    # _fragment_rerun 도 본체에서 lazy import — _tab13_map 모듈은 ag_well_helpers
    # 만 의존하고 본체 module 의 alias 에 직접 묶이지 않도록 분리 시점 결합 회피.
    _fragment_rerun = ag_well_helpers.fragment_rerun

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

    # max 가 없는 항목(EC 등) — 마스터 전체 P95 를 절대 fallback 기준으로 고정.
    # 시기·지역 필터를 바꿔도 boundary 라벨/색 의미가 일정하게 유지됨.
    fallback_max = None
    if "max" not in std:
        try:
            fallback_max = _full_quality_p95(item)
        except Exception:
            fallback_max = None

    # 사용자 요청 #9: 기준치/마커 안내 보조문구 삭제. 제목만 유지.
    # 2026-05-17 사용자 요청: 검색 input 을 지도 헤더 라인 오른쪽 끝으로 이동.
    # 검색은 414공 전체 master 에서 — qf 가 아닌 active_only=False 마스터 사용.
    _header_html = (
        f'<p class="subsection-title" style="margin:6px 0;">'
        f'관정별 {item_kor} 분포 — 분석기간 내 마지막 측정값</p>'
    )
    df_master_full = ag_well_loader.load_master(active_only=False)
    _render_map_header_with_search(df_master_full, title_html=_header_html)

    sel = st.session_state.get("qty_selected_permit")

    # 2026-05-25: 재중심은 "검색 선택" 에서만(마커 직접 클릭은 이동 안 함) —
    # 선택할 때마다 지도 뷰가 튀던(돌아가던) 현상 제거. _qty_center_request 가
    # 현재 sel 과 일치할 때만 1회 재중심하고 플래그를 소모한다.
    if sel and st.session_state.get("_qty_center_request") == sel:
        st.session_state.pop("_qty_center_request", None)
        st.session_state.pop("_qty_centered_permit", None)  # 강제 재중심 보장
        ag_well_helpers.maybe_recenter_to_selected_well(
            sel, df_master_f,
            fingerprint_key="_qty_centered_permit",
            center_key="qty_map_center",
            zoom_key="qty_map_zoom",
        )

    saved_zoom = st.session_state.get("qty_map_zoom", 11)
    saved_center = st.session_state.get("qty_map_center", (33.42, 126.55))
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
            f'<div style="font-size:16px;line-height:1.5;min-width:160px;">'
            f'<b>{well_id}</b><br>{permit}<br>'
            f'{item_kor}: <b>{_fmt_val(v)} {unit}</b><br>'
            f'시기: {date_text}<br>판정: {verdict}'
            f'<span style="display:none;">{permit}</span>'
            f'</div>'
        )
        # 선택 마커 halo — pointer-events:none (sel-halo) 으로 클릭 가로채기 방지.
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

    # ── 지도 높이 고정 (흰 깜박임/클릭 race 차단):
    # 이전엔 sel 유무에 따라 430/780 토글 → height props 변경 → iframe
    # ResizeObserver → Leaflet click 큐 비움 → 다음 클릭 무반응 + 흰색
    # 깜박임 유발. height 를 고정해 ResizeObserver 트리거를 원천 차단.
    # 사용자는 분석표를 보려면 아래로 스크롤 (tab6/tab7 와 같은 정책).
    map_h = 800  # 사용자 요청 2026-05-09: 화면의 80% 수준
    click = st_folium(
        m, width=None, height=map_h,
        # 사용자 요청 (2026-05-16 v15): zoom/center 제거 — 흰색 깜빡임 차단.
        returned_objects=[
            "last_object_clicked_tooltip",
            "last_object_clicked_popup",
        ],
        key="qty_map",
    )

    if click:
        # G3 fix 2026-05-30: quantization → persist_zoom_center 헬퍼.
        persist_zoom_center(click, zoom_key="qty_map_zoom", center_key="qty_map_center")
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
    # 2026-05-17: 검색 input 은 지도 헤더 라인으로 이동했으므로 본 바는
    # 「선택 관정 표시 + 선택 해제」만 노출.
    df_master_full = ag_well_loader.load_master(active_only=False)
    _render_well_selection_bar(df_master_full, sel, include_search=False)
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
    # 정수 라벨 (요청 #3) — 단, pH 처럼 min/max 둘 다 있는 양쪽 대칭 항목은
    # _color_score 가 |v - mid| / half 로 동작하므로 boundary 도 mid 로부터의
    # 거리(±값)로 표시해야 의미가 맞음.
    if "min" in std and "max" in std:
        half = (std["max"] - std["min"]) / 2.0

        def _fmt(v: float) -> str:
            return f"{v:.2f}".rstrip("0").rstrip(".")

        boundaries = [f"±{_fmt(half * p / 100.0)}" for p in breaks_pct]
    else:
        boundaries = [f"{int(round(ref_max * (p / 100.0)))}" for p in breaks_pct]
    swatches = "".join(
        f'<div style="display:inline-block;width:32px;height:12px;'
        f'background:{c};border:0.5px solid rgba(0,0,0,0.18);"></div>'
        for c in _QUALITY_PALETTE
    )
    pct_labels = (
        '<div style="display:flex;font-size:14px;color:var(--color-text-secondary);'
        'gap:0;width:192px;justify-content:space-between;'
        'margin-top:1px;">'
        f'<span>0</span>'
        f'<span>{boundaries[0]}</span>'
        f'<span>{boundaries[1]}</span>'
        f'<span>{boundaries[2]}</span>'
        f'<span style="color:var(--color-accent-darkred);font-weight:700;">{boundaries[3]}</span>'
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
        font-size: 15px; color: var(--color-text-primary);
    ">
      <div style="font-weight:600;margin-bottom:4px;color:var(--color-text-info);">
        {item_kor} ({unit})
      </div>
      <div style="display:flex;gap:0;width:192px;">{swatches}</div>
      {pct_labels}
    </div>
    """
