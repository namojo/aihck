// 브라우저 엔진(engine.js)이 파이썬 구현과 같은 총 배상금을 내는지 확인한다.
// 사용: node scripts/verify_engine.js   (먼저 python scripts/build_site.py, python -m clausetower demo --llm mock)
const fs = require('fs'), path = require('path'), vm = require('vm');
const ROOT = path.resolve(__dirname, '..');
const CT = require(path.join(ROOT, 'src/clausetower/web/engine.js'));
const ctx = { window: {} }; vm.runInNewContext(fs.readFileSync(path.join(ROOT, 'site/data.js'), 'utf8'), ctx); const D = ctx.window.CT_DATA;
const POLICIES = ['deadline_first', 'fifo', 'value_first', 'exposure_first', 'exposure_abs'];
let fail = 0, checks = 0;
function compare(label, R, py) {
  for (const p of POLICIES) { checks++; const a = R.policies[p].total_penalty_krw, b = py.policies[p].total_penalty_krw; const ok = a === b; if (!ok) fail++;
    console.log(`${ok ? 'OK  ' : 'DIFF'} ${label} ${p.padEnd(15)} js=${a.toLocaleString()} py=${b.toLocaleString()}`); }
  checks++; const ra = R.ranking.map(r => r.shipment_id).join(','), rb = py.ranking.map(r => r.shipment_id).join(','); const okr = ra === rb; if (!okr) fail++;
  console.log(`${okr ? 'OK  ' : 'DIFF'} ${label} ranking order${okr ? '' : `\n   js=${ra}\n   py=${rb}`}`);
}
for (const S of D.scenarios) {
  const sid = S.scenario.id;
  const golden = path.join(ROOT, 'out/demo', `report_${sid}.json`);
  if (fs.existsSync(golden)) { const py = JSON.parse(fs.readFileSync(golden, 'utf8')); const judgments = {}; for (const c of D.customers) judgments[c.id] = CT.deriveJudgment(S.judgments.golden[c.id], D.sources.golden.terms[c.id], S.scenario.event, null);
    compare(`${sid}/golden`, CT.buildReport({ scenario: S.scenario, customers: D.customers, terms: D.sources.golden.terms, extraction: D.sources.golden.extraction, judgments, shipments: S.shipments_by_seed.A, llm_mode: 'golden' }), py); }
  const real = path.join(ROOT, 'eval/results/real', `report_${sid}.json`);
  if (fs.existsSync(real) && S.judgments.real) { const py = JSON.parse(fs.readFileSync(real, 'utf8')); const judgments = {}; for (const c of D.customers) judgments[c.id] = CT.deriveJudgment(S.judgments.real[c.id], D.sources.real.terms[c.id], S.scenario.event, null);
    compare(`${sid}/real`, CT.buildReport({ scenario: S.scenario, customers: D.customers, terms: D.sources.real.terms, extraction: D.sources.real.extraction, judgments, shipments: S.shipments_by_seed.A, llm_mode: 'real' }), py); }
}
// 탐색은 난수가 달라 값이 다를 수 있으니 '시작점보다 나쁘지 않다'만 본다
const S0 = D.scenarios[0]; const j0 = {}; for (const c of D.customers) j0[c.id] = CT.deriveJudgment(S0.judgments.golden[c.id], D.sources.golden.terms[c.id], S0.scenario.event, null);
const R0 = CT.buildReport({ scenario: S0.scenario, customers: D.customers, terms: D.sources.golden.terms, extraction: D.sources.golden.extraction, judgments: j0, shipments: S0.shipments_by_seed.A, llm_mode: 'golden', withSearch: true, searchOpts: { restarts: 2, sweeps: 1 } });
checks++; if (R0.policies.search_best.total_penalty_krw > R0.policies.exposure_first.total_penalty_krw) { fail++; console.log('DIFF search worse than start'); } else console.log(`OK   search ${R0.policies.search_best.total_penalty_krw.toLocaleString()} <= exposure_first ${R0.policies.exposure_first.total_penalty_krw.toLocaleString()}`);
console.log(`\n${checks - fail}/${checks} checks passed`);
process.exit(fail ? 1 : 0);
