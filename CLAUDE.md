# RFP Compass — RFP 자동 검토 에이전트 하네스

300쪽 제안요청서(RFP) PDF를 넣으면 **요구사항 추적표 · 배점 기준 목차 초안 · 위험 조항 경고 · 제안서 초안 커버리지**가 나오는 해커톤 프로젝트.
이 저장소는 두 층으로 되어 있다.

| 층 | 무엇 | 어디 |
| --- | --- | --- |
| 런타임 파이프라인 | PDF → 구조화 → Claude 추출/판정 → 엑셀·워드·HTML 출력. 결정적 코드가 흐름을 쥐고, LLM은 "읽기·판단" 단계만 맡는다 | `src/rfpharness/` |
| 개발 하네스 | 팀이 Claude Code 안에서 파이프라인을 만들고 고치는 데 쓰는 서브에이전트·스킬·평가 루프 | `.claude/agents/`, `.claude/skills/`, `eval/` |

## 빠른 시작

```bash
uv venv .venv && . .venv/bin/activate && uv pip install -e ".[dev]"
python samples/make_sample_rfp.py                 # 가상 RFP PDF 생성 → samples/sample_rfp.pdf
RFPHARNESS_LLM=mock python -m rfpharness review samples/sample_rfp.pdf --draft samples/draft_proposal.md
python -m rfpharness review samples/sample_rfp.pdf  # 실제 Claude 호출. 기본 auto: API 키가 있으면 SDK, 없으면 claude CLI(구독), 둘 다 없으면 mock
pytest -q                                          # 규칙 엔진·파서·파이프라인(mock) 테스트
python eval/run_eval.py out/sample_rfp/report.json # 골든셋 대비 재현율/정밀도
```

산출물은 `out/<rfp이름>/`에 쌓인다: `report.json`(단일 진실 원천), `traceability.xlsx`, `toc_draft.docx`, `dashboard.html`, `checkpoints/`.

## 파이프라인 6단계

```
parse → extract → score/toc → risk → coverage → export
```

1. **parse** (`parse.py`) — pdfplumber로 페이지 텍스트와 표를 뽑고, 제목 패턴(Ⅰ. / 1. / 가. / 1))으로 섹션을 나눈다. LLM을 쓰지 않는다.
2. **extract** (`extract.py`) — 섹션 단위로 Claude에 보내 `Requirement` 목록을 구조화 출력(`messages.parse` + pydantic)으로 받는다. 표 안의 요구사항(SFR-001 같은 고유번호)뿐 아니라 본문 문장에 숨은 "~하여야 한다"도 잡는다. 원문 인용(`quote`)과 페이지가 없는 요구사항은 버린다.
3. **score / toc** (`toc.py`) — 평가 배점표를 찾아 `ScoringCriterion`으로 만들고, 요구사항을 배점 항목에 연결한 뒤 배점 비중에 비례해 분량을 배분한 목차 초안(`TocNode`)을 만든다.
4. **risk** (`risk.py`) — `rules/risk_rules.yaml`의 규칙 20개(정규식 + 임계값)로 1차 탐지하고, Claude가 조항 문맥을 읽어 심각도·근거·협상 포인트를 보강한다. 규칙에 걸리지 않은 조항도 LLM이 추가로 올릴 수 있지만 `source: llm`으로 표시한다.
5. **coverage** (`coverage.py`) — 제안서 초안(md/docx)이 있으면 요구사항마다 `covered / partial / missing`을 판정하고 근거 문단을 붙인다.
6. **export** (`export.py`) — 엑셀(추적표·위험·배점-목차·커버리지 시트), 워드(목차 초안), HTML 대시보드(데모용).

각 단계는 `out/<name>/checkpoints/<stage>.json`에 결과를 저장하고 `--from <stage>`로 재개할 수 있다. 데모 리허설 중 LLM 단계만 다시 돌릴 때 쓴다.

## 지켜야 할 원칙

