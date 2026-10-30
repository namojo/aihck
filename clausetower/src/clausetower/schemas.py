"""데이터 계약. 여기를 바꾸면 export, 대시보드, eval이 함께 바뀐다. 필드 추가는 Optional로."""

from __future__ import annotations

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class Citation(BaseModel):
    clause: str = Field(description="조항 번호. 예: 제12조 제2항")
    quote: str = Field(description="계약서 원문을 그대로 옮긴 문장. 요약하지 않는다.")


class Tier(BaseModel):
    from_day: int = Field(description="이 구간이 시작되는 지연 일수(1부터)")
    to_day: Optional[int] = Field(default=None, description="이 구간이 끝나는 지연 일수. 끝이 없으면 null")
    rate_pct: float = Field(description="이 구간의 일당 요율(기준금액의 %)")


class FlatEscalation(BaseModel):
    after_hours: float = Field(description="이 시간을 넘긴 지연부터 가중 정액이 적용된다")
    amount_krw: int = Field(description="가중 정액(원)")


class ForceMajeure(BaseModel):
    covered_events: list[str] = Field(description="계약서에 적힌 면책 사유를 적힌 그대로. 예: ['태풍', '지진'] 또는 ['천재지변 일체']")
    notice_hours: Optional[float] = Field(default=None, description="면책을 주장하려면 발생 후 이 시간 안에 통지해야 한다. 없으면 null")
    conditions: list[str] = Field(default_factory=list, description="면책에 붙은 정성 조건. 예: '대체 운송수단 확보 노력을 입증'")
    citation: Citation


class PenaltyTerms(BaseModel):
    """계약서에서 뽑은 지연 배상 조건. 계산기(exposure.py)의 입력이다."""

    customer_id: str
    basis: Literal["per_calendar_day", "per_business_day", "per_hour", "flat_per_shipment", "tiered_per_day"]
    rate_pct: Optional[float] = Field(default=None, description="단위당 요율(기준금액의 %). flat과 tiered는 null")
    flat_amount_krw: Optional[int] = Field(default=None, description="flat_per_shipment일 때 건당 정액(원)")
    flat_escalation: Optional[FlatEscalation] = None
    tiers: list[Tier] = Field(default_factory=list, description="tiered_per_day일 때 구간표")
    grace_hours: float = Field(default=0, description="유예 시간. 이 범위의 지연은 배상금이 없다")
    base: Literal["shipment_value", "monthly_fee", "contract_value"] = "shipment_value"
    base_amount_krw: Optional[int] = Field(default=None, description="base가 monthly_fee나 contract_value일 때 그 금액(원)")
    cap_pct: Optional[float] = Field(default=None, description="상한(기준금액의 %). 없으면 null")
    cap_amount_krw: Optional[int] = Field(default=None, description="상한 금액(원). 없으면 null")
    cap_scope: Literal["shipment", "customer_period"] = Field(default="shipment", description="상한이 건별인지 고객·기간 합계인지")
    partial_unit_rounds_up: bool = Field(default=True, description="1단위 미만 지연을 1단위로 올림하는지")
    force_majeure: Optional[ForceMajeure] = Field(default=None, description="불가항력 조항. 없으면 null")
    citations: dict[str, Citation] = Field(default_factory=dict, description="항목별 근거. 키: rate, grace, cap, basis 등")
    notes: Optional[str] = None


class ExtractionResult(BaseModel):
    terms: PenaltyTerms
    confidence: float = Field(ge=0, le=1, description="추출 확신도 0~1")
    ambiguities: list[str] = Field(default_factory=list, description="해석이 갈릴 수 있는 지점")


