"""파이프라인 전 단계가 공유하는 데이터 계약.

이 파일을 바꾸면 export.py, eval/, dashboard 템플릿이 같이 바뀐다. 필드 추가는 Optional로.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field

# 공공 SW 사업 요구사항 분류(소프트웨어사업 요구사항 분석·적용 가이드)
Category = Literal["SFR", "PER", "SIR", "INR", "DAR", "TER", "SER", "QUR", "COR", "PMR", "PSR"]
CATEGORY_LABELS: dict[str, str] = {
    "SFR": "기능",
    "PER": "성능",
    "SIR": "시스템장비구성",
    "INR": "인터페이스",
    "DAR": "데이터",
    "TER": "테스트",
    "SER": "보안",
    "QUR": "품질",
    "COR": "제약사항",
    "PMR": "프로젝트관리",
    "PSR": "프로젝트지원",
}
Obligation = Literal["must", "should", "may"]
Severity = Literal["high", "medium", "low"]
CoverageStatus = Literal["covered", "partial", "missing"]


# ---------- parse ----------
class Table(BaseModel):
    table_id: str
    page: int
    caption: Optional[str] = None
    header: list[str] = Field(default_factory=list)
    rows: list[list[str]] = Field(default_factory=list)


class Section(BaseModel):
    section_id: str
    heading: str
    level: int = 1
    page_start: int
    page_end: int
    text: str
    table_ids: list[str] = Field(default_factory=list)


class Page(BaseModel):
    number: int
    text: str
    prose_text: Optional[str] = Field(default=None, description="표 영역을 제외한 본문 텍스트. 숨은 요구사항 탐색용")


class DocumentMeta(BaseModel):
    source_path: str
    title: Optional[str] = None
    page_count: int = 0
    needs_ocr: bool = False
    stripped_lines: list[str] = Field(default_factory=list)


class Document(BaseModel):
    meta: DocumentMeta
    pages: list[Page]
    sections: list[Section]
    tables: list[Table]

    def page_text(self, number: int) -> str:
        for p in self.pages:
            if p.number == number:
                return p.text
        return ""


# ---------- extract ----------
class Requirement(BaseModel):
    id: str = Field(description="RFP 고유번호(SFR-001 등). 없으면 REQ-P-### 형태로 부여")
    title: str = Field(description="요구사항 명칭, 30자 이내")
    category: Category
    obligation: Obligation
    quote: str = Field(description="RFP 원문 그대로. 요약 금지")
    page: int
    section: Optional[str] = None
    detail: Optional[str] = Field(default=None, description="세부 내용 요약, 2문장 이내")
    deliverables: list[str] = Field(default_factory=list)
    source: Literal["table", "prose"] = "table"
    confidence: float = 1.0
    flags: list[str] = Field(default_factory=list)


class ExtractionResult(BaseModel):
    """한 섹션(또는 표)에 대한 LLM 구조화 출력."""

    requirements: list[Requirement]


# ---------- toc ----------
class ScoringCriterion(BaseModel):
    id: str
    name: str
    parent: Optional[str] = None
    points: float
    description: Optional[str] = None
    page: Optional[int] = None


class TocNode(BaseModel):
    number: str
    title: str
    criterion_ids: list[str] = Field(default_factory=list)
    requirement_ids: list[str] = Field(default_factory=list)
    suggested_pages: int = 0
    writing_guide: str = ""


class RequirementMapping(BaseModel):
    requirement_id: str
    criterion_id: Optional[str] = None


class MappingResult(BaseModel):
    """LLM이 돌려주는 요구사항→배점 항목 연결."""

    mappings: list[RequirementMapping]


class TocResult(BaseModel):
    scoring: list[ScoringCriterion]
    toc: list[TocNode]
    unmapped_requirement_ids: list[str] = Field(default_factory=list)
    total_pages: int = 0
    flags: list[str] = Field(default_factory=list)


# ---------- risk ----------
class RiskFinding(BaseModel):
    rule_id: str
    title: str
    category: str
    severity: Severity
    quote: str
    page: int
    section: Optional[str] = None
    why: str
    extracted_value: Optional[str] = None
    threshold: Optional[str] = None
    negotiation_point: str = ""
    basis: Optional[str] = None
    source: Literal["rule", "rule+llm", "llm"] = "rule"


class RiskJudgement(BaseModel):
    """규칙에 걸린 조항 하나에 대한 LLM 보강."""

    severity: Severity
    why: str = Field(description="두 문장 이내. 심각도를 바꿨다면 그 이유 포함")
    negotiation_point: str
    additional_findings: list[RiskFinding] = Field(
        default_factory=list, description="규칙에 없지만 문맥에서 발견한 위험. source는 llm"
    )


class RiskResult(BaseModel):
    findings: list[RiskFinding]


# ---------- coverage ----------
class Paragraph(BaseModel):
    id: str
    text: str
    heading: Optional[str] = None


class CoverageItem(BaseModel):
    requirement_id: str
    status: CoverageStatus
    evidence_paragraph_ids: list[str] = Field(default_factory=list)
    evidence_quote: Optional[str] = None
    gap_note: Optional[str] = None


class CoverageJudgement(BaseModel):
    items: list[CoverageItem]


class CoverageResult(BaseModel):
    draft_path: str
    items: list[CoverageItem]
    covered: int = 0
    partial: int = 0
    missing: int = 0
    must_missing: int = 0


# ---------- report ----------
class Summary(BaseModel):
    title: Optional[str] = None
    page_count: int = 0
    table_count: int = 0
    requirement_count: int = 0
    requirement_table: int = 0
    requirement_prose: int = 0
    requirement_must: int = 0
    scoring_count: int = 0
    scoring_points: float = 0
    toc_count: int = 0
    unmapped_count: int = 0
    risk_count: int = 0
    risk_high: int = 0
    risk_medium: int = 0
    risk_low: int = 0
    coverage_covered: Optional[int] = None
    coverage_partial: Optional[int] = None
    coverage_missing: Optional[int] = None
    coverage_must_missing: Optional[int] = None
    llm_mode: str = "mock"
    stage_seconds: dict[str, float] = Field(default_factory=dict)


class ReviewReport(BaseModel):
    summary: Summary
    document_meta: DocumentMeta
    requirements: list[Requirement]
    toc: Optional[TocResult] = None
    risks: list[RiskFinding] = Field(default_factory=list)
    coverage: Optional[CoverageResult] = None
