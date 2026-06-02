# ==============================================================================
#  파일명: src/dashboard/tabs/tab34_drone_diff.py
#  모듈: 34.시계열 분석 탭 (드론영상 그룹)
# ------------------------------------------------------------------------------
#  같은 시설물의 다른 시점 정사영상을 좌·우 분할 + 동기화 동기화 비교.
#
#  사용자 요청 (2026-05-24):
#    - 1행 3열 UI: 좌 시점 / 중앙 시설물 / 우 시점 dropdown
#    - 좌·우 같은 축척·좌표에 맞춰 표시
#    - 한쪽 이동/zoom 시 반대편이 따라옴 (동기화)
#    - 같은 미션 좌우 동시 표시 OK (시뮬레이션 모드 — 2 epoch 데이터 도착 전 검증용)
#
#  구현:
#    - st.columns(3) — 좌측 시점, 중앙 시설물, 우측 시점 dropdown
#    - st.components.v1.iframe → diff_viewer.html (pdf_server :8766 same-origin)
#    - 정사영상 ImageOverlay + V-World 배경 + Leaflet.Sync 양방향 동기화
#
#  관련 메모리:
#    [[project-drone-purpose]] 드론 주요 목적 = 시계열 변화 감지
#    [[project-fragment-pattern]] @st.fragment — render() 만, nested 금지
#    [[project-drone-tab31-structure]] 4 미션 · site_id 기준 · pdf_server :8766
# ==============================================================================
from __future__ import annotations

from datetime import date

import pandas as pd
import streamlit as st

import config

from src.dashboard import theme
from src.dashboard.quit_helper import quit_button

from src.dashboard.tabs._drone_helpers import (
    get_registry,
    url_for_diff_viewer,
)


