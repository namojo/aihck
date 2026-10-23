# RFP Compass 재구현 스펙

다른 코딩 에이전트(Codex 등)가 이 저장소를 보지 않고도 같은 동작을 다시 만들고, 이 저장소의 테스트·골든셋으로 검증할 수 있도록 쓴 스펙이다. 언어는 Python 3.11+를 가정하지만, 입출력 계약(JSON 스키마)과 수용 기준만 지키면 다른 언어도 된다.

## 0. 목표와 비목표

- 목표: 제안요청서 PDF 1건 → `report.json`(아래 스키마) + 엑셀·워드·HTML 산출물. 데모 웹 UI에서 업로드·진행·결과 열람.
- 비목표: OCR, 선 없는 표 복원, 제안서 본문 자동 작성, 다국어 RFP.

## 1. 데이터 계약 (`src/rfpharness/schemas.py`)

모든 단계는 아래 JSON 모양을 주고받는다. 필드명·열거값은 그대로 지킨다.

```
Document      { meta{source_path,title?,page_count,needs_ocr,stripped_lines[]}, pages[{number,text,prose_text?}],
                sections[{section_id,heading,level,page_start,page_end,text,table_ids[]}],
                tables[{table_id,page,caption?,header[],rows[][]}] }
Requirement   { id, title, category∈{SFR,PER,SIR,INR,DAR,TER,SER,QUR,COR,PMR,PSR}, obligation∈{must,should,may},
                quote, page, section?, detail?, deliverables[], source∈{table,prose}, confidence, flags[] }
ScoringCriterion { id, name, parent?, points, description?, page? }
TocNode       { number, title, criterion_ids[], requirement_ids[], suggested_pages, writing_guide }
TocResult     { scoring[], toc[], unmapped_requirement_ids[], total_pages, flags[] }
RiskFinding   { rule_id, title, category, severity∈{high,medium,low}, quote, page, section?, why,
                extracted_value?, threshold?, negotiation_point, basis?, source∈{rule,rule+llm,llm} }
CoverageItem  { requirement_id, status∈{covered,partial,missing}, evidence_paragraph_ids[], evidence_quote?, gap_note? }
CoverageResult{ draft_path, items[], covered, partial, missing, must_missing }
ReviewReport  { summary{...건수와 llm_mode, stage_seconds}, document_meta, requirements[], toc?, risks[], coverage? }
```

불변 조건
- 모든 `Requirement.quote`, `RiskFinding.quote`는 비어 있지 않고 `page ≥ 1`.
- `Requirement.id`는 보고서 안에서 유일. RFP 고유번호(`^[A-Z]{3}-\d{3}$`)가 있으면 그대로, 없으면 `REQ-P-001`부터 순번.
- `CoverageResult.covered+partial+missing == len(requirements)`.

## 2. 단계별 사양

### 2.1 parse (LLM 없음)
- 입력: PDF 경로. 출력: `Document`.
- 페이지 텍스트는 그대로 두고, 여러 페이지에 반복되는 40자 이하 줄(머리말·꼬리말·쪽번호)은 제거해 `meta.stripped_lines`에 남긴다. 제거한 줄 중 "제안요청서"가 들어 있으면 그것이 `meta.title`.
- 표는 **선이 있는 표만** 추출한다. 첫 행이 header. 병합 셀(빈 문자열)은 윗 셀을 상속하되 "고유번호" 열은 상속하지 않는다.
- `prose_text`는 표 영역을 제외한 페이지 텍스트다(가짜 요구사항 방지).
- 섹션은 제목 패턴(로마 숫자·`제n장` 레벨 1, `n.` 레벨 2)에서 자른다. 표는 같은 페이지에서 표 위에 있는 마지막 제목의 섹션에 속한다.
- 페이지당 평균 50자 미만이면 `needs_ocr=True`(예외를 내지 않는다).

### 2.2 extract (LLM)
- 섹션마다 `prose_text`(페이지 표시 `[p.N]` 포함)와 그 섹션의 표(마크다운)를 한 번에 보낸다. 6,000자 초과 시 문단 경계로 나누되 표는 자르지 않는다.
- 시스템 프롬프트 요지: 표의 고유번호 요구사항 전부 + 본문 의무 문장("하여야 한다" 등)을 `source=prose`로, 인용은 원문 그대로, 분류 11종, 어미로 must/should/may, 계약 조건은 요구사항 아님, 중복 제거 금지.
- 후처리(코드): `quote`가 원문(페이지 텍스트 또는 표 셀, 공백 제거 비교)에 없으면 `flags+=quote_not_found`, `confidence≤0.3`. 같은 id 병합, 인용 90% 이상 겹치면 표 쪽을 남김, prose id 재번호.
- mock: 고유번호 열이 있는 표의 각 행 → 요구사항(인용은 세부내용 셀), 계약 조건이 아닌 섹션의 prose_text에서 의무 어미 문장 → prose 요구사항.

