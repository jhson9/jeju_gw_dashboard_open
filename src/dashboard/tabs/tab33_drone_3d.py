# ==============================================================================
#  파일명: src/dashboard/tabs/tab33_drone_3d.py
#  모듈: 33.3D영상 분석 탭 (드론영상 그룹)
# ------------------------------------------------------------------------------
#  DJI Terra 산출물 중 3D 모델(3D Tiles)을 CesiumJS 로 표시.
#  미션 선택 → 3D Tileset 로딩. 오프라인 운영을 위해 Cesium 번들 로컬 배치.
#
#  2026-05-23 tab31_drone_viewer 분할 시 _render_3d_subtab 승격.
#  session_state 키 (tab31_3d_*) 는 호환성 위해 그대로 유지.
# ==============================================================================
from __future__ import annotations

import streamlit as st

from src.dashboard import theme
from src.dashboard.quit_helper import quit_button

from src.dashboard.tabs._drone_helpers import (
    CESIUM_BUNDLE_DIR,
    CESIUM_JS,
    get_registry,
    is_cloud_env,
    mission_label,
    render_cloud_unavailable_notice,
    url_for_3d_viewer,
    url_for_tileset,
)


@st.fragment
def render() -> None:
    # 2026-05-23: selectbox 변경 시 페이지 전체 rerun 으로 인해 탭 idx 0 으로
    # 리셋되는 문제를 fragment-scoped rerun 으로 차단. 외부 rerun 안 일으킴.
    # 메모리 [[project-fragment-pattern]] — render() 만 @st.fragment, nested 금지.
    _t, _q = st.columns([10, 1])
    with _t:
        st.markdown(
            '<p class="tab-title" style="margin:0;">33.3D영상 분석</p>',
            unsafe_allow_html=True,
        )
    with _q:
        quit_button("quit_in_tab33")

    # Cloud 환경 가드 — pdf_server :8766 localhost-only (2026-06-02).
    # Streamlit Cloud 에서는 iframe 이 사용자 PC 의 127.0.0.1 을 보러 가
    # "연결을 거부했습니다" 오류 발생 → 안내문으로 대체.
    if is_cloud_env():
        render_cloud_unavailable_notice(
            "33.3D영상 분석",
            missing_feature="Cesium 3D Tiles 뷰어 (b3dm)",
        )
        return

    reg = get_registry()
    if len(reg) == 0:
        st.warning(
            "등록된 드론 미션이 없습니다. "
            f"`{reg.registry_file}` 파일과 `data_drone/` 폴더 구성을 확인해 주세요."
        )
        return

    if not CESIUM_JS.exists():
        st.warning(
            "**CesiumJS 번들이 배치되지 않았습니다.** 오프라인 환경 운영을 위해 "
            "다음 경로에 CesiumJS 풀 번들을 배치해 주세요.\n\n"
            f"`{CESIUM_BUNDLE_DIR}`\n\n"
            "다운로드 (외부망에서 1회):\n"
            "1. https://cesium.com/downloads/ → CesiumJS ZIP 받기\n"
            "2. 압축 풀어 안의 `Build/Cesium/` 폴더 내용을 위 경로로 복사\n"
            "3. 결과: `static/libs/cesium/Cesium.js`, `Workers/`, `Assets/`, `Widgets/`"
        )

    options = {mission_label(m): m.id for m in reg if m.has("tiles_3d")}
    missing_3d = [m for m in reg if not m.has("tiles_3d")]

    if not options:
        st.info("3D 모델이 처리된 미션이 없습니다. DJI Terra 에서 3D 재건을 실행해 주세요.")
        return

    sel_label = st.selectbox("미션 선택", list(options.keys()), key="tab31_3d_sel")
    sel_id = options[sel_label]
    m = reg.get(sel_id)

    tileset_path = reg.get_3dtiles_path(sel_id)
    if not tileset_path or not tileset_path.exists():
        st.error(f"3D Tiles 파일을 찾을 수 없습니다: {tileset_path}")
        return

    tileset_url = url_for_tileset(m)

    if not CESIUM_JS.exists():
        st.caption(f"📦 tileset.json URL: `{tileset_url}` — 번들 배치 후 자동으로 활성화됩니다.")
        return

    center = m.center_wgs84   # (lat, lon)
    mlat, mlon = float(center[0]), float(center[1])
    alt = float((m.meta.get("geo") or {}).get("altitude_m") or 200.0)

    # ❗ 핵심 설계 (2026-05-24, [[project-drone-purpose]]): srcdoc 폐기 → 진짜 iframe src.
    #   뷰어 HTML·Cesium 번들·3D Tiles 가 모두 pdf_server :8766 같은 origin →
    #   Web Worker same-origin → Draco 디코딩 worker 정상 작동.
    #   기존 cesium_html 거대 문자열 + 진단용 코드 (MIME monkey-patch, 미니콘솔,
    #   Worker hook 등) 전체 제거 — 모두 srcdoc 우회용이었으며 srcdoc 폐기로 불필요.
    # mission_id 를 query string 으로 전달 — iframe src 가 미션마다 달라져
    # Streamlit 이 iframe 을 재생성 (hash 만 다르면 reload 안 됨).
    # sse=4 — DJI Terra 권장 정밀 범위 (4~8, 작을수록 정밀·메모리 ↑).
    viewer_url = url_for_3d_viewer(tileset_url, mlat, mlon, sse=4, mission_id=sel_id)
    st.components.v1.iframe(viewer_url, height=1040, scrolling=False)

    st.caption(
        f"🛰️ 3D Tiles URL: `{tileset_url}`  ·  "
        f"중심 {center[0]:.5f}, {center[1]:.5f}  ·  해발 {alt:.0f}m"
    )


    if missing_3d:
        st.markdown(
            f'<div style="margin-top:8px;padding:8px 12px;border-radius:6px;'
            f'background:{theme.COLOR_BG_SECONDARY};border-left:3px solid {theme.COLOR_TEXT_TERTIARY};'
            f'font-size:13px;color:{theme.COLOR_TEXT_SECONDARY};">'
            f'ℹ️ 3D 미처리 미션 {len(missing_3d)}건 — '
            f'{", ".join(mm.name for mm in missing_3d)}. '
            f'DJI Terra 에서 3D 재건을 실행하면 자동으로 활성화됩니다.'
            f'</div>',
            unsafe_allow_html=True,
        )
