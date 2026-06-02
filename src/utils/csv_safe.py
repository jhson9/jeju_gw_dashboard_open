# ==============================================================================
#  파일명: src/utils/csv_safe.py
#  목적: CSV Formula Injection 방어 공용 헬퍼.
# ------------------------------------------------------------------------------
#  배경:
#    Excel/LibreOffice 등의 표 계산 프로그램은 셀의 첫 문자가
#    `=`, `+`, `-`, `@`, `\t`, `\r` 일 때 그 셀을 수식으로 해석한다.
#    사용자 입력에 `=HYPERLINK("http://evil"...)`, `=cmd|...` 등이
#    포함된 채로 CSV 가 생성·전달되면, 수신자가 그 파일을 Excel 로 열 때
#    원격 호출 / 명령 실행 / 정보 노출이 가능하다 (CWE-1236).
#
#  방어:
#    위험 prefix 로 시작하는 값 앞에 single quote(`'`) 를 붙여
#    Excel 이 텍스트로만 해석하도록 회피한다.
#
#  사용:
#    - 단일 값:     `cleaned = csv_safe_cell(raw)`
#    - DataFrame:  `df_safe = sanitize_dataframe(df)`
#       · object/str dtype 컬럼에만 적용 (숫자/날짜 컬럼은 제외 — 안전 + 성능).
#
#  연혁:
#    - 2026-05-29 신규: src/drone/importer.py 의 inline `_csv_safe` 를
#                       공용으로 추출. tab12 CSV download 에도 적용.
# ==============================================================================
from __future__ import annotations

from typing import Any

import pandas as pd

# Excel/CSV 수식 prefix — 첫 문자가 이들 중 하나면 수식으로 해석된다.
_DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def csv_safe_cell(value: Any) -> Any:
    """Return value with leading `'` if it would be interpreted as a formula.

    - None / NaN / 빈 문자열은 그대로 반환 (수식이 될 수 없음).
    - 위험 prefix 면 `'` 를 앞에 붙여 텍스트로 강제.
    - 그 외엔 원본 그대로 반환.
    """
    if value is None:
        return value
    # NaN(부동소수점) 대응 — pandas/numpy 의 NaN 은 != self.
    try:
        if value != value:  # type: ignore[comparison-overlap]
            return value
    except Exception:
        pass
    s = str(value)
    if not s:
        return value
    if s[0] in _DANGEROUS_PREFIXES:
        return "'" + s
    return value if isinstance(value, str) is False else s


def sanitize_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of *df* with object/string columns made formula-safe.

    숫자·날짜·bool dtype 은 prefix 위험이 없으므로 건드리지 않는다 (성능 + 손상 회피).
    """
    if df is None or df.empty:
        return df
    out = df.copy()
    for col in out.columns:
        # object 와 string dtype 만 처리. 숫자/날짜/bool 은 안전.
        if out[col].dtype == object or pd.api.types.is_string_dtype(out[col]):
            out[col] = out[col].map(csv_safe_cell)
    return out


__all__ = ["csv_safe_cell", "sanitize_dataframe"]
