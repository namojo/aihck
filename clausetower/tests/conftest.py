import os
import sys
from datetime import datetime
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
os.environ.setdefault("CLAUSETOWER_LLM", "mock")

from clausetower.schemas import Citation, ForceMajeure, ForceMajeureJudgment, PenaltyTerms  # noqa: E402

MON = datetime(2026, 11, 2, 6, 0)   # 월요일 06:00
FRI = datetime(2026, 11, 6, 6, 0)   # 금요일 06:00


def cite(clause="제1조", quote="원문"):
    return Citation(clause=clause, quote=quote)


@pytest.fixture
def daily_terms():
    return PenaltyTerms(customer_id="X", basis="per_calendar_day", rate_pct=0.1, grace_hours=24, cap_pct=10,
                        citations={"rate": cite("제12조 제1항", "1,000분의 1"), "grace": cite("제12조 제2항", "24시간"),
                                   "cap": cite("제12조 제3항", "100분의 10")},
                        force_majeure=ForceMajeure(covered_events=["태풍"], notice_hours=24, citation=cite("제15조", "태풍")))


def judgment(applies: bool, has_clause: bool = True, reasoning="근거"):
    return ForceMajeureJudgment(customer_id="X", has_clause=has_clause, event_covered=applies, notice_ok=True,
                                applies=applies, reasoning=reasoning, citation=cite("제15조", "태풍"))
