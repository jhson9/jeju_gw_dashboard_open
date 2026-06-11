# ==============================================================================
#  파일명: tests/test_recenter_quantization.py
#  목적: maybe_recenter_to_selected_well 의 center/zoom quantization 회귀 가드.
#       오류분석·로직·검증 3 에이전트 합의(2026-05-12)로 도입된 round-4 + zoom
#       round-0.5 정책 보호. 이 정책이 깨지면 raw float 가 다시 session_state 에
#       들어가 st_folium 의 round-4 반환값과 mismatch → iframe 흰 깜박임 부활.
#
#  메모리 규칙 보호:
#    - keyword-only 4개 시그니처 (fingerprint_key/center_key/zoom_key/target_zoom)
#    - fingerprint 패턴 (같은 permit 재호출 no-op)
# ==============================================================================
import inspect

import pandas as pd
import streamlit as st


def setup_function(_fn):
    """각 테스트 전에 session_state 의 테스트용 키 정리."""
    for k in (
        "_test_fp", "_test_center", "_test_zoom",
        "_test_fp2", "_test_center2", "_test_zoom2",
    ):
        try:
            del st.session_state[k]
        except (KeyError, AttributeError):
            pass


def _df(permit: str, lat: float, lon: float) -> pd.DataFrame:
    return pd.DataFrame({"permit_no": [permit], "lat": [lat], "lon": [lon]})


def test_signature_keyword_only_four():
    """메모리 규칙: keyword-only 4개 (fingerprint_key/center_key/zoom_key/target_zoom)."""
    from src.dashboard.ag_map_builders import maybe_recenter_to_selected_well

    sig = inspect.signature(maybe_recenter_to_selected_well)
    kw_only = [n for n, p in sig.parameters.items() if p.kind == p.KEYWORD_ONLY]
    assert kw_only == ["fingerprint_key", "center_key", "zoom_key", "target_zoom"]


def test_center_quantized_to_round_4():
    """raw float → round 4 저장. st_folium 의 returned center round-4 와 정합."""
    from src.dashboard.ag_map_builders import maybe_recenter_to_selected_well

    df = _df("P1", lat=33.38231042, lon=126.55418791)
    maybe_recenter_to_selected_well(
        "P1", df,
        fingerprint_key="_test_fp",
        center_key="_test_center",
        zoom_key="_test_zoom",
    )
    saved = st.session_state["_test_center"]
    # 정확히 round 4 결과
    assert saved == (33.3823, 126.5542)


def test_zoom_quantized_to_half_step():
    """target_zoom → round 0.5 단계로 저장 (st_folium zoomSnap=0.5 정합)."""
    from src.dashboard.ag_map_builders import maybe_recenter_to_selected_well

    df = _df("P2", lat=33.4, lon=126.5)
    maybe_recenter_to_selected_well(
        "P2", df,
        fingerprint_key="_test_fp",
        center_key="_test_center",
        zoom_key="_test_zoom",
        target_zoom=12,
    )
    assert st.session_state["_test_zoom"] == 12.0


def test_fingerprint_noop_on_same_permit():
    """같은 permit 으로 재호출 시 no-op — fingerprint 일치 시 session_state 변경 없음."""
    from src.dashboard.ag_map_builders import maybe_recenter_to_selected_well

    df = _df("P1", lat=33.38, lon=126.55)
    maybe_recenter_to_selected_well(
        "P1", df,
        fingerprint_key="_test_fp",
        center_key="_test_center",
        zoom_key="_test_zoom",
    )
    first_center = st.session_state["_test_center"]

    # 다른 lat/lon 같은 permit — fingerprint match → no-op
    df2 = _df("P1", lat=99.99, lon=99.99)
    maybe_recenter_to_selected_well(
        "P1", df2,
        fingerprint_key="_test_fp",
        center_key="_test_center",
        zoom_key="_test_zoom",
    )
    # center 가 첫 호출 값 그대로 유지 (no-op 확인)
    assert st.session_state["_test_center"] == first_center


def test_none_permit_is_noop():
    """sel_permit=None → 아무 것도 하지 않음."""
    from src.dashboard.ag_map_builders import maybe_recenter_to_selected_well

    df = _df("P1", lat=33.38, lon=126.55)
    maybe_recenter_to_selected_well(
        None, df,
        fingerprint_key="_test_fp",
        center_key="_test_center",
        zoom_key="_test_zoom",
    )
    assert "_test_center" not in st.session_state
    assert "_test_zoom" not in st.session_state


def test_missing_permit_in_df_is_noop():
    """df 에 sel_permit 이 없으면 no-op."""
    from src.dashboard.ag_map_builders import maybe_recenter_to_selected_well

    df = _df("P1", lat=33.38, lon=126.55)
    maybe_recenter_to_selected_well(
        "P_NOT_EXIST", df,
        fingerprint_key="_test_fp",
        center_key="_test_center",
        zoom_key="_test_zoom",
    )
    assert "_test_center" not in st.session_state


def test_different_tabs_isolated_fingerprints():
    """3종 fingerprint 키(_search/_usage/_qty)는 독립. 한 탭의 recenter 가 다른 탭 영향 없음."""
    from src.dashboard.ag_map_builders import maybe_recenter_to_selected_well

    df = _df("P1", lat=33.38, lon=126.55)
    # tab6 (검색) recenter
    maybe_recenter_to_selected_well(
        "P1", df,
        fingerprint_key="_test_fp",
        center_key="_test_center",
        zoom_key="_test_zoom",
    )
    # tab7 (이용량) recenter — 별도 키 — 영향 없이 발동해야 함
    maybe_recenter_to_selected_well(
        "P1", df,
        fingerprint_key="_test_fp2",
        center_key="_test_center2",
        zoom_key="_test_zoom2",
    )
    # 양쪽 다 정상 저장
    assert st.session_state["_test_center"] == (33.38, 126.55)
    assert st.session_state["_test_center2"] == (33.38, 126.55)
