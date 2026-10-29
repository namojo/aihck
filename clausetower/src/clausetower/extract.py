"""LLM 단계 둘: 계약서 → PenaltyTerms(extract), 사건 × 계약 → 불가항력 판단(judge).

mock 모드는 정답지를 그대로 돌려준다. 그래서 mock에서 추출 정확도는 의미가 없고, 실제 모드에서만 측정한다.
"""

from __future__ import annotations

from .contracts import load_contract_text, load_golden_judgment, load_golden_terms
from .llm import LLM, load_prompt
from .schemas import EventContext, ExtractionResult, ForceMajeureJudgment, PenaltyTerms


def extract_terms(llm: LLM, customer_id: str) -> ExtractionResult:
    text = load_contract_text(customer_id)
    user = f"고객 ID: {customer_id}\n\n--- 계약서 전문 ---\n{text}"

    def mock() -> ExtractionResult:
        return ExtractionResult(terms=load_golden_terms(customer_id), confidence=1.0,
                                ambiguities=["mock 모드: 정답지를 그대로 사용"])

    result = llm.parse(stage="extract", system=load_prompt("extract"), user=user, schema=ExtractionResult, mock_fn=mock)
    if result.terms.customer_id != customer_id:
        result = result.model_copy(update={"terms": result.terms.model_copy(update={"customer_id": customer_id})})
    return result


def judge_force_majeure(llm: LLM, customer_id: str, terms: PenaltyTerms, event: EventContext,
                        scenario_id: str) -> ForceMajeureJudgment:
    text = load_contract_text(customer_id)
    notice = (f"운영팀은 사건 발생 {event.notice_sent_after_hours:g}시간 뒤에 고객에게 통지했다."
              if event.notice_sent_after_hours is not None else "운영팀은 고객에게 통지하지 않았다.")
    facts = "\n".join(f"- {k}: {'예' if v else '아니오'}" for k, v in event.facts.items()) or "- (추가 사실 없음)"
    clause = (f"추출된 불가항력 조항: 사유 {terms.force_majeure.covered_events}, 통지 시한 {terms.force_majeure.notice_hours}시간, "
              f"조건 {terms.force_majeure.conditions}" if terms.force_majeure else "추출 결과: 불가항력 조항 없음")
    user = (f"고객 ID: {customer_id}\n\n--- 사건 ---\n유형: {event.event_type}\n설명: {event.description}\n{notice}\n"
            f"사실 관계:\n{facts}\n\n{clause}\n\n--- 계약서 전문 ---\n{text}")

    def mock() -> ForceMajeureJudgment:
        return load_golden_judgment(customer_id, scenario_id)

    j = llm.parse(stage="judge", system=load_prompt("judge"), user=user, schema=ForceMajeureJudgment, mock_fn=mock)
    if j.customer_id != customer_id:
        j = j.model_copy(update={"customer_id": customer_id})
    # 계산기가 쓰는 최종 플래그는 기계적으로 다시 만든다. 모델이 applies만 뒤집는 실수를 막는다.
    derived = j.has_clause and j.event_covered and j.notice_ok and all(j.conditions_met.values())
    if derived != j.applies:
        j = j.model_copy(update={"applies": derived, "reasoning": j.reasoning + " (최종 적용 여부는 조건을 기계적으로 결합해 확정)"})
    return j
