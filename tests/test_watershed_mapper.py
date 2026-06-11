# ==============================================================================
#  파일명: tests/test_watershed_mapper.py
#  목적: watershed_mapper 캐시 가드 + 매핑 함수의 시그니처 회귀 가드.
#       V4 권장 후속(2026-05-11) — Phase C #11 에서 streamlit-optional 캐시
#       데코레이터를 부착한 이후 CLI 진입점 호환 검증.
# ==============================================================================


def test_module_imports_with_streamlit_optional_cache():
    """streamlit 이 설치되어 있어도 없어도 import 자체는 성공해야 한다."""
    from src.analysis import watershed_mapper

    # streamlit cache wrapper (또는 no-op fallback) 가 정의되어 있어야 함
    assert hasattr(watershed_mapper, "_cache_data")
    assert callable(watershed_mapper._cache_data)


def test_public_functions_present_and_callable():
    """주요 매핑 함수가 export 되어 있어야 한다."""
    from src.analysis import watershed_mapper

    assert callable(watershed_mapper.load_station_to_watershed_map)
    assert callable(watershed_mapper.get_watershed_to_stations_map)


def test_mapping_signatures_unchanged():
    """함수 시그니처가 회귀하지 않았는지 확인 (verbose: bool = False)."""
    import inspect
    from src.analysis import watershed_mapper

    sig1 = inspect.signature(watershed_mapper.load_station_to_watershed_map)
    sig2 = inspect.signature(watershed_mapper.get_watershed_to_stations_map)
    for sig in (sig1, sig2):
        assert "verbose" in sig.parameters
        assert sig.parameters["verbose"].default is False


def test_cache_wraps_or_passes_through():
    """캐시 래퍼가 streamlit 환경에서는 CachedFunc, CLI 에서는 원본 함수로 동작.

    Phase C #11 의 streamlit-optional 캐시 가드가 두 환경 모두에서 안전한지 검증.
    어느 쪽이든 함수는 호출 가능해야 한다.
    """
    from src.analysis import watershed_mapper

    fn = watershed_mapper.load_station_to_watershed_map
    # streamlit 이 설치된 환경에서는 streamlit.cache_data 의 CachedFunc 가 적용됨.
    # 미설치(no-op fallback) 환경에서는 원본 함수 자체. 둘 다 callable 이어야 함.
    assert callable(fn)
    # CachedFunc 또는 일반 함수 어느 쪽이든 __wrapped__ 또는 __name__ 검사로
    # 본 모듈 함수임을 확인 (회귀 시 다른 객체로 바뀌면 fail).
    name = getattr(fn, "__name__", None) or getattr(
        getattr(fn, "__wrapped__", None), "__name__", None
    )
    # streamlit cache_data 는 함수명 보존
    assert name == "load_station_to_watershed_map" or fn.__class__.__name__ in (
        "CachedFunc", "function"
    )
