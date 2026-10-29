# ClauseTower — 계약을 읽는 물류 관제탑

**급한 순서가 아니라, 물리는 순서로.** 물류 교란이 터졌을 때 고객별 계약서의 지체상금·SLA 조항을 읽어 "한 사이클 더 기다리게 하면 누구에게 얼마가 물리는가"를 계산하고, 그 순서로 배차한다. 사내 해커톤 출품작. 고객·계약·사건은 전부 가상이다.

| 한눈에 | |
| --- | --- |
| 문제 | 교란 때 관제실은 마감 급한 순서로 배차한다. 돈이 물리는 순서는 그것과 다르다(면책, 통지 시한, 유예, 상한, 사유 불문 조항) |
| 해법 | LLM이 계약을 읽고 면책을 판단 → 결정적 코드가 노출액을 계산 → 시뮬레이터가 정책을 비교해 증명 |
| 결과(측정) | 같은 화물·같은 교란에서 순서만 바꿔 총 페널티 **58~77% 절감**(시나리오 3종), 시드 30개 × 3종에서 **90/90 승** |
| 실제 모델(측정) | Claude가 계약서 8부를 읽은 추출 정확도 **96.2%**(106항목), 면책 판단 **100% / 96.9%**, 인용 원문 일치 **100%**, 호출 24회 |
| 근거 | 모든 판단에 계약서 **조항 번호와 원문 인용**이 붙는다 |
| 웹 데모 | **https://namojo.github.io/clausetower/** — 브라우저 안에서 시뮬레이션이 돌고, 계약서를 올리면 AI가 바로 분석한다(연결 방식 3종) |
| 돌려 보기 | `pip install -e .` 뒤 `python -m clausetower demo --llm mock` → `out/demo/dashboard.html` (네트워크 불필요, 10초) |

## 심사 기준에 대한 답

| 기준 | 어디서 확인하나 |
| --- | --- |
| AI 활용 수준 | LLM은 **읽기와 판단**(계약 조항 구조화, 불가항력 적용 여부)만 맡고 돈 계산은 코드가 한다. 구조화 출력(pydantic), 조건의 기계적 결합, 실패 시 정답지 대체와 기록. `src/clausetower/extract.py`, `prompts/` |
| 문제 해결 방식 | "급함"이 아니라 "물리는 돈"으로 우선순위를 바꾸는 한 가지 변경. 같은 시뮬레이터에서 정책 5개를 나란히 비교하고 지역 탐색 상한선까지 둔다. `src/clausetower/sim.py` |
| 실제 업무 적용 가능성 | 기존 배차 엔진을 바꾸지 않고 우선순위 입력에 열 하나를 더하는 형태. 모든 판단에 원문 인용. 사람이 최종 결정. `docs/proposal.md` 7~8절 |
| 재현성 | 결정적 시뮬레이터, mock 모드, 시험 31개, 실제 모델 실행 보고서와 로그를 저장소에 포함. 아래 "검증 절차" |

## 웹 데모: 조건을 바꾸고, 실제 계약서를 올려 본다

https://namojo.github.io/clausetower/ 는 서버가 없는 정적 페이지다. 화면 맨 위가 관제 요약과 "지금 조치"(보낼 화물·보낼 통지·살릴 면책)이고, 그 아래로 물리는 순서, 추이, 계약 케이스, 실제 케이스 분석이 이어진다. 파이썬 계산기와 시뮬레이터를 JavaScript로 옮겼고(`src/clausetower/web/engine.js`), 같은 입력에서 파이썬과 같은 총 페널티가 나오는지 `scripts/verify_engine.js`가 31개 항목을 대조한다(전부 일치). 통지 시점, 결항 대수, 입증 자료, 화물 배치, 계약 읽기 출처(정답지 또는 실제 Claude 추출)를 바꾸면 면책 판단이 조건 결합으로 다시 계산되고 모든 화면이 갱신된다. 고객별 면책을 사람이 뒤집는 것도 된다.

![웹 데모](docs/screenshots/web/web_overview.png)

**실제 케이스 분석(AI).** 계약서(txt, md, docx 또는 붙여넣기)를 올리면 조건을 추출하고 현재 사건의 면책을 판단해 시뮬레이션에 넣는다. 사건을 직접 적으면 8개 계약의 면책을 다시 판단한다. 연결 방식은 세 가지이고, 계약서 본문은 선택한 LLM 엔드포인트 외에는 어디에도 전송되지 않는다.

