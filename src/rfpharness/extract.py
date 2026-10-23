"""요구사항 추출: 섹션·표 → Requirement[]. LLM(구조화 출력) 또는 mock(결정적 규칙)."""
from __future__ import annotations

import logging
import re

from .llm import LLM, load_prompt
from .parse import _is_heading, parent_heading, table_to_markdown
from .schemas import CATEGORY_LABELS, Document, ExtractionResult, Requirement, Section, Table

log = logging.getLogger("rfpharness.extract")

CHUNK_CHARS = 6000
ID_RE = re.compile(r"\b([A-Z]{3})-(\d{3})\b")
MUST_RE = re.compile(r"(하여야\s*한다|해야\s*한다|이어야\s*한다|되어야\s*한다|필수|반드시|제출하여야|포함하여야|이상이어야|이내여야|하여야\s*함|해야\s*함)")
SHOULD_RE = re.compile(r"(권장|바람직|권고)")
MAY_RE = re.compile(r"(할\s*수\s*있다|선택적|선택\s*사항)")
PROSE_REQ_RE = re.compile(r"(하여야\s*한다|해야\s*한다|이어야\s*한다|되어야\s*한다|제출하여야\s*한다|포함하여야\s*한다|구축하여야\s*한다|제공하여야\s*한다)")
KEYWORD_CATEGORY: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"보안|암호|접근\s*통제|취약점|개인정보"), "SER"),
    (re.compile(r"응답\s*시간|동시\s*(접속|사용자)|TPS|처리량|성능"), "PER"),
    (re.compile(r"데이터\s*(이관|전환|정제|표준)|DB|데이터베이스"), "DAR"),
    (re.compile(r"연계|인터페이스|API|EAI"), "INR"),
    (re.compile(r"테스트|시험"), "TER"),
    (re.compile(r"교육|매뉴얼|하자\s*보수|유지\s*보수|기술\s*지원|이전"), "PSR"),
    (re.compile(r"일정|보고|회의|산출물|방법론|품질\s*보증|위험\s*관리|착수|검수"), "PMR"),
    (re.compile(r"품질|가용성|신뢰성|사용성"), "QUR"),
    (re.compile(r"서버|스토리지|네트워크|장비|클라우드|HW|하드웨어"), "SIR"),
    (re.compile(r"준수|표준|법령|지침|제약|제안서"), "COR"),
]


def _obligation(text: str) -> str:
    if MUST_RE.search(text):
        return "must"
    if MAY_RE.search(text):
        return "may"
    if SHOULD_RE.search(text):
        return "should"
    return "must" if re.search(r"한다[.。]?$", text.strip()) else "should"


def _guess_category(text: str, default: str = "SFR") -> str:
    for pat, cat in KEYWORD_CATEGORY:
        if pat.search(text):
            return cat
    return default


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s)


def _quote_found(doc: Document, req: Requirement, section: Section | None) -> bool:
    q = _norm(req.quote)[:60]
    if not q:
        return False
    pages = [req.page]
    if section:
        pages += list(range(section.page_start, section.page_end + 1))
    for p in pages:
        if q in _norm(doc.page_text(p)):
            return True
    # 표 셀은 페이지 텍스트에서 열이 섞여 나오므로 셀 단위로도 확인한다
    for t in doc.tables:
        if t.page in pages:
            for row in [t.header] + t.rows:
                for c in row:
                    if q in _norm(c):
                        return True
    return False


# ----------------------------------------------------------------------
def _chunks_for_section(doc: Document, sec: Section) -> list[tuple[str, list[Table]]]:
    """섹션 텍스트를 6,000자 이하로 자르고 표는 통째로 붙인다."""
    tables = [t for t in doc.tables if t.table_id in sec.table_ids]
    # 페이지 표시를 넣기 위해 페이지별 텍스트를 섹션 범위 안에서 모은다
    parts: list[str] = []
    for p in range(sec.page_start, sec.page_end + 1):
        page = next((pg for pg in doc.pages if pg.number == p), None)
        ptext = (page.prose_text if page and page.prose_text is not None else doc.page_text(p)) if page else ""
        if ptext.strip():
            parts.append(f"[p.{p}]\n{ptext}")
    text = "\n".join(parts)
    chunks: list[tuple[str, list[Table]]] = []
    buf = ""
    for para in text.split("\n"):
        if len(buf) + len(para) > CHUNK_CHARS and buf:
            chunks.append((buf, []))
            buf = ""
        buf += para + "\n"
    if buf.strip():
        chunks.append((buf, []))
    # 표는 페이지가 속한 청크에 붙인다(없으면 마지막 청크)
    for t in tables:
        target = None
        for i, (c, _) in enumerate(chunks):
            if f"[p.{t.page}]" in c:
                target = i
        if target is None:
            target = len(chunks) - 1 if chunks else None
        if target is None:
            chunks.append(("", [t]))
        else:
            chunks[target][1].append(t)
    return chunks