- **원문 인용 없는 결과는 없다.** 요구사항·위험 조항 모두 `quote`와 `page`를 가진다. 심사위원이 "그 조항 어디 있어요?"라고 물으면 페이지를 바로 연다.
- **LLM 호출은 `llm.py`를 통해서만.** 모델 기본값 `claude-opus-5-5`, 구조화 출력은 pydantic 스키마. 모드는 `claude-code`(Claude Code CLI를 서브프로세스로 호출, API 키 없이 구독으로 실행), `anthropic`(SDK), `mock`(네트워크 없이 결정적 결과). 기본 `auto`는 키 → CLI → mock 순으로 고른다. 테스트는 mock으로만 돈다.
- **LLM 호출은 병렬이다.** `LLM.map()`이 스레드 풀(`RFPHARNESS_CONCURRENCY`, 기본 4)로 extract 청크·risk 조항·coverage 배치를 돌린다. 순서는 보존된다. mock은 순차.
- **규칙과 LLM은 이중 판정.** 위험 조항은 규칙이 "어디"를, LLM이 "왜·얼마나"를 맡는다. 둘 중 하나만으로 결론 내지 않는다.
- **스키마가 계약이다.** `schemas.py`를 바꾸면 `export.py`, `eval/`, 대시보드가 같이 바뀐다. 필드 추가는 Optional로.
- **법령 수치는 규칙 파일에만.** 지체상금률·하자보수 기간 같은 기준은 코드가 아니라 `rules/risk_rules.yaml`의 `threshold`에 두고 `basis`에 근거를 적는다. 팀이 최신 법령으로 확인한 뒤 값을 바꾼다.
- **데모 데이터는 가짜다.** `samples/`의 RFP는 가상의 기관·사업이다. 실제 나라장터 RFP로 시연할 때는 `samples/real/`(git 제외)에 두고 발표 첫 장에 출처를 적는다.

## 서브에이전트와 스킬

| 이름 | 역할 | 맡는 모듈 |
| --- | --- | --- |
| `rfp-orchestrator` | 전체 흐름 조율, 단계별 체크포인트 확인, 실패 시 재개 지점 결정 | `pipeline.py`, `cli.py` |
| `rfp-parser` | PDF 파싱 품질(표 깨짐, 페이지 번호, 섹션 경계) 책임 | `parse.py` |
| `requirement-extractor` | 요구사항 추출 프롬프트·스키마·중복 병합 | `extract.py`, `prompts/extract.md` |
| `toc-architect` | 배점표 인식과 목차 초안 생성 | `toc.py`, `prompts/toc.md` |
| `risk-auditor` | 위험 규칙 유지, LLM 보강 판정 | `risk.py`, `rules/risk_rules.yaml`, `prompts/risk.md` |
| `coverage-checker` | 제안서 초안 대조 | `coverage.py`, `prompts/coverage.md` |
| `eval-judge` | 골든셋 대비 측정, 프롬프트 개선 제안(힐클라임) | `eval/` |

스킬: `/rfp-review <pdf>` (전체 실행 + 요약), `/risk-rules` (규칙 추가·검증 절차), `/demo-rehearsal` (3분 데모 리허설 체크리스트).

## 작업 규칙

- 코드 변경 후 `pytest -q`가 통과해야 커밋한다. LLM 프롬프트를 바꿨으면 `python eval/run_eval.py`로 재현율이 떨어지지 않았는지 본다(mock은 프롬프트를 안 쓰므로 실제 모드로 1회).
- 새 위험 규칙은 `tests/test_risk_rules.py`에 걸리는 예문과 안 걸리는 예문을 1개씩 같이 넣는다.
- 출력 파일(`out/`), 실제 RFP(`samples/real/`), `.venv`는 커밋하지 않는다.
- 한글 문서·주석은 평서문으로, 수치는 출처와 함께 쓴다. 기획서(`docs/proposal/`)의 숫자 중 측정하지 않은 것은 "목표"라고 표시한다.
