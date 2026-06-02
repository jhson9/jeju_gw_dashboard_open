# ==============================================================================
#  파일명: src/dashboard/permit_lookup.py
#  지도 클릭 → permit_no 추출 헬퍼.
#
#  Source 분리: ag_well_helpers.py 1366줄 → 그룹별 분리 2단계 (2026-05-09).
#    - _PERMIT_RE              (PERMIT 정규식 패턴)
#    - parse_clicked_popup     (popup HTML 폴백 추출)
#    - lookup_permit_by_well_id (tooltip 문자열 → permit_no, 1순위 경로)
#
#  호환성: ag_well_helpers.py 가 이 모듈에서 모두 re-export → 기존 호출처
#  (`ag_well_helpers.lookup_permit_by_well_id(...)` 등) 그대로 동작.
#  외부 호출: tab11_ag_search.py, tab12_ag_usage.py, tab13_ag_quality.py 3곳.
# ==============================================================================
from __future__ import annotations

import logging
import re

import pandas as pd
import streamlit as st

from src.analysis import ag_well_loader


_logger = logging.getLogger(__name__)

_PERMIT_RE = re.compile(r"([A-Z]\d{6,})")

# well_id 가 결측·null-like 일 때 dict 캐시 키 충돌 방지용
_NULL_STRS = frozenset({"", "nan", "none", "<na>", "null"})


@st.cache_data(ttl=300, show_spinner=False, max_entries=2)
def _well_id_lookup_data() -> "tuple[dict[str, str], frozenset[str]]":
    """well_id → permit_no 매핑 + 중복 well_id 집합.

    - active_only=False : 비활성 관정 포함 → tab8 의 df_master_full 컨텍스트 호환
    - null-like well_id/permit_no 제외 : "nan" 같은 충돌 키가 dict 진입하지 않도록 차단
    - 중복 well_id 는 dict 에서 완전 제외 + 별도 frozenset 으로 반환 :
      한 well_id 가 두 permit_no 와 매핑되는 row 가 master.csv 에 존재할 때
      (예: F-662, F-663) 첫 행 keep 은 잘못된 permit_no 를 반환할 위험.
      호출처가 popup parse fallback 으로 정확히 식별하도록 위임.
    - ttl=300 : load_master 의 cache_data ttl 과 동기화 → master.csv 5분 갱신 시 함께 invalidate
    """
    df = ag_well_loader.load_master(active_only=False)
    if df.empty or "well_id" not in df.columns or "permit_no" not in df.columns:
        return {}, frozenset()

    well_ids = df["well_id"].astype(str).str.strip()
    permit_nos = df["permit_no"].astype(str).str.strip()

    # well_id 와 permit_no 가 모두 null-like 아닌 row 만 매핑 대상
    mask = (
        ~well_ids.str.lower().isin(_NULL_STRS)
        & ~permit_nos.str.lower().isin(_NULL_STRS)
    )
    well_ids = well_ids[mask]
    permit_nos = permit_nos[mask]

    dup_mask = well_ids.duplicated(keep=False)
    dup_set = frozenset(well_ids[dup_mask].unique())
    if dup_set:
        # 2026-05-25: 콘솔에 관정 번호가 노출되지 않도록 debug 레벨 + 목록 제거.
        # (중복 well_id 처리 동작은 그대로 — tooltip|permit / popup fallback)
        _logger.debug(
            "[permit_lookup] master.csv well_id 중복 %d 건 — dict 매핑 제외, "
            "fallback 처리.", len(dup_set),
        )

    keep = ~well_ids.duplicated(keep=False)  # 중복 well_id 모두 제외
    return dict(zip(well_ids[keep], permit_nos[keep])), dup_set


def _well_id_to_permit_map() -> "dict[str, str]":
    """호환성 wrapper — 외부에서 dict 만 필요한 경우."""
    mapping, _ = _well_id_lookup_data()
    return mapping


def parse_clicked_popup(popup_html: str | None) -> str | None:
    """(폴백) popup HTML 에서 permit_no 추출 — tooltip 방식 실패 시 사용.

    주의: streamlit-folium 0.27.x 는 popup 컨텐츠를 .innerText 형식으로
          반환하는 것으로 보여, popup 안의 <span style='display:none;'>…</span>
          숨김 텍스트가 떨어져 나갈 수 있음. 따라서 신뢰도 낮은 폴백.
    """
    if not popup_html:
        return None
    m = _PERMIT_RE.search(str(popup_html))
    return m.group(1) if m else None


def lookup_permit_by_well_id(
    well_id: str | None,
    df: "pd.DataFrame | None",
) -> str | None:
    """tooltip 문자열에서 permit_no 추출.

    현재 tooltip 은 `well_id` 단독. 다만 well_id 결측 row 의 fallback 으로
    permit_no 가 들어올 수 있고, 구 형식 `{well_id}|{permit_no}` 도 호환.

    분기 순서 (우선순위):
      1) dict 캐시 O(1) 매칭 — 매 클릭의 hot path (Phase 1-A)
      2) df 컬럼 풀스캔 — dict miss 시 보루 (df 인자가 있을 때만)
      3) PERMIT 정규식 직접 매칭 — well_id 결측 row 의 fallback tooltip
      4) `|` split 마지막 토큰의 PERMIT 매칭 — 구 형식 호환
    """
    if not well_id:
        return None
    text = str(well_id).strip()
    if not text:
        return None

    # 새 tooltip 은 `|` 가 없는 well_id 단독. 구 형식 호환을 위해 분리해 둠.
    well_id_clean = text.split("|", 1)[0].strip() if "|" in text else text

    # 중복 well_id 는 정확한 permit 식별 불가 → dict/풀스캔 모두 skip,
    # 호출처 popup parse fallback 으로 위임. (1)·(2) 모두 우회.
    dup_set: "frozenset[str]" = frozenset()
    try:
        mapping, dup_set = _well_id_lookup_data()
    except Exception:  # noqa: BLE001 — 캐시 실패 시 풀스캔으로 폴백
        mapping = {}

    is_ambiguous = well_id_clean in dup_set

    # (1) dict 캐시 — O(1), 1순위 hot path
    if well_id_clean and not is_ambiguous:
        cached = mapping.get(well_id_clean)
        if cached:
            return cached

    # (2) df 풀스캔 — dict miss 시 보루. 중복 well_id 는 skip.
    if (df is not None and not df.empty
            and "well_id" in df.columns and "permit_no" in df.columns
            and well_id_clean and not is_ambiguous):
        match = df[df["well_id"].astype(str).str.strip() == well_id_clean]
        if len(match) >= 1:
            return str(match.iloc[0]["permit_no"])

    # (3) PERMIT 정규식 매칭 — well_id 결측 row 의 fallback tooltip
    m = _PERMIT_RE.search(text)
    if m:
        return m.group(1)

    # (4) `|` split 마지막 토큰 — 구 형식 호환
    if "|" in text:
        last = text.rsplit("|", 1)[-1].strip()
        m = _PERMIT_RE.fullmatch(last)
        if m:
            return m.group(1)

    return None