### 2.3 toc (탐지는 코드, 연결은 LLM)
- 배점표 후보: header에 "배점" 또는 "점수"가 있고 숫자 열 합이 60~200. 캡션·header에 "기술"이 있으면 우선.
- 2개 텍스트 열이 있으면 (상위 항목, 세부 항목) 계층. 합계 행은 제외. 상위 합이 100/90/80이 아니면 `flags+=points_sum_mismatch:<합>`.
- LLM에 (배점 항목, 요구사항) 목록을 주고 요구사항 → 하위 항목 id 1개 연결(없으면 null). 연결 안 된 것은 `unmapped`로 "기타 요구사항 대응" 장에 모은다. 사라지는 요구사항은 없다.
- 분량: `total_pages`는 본문에서 "제안서 … N쪽 이내" 패턴을 찾고(없으면 80), 항목별 `round(total × points / 합)`.

### 2.4 risk (규칙 → LLM 보강)
- 규칙 파일 `rules/risk_rules.yaml`: `id, title, category, pattern(정규식), compare∈{present,gt,lt,absent}, value_kind?, threshold?, requires?(absent용), exclude?, scope?, severity_default, why, negotiation_point, basis, examples{hit,miss}`.
- 매칭은 페이지를 이어 붙인 전체 텍스트에서 줄바꿈을 공백으로 바꾼 문자열로 한다(길이 보존 → 쪽 번호 역산 가능). `gt/lt`는 `value_kind`별 정규화(`1000분의 2.5`→0.25%/일, `3년`/`18개월`→년, `100분의 10`→%).
- 인용은 매칭을 감싼 문장(직전 "다." 또는 제목 줄 끝 ~ 직후 "다."). 매칭이 표 안이면 해당 셀 원문을 인용. 같은 (rule_id, 인용 앞 60자)는 1건.
- `absent`: `requires`가 문서에 있고 `pattern`이 문서 어디에도 없을 때 1건(문서 단위).
- LLM 보강(실제 모드만): 조항 ±600자 문맥을 주고 `severity, why, negotiation_point, additional_findings[]`를 받는다. 결과 `source=rule+llm`, 추가 발견은 `source=llm`.

### 2.5 coverage (LLM)
- 초안(md: 빈 줄로 문단, `#`은 heading / docx: Heading 스타일로 문단 묶음)을 `P-001…` id로 번호 매김.
- 요구사항 12개씩 + 문단 전체를 보내 `covered/partial/missing`, 근거 문단 id, 20자 이내 발췌, 누락 메모를 받는다. 존재하지 않는 문단 id는 버리고, 근거가 없는 covered는 partial로 강등.
- mock: (제목+정의+인용)의 글자 2-gram이 어떤 문단에 50% 이상 들어 있으면 covered, 28% 이상 partial, 그 외 missing.

### 2.6 export (LLM 없음)
- `traceability.xlsx` 시트 4개: 요구사항 추적표(ID·요구사항·분류·필수·원문·쪽·섹션·산출물·출처·제안서 목차·커버리지·근거/보완·비고), 위험 조항, 배점-목차, 커버리지. 심각도·판정별 셀 배경색.
- `toc_draft.docx`: 목차 장별 제목(분량)·작성 가이드·대응 요구사항 + 위험 요약.
- `dashboard.html`: `web/app.html` 템플릿의 `/*__EMBEDDED_REPORT__*/null` 자리에 `{report, pages}` JSON을 심은 오프라인 단일 파일.

### 2.7 pipeline / cli
- 단계 순서 `parse, extract, toc, risk, coverage, export`. 각 단계 결과를 `out/<name>/checkpoints/<stage>.json`에 저장. `--from/--to/--fresh`. coverage는 `--draft`가 없으면 건너뜀. 끝나면 `report.json`과 요약 문자열.
- `python -m rfpharness review <pdf> [--draft] [--out] [--from] [--to] [--fresh] [--llm anthropic|mock] [--model]`, `parse <pdf> [--show-tables]`, `serve [--host] [--port] [--llm]`.

### 2.8 llm 게이트웨이
- `LLM(mode, model).parse(stage, system, user, schema, mock_fn, max_tokens=16000) → schema 인스턴스`.
- anthropic 모드: `client.messages.parse(model, max_tokens, system, messages=[user], output_format=schema)`. 검증 실패 1회 재시도, 429는 retry-after 후 1회 재시도, 인증 실패는 mock으로 내려가며 로그. `stop_reason == "refusal"`은 오류. 사용량(호출 수, 토큰) 누적.
- mock 모드: `mock_fn()` 반환.

