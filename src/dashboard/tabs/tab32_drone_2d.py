# ==============================================================================
#  파일명: src/dashboard/tabs/tab32_drone_2d.py
#  모듈: 32.정사영상 분석 탭 (드론영상 그룹)
# ------------------------------------------------------------------------------
#  DJI Terra 산출물 중 2D 정사사진(orthomosaic)을 Folium ImageOverlay 로 표시.
#  미션 선택 → 정사사진 + BBOX + DSM 색상 토글. 시각 확인 전용 (측정 도구 X).
#
#  2026-05-23 tab31_drone_viewer 분할 시 _render_2d_subtab 승격.
#  session_state 키 (tab31_2d_*) 는 호환성 위해 그대로 유지.
# ==============================================================================
from __future__ import annotations

import html
import math

import folium
import streamlit as st
from streamlit_folium import st_folium

import config

from src.dashboard import theme
from src.dashboard.quit_helper import quit_button
from src.drone import (
    MissionNotFound,
    get_or_make_dsm_heatmap,
    load_dsm_meta,
)
from src.drone.preview import get_or_make_preview
from src.drone.measure import polyline_distance, polygon_area_m2

from src.dashboard.tabs._drone_helpers import (
    get_image_provider,
    get_registry,
    get_sampler,
    gsd_cm_str,
    mission_label,
    site_color,
    url_for_dsm_heatmap,
    zoom_for_bbox,
)


# ──────────────────────────────────────────────────────────────────
#  측정 도구 (DJI Terra 식) — 좌표(Coordinate) + 거리(Distance)
#  - session_state 키는 미션별 namespace (tab31_2d_*_{mission_id})
#  - 좌표: 클릭 지점의 X/Y/Z(경도/위도/표고) 를 마커 툴팁으로 표시
#  - 거리: 시작점 깃발 + 점을 이어 클릭 → 직선거리(straight)를 툴팁에 표시
#    (measure.py 는 수평/수직/경사도 제공하나 UI 는 직선거리만 우선 노출)
#  - 표고(Z)·3D 직선거리는 DSM(DsmSampler) 이 있는 미션에서만 정확
# ──────────────────────────────────────────────────────────────────

def _xyz_html(lon: float, lat: float, height) -> str:
    """지도 마커 툴팁용 — X/Y/Z 만 간단히."""
    h_str = f"{height:.2f} m" if isinstance(height, (int, float)) else "—"
    return (
        f"<b>X</b> {lon:.6f}<br>"
        f"<b>Y</b> {lat:.6f}<br>"
        f"<b>Z</b> {h_str}"
    )


def _click_fp(clicked: dict | None) -> str:
    """last_clicked dict → 중복 처리 방지용 fingerprint."""
    if not clicked:
        return ""
    return f"{round(clicked.get('lat', 0), 7)},{round(clicked.get('lng', 0), 7)}"


# 거리·면적 외곽선 — 노랑. 정사영상 위에서 빨간선이 잘 안 보이는 문제 해소(시인성↑).
# 시작점 삼각형 색과 동일 톤(#FFD400). 두께는 거리 4, 면적 외곽 3 으로 굵게.
_LINE_YELLOW = "#FFD400"


# 거리 측정 시작점 마커 — 삼각형(검정 외곽선 + 노랑 내부). 이모지 깃발 대비 2단계
# 크게(30px) + 색상 고정으로 시인성↑. 끝(아래 꼭짓점)이 클릭 지점을 가리킴.
_START_TRI_SVG = (
    "<svg width='30' height='30' viewBox='0 0 30 30'>"
    "<polygon points='15,28 3,5 27,5' fill='#FFD400' stroke='#111111' "
    "stroke-width='2.5' stroke-linejoin='round'/></svg>"
)


