from pathlib import Path

import pytest

from rfpharness.parse import _is_heading, parse_pdf

SAMPLE = Path(__file__).resolve().parents[1] / "samples" / "sample_rfp.pdf"


@pytest.mark.parametrize("line,level", [
    ("Ⅰ. 사업 개요", 1), ("제 3 장 요구사항", 1), ("2. 사업 기간 및 예산", 2), ("가. 세부 내용", 3), ("1) 항목", 4),
])
def test_heading_patterns(line, level):
    h = _is_heading(line)
    assert h and h[0] == level


@pytest.mark.parametrize("line", ["SFR-001 통합 민원 접수", "12.5", "이 문장은 제목이 아니다. 요구사항을 포함한다."])
def test_non_headings(line):
    assert _is_heading(line) is None


@pytest.fixture(scope="module")
def doc():
    if not SAMPLE.exists():
        pytest.skip("samples/sample_rfp.pdf 없음 — python samples/make_sample_rfp.py 실행")
    return parse_pdf(SAMPLE)


def test_sample_structure(doc):
    assert doc.meta.page_count == 12
    assert not doc.meta.needs_ocr
    assert "제안요청서" in (doc.meta.title or "")
    # 요구사항 표 11종 + 현황 + 총괄 + 배점 + 일정 (페이지가 넘어가면 표가 나뉘어 더 많을 수 있다)
    assert len(doc.tables) >= 15


def test_requirement_tables_have_id_column(doc):
    req_tables = [t for t in doc.tables if any("고유번호" in h for h in t.header)]
    ids = [r[0] for t in req_tables for r in t.rows if r and r[0]]
    assert "SFR-001" in ids and "PSR-004" in ids
    assert len([i for i in ids if "-" in i]) == 44


def test_tables_assigned_to_right_section(doc):
    by_id = {t.table_id: t for t in doc.tables}
    sec = next(s for s in doc.sections if s.heading.endswith("8. 보안 요구사항"))
    ids = [r[0] for tid in sec.table_ids for r in by_id[tid].rows]
    assert "SER-001" in ids


def test_scoring_table_present(doc):
    assert any(any("배점" in h for h in t.header) for t in doc.tables)
