"""배송 네트워크 시뮬레이터와 배차 정책. 결정적이다(같은 시나리오·시드면 같은 결과).

모형은 작다. 허브 하나, 노선 여러 개, 트럭 N대, 화물 M건. 트럭은 한 번에 한 건을 싣고 왕복한다.
교란은 트럭 결항, 노선 이동시간 배율, 출고 준비 지연 세 가지로 표현한다.
정책은 '트럭이 비었을 때 준비된 화물 중 무엇을 먼저 보내는가'만 정한다. 나머지는 모두 같다.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import timedelta
from typing import Callable

from .exposure import apply_customer_period_cap, compute_penalty
from .schemas import (Breakdown, Customer, DispatchRecord, ForceMajeureJudgment, PenaltyTerms, PolicyResult,
                      Scenario, Shipment)

ROUTES = {  # 노선: 편도 시간(시간)
    "N1": 2.0, "N2": 3.0, "S1": 4.0, "S2": 5.0, "S3": 6.0, "P1": 3.5, "P2": 4.5, "E1": 2.5,
}
VALUE_RANGE = {  # 고객 세그먼트별 건당 화물가액(원) 범위
    "A": (80_000_000, 160_000_000), "B": (20_000_000, 60_000_000), "C": (40_000_000, 90_000_000),
    "D": (30_000_000, 70_000_000), "E": (15_000_000, 40_000_000), "F": (10_000_000, 30_000_000),
    "G": (50_000_000, 120_000_000), "H": (60_000_000, 140_000_000),
}


def build_shipments(scenario: Scenario, customers: list[Customer]) -> list[Shipment]:
    rng = random.Random(scenario.seed)
    routes = list(ROUTES)
    out: list[Shipment] = []
    for c in customers:
        lo, hi = VALUE_RANGE.get(c.id, (20_000_000, 80_000_000))
        for k in range(scenario.shipments_per_customer):
            route = rng.choice(routes)
            ready = round(rng.uniform(0, 16), 1)
            slack = rng.uniform(1, 12)
            out.append(Shipment(id=f"{c.id}{k + 1:02d}", customer_id=c.id, value_krw=int(rng.uniform(lo, hi) // 1_000_000 * 1_000_000),
                                ready_h=ready, due_h=round(ready + ROUTES[route] + slack, 1), route=route, travel_h=ROUTES[route]))
    d = scenario.disruption
    if d.ready_delay_h > 0:
        pool = [s for s in out if not d.ready_delay_routes or s.route in d.ready_delay_routes]
        rng2 = random.Random(scenario.seed + 1)
        rng2.shuffle(pool)
        n = round(len(pool) * d.ready_delay_share)
        hit = {s.id for s in pool[:n]}
        out = [s.model_copy(update={"ready_h": s.ready_h + d.ready_delay_h}) if s.id in hit else s for s in out]
    return sorted(out, key=lambda s: (s.ready_h, s.id))


def travel_time(scenario: Scenario, route: str, t: float) -> float:
    d = scenario.disruption
    base = ROUTES[route]
    if route in d.route_multipliers and d.route_multiplier_from_h <= t < d.route_multiplier_until_h:
        return base * d.route_multipliers[route]
    return base


@dataclass
class Context:
    scenario: Scenario
    terms: dict[str, PenaltyTerms]
    judgments: dict[str, ForceMajeureJudgment]
    customers: dict[str, Customer]

    def penalty(self, s: Shipment, delivered_h: float) -> Breakdown:
        due_at = self.scenario.t0 + timedelta(hours=s.due_h)
        return compute_penalty(self.terms[s.customer_id], shipment_id=s.id, delay_hours=delivered_h - s.due_h,
                               shipment_value_krw=s.value_krw, due_at=due_at, judgment=self.judgments.get(s.customer_id))


@dataclass
class State:
    t: float
    free_trucks: int
    waiting: list[Shipment]
    avg_cycle_h: float
    decisions: dict[str, str] = field(default_factory=dict)


Policy = Callable[[State, Context], Shipment]


def deadline_first(state: State, ctx: Context) -> Shipment:
    return min(state.waiting, key=lambda s: (s.due_h, s.id))


def value_first(state: State, ctx: Context) -> Shipment:
    return max(state.waiting, key=lambda s: (s.value_krw, -s.due_h))


def fifo(state: State, ctx: Context) -> Shipment:
    return min(state.waiting, key=lambda s: (s.ready_h, s.id))


def marginal_exposure(state: State, ctx: Context, s: Shipment, defer_h: float | None = None) -> tuple[int, int, Breakdown]:
    """지금 보낼 때와 한 사이클 미룰 때의 페널티. 차이가 '기다리게 했을 때 물리는 돈'이다."""
    defer = state.avg_cycle_h if defer_h is None else defer_h
    now_eta = state.t + travel_time(ctx.scenario, s.route, state.t)
    later_eta = state.t + defer + travel_time(ctx.scenario, s.route, state.t + defer)
    b_now = ctx.penalty(s, now_eta)
    b_later = ctx.penalty(s, later_eta)
    return b_now.penalty_krw, b_later.penalty_krw, b_later


def _exposure_key(state: State, ctx: Context, s: Shipment, per_hour: bool):
    now_p, later_p, _ = marginal_exposure(state, ctx, s)
    marginal = later_p - now_p
    occupancy = 2 * travel_time(ctx.scenario, s.route, state.t)
    score = marginal / occupancy if per_hour else marginal
    return (-score, -later_p, s.due_h, s.id)


def exposure_first(state: State, ctx: Context) -> Shipment:
    """물리는 순서. 한 사이클 미뤘을 때 늘어나는 페널티('물리는 돈')를 그 화물이 트럭을 묶어 두는 시간으로 나눈 값이
    큰 화물부터 보낸다. 같으면 미뤘을 때의 페널티가 큰 순, 그다음 마감이 급한 순. 30개 시드 평가에서 절대값 변형보다 평균이 낮았다."""
    chosen = min(state.waiting, key=lambda s: _exposure_key(state, ctx, s, per_hour=True))
    now_p, later_p, b = marginal_exposure(state, ctx, chosen)
    state.decisions[chosen.id] = f"미루면 +{later_p - now_p:,}원" + (f" ({b.blocked_by})" if b.blocked_by else "")
    return chosen


def exposure_abs(state: State, ctx: Context) -> Shipment:
    """변형: 트럭 점유 시간으로 나누지 않은 '물리는 돈' 절대값 순. 비교용."""
    return min(state.waiting, key=lambda s: _exposure_key(state, ctx, s, per_hour=False))


POLICIES: dict[str, tuple[str, Policy]] = {
    "deadline_first": ("마감 급한 순(기존)", deadline_first),
    "fifo": ("도착 순", fifo),
    "value_first": ("고액 화물 순", value_first),
    "exposure_first": ("물리는 순서(ClauseTower)", exposure_first),
    "exposure_abs": ("물리는 순서(절대값 변형)", exposure_abs),
}


def run_policy(scenario: Scenario, shipments: list[Shipment], ctx: Context, policy: Policy, policy_id: str,
               label: str, order: list[str] | None = None) -> PolicyResult:
    """이벤트 기반 시뮬레이션. order가 주어지면 정책 대신 그 우선순위 목록을 따른다(탐색용)."""
    d = scenario.disruption
    n = scenario.trucks
    truck_free = [0.0] * n
    for i in range(min(d.trucks_out, n)):
        truck_free[i] = max(truck_free[i], d.trucks_out_until_h) if d.trucks_out_from_h <= 0 else truck_free[i]
    pending = list(shipments)
    records: list[DispatchRecord] = []
    breakdowns: dict[str, list[Breakdown]] = {}
    rank = {sid: i for i, sid in enumerate(order)} if order else None
    peak: tuple[float, list[str]] = (0.0, [])
    avg_cycle = 2 * sum(ROUTES.values()) / len(ROUTES) / max(1, n - d.trucks_out)
    t = 0.0
    while pending:
        i = min(range(n), key=lambda k: truck_free[k])
        t = max(t, truck_free[i])
        if d.trucks_out and d.trucks_out_from_h > 0 and i < d.trucks_out and d.trucks_out_from_h <= t < d.trucks_out_until_h:
            truck_free[i] = d.trucks_out_until_h
            continue
        waiting = [s for s in pending if s.ready_h <= t]
        if not waiting:
            t = min(s.ready_h for s in pending)
            truck_free[i] = max(truck_free[i], t)
            continue
        free_count = sum(1 for k in range(n) if truck_free[k] <= t)
        state = State(t=t, free_trucks=free_count, waiting=waiting, avg_cycle_h=avg_cycle)
        if len(waiting) > len(peak[1]):
            peak = (t, [w.id for w in waiting])
        chosen = min(waiting, key=lambda s: rank[s.id]) if rank else policy(state, ctx)
        tt = travel_time(scenario, chosen.route, t)
        delivered = t + tt
        truck_free[i] = t + 2 * tt
        b = ctx.penalty(chosen, delivered)
        breakdowns.setdefault(chosen.customer_id, []).append(b)
        records.append(DispatchRecord(shipment_id=chosen.id, customer_id=chosen.customer_id, truck=i, dispatched_h=round(t, 2),
                                      delivered_h=round(delivered, 2), due_h=chosen.due_h, delay_h=round(max(0.0, delivered - chosen.due_h), 2),
                                      penalty_krw=b.penalty_krw, blocked_by=b.blocked_by, rank_reason=state.decisions.get(chosen.id)))
        pending.remove(chosen)
    # 고객·기간 상한은 인도 시간순으로 적용한다
    per_customer: dict[str, int] = {}
    final_penalty: dict[str, int] = {}
    for cid, bs in breakdowns.items():
        bs_sorted = sorted(bs, key=lambda b: next(r.delivered_h for r in records if r.shipment_id == b.shipment_id))
        for b in apply_customer_period_cap(ctx.terms[cid], bs_sorted):
            final_penalty[b.shipment_id] = b.penalty_krw
        per_customer[cid] = sum(final_penalty[b.shipment_id] for b in bs)
    records = [r.model_copy(update={"penalty_krw": final_penalty[r.shipment_id]}) for r in records]
    curve: list[tuple[float, int]] = []
    acc = 0
    for r in sorted(records, key=lambda r: r.delivered_h):
        acc += r.penalty_krw
        curve.append((r.delivered_h, acc))
    return PolicyResult(policy=policy_id, label=label, total_penalty_krw=sum(per_customer.values()),
                        late_count=sum(1 for r in records if r.delay_h > 0), on_time_count=sum(1 for r in records if r.delay_h <= 0),
                        records=records, per_customer_krw=per_customer, penalty_curve=curve,
                        peak_queue_h=peak[0], peak_queue_ids=peak[1])


def search_best_order(scenario: Scenario, shipments: list[Shipment], ctx: Context, *, restarts: int = 12,
                      sweeps: int = 3, seed: int = 0, start: list[str] | None = None) -> PolicyResult:
    """근사 최적: 우선순위 순열에 대한 지역 탐색(인접·임의 교환). 상한선을 보여 주는 용도다."""
    rng = random.Random(seed)
    ids = [s.id for s in shipments]

    def evaluate(order: list[str]) -> int:
        return run_policy(scenario, shipments, ctx, deadline_first, "search", "탐색", order=order).total_penalty_krw

    best_order = list(start) if start else sorted(ids)
    best = evaluate(best_order)
    for r in range(restarts):
        order = list(best_order) if r == 0 else rng.sample(ids, len(ids))
        cur = evaluate(order)
        for _ in range(sweeps):
            improved = False
            for i in range(len(order) - 1):
                for j in (i + 1, rng.randrange(len(order))):
                    if j == i:
                        continue
                    order[i], order[j] = order[j], order[i]
                    v = evaluate(order)
                    if v < cur:
                        cur, improved = v, True
                    else:
                        order[i], order[j] = order[j], order[i]
            if not improved:
                break
        if cur < best:
            best, best_order = cur, list(order)
    res = run_policy(scenario, shipments, ctx, deadline_first, "search_best", "탐색 근사 최적(참고)", order=best_order)
    return res
