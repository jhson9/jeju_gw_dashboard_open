# ==============================================================================
#  파일명: src/dashboard/well_card_pdf.py  —  Build 2.0
#  모듈: 관정카드 PDF 뷰어 (⑤ 관정 검색 탭, tab11_ag_search 우측 컬럼)
# ------------------------------------------------------------------------------
#  Build 2.0 (2026-05-15): streamlit 의 /app/static/ 1GB hard limit 우회.
#    - 기존: data_well_card/*.pdf 를 src/dashboard/static/well_card/ 로 hard link
#            복제 (1.3GB) → streamlit static serving 자동 비활성 → 흰 화면 빈발
#    - 신규: src/dashboard/pdf_server.py (port 8766 데몬 스레드) 가 직접 서빙
#            → static 폴더 무관, 미래 자료 무제한 확장 가능
#    - 변경된 패턴: junction/hard link 동기화 함수들(_ensure_pdf_links 등) 폐기
#                   URL prefix: /app/static/well_card → pdf_server URL
#
#  기능 요약:
#   - data_well_card/index.json 을 mtime 캐시로 로드 → well_id ↔ {year:filename}
#   - 자료 있는 연도만 "새 탭" 링크 그리드로 노출 (자료 없는 해는 미노출)
#   - 클릭 = <a target="_blank"> → streamlit rerun 0회, 즉시 새 탭 오픈
#   - URL 안전성: urllib.parse.quote 로 한글·언더스코어 등 인코딩
#   - 보안: pdf_server 의 화이트리스트 prefix + path traversal 차단으로 보호.
#     data_*/ 폴더의 .csv, .json 등은 노출되지 않음 (확장자 .pdf only).
#
#  운영 메모:
#   - data_well_card/{새연도}/ 폴더가 추가되어도 pdf_server 가 PdfDataSource
#     기반으로 자동 인식 (streamlit 재시작 불요).
#   - index.json 변경 시 mtime 기반 캐시가 자동 갱신.
#   - 미래 자료 종류 추가: pdf_server.DATA_SOURCES 에 PdfDataSource 1개만 등록.
# ==============================================================================

from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import quote

import streamlit as st

from src.dashboard import pdf_server, theme
from src.dashboard.permit_lookup import lookup_permit_by_well_id


# ── 경로 상수 ────────────────────────────────────────────────────────────────
# __file__ = src/dashboard/well_card_pdf.py → parents[2] = 프로젝트 루트
PROJECT_ROOT     = Path(__file__).resolve().parents[2]
import config
PDF_DATA_DIR     = config.WELL_CARD_DIR
DRILLING_PDF_DIR = config.DRILLING_LOG_DIR
INDEX_PATH       = PDF_DATA_DIR / "index.json"

# URL 베이스 — pdf_server (port 8766) 의 화이트리스트 prefix.
# DATA_SOURCES dict 를 단일 진실 원천으로 사용해 URL/디스크 경로 동기 유지.
WELL_CARD_URL_BASE = pdf_server.DATA_SOURCES["well_card"].url_base
DRILLING_URL_BASE  = pdf_server.DATA_SOURCES["drilling_log"].url_base


# Build 2.0: hard link / junction 동기화 함수들은 모두 폐기.
# 삭제된 항목: _is_reparse_point, _ensure_pdf_links, _ensure_pdf_links_cached,
#              _pdf_dir_fingerprint, ensure_pdf_static_setup, STATIC_PDF_DIR,
#              STATIC_DRILLING_PDF_DIR, DRILLING_STATIC_SUBDIR, APP_DIR
# 대체: pdf_server.py 가 data_well_card/, data_drilling_log/ 를 직접 서빙.
# 사이즈 부담 0 (hard link 1.3GB 복제본 불필요).


# ── index.json 로딩 (mtime 캐시) ────────────────────────────────────────────
@st.cache_data(show_spinner=False)
def _load_index_cached(mtime: float) -> dict:
    """index.json 본문을 mtime 키로 캐시. 파일 변경 시 자동 invalidate."""
    try:
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _load_index() -> dict:
    """디스크의 index.json 을 mtime 캐시로 로드."""
    if not INDEX_PATH.exists():
        return {}
    try:
        return _load_index_cached(INDEX_PATH.stat().st_mtime)
    except OSError:
        return {}