class ForceMajeureJudgment(BaseModel):
    """이번 사건에 이 고객의 불가항력 조항이 실제로 적용되는지에 대한 판단."""

    customer_id: str
    has_clause: bool
    event_covered: bool = Field(description="이번 사건이 조항의 면책 사유에 해당하는가")
    notice_ok: bool = Field(description="통지 요건이 있다면 충족했는가. 요건이 없으면 true")
    conditions_met: dict[str, bool] = Field(default_factory=dict, description="정성 조건별 충족 여부")
    applies: bool = Field(description="최종 판단: 면책이 적용되는가")
    reasoning: str = Field(description="두세 문장. 조항 문구와 사건 사실을 대조한 근거")
    citation: Optional[Citation] = None


class EventContext(BaseModel):
    event_type: str
    description: str
    onset_hours: float = 0
    notice_sent_after_hours: Optional[float] = Field(default=None, description="운영팀이 고객에게 통지한 시점(발생 후 시간). 안 했으면 null")
    facts: dict[str, bool] = Field(default_factory=dict, description="정성 조건 판단에 쓰는 사실. 예: 대체운송_노력_입증: false")


class Breakdown(BaseModel):
    customer_id: str
    shipment_id: str
    delay_hours: float
    effective_delay_hours: float
    units: float
    penalty_krw: int
    uncapped_krw: int
    capped: bool
    blocked_by: Optional[str] = None
    steps: list[str]
    citations: list[Citation] = Field(default_factory=list)


class Customer(BaseModel):
    id: str
    name: str
    segment: str
    monthly_fee_krw: Optional[int] = None
    contract_value_krw: Optional[int] = None


class Shipment(BaseModel):
    id: str
    customer_id: str
    value_krw: int
    ready_h: float
    due_h: float
    route: str
    travel_h: float


class Disruption(BaseModel):
    trucks_out: int = 0
    trucks_out_from_h: float = 0
    trucks_out_until_h: float = 0
    route_multipliers: dict[str, float] = Field(default_factory=dict)
    route_multiplier_from_h: float = 0
    route_multiplier_until_h: float = 0
    ready_delay_h: float = 0
    ready_delay_share: float = 0
    ready_delay_routes: list[str] = Field(default_factory=list)


class Scenario(BaseModel):
    id: str
    title: str
    description: str
    event: EventContext
    disruption: Disruption
    t0: datetime
    horizon_h: float = 72
    trucks: int = 10
    seed: int = 7
    shipments_per_customer: int = 5
    customer_facts: dict[str, dict[str, bool]] = Field(default_factory=dict)


class DispatchRecord(BaseModel):
    shipment_id: str
    customer_id: str
    truck: int
    dispatched_h: float
    delivered_h: float
    due_h: float
    delay_h: float
    penalty_krw: int
    blocked_by: Optional[str] = None
    rank_reason: Optional[str] = None


class PolicyResult(BaseModel):
    policy: str
    label: str
    total_penalty_krw: int
    late_count: int
    on_time_count: int
    records: list[DispatchRecord]
    per_customer_krw: dict[str, int]
    penalty_curve: list[tuple[float, int]] = Field(default_factory=list)
    peak_queue_h: float = 0
    peak_queue_ids: list[str] = Field(default_factory=list)


class RankRow(BaseModel):
    """대기열이 가장 길었던 시점의 '배상 노출 순위' 표 한 줄."""

    shipment_id: str
    customer_id: str
    customer_name: str
    due_in_h: float
    deadline_rank: int
    exposure_rank: int
    penalty_if_now_krw: int
    penalty_if_deferred_krw: int
    marginal_krw: int
    blocked_by: Optional[str]
    why: str
    citations: list[Citation]


class Report(BaseModel):
    scenario: Scenario
    customers: list[Customer]
    terms: dict[str, PenaltyTerms]
    extraction: dict[str, ExtractionResult]
    judgments: dict[str, ForceMajeureJudgment]
    ranking: list[RankRow]
    ranking_at_h: float = 0
    policies: dict[str, PolicyResult]
    savings_vs_deadline_krw: int
    savings_vs_deadline_pct: float
    llm_mode: str
    llm_calls: int
    generated_at: datetime
    agent_log: list[str] = Field(default_factory=list)
