# AGENTS.md — RFP Compass (도구 중립 안내)

이 파일은 Codex, Cursor 등 Claude Code가 아닌 코딩 에이전트를 위한 진입점이다. 내용은 `CLAUDE.md`와 같은 원칙을 따르며, 재구현·검증용 상세 스펙은 `docs/SPEC.md`에 있다.

## 한 문단 요약

300쪽 제안요청서(RFP) PDF를 넣으면 요구사항 추적표, 배점 기준 목차 초안, 위험 조항 경고, 제안서 초안 커버리지가 나온다. 결정적 코드(`parse`, 규칙 엔진, `export`)가 흐름을 쥐고, LLM은 구조화 출력으로 "읽기·판단"만 맡는다. 모든 결과는 원문 인용과 쪽 번호를 가진다.

## 명령

```bash
uv venv .venv && . .venv/bin/activate && uv pip install -e ".[dev]"
python samples/make_sample_rfp.py                                   # 가상 RFP PDF
RFPHARNESS_LLM=mock python -m rfpharness review samples/sample_rfp.pdf --draft samples/draft_proposal.md
pytest -q                                                           # 84개 테스트, 네트워크 불필요
python eval/run_eval.py out/sample_rfp/report.json                 # 골든셋 대비 재현율·정밀도
python -m rfpharness serve --port 8787                              # 데모 웹 UI (http://127.0.0.1:8787)
```

## 수용 기준 (이 저장소가 "동작한다"의 정의)

1. `pytest -q`가 전부 통과한다.
2. mock 모드 `review`가 샘플 RFP에서 표 요구사항 44건, 본문 요구사항 6건, 위험 규칙 19종 적중·R08 미적중, 배점 합 90점을 낸다 (`eval/run_eval.py` 종료 코드 0).
3. 실제 모드(`RFPHARNESS_LLM=anthropic`)에서는 같은 골든셋으로 요구사항 재현율 0.9 이상, 위험 탐지율 0.9 이상을 목표로 한다. 측정값은 `eval/history.jsonl`에 기록한다.
4. `out/<name>/`에 `report.json`, `traceability.xlsx`, `toc_draft.docx`, `dashboard.html`이 생기고 대시보드는 오프라인에서 열린다.
5. `serve`에서 "샘플 RFP로 시작"을 누르면 6단계 진행이 보이고 결과 4개 탭이 뜬다. 표의 행을 클릭하면 원문 쪽이 열리고 인용문이 하이라이트된다.

## 바꿀 때 지킬 것

- 스키마(`src/rfpharness/schemas.py`)가 계약이다. 필드 추가는 Optional로, 바꾸면 `export.py`·`eval/`·`web/app.html`을 같이 본다.
- 법령 수치는 `rules/risk_rules.yaml`에만 둔다. 규칙을 추가하면 `examples.hit`/`examples.miss`를 반드시 넣는다(테스트가 자동 검사).
- LLM 호출은 `llm.py`를 통해서만. 다른 모델 제공자로 바꾸려면 `LLM.parse()` 하나만 교체하면 된다(입력: system, user, pydantic 스키마 / 출력: 스키마 인스턴스).
- `samples/`의 RFP는 가상 데이터다. 실제 RFP는 `samples/real/`(git 제외)에 둔다.
