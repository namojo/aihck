"""PDF → Document(pages, sections, tables). LLM을 쓰지 않는 결정적 단계."""
from __future__ import annotations

import logging
import re
from collections import Counter
from pathlib import Path

import pdfplumber

from .schemas import Document, DocumentMeta, Page, Section, Table

log = logging.getLogger("rfpharness.parse")

# 제목 패턴: (정규식, 레벨). 새 양식을 만나면 여기에만 추가한다.
HEADING_PATTERNS: list[tuple[re.Pattern[str], int]] = [
    (re.compile(r"^(제\s*\d+\s*장|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]|[IVX]{1,4})[.\s]\s*(\S.{1,60})$"), 1),
    (re.compile(r"^(\d{1,2})\.\s+(\S.{1,60})$"), 2),
    (re.compile(r"^([가-힣])\.\s+(\S.{1,60})$"), 3),
    (re.compile(r"^(\d{1,2})\)\s+(\S.{1,60})$"), 4),
]
SECTION_LEVEL_MAX = 2  # 이 레벨까지만 섹션으로 자른다. 그 아래 제목은 본문에 남는다.
ID_RE = re.compile(r"^[A-Z]{3}-\d{3}$")


def _clean_cell(c: object) -> str:
    if c is None:
        return ""
    return re.sub(r"\s+", " ", str(c)).strip()


def _is_heading(line: str) -> tuple[int, str] | None:
    s = line.strip()
    if not s or len(s) > 70:
        return None
    for pat, level in HEADING_PATTERNS:
        m = pat.match(s)
        if m:
            title = m.group(2).strip()
            # 숫자만 있거나 표 셀처럼 보이는 줄 제외
            if re.fullmatch(r"[\d.\s%]+", title):
                return None
            return level, s
    return None