### 2.9 데모 웹 (`web/server.py`, `web/app.html`)
- `GET /` 단일 HTML. `GET /api/samples`, `POST /api/jobs`(multipart pdf, draft?, llm?), `POST /api/jobs/sample`(form pdf, draft?), `GET /api/jobs/{id}/events`(SSE: `{type:stage,stage,status∈{running,done,reused,skipped},done,total}` / `{type:done,summary,…}` / `{type:error}`), `GET /api/jobs/{id}/report`, `/pages`, `/download/{xlsx|docx|json|html}`.
- UI: 업로드 카드 → 6단계 스테퍼+스톱워치 → 요약 타일 5개 → 탭 4개(요구사항 추적표: 출처·분류 필터, 행 클릭 시 원문 쪽 드로어와 인용 하이라이트 / 위험 조항: 심각도 카드, 추출값 vs 기준값, 협상 포인트 / 배점 기준 목차: 배점 막대·분량·요구사항 id / 초안 커버리지: 충족·부분·누락 막대, 필수 누락 경고). 외부 CDN 없음.
- `RFPHARNESS_DEMO_DELAY=<초>`면 단계 사이에 지연을 넣어 진행이 보이게 한다(녹화용).

## 3. 샘플·골든셋·테스트

- `samples/make_sample_rfp.py` → `sample_rfp.pdf`(12쪽). 표 요구사항 44건(SFR12·PER3·SIR2·INR4·DAR3·TER2·SER5·QUR2·COR3·PMR4·PSR4), 본문 의무 문장 6건, 기술평가 배점표(상위 6항목 합 90), 계약 조건 15개 항에 위험 규칙 19종이 걸리는 조항(R08 계약보증금 10%는 정상).
- `samples/draft_proposal.md`: 요구사항 중 SFR-010·SFR-012·PER-002·DAR-002·TER-001·TER-002·SER-002·SER-004·QUR-001·COR-001·PSR-003 등을 일부러 뺀 초안.
- `eval/golden/sample_rfp.requirements.json`(`table_ids[]`, `prose_quotes[]`), `eval/golden/sample_rfp.risks.json`(`expected_hit[]`, `expected_miss[]`, `severity{}`, `scoring_points_total`).
- `eval/run_eval.py <report.json> [--record]`: 요구사항 재현율·정밀도(표는 id, 본문은 인용 앞 30자 겹침), 위험 탐지율·오탐, 배점 합. 종료 코드 0 = 재현율·탐지율 0.9 이상이고 오탐 없음.
- `tests/`: 규칙 예문 자동 검사(규칙마다 hit/miss), 제목 패턴, 샘플 파싱 구조, mock end-to-end, 체크포인트 재개.

## 4. 수용 기준 (검증 순서)

1. `python samples/make_sample_rfp.py && pytest -q` → 전부 통과.
2. `RFPHARNESS_LLM=mock python -m rfpharness review samples/sample_rfp.pdf --draft samples/draft_proposal.md --fresh` 요약이 "요구사항 50건 — 표 44 · 본문 6", "배점 항목 6개(합 90점)", "위험 조항 20건"(R13이 2곳에서 걸려 규칙 19종·20건), 커버리지 "누락 15 (필수 누락 14)"에 가깝다. 수치가 ±2 안이면 통과.
3. `python eval/run_eval.py out/sample_rfp/report.json` 종료 코드 0.
4. `python -m rfpharness serve` → 브라우저에서 "샘플 RFP로 시작" → 결과 탭 4개 표시, 행 클릭 시 원문 하이라이트, 엑셀·워드 다운로드.
5. (실제 모드) 같은 명령을 `RFPHARNESS_LLM=anthropic`으로 돌려 `eval/run_eval.py --record`. 재현율 0.9 이상이 목표이며 미달 시 `requirement-extractor` 에이전트 원칙에 따라 프롬프트를 한 가지만 바꾸고 재측정.

## 5. 재구현 시 흔한 실수

- 표 셀 텍스트가 페이지 텍스트에 열 단위로 섞여 나온다. 인용 검증을 페이지 텍스트로만 하면 표 요구사항이 전부 `quote_not_found`가 된다 → 표 셀로도 검증.
- 줄바꿈으로 끊긴 문장. 정규식 매칭 전에 줄바꿈을 공백으로 바꾸되 길이를 보존해야 쪽 번호가 맞는다.
- 제목 줄이 다음 문장에 붙는다("7. 대금 지급 사업비는…"). 제목 줄 끝을 문장 경계로 둔다. 매칭이 제목 안에서 시작하는 경우(`5. 손해배상`)도 같다.
- 선 없는 표 폴백은 본문 문단을 표로 만든다. 끄는 편이 낫다.
- mock 통과는 배관 확인이지 품질 확인이 아니다. 실제 모드 측정값을 반드시 기록한다.