def _render_user(sec: Section, text: str, tables: list[Table]) -> str:
    out = [f"## 섹션: {sec.heading} (p.{sec.page_start}–{sec.page_end})", "", text.strip()]
    for t in tables:
        out += ["", f"### 표 {t.table_id} (p.{t.page}) — {t.caption or ''}", table_to_markdown(t)]
    return "\n".join(out)


# ----------------------------------------------------------------------
def mock_extract(doc: Document, sec: Section, text: str, tables: list[Table], prose_counter: list[int]) -> ExtractionResult:
    """프롬프트 없이 결정적으로 뽑는 mock. 표의 고유번호 행 + 본문의 의무 문장."""
    reqs: list[Requirement] = []
    table_sentences: set[str] = set()
    for t in tables:
        hdr = [h for h in t.header]
        id_col = next((i for i, h in enumerate(hdr) if "고유번호" in h or h.upper() == "ID"), None)
        if id_col is None:
            # 첫 열이 ID 패턴이면 사용
            if t.rows and ID_RE.fullmatch(t.rows[0][0] if t.rows[0] else ""):
                id_col = 0
            else:
                continue
        name_col = next((i for i, h in enumerate(hdr) if "명칭" in h or "요구사항명" in h or h == "항목"), None)
        def_col = next((i for i, h in enumerate(hdr) if "정의" in h), None)
        detail_col = next((i for i, h in enumerate(hdr) if "세부" in h or "내용" in h), None)
        out_col = next((i for i, h in enumerate(hdr) if "산출" in h), None)
        for r in t.rows:
            rid = r[id_col].strip() if id_col < len(r) else ""
            if not ID_RE.fullmatch(rid):
                continue
            quote = ""
            for c in (detail_col, def_col):
                if c is not None and c < len(r) and r[c].strip():
                    quote = r[c].strip()
                    break
            if not quote:
                continue
            title = r[name_col].strip() if name_col is not None and name_col < len(r) and r[name_col].strip() else quote[:25]
            cat = rid[:3] if rid[:3] in CATEGORY_LABELS else _guess_category(quote)
            deliverables = [d.strip() for d in re.split(r"[,、，/]", r[out_col])] if out_col is not None and out_col < len(r) and r[out_col].strip() else []
            table_sentences.add(_norm(quote)[:40])
            reqs.append(Requirement(id=rid, title=title[:40], category=cat, obligation=_obligation(quote), quote=quote, page=t.page,
                                    section=sec.heading, detail=r[def_col].strip() if def_col is not None and def_col < len(r) else None,
                                    deliverables=deliverables, source="table"))
    # 본문: 페이지 블록마다 줄을 이어 붙여 문장으로 자른 뒤 의무 문장을 찾는다.
    # 표 셀 텍스트도 페이지 텍스트에 섞여 있으므로, 표 셀에 포함된 문장은 건너뛴다.
    table_cells = {_norm(c) for t in tables for row in ([t.header] + t.rows) for c in row if len(_norm(c)) >= 10}
    table_cells |= {_norm(c) for t in doc.tables if t.page in range(sec.page_start, sec.page_end + 1) for row in ([t.header] + t.rows) for c in row if len(_norm(c)) >= 10}
    contract_like = any(k in (sec.heading + " " + parent_heading(doc, sec)) for k in ("계약 조건", "계약조건", "계약 일반", "특수조건"))
    if contract_like:
        # 계약 조건은 요구사항이 아니라 위험 조항 단계가 다룬다
        return ExtractionResult(requirements=reqs)
    page = sec.page_start
    for block in re.split(r"(?=\[p\.\d+\])", text):
        m = re.match(r"\[p\.(\d+)\]", block)
        if m:
            page = int(m.group(1))
            block = block[m.end():]
        # 제목 줄은 문장 경계다. 제목이 다음 문장에 붙지 않게 빈 줄로 바꾼다.
        lines = [("\n" if _is_heading(l) else l) for l in block.splitlines()]
        merged = re.sub(r"[ \t]*\n[ \t]*", " ", "\n".join(lines))
        merged = re.sub(r"\s{2,}", "\n", merged)
        for sent in re.split(r"(?<=다\.)\s+|\n", merged):
            sent = sent.strip()
            if len(sent) < 12 or ID_RE.search(sent) or "|" in sent or not PROSE_REQ_RE.search(sent):
                continue
            ns = _norm(sent)
            if ns[:40] in table_sentences or any(ns[:30] in cell for cell in table_cells):
                continue
            prose_counter[0] += 1
            rid = f"REQ-P-{prose_counter[0]:03d}"
            title = re.sub(r"^(또한|그리고|단,|다만,)\s*", "", sent)
            if len(title) > 28:
                title = title[:28].rsplit(" ", 1)[0].rstrip("(,·") + "…"
            reqs.append(Requirement(id=rid, title=title, category=_guess_category(sent, "COR" if ("계약" in sec.heading or "조건" in sec.heading) else "SFR"),
                                    obligation=_obligation(sent), quote=sent, page=page, section=sec.heading, source="prose", confidence=0.8))
    return ExtractionResult(requirements=reqs)


