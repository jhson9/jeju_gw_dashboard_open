# -*- coding: utf-8 -*-
# =============================================================================
# SOURCE  : jeju_groundwater_dashboard/src/dashboard/tabs/tab35_drone_diff_3d.py
# PORTED  : 2026-06-01 (자율 작업)
# RENAMED : tab35_drone_diff_3d.py -> tab14_drone_timeseries_3d.py
# 의존    : src/drone/*, _drone_helpers, config.DRONE_DATA_ROOT
# 데이터  : 3개 저수조 (2505_구좌덕천 / 2605_구좌덕천 / 2605_구좌세화)
# 우선순위: 노트북 데스크톱 (Chrome) / 보조: Tab S10+ Samsung Internet 가로
# 모바일 폰(<768px) 미지원 - Cesium 3D 자산 무거움.
# 변경    : (1) Quit 버튼 제거 (공개판 정책 fa4878f 준수)
#               - 'from ...quit_helper import quit_button' 삭제
#               - '_t, _q = st.columns([10, 1])' -> '_t = st.container()'
#               - 'with _q: quit_button(...)' 2줄 삭제
#           (2) 그 외 본문 무수정
# =============================================================================

# ==============================================================================
#  파일명: src/dashboard/tabs/tab35_drone_diff_3d.py  —  Build 3.0
#  모듈: 35.시계열 분석(3D) 탭 (드론영상 그룹)
# ------------------------------------------------------------------------------
#  같은 시설물의 다른 시점 3D 모델을 좌·우 분할 + master-slave 카메라 동기화.
#  tab34 (2D 정사영상 비교) 와 동일 UI 구조의 3D 버전.
#
#  현재 시뮬레이션 모드 — 같은 미션을 좌·우 동시 표시 (검증용).
#  실데이터는 같은 site_id 의 2 시점 b3dm 확보 후 (2605 송당 ~2026-06-23).
#
#  UI 구조:
#    - 1행 3열 dropdown: 좌 시점 · 중앙 시설물 · 우 시점
#    - iframe → /pdfs/drone_viewer/diff_viewer_3d.html (pdf_server :8766)
#    - 메타 카드 3개: 좌 시점 / 촬영 간격 / 우 시점
#    - M3C2 roadmap 표 (7단계 진행 계획)
#
# ------------------------------------------------------------------------------
#  변경 이력 (2026-05-25 사용자 검증 + 다회 에이전트 진단)
# ------------------------------------------------------------------------------
#  [Build 1.0] 초기 — tab34 의 3D 버전, 양방향 카메라 동기화
#  [Build 2.0] 깜빡거림·검은 화면 1차 fix:
#              · requestRenderMode = true
#              · webglcontextlost 핸들러
#              · 카메라 sync 3중 안전망 (percentageChanged + threshold + rAF)
#  [Build 2.5] LOD 정밀 비교 모드:
#              · Adaptive SSE (정지 4 / 이동 32, moveEnd+800ms refine)
#              · 메모리 cap 512MB / viewer, dynamicSSE on
#              · sse=4 로 인자 변경 (정지 시 cm 급 디테일)
#  [Build 3.0] Master-Slave 패턴 + LOD 5종 OFF (좌·우 완벽 일치):
#              · 양방향 sync 의 setView ↛ moveStart/moveEnd 문제 우회
#              · 우측 master, 좌측 slave (마우스 입력 차단)
#              · dynamicSSE/skipLOD/foveatedSSE/progressive/cullMoving 모두 false
#              · adaptive SSE 가 양쪽 tileset 동시 변경 (master movement 만 listen)
#              · preRender 가드의 useDefaultRenderLoop dead-lock 제거
#              · scene.renderError 자가 복원 + 3회 카운터
#
#  자세한 원인·해결 정리: diff_viewer_3d.html 상단 주석 참조 (✓✓✓ 필독)
#
# ------------------------------------------------------------------------------
#  파라미터·전제
# ------------------------------------------------------------------------------
#  · sse=4: 정지 시 최고 해상도. 이동 시 32 로 viewer 안에서 자동 전환.
#  · 데스크탑 + GPU 4GB+ 전제 ([[project-drone-purpose]])
#  · 같은 origin (8766) → Cesium Worker 정상 작동
#  · iframe height=1024 — tab34 (1224) 보다 약간 작게 (3D GPU 부담 고려)
#
# ------------------------------------------------------------------------------
#  향후 (실데이터 확보 후)
# ------------------------------------------------------------------------------
#  · 같은 site_id 2 시점 → ICP 정렬 → M3C2 거리 계산 → diff 점군 생성
#  · diff bbox 산출 → "다음 변화 지점" 버튼으로 자동 flyTo
#  · 변화량 색상 overlay (좌·우 viewer 위에 반투명)
#  · DoD (DSM Difference) 2.5D 분석과 함께 사용 (tab34 와 연계)
#
# ------------------------------------------------------------------------------
#  관련 메모리
# ------------------------------------------------------------------------------
#  [[project-drone-purpose]] 시계열 변화 감지가 드론 주요 목적
#  [[project-fragment-pattern]] @st.fragment — render() 만, nested 금지
#  [[project-drone-dual-viewer-sync]] master-slave + LOD 5종 OFF 패턴
#  [[feedback-cesium-show-not-assign]] scene.xxx.show=false 만 사용
#  [[project-drone-2605-3d-pending]] 2605 송당 3D 작업 2026-06-23 경
# ==============================================================================
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

