// 웹 데모 조작 패널. 상태 → 시나리오·판단 재구성 → 엔진 실행 → 공용 렌더.
(function () {
  const D = window.CT_DATA; const $ = s => document.querySelector(s);
  const state = { sid: D.scenarios[0].scenario.id, source: D.sources.real ? 'real' : 'golden', seed: 'A', overrides: {}, search: false, params: {}, extra: [], live: null };
  const scen = () => D.scenarios.find(s => s.scenario.id === state.sid);
  const fmt = n => n.toLocaleString('ko-KR');

  function defaults(sc) {
    const d = sc.disruption; const affected = Object.keys(d.route_multipliers || {});
    return { notice: sc.event.notice_sent_after_hours, facts: Object.assign({}, sc.event.facts || {}), trucks: sc.trucks, trucks_out: d.trucks_out || 0, trucks_out_until: d.trucks_out_until_h || 0, mult: affected.length ? d.route_multipliers[affected[0]] : 1, affected };
  }
  function resetParams() { state.params = defaults(scen().scenario); state.overrides = {}; state.search = false; }

  function currentSource() { const s = scen(); return (state.source === 'real' && s.judgments.real && D.sources.real) ? 'real' : 'golden'; }

  function currentEvent() { const S = scen().scenario; const p = state.params; return Object.assign({}, S.event, { notice_sent_after_hours: p.notice, facts: Object.assign({}, p.facts) }); }
  function allCustomers() { return D.customers.concat(state.extra.map(x => x.customer)); }
  function allTerms(src) { const t = Object.assign({}, D.sources[src].terms); state.extra.forEach(x => t[x.customer.id] = x.terms); return t; }
  function allExtraction(src) { const t = Object.assign({}, D.sources[src].extraction); state.extra.forEach(x => t[x.customer.id] = x.extraction); return t; }
  function baseJudgment(src, cid) { if (state.live && state.live.judgments[cid]) return state.live.judgments[cid]; const x = state.extra.find(e => e.customer.id === cid); if (x) return x.judgment; return scen().judgments[src][cid]; }

  function build() {
    const S = scen(); const src = currentSource(); const p = state.params; const base = S.scenario;
    const scenario = JSON.parse(JSON.stringify(base)); scenario.trucks = p.trucks; scenario.event.notice_sent_after_hours = p.notice; scenario.event.facts = Object.assign({}, p.facts);
    if (state.live) { scenario.event.event_type = state.live.event.event_type; scenario.event.description = state.live.event.description; scenario.title = base.title + ' → ' + state.live.event.event_type + '(AI 재판단)'; }
    scenario.disruption.trucks_out = Math.min(p.trucks_out, p.trucks); scenario.disruption.trucks_out_until_h = p.trucks_out_until;
    for (const r of p.affected) scenario.disruption.route_multipliers[r] = p.mult;
    const customers = allCustomers(); const terms = allTerms(src), extraction = allExtraction(src); const judgments = {};
    for (const c of customers) judgments[c.id] = CT.deriveJudgment(baseJudgment(src, c.id), terms[c.id], scenario.event, state.overrides[c.id]);
    let shipments = S.shipments_by_seed[state.seed].slice(); state.extra.forEach(x => shipments = shipments.concat(x.shipments)); shipments.sort((a, b) => a.ready_h - b.ready_h || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0));
    const label = D.sources[src].label + (state.extra.length ? ` + 업로드 ${state.extra.length}건(라이브 AI)` : '') + (state.live ? ' + 사건 재판단(라이브 AI)' : '');
    return CT.buildReport({ scenario, customers, terms, extraction, judgments, shipments, llm_mode: label, withSearch: state.search, searchOpts: { restarts: 6, sweeps: 2 } });
  }

  function renderControls() {
    const S = scen().scenario; const p = state.params; const d = S.disruption; const conds = new Set(); const src = currentSource();
    // 토글로 보여 주는 사실은 시나리오가 정의한 것과 정답지 계약의 정성 조건만. 모델이 추가로 적은 조건은 모델의 판단값을 그대로 둔다.
    for (const t of Object.values(D.sources.golden.terms)) for (const c of (t.force_majeure ? t.force_majeure.conditions : [])) conds.add(c);
    Object.keys(S.event.facts || {}).forEach(k => conds.add(k));
    const seedOpts = Object.keys(scen().shipments_by_seed).map(k => `<option value="${k}" ${k === state.seed ? 'selected' : ''}>화물 배치 ${k}</option>`).join('');
    const srcOpts = Object.keys(D.sources).filter(k => k === 'golden' || scen().judgments.real).map(k => `<option value="${k}" ${k === src ? 'selected' : ''}>${D.sources[k].label}</option>`).join('');
    let html = `
      <div class="ctl"><b>계약 읽기 출처</b><select id="c-source">${srcOpts}</select><span class="note">정답지와 실제 모델 추출을 바꿔 가며 비교</span></div>
      <div class="ctl"><b>화물 배치</b><select id="c-seed">${seedOpts}</select><span class="note">가액·노선·마감만 다른 56건 배치 5종</span></div>
      <div class="ctl"><b>고객 통지 시점</b><input type="range" id="c-notice" min="-1" max="48" step="1" value="${p.notice == null ? -1 : p.notice}"><span class="val" id="v-notice"></span></div>
      <div class="ctl"><b>트럭 수</b><input type="range" id="c-trucks" min="4" max="12" step="1" value="${p.trucks}"><span class="val" id="v-trucks"></span></div>`;
    if (d.trucks_out_until_h || d.trucks_out) html += `
      <div class="ctl"><b>결항 트럭 수</b><input type="range" id="c-out" min="0" max="8" step="1" value="${p.trucks_out}"><span class="val" id="v-out"></span></div>
      <div class="ctl"><b>결항 종료 시각</b><input type="range" id="c-until" min="0" max="36" step="1" value="${p.trucks_out_until}"><span class="val" id="v-until"></span></div>`;
    if (p.affected.length) html += `<div class="ctl"><b>피해 노선 이동시간 배율</b><input type="range" id="c-mult" min="1" max="2.5" step="0.1" value="${p.mult}"><span class="val" id="v-mult"></span></div>`;
    for (const c of conds) html += `<div class="ctl"><b>사실: ${c}</b><label class="row"><input type="checkbox" data-fact="${c}" ${p.facts[c] ? 'checked' : ''}> 충족(입증 자료 있음)</label></div>`;
    html += `<div class="ctl"><b>&nbsp;</b><button id="c-reset">원래 사건으로 되돌리기</button></div>`;
    $('#controls').innerHTML = html;
    const bind = (id, fn) => { const el = document.getElementById(id); if (el) el.addEventListener('input', fn); };
    bind('c-notice', e => { const v = +e.target.value; p.notice = v < 0 ? null : v; refresh(); });
    bind('c-trucks', e => { p.trucks = +e.target.value; refresh(); });
    bind('c-out', e => { p.trucks_out = +e.target.value; refresh(); });
    bind('c-until', e => { p.trucks_out_until = +e.target.value; refresh(); });
    bind('c-mult', e => { p.mult = +e.target.value; refresh(); });
    document.querySelectorAll('[data-fact]').forEach(el => el.addEventListener('change', e => { p.facts[e.target.dataset.fact] = e.target.checked; refresh(); }));
    $('#c-source').addEventListener('change', e => { state.source = e.target.value; state.overrides = {}; refresh(true); });
    $('#c-seed').addEventListener('change', e => { state.seed = e.target.value; refresh(); });
    $('#c-reset').addEventListener('click', () => { resetParams(); refresh(true); });
    const ov = D.customers.filter(c => D.sources[src].terms[c.id].force_majeure).map(c => `<label><input type="checkbox" data-ovr="${c.id}" ${state.overrides[c.id] ? 'checked' : ''}> ${c.name}: 면책 인정</label>`).join('');
    $('#overrides').innerHTML = ov;
    document.querySelectorAll('[data-ovr]').forEach(el => el.addEventListener('change', e => { const id = e.target.dataset.ovr; if (e.target.checked) state.overrides[id] = true; else delete state.overrides[id]; refresh(); }));
    $('#tabs').innerHTML = D.scenarios.map(s => `<button class="tab ${s.scenario.id === state.sid ? 'on' : ''}" data-id="${s.scenario.id}">${s.scenario.title}</button>`).join('');
    document.querySelectorAll('nav.tabs .tab').forEach(t => t.addEventListener('click', () => { state.sid = t.dataset.id; state.live = null; resetParams(); refresh(true); }));
    $('#clegend').innerHTML = allCustomers().map((c, i) => `<span><i style="background:var(--c${(i % 8) + 1})"></i>${c.name}</span>`).join('');
    $('#contracts').innerHTML = D.customers.map(c => `<details style="margin:6px 0"><summary>${c.name}</summary><pre style="white-space:pre-wrap;font:13px/1.5 inherit;background:#fff;border:1px solid var(--grid);border-radius:8px;padding:10px">${D.contracts[c.id].replace(/[&<>]/g, ch => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[ch]))}</pre></details>`).join('');
  }

  function showVals() {
    const p = state.params; const set = (id, v) => { const el = document.getElementById(id); if (el) el.textContent = v; };
    set('v-notice', p.notice == null ? '통지 안 함' : `발생 ${p.notice}시간 뒤`); set('v-trucks', `${p.trucks}대`); set('v-out', `${Math.min(p.trucks_out, p.trucks)}대`); set('v-until', `+${p.trucks_out_until}h까지`); set('v-mult', `${p.mult.toFixed(1)}배`);
  }

  function refresh(rebuild) {
    if (rebuild) renderControls(); showVals();
    const R = build(); window.CT_LAST = R; renderReport(R);
    const src = currentSource(); const meta = D.sources[src].meta;
    const changed = Object.entries(R.judgments).filter(([cid, j]) => { const b = (scen().judgments[src] || {})[cid]; return j.manual_override || (b && b.applies !== j.applies); });
    $('#src-note').innerHTML = `<span class="badge">출처: ${D.sources[src].label}</span> ` + (meta ? `실제 모델 실행은 저장소의 <code>eval/results/real/</code>에 보고서와 로그로 남아 있다. ` : '') +
      (changed.length ? `현재 설정에서 원래 판단과 달라진 고객: ${changed.map(([cid, j]) => `${R.customers.find(c => c.id === cid).name}(${j.manual_override ? '사람이 뒤집음' : '통지·사실 변경으로 재계산'})`).join(', ')}` : '면책 판단은 원래 사건과 같다.');
    $('#search-note').textContent = state.search ? '탐색 완료. 설정을 바꾸면 다시 계산해야 한다.' : '';
    $('#btn-search').disabled = state.search;
  }
  $('#btn-search').addEventListener('click', () => { $('#search-note').textContent = '탐색 중…'; setTimeout(() => { state.search = true; refresh(); }, 30); });
  const _refresh = refresh; refresh = function (rebuild) { if (!rebuild) state.search = false; _refresh(rebuild); };
  window.CT_APP = {
    state, currentEvent, customers: allCustomers, currentTerms: () => allTerms(currentSource()), contractText: cid => { const x = state.extra.find(e => e.customer.id === cid); return x ? x.text : D.contracts[cid]; },
    judgeUserText(cid, terms, ev, text) {
      const notice = ev.notice_sent_after_hours != null ? `운영팀은 사건 발생 ${ev.notice_sent_after_hours}시간 뒤에 고객에게 통지했다.` : '운영팀은 고객에게 통지하지 않았다.';
      const facts = Object.entries(ev.facts || {}).map(([k, v]) => `- ${k}: ${v ? '예' : '아니오'}`).join('\n') || '- (추가 사실 없음)';
      const clause = terms.force_majeure ? `추출된 불가항력 조항: 사유 ${JSON.stringify(terms.force_majeure.covered_events)}, 통지 시한 ${terms.force_majeure.notice_hours}시간, 조건 ${JSON.stringify(terms.force_majeure.conditions || [])}` : '추출 결과: 불가항력 조항 없음';
      return `고객 ID: ${cid}\n\n--- 사건 ---\n유형: ${ev.event_type}\n설명: ${ev.description}\n${notice}\n사실 관계:\n${facts}\n\n${clause}\n\n--- 계약서 전문 ---\n${text}`;
    },
    addCustomer(customer, terms, extraction, judgment, shipments) { state.extra.push({ customer, terms, extraction, judgment, shipments, text: $('#u-text').value }); refresh(true); },
    clearExtra() { state.extra = []; refresh(true); },
    setLiveEvent(event, judgments) { state.live = { event, judgments }; refresh(true); },
    clearLiveEvent() { state.live = null; refresh(true); },
  };
  resetParams(); refresh(true);
})();

