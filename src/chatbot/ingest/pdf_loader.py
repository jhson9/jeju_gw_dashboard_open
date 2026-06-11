"""PDF 텍스트 추출 (페이지 번호 보존, 국가법령정보센터 머리글 제거)."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import fitz  # PyMuPDF

# 국가법령정보센터 PDF 머리글: "법제처   3   국가법령정보센터"
_HEADER_RE = re.compile(r"^법제처\s+\d+\s+국가법령정보센터\s*$")
# 자치법규정보시스템 머리글 변형도 방어
_HEADER_RE2 = re.compile(r"^(자치법규정보시스템|국가법령정보센터)\s*$")


@dataclass
class PageText:
    page_no: int  # 1-base
    text: str


def _clean_page(raw: str, doc_title: str) -> str:
    """머리글·문서제목 반복행 제거."""
    lines = []
    for i, line in enumerate(raw.splitlines()):
        s = line.strip()
        if _HEADER_RE.match(s) or _HEADER_RE2.match(s):
            continue
        # 머리글 바로 다음 줄의 문서 제목 반복 제거 (페이지 상단 2줄 이내)
        if i <= 2 and s and s == doc_title:
            continue
        lines.append(line)
    return "\n".join(lines)


def doc_title_from_filename(pdf_path: Path) -> str:
    """파일명에서 문서 제목 추출: '지하수법(법률)(제21065호)(20251001).pdf' → '지하수법'"""
    stem = pdf_path.stem
    m = re.match(r"^(.*?)\((법률|대통령령|기후에너지환경부령|환경부령|행정안전부령|제\d+호)", stem)
    return (m.group(1) if m else stem).strip()


def doc_category(pdf_path: Path) -> str:
    """문서 구분: 법률/시행령/시행규칙/조례/계획·지침."""
    name = pdf_path.stem
    if "시행규칙" in name:
        return "시행규칙"
    if "시행령" in name:
        return "시행령"
    if "조례" in name:
        return "조례"
    if "(법률)" in name or "특별법" in name:
        return "법률"
    return "계획·지침"


def effective_date(pdf_path: Path) -> str:
    """파일명 끝 (YYYYMMDD) → 시행일자 문자열."""
    m = re.findall(r"\((\d{8})\)", pdf_path.stem)
    if m:
        d = m[-1]
        return f"{d[:4]}-{d[4:6]}-{d[6:]}"
    return ""


def load_pdf(pdf_path: Path) -> list[PageText]:
    """PDF → 페이지별 정제 텍스트."""
    title = doc_title_from_filename(pdf_path)
    pages: list[PageText] = []
    with fitz.open(pdf_path) as doc:
        for i, page in enumerate(doc):
            txt = _clean_page(page.get_text("text"), title)
            pages.append(PageText(page_no=i + 1, text=txt))
    return pages


def extract_tables(pdf_path: Path) -> list[tuple[int, str, str]]:
    """PDF에서 표 추출 → [(페이지, 제목, 마크다운)].

    별표·기준표가 한 단어씩 세로로 깨지는 문제 해결용 (2026-06-11).
    3행 2열 이상, 내용이 충분한 표만 채택 (서식·빈 표 제외).
    """
    out: list[tuple[int, str, str]] = []
    with fitz.open(pdf_path) as doc:
        for i, page in enumerate(doc):
            try:
                tabs = page.find_tables()
            except Exception:
                continue
            for t in tabs.tables:
                if t.row_count < 3 or t.col_count < 2:
                    continue
                try:
                    md = t.to_markdown()
                except Exception:
                    continue
                if len(md) < 150:  # 빈 칸 위주 서식 제외
                    continue
                # 표 위쪽 텍스트에서 제목 추정 ("별표 N" 우선)
                x0, y0, x1, y1 = t.bbox
                above = page.get_text(
                    "text", clip=(0, max(0, y0 - 90), page.rect.width, y0))
                lines = [s.strip() for s in above.splitlines() if s.strip()]
                title = ""
                for line in lines:
                    if "별표" in line or "별지" in line:
                        title = line[:60]
                        break
                if not title and lines:
                    title = lines[-1][:60]
                out.append((i + 1, title, md))
    return out