def _render_coord_actions(sel_id: str, coords_key: str, pending_key: str) -> None:
    """좌표 편집 중(pending) 액션 — 측정 도구바 안에 한 줄로 배치 (이름/저장/취소).

    좌표값(X/Y/Z)은 지도 마커 툴팁에 이미 표시되므로 여기선 컨트롤만 둔다.
    """
    pending = st.session_state.get(pending_key)
    if not pending:
        return
    saved = st.session_state.get(coords_key, [])
    cn, cs, cc = st.columns([2.4, 1, 1])
    with cn:
        name = st.text_input(
            "이름", value="", key=f"tab31_2d_coordname_{sel_id}",
            placeholder=f"좌표 {len(saved) + 1}", label_visibility="collapsed",
        )
    with cs:
        if st.button("저장", key=f"tab31_2d_coordsave_{sel_id}",
                     type="primary", use_container_width=True):
            saved = list(saved)
            saved.append({
                "name": (name.strip() or f"좌표 {len(saved) + 1}"),
                "lat": pending["lat"], "lon": pending["lon"],
                "height": pending.get("height"),
            })
            st.session_state[coords_key] = saved
            st.session_state.pop(pending_key, None)
            st.session_state.pop(f"tab31_2d_clickfp_{sel_id}", None)
            st.rerun(scope="fragment")
    with cc:
        if st.button("취소", key=f"tab31_2d_coordcancel_{sel_id}",
                     use_container_width=True):
            st.session_state.pop(pending_key, None)
            st.session_state.pop(f"tab31_2d_clickfp_{sel_id}", None)
            st.rerun(scope="fragment")


def _render_coord_saved(sel_id: str, coords_key: str) -> None:
    """저장된 좌표 목록 (지도 하단)."""
    saved = st.session_state.get(coords_key, [])
    if not saved:
        return
    with st.expander(f"📍 저장된 좌표 {len(saved)}개", expanded=False):
        for i, cdt in enumerate(saved):
            h = cdt.get("height")
            h_str = f"{h:.3f} m" if isinstance(h, (int, float)) else "—"
            rcol, dcol = st.columns([6, 1])
            with rcol:
                st.markdown(
                    f"**{html.escape(cdt['name'])}** · "
                    f"Lon {cdt['lon']:.7f} · Lat {cdt['lat']:.7f} · Height {h_str}"
                )
            with dcol:
                if st.button("삭제", key=f"tab31_2d_coorddel_{sel_id}_{i}",
                             use_container_width=True):
                    st.session_state[coords_key] = [
                        c for j, c in enumerate(saved) if j != i
                    ]
                    st.rerun(scope="fragment")


def _render_dist_actions(sel_id: str, dist_key: str, saved_key: str) -> None:
    """거리 측정 액션 — 측정 도구바 안에 한 줄로 배치 (이름/저장/점취소/초기화).

    직선거리 값은 지도 폴리라인 툴팁에 표시되므로 여기선 컨트롤만 둔다.
    """
    pts = st.session_state.get(dist_key, [])
    saved = st.session_state.get(saved_key, [])

    if len(pts) >= 2:
        res = polyline_distance(
            [(p["lat"], p["lon"], p.get("height")) for p in pts]
        )
        cn, cs, cu, cc = st.columns([2.2, 1, 1, 1])
        with cn:
            name = st.text_input(
                "이름", value="", key=f"tab31_2d_distname_{sel_id}",
                placeholder=f"거리 {len(saved) + 1}", label_visibility="collapsed",
            )
        with cs:
            if st.button("저장", key=f"tab31_2d_distsave_{sel_id}",
                         type="primary", use_container_width=True):
                saved = list(saved)
                saved.append({
                    "name": (name.strip() or f"거리 {len(saved) + 1}"),
                    "pts": list(pts), "straight_m": res.straight_m,
                })
                st.session_state[saved_key] = saved
                st.session_state[dist_key] = []
                st.session_state.pop(f"tab31_2d_clickfp_{sel_id}", None)
                st.rerun(scope="fragment")
        with cu:
            if st.button("점 취소", key=f"tab31_2d_distundo_{sel_id}",
                         use_container_width=True):
                st.session_state[dist_key] = list(pts)[:-1]
                st.session_state.pop(f"tab31_2d_clickfp_{sel_id}", None)
                st.rerun(scope="fragment")
        with cc:
            if st.button("초기화", key=f"tab31_2d_distclear_{sel_id}",
                         use_container_width=True):
                st.session_state[dist_key] = []
                st.session_state.pop(f"tab31_2d_clickfp_{sel_id}", None)
                st.rerun(scope="fragment")
    elif len(pts) == 1:
        _sp, cc = st.columns([3, 1])
        with cc:
            if st.button("초기화", key=f"tab31_2d_distclear1_{sel_id}",
                         use_container_width=True):
                st.session_state[dist_key] = []
                st.session_state.pop(f"tab31_2d_clickfp_{sel_id}", None)
                st.rerun(scope="fragment")


