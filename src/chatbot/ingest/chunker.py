"""청크 분할 — 법령은 조문(제N조) 단위, 보고서는 길이 기반.

조문 단위 분할이 출처 표시("지하수법 제7조")의 핵심.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from .pdf_loader import (PageText, doc_category, doc_title_from_filename,
                         effective_date, extract_tables, load_pdf)

try:  # 패키지/단독 실행 양쪽 지원
    from ..config import (ARTICLE_MAX_CHARS, ARTICLE_MIN_COUNT,
                          REPORT_CHUNK_CHARS, REPORT_CHUNK_OVERLAP)
except ImportError:  # pragma: no cover
    from src.chatbot.config import (ARTICLE_MAX_CHARS, ARTICLE_MIN_COUNT,
                                    REPORT_CHUNK_CHARS, REPORT_CHUNK_OVERLAP)

# 조문 시작: 줄 처음 "제5조(지하수의 조사)" / "제30조의2(…)"
_ARTICLE_RE = re.compile(r"^(제\d+조(?:의\d+)?)\(([^)]{1,60})\)", re.MULTILINE)
# 항 시작: ①②…⑳
_CLAUSE_RE = re.compile(r"(?=[①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭⑮⑯⑰⑱⑲⑳])")


@dataclass
class Chunk:
    chunk_id: str
    doc_name: str          # 예: 지하수법
    category: str          # 법률/시행령/시행규칙/조례/계획·지침
    article: str           # 예: 제7조(지하수개발ㆍ이용의 허가) / 보고서는 절 제목
    page: int              # 시작 페이지 (1-base)
    eff_date: str          # 시행일자
    source_file: str       # 원본 PDF 파일명
    text: str = field(repr=False, default="")

    @property
    def label(self) -> str:
        return f"{self.doc_name} {self.article}" if self.article else self.doc_name


def _join_pages(pages: list[PageText]) -> tuple[str, list[tuple[int, int]]]:
    """페이지 텍스트 연결 + (문자오프셋, 페이지번호) 매핑."""
    parts, page_map, offset = [], [], 0
    for p in pages:
        page_map.append((offset, p.page_no))
        parts.append(p.text)
        offset += len(p.text) + 1
    return "\n".join(parts), page_map


def _page_at(offset: int, page_map: list[tuple[int, int]]) -> int:
    page = page_map[0][1]
    for off, no in page_map:
        if off <= offset:
            page = no
        else:
            break
    return page


def _strip_toc(full: str) -> int:
    """목차부 건너뛰기: 본문 첫 조문(제1조(목적))의 시작 오프셋 추정."""
    m = re.search(r"^제1조\(목적\)", full, re.MULTILINE)
    return m.start() if m else 0


def _split_long_article(header: str, body: str) -> list[str]:
    """긴 조문을 항(①②) 단위로 묶어 재분할. 각 조각에 조문 머리 유지."""
    clauses = [c for c in _CLAUSE_RE.split(body) if c.strip()]
    pieces, buf = [], ""
    for c in clauses:
        if buf and len(buf) + len(c) > ARTICLE_MAX_CHARS:
            pieces.append(buf)
            buf = ""
        buf += c
    if buf.strip():
        pieces.append(buf)
    # 항 구분이 없는 긴 본문(별표·서식 등)은 길이 기준 강제 분할
    final: list[str] = []
    for p in pieces:
        while len(p) > ARTICLE_MAX_CHARS * 1.5:
            cut = p.rfind("\n", 0, ARTICLE_MAX_CHARS)
            cut = cut if cut > ARTICLE_MAX_CHARS // 2 else ARTICLE_MAX_CHARS
            final.append(p[:cut])
            p = p[cut:]
        final.append(p)
    return [f"{header} {p.strip()}" for p in final if p.strip()]


def chunk_law(doc_name: str, full: str, page_map, meta: dict) -> list[Chunk]:
    """법령형: 조문 단위 분할."""
    body_start = _strip_toc(full)
    matches = list(_ARTICLE_RE.finditer(full, body_start))
    chunks: list[Chunk] = []
    seen: dict[str, int] = {}  # 부칙 등 동일 조문번호 반복 → id 중복 방지
    for i, m in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(full)
        article = f"{m.group(1)}({m.group(2)})"
        text = full[m.end():end].strip()
        page = _page_at(m.start(), page_map)
        texts = (_split_long_article(article, text)
                 if len(text) > ARTICLE_MAX_CHARS else [f"{article} {text}"])
        base_id = f"{meta['source_file']}::{m.group(1)}"
        seen[base_id] = seen.get(base_id, 0) + 1
        if seen[base_id] > 1:  # 두 번째 등장부터 #n 부가
            base_id += f"#{seen[base_id]}"
        for j, t in enumerate(texts):
            suffix = f"-{j+1}" if len(texts) > 1 else ""
            chunks.append(Chunk(
                chunk_id=f"{base_id}{suffix}",
                doc_name=doc_name, article=article, page=page,
                text=t, **{k: meta[k] for k in ("category", "eff_date", "source_file")}))
    return chunks


def chunk_report(doc_name: str, pages: list[PageText], meta: dict) -> list[Chunk]:
    """보고서형: 문단 경계 기준 길이 분할 + 오버랩."""
    full, page_map = _join_pages(pages)
    paras = [p for p in re.split(r"\n\s*\n", full) if p.strip()]
    chunks, buf, buf_off, offset, n = [], "", 0, 0, 0

    def _flush():
        nonlocal n, buf
        n += 1
        chunks.append(Chunk(
            chunk_id=f"{meta['source_file']}::chunk{n:04d}",
            doc_name=doc_name, article=f"p.{_page_at(buf_off, page_map)} 부분",
            page=_page_at(buf_off, page_map), text=buf.strip(),
            **{k: meta[k] for k in ("category", "eff_date", "source_file")}))

    for p in paras:
        # 문단 자체가 청크 한도보다 길면 길이 기준 강제 분할
        while len(p) > REPORT_CHUNK_CHARS * 2:
            cut = p.rfind("\n", 0, REPORT_CHUNK_CHARS)
            cut = cut if cut > REPORT_CHUNK_CHARS // 2 else REPORT_CHUNK_CHARS
            buf += "\n" + p[:cut]
            _flush()
            buf = ""
            p = p[cut:]
            buf_off = offset
        if buf and len(buf) + len(p) > REPORT_CHUNK_CHARS:
            _flush()
            buf = buf[-REPORT_CHUNK_OVERLAP:]  # 오버랩 유지
            buf_off = offset
        buf += "\n" + p
        offset = full.find(p, offset) + len(p)
    if buf.strip():
        _flush()
    return chunks


def chunk_pdf(pdf_path: Path) -> list[Chunk]:
    """PDF 1건 → 청크 목록. 조문이 충분하면 법령형, 아니면 보고서형."""
    pages = load_pdf(pdf_path)
    doc_name = doc_title_from_filename(pdf_path)
    meta = dict(category=doc_category(pdf_path),
                eff_date=effective_date(pdf_path),
                source_file=pdf_path.name)
    full, page_map = _join_pages(pages)
    body = full[_strip_toc(full):]
    n_articles = len(_ARTICLE_RE.findall(body))
    # 법령형 판별: 조문 수 + 밀도(조문당 평균 글자 수).
    # 보고서가 법령을 '인용'한 경우 조문 수는 채우지만 밀도가 매우 낮다
    # (예: 물 재이용 관리계획 보고서 497쪽/조문 10개 → 조문당 4만자).
    dense = n_articles > 0 and (len(body) / n_articles) <= 4000
    if n_articles >= ARTICLE_MIN_COUNT and dense:
        base = chunk_law(doc_name, full, page_map, meta)
    else:
        base = chunk_report(doc_name, pages, meta)
    # 표는 구조 보존 청크로 추가 (별표·기준표 대응, 2026-06-11)
    return base + table_chunks(pdf_path)


def _split_table_md(md: str, max_chars: int = 1800) -> list[str]:
    """긴 마크다운 표를 헤더 유지하며 행 단위 분할."""
    lines = md.splitlines()
    if len(md) <= max_chars or len(lines) < 4:
        return [md]
    header, body = lines[:2], lines[2:]
    parts, buf = [], []
    size = sum(len(s) for s in header)
    for row in body:
        if buf and size + len(row) > max_chars:
            parts.append("\n".join(header + buf))
            buf, size = [], sum(len(s) for s in header)
        buf.append(row)
        size += len(row)
    if buf:
        parts.append("\n".join(header + buf))
    return parts


def table_chunks(pdf_path: Path) -> list[Chunk]:
    """PDF의 표를 구조 보존(마크다운) 청크로 변환. article에 〔표〕 표식."""
    doc_name = doc_title_from_filename(pdf_path)
    meta = dict(category=doc_category(pdf_path),
                eff_date=effective_date(pdf_path),
                source_file=pdf_path.name)
    chunks: list[Chunk] = []
    for n, (page_no, title, md) in enumerate(extract_tables(pdf_path), 1):
        label = title if title else f"p.{page_no} 표"
        for j, part in enumerate(_split_table_md(md), 1):
            suffix = f"-{j}" if "\n" in part and j > 1 else ("" if j == 1 else f"-{j}")
            text = (f"{label}\n{part}") if title else part
            chunks.append(Chunk(
                chunk_id=f"{meta['source_file']}::table{n:03d}{suffix}",
                doc_name=doc_name, article=f"{label} 〔표〕", page=page_no,
                text=text,
                **{k: meta[k] for k in ("category", "eff_date", "source_file")}))
    return chunks