| 연결 방식 | 준비 | 흐름 |
| --- | --- | --- |
| Anthropic API 키 | 키를 입력(브라우저 localStorage에만 저장) | 브라우저 → api.anthropic.com 직접 호출(tool use로 구조화 출력) |
| 로컬 도우미(Claude 구독, Claude Code CLI) | PC에서 `python -m clausetower serve --llm claude-code` | 브라우저 → 127.0.0.1:8787 → 기존 `llm.py`가 CLI로 처리. 사내 LLM 중계도 같은 경로(`--llm openai`) |
| 사내·호환 엔드포인트 | 기본 주소, 모델 이름, 토큰 입력 | 브라우저 → OpenAI 호환(`/chat/completions` + tools) 또는 Anthropic 호환(`/v1/messages`) 직접 호출. CORS가 막히면 도우미로 중계 |

로컬 도우미를 Claude 구독으로 띄우고 예시 계약서를 올린 실제 실행(추출 22초, 조건 전부 정확, 인용 원문 일치):

![구독 경로 실제 실행](docs/screenshots/web/web_live_helper_real.png)

사내 LLM을 파이썬 파이프라인에서 직접 쓰려면 `CLAUSETOWER_OPENAI_BASE_URL`, `CLAUSETOWER_OPENAI_API_KEY`, `CLAUSETOWER_MODEL`을 두고 `--llm openai`로 실행한다. Anthropic 호환 게이트웨이는 SDK의 `ANTHROPIC_BASE_URL`로 바꾼다.

## 빠른 시작

```bash
cd clausetower
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
python -m clausetower demo --llm mock             # 3개 시나리오 실행 + out/demo/dashboard.html
python -m clausetower run typhoon --llm mock      # 하나만
pytest -q                                         # 39개
python -m clausetower serve --llm claude-code     # 웹 데모용 로컬 도우미(구독). --llm openai 로 사내 LLM
python scripts/build_site.py && node scripts/verify_engine.js   # 웹 데모 조립 + 브라우저 엔진 검증
python eval/run_eval.py robustness --seeds 30     # 다중 시드 견고성 → eval/results/robustness.md
```

실제 Claude로 돌리기: `claude` CLI가 로그인돼 있으면 `--llm claude-code`(API 키 없이 구독), `ANTHROPIC_API_KEY`가 있으면 `--llm anthropic`. 기본 `auto`는 키 → CLI → mock 순으로 고른다. 모델 기본값 `claude-opus-5-5`(`CLAUSETOWER_MODEL`). 계약 추출은 시나리오 간에 공유되어 호출은 8 + 시나리오당 8회다. 실제 모델 결과를 정답지와 대조하려면 `python eval/run_eval.py extraction out/<...>/report.json`.

## 무엇이 나오나

**맨 위는 관제 요약과 조치다.** 두 숫자(기존 대 ClauseTower) 옆에 지금 할 일 셋이 뜬다. 지금 보낼 화물 3건, 통지 시한이 걸린 계약과 놓쳤을 때 물리는 돈, 입증 자료 같은 정성 조건 하나로 살아나는 면책과 그 금액. 모두 조항 번호가 붙고 "조항 보기"가 바로 열린다. 웹 데모에서는 "통지 12h로 시뮬레이션", "충족으로 바꿔 보기"를 누르면 그 가정으로 전체가 다시 계산된다.

![관제 요약과 지금 조치](docs/screenshots/typhoon_kpi.png)

![물리는 순서](docs/screenshots/typhoon_ranking.png)

왼쪽이 ClauseTower 순위, 그 옆이 기존 마감 순위와 변동이다. 마감 1위였던 화물이 14위로 내려가고(한 사이클 미뤄도 페널티가 안 늘어서), 마감 40위가 2위로 올라온다(건당 정액이라 바로 물려서). 각 행을 펼치면 계약서 인용이 나온다.

**계약 케이스는 항목별 비교표로.** 고객 × (과금 방식·요율, 유예, 상한, 불가항력 사유, 통지 시한·조건, 이번 사건 판단, 정책별 페널티). 어느 칸을 눌러도 그 항목의 상세가 열린다.

![계약 케이스 비교표](docs/screenshots/typhoon_board_matrix.png)

**계약 상세는 항목 단위다.** 항목마다 값, 운영에 뜻하는 바, 조항 번호와 원문 인용이 붙고 "원문에서 보기"가 전문 탭의 해당 문장으로 건너뛴다. 이번 사건 판단은 조항 있음 → 사유 해당 → 통지 충족 → 조건 충족의 체크리스트로 보여 어디서 면책이 끊겼는지 바로 보인다.

![계약 상세 서랍](docs/screenshots/typhoon_drawer.png)