def _strip_repeated_lines(pages_text: list[str]) -> tuple[list[str], list[str]]:
    """머리말·꼬리말처럼 여러 페이지에 반복되는 짧은 줄을 제거한다."""
    if len(pages_text) < 3:
        return pages_text, []
    counter: Counter[str] = Counter()
    for t in pages_text:
        for ln in {l.strip() for l in t.splitlines() if l.strip()}:
            if len(ln) <= 40:
                counter[ln] += 1
    threshold = max(3, len(pages_text) // 2)
    repeated = {ln for ln, n in counter.items() if n >= threshold}
    repeated |= {ln for ln in counter if re.fullmatch(r"[-–—\s]*\d{1,3}[-–—\s]*", ln)}
    out = []
    for t in pages_text:
        out.append("\n".join(l for l in t.splitlines() if l.strip() not in repeated))
    return out, sorted(repeated)


def _inherit_merged_cells(header: list[str], rows: list[list[str]]) -> list[list[str]]:
    """병합 셀(빈 문자열)은 위 셀을 상속한다. 단, 고유번호 열은 상속하지 않는다."""
    id_cols = {i for i, h in enumerate(header) if "고유번호" in h or h.upper() in {"ID", "번호"}}
    prev: list[str] = []
    out: list[list[str]] = []
    for r in rows:
        r = list(r) + [""] * (len(header) - len(r))
        if prev:
            for i, c in enumerate(r):
                if c == "" and i not in id_cols and i < len(prev) and not any(r):
                    r[i] = prev[i]
        # 부분 병합: 첫 열이 비어 있고 나머지에 값이 있으면 첫 열만 상속(평가 항목 표의 흔한 형태)
        if prev and r and r[0] == "" and 0 not in id_cols and any(r[1:]):
            r[0] = prev[0]
        out.append(r)
        prev = r
    return out


def parse_pdf(path: str | Path) -> Document:
    path = Path(path)
    pages_text: list[str] = []
    prose_texts: list[str] = []
    tables: list[Table] = []
    table_tops: dict[str, float] = {}
    heading_pos: list[tuple[int, float, str]] = []  # (page, top, heading line)
    with pdfplumber.open(str(path)) as pdf:
        for pno, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            pages_text.append(text)
            try:
                for ln in page.extract_text_lines():
                    h = _is_heading(ln["text"])
                    if h and h[0] <= SECTION_LEVEL_MAX:
                        heading_pos.append((pno, float(ln["top"]), h[1]))
            except Exception:  # noqa: BLE001
                pass
            # 선이 있는 표만 쓴다. 텍스트 전략 폴백은 본문 문단을 가짜 표로 만들어 요구사항을 오염시킨다.
            found = page.find_tables() or []
            for ti, ft in enumerate(found, start=1):
                raw = ft.extract() or []
                cleaned = [[_clean_cell(c) for c in row] for row in raw if row and any(_clean_cell(c) for c in row)]
                if len(cleaned) < 2:
                    continue
                header = cleaned[0]
                rows = _inherit_merged_cells(header, cleaned[1:])
                tid = f"T-{pno:03d}-{ti}"
                tables.append(Table(table_id=tid, page=pno, header=header, rows=rows))
                table_tops[tid] = float(ft.bbox[1])
            # 표 영역을 뺀 본문. 표 셀 텍스트가 문장에 섞여 가짜 요구사항이 되는 것을 막는다.
            try:
                outside = page
                for ft in found:
                    x0, top, x1, bottom = ft.bbox
                    outside = outside.outside_bbox((x0 - 1, top - 1, x1 + 1, bottom + 1))
                prose_texts.append(outside.extract_text() or "")
            except Exception:  # noqa: BLE001
                prose_texts.append(text if not found else "")

    pages_text, stripped = _strip_repeated_lines(pages_text)
    prose_texts = ["\n".join(l for l in t.splitlines() if l.strip() not in set(stripped)) for t in prose_texts]
    pages = [Page(number=i + 1, text=t, prose_text=prose_texts[i] if i < len(prose_texts) else None) for i, t in enumerate(pages_text)]
    avg_chars = sum(len(p.text) for p in pages) / max(1, len(pages))
    needs_ocr = avg_chars < 50

    # 섹션 분할
    sections: list[Section] = []
    cur: dict | None = None
    all_headings: list[tuple[int, int, str]] = []  # (page, level, heading)
    for p in pages:
        for line in p.text.splitlines():
            h = _is_heading(line)
            if h and h[0] <= SECTION_LEVEL_MAX:
                if cur:
                    cur["page_end"] = p.number if cur["lines"] and cur["last_page"] == p.number else cur["last_page"]
                    sections.append(_finish(cur, len(sections)))
                cur = {"heading": h[1], "level": h[0], "page_start": p.number, "last_page": p.number, "lines": []}
                all_headings.append((p.number, h[0], h[1]))
                continue
            if cur is None:
                cur = {"heading": "(머리글)", "level": 1, "page_start": p.number, "last_page": p.number, "lines": []}
            cur["lines"].append(line)
            cur["last_page"] = p.number
    if cur:
        cur["page_end"] = cur["last_page"]
        sections.append(_finish(cur, len(sections)))

    # 표를 섹션에 배정: 같은 페이지에서 표보다 위에 있는 마지막 제목의 섹션. 없으면 그 페이지에 걸친 첫 섹션.
    heading_to_section: dict[tuple[int, str], Section] = {}
    for sec in sections:
        heading_to_section.setdefault((sec.page_start, sec.heading), sec)
    for t in tables:
        top = table_tops.get(t.table_id, 0.0)
        above = [(pg, tp, h) for (pg, tp, h) in heading_pos if pg == t.page and tp < top]
        chosen: Section | None = None
        if above:
            pg, tp, h = max(above, key=lambda x: x[1])
            chosen = heading_to_section.get((pg, h))
        if chosen is None:
            spanning = [s for s in sections if s.page_start <= t.page <= s.page_end]
            chosen = spanning[0] if spanning else (sections[-1] if sections else None)
        if chosen is None:
            continue
        chosen.table_ids.append(t.table_id)
        if t.caption is None:
            t.caption = chosen.heading

    title = next((l for l in stripped if "제안요청서" in l or "제안 요청서" in l), None)
    for line in (pages[0].text.splitlines() if pages and title is None else []):
        if "제안요청서" in line or "제안 요청서" in line:
            title = line.strip()
            break
    if title is not None and title.strip() in ("제안요청서", "제안 요청서") and pages:
        prev = [l.strip() for l in pages[0].text.splitlines() if l.strip()]
        i = prev.index(title.strip()) if title.strip() in prev else -1
        if i > 0:
            title = f"{prev[i - 1]} {title.strip()}"
    if title is None and pages:
        title = next((l.strip() for l in pages[0].text.splitlines() if l.strip()), None)

    meta = DocumentMeta(source_path=str(path), title=title, page_count=len(pages), needs_ocr=needs_ocr, stripped_lines=stripped)
    log.info("parsed %s: %d pages, %d sections, %d tables, needs_ocr=%s", path.name, len(pages), len(sections), len(tables), needs_ocr)
    return Document(meta=meta, pages=pages, sections=sections, tables=tables)


def _finish(cur: dict, idx: int) -> Section:
    return Section(
        section_id=f"S-{idx + 1:03d}",
        heading=cur["heading"],
        level=cur["level"],
        page_start=cur["page_start"],
        page_end=cur.get("page_end", cur["last_page"]),
        text="\n".join(cur["lines"]).strip(),
    )


def table_to_markdown(t: Table) -> str:
    lines = ["| " + " | ".join(t.header) + " |", "|" + "---|" * len(t.header)]
    for r in t.rows:
        lines.append("| " + " | ".join(r) + " |")
    return "\n".join(lines)


def parent_heading(doc: Document, sec: Section) -> str:
    """해당 섹션을 포함하는 가장 가까운 상위(레벨 1) 제목."""
    parent = sec.heading
    for s in doc.sections:
        if s.level == 1:
            parent = s.heading
        if s.section_id == sec.section_id:
            break
    return parent


def section_for_page(doc: Document, page: int) -> str | None:
    for s in doc.sections:
        if s.page_start <= page <= s.page_end:
            return s.heading
    return None