// ---------------- 실제 케이스 분석(AI). 연결 방식 셋: API 키 직접 / 로컬 도우미(구독·사내 중계) / 사내·호환 엔드포인트 ----------------
(function () {
  const D = window.CT_DATA; const $ = s => document.querySelector(s);
  const store = { get: k => localStorage.getItem('clausetower.' + k) || '', set: (k, v) => v ? localStorage.setItem('clausetower.' + k, v) : localStorage.removeItem('clausetower.' + k) };
  const HELP = { api: '본인의 Anthropic API 키로 이 브라우저가 api.anthropic.com을 직접 호출한다. 서버를 거치지 않는다.',
    helper: '브라우저는 Claude 구독(CLI)을 직접 못 쓴다. PC에서 도우미를 띄우면 도우미가 기존 파이프라인(llm.py)으로 처리한다. 사내 LLM도 도우미가 중계할 수 있다.',
    custom: 'OpenAI 호환 또는 Anthropic 호환 사내 게이트웨이를 브라우저에서 직접 호출한다. 도구 호출(tool use)로 구조화 출력을 받는다.' };
  function backend() { return $('#k-backend').value; }
  function showBackend() { const b = backend(); document.querySelectorAll('[data-for]').forEach(el => el.style.display = el.dataset.for === b ? '' : 'none'); $('#k-help').textContent = HELP[b]; store.set('backend', b); }
  $('#k-backend').value = store.get('backend') || 'api'; $('#k-backend').addEventListener('change', showBackend); showBackend();
  const masked = v => v ? '••••••••' + v.slice(-4) : '';
  $('#k-key').value = masked(store.get('anthropic_key'));
  $('#k-save').onclick = () => { const v = $('#k-key').value.trim(); if (v && !v.startsWith('•')) { store.set('anthropic_key', v); $('#k-key').value = masked(v); status('키 저장됨(이 브라우저에만).'); } };
  $('#k-clear').onclick = () => { store.set('anthropic_key', ''); $('#k-key').value = ''; status('키 지움.'); };
  $('#h-url').value = store.get('helper_url') || 'http://127.0.0.1:8787'; $('#h-url').addEventListener('change', e => store.set('helper_url', e.target.value.trim()));
  $('#c-url').value = store.get('custom_url'); $('#c-model').value = store.get('custom_model'); $('#c-proto').value = store.get('custom_proto') || 'openai'; $('#c-key').value = masked(store.get('custom_key'));
  for (const [id, k] of [['c-url', 'custom_url'], ['c-model', 'custom_model'], ['c-proto', 'custom_proto']]) $('#' + id).addEventListener('change', e => store.set(k, e.target.value.trim()));
  $('#c-key').addEventListener('change', e => { const v = e.target.value.trim(); if (v && !v.startsWith('•')) { store.set('custom_key', v); e.target.value = masked(v); } });
  $('#h-check').onclick = async () => { try { const r = await fetch($('#h-url').value.replace(/\/$/, '') + '/health'); const j = await r.json(); status(`도우미 연결됨: LLM 모드 ${j.mode}, 모델 ${j.model}${j.mode === 'mock' ? ' — 주의: mock(자리표시자)' : ''}`); } catch (e) { status('도우미에 연결할 수 없다. 터미널에서 python -m clausetower serve 를 실행했는지, 주소가 맞는지 확인하라.'); } };
  function status(t) { $('#k-status').textContent = t; }

  function toolBlock(schema, toolName) { return { name: toolName, description: '결과를 이 스키마로 돌려준다.', input_schema: schema }; }
  async function callAnthropicLike(url, headers, model, { system, user, schema, toolName, maxTokens }) {
    const body = { model, max_tokens: maxTokens, system, messages: [{ role: 'user', content: user }], tools: [toolBlock(schema, toolName)], tool_choice: { type: 'tool', name: toolName } };
    const res = await fetch(url, { method: 'POST', headers: Object.assign({ 'content-type': 'application/json', 'anthropic-version': '2023-06-01' }, headers), body: JSON.stringify(body) });
    if (!res.ok) throw new Error(`API ${res.status}: ${(await res.text()).slice(0, 300)}`);
    const data = await res.json(); const tu = (data.content || []).find(c => c.type === 'tool_use'); if (!tu) throw new Error('구조화 출력이 없다: ' + JSON.stringify(data.content || data).slice(0, 200));
    return tu.input;
  }
  async function callOpenAILike(base, key, model, { system, user, schema, toolName, maxTokens }) {
    const body = { model, max_tokens: maxTokens, messages: [{ role: 'system', content: system }, { role: 'user', content: user }], tools: [{ type: 'function', function: { name: toolName, description: '결과를 이 스키마로 돌려준다.', parameters: schema } }], tool_choice: { type: 'function', function: { name: toolName } } };
    const headers = { 'content-type': 'application/json' }; if (key) headers.authorization = 'Bearer ' + key;
    const res = await fetch(base.replace(/\/$/, '') + '/chat/completions', { method: 'POST', headers, body: JSON.stringify(body) });
    if (!res.ok) throw new Error(`API ${res.status}: ${(await res.text()).slice(0, 300)}`);
    const data = await res.json(); const msg = ((data.choices || [])[0] || {}).message || {}; const calls = msg.tool_calls || [];
    if (calls.length) return JSON.parse(calls[0].function.arguments); if (msg.content) return JSON.parse(msg.content); throw new Error('구조화 출력이 없다');
  }
  async function callHelper(kind, payload) {
    const base = ($('#h-url').value || 'http://127.0.0.1:8787').replace(/\/$/, '');
    const res = await fetch(base + '/' + kind, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify(payload) });
    const data = await res.json().catch(() => ({})); if (!res.ok) throw new Error(`도우미 ${res.status}: ${data.error || ''}`); return data;
  }
  // kind: 'extract' | 'judge'. payload는 도우미 규격({customer_id,text} / {customer_id,terms,event,text}); 직접 호출일 때는 같은 프롬프트로 바꿔 보낸다.
  async function callLLM(kind, payload, { system, user, schema, toolName, maxTokens = 6000 }) {
    const b = backend();
    if (b === 'helper') return callHelper(kind, payload);
    if (b === 'api') { const key = store.get('anthropic_key'); if (!key) throw new Error('API 키를 먼저 저장하세요.'); return callAnthropicLike('https://api.anthropic.com/v1/messages', { 'x-api-key': key, 'anthropic-dangerous-direct-browser-access': 'true' }, $('#k-model').value, { system, user, schema, toolName, maxTokens }); }
    const url = store.get('custom_url'), model = store.get('custom_model'), key = store.get('custom_key'); if (!url || !model) throw new Error('사내 엔드포인트의 기본 주소와 모델 이름을 적으세요.');
    if ($('#c-proto').value === 'anthropic') return callAnthropicLike(url.replace(/\/$/, '') + '/v1/messages', key ? { 'x-api-key': key, authorization: 'Bearer ' + key } : {}, model, { system, user, schema, toolName, maxTokens });
    return callOpenAILike(url, key, model, { system, user, schema, toolName, maxTokens });
  }
  const backendLabel = () => ({ api: 'Anthropic API(' + $('#k-model').value + ')', helper: '로컬 도우미', custom: '사내 엔드포인트(' + (store.get('custom_model') || '?') + ')' })[backend()];

  const verbatim = (quote, text) => { const head = (quote || '').split('…')[0].trim().slice(0, 20); return !!head && text.includes(head); };
  const nextId = () => { const ids = new Set(window.CT_APP.customers().map(c => c.id)); for (const ch of 'IJKLMNOPQRSTUVWXYZ') if (!ids.has(ch)) return ch; return 'Z'; };
  function mulberry(a) { return function () { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
  function makeShipments(id, name, count = 7) { let h = 7; for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) | 0; const rng = mulberry(h); const routes = Object.keys(CT.ROUTES); const out = [];
    for (let k = 0; k < count; k++) { const route = routes[Math.floor(rng() * routes.length)]; const ready = Math.round(rng() * 160) / 10; const slack = 1 + rng() * 11; const value = Math.floor((20 + rng() * 60)) * 1_000_000;
      out.push({ id: `${id}${String(k + 1).padStart(2, '0')}`, customer_id: id, value_krw: value, ready_h: ready, due_h: Math.round((ready + CT.ROUTES[route] + slack) * 10) / 10, route, travel_h: CT.ROUTES[route] }); }
    return out; }

  async function readFile(file) {
    if (file.name.toLowerCase().endsWith('.docx')) { if (!window.mammoth) throw new Error('docx 변환 라이브러리를 불러오지 못했다(네트워크). 본문을 붙여넣으세요.'); const r = await window.mammoth.extractRawText({ arrayBuffer: await file.arrayBuffer() }); return r.value; }
    return await file.text();
  }
  $('#u-file').addEventListener('change', async e => { const f = e.target.files[0]; if (!f) return; try { $('#u-text').value = await readFile(f); if (!$('#u-name').value) $('#u-name').value = f.name.replace(/\.[^.]+$/, ''); } catch (err) { $('#u-out').textContent = err.message; } });
  $('#u-sample').onclick = () => { $('#u-name').value = '새벽물산'; $('#u-text').value = `# 긴급 부품 운송 약정서 (새벽물산)\n\n## 제7조 (지연 배상)\n① 수행사가 배송 시한을 넘긴 경우 지연된 매 1시간마다 해당 주문 상품가액의 0.08%를 배상한다.\n② 배송 시한 경과 후 3시간 이내의 지연은 배상 대상에서 제외한다.\n③ 배상금 총액은 해당 주문 상품가액의 8%를 초과하지 아니한다.\n\n## 제12조 (불가항력)\n태풍, 지진, 홍수 등 천재지변 또는 파업으로 인한 지연에 대하여 수행사는 책임을 지지 아니한다. 수행사는 사유 발생 후 36시간 이내에 발주자에게 통지한다.`; };
  $('#e-sample').onclick = () => { $('#e-type').value = '화물연대 파업'; $('#e-desc').value = '화물연대 총파업으로 운송사 소속이 아닌 지입 차량 절반이 운행을 거부했다. 운송사는 대체 차량 수배를 시도한 기록이 있다. 정부 업무개시명령은 아직 없다.'; };

  $('#u-run').onclick = async () => {
    const name = $('#u-name').value.trim() || '추가 고객'; const text = $('#u-text').value.trim(); const out = $('#u-out');
    if (text.length < 80) { out.textContent = '계약서 본문이 너무 짧다.'; return; }
    const id = nextId(); out.textContent = `계약서를 읽는 중… (${backendLabel()}, 수십 초)`; $('#u-run').disabled = true;
    try {
      const t0 = Date.now(); const exi = await callLLM('extract', { customer_id: id, text }, { system: D.prompts.extract, user: `고객 ID: ${id}\n\n--- 계약서 전문 ---\n${text}`, schema: D.schemas.extract, toolName: 'submit_extraction' }); const ex = { input: exi };
      const terms = ex.input.terms; terms.customer_id = id; terms.citations = terms.citations || {}; terms.tiers = terms.tiers || []; terms.grace_hours = terms.grace_hours || 0;
      const bad = Object.entries(terms.citations).filter(([, c]) => !verbatim(c.quote, text)).map(([k]) => k); if (terms.force_majeure && !verbatim(terms.force_majeure.citation.quote, text)) bad.push('force_majeure');
      const app = window.CT_APP; const ev = app.currentEvent(); const sid = app.state.sid;
      out.textContent = `조건 추출 완료(${((Date.now() - t0) / 1000).toFixed(0)}초). 이제 현재 사건에 대한 면책을 판단하는 중…`;
      const judgeUser = app.judgeUserText(id, terms, ev, text);
      const j = await callLLM('judge', { customer_id: id, terms, event: ev, text }, { system: D.prompts.judge, user: judgeUser, schema: D.schemas.judge, toolName: 'submit_judgment' }); j.customer_id = id; j.conditions_met = j.conditions_met || {};
      app.addCustomer({ id, name, segment: '업로드', monthly_fee_krw: terms.base === 'monthly_fee' ? terms.base_amount_krw : null }, terms, { terms, confidence: ex.input.confidence, ambiguities: ex.input.ambiguities || [] }, j, makeShipments(id, name));
      out.innerHTML = `<b>${name}</b>(${id})을 추가했다. ${terms.basis} · 요율 ${terms.rate_pct ?? '-'}% · 유예 ${terms.grace_hours}h · ${terms.cap_pct != null ? '상한 ' + terms.cap_pct + '%' : terms.cap_amount_krw != null ? '상한 ' + terms.cap_amount_krw.toLocaleString() + '원' : '상한 없음'} · ${terms.force_majeure ? '면책 조항 있음' : '면책 조항 없음'}. 확신도 ${(ex.input.confidence * 100).toFixed(0)}%. ` +
        (bad.length ? `<span style="color:var(--crit)">인용 ${bad.join(', ')}이(가) 원문과 글자 그대로 일치하지 않는다. 카드에서 확인하라.</span>` : '인용은 모두 원문과 일치한다.') + ` 화물 7건을 만들어 시뮬레이션에 넣었다. 아래 표에서 ${id}로 시작하는 화물을 찾아보라.`;
    } catch (err) { out.textContent = '실패: ' + err.message + (String(err.message).includes('Failed to fetch') ? ' (브라우저가 직접 호출을 막았거나 네트워크 문제. 키와 네트워크를 확인하라.)' : ''); }
    finally { $('#u-run').disabled = false; }
  };
  $('#u-remove').onclick = () => { window.CT_APP.clearExtra(); $('#u-out').textContent = '추가한 고객을 모두 제거했다.'; };

  $('#e-run').onclick = async () => {
    const type = $('#e-type').value.trim(), desc = $('#e-desc').value.trim(); const out = $('#e-out'); if (!type || desc.length < 10) { out.textContent = '사건 유형과 설명을 적으세요.'; return; }
    const app = window.CT_APP; const ev = Object.assign({}, app.currentEvent(), { event_type: type, description: desc }); const custs = app.customers(); const terms = app.currentTerms();
    out.textContent = `계약 ${custs.length}건의 면책을 판단하는 중… (${backendLabel()}, 병렬 4개)`; $('#e-run').disabled = true;
    try {
      const results = {}; let i = 0; const queue = custs.slice();
      const worker = async () => { while (queue.length) { const c = queue.shift(); const j = await callLLM('judge', { customer_id: c.id, terms: terms[c.id], event: ev, text: app.contractText(c.id) }, { system: D.prompts.judge, user: app.judgeUserText(c.id, terms[c.id], ev, app.contractText(c.id)), schema: D.schemas.judge, toolName: 'submit_judgment' }); j.customer_id = c.id; j.conditions_met = j.conditions_met || {}; results[c.id] = j; out.textContent = `판단 ${++i}/${custs.length}…`; } };
      await Promise.all([worker(), worker(), worker(), worker()]);
      app.setLiveEvent(ev, results);
      const applied = custs.filter(c => results[c.id].applies).map(c => c.name); out.innerHTML = `사건 '<b>${type}</b>'에 대한 판단 완료. 면책 적용: ${applied.length ? applied.join(', ') : '없음'}. 위 '고객별 결과'와 '계약서 근거' 카드에 각 판단의 이유가 있다. 통지 시점 슬라이더를 움직이면 통지 요건만 다시 계산된다.`;
    } catch (err) { out.textContent = '실패: ' + err.message; } finally { $('#e-run').disabled = false; }
  };
  $('#e-reset').onclick = () => { window.CT_APP.clearLiveEvent(); $('#e-out').textContent = '원래 사건의 판단으로 되돌렸다.'; };
})();