def _render_dist_saved(sel_id: str, saved_key: str) -> None:
    """저장된 거리 목록 (지도 하단)."""
    saved = st.session_state.get(saved_key, [])
    if not saved:
        return
    with st.expander(f"📏 저장된 거리 {len(saved)}개", expanded=False):
        for i, d in enumerate(saved):
            rcol, dcol = st.columns([6, 1])
            with rcol:
                st.markdown(
                    f"**{html.escape(d['name'])}** · 직선 {d['straight_m']:.2f} m "
                    f"· 점 {len(d['pts'])}개"
                )
            with dcol:
                if st.button("삭제", key=f"tab31_2d_distdel_{sel_id}_{i}",
                             use_container_width=True):
                    st.session_state[saved_key] = [
                        c for j, c in enumerate(saved) if j != i
                    ]
                    st.rerun(scope="fragment")


def _render_area_actions(sel_id: str, area_key: str, saved_key: str) -> None:
    """면적 측정 액션 — 측정 도구바 안에 한 줄로 (이름/저장/점취소/초기화).

    투영 면적(m²)은 지도 폴리곤 툴팁에 표시되므로 여기선 컨트롤만 둔다.
    """
    pts = st.session_state.get(area_key, [])
    saved = st.session_state.get(saved_key, [])
    if len(pts) >= 3:
        area = polygon_area_m2([(p["lat"], p["lon"]) for p in pts])
        cn, cs, cu, cc = st.columns([2.2, 1, 1, 1])
        with cn:
            name = st.text_input(
                "이름", value="", key=f"tab31_2d_areaname_{sel_id}",
                placeholder=f"면적 {len(saved) + 1}", label_visibility="collapsed",
            )
        with cs:
            if st.button("저장", key=f"tab31_2d_areasave_{sel_id}",
                         type="primary", use_container_width=True):
                saved = list(saved)
                saved.append({
                    "name": (name.strip() or f"면적 {len(saved) + 1}"),
                    "pts": list(pts), "area_m2": area,
                })
                st.session_state[saved_key] = saved
                st.session_state[area_key] = []
                st.session_state.pop(f"tab31_2d_clickfp_{sel_id}", None)
                st.rerun(scope="fragment")
        with cu:
            if st.button("점 취소", key=f"tab31_2d_areaundo_{sel_id}",
                         use_container_width=True):
                st.session_state[area_key] = list(pts)[:-1]
                st.session_state.pop(f"tab31_2d_clickfp_{sel_id}", None)
                st.rerun(scope="fragment")
        with cc:
            if st.button("초기화", key=f"tab31_2d_areaclear_{sel_id}",
                         use_container_width=True):
                st.session_state[area_key] = []
                st.session_state.pop(f"tab31_2d_clickfp_{sel_id}", None)
                st.rerun(scope="fragment")
    elif len(pts) >= 1:
        _sp, cc = st.columns([3, 1])
        with cc:
            if st.button("초기화", key=f"tab31_2d_areaclear1_{sel_id}",
                         use_container_width=True):
                st.session_state[area_key] = []
                st.session_state.pop(f"tab31_2d_clickfp_{sel_id}", None)
                st.rerun(scope="fragment")


def _render_area_saved(sel_id: str, saved_key: str) -> None:
    """저장된 면적 목록 (지도 하단)."""
    saved = st.session_state.get(saved_key, [])
    if not saved:
        return
    with st.expander(f"▱ 저장된 면적 {len(saved)}개", expanded=False):
        for i, d in enumerate(saved):
            rcol, dcol = st.columns([6, 1])
            with rcol:
                st.markdown(
                    f"**{html.escape(d['name'])}** · 투영면적 {d['area_m2']:.2f} m² "
                    f"· 점 {len(d['pts'])}개"
                )
            with dcol:
                if st.button("삭제", key=f"tab31_2d_areadel_{sel_id}_{i}",
                             use_container_width=True):
                    st.session_state[saved_key] = [
                        c for j, c in enumerate(saved) if j != i
                    ]
                    st.rerun(scope="fragment")


