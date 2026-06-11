# ==============================================================================
#  파일명: src/dashboard/tabs/tab34_drone_diff_dod.py
#  모듈: 34.시계열 분석(2D) 탭
# ------------------------------------------------------------------------------
#  시계열 비교 + DoD (DEM of Difference) 색상 overlay 통합.
#  이전 tab34 (실험적) 의 안정 검증 후 2026-06-06 tab34 로 승격.
#  원본 tab34 (DoD 없음) 는 _archive/tab34_drone_diff_pre_dod_consolidation.py 에 보관.
#
#  추가 UI:
#    - DoD ON/OFF 토글
#    - DoD 불투명도 슬라이더 (0~100%)
#    - DoD 임계치 슬라이더 (±m) — 작은 변화 회색 마스킹
#    - DoD 통계 카드 (평균 Δz · 양수 부피 m³ · 음수 부피 m³ · net m³)
#    - 색상 범례 (RdBu_r)
#
#  20-에이전트 합의:
#    · 농업기반시설 1팀: 임계치 기본값을 시설물 타입별로 차등 권장
#    · DJI Terra 2팀: 시뮬레이션 모드 (L=R) 에서 Δ=0 데모 표시
#    · DSM/DoD 3팀: 실데이터 없을 때 PNG 없음 → JS 가 자동 비활성 + 안내
#    · Streamlit 5팀: @st.fragment 유지, DoD 토글 state 는 fragment 안 session_state
#    · 회귀 14팀: 원본 tab34/diff_viewer.html 비손상, 신규 파일만 추가
#
#  관련 메모리:
#    [[project-drone-dod-experimental-36-37]]
#    [[project-drone-purpose]] [[project-fragment-pattern]]
# ==============================================================================
from __future__ import annotations

import math
from datetime import date

import pandas as pd
import streamlit as st

import config

from src.dashboard import theme
from src.dashboard.quit_helper import quit_button

from src.dashboard.tabs._drone_helpers import (
    get_registry,
    url_for_diff_viewer_dod,
    diff_viewer_dod_inline_html,
    is_cloud_env,
)
from src.dashboard.tabs._dod_helpers import (
    compute_dod,
    dod_bounds_str,
    dod_feasibility,
    dod_png_path,
    ensure_hillshade,
    format_stats_card_value,
    colormap_legend_html,
    hs_bounds_str,
    lod95_for,
    recommended_threshold_for,
    url_for_dod_png,
    url_for_hs_png,
)


