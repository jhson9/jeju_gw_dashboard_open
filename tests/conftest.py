# ==============================================================================
#  파일명: tests/conftest.py
#  목적: pytest 공통 fixture / sys.path 셋업.
#  V4 권장(2026-05-11): src/analysis/* 단위 테스트 인프라.
# ==============================================================================
import sys
from pathlib import Path

import pytest

_PROJ_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJ_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJ_ROOT))


@pytest.fixture
def proj_root() -> Path:
    return _PROJ_ROOT
