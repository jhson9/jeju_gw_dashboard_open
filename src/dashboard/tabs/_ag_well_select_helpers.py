# ==============================================================================
#  파일명: src/dashboard/tabs/_ag_well_select_helpers.py
#  목적: tab7(이용량) · tab8(수질) 의 "관정 선택 바 + 검색" UI 통합.
#       두 탭이 110줄 거의 동일 코드를 갖고 있었음 (key prefix · placeholder 만
#       다름). 단일 모듈로 통합해 향후 한쪽만 수정되는 drift 위험 제거.
#
#  Source 분리: V1 검증팀 권장(2026-05-11). 외부 호출처(tab7/tab8/_tab13_map)는
#  기존 wrapper 함수 시그니처를 그대로 유지 — wrapper 가 prefix·placeholder 를
#  고정해 본 모듈을 호출하는 shim 패턴.
# ==============================================================================
from __future__ import annotations

import pandas as pd
import streamlit as st

from src.analysis import ag_well_loader
from src.dashboard import ag_well_helpers


_fragment_rerun = ag_well_helpers.fragment_rerun


# 2026-05-17 사용자 요청: 「선택 해제」 버튼 hover tooltip — 10자 이내.
# 길게 설명하기보다 동작만 짧게 (시각 톤 다운과 일관).
_CLEAR_BUTTON_HELP = "선택 관정 해제"


def render_well_selection_bar(
    df_master: pd.DataFrame, selected_permit: str | None,
    *,
    key_prefix: str,
    search_placeholder: str,
    include_search: bool = True,
) -> None:
    """상시 표시되는 「선택 관정 + (옵션) 검색 + 선택 해제」 바.

    Parameters
    ----------
    key_prefix : str
        세션/위젯 키 접두어. tab7 = "usage", tab8 = "qty".
        다음 키들이 prefix 기반으로 구성됨:
          - `{prefix}_selected_permit`        (선택된 관정)
          - `{prefix}_clear_sel`              (선택 해제 버튼 widget key)
          - `{prefix}_well_search`            (검색 input widget key)
          - `_{prefix}_well_search_last`     (같은 키워드 재처리 방지)
    search_placeholder : str
        검색 input 의 placeholder. 탭별 예시 관정명이 달라 분리.
        `include_search=False` 일 때는 무시.
    include_search : bool
        검색 input 칼럼 포함 여부. 2026-05-17 사용자 요청으로 검색 input 을
        지도 헤더 라인으로 분리한 후, 본 바는 「선택 관정 + 선택 해제」만
        남기는 케이스를 위해 도입.
    """
    # 2026-05-17 사용자 요청: 칼럼별 baseline 정렬 — vertical_alignment="center"
    # 로 통일하여 margin-top hack 제거. 「선택 관정 표시」 와 「선택 해제」 버튼
    # 이 같은 높이로 정렬됨.
    if include_search:
        h_left, h_search, h_right = st.columns(
            [4, 2.2, 1], vertical_alignment="center",
        )
    else:
        h_left, h_right = st.columns(
            [6.2, 1], vertical_alignment="center",
        )

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
                f'<span style="font-weight:400;color:var(--color-text-secondary);font-size:16px;">'
                f'({addr} · {selected_permit})</span>'
            )
        else:
            # include_search=False 인 경우 안내문구는 「검색창」 대신 「위 검색창」
            # 표현이 적절하지만, 두 모드에서 공통 사용을 위해 일반화된 표현 유지.
            inner = (
                '선택 관정: '
                '<span style="font-weight:400;color:#7a7a76;font-size:16px;">'
                '(미선택 — 지도 마커 클릭 또는 검색창에 관정명 입력)</span>'
            )
        st.markdown(
            f'<div class="subsection-title" style="color:var(--color-text-info);'
            f'padding:10px 0 4px;border-top:1px solid rgba(26,26,24,0.15);'
            f'margin-top:10px;">{inner}</div>',
            unsafe_allow_html=True,
        )

    if include_search:
        with h_search:
            # margin-top hack 제거 — vertical_alignment="center" 가 baseline 정렬 담당.
            render_well_search_input(
                df_master,
                key_prefix=key_prefix,
                placeholder=search_placeholder,
            )

    with h_right:
        # 시각 톤 다운 — type="secondary" (기본 외곽선 + 보조 배경).
        # 2026-05-17 수정: tertiary 는 외곽선 없어 발견성 너무 낮다는 사용자
        # 피드백 → secondary 로 변경. primary 만큼 강조되지 않으면서 시각적
        # 윤곽은 유지. use_container_width 미사용으로 폭은 자연 폭.
        if selected_permit and st.button(
            "선택 해제",
            key=f"{key_prefix}_clear_sel",
            type="secondary",
            help=_CLEAR_BUTTON_HELP,
        ):
            st.session_state.pop(f"{key_prefix}_selected_permit", None)
            _fragment_rerun()


