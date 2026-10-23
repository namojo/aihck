"""위험 조항: 규칙(어디) + LLM(왜·얼마나) 이중 판정."""
from __future__ import annotations

import logging
import re
from pathlib import Path

import yaml

from .llm import LLM, load_prompt
from .parse import section_for_page
from .schemas import Document, RiskFinding, RiskJudgement

log = logging.getLogger("rfpharness.risk")
RULES_PATH = Path(__file__).resolve().parents[2] / "rules" / "risk_rules.yaml"


def load_rules(path: str | Path = RULES_PATH) -> list[dict]:
    data = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    rules = data["rules"]
    for r in rules:
        r["_pattern"] = re.compile(r["pattern"]) if r.get("pattern") else None
        r["_requires"] = re.compile(r["requires"]) if r.get("requires") else None
        r["_exclude"] = re.compile(r["exclude"]) if r.get("exclude") else None
    return rules


# ---------------- 값 정규화 ----------------
def normalize_value(kind: str, text: str) -> tuple[float | None, str]:
    """매칭된 문장에서 수치를 뽑아 규칙 단위로 환산한다. (값, 표시 문자열)"""
    if kind == "rate_per_day_percent":
        m = re.search(r"1000분의\s*(\d+(?:\.\d+)?)", text)
        if m:
            v = float(m.group(1)) / 10
            return v, f"{v:g}%/일 (1000분의 {m.group(1)})"
        m = re.search(r"(\d+(?:\.\d+)?)\s*/\s*1000", text)
        if m:
            v = float(m.group(1)) / 10
            return v, f"{v:g}%/일"
        m = re.search(r"(\d+(?:\.\d+)?)\s*‰", text)
        if m:
            v = float(m.group(1)) / 10
            return v, f"{v:g}%/일"
        m = re.search(r"(\d+(?:\.\d+)?)\s*(%|퍼센트)", text)
        if m:
            v = float(m.group(1))
            return v, f"{v:g}%/일"
        return None, ""
    if kind == "years":
        m = re.search(r"(\d+)\s*(년|개월)", text)
        if m:
            n = int(m.group(1))
            v = n if m.group(2) == "년" else n / 12
            return v, f"{n}{m.group(2)}"
        return None, ""
    if kind == "percent":
        m = re.search(r"100분의\s*(\d+(?:\.\d+)?)", text)
        if m:
            return float(m.group(1)), f"{m.group(1)}%"
        m = re.search(r"(\d+(?:\.\d+)?)\s*(%|퍼센트|/\s*100)", text)
        if m:
            return float(m.group(1)), f"{m.group(1)}%"
        return None, ""
    return None, ""


def threshold_label(rule: dict) -> str | None:
    th = rule.get("threshold")
    if th is None:
        return None
    kind = rule.get("value_kind")
    if kind == "rate_per_day_percent":
        return f"{th:g}%/일 (1000분의 {th * 10:g})"
    if kind == "years":
        return f"{th:g}년"
    if kind == "percent":
        return f"{th:g}%"
    return str(th)


HEADING_LINE_RE = re.compile(r"^\s*(제\s*\d+\s*조|[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]\.|\d{1,2}\.|[가-힣]\.|\d{1,2}\))\s*\S")


def _heading_ends(text: str) -> list[tuple[int, int]]:
    """제목처럼 보이는 줄의 (시작, 끝) 오프셋. 인용문이 제목을 삼키지 않게 경계로 쓴다."""
    spans: list[tuple[int, int]] = []
    pos = 0
    for line in text.split("\n"):
        if len(line.strip()) <= 50 and HEADING_LINE_RE.match(line) and not line.rstrip().endswith("다."):
            spans.append((pos, pos + len(line) + 1))
        pos += len(line) + 1
    return spans


