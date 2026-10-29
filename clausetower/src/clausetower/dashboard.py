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
<title>ClauseTower 관제</title><style>__CSS__</style></head><body>
<header><h1>ClauseTower</h1><span class="tag">급한 순서가 아니라, 물리는 순서로 — 계약 조항을 읽는 물류 관제탑</span><nav class="tabs">__TABS__</nav></header>
<main>
<section><h2 id="sc-title"></h2><p class="sub" id="sc-desc"></p><p class="sub" id="sc-event"></p><div class="kpis" id="kpis"></div></section>
<section><h2>물리는 순서 <small>대기열이 가장 길었던 시점 <span id="rank-at"></span>의 대기 화물. 왼쪽이 ClauseTower 순위, 그 옆이 기존 마감 순위와 변동.</small></h2><p class="sub" id="rank-sub"></p>
<div style="overflow-x:auto"><table><thead><tr><th class="n">노출 순위</th><th class="n">마감 순위</th><th>화물</th><th>고객</th><th class="n">마감까지</th><th class="n">지금 보내면</th><th class="n">한 사이클 미루면</th><th class="n">물리는 돈</th><th>판단과 근거</th></tr></thead><tbody id="rank-body"></tbody></table></div><button class="more" id="rank-more" style="margin-top:10px"></button></section>
<div class="grid2">
<section><h2>누적 페널티 <small>시간에 따라 쌓이는 페널티. 낮을수록 좋다.</small></h2><div class="legend"><span><i style="background:var(--base)"></i>기존(마감 순)</span><span><i style="background:var(--ours)"></i>ClauseTower</span><span><i style="background:var(--search)"></i>탐색 근사 최적(점선)</span></div><div id="curve"></div></section>
<section><h2>정책별 총 페널티 <small>같은 화물, 같은 교란, 순서만 다르다.</small></h2><div id="bars" style="margin-top:12px"></div></section>
</div>
<section><h2>고객별 결과 <small>계약 조건, 이번 사건의 면책 판단, 정책별 페널티.</small></h2><table><thead><tr><th>고객</th><th>계약 조건(추출)</th><th>면책 판단</th><th class="n">기존</th><th class="n">ClauseTower</th></tr></thead><tbody id="cust-body"></tbody></table></section>
<section><h2>배차 간트 <small>트럭별 운행. 막대 색은 고객, 빨간 테두리는 지연, 빗금은 결항.</small></h2>
<div class="legend">__CLEGEND__</div>
<p class="sub" id="g-base-t"></p><div class="gantt-wrap" id="g-base"></div><p class="sub" id="g-ours-t" style="margin-top:14px"></p><div class="gantt-wrap" id="g-ours"></div></section>
<section><h2>계약서 근거 <small>고객별 추출 조건과 원문 인용. "그 조항 어디 있어요?"에 바로 답한다.</small></h2><div class="cards" id="cards"></div></section>
<section><h2>에이전트 실행 기록</h2><ol class="log" id="log"></ol></section>
</main><div class="tip" id="tip"></div><footer id="foot"></footer>
<script>__JS__</script></body></html>"""


def build_dashboard(reports: list[Report], out_path: Path) -> Path:
    tabs = "".join(f'<button class="tab" data-id="{r.scenario.id}">{r.scenario.title}</button>' for r in reports)
    legend = "".join(f'<span><i style="background:var(--c{i + 1})"></i>{c.name}</span>' for i, c in enumerate(reports[0].customers))
    data = json.dumps([json.loads(r.model_dump_json()) for r in reports], ensure_ascii=False)
    web = Path(__file__).parent / "web"
    render_js = (web / "render.js").read_text(encoding="utf-8")
    css = CSS.replace("__STYLE__", (web / "style.css").read_text(encoding="utf-8"))
    html = (HTML.replace("__CSS__", css).replace("__TABS__", tabs).replace("__CLEGEND__", legend)
            .replace("__JS__", JS.replace("__RENDER__", render_js).replace("__DATA__", data.replace("</", "<\\/"))))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path
