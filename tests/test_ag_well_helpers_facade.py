# ==============================================================================
#  파일명: tests/test_ag_well_helpers_facade.py
#  목적: ag_well_helpers 의 re-export facade 회귀 가드.
#       이 모듈은 ag_filters / year_slider / well_card / ag_map_builders /
#       permit_lookup / well_count_table 6개 모듈을 일괄 re-export. 호출처
#       tab6/7/8/10 이 모두 `ag_well_helpers.X` 형태로 접근. 1개라도 누락되면
#       AttributeError 로 탭 진입 실패.
#
#  메모리 규칙 보호:
#    - fragment_rerun() 인자 없이 호출
#    - maybe_recenter_to_selected_well keyword-only 4개
# ==============================================================================
import inspect


def test_fragment_rerun_exists_and_callable():
    """fragment_rerun 함수 export + 인자 없이 호출 가능 (메모리 규칙)."""
    from src.dashboard import ag_well_helpers

    assert hasattr(ag_well_helpers, "fragment_rerun")
    fn = ag_well_helpers.fragment_rerun
    assert callable(fn)
    sig = inspect.signature(fn)
    # 인자가 있다면 default 가 있어 인자 없이 호출 가능해야 함
    required_params = [
        p for p in sig.parameters.values()
        if p.default is inspect.Parameter.empty
        and p.kind not in (p.VAR_POSITIONAL, p.VAR_KEYWORD)
    ]
    assert len(required_params) == 0, (
        f"fragment_rerun 은 인자 없이 호출 가능해야 함 — required: {required_params}"
    )


def test_maybe_recenter_to_selected_well_re_exported():
    """ag_map_builders.maybe_recenter_to_selected_well 가 facade 통해 접근 가능."""
    from src.dashboard import ag_well_helpers

    assert hasattr(ag_well_helpers, "maybe_recenter_to_selected_well")
    fn = ag_well_helpers.maybe_recenter_to_selected_well
    # 메모리 규칙: keyword-only 4개
    sig = inspect.signature(fn)
    kw_only = [n for n, p in sig.parameters.items() if p.kind == p.KEYWORD_ONLY]
    assert kw_only == [
        "fingerprint_key", "center_key", "zoom_key", "target_zoom"
    ]


def test_permit_lookup_re_exported():
    """permit_lookup 의 2개 함수 + 정규식 export."""
    from src.dashboard import ag_well_helpers

    assert hasattr(ag_well_helpers, "lookup_permit_by_well_id")
    assert hasattr(ag_well_helpers, "parse_clicked_popup")
    assert callable(ag_well_helpers.lookup_permit_by_well_id)
    assert callable(ag_well_helpers.parse_clicked_popup)


def test_ag_filters_re_exported():
    """tab6/7/8 의 cascading 위치 필터 헬퍼 export."""
    from src.dashboard import ag_well_helpers

    # cascading_location_filters 가 가장 핵심 — tab6 의 검색 필터
    assert hasattr(ag_well_helpers, "cascading_location_filters")


def test_year_slider_re_exported():
    """year_slider 위젯 export — tab7/tab8 의 분석연도 슬라이더."""
    from src.dashboard import ag_well_helpers

    assert hasattr(ag_well_helpers, "year_slider")
    assert callable(ag_well_helpers.year_slider)


def test_map_builders_re_exported():
    """build_search_map / build_usage_map / build_quality_map 등 빌더 export."""
    from src.dashboard import ag_well_helpers

    # tab6 검색 지도 빌더
    assert hasattr(ag_well_helpers, "build_search_map")
    assert callable(ag_well_helpers.build_search_map)


def test_well_card_re_exported():
    """관정 카드 렌더 함수 export."""
    from src.dashboard import ag_well_helpers

    # render_well_card 가 가장 핵심
    candidates = [n for n in dir(ag_well_helpers) if "well_card" in n.lower()
                  or "render_well" in n.lower()]
    assert len(candidates) > 0, "well_card 관련 함수 re-export 누락"
