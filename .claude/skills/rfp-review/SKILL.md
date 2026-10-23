---
name: rfp-review
description: RFP PDF 한 건을 처음부터 끝까지 검토해 요구사항 추적표·배점 기준 목차 초안·위험 조항 경고·(초안이 있으면) 커버리지를 만들고 결과를 요약한다. "/rfp-review <pdf> [--draft <md>]" 또는 "이 RFP 검토해줘" 요청에 쓴다.
---

# /rfp-review — RFP 전체 검토

## 절차

1. 인자를 확인한다. PDF 경로가 없으면 `samples/sample_rfp.pdf`를 쓸지 묻는다. `--draft`가 있으면 커버리지 단계를 포함한다.
2. 실행 모드를 정한다. 기본 `auto`는 API 키가 있으면 `anthropic`, `claude` CLI가 있으면 `claude-code`(구독으로 실행), 둘 다 없으면 `mock`이다. 결과 요약에 실제 모드를 명시한다.
3. 기존 체크포인트가 있으면 재사용 여부를 사용자에게 한 줄로 묻지 않고 재사용한다. 사용자가 "처음부터"라고 하면 `--fresh`.
   ```bash
   RFPHARNESS_LLM=<mode> python -m rfpharness review <pdf> [--draft <md>] [--fresh] --out out/<name>
   ```
4. 끝나면 `out/<name>/report.json`을 읽고 아래 형식으로 요약한다. 숫자는 report.json의 `summary`에서 가져온다.

```
RFP: <제목> (<페이지>쪽, <표 수>개 표)
요구사항 <N>건 — 표 <a> · 본문 <b> · 필수 <c>
배점 항목 <k>개(합 <sum>점) → 목차 <m>장, 미연결 요구사항 <u>건
위험 조항 <r>건 — 높음 <h> · 보통 <mid> · 낮음 <low>
  1. [높음] <제목> p.<page> — <why 한 문장>
  2. ...
커버리지(초안 대조) — 충족 <x> · 부분 <y> · 누락 <z> (필수 누락 <z_must>)
산출물: traceability.xlsx · toc_draft.docx · dashboard.html
```

5. 위험 조항 상위 3개는 `quote`를 원문 그대로 인용한다. 요약하지 않는다.
6. 요구사항 0건, 배점표 미발견, `needs_ocr` 중 하나라도 있으면 성공으로 보고하지 않고 담당 에이전트(`rfp-parser`, `toc-architect`)를 호출해 원인을 확인한다.

## 하지 않는 것

- 결과 숫자를 손으로 고치지 않는다. 틀렸으면 파이프라인을 고치고 다시 돌린다.
- 실제 고객사 RFP를 `samples/`에 복사하지 않는다. `samples/real/`(git 제외)에 둔다.