def _sentence_around(text: str, start: int, end: int, heading_ends: list[tuple[int, int]] | None = None) -> str:
    """매칭 위치를 감싸는 문장. 경계는 직전 '다.' 또는 제목 줄 끝, 직후 '다.'"""
    left = text.rfind("다.", 0, start)
    left = left + 2 if left >= 0 else 0
    if heading_ends:
        # 제목 줄이 문장 앞에 있거나, 매칭이 제목 줄 안에서 시작한 경우("7. 대금 지급 사업비는…", "5. 손해배상")
        for hs, he in heading_ends:
            if (left < he <= start) or (hs <= start < he):
                left = max(left, he)
    search_from = max(end, left)
    right = text.find("다.", search_from)
    right = right + 2 if right >= 0 else min(len(text), search_from + 120)
    return re.sub(r"\s+", " ", text[left:right]).strip()


def _full_text(doc: Document) -> tuple[str, list[tuple[int, int]]]:
    """페이지를 이어 붙인 전체 텍스트와 (페이지 번호, 그 페이지가 끝나는 오프셋) 목록."""
    parts: list[str] = []
    offsets: list[tuple[int, int]] = []
    pos = 0
    for p in doc.pages:
        t = p.text + "\n"
        parts.append(t)
        pos += len(t)
        offsets.append((p.number, pos))
    return "".join(parts), offsets


def _table_cell_quote(doc: Document, page: int, matched: str) -> str | None:
    """매칭이 표 안에서 났으면 열이 섞인 페이지 텍스트 대신 해당 셀 원문을 인용한다."""
    key = re.sub(r"\s+", "", matched)[:12]
    if not key:
        return None
    for t in doc.tables:
        if t.page != page:
            continue
        for row in t.rows:
            for c in row:
                if key in re.sub(r"\s+", "", c):
                    return c
    return None


def _page_for_pos(pos: int, offsets: list[tuple[int, int]]) -> int:
    for pno, end in offsets:
        if pos < end:
            return pno
    return offsets[-1][0]


# ---------------- 규칙 적용 ----------------
def apply_rules(doc: Document, rules: list[dict] | None = None) -> list[RiskFinding]:
    rules = rules or load_rules()
    raw, offsets = _full_text(doc)
    heading_ends = _heading_ends(raw)
    text = raw.replace("\n", " ")  # 줄바꿈으로 끊긴 문장을 이어서 매칭. 길이가 같아 오프셋이 유지된다.
    findings: list[RiskFinding] = []
    seen: set[tuple[str, str]] = set()
    for rule in rules:
        compare = rule.get("compare", "present")
        if compare == "absent":
            if rule["_requires"] and not rule["_requires"].search(text):
                continue
            if rule["_pattern"] and rule["_pattern"].search(text):
                continue
            m = rule["_requires"].search(text) if rule["_requires"] else None
            if not m:
                continue
            quote = _sentence_around(text, m.start(), m.end(), heading_ends)
            page = _page_for_pos(m.start(), offsets)
            findings.append(_finding(rule, quote, page, doc, None))
            continue
        if not rule["_pattern"]:
            continue
        for m in rule["_pattern"].finditer(text):
            window = text[max(0, m.start() - 20): m.end() + 20]
            if rule["_exclude"] and rule["_exclude"].search(window):
                continue
            quote = _sentence_around(text, m.start(), m.end(), heading_ends)
            value_label = None
            if compare in ("gt", "lt"):
                v, value_label = normalize_value(rule.get("value_kind", ""), m.group(0))
                if v is None:
                    v, value_label = normalize_value(rule.get("value_kind", ""), quote)
                if v is None:
                    continue
                th = float(rule["threshold"])
                if compare == "gt" and not v > th:
                    continue
                if compare == "lt" and not v < th:
                    continue
            page = _page_for_pos(m.start(), offsets)
            cell = _table_cell_quote(doc, page, m.group(0))
            if cell:
                quote = cell
            key = (rule["id"], re.sub(r"\s+", "", quote)[:60])
            if key in seen:
                continue
            seen.add(key)
            findings.append(_finding(rule, quote, page, doc, value_label))
    sev_order = {"high": 0, "medium": 1, "low": 2}
    findings.sort(key=lambda f: (sev_order[f.severity], f.page))
    return findings


