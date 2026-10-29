"""GitHub Pages용 웹 데모를 site/에 조립한다. 브라우저 안에서 시뮬레이션이 돌아가는 정적 사이트다.

  python scripts/build_site.py            # site/ 생성
구성: index.html, style.css, engine.js(계산기·시뮬레이터 이식), render.js(공용 렌더), app.js(조작 패널), data.js(계약·정답지·실제 모델 결과·화물 배치)
"""
from __future__ import annotations

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from clausetower.contracts import list_scenarios, load_contract_text, load_customers, load_golden_judgment, load_golden_terms, load_scenario  # noqa: E402
from clausetower.schemas import ExtractionResult, ForceMajeureJudgment, Report  # noqa: E402
from clausetower.sim import build_shipments  # noqa: E402

WEB = ROOT / "src" / "clausetower" / "web"
SITE = ROOT / "site"
REAL_DIR = ROOT / "eval" / "results" / "real"
SEEDS = [None, 101, 102, 103, 104]  # None = 시나리오 기본 시드


def dump(model):
    return json.loads(model.model_dump_json())


def build_data() -> dict:
    customers = load_customers()
    golden_terms = {c.id: dump(load_golden_terms(c.id)) for c in customers}
    golden_extraction = {cid: {"terms": t, "confidence": 1.0, "ambiguities": ["정답지(팀 작성)"]} for cid, t in golden_terms.items()}
    real_reports = {p.stem.replace("report_", ""): Report.model_validate_json(p.read_text(encoding="utf-8")) for p in REAL_DIR.glob("report_*.json")}
    real_terms = real_extraction = None
    real_meta = {}
    if real_reports:
        any_r = next(iter(real_reports.values()))
        real_terms = {cid: dump(t) for cid, t in any_r.terms.items()}
        real_extraction = {cid: dump(e) for cid, e in any_r.extraction.items()}
        real_meta = {"llm_mode": any_r.llm_mode, "model": "claude-opus-5-5", "scenarios": sorted(real_reports)}
    scenarios = []
    order = {"typhoon": 0, "port_congestion": 1, "wms_outage": 2}
    for sid in sorted(list_scenarios(), key=lambda x: order.get(x, 9)):
        sc = load_scenario(sid)
        by_seed = {}
        for i, seed in enumerate(SEEDS):
            s2 = sc if seed is None else sc.model_copy(update={"seed": seed})
            by_seed[chr(ord("A") + i)] = [dump(s) for s in build_shipments(s2, customers)]
        judg = {"golden": {c.id: dump(load_golden_judgment(c.id, sid)) for c in customers}}
        if sid in real_reports:
            judg["real"] = {cid: dump(j) for cid, j in real_reports[sid].judgments.items()}
        scenarios.append({"scenario": dump(sc), "shipments_by_seed": by_seed, "judgments": judg})
    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "customers": [dump(c) for c in customers],
        "contracts": {c.id: load_contract_text(c.id) for c in customers},
        "sources": {"golden": {"terms": golden_terms, "extraction": golden_extraction, "label": "정답지(팀 작성)"},
                    **({"real": {"terms": real_terms, "extraction": real_extraction, "label": f"실제 Claude 추출({real_meta.get('model')})", "meta": real_meta}} if real_terms else {})},
        "scenarios": scenarios,
        "prompts": {"extract": (ROOT / "prompts" / "extract.md").read_text(encoding="utf-8"),
                    "judge": (ROOT / "prompts" / "judge.md").read_text(encoding="utf-8")},
        "schemas": {"extract": ExtractionResult.model_json_schema(), "judge": ForceMajeureJudgment.model_json_schema()},
    }


