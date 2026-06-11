# ==============================================================================
#  파일명: tests/test_theme_tokens.py
#  목적: 디자인 시스템 토큰의 회귀 가드.
#       Phase D #21 + L5 추가에서 dual_zone 패키지의 인라인 hex 14건을
#       theme.COLOR_* 토큰으로 치환. 이 토큰들의 정확한 hex 값이 회귀하면
#       디자인 일관성 깨짐 — skill memory 'jeju-design-system' 정책 보호.
# ==============================================================================


def test_text_color_tokens_exact_hex():
    """텍스트 색상 3종 — 토큰 hex 값 회귀 가드."""
    from src.dashboard import theme

    # Phase D #21 + L5 추가에서 dual_zone 의 #000/#1a1a1a/#222 가 모두
    # COLOR_TEXT_PRIMARY 로 매핑. 이 값이 바뀌면 14곳의 색이 한꺼번에 변경.
    assert theme.COLOR_TEXT_PRIMARY == "#1a1a18"
    assert theme.COLOR_TEXT_SECONDARY == "#5f5e5a"
    assert theme.COLOR_TEXT_TERTIARY == "#7f7f7f"


def test_accent_navy_dual_zone_token():
    """ri_dual_zone 클러스터 외곽선 색 (Phase D #21 에서 #1F3A5F → 토큰)."""
    from src.dashboard import theme

    assert theme.COLOR_ACCENT_NAVY == "#1F3A5F"


def test_info_status_tokens():
    """헤더·상태 표시 색 — tab 제목·badge 등 광범위 사용."""
    from src.dashboard import theme

    assert theme.COLOR_TEXT_INFO == "#185fa5"
    assert theme.COLOR_SUCCESS == "#1d9e75"
    assert theme.COLOR_DANGER == "#e24b4a"


def test_aws_color_map_completeness():
    """AWS 지점 4개 색상 매핑 — tab2/tab9 차트 + KPI 보드 의존."""
    from src.dashboard import theme

    assert set(theme.COLOR_AWS.keys()) == {"제주", "서귀포", "성산", "고산"}
    for name, hex_val in theme.COLOR_AWS.items():
        assert isinstance(hex_val, str)
        assert hex_val.startswith("#") and len(hex_val) == 7, (
            f"{name} 색상 형식 오류: {hex_val}"
        )


def test_region_color_map_completeness():
    """권역 4개 (동/서/남/북) 색상 매핑 — 유역 막대 차트 의존."""
    from src.dashboard import theme

    assert set(theme.COLOR_REGION.keys()) == {"동부", "서부", "남부", "북부"}


def test_palette_accent_indices_stable():
    """PALETTE_ACCENT 인덱스 alias 가 안정 — Plotly literal hex 정리 정책."""
    from src.dashboard import theme

    # COLOR_ACCENT_DARKRED = PALETTE_ACCENT[4], COLOR_ACCENT_BLUE_2 = PALETTE_ACCENT[3]
    assert theme.PALETTE_ACCENT[4] == theme.COLOR_ACCENT_DARKRED
    assert theme.PALETTE_ACCENT[3] == theme.COLOR_ACCENT_BLUE_2


def test_quality_palette_6tier():
    """수질 6단계 팔레트 — tab8 수질 분포 의존."""
    from src.dashboard import theme

    assert len(theme.PALETTE_QUALITY_6TIER) == 6
    # 마지막 단계 = COLOR_QUALITY_MAX alias
    assert theme.PALETTE_QUALITY_6TIER[5] == theme.COLOR_QUALITY_MAX
