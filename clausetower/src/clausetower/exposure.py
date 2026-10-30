"""지연 배상금 계산기. 결정적이고 순수하다. LLM은 여기 들어오지 않는다.

입력은 계약에서 뽑은 PenaltyTerms, 지연 시간, 기준금액, 그리고 불가항력 판단이다.
출력은 금액과 함께 '왜 이 금액인가'를 단계별 문장으로 남긴 Breakdown이다. 설명과 인용은 이 단계 문장에서 나온다.
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta

from .schemas import Breakdown, Citation, ForceMajeureJudgment, PenaltyTerms

HOURS_PER_DAY = 24.0


def _base_amount(terms: PenaltyTerms, shipment_value_krw: int) -> int:
    if terms.base == "shipment_value":
        return shipment_value_krw
    if terms.base_amount_krw is None:
        raise ValueError(f"{terms.customer_id}: base={terms.base}인데 base_amount_krw가 없다")
    return terms.base_amount_krw


def _business_day_units(due_at: datetime, effective_hours: float, rounds_up: bool) -> float:
    """유예가 끝난 시점부터 24시간 단위로 걸어가며 평일에 시작하는 단위만 센다."""
    if effective_hours <= 0:
        return 0.0
    units = 0.0
    cursor = due_at
    remaining = effective_hours
    while remaining > 0:
        step = min(HOURS_PER_DAY, remaining)
        if cursor.weekday() < 5:
            units += 1.0 if rounds_up else step / HOURS_PER_DAY
        cursor += timedelta(hours=HOURS_PER_DAY)
        remaining -= step
    return units


def compute_penalty(
    terms: PenaltyTerms,
    *,
    shipment_id: str,
    delay_hours: float,
    shipment_value_krw: int,
    due_at: datetime,
    judgment: ForceMajeureJudgment | None = None,
) -> Breakdown:
    steps: list[str] = []
    cites: list[Citation] = []
    base = _base_amount(terms, shipment_value_krw)
    delay_hours = max(0.0, delay_hours)

    def done(penalty: int, uncapped: int, *, units: float, effective: float, blocked: str | None = None, capped=False):
        return Breakdown(customer_id=terms.customer_id, shipment_id=shipment_id, delay_hours=round(delay_hours, 2),
                         effective_delay_hours=round(effective, 2), units=units, penalty_krw=int(penalty),
                         uncapped_krw=int(uncapped), capped=capped, blocked_by=blocked, steps=steps, citations=cites)

    if delay_hours <= 0:
        steps.append("지연 없음. 배상금 0원.")
        return done(0, 0, units=0, effective=0)

    # 1) 불가항력
    if judgment is not None and judgment.has_clause:
        if judgment.applies:
            steps.append(f"불가항력 조항 적용: {judgment.reasoning}")
            if judgment.citation:
                cites.append(judgment.citation)
            return done(0, 0, units=0, effective=0, blocked="불가항력 면책")
        steps.append(f"불가항력 조항 있으나 미적용: {judgment.reasoning}")
        if judgment.citation:
            cites.append(judgment.citation)
    elif terms.force_majeure is None:
        steps.append("불가항력 조항 없음. 사유를 불문하고 지연 배상금이 발생한다.")

    # 2) 유예
    effective = delay_hours - terms.grace_hours
    if terms.grace_hours > 0:
        if "grace" in terms.citations:
            cites.append(terms.citations["grace"])
        if effective <= 0:
            steps.append(f"지연 {delay_hours:.1f}시간은 유예 {terms.grace_hours:.0f}시간 이내. 배상금 0원.")
            return done(0, 0, units=0, effective=0, blocked="유예기간 내")
        steps.append(f"지연 {delay_hours:.1f}시간 중 유예 {terms.grace_hours:.0f}시간을 뺀 {effective:.1f}시간이 과금 대상.")
    else:
        steps.append(f"유예 없음. 지연 {delay_hours:.1f}시간 전체가 과금 대상.")

    # 3) 단위와 요율
    if "rate" in terms.citations:
        cites.append(terms.citations["rate"])
    units = 0.0
    if terms.basis == "per_hour":
        units = math.ceil(effective) if terms.partial_unit_rounds_up else effective
        amount = base * (terms.rate_pct or 0) / 100 * units
        steps.append(f"시간당 {terms.rate_pct}% × {units:g}시간 × 기준금액 {base:,}원 = {amount:,.0f}원")
    elif terms.basis == "per_calendar_day":
        units = math.ceil(effective / HOURS_PER_DAY) if terms.partial_unit_rounds_up else effective / HOURS_PER_DAY
        amount = base * (terms.rate_pct or 0) / 100 * units
        steps.append(f"일당 {terms.rate_pct}% × {units:g}일(역일) × 기준금액 {base:,}원 = {amount:,.0f}원")
    elif terms.basis == "per_business_day":
        units = _business_day_units(due_at + timedelta(hours=terms.grace_hours), effective, terms.partial_unit_rounds_up)
        amount = base * (terms.rate_pct or 0) / 100 * units
        steps.append(f"일당 {terms.rate_pct}% × {units:g}일(영업일, 주말 제외) × 기준금액 {base:,}원 = {amount:,.0f}원")
    elif terms.basis == "tiered_per_day":
        days = math.ceil(effective / HOURS_PER_DAY)
        units = days
        amount = 0.0
        parts = []
        for tier in terms.tiers:
            lo = tier.from_day
            hi = tier.to_day if tier.to_day is not None else days
            n = max(0, min(days, hi) - lo + 1)
            if n:
                piece = base * tier.rate_pct / 100 * n
                amount += piece
                parts.append(f"{lo}~{hi}일차 {tier.rate_pct}%×{n}일={piece:,.0f}원")
        steps.append(f"계단식 {days}일: " + ", ".join(parts) + f" → 합계 {amount:,.0f}원")
    elif terms.basis == "flat_per_shipment":
        units = 1
        amount = float(terms.flat_amount_krw or 0)
        label = f"지연 건당 정액 {amount:,.0f}원"
        if terms.flat_escalation and delay_hours > terms.flat_escalation.after_hours:
            amount = float(terms.flat_escalation.amount_krw)
            label = f"지연 {delay_hours:.1f}시간 > {terms.flat_escalation.after_hours:.0f}시간, 가중 정액 {amount:,.0f}원"
        steps.append(label)
    else:
        raise ValueError(f"알 수 없는 basis: {terms.basis}")

    uncapped = int(round(amount))

    # 4) 건별 상한
    penalty = uncapped
    capped = False
    if terms.cap_scope == "shipment":
        cap = None
        if terms.cap_pct is not None:
            cap = base * terms.cap_pct / 100
        if terms.cap_amount_krw is not None:
            cap = min(cap, terms.cap_amount_krw) if cap is not None else terms.cap_amount_krw
        if cap is not None:
            if "cap" in terms.citations:
                cites.append(terms.citations["cap"])
            if penalty > cap:
                steps.append(f"상한 {cap:,.0f}원에 걸려 {penalty:,}원 → {cap:,.0f}원")
                penalty = int(round(cap))
                capped = True
            else:
                steps.append(f"상한 {cap:,.0f}원 이내.")
        else:
            steps.append("상한 없음.")
    return done(penalty, uncapped, units=units, effective=effective, capped=capped)


def apply_customer_period_cap(terms: PenaltyTerms, breakdowns: list[Breakdown]) -> list[Breakdown]:
    """고객·기간 합계 상한. 시간순으로 더해 가다 상한에 닿으면 이후 건은 0원이 된다."""
    if terms.cap_scope != "customer_period":
        return breakdowns
    cap = None
    if terms.cap_amount_krw is not None:
        cap = terms.cap_amount_krw
    if terms.cap_pct is not None and terms.base_amount_krw is not None:
        c = terms.base_amount_krw * terms.cap_pct / 100
        cap = min(cap, c) if cap is not None else c
    if cap is None:
        return breakdowns
    running = 0
    out: list[Breakdown] = []
    for b in breakdowns:
        allowed = max(0, int(round(cap)) - running)
        if b.penalty_krw > allowed:
            b = b.model_copy(update={
                "penalty_krw": allowed, "capped": True,
                "steps": b.steps + [f"고객 합계 상한 {cap:,.0f}원: 누적 {running:,}원 → 이 건은 {allowed:,}원만 과금"],
                "citations": b.citations + ([terms.citations["cap"]] if "cap" in terms.citations else []),
            })
        running += b.penalty_krw
        out.append(b)
    return out
