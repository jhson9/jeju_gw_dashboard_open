# ==============================================================================
#  파일명: src/dashboard/ag_filters.py
#  농업용 관정 공통 필터 위젯 + 정렬 상수 (시·읍면·리 cascading dropdown).
#
#  Source 분리: ag_well_helpers.py → 그룹별 분리 6단계 (마지막) (2026-05-09).
#    [상수]
#      - SI_DROPDOWN_LIST           : ['제주시', '서귀포시']
#      - EUP_DROPDOWN_ORDER         : 시별 읍면 공식 통계 순서
#      - RI_BY_LOCATION             : (시, 읍면) → 리 정적 매핑 (성능 개선)
#    [함수]
#      - _eup_clean                 : well_eup 컬럼 클린업 헬퍼
#      - cascading_location_filters : 시 → 읍면동 → 리 단계적 selectbox 3개
#      - apply_cascading_filters    : cascading 결과를 master DataFrame 에 적용
#
#  호환성: ag_well_helpers.py 가 이 모듈에서 모두 re-export → 기존 호출처
#  (`ag_well_helpers.cascading_location_filters(...)` 등) 그대로 동작.
#  외부 호출:
#    - cascading_location_filters : tab11_ag_search.py, tab12_ag_usage.py, tab13_ag_quality.py
#    - apply_cascading_filters    : tab11_ag_search.py, tab12_ag_usage.py × 2, tab13_ag_quality.py
# ==============================================================================
from __future__ import annotations

import logging

import pandas as pd
import streamlit as st


_logger = logging.getLogger(__name__)

# 한 리 명이 여러 시·읍에 존재하는 동명 리 — sel 에 시·읍 정보가 없으면
# 양쪽 모두 매칭되어 의도 외 cross-시 결과가 나옴 (예: "고성리" → 제주시
# 애월읍 + 서귀포시 성산읍). RI_BY_LOCATION 기준 4건.
_AMBIGUOUS_RI: "frozenset[str]" = frozenset({"고성리", "상모리", "수산리", "세화리"})


# ============================================================================
#  ■ 정렬 상수 — 드롭다운 (공식 통계 순서)
# ----------------------------------------------------------------------------
#  표(위치 기반, 서→동) 정의는 well_count_table.WELL_COUNT_TABLE_STRUCTURE 참조.
#  여기는 셀렉트박스·다중선택 옵션 순서에 쓰는 (B) 드롭다운 순서.
# ============================================================================

# (B) 드롭다운: 공식 통계 순서
SI_DROPDOWN_LIST: list[str] = ["제주시", "서귀포시"]
EUP_DROPDOWN_ORDER: dict[str, list[str]] = {
    "제주시":   ["한림읍", "애월읍", "구좌읍", "조천읍", "한경면", "동지역"],
    "서귀포시": ["대정읍", "남원읍", "성산읍", "안덕면", "표선면", "동지역"],
}

# (C) 정적 (시 → 읍면동 → 리) 매핑 — master CSV 9년치 누적에서 한 번만
# 추출하여 코드에 박음. cascading_location_filters 가 리 dropdown 옵션을
# 매번 df.groupby 로 동적 추출하던 비용을 제거 (사용자 요청 2026-05-09).
# master 변경 시 갱신 절차: scripts/extract_ri_mapping.py 실행 결과로 교체.
RI_BY_LOCATION: dict[str, dict[str, list[str]]] = {
    "제주시": {
        "한림읍": [
            "귀덕리", "금능리", "금악리", "대림리", "동명리", "명월리",
            "상대리", "상명리", "월령리", "월림리", "한림리", "협재리",
        ],
        "애월읍": [
            "고성리", "곽지리", "광령1리", "광령리", "구엄리", "금성리",
            "납읍리", "봉성리", "상가리", "상귀리", "소길리", "수산리",
            "신엄리", "애월리", "어음리", "유수암리", "장전리", "하가리",
            "하귀1리", "하귀2리",
        ],
        "구좌읍": [
            "김녕리", "덕천리", "동복리", "상도리", "세화리", "송당리",
            "월정리", "종달리", "평대리", "한동리", "행원리",
        ],
        "조천읍": [
            "대흘리", "북촌리", "선흘리", "신촌리", "와산리", "와흘리",
            "조천리", "함덕리",
        ],
        "한경면": [
            "고산리", "금등리", "낙천리", "두모리", "신창리", "용수리",
            "저지리", "조수리", "청수리", "판포리",
        ],
        # 동지역은 master 에 well_ri 데이터가 없어 비어있음 (의도)
        "동지역": [],
    },
    "서귀포시": {
        "대정읍": [
            "구억리", "동일리", "무릉리", "보성리", "상모리", "신도리",
            "신평리", "안성리", "영락리", "인성리", "일과리", "하모리",
        ],
        "남원읍": [
            "남원리", "수망리", "신례리", "신흥리", "위미리", "의귀리",
            "태흥리", "하례", "하례리", "한남리",
        ],
        "성산읍": [
            "고성리", "난산리", "삼달리", "수산리", "시흥리", "신산리",
            "신풍리", "오조리", "온평리",
        ],
        "안덕면": [
            "감산리", "광평리", "덕수리", "동광리", "사계리", "상모리",
            "상창리", "상천리", "서광리", "창천리", "화순리",
        ],
        "표선면": [
            "가시리", "성읍리", "세화리", "토산리", "표선리", "하천리",
        ],
        "동지역": [],
    },
}