@st.fragment
def render() -> None:
    # (2026-06-11 v2) 탭 제목 제거 — 하위탭 pill 문구와 중복 (사용자 요청)

    st.caption(
        "🧪 **실험적 탭** — tab34 의 사본 + DoD (표고 차분) 색상 overlay. "
        "원본 tab34 는 그대로 유지됩니다. 만족 시 통합 결정."
    )

    reg = get_registry()
    if len(reg) == 0:
        st.warning("등록된 드론 미션이 없습니다.")
        return

    missions_2d = [m for m in reg if m.has("tiles_2d")]
    if not missions_2d:
        st.warning(
            "정사영상(tiles_2d)이 처리된 미션이 없습니다. "
            "DJI Terra 산출물의 result.tif → derived/preview.png 생성 후 활성화됩니다."
        )
        return

    sites: dict[str, list] = {}
    for m in missions_2d:
        sites.setdefault(m.site_id, []).append(m)
    for sid in sites:
        sites[sid].sort(key=lambda m: m.flight_date)

    facility_labels: dict[str, str] = {}
    for sid, ms in sites.items():
        first = ms[0]
        n = len(ms)
        suffix = f" · {n} 시점" if n > 1 else " · 1 시점 (시뮬레이션)"
        facility_labels[sid] = f"{first.name} ({first.site_type}){suffix}"

    # ── 1행 3열: 좌 시점 · 중앙 시설물 · 우 시점 ──
    col_left, col_center, col_right = st.columns([1, 1.2, 1])

    with col_center:
        sel_site_id = st.selectbox(
            "📍 시설물",
            list(facility_labels.keys()),
            format_func=lambda sid: facility_labels[sid],
            key="tab34_site",
        )

    available = sites[sel_site_id]
    time_label = lambda m: m.flight_date
    time_ids = [m.id for m in available]
    id_to_mission = {m.id: m for m in available}

    with col_left:
        sel_left_id = st.selectbox(
            "◀ 좌측 시점",
            time_ids,
            index=0,
            format_func=lambda mid: time_label(id_to_mission[mid]),
            key=f"tab34_left_{sel_site_id}",
        )

    with col_right:
        sel_right_id = st.selectbox(
            "우측 시점 ▶",
            time_ids,
            index=len(time_ids) - 1,
            format_func=lambda mid: time_label(id_to_mission[mid]),
            key=f"tab34_right_{sel_site_id}",
        )

    left = id_to_mission[sel_left_id]
    right = id_to_mission[sel_right_id]

    # ── DoD feasibility + 컨트롤 패널 ──
    feasible, msg, mode = dod_feasibility(left, right)
    # [공개판] DSM 원본(map/dsm.tif) 미동봉 — 실제 파일이 있을 때만 DoD 허용.
    #   (registry 의 available 플래그와 별개로 파일 존재를 이중 확인 —
    #    시뮬레이션 모드(동일 미션)도 DSM 파일이 없으면 계산 불가하므로 차단.)
    def _dsm_file_ok(_m):
        _p = _m.output_path("dsm")
        return bool(_p) and _p.exists()
    if feasible and not (_dsm_file_ok(left) and _dsm_file_ok(right)):
        feasible, msg, mode = False, "공개판 — DSM 원본 미포함 (DoD 계산 비활성)", "unavailable"
    if mode == "simulation":
        st.info(f"💡 **시뮬레이션 모드** — 좌·우 같은 미션, DoD Δ=0 표시. ({msg})")
    elif not feasible:
        st.warning(f"⚠ DoD 비활성: {msg}")

    # 농업기반시설 1팀 권장: 시설물 타입별 임계치 기본값
    rec_th = recommended_threshold_for(left.site_type)
    # 🆕 (2026-06-11 Q1) LoD95 자동 산출 — 권장값보다 크면 기본값으로 (max).
    #   LoD95 미만의 변화는 측량 불확실도 이내라 노이즈일 가능성 높음.
    lod95 = lod95_for(left, right)
    default_th = float(rec_th if lod95 is None else max(rec_th, lod95))
    th_max = max(1.0, math.ceil(default_th * 10.0) / 10.0)
    th_help = f"{left.site_type} 권장 ±{rec_th:.2f} m"
    if lod95 is not None:
        th_help += (f" · LoD95(95% 최소탐지한계) = ±{lod95:.2f} m — "
                    "이보다 작은 변화는 측량 불확실도 이내")

    ctrl_a, ctrl_b, ctrl_c, ctrl_d = st.columns([1, 1, 1.1, 1.1])
    with ctrl_a:
        dod_on = st.toggle(
            "🎨 DoD 표시",
            value=feasible,
            help="OFF 시 정사영상만 표시 (= tab34 와 동일).",
            key=f"tab34_dod_on_{sel_site_id}_{sel_left_id}_{sel_right_id}",
            disabled=not feasible,
        )
        # 🆕 (2026-06-11 Q4) hillshade 토글 — 기본 OFF (기존 화면 유지).
        #   ON 시 after 미션 DSM 음영기복을 DoD 아래(z=423)에 표시.
        _after_m = right if left.flight_date <= right.flight_date else left
        hs_on = st.toggle(
            "⛰️ 음영기복(hillshade)",
            value=False,
            help="after 미션 DSM 기반 음영기복을 DoD 아래에 깔아 지형 맥락 표시. "
                 "최초 ON 시 생성에 수 초 소요 (이후 캐시).",
            key=f"tab34_hs_on_{sel_site_id}",
            disabled=not _after_m.has("dsm"),
        )
    with ctrl_b:
        opacity = st.slider(
            "🌫️ DoD 불투명도",
            min_value=0.0, max_value=1.0,
            value=0.65, step=0.05,
            disabled=not (feasible and dod_on),
            key=f"tab34_dod_opacity_{sel_site_id}",
        )
    with ctrl_c:
        threshold = st.slider(
            "🎯 임계치 ±m (작은 변화 무시)",
            min_value=0.0, max_value=float(th_max),
            value=min(round(default_th, 2), float(th_max)), step=0.01,
            disabled=not feasible,
            key=f"tab34_dod_threshold_{sel_site_id}",
            help=th_help,
        )
    with ctrl_d:
        if lod95 is not None:
            st.caption(
                f"📏 **LoD95 = ±{lod95:.2f} m**  \n"
                "95% 신뢰 최소탐지한계 — 1.96×√(RMSE₁²+RMSE₂²)"
            )
        else:
            st.caption("📏 LoD95: RMSE 메타 없음 — 산출 불가")

    # ── DoD 계산 (캐시) ──
    # Build 1.3 (사용자 제보): CSS 회전 spinner + st.empty() placeholder 패턴.
    # Streamlit 이 spinner HTML 을 먼저 flush → 브라우저에서 GPU 기반 회전
    # 시작 → Python 이 25초간 block → 완료 후 placeholder.empty() 로 자동 제거.
    dod_result = None
    dod_png_url = ""
    dod_bounds  = ""
    if feasible:
        # 🆕 (2026-06-11 S5) PNG 존재 = Δz 캐시 가능성 높음 → 임계치 변경은
        # 재렌더(1~2초)만. PNG 미존재 = full 계산(~25초) 안내 유지.
        cache_hit = dod_png_path(left, right).exists()
        spinner_slot = st.empty()
        if not cache_hit:
            spinner_slot.markdown(
                '<div style="display:flex;align-items:center;gap:10px;'
                'padding:8px 12px;background:rgba(255,193,7,0.08);'
                'border:1px solid rgba(255,193,7,0.4);border-radius:6px;'
                'font-size:13px;color:#856404;">'
                '<div style="width:16px;height:16px;border:3px solid #ddd;'
                'border-top-color:#ff9800;border-radius:50%;'
                'animation:tab34-dod-spin 0.9s linear infinite;flex-shrink:0;"></div>'
                '<span><b>DoD 계산 중</b> (DSM 차분 + RTK 보정 + 3x3 median filter) — 약 25초 소요. '
                '이후 같은 좌·우 조합은 즉시, 임계치 변경은 1~2초 내 재렌더됩니다.</span>'
                '<style>@keyframes tab34-dod-spin {to {transform: rotate(360deg);}}</style>'
                '</div>',
                unsafe_allow_html=True,
            )
        dod_result = compute_dod(left, right, threshold_m=threshold)
        if not cache_hit:
            spinner_slot.empty()
        dod_png_url = url_for_dod_png(left, right)
        dod_bounds  = dod_bounds_str(left, right)

    # 🆕 (2026-06-11 Q4) hillshade 생성 (캐시) + URL — 토글 ON 일 때만
    hs_png_url = ""
    hs_bounds  = ""
    if hs_on:
        with st.spinner("⛰️ 음영기복 생성 중… (최초 1회, 이후 캐시)"):
            hs_ok = ensure_hillshade(left, right)
        if hs_ok:
            hs_png_url = url_for_hs_png(left, right)
            hs_bounds  = hs_bounds_str(left, right)
        else:
            st.caption("⚠ 음영기복 생성 실패 — DSM 또는 rasterio 의존성 확인 (탭 동작에는 영향 없음).")

    # ── 좌·우 viewer + DoD overlay ──
    # [공개판] Cloud: pdf_server(:8766) 없음 → viewer html 을 인라인 렌더
    #   (preview.png 는 data URI 임베드). 로컬: 기존 iframe 방식 유지.
    if is_cloud_env():
        _inline = diff_viewer_dod_inline_html(
            left, right,
            vworld_key=(config.VWORLD_API_KEY or "").strip(),
            dod_png_url=dod_png_url,
            dod_bounds=dod_bounds,
            dod_opacity=opacity,
            dod_visible=dod_on,
            hs_img=hs_png_url,
            hs_bounds=hs_bounds,
            hs_opacity=0.35,
        )
        if _inline is None:
            st.warning("시계열 비교 뷰어 준비 실패 — preview.png 동봉 여부를 확인하세요.")
            return
        st.components.v1.html(_inline, height=1224, scrolling=False)
    else:
        viewer_url = url_for_diff_viewer_dod(
            left, right,
            vworld_key=(config.VWORLD_API_KEY or "").strip(),
            dod_png_url=dod_png_url,
            dod_bounds=dod_bounds,
            dod_opacity=opacity,
            dod_visible=dod_on,
            hs_img=hs_png_url,
            hs_bounds=hs_bounds,
            hs_opacity=0.35,
        )
        st.components.v1.iframe(viewer_url, height=1224, scrolling=False)

    # ── 메타 정보 (촬영 간격) ──
    def _parse_date(s: str) -> date | None:
        try:
            parts = s.split("-")
            y = int(parts[0])
            m = int(parts[1]) if len(parts) >= 2 else 1
            d = int(parts[2]) if len(parts) >= 3 else 1
            return date(y, m, d)
        except (ValueError, IndexError):
            return None

    ld, rd = _parse_date(left.flight_date), _parse_date(right.flight_date)
    if ld and rd and ld != rd:
        interval_text = f"{abs((rd - ld).days)} 일"
    elif ld and rd and ld == rd:
        interval_text = "0 일 (동일)"
    else:
        interval_text = "—"

    meta_cols = st.columns(3)
    theme.render_stat_card(
        "◀ 좌측", left.flight_date, f"{left.name}",
        color=theme.COLOR_TEXT_INFO, container=meta_cols[0],
    )
    theme.render_stat_card(
        "🗓️ 촬영 간격", interval_text, "두 시점 사이 일수",
        color=(theme.COLOR_SUCCESS if ld and rd and ld != rd
               else theme.COLOR_TEXT_TERTIARY),
        container=meta_cols[1],
    )
    theme.render_stat_card(
        "우측 ▶", right.flight_date, f"{right.name}",
        color=theme.COLOR_TEXT_INFO, container=meta_cols[2],
    )

    st.caption(
        "ℹ️ 좌·우 동기화 + DoD 색상 overlay (파랑=감소, 흰색=변화 없음, 빨강=증가). "
        "농업기반시설 점검 — 퇴적·침하·식생 변화 감지."
    )

    # ── DoD 통계 + 범례 ──
    if dod_result:
        stats = dod_result.get("stats") or {}
        st.markdown("### 📊 DoD 통계")
        s_cols = st.columns(4)
        theme.render_stat_card(
            "평균 Δz",
            format_stats_card_value(stats, "mean_m", unit="m"),
            "양수=퇴적·신축 / 음수=침식·제거",
            color=theme.COLOR_TEXT_INFO,
            container=s_cols[0],
        )
        theme.render_stat_card(
            "최대 증가",
            format_stats_card_value(stats, "max_m", unit="m"),
            "가장 큰 표고 상승 지점",
            color=theme.COLOR_SUCCESS,
            container=s_cols[1],
        )
        theme.render_stat_card(
            "최대 감소",
            format_stats_card_value(stats, "min_m", unit="m"),
            "가장 큰 표고 하강 지점",
            color=theme.COLOR_TEXT_INFO,
            container=s_cols[2],
        )
        theme.render_stat_card(
            "net 부피",
            format_stats_card_value(stats, "net_volume_m3", unit="m³", fmt="{:+.2f}"),
            "양수 − 음수 = 순변화 부피",
            color=theme.COLOR_TEXT_TERTIARY,
            container=s_cols[3],
        )
        # 🆕 (2026-06-11 Q1/Q2) LoD95 + 부피 불확실도 카드 (2행)
        q_cols = st.columns(4)
        theme.render_stat_card(
            "LoD95 (최소탐지한계)",
            (f"±{lod95:.2f} m" if lod95 is not None else "—"),
            "1.96 × √(RMSE₁² + RMSE₂²) — 이보다 작은 Δz 는 불확실도 이내",
            color=theme.COLOR_TEXT_TERTIARY,
            container=q_cols[0],
        )
        theme.render_stat_card(
            "부피 불확실도",
            format_stats_card_value(stats, "volume_uncert_m3", unit="m³", fmt="± {:.1f}"),
            "LoD95(없으면 임계치) × 변화 면적",
            color=theme.COLOR_TEXT_TERTIARY,
            container=q_cols[1],
        )
        st.caption(f"모드: **{dod_result.get('mode', '—')}** · {dod_result.get('message', '')}")

        # 🆕 (2026-06-11 Q5) DoD GeoTIFF 보존 경로 안내 (QGIS 등 후처리용)
        _tif = dod_png_path(left, right).with_suffix(".tif")
        if _tif.exists():
            st.caption(f"💾 DoD GeoTIFF (Δz, float32, nodata=-9999): `{_tif}`")

        # 🆕 (2026-06-11 Q3) Δz 분포 히스토그램 — threshold·LoD95 ±라인
        hist = (stats or {}).get("hist")
        if hist and hist.get("counts"):
            with st.expander("📊 Δz 분포 히스토그램", expanded=False):
                import plotly.graph_objects as go
                edges = hist["bin_edges"]
                counts = hist["counts"]
                centers = [(edges[i] + edges[i + 1]) / 2.0 for i in range(len(counts))]
                bin_w = (edges[1] - edges[0]) if len(edges) > 1 else 0.025
                fig = go.Figure(go.Bar(
                    x=centers, y=counts, width=bin_w * 0.9,
                    marker_color=["#08519c" if c < 0 else "#a50f15" for c in centers],
                ))
                if threshold and threshold > 0 and threshold <= abs(edges[-1]):
                    fig.add_vline(x=float(threshold), line_dash="dash",
                                  line_color="#ff9800",
                                  annotation_text=f"+임계치 {threshold:.2f}")
                    fig.add_vline(x=-float(threshold), line_dash="dash",
                                  line_color="#ff9800",
                                  annotation_text="−임계치")
                if lod95 is not None and lod95 <= abs(edges[-1]):
                    fig.add_vline(x=float(lod95), line_dash="dot",
                                  line_color="#4a90e2",
                                  annotation_text=f"+LoD95 {lod95:.2f}")
                    fig.add_vline(x=-float(lod95), line_dash="dot",
                                  line_color="#4a90e2",
                                  annotation_text="−LoD95")
                fig.update_layout(
                    height=300, margin=dict(l=10, r=10, t=30, b=10),
                    xaxis_title="Δz (m, ±1.0 클립)", yaxis_title="픽셀 수",
                    showlegend=False, bargap=0,
                )
                st.plotly_chart(fig, use_container_width=True,
                                key=f"tab34_dod_hist_{sel_site_id}")
                st.caption(
                    "범위 밖(|Δz|>1.0m)은 ±1.0 빈에 클립. "
                    "주황 점선=임계치, 파랑 점선=LoD95."
                )

    st.markdown("**🎨 색상 범례 (RdBu_r diverging colormap)**")
    st.markdown(colormap_legend_html(vmax_m=1.0), unsafe_allow_html=True)

    # Build 1.3 (2026-06-03 사용자 제보): 차량처럼 이동 가능한 구조물 검출 한계 분석
    with st.expander("🚗 왜 차량 위치 변화는 DoD 에 잘 안 잡힐까? — RTK 와 DSM 한계",
                     expanded=False):
        st.markdown(
            "### 사용자 관찰\n"
            "차량은 분명히 다른 위치에 주차됐는데, DoD 색이 거의 안 들어옴.  "
            "흰 더미 같은 정지 구조물은 잘 검출되는데, **이동 가능한 구조물은 약함**.\n"
            "\n"
            "### 원인 분석\n"
            "| 원인 | 현재 데이터 | 영향 |\n"
            "|---|---|---|\n"
            "| **RTK 모드 차이** | 2025-01 = Single (RMSE 0.93m) / 2026-05 = Fix (RMSE 0.42m) | 두 미션 수평 오차 ~1m → 차량 너비(2m)와 비슷 → 위치 A·B 가 부분 overlap → DoD 신호 **상쇄 (cancel out)** |\n"
            "| **SfM-MVS outlier 제거** | DJI Terra 가 차량 같은 비정합 픽셀을 outlier 처리 가능 | 한 미션 DSM 에 차량 없으면 차분 = 0 |\n"
            "| **median filter 3x3** | Build 1.2 자동 적용 | 가장자리 노이즈 ↓ 하지만 작은 features 도 약간 smoothing |\n"
            "\n"
            "### RTK 양쪽 다 있으면 차량 검출 가능?\n"
            "**YES — 큰 폭 개선**. 두 미션 모두 RTK Fix 면:\n"
            "- 수평 정확도 ~3cm (현재 ~1m)\n"
            "- 수직 정확도 ~5cm\n"
            "- 차량 위치 변화 (수 m 이동) 가 깨끗한 빨강/파랑 patch 로 분리 표시\n"
            "- 농기계·트럭·자재 더미 등 day-to-day 변화 추적 가능\n"
            "\n"
            "**현재 데이터로 차량 흔적 보려면**: 임계치 슬라이더 **±0.05m** 로 내려서 "
            "약한 신호도 보기. 노이즈 많이 보이지만 차량 자리에 약한 빨강 patch 가 보일 수 있음.\n"
            "\n"
            "### 진정한 가변 구조물 검출은?\n"
            "- **Point cloud M3C2** (점군 normal 방향) — Phase 2\n"
            "- M3C2 는 RTK 정확도 영향 받지만 normal projection 으로 "
            "수평 오차의 cancel-out 효과 ↓\n"
            "- 향후 2025-01 재촬영 RTK Fix 권장"
        )

    with st.expander("🔬 결과 해석 가이드 — 왜 탱크 가장자리에 빨강·파랑이 보일까?",
                     expanded=False):
        st.markdown(
            "### 잘 검출되는 변화 (신뢰 ✅)\n"
            "- **건초 더미·자재 더미** 등 평면 지면 위 정지 새 물체 → 강한 빨강 (Δz +1~3m)\n"
            "- **토사 퇴적·식생 성장** → 넓은 영역 옅은 빨강\n"
            "- **굴착·식생 제거** → 넓은 영역 옅은 파랑\n"
            "\n"
            "### 인공물 — 실제 변화가 아닌 색 (주의 ⚠️)\n"
            "**둥근 탱크·옹벽 가장자리의 ±수 m 빨강·파랑 halo**: DSM 은 수직 표고만 측정 → "
            "수직 벽면 정보 없음. 두 미션 sub-pixel 수평 시프트로 가장자리에 oscillation. "
            "**탱크 실제 변화 없어도 가장자리에 띠 보임 = 정상**.\n"
            "\n"
            "Build 1.2 부터 3x3 median filter 자동 적용으로 가장자리 노이즈 감소.\n"
            "\n"
            "### 진정한 벽면 변화는?\n"
            "Point cloud M3C2 (점군 normal 방향) 가 표준 — Phase 2 예정.\n"
            "\n"
            "### 임계치 조정 팁\n"
            "- 노이즈 많으면 ±0.15~0.30m\n"
            "- 미세 변화 ±0.05m (저수조·옹벽 추천값)\n"
            "- 식생 변화 무시 ±0.50m+"
        )