@st.fragment
def render() -> None:
    # 2026-05-23: selectbox/slider/checkbox 변경 시 페이지 전체 rerun 으로 인해
    # st.tabs 가 idx 0 으로 리셋되는 문제를 fragment-scoped rerun 으로 차단.
    # 메모리 [[project-fragment-pattern]] — render() 만 @st.fragment, nested 금지.
    # (2026-06-11 v2) 탭 제목 제거 — 하위탭 pill 문구와 중복 (사용자 요청)

    reg = get_registry()
    if len(reg) == 0:
        st.warning(
            "등록된 드론 미션이 없습니다. "
            f"`{reg.registry_file}` 파일과 `data_drone/` 폴더 구성을 확인해 주세요."
        )
        return

    options = {mission_label(m): m.id for m in reg if m.has("tiles_2d")}
    if not options:
        st.info("2D 정사사진이 있는 미션이 없습니다. registry.json 의 tiles_2d.available 을 확인하세요.")
        return

    col_sel, col_opacity, col_dsm = st.columns([3, 1, 1])
    with col_sel:
        sel_label = st.selectbox("미션 선택", list(options.keys()), key="tab31_2d_sel")
    with col_opacity:
        opacity = st.slider("정사사진 투명도", 0.3, 1.0, 0.9, 0.05, key="tab31_2d_opacity")
    sel_id = options[sel_label]

    try:
        m = reg.get(sel_id)
    except MissionNotFound:
        st.error(f"미션을 찾을 수 없습니다: {sel_id}")
        return

    has_dsm = m.has("dsm")
    abs_z_trusted = m.z_trusted and has_dsm

    with col_dsm:
        if has_dsm:
            dsm_overlay_on = st.checkbox(
                "표고 색상",
                value=False,
                key="tab31_2d_dsm_overlay",
                help="DSM 을 viridis 색상으로 표시. 미션 내 표고 분포는 cm 정확.",
            )
        else:
            dsm_overlay_on = False
            st.caption("📡 DSM 없음")

    # ── 측정 도구바 (DJI Terra 식) — 측정 메뉴 + 해당 도구 액션을 한 줄에 통합 ──
    #   [측정] [좌표] [거리] [해제] | (모드별 액션: 이름/저장/취소·점취소·초기화)
    mode_key = f"tab31_2d_measure_mode_{sel_id}"   # 미션별 — 미션 전환 시 모드 누수 방지
    coords_key = f"tab31_2d_coords_{sel_id}"
    pending_key = f"tab31_2d_pending_{sel_id}"
    dist_key = f"tab31_2d_distpts_{sel_id}"
    saved_dist_key = f"tab31_2d_dists_{sel_id}"
    area_key = f"tab31_2d_areapts_{sel_id}"
    saved_area_key = f"tab31_2d_areas_{sel_id}"
    fp_key = f"tab31_2d_clickfp_{sel_id}"

    def _reset_inprogress() -> None:
        # 진행 중 측정(편집 좌표·거리/면적 점열·클릭지문) 초기화.
        st.session_state.pop(pending_key, None)
        st.session_state[dist_key] = []
        st.session_state[area_key] = []
        st.session_state.pop(fp_key, None)

    # 시각 정리(A): 라벨/버튼을 콤팩트하게, 액션 영역은 넉넉히. 아이콘+짧은 라벨.
    mode = st.session_state.get(mode_key)   # None | "coord" | "dist" | "area"
    lbl, bt1, bt2, bt3, bt4, act = st.columns([0.5, 0.95, 0.95, 0.95, 0.95, 5.7])
    with lbl:
        st.markdown(
            f"<div style='padding-top:7px;font-weight:700;font-size:13px;"
            f"color:{theme.COLOR_TEXT_SECONDARY};'>측정</div>",
            unsafe_allow_html=True,
        )
    with bt1:
        if st.button("🎯 좌표", key="tab31_2d_btn_coord",
                     type=("primary" if mode == "coord" else "secondary"),
                     use_container_width=True):
            st.session_state[mode_key] = None if mode == "coord" else "coord"
            _reset_inprogress()
            st.rerun(scope="fragment")
    with bt2:
        if st.button("📏 거리", key="tab31_2d_btn_dist",
                     type=("primary" if mode == "dist" else "secondary"),
                     use_container_width=True):
            st.session_state[mode_key] = None if mode == "dist" else "dist"
            _reset_inprogress()
            st.rerun(scope="fragment")
    with bt3:
        if st.button("▱ 면적", key="tab31_2d_btn_area",
                     type=("primary" if mode == "area" else "secondary"),
                     use_container_width=True):
            st.session_state[mode_key] = None if mode == "area" else "area"
            _reset_inprogress()
            st.rerun(scope="fragment")
    with bt4:
        if st.button("✖ 해제", key="tab31_2d_btn_clear",
                     use_container_width=True, disabled=(mode is None)):
            st.session_state[mode_key] = None
            _reset_inprogress()
            st.rerun(scope="fragment")
    with act:
        if mode == "coord":
            _render_coord_actions(sel_id, coords_key, pending_key)
        elif mode == "dist":
            _render_dist_actions(sel_id, dist_key, saved_dist_key)
        elif mode == "area":
            _render_area_actions(sel_id, area_key, saved_area_key)

    # ── 캡션: 항상 1줄로 렌더(높이 고정) — 클릭 Y-오프셋 방지(레이아웃 시프트 차단).
    #   측정값은 지도 마커/폴리곤 툴팁에 표시.
    mode = st.session_state.get(mode_key)
    if mode == "coord":
        cap = "🎯 지도를 클릭하면 그 지점의 X·Y·Z(경도·위도·표고)가 지도 툴팁에 표시됩니다."
    elif mode == "dist":
        cap = "📏 시작점 클릭→삼각형, 이어 클릭하면 직선거리가 지도 툴팁에 표시됩니다."
    elif mode == "area":
        cap = "▱ 세 점 이상 클릭하면 폴리곤의 투영 면적(m²)이 지도 툴팁에 표시됩니다."
    else:
        cap = "ℹ️ '🎯 좌표' · '📏 거리' · '▱ 면적' 중 하나를 선택한 뒤 지도를 클릭하세요."
    st.caption(cap)

    bbox = m.bbox_wgs84
    if bbox is None:
        st.error("미션 BBOX 정보가 없습니다 (meta.json 의 geo.bbox_wgs84 확인).")
        return
    center = m.center_wgs84
    if center is None:
        st.error("미션 중심 좌표 정보가 없습니다 (meta.json 의 geo.center_wgs84 확인).")
        return

    # [공개판 V1.2.6 패턴] repo 동봉 preview.png 우선 사용 — Cloud 에는
    # 원본 result.tif 가 없어 get_or_make_preview 재생성이 불가능하다.
    from src.drone.preview import preview_path as _preview_path
    preview_p = _preview_path(m)
    if not preview_p.exists():
        with st.spinner("정사사진 미리보기 준비 중…"):
            preview_p = get_or_make_preview(m)   # fallback (로컬 dev)
    if preview_p is None or not preview_p.exists():
        st.warning(f"정사사진 미리보기를 찾을 수 없습니다: {m.output_path('tiles_2d')}")
        return

    # DSM 메타는 popup 의 표고 범위 표시용으로 항상 lazy load (DSM 있을 때만).
    dsm_meta = load_dsm_meta(m) if has_dsm else None
    if dsm_overlay_on and has_dsm:
        with st.spinner("DSM 색상 매핑 생성 중… (첫 회만 ~10초)"):
            heat_p = get_or_make_dsm_heatmap(m)
        if heat_p is None:
            st.warning("DSM 색상 매핑 생성 실패.")
            dsm_overlay_on = False

    # V-World 로컬 캐시 (zoom 8~14) + 인터넷 연결 시 V-World API 다이렉트 (zoom 15+).
    # 11/12/13 탭의 map_helpers.make_map() 과 동일한 V-World 패턴 + 정사영상용 HD 추가.
    # ── 줌·이동·클릭 안정화 (streamlit-folium 권장 패턴, 2026-05-26 재작성) ──
    #   문제: 측정 모드에서 center/zoom 을 returned_objects 로 회수하면 pan/zoom 마다
    #   rerun 이 일어나 클릭이 묻히고, 측정 마커를 folium.Map 에 직접 add 하면 매 클릭
    #   지도 HTML(논리내용)이 바뀌어 iframe 이 재렌더→클릭 큐가 비워졌다("측정이 거의
    #   안 됨"). 해결: ① base 지도(타일·정사영상·BBOX)는 정적으로 두고 ② 측정 마커는
    #   FeatureGroup 으로 분리해 feature_group_to_add 로 in-place 갱신 ③ returned_objects
    #   는 ["last_clicked"] 만 (pan/zoom rerun 0) ④ 클릭은 on_change 콜백에서 읽어
    #   stale(1-rerun 지연) 문제 회피. base 지도가 재로드되지 않으므로 사용자의 pan/zoom
    #   이 그대로 보존된다(별도 view 저장 불필요).
    initial_zoom = zoom_for_bbox(bbox)
    fmap = folium.Map(
        location=[center[0], center[1]],
        zoom_start=initial_zoom,
        tiles=None,
        control_scale=True,
        prefer_canvas=True,
        max_zoom=25,   # Build 1.4 (2026-06-03): 22->25 1단 추가 줌
    )
    local_attr = "ⓒ V-World (로컬 캐시)"
    folium.TileLayer(
        tiles="/app/static/map_tiles/Base/{z}/{x}/{y}.png",
        attr=local_attr, name="V-World 일반", overlay=False, control=True,
        min_zoom=8, max_zoom=25, min_native_zoom=10, max_native_zoom=14,
        show=True,
    ).add_to(fmap)
    folium.TileLayer(
        tiles="/app/static/map_tiles/Satellite/{z}/{x}/{y}.jpeg",
        attr=local_attr, name="V-World 위성", overlay=False, control=True,
        min_zoom=8, max_zoom=25, min_native_zoom=10, max_native_zoom=14,
        show=False,
    ).add_to(fmap)
    # 인터넷 연결 시 V-World API 다이렉트 — zoom 15~19 에서 자세히 (overlay 로 자동 활성).
    # 정사영상은 zoom 17~19 영역에서 사용되므로 캐시 외 zoom 에서 V-World HD 가 자동 표시.
    api_key = (config.VWORLD_API_KEY or "").strip()
    if api_key:
        folium.TileLayer(
            tiles=f"https://api.vworld.kr/req/wmts/1.0.0/{api_key}/Base/{{z}}/{{y}}/{{x}}.png",
            attr="ⓒ V-World", name="V-World 일반 HD (zoom 15+)",
            overlay=True, control=True,
            min_zoom=15, max_zoom=19, show=True,
        ).add_to(fmap)
        folium.TileLayer(
            tiles=f"https://api.vworld.kr/req/wmts/1.0.0/{api_key}/Satellite/{{z}}/{{y}}/{{x}}.jpeg",
            attr="ⓒ V-World", name="V-World 위성 HD (zoom 15+)",
            overlay=True, control=True,
            min_zoom=15, max_zoom=19, show=False,
        ).add_to(fmap)

    provider = get_image_provider()
    provider.add_layer(
        sel_id, fmap,
        name=f"드론 정사사진 — {m.name}",
        opacity=opacity, show=True,
    )

    # ⚠️ ImageOverlay/Rectangle 의 bbox 정확성은 측정 도구의 거리값 정확성에
    #    직결됨 (2026-05-29 회귀 fix 참조).
    #    bbox 는 m.bbox_wgs84 = meta.json.geo.bbox_wgs84 를 그대로 사용하며,
    #    그 값은 src/drone/importer.py 의 result.tif rasterio 추출에서 옴.
    #    bbox 가 result.tif georeferencing 과 다르면 ImageOverlay 가
    #    이미지를 잘못된 영역에 stretch → 픽셀↔위경도 변환 왜곡 →
    #    measure._distance_haversine 의 거리값이 비율만큼 잘못 표시됨.
    #    데이터 관리 탭 Section F 의 "메타 bbox 정합성 검사" 로 언제든 확인.
    if dsm_overlay_on and has_dsm:
        lon_min, lat_min, lon_max, lat_max = bbox
        folium.raster_layers.ImageOverlay(
            image=url_for_dsm_heatmap(m),
            bounds=[[lat_min, lon_min], [lat_max, lon_max]],
            name="표고 색상 (DSM viridis)",
            opacity=0.7, interactive=False, zindex=410, show=True,
        ).add_to(fmap)

    # 미션 영역(BBOX) 외곽선만 표시 — popup 없음. 모든 모드에서 큰 정보 툴팁이
    # 측정·열람을 방해하지 않도록 제거(미션 상세는 하단 통계 카드에 표시됨).
    folium.Rectangle(
        bounds=[[bbox[1], bbox[0]], [bbox[3], bbox[2]]],
        color=site_color(m.site_type), weight=2, fill=False,
    ).add_to(fmap)

    folium.LayerControl(collapsed=True).add_to(fmap)
    # fit_bounds 호출은 streamlit_folium 첫 렌더에서 zoom_start 를 무시하고
    # zoom 1 로 fallback 시키는 버그가 있어 제거.

    # ── 측정 마커는 별도 FeatureGroup 에 담아 feature_group_to_add 로 in-place 갱신 ──
    #   base 지도(fmap)는 정적 → 재로드 없음 → 클릭 큐 보존 + 사용자 pan/zoom 유지.
    saved_coords = st.session_state.get(coords_key, [])
    pending = st.session_state.get(pending_key)
    dist_pts = st.session_state.get(dist_key, [])
    fg = folium.FeatureGroup(name="측정")

    # 저장된 좌표 (이름 + X/Y/Z hover 툴팁)
    for i, cdt in enumerate(saved_coords, 1):
        folium.CircleMarker(
            location=[cdt["lat"], cdt["lon"]],
            radius=6, color=theme.COLOR_ACCENT_NAVY, weight=2,
            fill=True, fill_color="#ffffff", fill_opacity=1.0,
            tooltip=folium.Tooltip(
                f"<b>{html.escape(cdt.get('name') or f'좌표 {i}')}</b><br>"
                + _xyz_html(cdt["lon"], cdt["lat"], cdt.get("height"))
            ),
        ).add_to(fg)
    # 편집 중 좌표 — permanent 툴팁으로 클릭 즉시 X/Y/Z 를 지도에 표시.
    if pending and mode == "coord":
        folium.CircleMarker(
            location=[pending["lat"], pending["lon"]],
            radius=7, color=theme.COLOR_DANGER, weight=2,
            fill=True, fill_color=theme.COLOR_DANGER, fill_opacity=0.9,
            tooltip=folium.Tooltip(
                _xyz_html(pending["lon"], pending["lat"], pending.get("height")),
                permanent=True, direction="top",
            ),
        ).add_to(fg)
    # 거리 측정: 시작점 삼각형 + 점 + 폴리라인. 직선거리를 마지막 점 툴팁에 표시.
    if mode == "dist" and dist_pts:
        n = len(dist_pts)
        straight_label = None
        if n >= 2:
            pts_t = [(p["lat"], p["lon"], p.get("height")) for p in dist_pts]
            straight_label = f"{polyline_distance(pts_t).straight_m:.2f} m"
        for j, p in enumerate(dist_pts):
            if j == 0:
                folium.Marker(
                    location=[p["lat"], p["lon"]],
                    icon=folium.DivIcon(
                        html=_START_TRI_SVG,
                        icon_size=(30, 30), icon_anchor=(15, 28),
                    ),
                    tooltip="시작점",
                ).add_to(fg)
            else:
                is_last = (j == n - 1)
                tip = (folium.Tooltip(straight_label, permanent=True, direction="right")
                       if (is_last and straight_label) else None)
                folium.CircleMarker(
                    location=[p["lat"], p["lon"]],
                    radius=5, color=theme.COLOR_DANGER, weight=2,
                    fill=True, fill_color="#ffffff", fill_opacity=1.0,
                    tooltip=tip,
                ).add_to(fg)
        if n >= 2:
            folium.PolyLine(
                [[p["lat"], p["lon"]] for p in dist_pts],
                color=_LINE_YELLOW, weight=4, opacity=1.0,
            ).add_to(fg)
    # 면적 측정: 점 + 폴리곤. 투영면적(m²)을 폴리곤 중심 permanent 툴팁에 표시.
    area_pts = st.session_state.get(area_key, [])
    if mode == "area" and area_pts:
        locs = [[p["lat"], p["lon"]] for p in area_pts]
        for p in area_pts:
            folium.CircleMarker(
                location=[p["lat"], p["lon"]],
                radius=5, color=theme.COLOR_DANGER, weight=2,
                fill=True, fill_color="#ffffff", fill_opacity=1.0,
            ).add_to(fg)
        if len(area_pts) == 2:   # 2점 = 선분만(3점↑은 Polygon 자체 외곽선 사용 → 이중 렌더 방지)
            folium.PolyLine(locs, color=_LINE_YELLOW, weight=4, opacity=1.0).add_to(fg)
        if len(area_pts) >= 3:
            a_m2 = polygon_area_m2([(p["lat"], p["lon"]) for p in area_pts])
            folium.Polygon(
                locations=locs, color=_LINE_YELLOW, weight=4,
                fill=True, fill_color=theme.COLOR_DANGER, fill_opacity=0.15,
                tooltip=folium.Tooltip(f"{a_m2:.2f} m²", permanent=True),
            ).add_to(fg)

    # ── 클릭 처리 콜백 (on_change) — stale(1-rerun 지연) 회피 ──
    # 측정 모드에서 지도 빈 곳 클릭 → last_clicked 변경 → 콜백에서 DSM 표고 샘플 후
    # 좌표(pending)/거리(점 누적)에 반영. returned_objects 가 ["last_clicked"] 뿐이라
    # pan/zoom 은 rerun 을 일으키지 않는다(클릭만 등록).
    map_key = f"tab31_2d_map_{sel_id}"

    def _on_map_click() -> None:
        state = st.session_state.get(map_key)
        if not state:
            return
        lc = state.get("last_clicked")
        if not lc:
            return
        cur_mode = st.session_state.get(mode_key)
        if cur_mode not in ("coord", "dist", "area"):
            return
        fp = _click_fp(lc)
        if not fp or fp == st.session_state.get(fp_key):
            return
        lat, lon = lc.get("lat"), lc.get("lng")
        if lat is None or lon is None:
            return
        st.session_state[fp_key] = fp
        # 표고(Z)는 좌표·거리에서만 필요. 면적은 수평 투영이라 DSM 샘플 생략(빠름).
        height = None
        if cur_mode in ("coord", "dist") and has_dsm:
            sampler = get_sampler(sel_id)
            if sampler is not None:
                r = sampler.sample(lat, lon)
                if r is not None:
                    height = r.el_m
        pt = {"lat": lat, "lon": lon, "height": height}
        if cur_mode == "coord":
            st.session_state[pending_key] = pt
        elif cur_mode == "dist":   # 점 누적 (항상 최신 session_state 기준)
            st.session_state[dist_key] = st.session_state.get(dist_key, []) + [pt]
        else:   # area — 점 누적
            st.session_state[area_key] = st.session_state.get(area_key, []) + [pt]

    # ★ height 는 뷰포트 안에 들어오는 값으로 — 1080px(뷰포트보다 큼)이면 클릭→재렌더
    #   시 브라우저가 큰 컴포넌트를 보이려 페이지를 자동 스크롤하고, 그 스크롤량만큼
    #   Leaflet 좌표 기준이 어긋나 클릭이 아래로 찍혔다. 700px 로 줄여 자동 스크롤 차단.
    st_folium(
        fmap, height=700, width=None,
        feature_group_to_add=fg,
        returned_objects=["last_clicked"],
        key=map_key,
        on_change=_on_map_click,
    )

    # ── 저장 목록 (지도 하단) — 진행 중 액션은 상단 도구바로 이동함 ──
    _render_coord_saved(sel_id, coords_key)
    _render_dist_saved(sel_id, saved_dist_key)
    _render_area_saved(sel_id, saved_area_key)

    survey = m.meta.get("survey_info") or {}
    cols = st.columns(4)
    theme.render_stat_card(
        "🎯 정확도",
        f"{survey.get('rtk_mode','—')}",
        f"RMSE {survey.get('rmse_m','—')} m · "
        + ("절대 cm" if abs_z_trusted else "절대 ±1m") + " / "
        + ("상대 cm" if has_dsm else "상대 없음"),
        color=(theme.COLOR_SUCCESS if abs_z_trusted else site_color(m.site_type)),
        container=cols[0],
    )
    theme.render_stat_card(
        "📷 촬영", f"{survey.get('image_count','—')}장",
        f"{survey.get('camera','—')} · {m.flight_date}",
        container=cols[1],
    )
    theme.render_stat_card(
        "📐 해상도", f"{gsd_cm_str(m,'result_tif')} cm",
        f"DSM {gsd_cm_str(m,'dsm_tif')} cm · GSD",
        container=cols[2],
    )
    theme.render_stat_card(
        "🗺️ 영역",
        f"{(bbox[2]-bbox[0])*111000*math.cos(math.radians(center[0])):.0f} × "
        f"{(bbox[3]-bbox[1])*111000:.0f} m",
        f"중심 {center[0]:.5f}, {center[1]:.5f}",
        container=cols[3],
    )