def _eup_clean(s: pd.Series) -> pd.Series:
    """well_eup 클린업: NaN/공백/'nan'/'None' → 빈 문자열."""
    return (
        s.astype(str).str.strip()
         .replace({"nan": "", "None": "", "NaN": "", "<NA>": ""})
    )


def cascading_location_filters(
    df: pd.DataFrame,
    key_prefix: str = "loc",
    si_label: str = "시",
) -> dict:
    """시 → 읍면동 → 리 의 단계적(cascading) 드롭다운 3 개.

    옵션 정렬 규칙 (드롭다운):
      - 시:   항상 ['전체', '제주시', '서귀포시'] (데이터 유무 무관)
      - 읍면: EUP_DROPDOWN_ORDER 의 공식 통계 순서
              제주시:  한림읍·애월읍·구좌읍·조천읍·한경면·동지역
              서귀포시:대정읍·남원읍·성산읍·안덕면·표선면·동지역
      - 리:   해당 (시, 읍면) 에 속한 리들을 가나다 순

    Parameters
    ----------
    si_label : str
        시 selectbox 의 라벨. 탭별로 '시' / '시 구분' 등 다른 라벨이 필요할 때 지정.

    Returns
    -------
    {'well_si': str|None, 'well_eup': str|None, 'well_ri': str|None}
        '전체' 또는 미선택은 None. '동지역' 은 그대로 문자열로 반환되며
        apply_cascading_filters 에서 '동' 끝나거나 빈 well_eup 으로 매칭.
    """
    work = df.copy() if not df.empty else df

    c1, c2, c3 = st.columns(3)

    # ── 1) 시 (항상 고정 옵션)
    with c1:
        si_opts = ["전체"] + SI_DROPDOWN_LIST
        si_sel = st.selectbox(si_label, si_opts, key=f"{key_prefix}_si")

    # ── 2) 읍/면/동 (시에 따라)
    with c2:
        if si_sel == "전체":
            eup_opts = ["전체"]
        else:
            eup_opts = ["전체"] + EUP_DROPDOWN_ORDER.get(si_sel, [])
        # 시 변경 시 기존 읍 선택이 옵션에 없으면 자동 리셋
        cur = st.session_state.get(f"{key_prefix}_eup", "전체")
        if cur not in eup_opts:
            st.session_state[f"{key_prefix}_eup"] = "전체"
        eup_sel = st.selectbox("읍/면/동", eup_opts, key=f"{key_prefix}_eup")

    # ── 3) 리 (정적 RI_BY_LOCATION 매핑에서 즉시 lookup — 사용자 요청
    #     2026-05-09: 매번 df.groupby 로 추출하지 말고 미리 정리된 코드를
    #     쓰자). master 변경 시 RI_BY_LOCATION 만 갱신하면 됨.
    if si_sel != "전체" and eup_sel != "전체":
        ri_list = RI_BY_LOCATION.get(si_sel, {}).get(eup_sel, [])
    elif si_sel != "전체":
        # 시만 선택, 읍면 전체 → 그 시의 모든 리 (중복 제거 + 정렬)
        seen: set = set()
        ri_list = []
        for eup_ris in RI_BY_LOCATION.get(si_sel, {}).values():
            for ri in eup_ris:
                if ri not in seen:
                    seen.add(ri)
                    ri_list.append(ri)
        ri_list.sort()
    else:
        ri_list = []
    ri_opts = ["전체"] + ri_list

    with c3:
        cur = st.session_state.get(f"{key_prefix}_ri", "전체")
        if cur not in ri_opts:
            st.session_state[f"{key_prefix}_ri"] = "전체"
        ri_sel = st.selectbox("리", ri_opts, key=f"{key_prefix}_ri")

    return {
        "well_si":  None if si_sel  == "전체" else si_sel,
        "well_eup": None if eup_sel == "전체" else eup_sel,
        "well_ri":  None if ri_sel  == "전체" else ri_sel,
    }


def apply_cascading_filters(df: pd.DataFrame, sel: dict) -> pd.DataFrame:
    """cascading_location_filters 의 결과를 master DataFrame 에 적용.

    '동지역' 은 well_eup 이 '동'으로 끝나거나 비어있는 행을 모두 매칭.
    """
    out = df.copy()

    si = sel.get("well_si")
    if si and "well_si" in out.columns:
        out = out[out["well_si"].astype(str).str.strip() == si]

    eup = sel.get("well_eup")
    if eup and "well_eup" in out.columns:
        eup_c = _eup_clean(out["well_eup"])
        if eup == "동지역":
            out = out[eup_c.str.endswith("동", na=False) | (eup_c == "")]
        else:
            out = out[eup_c == eup]

    ri = sel.get("well_ri")
    if ri and "well_ri" in out.columns:
        # 동명 리 가드 — 시·읍 미지정 채 단독 매칭은 cross-시 결과를 만들 수 있음.
        # cascading_location_filters dropdown 흐름에서는 항상 si 가 채워지므로
        # 정상 경로에서는 발동 안 함. session_state 잔존·외부 sel 조립 시 경고.
        if ri in _AMBIGUOUS_RI and not si and not eup:
            _logger.warning(
                "[ag_filters] 동명 리 '%s' 가 시·읍 미선택 채 단독 매칭됨 — "
                "양쪽 시의 row 가 모두 포함됨. cascading dropdown 정상 경로면 "
                "이 경고는 발생하지 않음.", ri,
            )
        out = out[out["well_ri"].astype(str).str.strip() == ri]

    return out
