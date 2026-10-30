"""배상금 계산기. 돈 계산은 여기서 전부 검증한다."""
from datetime import datetime

import pytest

from clausetower.exposure import apply_customer_period_cap, compute_penalty
from clausetower.schemas import FlatEscalation, PenaltyTerms, Tier

from conftest import FRI, MON, cite, judgment


def pen(terms, delay, value=100_000_000, due=MON, j=None):
    return compute_penalty(terms, shipment_id="S", delay_hours=delay, shipment_value_krw=value, due_at=due, judgment=j)


def test_no_delay_is_zero(daily_terms):
    b = pen(daily_terms, 0)
    assert b.penalty_krw == 0 and b.blocked_by is None and "지연 없음" in b.steps[0]


def test_grace_blocks_small_delay(daily_terms):
    b = pen(daily_terms, 20)
    assert b.penalty_krw == 0 and b.blocked_by == "유예기간 내"
    assert any(c.clause == "제12조 제2항" for c in b.citations)


def test_partial_day_rounds_up_after_grace(daily_terms):
    b = pen(daily_terms, 25)  # 유예 24h 뒤 1시간 → 1일
    assert b.units == 1 and b.penalty_krw == 100_000
    b = pen(daily_terms, 24 + 48.5)  # 48.5h → 3일
    assert b.units == 3 and b.penalty_krw == 300_000


def test_cap_applies_and_is_cited(daily_terms):
    b = pen(daily_terms, 24 + 24 * 200)  # 200일 → 20% > 상한 10%
    assert b.capped and b.penalty_krw == 10_000_000 and b.uncapped_krw == 20_000_000
    assert any(c.clause == "제12조 제3항" for c in b.citations)


def test_force_majeure_applies_zeroes_and_cites(daily_terms):
    b = pen(daily_terms, 100, j=judgment(True, reasoning="태풍은 제15조 사유"))
    assert b.penalty_krw == 0 and b.blocked_by == "불가항력 면책"
    assert "태풍은 제15조 사유" in b.steps[0] and b.citations[0].clause == "제15조"


def test_force_majeure_not_applying_still_charges(daily_terms):
    b = pen(daily_terms, 100, j=judgment(False, reasoning="통지 지연"))
    assert b.penalty_krw > 0 and "미적용" in b.steps[0]


def test_hourly_no_cap_no_fm():
    t = PenaltyTerms(customer_id="B", basis="per_hour", rate_pct=0.05, grace_hours=0)
    b = pen(t, 10.2, value=40_000_000)
    assert b.units == 11 and b.penalty_krw == 220_000 and not b.capped
    assert "불가항력 조항 없음" in b.steps[0] and "상한 없음" in b.steps[-1]


def test_business_days_skip_weekend():
    t = PenaltyTerms(customer_id="F", basis="per_business_day", rate_pct=0.2, grace_hours=0, cap_pct=5)
    # 금요일 06:00 마감, 72시간 지연 → 금, 토, 일 중 금요일만 영업일
    b = pen(t, 72, value=10_000_000, due=FRI)
    assert b.units == 1 and b.penalty_krw == 20_000
    # 월요일 마감, 72시간 → 월, 화, 수
    assert pen(t, 72, value=10_000_000, due=MON).units == 3


def test_tiered_sums_each_band():
    t = PenaltyTerms(customer_id="D", basis="tiered_per_day", cap_pct=15,
                     tiers=[Tier(from_day=1, to_day=2, rate_pct=0.1), Tier(from_day=3, to_day=5, rate_pct=0.2), Tier(from_day=6, rate_pct=0.5)])
    b = pen(t, 24 * 7, value=10_000_000)  # 7일: 0.1×2 + 0.2×3 + 0.5×2 = 1.8%
    assert b.penalty_krw == 180_000 and "6~7일차" in b.steps[-2]


def test_flat_with_escalation():
    t = PenaltyTerms(customer_id="E", basis="flat_per_shipment", flat_amount_krw=500_000,
                     flat_escalation=FlatEscalation(after_hours=24, amount_krw=2_000_000), cap_amount_krw=20_000_000, cap_scope="customer_period")
    assert pen(t, 3).penalty_krw == 500_000
    assert pen(t, 30).penalty_krw == 2_000_000


def test_customer_period_cap_accumulates_in_order():
    t = PenaltyTerms(customer_id="E", basis="flat_per_shipment", flat_amount_krw=2_000_000, cap_amount_krw=5_000_000,
                     cap_scope="customer_period", citations={"cap": cite("제9조 제3항", "합계 20,000,000원")})
    bs = [pen(t, 30) for _ in range(4)]
    out = apply_customer_period_cap(t, bs)
    assert [b.penalty_krw for b in out] == [2_000_000, 2_000_000, 1_000_000, 0]
    assert out[2].capped and out[3].capped and "고객 합계 상한" in out[2].steps[-1]


def test_monthly_fee_base_and_period_cap():
    t = PenaltyTerms(customer_id="G", basis="per_hour", rate_pct=0.05, grace_hours=6, base="monthly_fee",
                     base_amount_krw=180_000_000, cap_pct=20, cap_scope="customer_period")
    b = pen(t, 8, value=1)  # 기준은 월 서비스료. 유예 6h 뒤 2시간
    assert b.units == 2 and b.penalty_krw == 180_000
    out = apply_customer_period_cap(t, [pen(t, 6 + 1000, value=1)])  # 1000h → 9천만 > 상한 3천6백만
    assert out[0].penalty_krw == 36_000_000


def test_missing_base_amount_is_an_error():
    t = PenaltyTerms(customer_id="G", basis="per_hour", rate_pct=0.05, base="monthly_fee")
    with pytest.raises(ValueError, match="base_amount_krw"):
        pen(t, 10)


def test_steps_explain_every_number(daily_terms):
    b = pen(daily_terms, 24 + 30)
    text = " ".join(b.steps)
    assert "유예 24시간" in text and "일당 0.1%" in text and "2일" in text and "상한" in text
