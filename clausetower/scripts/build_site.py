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
<title>ClauseTower — 계약을 읽는 물류 관제탑</title>
<link rel="preconnect" href="https://fonts.googleapis.com"><link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans+KR:wght@400;500;600;700&family=IBM+Plex+Mono:wght@400;500&display=swap" rel="stylesheet">
<link rel="stylesheet" href="style.css"></head><body>
<header class="appbar">
  <div class="brand"><span class="mark">Clause<b>Tower</b></span><span class="tag">급한 순서가 아니라, 물리는 순서로</span></div>
  <span class="spacer"></span>
  <nav class="seg tabs" id="tabs"></nav>
  <span class="status-chip" id="conn-chip"><i></i><span>AI 연결 안 됨 · 아래 ③에서 연결</span></span>
</header>
<div class="shell">
<aside class="panel" id="panel">
  <h2>사건</h2><div class="grp" id="panel-event"></div>
  <h2>운영</h2><div class="grp" id="panel-ops"></div>
  <h2>화물·출처</h2><div class="grp" id="panel-cargo"></div>
  <h2>면책 판단 (사람의 최종 결정)</h2><div class="grp" id="panel-judge"></div>
  <div class="grp"><button class="btn ghost" id="c-reset" style="width:100%">원래 사건으로 되돌리기</button></div>
