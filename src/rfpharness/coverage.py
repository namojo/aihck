"""제안서 초안 ↔ 요구사항 커버리지."""
from __future__ import annotations

import logging
import re
from pathlib import Path

from .llm import LLM, load_prompt
from .schemas import CoverageItem, CoverageJudgement, CoverageResult, Paragraph, Requirement

log = logging.getLogger("rfpharness.coverage")
BATCH = 12


def load_draft(path: str | Path) -> list[Paragraph]:
    path = Path(path)
    paras: list[Paragraph] = []
    heading = None
    if path.suffix.lower() == ".docx":
        import docx

        d = docx.Document(str(path))
        buf: list[str] = []
        for p in d.paragraphs:
            t = p.text.strip()
            if p.style.name.lower().startswith("heading"):
                if buf:
                    paras.append(Paragraph(id="", text=" ".join(buf), heading=heading))
                    buf = []
                heading = t
            elif t:
                buf.append(t)
        if buf:
            paras.append(Paragraph(id="", text=" ".join(buf), heading=heading))
    else:
        text = path.read_text(encoding="utf-8")
        for block in re.split(r"\n\s*\n", text):
            b = block.strip()
            if not b:
                continue
            if b.startswith("#"):
                heading = b.lstrip("#").strip()
                continue
            paras.append(Paragraph(id="", text=re.sub(r"\s+", " ", b), heading=heading))
    for i, p in enumerate(paras, start=1):
        p.id = f"P-{i:03d}"
    return paras


def _bigrams(s: str) -> set[str]:
    s = re.sub(r"[^\w가-힣]", "", s)
    return {s[i: i + 2] for i in range(len(s) - 1)}


def mock_judge(reqs: list[Requirement], paras: list[Paragraph]) -> CoverageJudgement:
    items: list[CoverageItem] = []
    for r in reqs:
        key = _bigrams(r.title + " " + (r.detail or "") + " " + r.quote)
        best, best_ratio = None, 0.0
        for p in paras:
            pb = _bigrams(p.text)
            ratio = len(key & pb) / max(1, len(key))
            if ratio > best_ratio:
                best, best_ratio = p, ratio
        if best_ratio >= 0.5:
            status = "covered"
        elif best_ratio >= 0.28:
            status = "partial"
        else:
            status = "missing"
        items.append(CoverageItem(
            requirement_id=r.id,
            status=status,
            evidence_paragraph_ids=[best.id] if best and status != "missing" else [],
            evidence_quote=best.text[:40] if best and status != "missing" else None,
            gap_note=None if status == "covered" else f"'{r.title}'에 대한 대응 방법과 수치를 초안에 추가",
        ))
    return CoverageJudgement(items=items)


def check_coverage(reqs: list[Requirement], draft_path: str | Path, llm: LLM, progress=None) -> CoverageResult:
    paras = load_draft(draft_path)
    system = load_prompt("coverage")
    para_text = "\n".join(f"[{p.id}] ({p.heading or '-'}) {p.text}" for p in paras)
    items: list[CoverageItem] = []
    batches = [reqs[i: i + BATCH] for i in range(0, len(reqs), BATCH)]
    valid = {p.id for p in paras}
    done = [0]

    def judge(batch: list[Requirement]) -> CoverageJudgement:
        req_text = "\n".join(f"- {r.id} | {r.title} | {r.category} | {r.obligation} | {r.quote[:160]}" for r in batch)
        j = llm.parse(stage="coverage", system=system, user=f"## 요구사항\n{req_text}\n\n## 제안서 초안 문단\n{para_text}", schema=CoverageJudgement,
                      mock_fn=lambda: mock_judge(batch, paras))
        done[0] += 1
        if progress:
            progress("coverage", done[0], len(batches))
        return j

    for j in llm.map(judge, batches):
        for it in j.items:
            it.evidence_paragraph_ids = [pid for pid in it.evidence_paragraph_ids if pid in valid]
            if it.status != "missing" and not it.evidence_paragraph_ids:
                it.status = "partial"
                it.gap_note = (it.gap_note or "") + " (근거 문단 id 확인 불가)"
        items.extend(j.items)
    by_id = {r.id: r for r in reqs}
    judged = {it.requirement_id for it in items}
    for r in reqs:
        if r.id not in judged:
            items.append(CoverageItem(requirement_id=r.id, status="missing", gap_note="판정 누락, 재실행 필요"))
    covered = sum(it.status == "covered" for it in items)
    partial = sum(it.status == "partial" for it in items)
    missing = sum(it.status == "missing" for it in items)
    must_missing = sum(it.status == "missing" and by_id.get(it.requirement_id) and by_id[it.requirement_id].obligation == "must" for it in items)
    log.info("coverage: covered %d partial %d missing %d (must missing %d)", covered, partial, missing, must_missing)
    return CoverageResult(draft_path=str(draft_path), items=items, covered=covered, partial=partial, missing=missing, must_missing=must_missing)