from src.dashboard import theme

from src.dashboard.tabs._drone_helpers import (
    get_registry,
    url_for_diff_viewer_3d,
)


@st.fragment
def render() -> None:
    # selectbox 변경 시 페이지 전체 rerun 으로 st.tabs idx 0 리셋되는 문제를
    # fragment-scoped rerun 으로 차단 — [[project-fragment-pattern]] 준수.
    _t = st.container()  # 공개판 정책: Quit 버튼 제거 (원본은 [10,1] 컬럼 분할)
    with _t:
        st.markdown(
            '<p class="tab-title" style="margin:0;">35.시계열 분석(3D)</p>',
            unsafe_allow_html=True,
        )

    reg = get_registry()
    if len(reg) == 0:
        st.warning("등록된 드론 미션이 없습니다.")
        return

    # tiles_3d (3D 모델) 있는 미션만 후보. site_id 별 그룹.
    missions_3d = [m for m in reg if m.has("tiles_3d")]
    if not missions_3d:
        st.warning(
            "3D 모델(tiles_3d)이 처리된 미션이 없습니다. "
            "DJI Terra 에서 3D 재건을 실행하면 자동으로 활성화됩니다."
        )
        return

    # site_id → 그 site_id 의 미션 목록
    sites: dict[str, list] = {}
    for m in missions_3d:
        sites.setdefault(m.site_id, []).append(m)
    for sid in sites:
        sites[sid].sort(key=lambda m: m.flight_date)

    facility_labels: dict[str, str] = {}
    for sid, ms in sites.items():
        first = ms[0]
        n = len(ms)
        suffix = f" · {n} 시점" if n > 1 else " · 1 시점 (시뮬레이션)"
        facility_labels[sid] = f"{first.name} ({first.site_type}){suffix}"

    # ── 1행 3열: 좌 시점 · 중앙 시설물 · 우 시점 (tab34 와 동일) ──
    col_left, col_center, col_right = st.columns([1, 1.2, 1])

    with col_center:
        sel_site_id = st.selectbox(
            "📍 시설물",
            list(facility_labels.keys()),
            format_func=lambda sid: facility_labels[sid],
            key="tab35_site",
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
            key=f"tab35_left_{sel_site_id}",
        )

    with col_right:
        sel_right_id = st.selectbox(
            "우측 시점 ▶",
            time_ids,
            index=len(time_ids) - 1,
            format_func=lambda mid: time_label(id_to_mission[mid]),
            key=f"tab35_right_{sel_site_id}",
        )

    left = id_to_mission[sel_left_id]
    right = id_to_mission[sel_right_id]

    # ── 시뮬레이션 모드 경고 — 좌·우 같은 미션 선택 시 ──
    # 사용자가 dropdown 라벨을 못 읽으면 "같은 영상이 두 번" 으로 오인 가능.
    if left.id == right.id:
        st.info(
            "💡 **시뮬레이션 모드** — 좌·우가 같은 미션입니다. "
            "같은 site_id 의 두 시점 데이터 확보 후 실제 시계열 비교 가능. "
            "(현재는 master-slave 동기화·LOD 일치 검증용)"
        )

    # ── 좌·우 3D 동기화 뷰어 (iframe) ──
    # height 1024 — tab34 (1224) 보다 약간 작게. 3D 는 GPU 부담 + 두 viewer
    # 라 화면 너무 길면 위·아래 패닝 부담. 22 에이전트 합의.
    # SSE=4 — tab34/35 는 "차이점 정밀 비교" 가 목적이라 정지 시 최고 해상도.
    # diff_viewer_3d.html 의 adaptive SSE 가 이동 중엔 32 로 올렸다가 멈추면
    # 800ms 후 4 로 refine — 사용자가 정지해서 자세히 볼 때 cm 급 디테일.
    viewer_url = url_for_diff_viewer_3d(left, right, sse=4)
    st.components.v1.iframe(viewer_url, height=1024, scrolling=False)

    # ── 메타 정보 (촬영 간격) — tab34 와 동일 패턴 ──
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
        "◀ 좌측",
        left.flight_date,
        f"{left.name}",
        color=theme.COLOR_TEXT_INFO,
        container=meta_cols[0],
    )
    theme.render_stat_card(
        "🗓️ 촬영 간격",
        interval_text,
        "두 시점 사이 일수",
        color=(theme.COLOR_SUCCESS if ld and rd and ld != rd
               else theme.COLOR_TEXT_TERTIARY),
        container=meta_cols[1],
    )
    theme.render_stat_card(
        "우측 ▶",
        right.flight_date,
        f"{right.name}",
        color=theme.COLOR_TEXT_INFO,
        container=meta_cols[2],
    )

    st.caption(
        "ℹ️ **우측 = 조작 영역** (회전·줌·팬), **좌측 = 자동 동기화**. "
        "우측에서 의심 지점에 멈추면 800ms 후 cm 급 정밀 해상도로 refine 됩니다. "
        "같은 시설물의 다른 시점에서 정확히 같은 각도·같은 LOD 로 비교 가능."
    )

    # ──────────────────────────────────────────────────────────────────
    #  📊 3D 변화 감지 (M3C2 / Point Cloud) — 진행 계획
    # ------------------------------------------------------------------
    #  tab34 의 DSM Difference (2.5D) 의 3D 확장 — 벽면/오버행 변화까지 포함.
    # ──────────────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 📊 3D 점군 변화 감지 (M3C2) — 계획")

    try:
        _pop = st.popover(
            "📖 M3C2 가 무엇인가요? (DSM Difference 와 차이)",
            help="M3C2 (Multiscale Model to Model Cloud Comparison) — "
                 "3D 점군 간 표준 변화 감지 알고리즘",
        )
    except AttributeError:
        _pop = st.expander("📖 M3C2 가 무엇인가요?", expanded=False)

    with _pop:
        st.markdown(
            "#### M3C2 = Multiscale Model to Model Cloud Comparison\n"
            "두 시점의 **3D 점군 (Point Cloud)** 을 직접 비교 — DSM Difference (수직 차이)"
            "보다 정밀한 **3D 표면 변화** 감지.\n"
            "\n"
            "**DSM Difference (tab34) vs M3C2 (tab35) 비교:**\n"
            "| 항목 | DSM Difference (tab34) | M3C2 (tab35) |\n"
            "|---|---|---|\n"
            "| 데이터 | DSM raster (2.5D, 수직 표고만) | Point cloud (3D, 전 방향) |\n"
            "| 표현 | 수직 변화만 (Δh) | 표면 normal 방향 변화 |\n"
            "| 측면 벽 변화 | ❌ 측정 못 함 | ✅ 측정 가능 |\n"
            "| 오버행/돌출부 | ❌ 무시 | ✅ 정확 |\n"
            "| 처리 시간 | ~30초 / 미션쌍 | ~5-30분 / 미션쌍 |\n"
            "| 정확도 | cm 급 (RTK 의존) | mm-cm 급 (point cloud 밀도) |\n"
            "\n"
            "**시설물 관리 적용 예 (tab34 보다 추가):**\n"
            "- 저수조 **외벽의 균열 폭 변화** → M3C2 의 normal 방향 거리 측정\n"
            "- 저수조 **상단 가장자리 침하** → 3D 표면 정밀 비교\n"
            "- 송수관 **표면 부식** → 미세 형태 변화\n"
            "- 옹벽 **수직 변형** → 측면 변위 정량\n"
        )

        st.markdown("**도구:**")
        st.markdown(
            "- **py4dgeo** (Python, OpenMP) — M3C2 / M3C2-EP 표준 구현, MIT 라이선스\n"
            "- **CloudCompare** (Desktop GUI) — M3C2 원조, batch CLI 가능\n"
            "- **Open3D** (Python) — ICP align + 점군 거리 계산\n"
        )

    # ── 3D 변화 감지 진행 계획 표 ──
    st.markdown("**진행 단계 (Roadmap)**")
    plan = pd.DataFrame([
        {
            "단계": "0",
            "내용": "3D 모델 좌·우 동기화 viewer",
            "필요 조건": "DJI Terra 3D Tiles (b3dm)",
            "산출물": "tab35 시뮬레이션 모드",
            "상태": "✅ 완료 (현재)",
        },
        {
            "단계": "1",
            "내용": "같은 site_id 의 2 시점 데이터 확보",
            "필요 조건": "드론 재촬영 + DJI Terra 재 export (3D + 점군)",
            "산출물": "registry.json 에 2 미션 등록 + LAS/PLY 파일",
            "상태": "⏳ 대기 (예: 2605 송당 2026-06-23경)",
        },
        {
            "단계": "2",
            "내용": "점군 ICP 정렬 (Co-registration)",
            "필요 조건": "단계 1 완료 + Open3D 패키지",
            "산출물": "RTK 보정 + 안정 영역 ICP → 정렬 RMSE 수 cm",
            "상태": "📝 prepared",
        },
        {
            "단계": "3",
            "내용": "M3C2 거리 계산 (py4dgeo)",
            "필요 조건": "단계 2 완료 + py4dgeo 패키지",
            "산출물": "각 점에 distance + LoD95 attribute 추가된 LAS",
            "상태": "📝 prepared",
        },
        {
            "단계": "4",
            "내용": "결과 → 컬러 점군 또는 3D Tiles 변환",
            "필요 조건": "단계 3 완료 + py3dtiles",
            "산출물": "diff_<l>_<r>.ply 또는 b3dm + 통계 JSON",
            "상태": "📋 설계됨",
        },
        {
            "단계": "5",
            "내용": "tab35 viewer 에 변화량 색상 overlay",
            "필요 조건": "단계 4 완료",
            "산출물": "좌·우 viewer 사이 또는 중앙에 변화 색상 표시",
            "상태": "📋 설계됨",
        },
        {
            "단계": "6",
            "내용": "변화 측정 도구 (사용자 클릭 → 두 점 거리)",
            "필요 조건": "단계 5 완료",
            "산출물": "사용자가 특정 영역 측정 가능",
            "상태": "🔮 향후",
        },
    ])
    st.dataframe(plan, use_container_width=True, hide_index=True)

    st.caption(
        "📌 현재 단계 0 (시뮬레이션 모드). 같은 시설물의 다른 시점 데이터 추가 시 "
        "단계 1 → 6 순차 진행. 단계 2~5 약 1~2주 예상. "
        "tab34 의 DSM Difference 와 함께 사용 권장 (DSM 은 빠른 개관, M3C2 는 정밀 분석)."
    )