# ----------------------------------------------------------------------
def dedupe(reqs: list[Requirement]) -> list[Requirement]:
    by_id: dict[str, Requirement] = {}
    for r in reqs:
        if r.id in by_id:
            a = by_id[r.id]
            if len(r.quote) > len(a.quote):
                r.deliverables = sorted(set(a.deliverables + r.deliverables))
                by_id[r.id] = r
            continue
        by_id[r.id] = r
    out: list[Requirement] = []
    seen_quotes: list[tuple[str, Requirement]] = []
    for r in by_id.values():
        nq = _norm(r.quote)
        dup = None
        for q, other in seen_quotes:
            if not nq or not q:
                continue
            shorter, longer = (nq, q) if len(nq) <= len(q) else (q, nq)
            if len(shorter) >= 15 and shorter in longer and len(shorter) / len(longer) >= 0.9:
                dup = other
                break
        if dup:
            # 표 쪽을 남긴다
            if dup.source == "prose" and r.source == "table":
                out.remove(dup)
                seen_quotes = [(q, o) for q, o in seen_quotes if o is not dup]
            else:
                continue
        out.append(r)
        seen_quotes.append((nq, r))
    return out


def renumber_prose(reqs: list[Requirement]) -> list[Requirement]:
    n = 0
    for r in reqs:
        if r.source == "prose" and r.id.startswith("REQ-P-"):
            n += 1
            r.id = f"REQ-P-{n:03d}"
    return reqs


def extract_requirements(doc: Document, llm: LLM, progress=None) -> list[Requirement]:
    system = load_prompt("extract")
    all_reqs: list[Requirement] = []
    prose_counter = [0]
    sections = [s for s in doc.sections if s.text.strip() or s.table_ids]
    jobs: list[tuple[Section, str, list[Table]]] = []
    for sec in sections:
        for text, tables in _chunks_for_section(doc, sec):
            if text.strip() or tables:
                jobs.append((sec, text, tables))
    done = [0]

    def run(job: tuple[Section, str, list[Table]]) -> list[Requirement]:
        sec, text, tables = job
        result = llm.parse(
            stage="extract",
            system=system,
            user=_render_user(sec, text, tables),
            schema=ExtractionResult,
            mock_fn=lambda: mock_extract(doc, sec, text, tables, prose_counter),
        )
        for r in result.requirements:
            if not r.section:
                r.section = sec.heading
            if not _quote_found(doc, r, sec):
                r.flags.append("quote_not_found")
                r.confidence = min(r.confidence, 0.3)
        done[0] += 1
        if progress:
            progress("extract", done[0], len(jobs))
        return result.requirements

    for reqs_part in llm.map(run, jobs):
        all_reqs.extend(reqs_part)
    reqs = renumber_prose(dedupe(all_reqs))
    log.info("extracted %d requirements (%d table, %d prose)", len(reqs), sum(r.source == "table" for r in reqs), sum(r.source == "prose" for r in reqs))
    return reqs
