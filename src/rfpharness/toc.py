"""배점표 인식 → 요구사항 연결 → 배점 비례 목차 초안."""
from __future__ import annotations

import logging
import re

from .llm import LLM, load_prompt
from .schemas import Document, MappingResult, Requirement, RequirementMapping, ScoringCriterion, Table, TocNode, TocResult

log = logging.getLogger("rfpharness.toc")

NUM_RE = re.compile(r"^\d+(\.\d+)?$")
PAGE_LIMIT_RE = re.compile(r"제안서[^\n]{0,30}?(\d{2,3})\s*(쪽|페이지|매|면)\s*(이내|이하)")

CRITERION_HINTS: list[tuple[re.Pattern[str], list[str]]] = [
    (re.compile(r"보안|정보보호"), ["SER"]),
    (re.compile(r"성능|안정성|가용"), ["PER", "QUR"]),
    (re.compile(r"데이터|이관|전환"), ["DAR"]),
    (re.compile(r"연계|인터페이스"), ["INR"]),
    (re.compile(r"사업\s*관리|추진\s*체계|일정|방법론|위험|품질\s*보증|수행\s*조직"), ["PMR"]),
    (re.compile(r"교육|유지\s*보수|지원|하자|기술\s*이전"), ["PSR"]),
    (re.compile(r"테스트|시험|품질"), ["TER", "QUR"]),
    (re.compile(r"기능|구현|시스템|구축|설계|아키텍처|장비|인프라"), ["SFR", "SIR"]),
    (re.compile(r"이해도|전략|개요"), ["COR"]),
]


def _to_num(s: str) -> float | None:
    s = s.replace(",", "").replace("점", "").strip()
    return float(s) if NUM_RE.match(s) else None


def find_scoring_tables(doc: Document) -> list[Table]:
    cands: list[tuple[int, Table]] = []
    for t in doc.tables:
        pts_col = next((i for i, h in enumerate(t.header) if "배점" in h or "점수" in h), None)
        if pts_col is None:
            continue
        nums = [_to_num(r[pts_col]) for r in t.rows if pts_col < len(r)]
        nums = [n for n in nums if n is not None]
        if not nums:
            continue
        total = sum(nums)
        score = 0
        if 60 <= total <= 200:
            score += 2
        cap = (t.caption or "")
        if "기술" in cap or "정성" in cap or any("기술" in h for h in t.header):
            score += 1
        if score:
            cands.append((score, t))
    cands.sort(key=lambda x: -x[0])
    return [t for _, t in cands]


def build_criteria(t: Table) -> list[ScoringCriterion]:
    pts_col = next(i for i, h in enumerate(t.header) if "배점" in h or "점수" in h)
    text_cols = [i for i, h in enumerate(t.header) if i != pts_col and not any(k in h for k in ("설명", "내용", "기준"))]
    desc_col = next((i for i, h in enumerate(t.header) if any(k in h for k in ("설명", "내용", "기준"))), None)
    name_col = text_cols[0] if text_cols else 0
    sub_col = text_cols[1] if len(text_cols) > 1 else None
    criteria: list[ScoringCriterion] = []
    parents: dict[str, ScoringCriterion] = {}
    pi = 0
    for r in t.rows:
        if pts_col >= len(r):
            continue
        pts = _to_num(r[pts_col])
        name = r[name_col].strip() if name_col < len(r) else ""
        if name in ("합계", "계", "총계", "소계") or not name:
            continue
        sub = r[sub_col].strip() if sub_col is not None and sub_col < len(r) else ""
        desc = r[desc_col].strip() if desc_col is not None and desc_col < len(r) else None
        if sub and pts is not None:
            if name not in parents:
                pi += 1
                parents[name] = ScoringCriterion(id=f"C{pi}", name=name, points=0, page=t.page)
                criteria.append(parents[name])
            p = parents[name]
            child_n = sum(1 for c in criteria if c.parent == p.id) + 1
            criteria.append(ScoringCriterion(id=f"{p.id}.{child_n}", name=sub, parent=p.id, points=pts, description=desc, page=t.page))
            p.points += pts
        elif pts is not None:
            if name in parents and sub == "":
                # 상위 항목 행에 합계 배점이 적힌 경우: 하위 합과 비교만
                continue
            pi += 1
            parents[name] = ScoringCriterion(id=f"C{pi}", name=name, points=pts, description=desc, page=t.page)
            criteria.append(parents[name])
    return criteria


def _leafs(criteria: list[ScoringCriterion]) -> list[ScoringCriterion]:
    parent_ids = {c.parent for c in criteria if c.parent}
    return [c for c in criteria if c.id not in parent_ids]