대시보드는 외부 자원 없는 단일 HTML이라 심사장에서 오프라인으로 열린다. 나머지 화면과 설명은 [기획서](docs/proposal.md)에 있다.

## 측정 결과

**정책 비교**(mock, 계약 조건은 정답지). 트럭 8대, 화물 56건, 시간 단위는 사건 발생 후.

| 시나리오 | 마감 급한 순(기존) | 도착 순 | 고액 화물 순 | **ClauseTower** | 탐색 근사 최적(참고) | 절감 |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 태풍 상륙 | 12,834,000 | 11,732,000 | 17,610,500 | **2,996,500** | 2,921,000 | 76.7% |
| 항만 적체 | 4,770,000 | 4,559,500 | 9,660,500 | **1,842,500** | 1,222,500 | 61.4% |
| 자사 WMS 장애 | 18,640,000 | 25,076,000 | 20,681,500 | **7,765,500** | 6,930,500 | 58.3% |

**다중 시드**(시드 30개로 화물 가액·노선·마감을 바꿔 반복, `eval/results/robustness.md`): 태풍 30/30 승, 절감 평균 69.1%(49.6~82.1). 항만 30/30, 58.7%(32.4~83.5). WMS 30/30, 62.4%(41.7~72.2).

**실제 모델**(`claude-code`, claude-opus-5-5, `eval/results/extraction_*.json`, 원본 보고서 `eval/results/real/`):

| 항목 | 값 |
| --- | --- |
| 계약 조건 추출 정확도(8부, 106항목) | 96.2%. 틀린 4건은 모두 면책의 정성 조건 개수. 금액 계산에 영향 없음 |
| 면책 판단 정확도(32항목) | 태풍 100%, 항만 적체 96.9%(누리에너지 1건을 보수적으로 면책 보류) |
| 인용 원문 일치율 | 100% |
| 태풍 시나리오 정책 비교 | 정답지 결과와 동일(12,834,000 → 2,996,500) |
| 호출·비용·시간 | 24회, CLI 보고 비용 $1.98, 호출 시간 합계 270초(4개 병렬), mock 대체 0회 |

## 선행 조사: 이미 있는 것과 없는 것

주제를 고르기 전에 검색 9회(영어·한국어)로 겹치는 제품과 논문을 찾았다. "세상에 없다"는 증명은 불가능하고, 아래는 찾지 못했다는 기록이다.

