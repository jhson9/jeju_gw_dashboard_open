# ==============================================================================
#  파일명: src/dashboard/tabs/tab31_drone_overview.py
#  모듈: 31.드론영상 현황 탭 (드론영상 그룹 첫 탭)
# ------------------------------------------------------------------------------
#  제주도 전체 지도 + 등록된 드론 미션 마커 + 미션 정보 테이블.
#  사용자 요청 (2026-05-23):
#    "31번은 전체 제주도 지도를 보여주고, 어떤 정보를 현재 가지고 있는지 표시만 해주면 좋겠어.
#     향후 드론 영상이 많아지면 이것들을다 보여줄수 있을 것 같아."
#
#  마커 클릭 → 32(정사) / 33(3D) 직접 이동 기능은 향후 추가 예정 (placeholder 단계).
# ==============================================================================
from __future__ import annotations

import html as _html_mod
import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from src.dashboard import theme
from src.dashboard.quit_helper import quit_button

from src.dashboard.tabs._drone_helpers import (
    get_registry,
    gsd_cm_str,
    site_color,
)


@st.fragment
def render() -> None:
    # 2026-05-23: 입력 위젯 변경 시 페이지 전체 rerun 으로 인해 st.tabs idx 0
    # 리셋되는 문제를 fragment-scoped rerun 으로 차단. 드론 그룹 4개 탭 모두 동일.
    # 메모리 [[project-fragment-pattern]] — render() 만 @st.fragment, nested 금지.
    _t, _q = st.columns([10, 1])
    with _t:
        st.markdown(
            '<p class="tab-title" style="margin:0;">31.드론영상 현황</p>',
            unsafe_allow_html=True,
        )
    with _q:
        quit_button("quit_in_tab31")

    st.caption(
        "DJI Terra 5.2.0 산출물(정사사진·3D 모델·DSM) 통합 현황. "
        "신규 미션은 `data_drone/registry.json` 에 추가. "
        "개별 미션 상세 분석은 **32.정사영상 분석** / **33.3D영상 분석** 탭에서."
    )

    reg = get_registry()
    if len(reg) == 0:
        st.warning(
            "등록된 드론 미션이 없습니다. "
            f"`{reg.registry_file}` 파일과 `data_drone/` 폴더 구성을 확인해 주세요."
        )
        return

    # ── 상단 메트릭 카드 4개 ────────────────────────────────────
    cols = st.columns(4)
    theme.render_stat_card(
        "총 미션", f"{len(reg)}건",
        "DJI Terra 산출물",
        color=theme.COLOR_TEXT_INFO, container=cols[0],
    )
    theme.render_stat_card(
        "2D 정사사진", f"{reg.count_available('tiles_2d')}건",
        "ImageOverlay 표시",
        color=theme.COLOR_SUCCESS, container=cols[1],
    )
    theme.render_stat_card(
        "3D 모델", f"{reg.count_available('tiles_3d')}건",
        "CesiumJS / 3D Tiles",
        color="#8E24AA", container=cols[2],
    )
    theme.render_stat_card(
        "DSM", f"{reg.count_available('dsm')}건",
        "수치 표면 모델",
        color=theme.COLOR_ACCENT_BLUE_2, container=cols[3],
    )

    st.divider()

    # ── 제주도 전체 지도 + 미션 마커 ────────────────────────────
    st.markdown("**🗺️ 제주도 전체 — 드론 촬영 미션 위치**")

    # 제주도 전체 지도 기본 중심·줌 (registry.json default_center/zoom 과 동일 값)
    fmap = folium.Map(
        location=[33.40, 126.55],
        zoom_start=10,
        tiles="OpenStreetMap",
        control_scale=True,
        prefer_canvas=True,
    )

    for m in reg:
        center = m.center_wgs84
        if center is None:
            continue
        outputs = []
        if m.has("tiles_2d"):
            outputs.append("2D")
        if m.has("tiles_3d"):
            outputs.append("3D")
        if m.has("dsm"):
            outputs.append("DSM")
        outputs_str = " · ".join(outputs) if outputs else "—"

        # P-fix I4 (2026-05-29): 사용자 입력값(m.name, m.eup_myeon_dong 등)은
        # html.escape() 로 HTML 특수문자 escape — popup HTML 에 그대로 합성
        # 시 XSS (`<script>`, `<img onerror>`) 위험. site_type / flight_date /
        # outputs_str 도 안전을 위해 일괄 escape (내부 값이지만 방어적 코딩).
        _esc = _html_mod.escape
        popup_html = (
            f'<div style="font-size:13px;">'
            f'<b>{_esc(m.name)}</b><br>'
            f'유형: {_esc(m.site_type)}<br>'
            f'촬영일: {_esc(m.flight_date)}<br>'
            f'위치: {_esc(m.eup_myeon_dong)}<br>'
            f'산출물: {_esc(outputs_str)}<br>'
            f'<span style="color:#666;">→ 32.정사영상 / 33.3D영상 탭에서 상세 분석</span>'
            f'</div>'
        )

        folium.CircleMarker(
            location=[center[0], center[1]],
            radius=10,
            color=site_color(m.site_type),
            fill=True,
            fill_opacity=0.85,
            weight=2,
            tooltip=f"{m.name} ({m.flight_date}) — {m.site_type}",
            popup=folium.Popup(popup_html, max_width=260),
        ).add_to(fmap)

    st_folium(
        fmap, height=520, width=None,
        returned_objects=[],
        key="tab31_overview_map",
    )

    st.caption(
        "ℹ️ 마커 클릭 시 미션 정보 팝업. 상세 영상은 **32.정사영상 분석** / **33.3D영상 분석** 탭에서. "
        "향후 마커 클릭 시 해당 탭으로 자동 이동 기능 추가 예정."
    )

    st.divider()

    # ── 미션 정보 테이블 ────────────────────────────────────────
    st.markdown("**📋 등록 미션 정보**")
    st.caption(
        "💡 **lon/lat ratio** 컬럼은 `meta.json`의 bbox 가 실제 `result.tif`의 georeferencing 과 "
        "얼마나 일치하는지 보여줍니다. **1.000 이 정상**이며, 0.95~1.05 이면 노란색, "
        "그 밖이면 빨간색으로 경고 표시 — Tab32 측정값이 같은 비율로 왜곡됨을 의미. "
        "데이터 관리 탭의 '메타 bbox 정합성 검사' 로 자동 보정 가능."
    )

    # P5 방어5 (2026-05-29): 메타 정합성 비율을 표에 직접 노출.
    # 회귀 발생 시 Tab31 진입만으로 즉시 시각적 확인 가능.
    # check_mission_bbox 가 rasterio 로 result.tif 를 읽으므로 비용이 있어
    # 안전하게 캐시 (5분 TTL). 미션 폴더 mtime 이 바뀌면 자동 무효화는 안 되니
    # 사용자가 다시 import 한 경우엔 데이터 관리 탭 진단으로 확인 권장.
    # M1 fix 2026-05-30: check_mission_bbox 가 매 fragment_rerun 마다 N개 미션
    # result.tif (90MB~1.1GB) 를 rasterio open → 수백 ms ~ 수 초. _drone_helpers 의
    # cached wrapper(check_mission_bbox_fast) 로 대체. (mtime_ns, size) 시그니처를
    # 캐시 key 에 포함해 importer 로 메타 갱신 시 자동 무효화.
    try:
        from src.dashboard.tabs._drone_helpers import check_mission_bbox_fast
        _ratios = {}
        for m in reg:
            try:
                _rep = check_mission_bbox_fast(m.data_dir)
                _ratios[m.id] = (_rep.lon_span_ratio, _rep.lat_span_ratio, _rep.is_consistent)
            except Exception:
                _ratios[m.id] = (None, None, None)
    except ImportError:
        _ratios = {}

    rows = []
    for m in reg:
        survey = m.meta.get("survey_info") or {}
        lon_r, lat_r, ok = _ratios.get(m.id, (None, None, None))
        rows.append({
            "ID": m.id,
            "이름": m.name,
            "타입": m.site_type,
            "위치": m.eup_myeon_dong,
            "촬영일": m.flight_date,
            "RTK": survey.get("rtk_mode", "—"),
            "이미지 수": survey.get("image_count", "—"),
            "RMSE(m)": survey.get("rmse_m", "—"),
            "정사사진 GSD(cm)": gsd_cm_str(m, "result_tif"),
            "DSM GSD(cm)": gsd_cm_str(m, "dsm_tif"),
            "lon ratio": round(lon_r, 3) if lon_r is not None else None,
            "lat ratio": round(lat_r, 3) if lat_r is not None else None,
            "2D": "✅" if m.has("tiles_2d") else "—",
            "3D": "✅" if m.has("tiles_3d") else "—",
            "DSM": "✅" if m.has("dsm") else "—",
            "PLY": "✅" if m.has("pointcloud_ply") else "—",
        })
    _df = pd.DataFrame(rows)

    # 색상 강조 — Styler 로 lon/lat ratio 컬럼만 음영 처리
    def _ratio_color(v):
        """ratio → background-color CSS. None/1.0 정상, 0.95~1.05 경고, 그 외 위험."""
        if v is None or pd.isna(v):
            return ""
        try:
            d = abs(float(v) - 1.0)
        except (TypeError, ValueError):
            return ""
        if d < 0.01:
            return ""   # 정상: 강조 없음 (1% 이내)
        if d < 0.05:
            return "background-color: #fff4cc; color: #6b5800;"  # 노란색 경고
        return "background-color: #fbe2e2; color: #b91c1c; font-weight: 600;"  # 빨강 위험

    try:
        # FutureWarning fix 2026-05-30: pandas 2.1+ 에서 Styler.applymap deprecated → Styler.map.
        # 양쪽 pandas 버전 호환: hasattr 체크. pandas 2.1 미만이면 applymap 폴백.
        _style = _df.style
        _style_map = getattr(_style, "map", None) or _style.applymap
        _styled = (
            _style_map(_ratio_color, subset=["lon ratio", "lat ratio"])
               .format({"lon ratio": "{:.3f}", "lat ratio": "{:.3f}"},
                       na_rep="—")
        )
        st.dataframe(_styled, use_container_width=True, hide_index=True)
    except Exception:
        # Styler 실패 시 plain DataFrame 폴백
        st.dataframe(_df, use_container_width=True, hide_index=True)

    # 비정상 ratio 미션 즉시 경고 (사용자가 표 스크롤 안 해도 보이게)
    _bad = [m.id for m in reg
            if _ratios.get(m.id, (None, None, True))[2] is False]
    if _bad:
        st.warning(
            f"⚠️ {len(_bad)} 미션의 메타 bbox 가 result.tif 와 불일치 — "
            f"Tab32 측정값 왜곡 위험: **{', '.join(_bad)}**. "
            "데이터 관리 탭 → '🎯 드론 메타 bbox 정합성 검사' 에서 자동 보정 권장."
        )

    with st.expander("자료 경로 (운영자용)"):
        for m in reg:
            st.markdown(f"**{m.name}** — `{m.data_dir}`")
            paths = []
            if m.has("tiles_2d"):
                paths.append(f"- 정사사진: `{m.output_path('tiles_2d')}`")
            if m.has("tiles_3d"):
                paths.append(f"- 3D Tiles: `{m.output_path('tiles_3d')}`")
            if m.has("dsm"):
                paths.append(f"- DSM    : `{m.output_path('dsm')}`")
            st.markdown("\n".join(paths) if paths else "_가용 자료 없음_")

    # ── 재측량 비교 분석 ─────────────────────────────────────────
    comparable_sites = reg.list_comparable_sites()
    if comparable_sites:
        st.divider()
        st.markdown("**🔄 재측량 비교 분석**")
        st.caption(
            "동일 지점을 2회 이상 촬영한 미션을 자동으로 감지해 측량 품질 변화를 비교합니다."
        )

        for site in comparable_sites:
            site_id    = site["site_id"]
            site_name  = site.get("name", site_id)
            missions   = site["missions"]   # flight_date 오름차순 정렬

            with st.expander(f"📍 {site_name}  ({len(missions)}회 촬영)", expanded=True):
                # 비교 테이블 구성
                comp_rows = []
                for m in missions:
                    sv = m.meta.get("survey_info") or {}
                    comp_rows.append({
                        "미션 ID":      m.id,
                        "촬영일":       m.flight_date,
                        "이미지 수":    sv.get("image_count", "—"),
                        "RMSE (m)":    sv.get("rmse_m", "—"),
                        "GSD (cm)":    round(sv.get("gsd_m", 0) * 100, 2)
                                        if sv.get("gsd_m") else "—",
                        "비행고도 (m)": sv.get("flying_altitude_m", "—"),
                        "면적 (km²)":  sv.get("coverage_km2", "—"),
                        "RTK":         sv.get("rtk_mode", "—"),
                        "2D": "✅" if m.has("tiles_2d") else "—",
                        "3D": "✅" if m.has("tiles_3d") else "—",
                        "DSM": "✅" if m.has("dsm") else "—",
                    })

                st.dataframe(
                    pd.DataFrame(comp_rows),
                    use_container_width=True,
                    hide_index=True,
                )

                # 변화량 요약 (2회 촬영인 경우)
                if len(missions) == 2:
                    sv0 = missions[0].meta.get("survey_info") or {}
                    sv1 = missions[1].meta.get("survey_info") or {}

                    def _delta(key: str, fmt: str = "{:+.3f}") -> str:
                        v0 = sv0.get(key)
                        v1 = sv1.get(key)
                        if v0 is None or v1 is None:
                            return "—"
                        try:
                            return fmt.format(float(v1) - float(v0))
                        except (TypeError, ValueError):
                            return "—"

                    d_cols = st.columns(3)  # 9팀 fix: 4번째 메트릭 잘림 안전 복원 → 3컬럼
                    d_cols[0].metric(
                        "RMSE 변화 (m)",
                        _delta("rmse_m"),
                        help="2차 - 1차 RMSE. 음수면 정확도 향상.",
                    )
                    d_cols[1].metric(
                        "GSD 변화 (m)",
                        _delta("gsd_m", "{:+.4f}"),
                        help="2차 - 1차 GSD. 음수면 해상도 향상.",
                    )
                    d_cols[2].metric(
                        "비행고도 변화 (m)",
                        _delta("flying_altitude_m", "{:+.1f}"),
                        help="2차 - 1차 비행고도. 부호 그대로 표시.",
                    )
                    # M1 fix 2026-05-30: 4번째 메트릭은 의도적 미사용 (잘린 부분 안전 복원).
                    # 원본에 다른 지표가 있었다면 backup 에서 재추가 필요.
