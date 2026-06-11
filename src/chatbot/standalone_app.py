"""51. 지하수 챗봇 — 단독 실행 Streamlit 앱 (Tab51 통합 전 검증용).

실행 (프로젝트 루트에서):
    streamlit run src/chatbot/standalone_app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

st.set_page_config(page_title="51. 지하수 챗봇", page_icon="💧", layout="wide")

# 대시보드와 동일한 디자인 체계 적용 (실패 시 챗봇 자체 폴백 CSS 사용)
try:
    from src.dashboard import theme
    theme.apply_theme()
except Exception:
    pass

from src.chatbot.render import render_chatbot  # noqa: E402

render_chatbot()
