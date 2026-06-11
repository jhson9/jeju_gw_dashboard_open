# ==============================================================================
#  파일명: tests/test_gwlevel_day_parser.py
#  목적: Phase C #12 의 parquet 통합 캐시 + parquet 우선 로더 회귀 가드.
#       - GWLEVEL_DAY_PARQUET 경로 노출
#       - latest_day_date_from_parquet (tab99_admin 1130→150ms 단축의 핵심)
#       - load_station_day 의 CSV 폴백 안전성 (parquet 없는 환경에서도 동작)
#       - build_day_parquet API 시그니처
#  실측 가치(2026-05-12): parquet 우선 경로 회귀 시 tab99_admin 진입 비용
#  복원(1130ms) — 사용자 가시 영향 매우 큼.
# ==============================================================================
import inspect
from pathlib import Path


def test_module_exports_parquet_api():
    """Phase C #12 의 신규 공개 API 가 모두 export 되어 있는지."""
    from src.collectors import gwlevel_day_parser as gw

    assert hasattr(gw, "GWLEVEL_DAY_PARQUET")
    assert hasattr(gw, "build_day_parquet")
    assert hasattr(gw, "latest_day_date_from_parquet")
    assert hasattr(gw, "load_station_day")
    assert hasattr(gw, "list_day_stations")


def test_parquet_path_under_gwlevel_dir():
    """parquet 캐시 경로가 data/GWlevel/ 하위로 정해져 있는지 (메모리 위치 안정)."""
    from src.collectors import gwlevel_day_parser as gw

    path = gw.GWLEVEL_DAY_PARQUET
    assert isinstance(path, Path)
    # by_station_day 의 부모 = data/GWlevel/ 로 통일
    assert path.parent.name == "GWlevel", (
        f"parquet 경로 예상과 다름: {path}"
    )
    assert path.suffix == ".parquet"


def test_build_day_parquet_signature():
    """ETL 함수 시그니처 — verbose:bool=True, Path 반환."""
    from src.collectors import gwlevel_day_parser as gw

    sig = inspect.signature(gw.build_day_parquet)
    assert "verbose" in sig.parameters
    assert sig.parameters["verbose"].default is True


def test_latest_day_date_returns_none_when_parquet_missing():
    """parquet 미생성 환경에서 None 반환 (예외 던지지 않음).

    tab99_admin._latest_day_csv_date 의 폴백 분기 안전성 보장 — None 받으면
    CSV 스캔으로 fallback. raise 면 dashboard 전체가 죽음.
    """
    from src.collectors import gwlevel_day_parser as gw

    # parquet 경로가 임시로 존재하지 않는 곳을 가리키게 monkeypatch
    original = gw.GWLEVEL_DAY_PARQUET
    try:
        gw.GWLEVEL_DAY_PARQUET = Path("/__nonexistent__/never_exists.parquet")
        result = gw.latest_day_date_from_parquet()
        assert result is None, (
            f"parquet 미존재 시 None 반환해야 함. 실제: {result!r}"
        )
    finally:
        gw.GWLEVEL_DAY_PARQUET = original


def test_load_station_day_csv_fallback_when_parquet_missing():
    """parquet 미존재 시 CSV 폴백 정상 동작 (load_station_day 의 핵심 안전성)."""
    from src.collectors import gwlevel_day_parser as gw
    import pandas as pd

    original = gw.GWLEVEL_DAY_PARQUET
    try:
        gw.GWLEVEL_DAY_PARQUET = Path("/__nonexistent__/never_exists.parquet")
        # 존재 안 하는 station — 빈 DataFrame 반환 (raise X)
        df = gw.load_station_day("__NONEXISTENT_STATION__")
        assert isinstance(df, pd.DataFrame)
        assert df.empty
        # 스키마는 유지
        assert list(df.columns) == ["관측소명", "날짜", "EL"]
    finally:
        gw.GWLEVEL_DAY_PARQUET = original


def test_load_station_day_signature_unchanged():
    """tab04_map / _tab04_station 호출처 시그니처 보호 (station:str → DataFrame)."""
    from src.collectors import gwlevel_day_parser as gw

    sig = inspect.signature(gw.load_station_day)
    assert list(sig.parameters.keys()) == ["station"]
    assert sig.parameters["station"].annotation == str
