"""파이프라인: 계약 읽기(LLM) → 면책 판단(LLM) → 노출액 산출(코드) → 정책 비교(시뮬레이터) → 보고서.

LLM이 제안하고 시뮬레이터가 판정한다. 어느 순서가 낫다는 결론은 시뮬레이션 숫자로만 낸다.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime

from .contracts import load_customers, load_scenario
from .extract import extract_terms, judge_force_majeure
from .llm import LLM
from .schemas import Customer, RankRow, Report
from .sim import POLICIES, Context, State, build_shipments, marginal_exposure, run_policy, search_best_order

log = logging.getLogger("clausetower.agent")


def ranking_at(ctx: Context, shipments, scenario, customers: dict[str, Customer], t: float, ids: list[str]) -> list[RankRow]:
    """특정 시점의 대기 화물에 대해 '마감 순서'와 '배상 노출 순'를 나란히 놓는다. 데모의 핵심 표다."""
    from .sim import ROUTES, travel_time
    waiting = [s for s in shipments if s.id in set(ids)]
    n = scenario.trucks - (scenario.disruption.trucks_out if scenario.disruption.trucks_out_from_h <= t < scenario.disruption.trucks_out_until_h else 0)
    avg_cycle = 2 * sum(ROUTES.values()) / len(ROUTES) / max(1, n)
    state = State(t=t, free_trucks=n, waiting=waiting, avg_cycle_h=avg_cycle)
    rows = []
    for s in waiting:
        now_p, later_p, b = marginal_exposure(state, ctx, s)
        occ = 2 * travel_time(scenario, s.route, t)
        rows.append((s, now_p, later_p, b, (later_p - now_p) / occ))
    by_deadline = sorted(rows, key=lambda r: (r[0].due_h, r[0].id))
    by_exposure = sorted(rows, key=lambda r: (-r[4], -r[2], r[0].due_h, r[0].id))
    d_rank = {r[0].id: i + 1 for i, r in enumerate(by_deadline)}
    e_rank = {r[0].id: i + 1 for i, r in enumerate(by_exposure)}
    out: list[RankRow] = []
    for s, now_p, later_p, b, _ in by_exposure:
        if b.blocked_by:
            why = f"{b.blocked_by}. 보류해도 배상금이 늘지 않는다."
        elif later_p - now_p == 0 and later_p == 0:
            why = "한 사이클 보류해도 마감 또는 유예 범위 안이다."
        else:
            why = " ".join(st for st in b.steps if "=" in st or "상한" in st or "정액" in st)[:160]
        out.append(RankRow(shipment_id=s.id, customer_id=s.customer_id, customer_name=customers[s.customer_id].name,
                           due_in_h=round(s.due_h - t, 1), deadline_rank=d_rank[s.id], exposure_rank=e_rank[s.id],
                           penalty_if_now_krw=now_p, penalty_if_deferred_krw=later_p, marginal_krw=later_p - now_p,
                           blocked_by=b.blocked_by, why=why, citations=b.citations[:2]))
    return out


def run(scenario_id: str, *, llm: LLM | None = None, with_search: bool = True,
        extraction_cache: dict | None = None) -> Report:
    llm = llm or LLM()
    agent_log: list[str] = []
    t0 = time.time()
    scenario = load_scenario(scenario_id)
    customers = load_customers()
    cmap = {c.id: c for c in customers}
    agent_log.append(f"시나리오 '{scenario.title}' 로드. 고객 {len(customers)}곳, LLM 모드 {llm.mode}.")

    if extraction_cache is not None and len(extraction_cache) == len(customers):
        extractions = dict(extraction_cache)
        agent_log.append("계약 추출 결과를 이전 실행에서 재사용(같은 계약서).")
    else:
        extractions = {c.id: r for c, r in zip(customers, llm.map(lambda c: extract_terms(llm, c.id), customers))}
        if extraction_cache is not None:
            extraction_cache.update(extractions)
    terms = {cid: r.terms for cid, r in extractions.items()}
    agent_log.append("계약서 8건에서 지연 배상 조건 추출 완료. " + ", ".join(
        f"{cid}:{t.basis}{'/상한無' if t.cap_pct is None and t.cap_amount_krw is None else ''}{'/면책無' if t.force_majeure is None else ''}"
        for cid, t in terms.items()))

    judgments = {c.id: j for c, j in zip(customers, llm.map(
        lambda c: judge_force_majeure(llm, c.id, terms[c.id], scenario.event, scenario.id), customers))}
    applied = [cid for cid, j in judgments.items() if j.applies]
    blocked = [f"{cid}({'통지 지연' if not j.notice_ok else '사유 불해당' if not j.event_covered else '조건 미충족'})"
               for cid, j in judgments.items() if j.has_clause and not j.applies]
    agent_log.append(f"불가항력 판단: 면책 적용 {applied or '없음'}, 조항은 있으나 미적용 {blocked or '없음'}.")

    shipments = build_shipments(scenario, customers)
    ctx = Context(scenario=scenario, terms=terms, judgments=judgments, customers=cmap)
    results = {}
    for pid, (label, fn) in POLICIES.items():
        results[pid] = run_policy(scenario, shipments, ctx, fn, pid, label)
    base_run = results["deadline_first"]
    ranking = ranking_at(ctx, shipments, scenario, cmap, base_run.peak_queue_h, base_run.peak_queue_ids)
    flips = [r for r in ranking if abs(r.deadline_rank - r.exposure_rank) >= 3]
    agent_log.append(f"대기열 최대 시점(+{base_run.peak_queue_h:.1f}h) 노출액 산출: 대기 화물 {len(ranking)}건, "
                     f"마감 순위와 노출 순위가 3계단 이상 갈린 화물 {len(flips)}건.")
    if with_search:
        results["search_best"] = search_best_order(scenario, shipments, ctx, start=[r.shipment_id for r in results["exposure_first"].records])
    base = results["deadline_first"].total_penalty_krw
    ours = results["exposure_first"].total_penalty_krw
    agent_log.append("시뮬레이션 비교(총 배상금): " + ", ".join(f"{r.label} {r.total_penalty_krw:,}원" for r in results.values()))
    savings = base - ours
    pct = (savings / base * 100) if base else 0.0
    agent_log.append(f"기존 대비 절감 {savings:,}원({pct:.1f}%). 소요 {time.time() - t0:.1f}초, LLM 호출 {llm.usage.calls}회"
                     + (f", 대체 {llm.usage.fallbacks}회" if llm.usage.fallbacks else ""))
    return Report(scenario=scenario, customers=customers, terms=terms, extraction=extractions, judgments=judgments,
                  ranking=ranking, ranking_at_h=base_run.peak_queue_h, policies=results, savings_vs_deadline_krw=savings, savings_vs_deadline_pct=round(pct, 1),
                  llm_mode=llm.mode, llm_calls=llm.usage.calls, generated_at=datetime.now(), agent_log=agent_log)


def resimulate(report: Report, *, with_search: bool = True) -> Report:
    """보고서의 LLM 결과(추출·판단)는 그대로 두고 시뮬레이션과 순위표만 다시 만든다. 정책을 고친 뒤 실제 모드 결과를 갱신할 때 쓴다."""
    scenario = report.scenario
    cmap = {c.id: c for c in report.customers}
    shipments = build_shipments(scenario, report.customers)
    ctx = Context(scenario=scenario, terms=report.terms, judgments=report.judgments, customers=cmap)
    results = {pid: run_policy(scenario, shipments, ctx, fn, pid, label) for pid, (label, fn) in POLICIES.items()}
    if with_search:
        results["search_best"] = search_best_order(scenario, shipments, ctx, start=[r.shipment_id for r in results["exposure_first"].records])
    base_run = results["deadline_first"]
    ranking = ranking_at(ctx, shipments, scenario, cmap, base_run.peak_queue_h, base_run.peak_queue_ids)
    base = base_run.total_penalty_krw
    ours = results["exposure_first"].total_penalty_krw
    savings = base - ours
    pct = (savings / base * 100) if base else 0.0
    log = [l for l in report.agent_log if not l.startswith(("시뮬레이션 비교", "기존 대비 절감", "대기열 최대 시점"))]
    log.append("시뮬레이션 비교(재실행): " + ", ".join(f"{r.label} {r.total_penalty_krw:,}원" for r in results.values()))
    log.append(f"기존 대비 절감 {savings:,}원({pct:.1f}%). LLM 결과는 원 실행({report.llm_mode}, {report.llm_calls}회)을 그대로 사용.")
    return report.model_copy(update={"ranking": ranking, "ranking_at_h": base_run.peak_queue_h, "policies": results,
                                     "savings_vs_deadline_krw": savings, "savings_vs_deadline_pct": round(pct, 1),
                                     "generated_at": datetime.now(), "agent_log": log})
