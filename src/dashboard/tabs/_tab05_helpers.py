# ==============================================================================
#  파일명: src/dashboard/tabs/_tab05_helpers.py
#  ④ 공간 분석 탭 — 포맷 헬퍼 (색상 diff, 기간 라벨, baseline 각주)
#
#  Source 분리: tab05_map.py 1055줄 → 그룹별 분리 1단계 (2026-05-09).
#    - _diff_html              : 양수/음수 색상 표시 HTML (theme.COLOR_SUCCESS/DANGER)
#    - _smart_period_labels    : 12개월 표 컬럼 라벨 (연도 변경 칸만 'YY년 M월')
#    - _baseline_footnote      : baseline 연도 그룹 각주 텍스트
#
#  외부 사용처: tab05_map.py 내부 전용 (외부 호출 0건). underscore prefix 로
#  module-private 표기.
# ==============================================================================
from __future__ import annotations

import pandas as pd

from src.dashboard import theme


def _diff_html(d: "float | None", unit: str = "", decimals: int = 1) -> str:
    if d is None:
        return "–"
    c = theme.COLOR_SUCCESS if d >= 0 else theme.COLOR_DANGER
    sg = "+" if d >= 0 else ""
    return f'<span style="color:{c};font-weight:500;">{sg}{d:.{decimals}f}{unit}</span>'


# ─── 기간 라벨 헬퍼 ─────────────────────────────────────────
def _smart_period_labels(table: pd.DataFrame) -> list[str]:
    """첫 칸과 연도가 바뀌는 칸은 'YY년 M월', 그 외에는 'M월' 만 반환.

    예) [25년 5월, 6월, 7월, ..., 12월, 26년 1월, 2월, 3월, 4월]
    """
    out, prev_y = [], None
    for _, r in table.iterrows():
        y, m = int(r["연월"][:4]), int(r["연월"][5:7])
        if prev_y is None or y != prev_y:
            out.append(f"{str(y)[2:]}년 {m}월")
        else:
            out.append(f"{m}월")
        prev_y = y
    return out


def _baseline_footnote(table: pd.DataFrame, n_baseline: int,
                       label: str = "과거 N년 평균") -> str:
    """12개월 표를 (year-group) 단위로 묶고, 각 그룹의 baseline 연도 범위를 텍스트로.

    출력 예: "과거 3년 평균 : 5월 ~ 12월 : 22년 ~ 24년 해당 월평균 수위
                          | 1월 ~ 4월 : 23년 ~ 25년 해당 월평균 수위"
    """
    if table.empty:
        return ""
    label = label.replace("N년", f"{n_baseline}년")

    # (year, month) 순서대로 그룹화
    groups: list[tuple[int, list[int]]] = []
    cur_y, cur_ms = None, []
    for _, r in table.iterrows():
        y, m = int(r["연월"][:4]), int(r["연월"][5:7])
        if cur_y is None or y == cur_y:
            cur_y = y
            cur_ms.append(m)
        else:
            groups.append((cur_y, cur_ms))
            cur_y, cur_ms = y, [m]
    if cur_y is not None:
        groups.append((cur_y, cur_ms))

    parts = []
    for y, ms in groups:
        m_first, m_last = ms[0], ms[-1]
        bl_first = (y - n_baseline) % 100
        bl_last = (y - 1) % 100
        if m_first == m_last:
            month_str = f"{m_first}월"
        else:
            month_str = f"{m_first}월 ~ {m_last}월"
        parts.append(
            f"{month_str} : {bl_first:02d}년 ~ {bl_last:02d}년 해당 월평균 수위"
        )
    return f"{label} : " + " &nbsp;|&nbsp; ".join(parts)
