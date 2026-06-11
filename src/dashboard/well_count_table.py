# ==============================================================================
#  파일명: src/dashboard/well_count_table.py
#  관정 수 표 — ⑤ 관정 검색 탭 상단의 시·구분별 관정 수 wide-format 표.
#
#  Source 분리: ag_well_helpers.py 1366줄 → 그룹별 분리 1단계 (2026-05-09).
#    - WELL_COUNT_TABLE_STRUCTURE (12행 고정 순서)
#    - compute_well_count_summary (long-format, tab4 데이터 리포트용)
#    - _well_counts_dict (내부 카운트 dict)
#    - render_well_count_table (가로 wide HTML 테이블 직접 렌더)
#
#  호환성: ag_well_helpers.py 가 이 모듈에서 모두 re-export → 기존 호출처
#  (`ag_well_helpers.render_well_count_table(df)` 등) 그대로 동작.
# ==============================================================================
from __future__ import annotations

import pandas as pd
import streamlit as st

import config


# (A) 표 구조: 위치 기반 (서 → 동, 해안선 따라). 12행 고정.
WELL_COUNT_TABLE_STRUCTURE: list[tuple[str, str]] = [
    # 제주시 (북서 → 북동)
    ("제주시",   "한경면"),
    ("제주시",   "한림읍"),
    ("제주시",   "애월읍"),
    ("제주시",   "제주동지역"),
    ("제주시",   "조천읍"),
    ("제주시",   "구좌읍"),
    # 서귀포시 (남서 → 남동)
    ("서귀포시", "대정읍"),
    ("서귀포시", "안덕면"),
    ("서귀포시", "서귀포동지역"),
    ("서귀포시", "남원읍"),
    ("서귀포시", "표선면"),
    ("서귀포시", "성산읍"),
]


def compute_well_count_summary(df: pd.DataFrame) -> pd.DataFrame:
    """시·구분별 관정 수 — 12행 고정 long format + 시 소계 + 총합계.

    카운트는 _well_counts_dict 로 동적 산출.
    (가로 wide format 표는 render_well_count_table 에서 직접 렌더.)
    """
    counts = _well_counts_dict(df)

    rows: list[dict] = []
    prev_si: "str | None" = None
    for si, gubun in WELL_COUNT_TABLE_STRUCTURE:
        # 시 전환 시 직전 시의 소계 행 삽입
        if prev_si is not None and si != prev_si:
            sub = sum(c for (s, _g), c in counts.items() if s == prev_si)
            rows.append({"시": f"{prev_si} 소계", "구분": "", "관정 수": sub})
        rows.append({"시": si, "구분": gubun, "관정 수": counts[(si, gubun)]})
        prev_si = si

    if prev_si is not None:
        sub = sum(c for (s, _g), c in counts.items() if s == prev_si)
        rows.append({"시": f"{prev_si} 소계", "구분": "", "관정 수": sub})

    rows.append({"시": "총합계", "구분": "",
                 "관정 수": int(sum(counts.values()))})
    return pd.DataFrame(rows)


def _well_counts_dict(df: pd.DataFrame) -> dict[tuple[str, str], int]:
    """(시, 구분) → 관정 수 dict.

    매칭 규칙:
      - '동지역' 구분: 해당 시의 관정 중 well_eup 가
          (1) '동'으로 끝나거나 (예: 강정동, 동홍동 — 서귀포시 동지역)
          (2) 비어있음/NaN (예: 제주시 도심 동지역은 well_eup 미기재)
      - 그 외 (읍·면): well_eup 가 정확히 일치
    """
    counts: dict[tuple[str, str], int] = {}
    if df.empty or "well_si" not in df.columns:
        for si, gubun in WELL_COUNT_TABLE_STRUCTURE:
            counts[(si, gubun)] = 0
        return counts

    work = df.copy()
    work["well_si"] = work["well_si"].astype(str).str.strip()
    # NaN 보존을 위해 별도 클린 컬럼 사용 ('nan'/'None' 문자열도 빈값 처리)
    eup_clean = (
        work["well_eup"].astype(str).str.strip()
            .replace({"nan": "", "None": "", "NaN": ""})
    )

    for si, gubun in WELL_COUNT_TABLE_STRUCTURE:
        if gubun.endswith("동지역"):
            m = (work["well_si"] == si) & (
                eup_clean.str.endswith("동", na=False) | (eup_clean == "")
            )
        else:
            m = (work["well_si"] == si) & (eup_clean == gubun)
        counts[(si, gubun)] = int(m.sum())
    return counts