- **있다.** SLA 마감 긴급도를 가중치로 쓰는 [현장서비스 배차](https://fieldcode.com/en/field-service-daily/how-ai-supports-sla-aware-scheduling), SLA 페널티를 비용 함수에 넣는 [클라우드 스케줄링 연구](https://arxiv.org/pdf/2505.12355), 계약서에서 페널티 조항을 분류·추출하는 [특허](https://image-ppubs.uspto.gov/dirsearch-public/print/downloadPdf/11755973), SLA 위반을 예측해 재배차를 트리거한다는 [물류 벤더 자료](https://oxmaint.com/industries/delivery-operations-management/ai-improve-sla-performance-delivery-operations).
- **못 찾았다.** 계약서 **조항의 구조**(요율 단위, 유예, 상한, 불가항력의 열거·포괄 표현, 통지 시한, 입증 조건)를 읽어 사건별 **실제 노출액**으로 바꾸고, 그 값으로 운영 배차를 바꾸며, 모든 판단에 원문을 인용하는 것. 한국어 지체상금 맥락에서는 관련 자료 자체가 없었다.
- 차별점을 한 문장으로: **"마감 긴급도"가 아니라 "계약이 실제로 물리는 돈"으로 배차하고, 그 돈의 근거를 조항 원문으로 보여 준다.**

## 구조

```
clausetower/
├── src/clausetower/
│   ├── schemas.py     데이터 계약(PenaltyTerms, Judgment, Breakdown, Report …)
│   ├── exposure.py    페널티 계산기. 결정적·순수. 유예→단위→요율/누진/정액→상한, 고객 합계 상한
│   ├── llm.py         LLM 단일 출입구(mock | claude-code | anthropic | auto), 구조화 출력, 실패 시 대체·기록
│   ├── extract.py     계약 → PenaltyTerms(인용 포함), 사건 × 계약 → 불가항력 판단(조건 기계적 결합)
│   ├── sim.py         배송 네트워크 시뮬레이터, 정책 5개, 우선순위 지역 탐색
│   ├── agent.py       파이프라인과 '물리는 순서' 표, 재시뮬레이션
│   ├── dashboard.py   단일 HTML 대시보드(인라인 SVG, 오프라인)
│   ├── server.py      웹 데모용 로컬 도우미(/extract, /judge, CORS)
│   ├── web/           engine.js(계산기·시뮬레이터 이식), render.js(공용 렌더), app.js(조작 패널·라이브 AI), style.css
│   └── cli.py         run | demo | serve | eval
├── contracts/         가상 계약서 8부(.md)와 정답지(golden/*.yaml)
├── scenarios/         교란 3종(태풍, 항만 적체, 자사 WMS 장애)
├── prompts/           extract.md, judge.md
├── eval/              run_eval.py(robustness, extraction), results/(측정값, 실제 모델 보고서)
├── tests/             39개
├── scripts/           build_site.py(웹 데모 조립), verify_engine.js(JS≡Python 검증), smoke_web.js(브라우저 스모크), real_run.py, screenshot.js
├── .github/workflows/ pages.yml(테스트 → 조립 → 검증 → gh-pages 배포)
└── docs/              proposal.md(기획서), demo-script.md(3분 대본), screenshots/
```

**설계 원칙**

- 돈 계산에 LLM을 쓰지 않는다. `exposure.py`는 입력이 같으면 출력이 같고, 계산 단계를 문장으로 남긴다.
- 모든 조건에 조항 번호와 원문 인용이 붙는다. 인용이 계약서에 그대로 있는지 시험과 eval이 확인한다.
- 면책의 최종 적용 여부는 모델의 `applies`를 믿지 않고 `has_clause ∧ event_covered ∧ notice_ok ∧ 조건 충족`으로 다시 만든다.
- 어느 순서가 낫다는 주장은 시뮬레이션 숫자로만 한다. 정책은 "트럭이 빌 때 무엇을 먼저 보내는가"만 다르고 나머지는 같다.
- LLM 호출이 실패하면 정답지로 대체하고 횟수를 보고서에 남긴다. 데모는 mock으로도 끝까지 돈다.
- 웹 데모의 엔진은 파이썬의 이식이며 둘의 결과가 같다는 것을 자동으로 검증한다. 라이브 분석의 세 연결 방식은 가짜 응답으로 브라우저 스모크 테스트를 돌리고(`scripts/smoke_web.js`), 구독 경로는 실제 CLI로 한 번 확인했다.

## 검증 절차(심사용)

```bash
pytest -q                                              # 39 passed
python -m clausetower demo --llm mock                  # 표의 숫자가 그대로 나온다(결정적)
python eval/run_eval.py robustness --seeds 30          # 90/90 승, 평균 절감률
python eval/run_eval.py extraction eval/results/real/report_typhoon.json   # 실제 모델 결과 채점(저장된 보고서)
python scripts/build_site.py && node scripts/verify_engine.js              # 웹 엔진 31/31 일치
node scripts/smoke_web.js site/index.html /tmp/shots                       # 브라우저 스모크(Playwright, API는 가짜 응답)
```

mock 모드에서 추출 정확도 100%는 정답지를 그대로 쓰기 때문이며 의미가 없다. 실제 모델 수치는 저장된 보고서(`eval/results/real/`)와 실행 로그(`run.log`)로 확인한다.

## 한계(정직하게)

- 시뮬레이터는 작은 모형이다(허브 1, 노선 8, 트럭 8, 화물 56, 건당 1적재). 절감률은 이 모형 안의 값이고 실제 네트워크 수치가 아니다.
- 계약서와 정답지를 같은 팀이 만들었다. 실제 계약서 블라인드 평가가 필요하다. 한국어 계약서만 다뤘다.
- 실제 모델 측정은 2개 시나리오 1회 실행이다. 분산을 재지 않았다.
- 탐색 근사 최적은 지역 탐색이며 진짜 최적이 아니다.
- 교란 동시 발생, 부분 적재, 환적, 통지 자동화는 없다(기획서 9절의 목표).
- 계약 해석의 최종 책임은 사람에게 있다. 이 도구는 노출액과 근거를 보여 주는 참모다.
- 웹 데모는 정적 페이지라 LLM 호출에 사용자의 키나 로컬 도우미가 필요하다. 업로드 계약의 화물 7건은 가상으로 만든다. PDF와 HWP 업로드는 아직 없다(텍스트로 붙여넣기).

## 배포

`main`에 푸시하면 GitHub Actions가 테스트, 사이트 조립, 엔진 검증을 거쳐 `gh-pages` 브랜치로 배포한다(`.github/workflows/pages.yml`). 저장소 설정의 Pages 소스가 `gh-pages` 브랜치여야 한다.
