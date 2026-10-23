"""mock 모드 end-to-end. 네트워크 없이 돈다."""
import json
from pathlib import Path

import pytest

from rfpharness.llm import LLM
from rfpharness.pipeline import Pipeline
from rfpharness.schemas import ReviewReport

ROOT = Path(__file__).resolve().parents[1]
SAMPLE = ROOT / "samples" / "sample_rfp.pdf"
DRAFT = ROOT / "samples" / "draft_proposal.md"


@pytest.fixture(scope="module")
def report(tmp_path_factory):
    if not SAMPLE.exists():
        pytest.skip("samples/sample_rfp.pdf 없음")
    out = tmp_path_factory.mktemp("out")
    pipe = Pipeline(SAMPLE, out, draft=DRAFT, llm=LLM(mode="mock"))
    rep = pipe.run()
    assert (out / "report.json").exists()
    assert (out / "traceability.xlsx").exists() and (out / "toc_draft.docx").exists() and (out / "dashboard.html").exists()
    return rep


def test_requirements(report: ReviewReport):
    ids = {r.id for r in report.requirements}
    assert {"SFR-001", "PER-003", "SER-005", "PSR-004"} <= ids
    assert report.summary.requirement_table == 44
    assert report.summary.requirement_prose >= 5
    assert all(r.quote and r.page >= 1 for r in report.requirements)
    assert all("quote_not_found" not in r.flags for r in report.requirements if r.source == "table")


def test_prose_requirements_found(report: ReviewReport):
    prose = " ".join(r.quote for r in report.requirements if r.source == "prose")
    assert "KWCAG" in prose  # 사업 범위 본문에 숨은 요구사항
    assert "사업수행계획서" in prose


def test_scoring_and_toc(report: ReviewReport):
    assert report.toc and report.summary.scoring_points == 90
    assert report.summary.scoring_count == 6
    assert report.summary.unmapped_count <= report.summary.requirement_count * 0.2


def test_risks(report: ReviewReport):
    hit = {f.rule_id for f in report.risks}
    expected = {"R01_delay_penalty_rate", "R02_delay_penalty_cap_missing", "R03_warranty_period", "R04_free_maintenance", "R05_unilateral_scope_change",
                "R06_ip_sole_ownership", "R07_liability_cap_missing", "R09_payment_terms", "R10_vague_acceptance", "R11_staffing_control",
                "R12_free_commercial_sw", "R13_security_certification", "R14_privacy_liability_shift", "R15_sla_penalty", "R16_third_party_integration",
                "R17_data_migration_scope", "R18_proposal_cost_and_ownership", "R19_termination_without_compensation", "R20_eligibility_track_record"}
    assert expected <= hit, f"missing: {expected - hit}"
    assert "R08_performance_bond_rate" not in hit  # 계약보증금 10%는 정상
    r01 = next(f for f in report.risks if f.rule_id == "R01_delay_penalty_rate")
    assert r01.page == 10 and "0.25" in (r01.extracted_value or "")


def test_coverage(report: ReviewReport):
    c = report.coverage
    assert c and c.covered + c.partial + c.missing == len(report.requirements)
    missing = {i.requirement_id for i in c.items if i.status == "missing"}
    assert "SER-002" in missing or "SER-004" in missing  # 초안에서 일부러 뺀 보안 요구사항
    assert "SFR-001" not in missing


def test_checkpoint_resume(report: ReviewReport, tmp_path):
    out = tmp_path / "o"
    pipe = Pipeline(SAMPLE, out, draft=DRAFT, llm=LLM(mode="mock"))
    pipe.run(stop="risk")
    assert (out / "checkpoints" / "risk.json").exists()
    rep2 = Pipeline(SAMPLE, out, draft=DRAFT, llm=LLM(mode="mock")).run(start="export")
    data = json.loads((out / "report.json").read_text(encoding="utf-8"))
    assert data["summary"]["requirement_count"] == rep2.summary.requirement_count == report.summary.requirement_count
