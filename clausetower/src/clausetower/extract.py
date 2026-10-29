"""LLM 단계 둘: 계약서 → PenaltyTerms(extract), 사건 × 계약 → 불가항력 판단(judge).

mock 모드는 정답지를 그대로 돌려준다. 그래서 mock에서 추출 정확도는 의미가 없고, 실제 모드에서만 측정한다.
"""

from __future__ import annotations

from .contracts import load_contract_text, load_golden_judgment, load_golden_terms
from .llm import LLM, load_prompt
from .schemas import EventContext, ExtractionResult, ForceMajeureJudgment, PenaltyTerms


def _mock_terms_for_text(customer_id: str) -> ExtractionResult:
    """정답지가 없는 임의 계약서에 대한 mock. 자리표시자임을 분명히 적는다."""
    return ExtractionResult(
        terms=PenaltyTerms(customer_id=customer_id, basis="per_calendar_day", rate_pct=0.1, grace_hours=0, cap_pct=10,
                           citations={"rate": {"clause": "(mock)", "quote": "(mock 모드: 실제 추출 아님)"}}),
        confidence=0.0, ambiguities=["mock 모드: 실제 LLM이 아니라 자리표시자 조건이다"])


def extract_terms_from_text(llm: LLM, customer_id: str, text: str, mock_fn=None) -> ExtractionResult:
    user = f"고객 ID: {customer_id}\n\n--- 계약서 전문 ---\n{text}"
    result = llm.parse(stage="extract", system=load_prompt("extract"), user=user, schema=ExtractionResult,
                       mock_fn=mock_fn or (lambda: _mock_terms_for_text(customer_id)))
    if result.terms.customer_id != customer_id:
        result = result.model_copy(update={"terms": result.terms.model_copy(update={"customer_id": customer_id})})
    return result


def extract_terms(llm: LLM, customer_id: str) -> ExtractionResult:
    text = load_contract_text(customer_id)

    def mock() -> ExtractionResult:
        return ExtractionResult(terms=load_golden_terms(customer_id), confidence=1.0,
                                ambiguities=["mock 모드: 정답지를 그대로 사용"])

    result = extract_terms_from_text(llm, customer_id, text, mock_fn=mock)
    if result.terms.customer_id != customer_id:
        result = result.model_copy(update={"terms": result.terms.model_copy(update={"customer_id": customer_id})})
    return result


def judge_from_text(llm: LLM, customer_id: str, terms: PenaltyTerms, event: EventContext, text: str,
                    mock_fn=None) -> ForceMajeureJudgment:
    notice = (f"운영팀은 사건 발생 {event.notice_sent_after_hours:g}시간 뒤에 고객에게 통지했다."
              if event.notice_sent_after_hours is not None else "운영팀은 고객에게 통지하지 않았다.")
    facts = "\n".join(f"- {k}: {'예' if v else '아니오'}" for k, v in event.facts.items()) or "- (추가 사실 없음)"
    clause = (f"추출된 불가항력 조항: 사유 {terms.force_majeure.covered_events}, 통지 시한 {terms.force_majeure.notice_hours}시간, "
              f"조건 {terms.force_majeure.conditions}" if terms.force_majeure else "추출 결과: 불가항력 조항 없음")
    user = (f"고객 ID: {customer_id}\n\n--- 사건 ---\n유형: {event.event_type}\n설명: {event.description}\n{notice}\n"
            f"사실 관계:\n{facts}\n\n{clause}\n\n--- 계약서 전문 ---\n{text}")

    def mock_generic() -> ForceMajeureJudgment:
        has = terms.force_majeure is not None
        return ForceMajeureJudgment(customer_id=customer_id, has_clause=has, event_covered=False, notice_ok=True, applies=False,
                                    reasoning="mock 모드: 실제 판단이 아니라 자리표시자다(면책 미적용으로 둔다).")

    j = llm.parse(stage="judge", system=load_prompt("judge"), user=user, schema=ForceMajeureJudgment, mock_fn=mock_fn or mock_generic)
    if j.customer_id != customer_id:
        j = j.model_copy(update={"customer_id": customer_id})
    # 계산기가 쓰는 최종 플래그는 기계적으로 다시 만든다. 모델이 applies만 뒤집는 실수를 막는다.
    derived = j.has_clause and j.event_covered and j.notice_ok and all(j.conditions_met.values())
    if derived != j.applies:
        j = j.model_copy(update={"applies": derived, "reasoning": j.reasoning + " (최종 적용 여부는 조건을 기계적으로 결합해 확정)"})
    return j


def judge_force_majeure(llm: LLM, customer_id: str, terms: PenaltyTerms, event: EventContext,
                        scenario_id: str) -> ForceMajeureJudgment:
    return judge_from_text(llm, customer_id, terms, event, load_contract_text(customer_id),
                           mock_fn=lambda: load_golden_judgment(customer_id, scenario_id))