def mock_map(reqs: list[Requirement], criteria: list[ScoringCriterion]) -> MappingResult:
    leafs = _leafs(criteria)
    if not leafs:
        return MappingResult(mappings=[RequirementMapping(requirement_id=r.id) for r in reqs])
    def leaf_text(c: ScoringCriterion) -> str:
        parent = next((p.name for p in criteria if p.id == c.parent), "")
        return f"{parent} {c.name} {c.description or ''}"
    fallback = max(leafs, key=lambda c: c.points)
    out = []
    for r in reqs:
        chosen = None
        best = -1
        for c in leafs:
            txt = leaf_text(c)
            score = 0
            for pat, cats in CRITERION_HINTS:
                if pat.search(txt) and r.category in cats:
                    score += 2
            # 제목 단어 겹침
            for w in re.findall(r"[가-힣A-Za-z]{2,}", r.title):
                if w in txt:
                    score += 1
            if score > best:
                best, chosen = score, c
        if best <= 0:
            chosen = fallback if r.category in ("SFR", "SIR", "INR", "DAR") else None
        out.append(RequirementMapping(requirement_id=r.id, criterion_id=chosen.id if chosen else None))
    return MappingResult(mappings=out)


def _page_limit(doc: Document, default: int) -> int:
    for p in doc.pages:
        m = PAGE_LIMIT_RE.search(p.text)
        if m:
            return int(m.group(1))
    return default


def build_toc(doc: Document, reqs: list[Requirement], llm: LLM, total_pages_default: int = 80) -> TocResult:
    flags: list[str] = []
    tables = find_scoring_tables(doc)
    if not tables:
        flags.append("scoring_table_not_found")
        return TocResult(scoring=[], toc=[], unmapped_requirement_ids=[r.id for r in reqs], total_pages=total_pages_default, flags=flags)
    criteria = build_criteria(tables[0])
    top_total = sum(c.points for c in criteria if not c.parent)
    if not (abs(top_total - 100) < 0.01 or abs(top_total - 90) < 0.01 or abs(top_total - 80) < 0.01):
        flags.append(f"points_sum_mismatch:{top_total:g}")

    crit_text = "\n".join(f"- {c.id} | {c.name} | 상위: {c.parent or '-'} | {c.points:g}점 | {c.description or ''}" for c in criteria)
    req_text = "\n".join(f"- {r.id} | {r.title} | {r.category} | {r.quote[:120]}" for r in reqs)
    mapping = llm.parse(
        stage="toc",
        system=load_prompt("toc"),
        user=f"## 배점 항목\n{crit_text}\n\n## 요구사항\n{req_text}",
        schema=MappingResult,
        mock_fn=lambda: mock_map(reqs, criteria),
    )
    valid_ids = {c.id for c in criteria}
    by_crit: dict[str, list[str]] = {c.id: [] for c in criteria}
    unmapped: list[str] = []
    mapped_ids = set()
    for m in mapping.mappings:
        mapped_ids.add(m.requirement_id)
        if m.criterion_id in valid_ids:
            by_crit[m.criterion_id].append(m.requirement_id)
        else:
            unmapped.append(m.requirement_id)
    for r in reqs:
        if r.id not in mapped_ids:
            unmapped.append(r.id)

    total_pages = _page_limit(doc, total_pages_default)
    pts_total = sum(c.points for c in criteria if not c.parent) or 1
    toc: list[TocNode] = []
    n = 0
    for c in [c for c in criteria if not c.parent]:
        n += 1
        children = [k for k in criteria if k.parent == c.id]
        node_reqs = list(by_crit.get(c.id, []))
        for k in children:
            node_reqs += by_crit.get(k.id, [])
        pages = max(1, round(total_pages * c.points / pts_total))
        toc.append(TocNode(number=str(n), title=c.name, criterion_ids=[c.id] + [k.id for k in children], requirement_ids=node_reqs,
                           suggested_pages=pages, writing_guide=_guide(c, node_reqs, pages)))
        for j, k in enumerate(children, start=1):
            kp = max(1, round(pages * k.points / (c.points or 1)))
            toc.append(TocNode(number=f"{n}.{j}", title=k.name, criterion_ids=[k.id], requirement_ids=by_crit.get(k.id, []),
                               suggested_pages=kp, writing_guide=_guide(k, by_crit.get(k.id, []), kp)))
    if unmapped:
        n += 1
        toc.append(TocNode(number=str(n), title="기타 요구사항 대응", criterion_ids=[], requirement_ids=unmapped, suggested_pages=max(1, len(unmapped) // 5),
                           writing_guide=f"배점 항목에 직접 연결되지 않은 요구사항 {len(unmapped)}건을 표로 대응. 누락으로 보이지 않게 한 줄씩 답한다."))
    return TocResult(scoring=criteria, toc=toc, unmapped_requirement_ids=unmapped, total_pages=total_pages, flags=flags)


def _guide(c: ScoringCriterion, req_ids: list[str], pages: int) -> str:
    ids = ", ".join(req_ids[:6]) + (f" 외 {len(req_ids) - 6}건" if len(req_ids) > 6 else "")
    body = f"배점 {c.points:g}점, 약 {pages}쪽. "
    if req_ids:
        body += f"요구사항 {ids}에 대한 대응 방안을 그림·표로 먼저 보이고 설명은 뒤에 둔다."
    else:
        body += "연결된 요구사항이 없다. 배점 항목 설명을 기준으로 우리 강점(실적·방법론)을 쓴다."
    if c.description:
        body += f" 평가 기준: {c.description[:60]}"
    return body