def _filename_contains_token(filename: str, token: str) -> bool:
    normalized_filename = filename.lower()
    normalized_token = token.strip().lower()
    if not normalized_token:
        return False
    # exact token 경계 매칭: D-001 이 D-0010 에 부분 일치하지 않도록.
    return bool(re.search(
        rf"(?:^|[^A-Za-z0-9]){re.escape(normalized_token)}(?:[^A-Za-z0-9]|$)",
        normalized_filename,
    ))


def available_pdf_years(well_id: str | None) -> list[tuple[int, str]]:
    """주어진 well_id 의 (year, filename) 리스트 — 최신 연도가 앞.

    index.json 에 등록되어 있지만 실제 PDF 파일이 누락된 경우(렌더 시점
    Path.is_file() == False) 는 제외한다. 사용자가 "있는 해만 노출" 을
    선택했으므로 결과 표시 정책에 직접 반영.
    """
    if not well_id:
        return []
    wid = str(well_id).strip()
    if not wid:
        return []
    idx = _load_index()
    entry = idx.get(wid)
    if not entry:
        return []
    files = entry.get("files") or {}
    out: list[tuple[int, str]] = []
    for year_str, fname in files.items():
        try:
            year = int(year_str)
        except (TypeError, ValueError):
            continue
        if not fname:
            continue
        if not (PDF_DATA_DIR / str(year) / fname).is_file():
            continue
        out.append((year, fname))
    out.sort(key=lambda t: t[0], reverse=True)
    return out


def available_drilling_pdfs(well_id: str | None) -> list[tuple[str, str]]:
    """data_drilling_log 의 well_id/permit 기반 PDF 문서 리스트."""
    if not well_id:
        return []
    keys = [k.strip() for k in {str(well_id).strip()} if k.strip()]
    permit = lookup_permit_by_well_id(well_id, None)
    if permit and permit not in keys:
        keys.append(permit.strip())
    if not keys or not DRILLING_PDF_DIR.is_dir():
        return []

    out: list[tuple[str, str]] = []
    for pdf in DRILLING_PDF_DIR.rglob("*.pdf"):
        if not pdf.is_file():
            continue
        name = pdf.name
        if any(_filename_contains_token(name, key) for key in keys):
            rel = pdf.relative_to(DRILLING_PDF_DIR).as_posix()
            out.append((name, rel))
    out.sort(key=lambda t: t[0].lower())
    return out