</aside>
<main class="canvas">
  <section class="card"><div class="head"><div><h2 id="sc-title"></h2><p class="lead" id="sc-desc" style="margin-bottom:8px"></p><div class="chips" id="sc-event"></div></div><div class="chips" id="src-note"></div></div>
    <div class="kpis" id="kpis"></div><div class="hot-row" id="hot"></div></section>
  <section class="card"><div class="head"><h2>계약 케이스 <small>고객 8곳의 지연 페널티 조건을 항목별로. 카드의 "원문 보기"가 인용 문장을 강조해 연다.</small></h2><div class="toggle" id="board-toggle"><button data-mode="cards" class="on">카드</button><button data-mode="matrix">비교표</button></div></div><div id="board" class="board"></div></section>
  <section class="card"><h2>물리는 순서 <small>대기열이 가장 길었던 시점 <span id="rank-at"></span>. 왼쪽이 ClauseTower 순위, 그 옆이 기존 마감 순위와 변동.</small></h2><p class="lead" id="rank-sub"></p>
    <div style="overflow-x:auto"><table><thead><tr><th class="n">노출 순위</th><th class="n">마감 순위</th><th>화물</th><th>고객</th><th class="n">마감까지</th><th class="n">지금 보내면</th><th class="n">한 사이클 미루면</th><th class="n">물리는 돈</th><th>판단과 근거</th></tr></thead><tbody id="rank-body"></tbody></table></div><button class="btn ghost" id="rank-more" style="margin-top:10px"></button></section>
  <div class="grid2">
    <section class="card"><h2>누적 페널티 <small>시간에 따라 쌓이는 페널티. 낮을수록 좋다.</small></h2><div class="legend"><span><i style="background:var(--penalty)"></i>기존(마감 순)</span><span><i style="background:var(--tower)"></i>ClauseTower</span><span><i style="background:var(--neutral)"></i>탐색 근사 최적(점선)</span></div><div id="curve"></div></section>
    <section class="card"><h2>정책별 총 페널티 <small>같은 화물, 같은 교란, 순서만 다르다.</small></h2><div id="bars" style="margin-top:14px"></div><div class="row" style="margin-top:10px"><button class="btn" id="btn-search">탐색 근사 최적 계산 (수 초)</button><span class="hint" id="search-note" style="font-size:12.5px;color:var(--ink-3)"></span></div></section>
  </div>
  <section class="card" id="live"><h2>실제 케이스 분석 <small>계약서를 올리거나 사건을 적으면 AI가 바로 읽고 판단해 시뮬레이션에 넣는다.</small></h2>
    <div class="steps">
      <div class="step"><h3><span class="no">1</span>AI 연결</h3>
        <select id="k-backend"><option value="api">Anthropic API 키 (브라우저에서 직접 호출)</option><option value="helper">로컬 도우미 (Claude 구독·Claude Code CLI, 사내 LLM 중계)</option><option value="custom">사내·호환 엔드포인트 (직접 호출)</option></select>
        <div class="hint" id="k-help"></div>
        <div data-for="api"><div class="row"><input type="password" id="k-key" placeholder="sk-ant-…" style="flex:1"><button class="btn" id="k-save">저장</button><button class="btn ghost" id="k-clear">지움</button></div><div class="hint">키는 이 브라우저에만 저장되고 api.anthropic.com으로만 간다.</div>
          <select id="k-model" style="margin-top:6px"><option value="claude-opus-5-5">claude-opus-5-5 (정확, 느림)</option><option value="claude-sonnet-5-5">claude-sonnet-5-5 (빠름)</option></select></div>
        <div data-for="helper"><div class="row"><input type="text" id="h-url" value="http://127.0.0.1:8787" style="flex:1"><button class="btn" id="h-check">연결 확인</button></div><div class="hint">PC에서 <code>python -m clausetower serve --llm claude-code</code>(구독) 또는 <code>--llm openai</code>(사내 LLM)를 띄운다.</div></div>
        <div data-for="custom"><select id="c-proto"><option value="openai">OpenAI 호환 (chat/completions + tools)</option><option value="anthropic">Anthropic 호환 (v1/messages)</option></select><input type="text" id="c-url" placeholder="기본 주소 https://llm.company.local/v1" style="margin-top:6px"><input type="text" id="c-model" placeholder="모델 이름" style="margin-top:6px"><input type="password" id="c-key" placeholder="토큰(선택) · Bearer 또는 x-api-key" style="margin-top:6px"><div class="hint">게이트웨이가 CORS를 허용해야 한다. 막히면 로컬 도우미로 중계한다.</div></div>
        <div class="out" id="k-status">연결 전</div></div>
      <div class="step"><h3><span class="no">2</span>계약서 올리기 → 조건 추출 → 시뮬레이션에 추가</h3>
        <input type="text" id="u-name" placeholder="고객 이름(예: 새벽물산)"><input type="file" id="u-file" accept=".txt,.md,.docx"><div class="hint">txt, md, docx 또는 아래에 붙여넣기. 지체상금·유예·상한·불가항력 조항이 있는 부분이면 충분하다.</div>
        <textarea id="u-text" rows="7" placeholder="계약서 본문"></textarea>
        <div class="row"><button class="btn primary" id="u-run">AI로 조건 추출하고 추가</button><button class="btn ghost" id="u-sample">예시 계약서</button><button class="btn ghost" id="u-remove">추가한 고객 제거</button></div><div class="out" id="u-out">대기</div></div>
      <div class="step"><h3><span class="no">3</span>사건 입력 → 계약별 면책 재판단</h3>
        <input type="text" id="e-type" placeholder="사건 유형(예: 화물연대 파업)"><textarea id="e-desc" rows="5" placeholder="무슨 일이 어떻게 일어났는지. 누구 책임인지, 통지는 언제 했는지, 입증 자료가 있는지."></textarea><div class="hint">통지 시점과 사실 관계는 왼쪽 패널의 값을 함께 보낸다. AI 없이 손으로 정하려면 왼쪽 "면책 판단"에서 고객별로 고른다.</div>
        <div class="row"><button class="btn primary" id="e-run">AI로 면책 다시 판단</button><button class="btn ghost" id="e-sample">예시 사건</button><button class="btn ghost" id="e-reset">원래 판단으로</button></div><div class="out" id="e-out">대기</div></div>
    </div></section>
  <section class="card"><details class="sec" open><summary><h2>배차 간트 <small>트럭별 운행. 막대 색은 고객, 빨간 테두리는 지연, 빗금은 결항.</small></h2></summary>
    <div class="legend" id="clegend" style="margin-top:10px"></div><p class="lead" id="g-base-t"></p><div class="gantt-wrap" id="g-base"></div><p class="lead" id="g-ours-t" style="margin-top:14px"></p><div class="gantt-wrap" id="g-ours"></div></details></section>
  <section class="card"><details class="sec"><summary><h2>실행 기록과 이 데모에 대해</h2></summary><ol class="log" id="log"></ol>
    <p class="lead" style="margin-top:12px">가상의 고객·계약·사건이다. 계약 조건은 정답지 또는 실제 Claude가 읽은 결과 중에서 고를 수 있고, 면책의 최종 적용 여부는 통지 시점과 사실 관계를 조건으로 결합해 브라우저에서 다시 계산한다. 돈 계산과 배차 시뮬레이션은 전부 이 페이지의 JavaScript가 수행하며 서버로 아무것도 보내지 않는다. 파이썬 구현과 같은 결과를 내는지는 저장소의 <code>scripts/verify_engine.js</code>가 확인한다. 코드와 기획서: <a href="https://github.com/namojo/clausetower">github.com/namojo/clausetower</a></p></details></section>
</main></div>
<div class="scrim" id="scrim"></div><aside class="drawer" id="drawer" aria-label="계약서 원문"><div class="dh"><div><b id="drawer-title"></b><div class="hint" id="drawer-sub" style="font-size:12.5px;color:var(--ink-3)"></div></div><span class="spacer" style="flex:1"></span><button class="btn ghost" id="drawer-close">닫기 ✕</button></div><div class="db" id="drawer-body"></div></aside>
<div class="tip" id="tip"></div><footer id="foot"></footer>
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