def render_map_header_with_search(
    df_master: pd.DataFrame,
    *,
    key_prefix: str,
    search_placeholder: str,
    title_html: str,
) -> None:
    """지도 헤더 라인용 — [제목 좌측] + [검색 input 우측] 한 줄 레이아웃.

    2026-05-17 사용자 요청: 지도 위 헤더 줄에 검색창을 배치해 화면 위쪽에서
    바로 관정명 입력이 가능하도록. tab6/7/9 (display) 가 동일 패턴 사용.

    Parameters
    ----------
    title_html : str
        제목 영역 HTML. subsection-title 클래스 wrapper 까지 포함된 완성 마크업.
        예: '<p class="subsection-title" style="margin:6px 0;">관정 검색 / 선택</p>'
    key_prefix, search_placeholder : str
        `render_well_search_input` 에 위임. 탭별로 다른 키/플레이스홀더.
    """
    # 2026-05-17 사용자 요청: 제목과 검색 input 의 높이 차이 제거 — 같은
    # 라인에서 끝나도록 vertical_alignment="bottom" 적용 (margin-top hack 폐기).
    h_title, h_search = st.columns(
        [3, 2], vertical_alignment="bottom",
    )
    with h_title:
        st.markdown(title_html, unsafe_allow_html=True)
    with h_search:
        render_well_search_input(
            df_master,
            key_prefix=key_prefix,
            placeholder=search_placeholder,
        )


def render_well_search_input(
    df_master: pd.DataFrame,
    *,
    key_prefix: str,
    placeholder: str,
) -> None:
    """관정명 직접 검색 — Enter 시 매칭 관정을 선택하고 지도 중심 이동.

    매칭 우선순위:
      ① well_id 정확 일치 (대소문자 무시) → 즉시 선택
      ② well_id 부분 일치 1건 → 선택
      ③ 부분 일치 다수 → 안내 메시지 (사용자가 더 정확히 입력)
      ④ 일치 없음 → 경고
    """
    search_key = f"{key_prefix}_well_search"
    last_key = f"_{key_prefix}_well_search_last"
    permit_key = f"{key_prefix}_selected_permit"

    keyword = st.text_input(
        "관정명 검색",
        value="",
        key=search_key,
        placeholder=placeholder,
        label_visibility="collapsed",
    )

    # 같은 키워드로 rerun 마다 재처리 방지
    last_kw = st.session_state.get(last_key, "")
    if keyword == last_kw:
        return
    st.session_state[last_key] = keyword

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

    st.session_state[permit_key] = permit_no
    # 2026-05-25: "지도 이동" 은 검색 선택에서만. 검색으로 고른 관정은 화면 밖일
    # 수 있어 그 관정 중심으로 이동시키되, 지도 마커를 직접 클릭한 경우엔
    # (이미 화면에 보이므로) 이동시키지 않아 뷰가 튀지 않게 한다.
    # 이 플래그를 지도 render 가 읽어 1회만 재중심한다(tab12·tab13).
    st.session_state[f"_{key_prefix}_center_request"] = permit_no
    # zoom·center 는 maybe_recenter_to_selected_well 이 다음 build 직전에
    # fingerprint 패턴으로 zoom 12 + 그 관정 중심으로 처리.
    _fragment_rerun()
