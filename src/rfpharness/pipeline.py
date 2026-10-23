"""6단계 파이프라인. 각 단계는 체크포인트에 저장되고 --from으로 재개한다."""
from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Callable

from .coverage import check_coverage
from .export import write_dashboard, write_toc_docx, write_xlsx
from .extract import extract_requirements
from .llm import LLM
from .parse import parse_pdf
from .risk import audit_risks
from .schemas import CoverageResult, Document, Requirement, ReviewReport, RiskFinding, Summary, TocResult
from .toc import build_toc

log = logging.getLogger("rfpharness.pipeline")
STAGES = ["parse", "extract", "toc", "risk", "coverage", "export"]
Progress = Callable[[str, str, int, int], None]  # (stage, status, done, total)


class Pipeline:
    def __init__(self, pdf: str | Path, out_dir: str | Path, draft: str | Path | None = None, llm: LLM | None = None, progress: Progress | None = None):
        self.pdf = Path(pdf)
        self.out = Path(out_dir)
        self.ckpt = self.out / "checkpoints"
        self.ckpt.mkdir(parents=True, exist_ok=True)
        self.draft = Path(draft) if draft else None
        self.llm = llm or LLM()
        self.progress = progress or (lambda *a: None)
        self.timings: dict[str, float] = {}
        self.doc: Document | None = None
        self.reqs: list[Requirement] = []
        self.toc: TocResult | None = None
        self.risks: list[RiskFinding] = []
        self.coverage: CoverageResult | None = None

    # ---- checkpoint helpers ----
    def _save(self, stage: str, obj) -> None:
        if isinstance(obj, list):
            data = [o.model_dump() for o in obj]
        else:
            data = obj.model_dump()
        (self.ckpt / f"{stage}.json").write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")

    def _has(self, stage: str) -> bool:
        return (self.ckpt / f"{stage}.json").exists()

    def _load(self, stage: str):
        return json.loads((self.ckpt / f"{stage}.json").read_text(encoding="utf-8"))

    def _sub(self, stage: str):
        return lambda _s, done, total: self.progress(stage, "running", done, total)

    # ---- stages ----
    def run(self, start: str = "parse", stop: str = "export", fresh: bool = False) -> ReviewReport:
        si, ei = STAGES.index(start), STAGES.index(stop)
        log.info("run %s → %s (llm=%s, fresh=%s)", start, stop, self.llm.mode, fresh)
        for idx, stage in enumerate(STAGES):
            if idx > ei:
                break
            reuse = (idx < si or (not fresh and self._has(stage) and stage != "export")) and self._has(stage)
            if stage == "coverage" and not self.draft and not self._has("coverage"):
                self.progress(stage, "skipped", 0, 0)
                continue
            t0 = time.time()
            self.progress(stage, "running", 0, 0)
            if reuse:
                self._restore(stage)
                self.progress(stage, "reused", 1, 1)
                continue
            getattr(self, f"_stage_{stage}")()
            self.timings[stage] = round(time.time() - t0, 2)
            self.progress(stage, "done", 1, 1)
        report = self.build_report()
        (self.out / "report.json").write_text(report.model_dump_json(indent=1), encoding="utf-8")
        return report

    def _restore(self, stage: str) -> None:
        data = self._load(stage)
        if stage == "parse":
            self.doc = Document.model_validate(data)
        elif stage == "extract":
            self.reqs = [Requirement.model_validate(d) for d in data]
        elif stage == "toc":
            self.toc = TocResult.model_validate(data)
        elif stage == "risk":
            self.risks = [RiskFinding.model_validate(d) for d in data]
        elif stage == "coverage":
            self.coverage = CoverageResult.model_validate(data)

    def _need_doc(self) -> Document:
        if self.doc is None:
            if self._has("parse"):
                self._restore("parse")
            else:
                self._stage_parse()
        return self.doc

    def _stage_parse(self) -> None:
        self.doc = parse_pdf(self.pdf)
        self._save("parse", self.doc)

    def _stage_extract(self) -> None:
        self.reqs = extract_requirements(self._need_doc(), self.llm, self._sub("extract"))
        self._save("extract", self.reqs)

    def _stage_toc(self) -> None:
        if not self.reqs and self._has("extract"):
            self._restore("extract")
        self.toc = build_toc(self._need_doc(), self.reqs, self.llm)
        self._save("toc", self.toc)

    def _stage_risk(self) -> None:
        self.risks = audit_risks(self._need_doc(), self.llm, self._sub("risk"))
        self._save("risk", self.risks)

    def _stage_coverage(self) -> None:
        if not self.reqs and self._has("extract"):
            self._restore("extract")
        self.coverage = check_coverage(self.reqs, self.draft, self.llm, self._sub("coverage"))
        self._save("coverage", self.coverage)

    def _stage_export(self) -> None:
        for s in ("extract", "toc", "risk", "coverage"):
            if self._has(s) and not getattr(self, {"extract": "reqs", "toc": "toc", "risk": "risks", "coverage": "coverage"}[s]):
                self._restore(s)
        report = self.build_report()
        write_xlsx(report, self.out / "traceability.xlsx")
        write_toc_docx(report, self.out / "toc_draft.docx")
        doc = self._need_doc()
        write_dashboard(report, self.out / "dashboard.html", {p.number: p.text for p in doc.pages})

    # ---- report ----
    def build_report(self) -> ReviewReport:
        doc = self._need_doc()
        s = Summary(
            title=doc.meta.title, page_count=doc.meta.page_count, table_count=len(doc.tables),
            requirement_count=len(self.reqs), requirement_table=sum(r.source == "table" for r in self.reqs),
            requirement_prose=sum(r.source == "prose" for r in self.reqs), requirement_must=sum(r.obligation == "must" for r in self.reqs),
            scoring_count=len([c for c in self.toc.scoring if not c.parent]) if self.toc else 0,
            scoring_points=sum(c.points for c in self.toc.scoring if not c.parent) if self.toc else 0,
            toc_count=len([n for n in self.toc.toc if "." not in n.number]) if self.toc else 0,
            unmapped_count=len(self.toc.unmapped_requirement_ids) if self.toc else 0,
            risk_count=len(self.risks), risk_high=sum(f.severity == "high" for f in self.risks),
            risk_medium=sum(f.severity == "medium" for f in self.risks), risk_low=sum(f.severity == "low" for f in self.risks),
            llm_mode=self.llm.mode, stage_seconds=self.timings,
        )
        if self.coverage:
            s.coverage_covered, s.coverage_partial, s.coverage_missing, s.coverage_must_missing = (
                self.coverage.covered, self.coverage.partial, self.coverage.missing, self.coverage.must_missing)
        return ReviewReport(summary=s, document_meta=doc.meta, requirements=self.reqs, toc=self.toc, risks=self.risks, coverage=self.coverage)


