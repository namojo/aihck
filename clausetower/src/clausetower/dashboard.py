"""단일 HTML 대시보드. 외부 자원 없이 열린다(심사장 오프라인 대비). 데이터는 JSON으로 내장하고 차트는 인라인 SVG다."""

from __future__ import annotations

import json
from pathlib import Path

from .schemas import Report

CSS = """
__STYLE__
"""

JS = r"""
__RENDER__
const DATA = __DATA__;
let cur = DATA[0].scenario.id;
function render(){
  const R = DATA.find(d => d.scenario.id === cur);
  document.querySelectorAll('nav.tabs .tab').forEach(t => t.classList.toggle('on', t.dataset.id === cur));
  renderReport(R);
}
document.querySelectorAll('nav.tabs .tab').forEach(t=>t.addEventListener('click',()=>{cur=t.dataset.id;render();}));
render();
"""

HTML = """<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ClauseTower 관제</title><style>__CSS__ .shell{grid-template-columns:1fr}</style></head><body>
<header class="appbar"><div class="brand"><span class="mark">Clause<b>Tower</b></span><span class="tag">급한 순서가 아니라, 물리는 순서로</span></div><span class="spacer"></span><nav class="seg tabs" id="tabs">__TABS__</nav></header>
<div class="shell"><main class="canvas">
  <section class="card"><div class="head"><div><h2 id="sc-title"></h2><p class="lead" id="sc-desc" style="margin-bottom:8px"></p><div class="chips" id="sc-event"></div></div></div><div class="kpis" id="kpis"></div><div class="hot-row" id="hot"></div></section>
  <section class="card"><div class="head"><h2>계약 케이스 <small>고객별 지연 페널티 조건을 항목별로. "원문 보기"가 인용 문장을 강조해 연다.</small></h2><div class="toggle" id="board-toggle"><button data-mode="cards" class="on">카드</button><button data-mode="matrix">비교표</button></div></div><div id="board" class="board"></div></section>
  <section class="card"><h2>물리는 순서 <small>대기열이 가장 길었던 시점 <span id="rank-at"></span>.</small></h2><p class="lead" id="rank-sub"></p>
    <div style="overflow-x:auto"><table><thead><tr><th class="n">노출 순위</th><th class="n">마감 순위</th><th>화물</th><th>고객</th><th class="n">마감까지</th><th class="n">지금 보내면</th><th class="n">한 사이클 미루면</th><th class="n">물리는 돈</th><th>판단과 근거</th></tr></thead><tbody id="rank-body"></tbody></table></div><button class="btn ghost" id="rank-more" style="margin-top:10px"></button></section>
  <div class="grid2">
    <section class="card"><h2>누적 페널티</h2><div class="legend"><span><i style="background:var(--penalty)"></i>기존(마감 순)</span><span><i style="background:var(--tower)"></i>ClauseTower</span><span><i style="background:var(--neutral)"></i>탐색 근사 최적(점선)</span></div><div id="curve"></div></section>
    <section class="card"><h2>정책별 총 페널티</h2><div id="bars" style="margin-top:14px"></div></section>
  </div>
  <section class="card"><details class="sec" open><summary><h2>배차 간트</h2></summary><div class="legend" style="margin-top:10px">__CLEGEND__</div><p class="lead" id="g-base-t"></p><div class="gantt-wrap" id="g-base"></div><p class="lead" id="g-ours-t" style="margin-top:14px"></p><div class="gantt-wrap" id="g-ours"></div></details></section>
  <section class="card"><details class="sec"><summary><h2>에이전트 실행 기록</h2></summary><ol class="log" id="log"></ol></details></section>
</main></div>
<div class="scrim" id="scrim"></div><aside class="drawer" id="drawer"><div class="dh"><div><b id="drawer-title"></b><div id="drawer-sub" style="font-size:12.5px;color:var(--ink-3)"></div></div><span style="flex:1"></span><button class="btn ghost" id="drawer-close">닫기 ✕</button></div><div class="db" id="drawer-body"></div></aside>
<div class="tip" id="tip"></div><footer id="foot"></footer>
<script>window.CT_DATA = {contracts: __CONTRACTS__};</script>
<script>__JS__</script></body></html>
"""


def build_dashboard(reports: list[Report], out_path: Path) -> Path:
    from .contracts import load_contract_text
    tabs = "".join(f'<button class="tab" data-id="{r.scenario.id}">{r.scenario.title}</button>' for r in reports)
    contracts = json.dumps({c.id: load_contract_text(c.id) for c in reports[0].customers}, ensure_ascii=False).replace("</", "<\\/")
    legend = "".join(f'<span><i style="background:var(--c{(i % 8) + 1})"></i>{c.name}</span>' for i, c in enumerate(reports[0].customers))
    data = json.dumps([json.loads(r.model_dump_json()) for r in reports], ensure_ascii=False)
    web = Path(__file__).parent / "web"
    render_js = (web / "render.js").read_text(encoding="utf-8")
    css = CSS.replace("__STYLE__", (web / "style.css").read_text(encoding="utf-8"))
    html = (HTML.replace("__CSS__", css).replace("__CONTRACTS__", contracts).replace("__TABS__", tabs).replace("__CLEGEND__", legend)
            .replace("__JS__", JS.replace("__RENDER__", render_js).replace("__DATA__", data.replace("</", "<\\/"))))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path