# ── 렌더러 ──────────────────────────────────────────────────────────────────
def render_well_card_pdf_box(well_id: str | None) -> None:
    """결과 표 우측 컬럼용 컴팩트 PDF 카드 박스.

    상태별 표시:
      - well_id 미선택  → "관정을 선택하면 …" 안내
      - 매칭/파일 없음  → "등록된 PDF 카드가 없습니다"
      - 자료 있음       → 연도 chip 그리드, 클릭 = 새 탭

    Build 2.0: 정적 동기화(ensure_pdf_static_setup) 불필요. pdf_server 가
    data_well_card/, data_drilling_log/ 를 직접 서빙하므로 호출자 책임은
    pdf_server.start_once() 1회 (app.py 진입점에서 실행).
    """
    title_html = (
        f'<div style="font-size:15px;font-weight:600;'
        f'color:{theme.COLOR_TEXT_INFO};'
        f'border-bottom:0.5px solid {theme.COLOR_BORDER_INFO};'
        f'padding-bottom:3px;margin-bottom:6px;">📄 관정카드 PDF</div>'
    )

    if not well_id:
        st.markdown(
            title_html
            + f'<div style="font-size:14px;color:{theme.COLOR_TEXT_TERTIARY};'
            + 'line-height:1.6;">관정을 선택하면 연도별 카드가 여기에 표시됩니다.</div>',
            unsafe_allow_html=True,
        )
        return

    years = available_pdf_years(well_id)
    docs = available_drilling_pdfs(well_id)
    if not years and not docs:
        st.markdown(
            title_html
            + f'<div style="font-size:14px;color:{theme.COLOR_TEXT_TERTIARY};'
            + f'line-height:1.6;"><b>{well_id}</b> 에 등록된 PDF 카드가 없습니다.</div>',
            unsafe_allow_html=True,
        )
        return

    # 연도 chip 그리드 — 좁은 컬럼에서도 자연 줄바꿈, 클릭 시 새 탭 오픈.
    # rel="noopener noreferrer" 로 reverse tabnabbing 차단.
    chips: list[str] = []
    for year, fname in years:
        href = f"{WELL_CARD_URL_BASE}/{year}/{quote(fname, safe='')}"
        chips.append(
            f'<a href="{href}" target="_blank" rel="noopener noreferrer" '
            f'style="display:inline-block;min-width:80px;text-align:center;'
            f'padding:4px 10px;margin:2px 4px 2px 0;'
            f'background:{theme.COLOR_BG_INFO};color:{theme.COLOR_TEXT_INFO};'
            f'border:0.5px solid {theme.COLOR_BORDER_INFO};border-radius:4px;'
            f'font-size:14px;font-weight:600;text-decoration:none;">{year}</a>'
        )

    # well_card 미등록 관정 (예: D-008) — chips 가 빈 리스트인데 docs 가 있어
    # 위 line 180 의 안내 메시지를 건너뛴 경우. "관정카드 PDF :" 라벨만 그려지면
    # 사용자가 "표시 안 됨" 으로 혼란 → "등록 없음" 안내 chip 1개 표시.
    # drilling 줄과 시각적 정렬 유지 (같은 height/padding/margin).
    if not chips:
        chips.append(
            f'<span style="display:inline-block;min-width:80px;text-align:center;'
            f'padding:4px 10px;margin:2px 4px 2px 0;'
            f'background:{theme.COLOR_BG_SECONDARY};'
            f'color:{theme.COLOR_TEXT_TERTIARY};'
            f'border:0.5px solid {theme.COLOR_BG_SECONDARY};border-radius:4px;'
            f'font-size:14px;">등록 없음</span>'
        )

    doc_chips: list[str] = []
    for name, rel_path in docs:
        href = f"{DRILLING_URL_BASE}/{quote(rel_path, safe='/')}"
        # 사용자 요청 (2026-05-16): chip 라벨에서 ".pdf" 확장자 제거 (예: "D-156")
        display_name = name[:-4] if name.lower().endswith(".pdf") else name
        label = display_name if len(display_name) <= 20 else display_name[:17] + "..."
        doc_chips.append(
            f'<a href="{href}" target="_blank" rel="noopener noreferrer" '
            f'style="display:inline-block;min-width:80px;text-align:center;'
            f'padding:4px 10px;margin:2px 4px 2px 0;'
            f'background:{theme.COLOR_BG_INFO};color:{theme.COLOR_TEXT_INFO};'
            f'border:0.5px solid {theme.COLOR_BORDER_INFO};border-radius:4px;'
            f'font-size:14px;font-weight:600;text-decoration:none;">{label}</a>'
        )

    # 사용자 요청 (2026-05-16): well_card chip 과 drilling_log chip 을 한 줄에 +
    # 지질주상도 그룹을 한 줄의 우측 끝으로 정렬 (margin-left:auto). doc_chips
    # 없으면 우측 그룹 자체 숨김. flex-wrap 으로 좁은 컬럼 자동 줄바꿈.
    inline_title_pdf = (
        f'<span style="font-size:15px;font-weight:600;'
        f'color:{theme.COLOR_TEXT_INFO};margin-right:8px;'
        f'white-space:nowrap;">📄 관정카드 PDF&nbsp;&nbsp;:&nbsp;&nbsp;</span>'
    )
    # margin-left:auto 가 우측 끝 정렬의 핵심. 좌측 그룹과 우측 그룹 사이
    # 가용 공간을 모두 흡수해 우측 그룹을 컨테이너 끝으로 밀어냄.
    right_group = (
        f'<div style="margin-left:auto;display:flex;flex-wrap:wrap;'
        f'align-items:center;">'
        f'<span style="font-size:15px;font-weight:600;'
        f'color:{theme.COLOR_TEXT_INFO};margin-right:8px;'
        f'white-space:nowrap;">📄 지질주상도&nbsp;&nbsp;:&nbsp;&nbsp;</span>'
        + "".join(doc_chips)
        + "</div>"
    ) if doc_chips else ""

    html = (
        f'<div style="display:flex;flex-wrap:wrap;align-items:center;'
        f'border-bottom:0.5px solid {theme.COLOR_BORDER_INFO};'
        f'padding-bottom:3px;margin-bottom:6px;">'
        + inline_title_pdf + "".join(chips)
        + right_group
        + "</div>"
    )

    st.markdown(html, unsafe_allow_html=True)