def format_summary(report: ReviewReport) -> str:
    s = report.summary
    lines = [
        f"RFP: {s.title or '(제목 미확인)'} ({s.page_count}쪽, 표 {s.table_count}개) — LLM 모드: {s.llm_mode}",
        f"요구사항 {s.requirement_count}건 — 표 {s.requirement_table} · 본문 {s.requirement_prose} · 필수 {s.requirement_must}",
        f"배점 항목 {s.scoring_count}개(합 {s.scoring_points:g}점) → 목차 {s.toc_count}장, 미연결 요구사항 {s.unmapped_count}건",
        f"위험 조항 {s.risk_count}건 — 높음 {s.risk_high} · 보통 {s.risk_medium} · 낮음 {s.risk_low}",
    ]
    for i, f in enumerate([f for f in report.risks if f.severity == "high"][:3], start=1):
        lines.append(f"  {i}. [높음] {f.title} p.{f.page} — {f.why}")
    if s.coverage_covered is not None:
        lines.append(f"커버리지(초안 대조) — 충족 {s.coverage_covered} · 부분 {s.coverage_partial} · 누락 {s.coverage_missing} (필수 누락 {s.coverage_must_missing})")
    lines.append("산출물: traceability.xlsx · toc_draft.docx · dashboard.html · report.json")
    return "\n".join(lines)
