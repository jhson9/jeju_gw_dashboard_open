# ==============================================================================
#  파일명: src/dashboard/quit_helper.py
#  모듈: 공용 Quit 버튼 헬퍼 — fragment 호환
# ------------------------------------------------------------------------------
#  문제 (2026-05-25 발견):
#    @st.fragment 안에서 Quit 버튼 클릭 → session_state["_quit_requested"]=True
#    set 만 하면 fragment-scoped rerun 만 발생. app.py module-level 의 quit 체크
#    (`if st.session_state.get("_quit_requested"): _shutdown_and_exit()`) 는
#    fragment rerun 이라 실행 안 됨 → Quit 무작동.
#
#  영향 받는 탭 (11 개): tab11~13, tab21~23, tab31~35.
#  (Quit 버튼이 있는 @st.fragment 탭 — tab02/04/05 는 fragment 지만 Quit 버튼
#   없어 무관. tab99_admin 은 non-fragment 라 st.rerun() 만으로 작동.)
#
#  해결:
#    Quit 클릭 시 session_state 만 set 하지 말고 **st.rerun(scope="app")** 으로
#    명시적 전체 페이지 rerun 트리거 → app.py module-level quit 체크 실행.
#    scope 인자 미지원 환경 (예: 미래 streamlit 변경) 대비 try/except 폴백.
#
#  사용:
#    from src.dashboard.quit_helper import quit_button
#    quit_button("quit_in_tabXX", container=col)   # container 옵션
#    # 또는
#    if quit_button("quit_in_tabXX"):   # bool 리턴도 가능
#        pass
# ==============================================================================
from __future__ import annotations

import streamlit as st


def quit_button(key: str, *, container=None) -> bool:
    """Fragment 호환 Quit 버튼.

    @st.fragment 안에서 호출해도 정상적으로 전역 shutdown 트리거.

    Args:
        key:       streamlit widget key (탭마다 unique 해야)
        container: st.columns 결과의 한 컬럼 등 (None 이면 현재 컨텍스트)

    Returns:
        클릭 여부 (True/False). 보통 호출자가 무시.
    """
    target = container if container is not None else st
    clicked = target.button("⏹ Quit", use_container_width=True, key=key)
    if clicked:
        st.session_state["_quit_requested"] = True
        # 핵심: fragment 안에서도 전체 페이지 rerun 강제 → app.py module-level
        # quit 체크 실행 → _shutdown_and_exit() 호출.
        try:
            st.rerun(scope="app")
        except (TypeError, AttributeError):
            # scope 인자 미지원 환경 (1.37 미만 또는 미래 변경) 폴백.
            st.rerun()
    return clicked
