---
name: risk-rules
description: 위험 조항 규칙(rules/risk_rules.yaml)을 추가·수정·검증하는 절차. "지체상금 규칙 추가해줘", "이 조항이 왜 안 잡혀?", "규칙 기준값 바꿔줘" 같은 요청에 쓴다.
---

# /risk-rules — 위험 규칙 관리

## 규칙 한 개의 구조

```yaml
- id: R03_warranty_period
  title: 하자담보책임 기간 과다
  category: 계약조건
  pattern: '하자\s*(담보|보수)\s*(책임)?\s*기간[^。\n]{0,40}?(\d+)\s*(년|개월)'
  extract: '(\d+)\s*(년|개월)'      # 값 추출. 단위가 개월이면 코드가 년으로 환산
  compare: gt                        # gt | lt | present | absent
  threshold: 1                       # 단위: 년
  severity_default: medium
  why: 소프트웨어 하자담보책임은 통상 1년이다. 그 이상은 무상 유지보수에 해당한다.
  negotiation_point: 하자보수 1년, 이후 유지보수는 별도 계약으로 분리 요청
  basis: 소프트웨어 진흥법 및 계약예규(용역계약일반조건) 하자담보 조항. 팀이 최신 조문으로 확인할 것
  examples:
    hit: "하자보수 기간은 검수 완료일로부터 3년으로 한다."
    miss: "하자보수 기간은 검수 완료일로부터 1년으로 한다."
```

## 추가 절차

1. 먼저 `rules/risk_rules.yaml`에서 비슷한 규칙이 있는지 `id`와 `title`을 훑는다. 있으면 `pattern`을 넓히는 쪽을 택한다.
2. 규칙을 쓴다. `examples.hit`와 `examples.miss`는 필수다. `tests/test_risk_rules.py`가 yaml의 모든 규칙에 대해 이 두 예문을 자동으로 검사한다.
3. `threshold`가 있는 규칙은 `basis`에 근거 법령·예규 이름을 적는다. 조문 번호를 확신하지 못하면 "팀이 확인할 것"이라고 쓴다. 틀린 조문 번호보다 빈칸이 낫다.
4. 검증:
   ```bash
   pytest tests/test_risk_rules.py -q
   RFPHARNESS_LLM=mock python -m rfpharness review samples/sample_rfp.pdf --from risk --to risk
   ```
5. 샘플 RFP가 그 위험을 담고 있지 않다면 `samples/make_sample_rfp.py`의 계약 조건 섹션에 해당 조항을 심고, `eval/golden/sample_rfp.risks.json`에 기대 결과를 추가한다.

## 오탐을 줄이는 요령

- `present` 유형은 단어 하나로 걸지 않는다. "지체상금"만으로 걸면 목차에서도 걸린다. 비율·기간 같은 수치가 함께 있을 때만 건다.
- `absent` 유형은 전체 문서 기준 한 번만 판정된다(`scope: document`). 섹션 단위로 두지 않는다.
- 정규식에 한글 어미 변형을 넣을 때는 `(한다|하여야 한다|해야 한다|함)`처럼 묶는다.