@st.fragment
def render() -> None:
    # selectbox 변경 시 페이지 전체 rerun 으로 st.tabs idx 0 리셋되는 문제를
    # fragment-scoped rerun 으로 차단 — [[project-fragment-pattern]] 준수.
    _t, _q = st.columns([10, 1])
    with _t:
        st.markdown(
            '<p class="tab-title" style="margin:0;">34.시계열 분석(2D)</p>',
            unsafe_allow_html=True,
        )
    with _q:
        quit_button("quit_in_tab34")

    reg = get_registry()
    if len(reg) == 0:
        st.warning("등록된 드론 미션이 없습니다.")
        return

    # tiles_2d (정사영상) 있는 미션만 후보. site_id 별 그룹.
    missions_2d = [m for m in reg if m.has("tiles_2d")]
    if not missions_2d:
        st.warning(
            "정사영상(tiles_2d)이 처리된 미션이 없습니다. "
            "DJI Terra 산출물의 result.tif → derived/preview.png 생성 후 활성화됩니다."
        )
        return

    # site_id → 그 site_id 의 미션 목록
    sites: dict[str, list] = {}
    for m in missions_2d:
        sites.setdefault(m.site_id, []).append(m)
    # 각 시설물 안 미션을 flight_date 순 정렬
    for sid in sites:
        sites[sid].sort(key=lambda m: m.flight_date)

    # 시설물 표시 라벨 (시설물명 + 타입 + 보유 시점 수)
    facility_labels: dict[str, str] = {}
    for sid, ms in sites.items():
        first = ms[0]
        n = len(ms)
        suffix = f" · {n} 시점" if n > 1 else " · 1 시점 (시뮬레이션)"
        facility_labels[sid] = f"{first.name} ({first.site_type}){suffix}"

    # ── 1행 3열: 좌 시점 · 중앙 시설물 · 우 시점 ──
    col_left, col_center, col_right = st.columns([1, 1.2, 1])

    # ❶ 중앙: 시설물 선택 — 좌·우 시점 옵션을 결정
    with col_center:
        sel_site_id = st.selectbox(
            "📍 시설물",
            list(facility_labels.keys()),
            format_func=lambda sid: facility_labels[sid],
            key="tab34_site_v2",
        )

    available = sites[sel_site_id]   # 선택된 시설물의 시점들
    time_label = lambda m: m.flight_date
    time_ids = [m.id for m in available]
    id_to_mission = {m.id: m for m in available}

    # ❷ 좌측: 좌측 시점
    with col_left:
        sel_left_id = st.selectbox(
            "◀ 좌측 시점",
            time_ids,
            index=0,
            format_func=lambda mid: time_label(id_to_mission[mid]),
            key=f"tab34_left_v2_{sel_site_id}",   # 시설물 바뀌면 key 도 바뀜
        )

    # ❸ 우측: 우측 시점 (기본값 = 가장 최신)
    with col_right:
        sel_right_id = st.selectbox(
            "우측 시점 ▶",
            time_ids,
            index=len(time_ids) - 1,
            format_func=lambda mid: time_label(id_to_mission[mid]),
            key=f"tab34_right_v2_{sel_site_id}",
        )

    left = id_to_mission[sel_left_id]
    right = id_to_mission[sel_right_id]

    # ── 시뮬레이션 모드 경고 — 좌·우 같은 미션 선택 시 ──
    if left.id == right.id:
        st.info(
            "💡 **시뮬레이션 모드** — 좌·우가 같은 미션입니다. "
            "같은 site_id 의 두 시점 데이터 확보 후 실제 시계열 비교 가능."
        )

    # ── 좌·우 동기화 뷰어 (iframe) — height 1224 (이전 720 의 1.7배) ──
    viewer_url = url_for_diff_viewer(
        left, right,
        vworld_key=(config.VWORLD_API_KEY or "").strip(),
    )
    st.components.v1.iframe(viewer_url, height=1224, scrolling=False)

    # ── 메타 정보 (촬영 간격) ──
    # flight_date 는 "YYYY-MM" 또는 "YYYY-MM-DD" 형식 — 간단 파싱.
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
        "ℹ️ 좌·우 양방향 동기화 — 한쪽을 이동·zoom 하면 반대편이 자동으로 따라옵니다. "
        "마우스 커서 위치도 두 지도에 표시되어 정확한 비교 가능."
    )

    # ──────────────────────────────────────────────────────────────────
    #  📊 DSM Difference (DoD) — 표고 차분 분석 (Phase 1, 진행 계획)
    # ------------------------------------------------------------------
    #  현재는 정사영상 시각 비교만. DoD 는 같은 site_id 의 2 시점 미션이 도착
    #  후 활성화. 사용자 요청 (2026-05-24): 진행 계획 표 + popover 설명 버튼.
    # ──────────────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### 📊 DSM Difference (DoD) — 표고 차분 분석 (계획)")

    # 설명 popover — streamlit 1.32+ 지원 (1.47.1 OK). 클릭 시 풍부한 설명 표시.
    try:
        _dod_pop = st.popover(
            "📖 DoD 란? 어떻게 보여집니까?",
            help="DSM Difference (Digital Surface Model Difference) — "
                 "두 시점의 표고 raster 차이를 색상으로 시각화",
        )
    except AttributeError:
        # 폴백 — popover 미지원 환경
        _dod_pop = st.expander("📖 DoD 란? 어떻게 보여집니까?", expanded=False)

    with _dod_pop:
        st.markdown(
            "#### DoD = DEM of Difference\n"
            "두 시점의 **DSM (Digital Surface Model, 표고 raster)** 픽셀별 차이를 계산:\n"
            "\n"
            "```\n"
            "DoD(픽셀) = DSM_새시점(픽셀) - DSM_옛시점(픽셀)\n"
            "```\n"
            "\n"
            "**해석:**\n"
            "- 양수 (+) → 표고 증가: 퇴적 / 구조물 신축 / 식생 성장\n"
            "- 음수 (-) → 표고 감소: 제거 / 침식 / 수위 하강\n"
            "- 0 부근    → 변화 없음"
        )

        st.markdown("**색상 매핑 (diverging colormap, RdBu_r):**")
        # 색상 예시 가시화 (HTML grid)
        st.markdown(
            '<div style="display:flex;gap:0;font-family:monospace;font-size:12px;'
            'margin:8px 0;border-radius:4px;overflow:hidden;border:1px solid #888;">'
            '<div style="flex:1;background:#08519c;color:#fff;padding:8px;text-align:center;">−1.0m<br>큰 감소</div>'
            '<div style="flex:1;background:#6baed6;color:#fff;padding:8px;text-align:center;">−0.3m<br>감소</div>'
            '<div style="flex:1;background:#f7f7f7;color:#333;padding:8px;text-align:center;">±0m<br>변화 없음</div>'
            '<div style="flex:1;background:#fc9272;color:#fff;padding:8px;text-align:center;">+0.3m<br>증가</div>'
            '<div style="flex:1;background:#a50f15;color:#fff;padding:8px;text-align:center;">+1.0m<br>큰 증가</div>'
            '</div>',
            unsafe_allow_html=True,
        )
        st.caption("🔵 파랑(-) ←→ ⚪ 흰색(0) ←→ 🔴 빨강(+)")

        st.markdown(
            "**시설물 관리 적용 예** ([[project-drone-purpose]] 참조):\n"
            "- 저수조 옆 토사 퇴적 → 그 지점 빨강 (배수 점검 필요)\n"
            "- 저수조 벽 파손 → 그 지점 파랑 (구조 점검 필요)\n"
            "- 수원지 수위 하강 → 수면 영역 파랑 (가뭄·누수)\n"
            "- 잡목 성장 → 넓은 영역 옅은 빨강 (식생 관리)"
        )

        st.markdown(
            "**우리 환경의 화면 표시 (Phase 2 완성 시):**\n"
            "1. 좌·우 정사영상 viewer **위에** 반투명 색상 overlay (불투명도 슬라이더)\n"
            "2. **임계치 슬라이더** — ±값 이하 변화는 회색 마스킹 (의미있는 변화만)\n"
            "3. **클릭 시 popup** — 그 지점의 정확한 변화량 (예: `+0.45 m`)\n"
            "4. **통계 카드** — 평균 변화 / 최대 증가·감소 / 변화 부피 (m³)"
        )

    # ── DoD 진행 계획 표 ──
    st.markdown("**진행 단계 (Roadmap)**")
    plan = pd.DataFrame([
        {
            "단계": "0",
            "내용": "정사영상 좌·우 동기화 viewer",
            "필요 조건": "DJI Terra map/{z}/{x}/{y}.png",
            "산출물": "tab34 시뮬레이션 모드",
            "상태": "✅ 완료 (현재)",
        },
        {
            "단계": "1",
            "내용": "같은 site_id 의 2 시점 데이터 확보",
            "필요 조건": "드론 재촬영 + DJI Terra 재 export",
            "산출물": "registry.json 에 2 미션 등록",
            "상태": "⏳ 대기 (예: 2605 송당 2026-06-23경)",
        },
        {
            "단계": "2",
            "내용": "DSM 차분 알고리즘 (rasterio + numpy)",
            "필요 조건": "단계 1 완료 + rasterio 패키지",
            "산출물": "src/drone/diff.py DsmDiffAnalyzer.compute_diff()",
            "상태": "📝 prepared (코드 골격 존재)",
        },
        {
            "단계": "3",
            "내용": "DoD raster → 컬러 PNG (RdBu_r colormap)",
            "필요 조건": "단계 2 완료 + matplotlib",
            "산출물": "derived/dod_<l>_<r>.png + 통계 JSON",
            "상태": "📝 prepared",
        },
        {
            "단계": "4",
            "내용": "diff_viewer.html 에 DoD overlay 통합",
            "필요 조건": "단계 3 완료",
            "산출물": "좌·우 viewer 위 반투명 색상 layer + 불투명도 슬라이더",
            "상태": "📋 설계됨",
        },
        {
            "단계": "5",
            "내용": "임계치 슬라이더 + 클릭 popup + 통계 카드",
            "필요 조건": "단계 4 완료",
            "산출물": "사용자 임계치 조정, 픽셀별 정확한 변화값 표시",
            "상태": "📋 설계됨",
        },
        {
            "단계": "6",
            "내용": "Point Cloud M3C2 (벽면 변화까지 포함)",
            "필요 조건": "Open3D + py4dgeo 패키지 + DJI Terra LAS export",
            "산출물": "3D 점군 변화 시각화 (수직 + 측면)",
            "상태": "🔮 향후 (Phase 2 확장)",
        },
        {
            "단계": "7",
            "내용": "three.js + 3d-tiles-renderer 3D mesh DoD",
            "필요 조건": "단계 6 완료",
            "산출물": "3D 메쉬 표면에 색상 입혀 표시",
            "상태": "🔮 향후 (Phase 3 확장)",
        },
    ])
    st.dataframe(plan, use_container_width=True, hide_index=True)

    st.caption(
        "📌 현재 단계 0 (시뮬레이션 모드). 같은 시설물의 다른 시점 데이터가 추가되면 "
        "단계 1 → 7 순차 진행. 단계 2~5 (DSM 기반) 는 ~1주, 단계 6~7 (3D 기반) 은 ~2주 예상. "
        "자세한 기술 명세는 `docs/DRONE_3D_WORK_REPORT_2026-05-24.md` §5 참조."
    )