def _finding(rule: dict, quote: str, page: int, doc: Document, value_label: str | None) -> RiskFinding:
    return RiskFinding(
        rule_id=rule["id"],
        title=rule["title"],
        category=rule.get("category", ""),
        severity=rule.get("severity_default", "medium"),
        quote=quote,
        page=page,
        section=section_for_page(doc, page),
        why=rule.get("why", ""),
        extracted_value=value_label or None,
        threshold=threshold_label(rule),
        negotiation_point=rule.get("negotiation_point", ""),
        basis=rule.get("basis"),
        source="rule",
    )


def match_rule_text(rule: dict, text: str) -> bool:
    """테스트용: 예문 하나에 규칙이 걸리는지."""
    if rule.get("compare") == "absent":
        if rule["_requires"] and not rule["_requires"].search(text):
            return False
        return not (rule["_pattern"] and rule["_pattern"].search(text))
    m = rule["_pattern"].search(text)
    if not m:
        return False
    if rule["_exclude"] and rule["_exclude"].search(text):
        return False
    if rule.get("compare") in ("gt", "lt"):
        v, _ = normalize_value(rule.get("value_kind", ""), m.group(0))
        if v is None:
            v, _ = normalize_value(rule.get("value_kind", ""), text)
        if v is None:
            return False
        th = float(rule["threshold"])
        return v > th if rule["compare"] == "gt" else v < th
    return True


# ---------------- LLM 보강 ----------------
def enrich_with_llm(doc: Document, findings: list[RiskFinding], llm: LLM, progress=None) -> list[RiskFinding]:
    if llm.mode == "mock":
        return findings
    system = load_prompt("risk")
    raw, offsets = _full_text(doc)
    text = raw.replace("\n", " ")
    out: list[RiskFinding] = []
    extra: list[RiskFinding] = []

    def judge(f: RiskFinding) -> RiskJudgement:
        pos = text.find(f.quote[:40])
        ctx = text[max(0, pos - 600): pos + len(f.quote) + 600] if pos >= 0 else doc.page_text(f.page)
        user = (
            f"## 규칙\n{f.rule_id} {f.title}\n기본 심각도: {f.severity}\n기준값: {f.threshold or '-'}\n근거: {f.basis or '-'}\n\n"
            f"## 의심 조항 (p.{f.page})\n{f.quote}\n추출값: {f.extracted_value or '-'}\n\n## 앞뒤 문맥\n{ctx}"
        )
        return llm.parse(stage="risk", system=system, user=user, schema=RiskJudgement, mock_fn=lambda f=f: RiskJudgement(severity=f.severity, why=f.why, negotiation_point=f.negotiation_point))

    judgements = llm.map(judge, findings)
    for i, (f, j) in enumerate(zip(findings, judgements)):
        f.severity = j.severity
        f.why = j.why or f.why
        f.negotiation_point = j.negotiation_point or f.negotiation_point
        f.source = "rule+llm"
        out.append(f)
        for a in j.additional_findings:
            a.source = "llm"
            if not a.section:
                a.section = section_for_page(doc, a.page)
            extra.append(a)
        if progress:
            progress("risk", i + 1, len(findings))
    # llm 추가 발견 중 기존과 겹치는 것 제거
    seen = {re.sub(r"\s+", "", f.quote)[:40] for f in out}
    for a in extra:
        k = re.sub(r"\s+", "", a.quote)[:40]
        if k not in seen:
            seen.add(k)
            out.append(a)
    return out


def audit_risks(doc: Document, llm: LLM, progress=None) -> list[RiskFinding]:
    findings = apply_rules(doc)
    log.info("rule findings: %d", len(findings))
    return enrich_with_llm(doc, findings, llm, progress)