HTML = """<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ClauseTower 웹 데모 — 계약을 읽는 물류 관제탑</title><link rel="stylesheet" href="style.css"><style>
.controls{display:grid;grid-template-columns:repeat(auto-fit,minmax(230px,1fr));gap:12px 18px}.ctl{display:flex;flex-direction:column;gap:4px;font-size:13px;color:var(--ink2)}
.ctl b{color:var(--ink);font-weight:600}.ctl input[type=range]{width:100%}.ctl select,.ctl button{font:inherit;padding:5px 8px;border:1px solid var(--axis);border-radius:8px;background:#fff}
.ctl .val{font-variant-numeric:tabular-nums;color:var(--ink)}.row{display:flex;gap:10px;flex-wrap:wrap;align-items:center}
.ovr{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:6px 14px;font-size:13px}.ovr label{display:flex;gap:6px;align-items:center}
.badge{display:inline-block;border-radius:999px;padding:2px 10px;font-size:12px;background:#eef3fb;color:#1c5cab;border:1px solid #c9dbf5}
.note{font-size:13px;color:var(--ink2)}a{color:var(--ours)}
</style></head><body>
<header><h1>ClauseTower</h1><span class="tag">급한 순서가 아니라, 물리는 순서로 — 계약 조항을 읽는 물류 관제탑</span><nav class="tabs" id="tabs"></nav></header>
<main>
<section><h2>사고 상황 바꾸기 <small>값을 바꾸면 브라우저 안에서 시뮬레이션이 다시 돌고 아래 모든 화면이 갱신된다.</small></h2>
<div class="controls" id="controls"></div>
<div style="margin-top:12px"><b style="font-size:13px">사람의 최종 결정</b> <span class="note">면책 판단을 사람이 뒤집을 수 있다. 뒤집은 고객은 표시된다.</span><div class="ovr" id="overrides"></div></div>
<p class="note" id="src-note" style="margin:10px 0 0"></p></section>
<section id="live"><h2>실제 케이스 분석(AI) <small>계약서를 올리거나 사건을 직접 적으면 이 브라우저에서 Claude를 호출해 바로 분석한다.</small></h2>
<div class="controls">
  <div class="ctl"><b>연결 방식</b><select id="k-backend">
      <option value="api">Anthropic API 키 (브라우저에서 직접 호출)</option>
      <option value="helper">로컬 도우미 (Claude 구독·Claude Code CLI, 사내 LLM 중계)</option>
      <option value="custom">사내·호환 엔드포인트 (브라우저에서 직접 호출)</option></select>
    <span class="note" id="k-help"></span></div>
  <div class="ctl" data-for="api"><b>Anthropic API 키</b><div class="row"><input type="password" id="k-key" placeholder="sk-ant-…" style="flex:1;font:inherit;padding:5px 8px;border:1px solid var(--axis);border-radius:8px"><button id="k-save">저장</button><button id="k-clear">지움</button></div>
    <span class="note">키는 이 브라우저의 localStorage에만 저장되고 api.anthropic.com으로만 전송된다. 공용 PC에서는 쓰고 나서 지운다.</span></div>
  <div class="ctl" data-for="api"><b>모델</b><select id="k-model"><option value="claude-opus-5-5">claude-opus-5-5 (정확, 느림)</option><option value="claude-sonnet-5-5">claude-sonnet-5-5 (빠름)</option></select></div>
  <div class="ctl" data-for="helper"><b>로컬 도우미 주소</b><div class="row"><input type="text" id="h-url" value="http://127.0.0.1:8787" style="flex:1;font:inherit;padding:5px 8px;border:1px solid var(--axis);border-radius:8px"><button id="h-check">연결 확인</button></div>
    <span class="note">PC에서 <code>python -m clausetower serve --llm claude-code</code>(구독) 또는 <code>--llm openai</code>(사내 LLM, 환경변수로 주소 지정)를 띄운다. 계약서는 이 PC와 도우미 사이에서만 오간다.</span></div>
  <div class="ctl" data-for="custom"><b>프로토콜</b><select id="c-proto"><option value="openai">OpenAI 호환 (chat/completions + tools)</option><option value="anthropic">Anthropic 호환 (v1/messages)</option></select></div>
  <div class="ctl" data-for="custom"><b>기본 주소</b><input type="text" id="c-url" placeholder="https://llm.company.local/v1" style="font:inherit;padding:5px 8px;border:1px solid var(--axis);border-radius:8px"><span class="note">게이트웨이가 CORS를 허용해야 한다. 막히면 로컬 도우미(--llm openai)로 중계한다.</span></div>
  <div class="ctl" data-for="custom"><b>모델 이름</b><input type="text" id="c-model" placeholder="예: company-llm-70b" style="font:inherit;padding:5px 8px;border:1px solid var(--axis);border-radius:8px"></div>
  <div class="ctl" data-for="custom"><b>토큰(선택)</b><input type="password" id="c-key" placeholder="Bearer 토큰 또는 x-api-key" style="font:inherit;padding:5px 8px;border:1px solid var(--axis);border-radius:8px"><span class="note">이 브라우저에만 저장된다.</span></div>
  <div class="ctl"><b>상태</b><span class="note" id="k-status">-</span></div>
</div>
<div class="grid2" style="margin-top:14px">
  <div><b style="font-size:14px">① 계약서 올리기 → 조건 추출 → 시뮬레이션에 추가</b>
    <div class="ctl" style="margin-top:6px"><input type="text" id="u-name" placeholder="고객 이름(예: 새벽물산)" style="font:inherit;padding:5px 8px;border:1px solid var(--axis);border-radius:8px">
      <input type="file" id="u-file" accept=".txt,.md,.docx"><span class="note">txt, md, docx. 또는 아래에 붙여넣기.</span>
      <textarea id="u-text" rows="7" placeholder="계약서 본문을 붙여넣는다. 지체상금, 유예, 상한, 불가항력 조항이 있는 부분이면 충분하다." style="font:inherit;padding:8px;border:1px solid var(--axis);border-radius:8px"></textarea>
      <div class="row"><button id="u-run">AI로 조건 추출하고 추가</button><button id="u-sample">예시 계약서 넣기</button><button id="u-remove">추가한 고객 모두 제거</button></div>
      <div id="u-out" class="note"></div></div></div>
  <div><b style="font-size:14px">② 사건 직접 입력 → 8개 계약 면책 재판단</b>
    <div class="ctl" style="margin-top:6px"><input type="text" id="e-type" placeholder="사건 유형(예: 화물연대 파업)" style="font:inherit;padding:5px 8px;border:1px solid var(--axis);border-radius:8px">
      <textarea id="e-desc" rows="4" placeholder="무슨 일이 어떻게 일어났는지. 누구 책임인지, 통지는 언제 했는지, 입증 자료가 있는지." style="font:inherit;padding:8px;border:1px solid var(--axis);border-radius:8px"></textarea>
      <span class="note">통지 시점과 사실 관계는 위의 '사고 상황 바꾸기' 값을 함께 보낸다.</span>
      <div class="row"><button id="e-run">AI로 면책 다시 판단</button><button id="e-sample">예시 사건 넣기</button><button id="e-reset">원래 판단으로</button></div>
      <div id="e-out" class="note"></div></div></div>
</div></section>
<section><h2 id="sc-title"></h2><p class="sub" id="sc-desc"></p><p class="sub" id="sc-event"></p><div class="kpis" id="kpis"></div></section>
<section><h2>물리는 순서 <small>대기열이 가장 길었던 시점 <span id="rank-at"></span>의 대기 화물. 왼쪽이 ClauseTower 순위, 그 옆이 기존 마감 순위와 변동.</small></h2><p class="sub" id="rank-sub"></p>
<div style="overflow-x:auto"><table><thead><tr><th class="n">노출 순위</th><th class="n">마감 순위</th><th>화물</th><th>고객</th><th class="n">마감까지</th><th class="n">지금 보내면</th><th class="n">한 사이클 미루면</th><th class="n">물리는 돈</th><th>판단과 근거</th></tr></thead><tbody id="rank-body"></tbody></table></div><button class="more" id="rank-more" style="margin-top:10px"></button></section>
<div class="grid2">
<section><h2>누적 페널티 <small>시간에 따라 쌓이는 페널티. 낮을수록 좋다.</small></h2><div class="legend"><span><i style="background:var(--base)"></i>기존(마감 순)</span><span><i style="background:var(--ours)"></i>ClauseTower</span><span><i style="background:var(--search)"></i>탐색 근사 최적(점선)</span></div><div id="curve"></div></section>
<section><h2>정책별 총 페널티 <small>같은 화물, 같은 교란, 순서만 다르다.</small></h2><div id="bars" style="margin-top:12px"></div><div class="row" style="margin-top:8px"><button class="more" id="btn-search">탐색 근사 최적 계산(수 초)</button><span class="note" id="search-note"></span></div></section>
</div>
<section><h2>고객별 결과 <small>계약 조건, 이번 사건의 면책 판단, 정책별 페널티.</small></h2><table><thead><tr><th>고객</th><th>계약 조건(추출)</th><th>면책 판단</th><th class="n">기존</th><th class="n">ClauseTower</th></tr></thead><tbody id="cust-body"></tbody></table></section>
<section><h2>배차 간트 <small>트럭별 운행. 막대 색은 고객, 빨간 테두리는 지연, 빗금은 결항.</small></h2><div class="legend" id="clegend"></div>
<p class="sub" id="g-base-t"></p><div class="gantt-wrap" id="g-base"></div><p class="sub" id="g-ours-t" style="margin-top:14px"></p><div class="gantt-wrap" id="g-ours"></div></section>
<section><h2>계약서 근거 <small>고객별 추출 조건과 원문 인용. "그 조항 어디 있어요?"에 바로 답한다.</small></h2><div class="cards" id="cards"></div>
<details style="margin-top:12px"><summary style="cursor:pointer;color:var(--ours)">계약서 전문 8부 보기</summary><div id="contracts"></div></details></section>
<section><h2>에이전트 실행 기록</h2><ol class="log" id="log"></ol></section>
<section><h2>이 데모에 대해</h2><p class="note">가상의 고객·계약·사건이다. 계약 조건은 '정답지' 또는 '실제 Claude가 계약서를 읽은 결과' 중에서 고를 수 있고, 면책의 최종 적용 여부는 통지 시점과 사실 관계를 조건으로 결합해 브라우저에서 다시 계산한다. 돈 계산과 배차 시뮬레이션은 전부 이 페이지의 JavaScript가 수행하며 서버로 아무것도 보내지 않는다. 파이썬 구현과 같은 결과를 내는지는 저장소의 <code>scripts/verify_engine.js</code>가 확인한다. 코드와 기획서: <a href="https://github.com/namojo/clausetower">github.com/namojo/clausetower</a></p></section>
</main><div class="tip" id="tip"></div><footer id="foot"></footer>
<script src="https://cdnjs.cloudflare.com/ajax/libs/mammoth/1.6.0/mammoth.browser.min.js" defer></script>
<script src="data.js"></script><script src="engine.js"></script><script src="render.js"></script><script src="app.js"></script></body></html>
"""


def main() -> int:
    if SITE.exists():
        shutil.rmtree(SITE)
    SITE.mkdir()
    data = build_data()
    (SITE / "data.js").write_text("window.CT_DATA = " + json.dumps(data, ensure_ascii=False).replace("</", "<\\/") + ";\n", encoding="utf-8")
    for name in ("engine.js", "render.js", "style.css", "app.js"):
        shutil.copy2(WEB / name, SITE / name)
    (SITE / "index.html").write_text(HTML, encoding="utf-8")
    (SITE / ".nojekyll").write_text("", encoding="utf-8")
    print(f"site/ 생성: 시나리오 {len(data['scenarios'])}개, 출처 {list(data['sources'])}, data.js {((SITE / 'data.js').stat().st_size) // 1024}KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