def render_well_count_table(df: pd.DataFrame) -> None:
    """시별로 한 줄 — 읍·면·동지역이 가로(컬럼) 방향으로 펼쳐지는 표.

    Build 3.x:
      - 모든 셀 숫자에 "공" 단위 부착
      - 표의 맨 끝 칸 (extra 컬럼) 추가:
          제주시 행: 「총합계 / 887공」
          서귀포시 행: 「기준년도 / 2025년」
      - 하단 별도 총합계 박스 제거 (표에 통합)
    """
    counts = _well_counts_dict(df)

    jeju_cols = [g for s, g in WELL_COUNT_TABLE_STRUCTURE if s == "제주시"]
    seog_cols = [g for s, g in WELL_COUNT_TABLE_STRUCTURE if s == "서귀포시"]

    jeju_sub = sum(counts[("제주시", g)] for g in jeju_cols)
    seog_sub = sum(counts[("서귀포시", g)] for g in seog_cols)
    grand = jeju_sub + seog_sub

    # 기준연도 — config 의 농업용 관정 사후관리 자료 마지막 연도
    base_year = config.AG_USAGE_YEAR_RANGE[1]

    def _render_one(
        si: str, columns: list[str], subtotal: int,
        extra_label: str, extra_value: str,
    ) -> str:
        # 폭 비율: 시 라벨 14% / 6 읍면 각 ~10.7% / 소계 10% / extra 12% = 100%
        n_cols = len(columns)
        eup_w = (100 - 14 - 10 - 12) / n_cols   # ≈ 10.67% (n_cols=6)
        colgroup = (
            "<colgroup>"
            '<col style="width:14%;">'
            + "".join(f'<col style="width:{eup_w:.4f}%;">' for _ in columns)
            + '<col style="width:10%;">'
            + '<col style="width:12%;">'
            + "</colgroup>"
        )

        # ── 헤더 행: 시 셀 rowspan=2
        thead = ['<thead><tr style="background:var(--color-bg-info);color:var(--color-text-info);">']
        thead.append(
            f'<th rowspan="2" style="padding:6px 10px;text-align:center;'
            f'border:0.5px solid #85b7eb;font-weight:700;font-size:13px;'
            f'background:var(--color-bg-secondary);color:var(--color-text-info);vertical-align:middle;">'
            f'{si}</th>'
        )
        for col in columns:
            thead.append(
                f'<th style="padding:6px 4px;text-align:center;'
                f'border:0.5px solid #85b7eb;font-weight:600;'
                f'white-space:nowrap;">{col}</th>'
            )
        thead.append(
            '<th style="padding:6px 8px;text-align:center;'
            'border:0.5px solid #85b7eb;font-weight:600;'
            'background:#d7e6f5;">소계</th>'
        )
        # extra 헤더 — 제주시는 "총합계", 서귀포시는 "기준년도"
        thead.append(
            f'<th style="padding:6px 8px;text-align:center;'
            f'border:0.5px solid #85b7eb;font-weight:700;'
            f'background:var(--color-text-info);color:#fff;">{extra_label}</th>'
        )
        thead.append("</tr>")

        # ── 데이터 행
        tds = ["<tr>"]
        for col in columns:
            cnt = counts[(si, col)]
            text = "" if cnt == 0 else f"{cnt:,}공"
            tds.append(
                f'<td style="padding:6px 4px;text-align:center;'
                f'border:0.5px solid rgba(26,26,24,0.15);">{text}</td>'
            )
        sub_text = "" if subtotal == 0 else f"{subtotal:,}공"
        tds.append(
            f'<td style="padding:6px 8px;text-align:center;font-weight:700;'
            f'background:var(--color-bg-info);color:var(--color-text-info);'
            f'border:0.5px solid rgba(26,26,24,0.15);">{sub_text}</td>'
        )
        # extra 데이터 — 제주시 행: 887공, 서귀포시 행: 2025년
        tds.append(
            f'<td style="padding:6px 8px;text-align:center;font-weight:700;'
            f'background:var(--color-text-info);color:#fff;'
            f'border:0.5px solid rgba(26,26,24,0.15);">{extra_value}</td>'
        )
        tds.append("</tr></thead>")

        return (
            '<table style="width:100%;border-collapse:collapse;font-size:12px;'
            'table-layout:fixed;'
            'border:0.5px solid rgba(26,26,24,0.15);border-radius:6px;'
            'overflow:hidden;margin-bottom:8px;">'
            + colgroup + "".join(thead) + "".join(tds) + "</table>"
        )

    # 제주시 (위): 끝 칸 = 총합계 / 887공
    grand_text = "" if grand == 0 else f"{grand:,}공"
    st.markdown(
        _render_one("제주시", jeju_cols, jeju_sub,
                    extra_label="총합계", extra_value=grand_text),
        unsafe_allow_html=True,
    )
    # 서귀포시 (아래): 끝 칸 = 기준년도 / 2025년
    st.markdown(
        _render_one("서귀포시", seog_cols, seog_sub,
                    extra_label="기준년도", extra_value=f"{base_year}년"),
        unsafe_allow_html=True,
    )
