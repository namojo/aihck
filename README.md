# RFP Compass

300쪽 제안요청서(RFP) PDF를 넣으면 **요구사항 추적표 · 배점 기준 목차 초안 · 위험 조항 경고 · 제안서 초안 커버리지**가 나오는 제안 검토 에이전트. 사내 해커톤 출품용 하네스와 데모, 아이디어 기획서를 담고 있다.

| 폴더 | 내용 |
| --- | --- |
| `src/rfpharness/` | 런타임 파이프라인(parse → extract → toc → risk → coverage → export)과 데모 웹 UI |
| `.claude/agents/`, `.claude/skills/` | Claude Code 개발 하네스: 단계별 서브에이전트 7개, 스킬 3개 |
| `rules/risk_rules.yaml` | 위험 조항 규칙 20개(법령 기준값·근거·협상 포인트·예문) |
| `samples/` | 가상 RFP 생성기와 PDF, 일부러 요구사항을 빠뜨린 제안서 초안 |
| `eval/` | 골든셋과 측정 스크립트(재현율·정밀도·위험 탐지율) |
| `tests/` | pytest 84개(네트워크 불필요) |
| `docs/proposal/` | 해커톤 아이디어 기획서(md · A4 HTML · PDF) |
| `docs/SPEC.md` | 다른 에이전트(Codex 등)가 재구현·검증할 때 쓰는 상세 스펙 |
| `docs/demo-script.md`, `docs/demo/` | 3분 데모 스크립트, 스크린샷·녹화본 |
| `scripts/build_site.py`, `.github/workflows/pages.yml` | GitHub Pages 정적 사이트 조립과 배포 |

## 빠른 시작

```bash
uv venv .venv && . .venv/bin/activate && uv pip install -e ".[dev]"
python samples/make_sample_rfp.py
RFPHARNESS_LLM=mock python -m rfpharness review samples/sample_rfp.pdf --draft samples/draft_proposal.md
python -m rfpharness serve --port 8787      # http://127.0.0.1:8787 → "샘플 RFP로 시작"
```

실제 Claude를 쓰는 방법은 둘이다. **API 키 없이** Claude Code 구독으로 돌리려면 `claude` CLI가 로그인된 상태에서 `RFPHARNESS_LLM=claude-code`(또는 기본 `auto`)로 실행한다. 파이프라인이 `claude -p --json-schema`를 서브프로세스로 불러 구조화 출력을 받는다. API 키가 있으면 `ANTHROPIC_API_KEY`를 두고 `RFPHARNESS_LLM=anthropic`. 모델 기본값은 `claude-opus-5-5`, `RFPHARNESS_MODEL`로 바꾼다. LLM 호출은 4개씩 병렬(`RFPHARNESS_CONCURRENCY`).

배포된 사이트: https://namojo.github.io/aihck/ (기획서, 데모 대시보드, 녹화본). `python scripts/build_site.py`로 `site/`를 만들고 `gh-pages` 브랜치로 올린다.

## 설계 한 장

```
PDF ─parse(결정적)─▶ Document{pages, sections, tables}
        │
        ├─extract(LLM 구조화 출력)─▶ Requirement[]  (표 + 본문 숨은 요구사항, 원문 인용·쪽)
        ├─toc(코드 탐지 + LLM 연결)─▶ ScoringCriterion[] → TocNode[] (배점 비례 분량)
        ├─risk(규칙 20개 → LLM 보강)─▶ RiskFinding[]  (추출값 vs 기준값, 협상 포인트)
        └─coverage(LLM 판정)─▶ CoverageItem[]  (covered/partial/missing, 필수 누락)
        ▼
export ─▶ report.json · traceability.xlsx · toc_draft.docx · dashboard.html
```

원칙: 결정적 코드가 흐름을 쥐고 LLM은 읽기·판단만 맡는다. 모든 결과는 원문 인용과 쪽 번호를 가진다. 규칙과 LLM은 이중 판정이다. 자세한 설명은 `CLAUDE.md`(Claude Code용)와 `AGENTS.md`(도구 중립), `docs/harness-design.md`를 본다.

## 고지

`samples/`의 RFP는 가상의 기관·사업이다. 위험 규칙의 법령 수치(`rules/risk_rules.yaml`의 `threshold`, `basis`)는 팀이 최신 조문으로 확인한 뒤 쓴다.
