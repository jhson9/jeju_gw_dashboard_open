# -*- coding: utf-8 -*-
# =============================================================================
# quit_helper.py — 외부 공개판 안전 NO-OP 버전 (2026-06-01)
#
# 원본은 Streamlit 앱에 "종료" 버튼을 띄워 클릭 시 os._exit(0) 으로 서버 자체를
# 종료. 로컬 단일 사용자 환경에선 편리하지만 외부 공개 (Streamlit Cloud) 에선
# 누구나 클릭해 서버를 다운시킬 수 있어 치명적 보안 위험.
#
# 본 파일은 모든 호출을 no-op 으로 만들어 다음을 보장:
#   * 14개 탭의 `quit_button(...)` 호출 그대로 두어도 화면에 버튼 안 보임
#   * 메인 V3 동기화 시 본 파일만 보존하면 됨 (탭 14개 손대지 않음)
#   * os._exit / _shutdown_and_exit 어디서도 호출되지 않음
# =============================================================================

from typing import Optional


def quit_button(key: str, *, container: Optional[object] = None) -> bool:
    """외부 공개판: 종료 버튼 표시 자체를 비활성화. 항상 False 반환."""
    return False


def maybe_quit() -> None:
    """외부 공개판: shutdown 트리거 비활성화."""
    return None
