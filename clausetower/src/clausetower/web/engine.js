// ClauseTower 엔진(브라우저용). 파이썬 exposure.py / sim.py / agent.py의 이식이다.
// 같은 입력이면 파이썬과 같은 총 배상금이 나와야 한다. scripts/verify_engine.js가 그것을 확인한다.
(function (root, factory) {
  if (typeof module === 'object' && module.exports) module.exports = factory(); else root.CT = factory();
})(typeof self !== 'undefined' ? self : this, function () {
  const ROUTES = { N1: 2.0, N2: 3.0, S1: 4.0, S2: 5.0, S3: 6.0, P1: 3.5, P2: 4.5, E1: 2.5 };
  const H = 24.0;
  const round = x => { const f = Math.floor(x), d = x - f; if (Math.abs(d - 0.5) < 1e-9) return f % 2 === 0 ? f : f + 1; return Math.round(x); };
  const fmt = n => n.toLocaleString('ko-KR');

  // ---------- 비교 도우미(파이썬 튜플 비교와 같은 동작) ----------
  function cmp(a, b) { for (let i = 0; i < a.length; i++) { if (a[i] < b[i]) return -1; if (a[i] > b[i]) return 1; } return 0; }
  function minBy(arr, key) { let best = null, bk = null; for (const x of arr) { const k = key(x); if (best === null || cmp(k, bk) < 0) { best = x; bk = k; } } return best; }
  function maxBy(arr, key) { let best = null, bk = null; for (const x of arr) { const k = key(x); if (best === null || cmp(k, bk) > 0) { best = x; bk = k; } } return best; }
  function sortBy(arr, key) { return arr.map((x, i) => [key(x), i, x]).sort((p, q) => cmp(p[0], q[0]) || p[1] - q[1]).map(p => p[2]); }

  // ---------- 날짜 ----------
  function dueDate(t0iso, hours) { return new Date(Date.parse(t0iso.endsWith('Z') ? t0iso : t0iso + 'Z') + hours * 3600e3); }
  function businessDayUnits(dueAt, effective, roundsUp) {
    if (effective <= 0) return 0; let units = 0, cursor = dueAt.getTime(), remaining = effective;
    while (remaining > 0) { const step = Math.min(H, remaining); const d = new Date(cursor).getUTCDay(); if (d >= 1 && d <= 5) units += roundsUp ? 1 : step / H; cursor += H * 3600e3; remaining -= step; }
    return units;
  }

  // ---------- 계산기 ----------
  function baseAmount(terms, value) { if (terms.base === 'shipment_value') return value; if (terms.base_amount_krw == null) throw new Error(terms.customer_id + ': base_amount_krw 없음'); return terms.base_amount_krw; }

  function computePenalty(terms, { shipmentId, delayHours, shipmentValue, dueAt, judgment }) {
    const steps = [], cites = []; const base = baseAmount(terms, shipmentValue); delayHours = Math.max(0, delayHours);
    const done = (penalty, uncapped, units, effective, blocked, capped) => ({ customer_id: terms.customer_id, shipment_id: shipmentId, delay_hours: Math.round(delayHours * 100) / 100,
      effective_delay_hours: Math.round(effective * 100) / 100, units, penalty_krw: penalty, uncapped_krw: uncapped, capped: !!capped, blocked_by: blocked || null, steps, citations: cites });
    if (delayHours <= 0) { steps.push('지연 없음. 배상금 0원.'); return done(0, 0, 0, 0, null); }
    if (judgment && judgment.has_clause) {
      if (judgment.applies) { steps.push('불가항력 조항 적용: ' + judgment.reasoning); if (judgment.citation) cites.push(judgment.citation); return done(0, 0, 0, 0, '불가항력 면책'); }
      steps.push('불가항력 조항 있으나 미적용: ' + judgment.reasoning); if (judgment.citation) cites.push(judgment.citation);
    } else if (!terms.force_majeure) steps.push('불가항력 조항 없음. 사유를 불문하고 지연 배상금이 발생한다.');
    let effective = delayHours - terms.grace_hours;
    if (terms.grace_hours > 0) { if (terms.citations.grace) cites.push(terms.citations.grace);
      if (effective <= 0) { steps.push(`지연 ${delayHours.toFixed(1)}시간은 유예 ${terms.grace_hours}시간 이내. 배상금 0원.`); return done(0, 0, 0, 0, '유예기간 내'); }
      steps.push(`지연 ${delayHours.toFixed(1)}시간 중 유예 ${terms.grace_hours}시간을 뺀 ${effective.toFixed(1)}시간이 과금 대상.`);
    } else steps.push(`유예 없음. 지연 ${delayHours.toFixed(1)}시간 전체가 과금 대상.`);
    if (terms.citations.rate) cites.push(terms.citations.rate);
    let units = 0, amount = 0; const ru = terms.partial_unit_rounds_up !== false;
    if (terms.basis === 'per_hour') { units = ru ? Math.ceil(effective) : effective; amount = base * (terms.rate_pct || 0) / 100 * units; steps.push(`시간당 ${terms.rate_pct}% × ${units}시간 × 기준금액 ${fmt(base)}원 = ${fmt(round(amount))}원`); }
    else if (terms.basis === 'per_calendar_day') { units = ru ? Math.ceil(effective / H) : effective / H; amount = base * (terms.rate_pct || 0) / 100 * units; steps.push(`일당 ${terms.rate_pct}% × ${units}일(역일) × 기준금액 ${fmt(base)}원 = ${fmt(round(amount))}원`); }
    else if (terms.basis === 'per_business_day') { units = businessDayUnits(new Date(dueAt.getTime() + terms.grace_hours * 3600e3), effective, ru); amount = base * (terms.rate_pct || 0) / 100 * units; steps.push(`일당 ${terms.rate_pct}% × ${units}일(영업일, 주말 제외) × 기준금액 ${fmt(base)}원 = ${fmt(round(amount))}원`); }
    else if (terms.basis === 'tiered_per_day') { const days = Math.ceil(effective / H); units = days; const parts = [];
      for (const tier of terms.tiers) { const lo = tier.from_day, hi = tier.to_day != null ? tier.to_day : days; const n = Math.max(0, Math.min(days, hi) - lo + 1); if (n) { const piece = base * tier.rate_pct / 100 * n; amount += piece; parts.push(`${lo}~${hi}일차 ${tier.rate_pct}%×${n}일=${fmt(round(piece))}원`); } }
      steps.push(`계단식 ${days}일: ${parts.join(', ')} → 합계 ${fmt(round(amount))}원`); }
    else if (terms.basis === 'flat_per_shipment') { units = 1; amount = terms.flat_amount_krw || 0; let label = `지연 건당 정액 ${fmt(amount)}원`;
      if (terms.flat_escalation && delayHours > terms.flat_escalation.after_hours) { amount = terms.flat_escalation.amount_krw; label = `지연 ${delayHours.toFixed(1)}시간 > ${terms.flat_escalation.after_hours}시간, 가중 정액 ${fmt(amount)}원`; } steps.push(label); }
    else throw new Error('알 수 없는 basis ' + terms.basis);
    const uncapped = round(amount); let penalty = uncapped, capped = false;
    if ((terms.cap_scope || 'shipment') === 'shipment') { let cap = null; if (terms.cap_pct != null) cap = base * terms.cap_pct / 100; if (terms.cap_amount_krw != null) cap = cap != null ? Math.min(cap, terms.cap_amount_krw) : terms.cap_amount_krw;
      if (cap != null) { if (terms.citations.cap) cites.push(terms.citations.cap); if (penalty > cap) { steps.push(`상한 ${fmt(round(cap))}원에 걸려 ${fmt(penalty)}원 → ${fmt(round(cap))}원`); penalty = round(cap); capped = true; } else steps.push(`상한 ${fmt(round(cap))}원 이내.`); } else steps.push('상한 없음.'); }
    return done(penalty, uncapped, units, effective, null, capped);
  }

  function applyCustomerPeriodCap(terms, breakdowns) {
    if (terms.cap_scope !== 'customer_period') return breakdowns; let cap = null;
    if (terms.cap_amount_krw != null) cap = terms.cap_amount_krw; if (terms.cap_pct != null && terms.base_amount_krw != null) { const c = terms.base_amount_krw * terms.cap_pct / 100; cap = cap != null ? Math.min(cap, c) : c; }
    if (cap == null) return breakdowns; let running = 0; const out = [];
    for (let b of breakdowns) { const allowed = Math.max(0, round(cap) - running);
      if (b.penalty_krw > allowed) b = Object.assign({}, b, { penalty_krw: allowed, capped: true, steps: b.steps.concat([`고객 합계 상한 ${fmt(round(cap))}원: 누적 ${fmt(running)}원 → 이 건은 ${fmt(allowed)}원만 과금`]), citations: b.citations.concat(terms.citations.cap ? [terms.citations.cap] : []) });
      running += b.penalty_krw; out.push(b); }
    return out;
  }

  // ---------- 시뮬레이터 ----------
  function travelTime(scenario, route, t) { const d = scenario.disruption; const base = ROUTES[route]; if (d.route_multipliers && d.route_multipliers[route] != null && d.route_multiplier_from_h <= t && t < d.route_multiplier_until_h) return base * d.route_multipliers[route]; return base; }
  function makeCtx(scenario, terms, judgments, customers) {
    const cmap = {}; customers.forEach(c => cmap[c.id] = c);
    return { scenario, terms, judgments, customers: cmap, penalty(s, deliveredH) { return computePenalty(terms[s.customer_id], { shipmentId: s.id, delayHours: deliveredH - s.due_h, shipmentValue: s.value_krw, dueAt: dueDate(scenario.t0, s.due_h), judgment: judgments[s.customer_id] }); } };
  }
  function marginalExposure(state, ctx, s, deferH) { const defer = deferH == null ? state.avg_cycle_h : deferH; const nowEta = state.t + travelTime(ctx.scenario, s.route, state.t); const laterEta = state.t + defer + travelTime(ctx.scenario, s.route, state.t + defer); const bNow = ctx.penalty(s, nowEta), bLater = ctx.penalty(s, laterEta); return [bNow.penalty_krw, bLater.penalty_krw, bLater]; }
  function exposureKey(state, ctx, s, perHour) { const [n, l] = marginalExposure(state, ctx, s); const marginal = l - n; const occ = 2 * travelTime(ctx.scenario, s.route, state.t); const score = perHour ? marginal / occ : marginal; return [-score, -l, s.due_h, s.id]; }
  const POLICY_FN = {
    deadline_first: (st) => minBy(st.waiting, s => [s.due_h, s.id]),
    fifo: (st) => minBy(st.waiting, s => [s.ready_h, s.id]),
    value_first: (st) => maxBy(st.waiting, s => [s.value_krw, -s.due_h]),
    exposure_first: (st, ctx) => { const c = minBy(st.waiting, s => exposureKey(st, ctx, s, true)); const [n, l, b] = marginalExposure(st, ctx, c); st.decisions[c.id] = `미루면 +${fmt(l - n)}원` + (b.blocked_by ? ` (${b.blocked_by})` : ''); return c; },
    exposure_abs: (st, ctx) => minBy(st.waiting, s => exposureKey(st, ctx, s, false)),
  };
  const POLICY_LABEL = { deadline_first: '마감 임박 순(기존)', fifo: '도착 순', value_first: '고액 화물 순', exposure_first: '배상 노출 순(ClauseTower)', exposure_abs: '배상 노출 순(절대값 변형)' };
  const avgRoute = Object.values(ROUTES).reduce((a, b) => a + b, 0) / Object.keys(ROUTES).length;

  function runPolicy(scenario, shipments, ctx, policyId, order) {
    const d = scenario.disruption, n = scenario.trucks; const truckFree = new Array(n).fill(0);
    for (let i = 0; i < Math.min(d.trucks_out || 0, n); i++) if (d.trucks_out_from_h <= 0) truckFree[i] = Math.max(truckFree[i], d.trucks_out_until_h);
    const pending = shipments.slice(); const records = []; const breakdowns = {}; const rank = order ? Object.fromEntries(order.map((id, i) => [id, i])) : null; let peak = [0, []];
    const avgCycle = 2 * avgRoute / Math.max(1, n - (d.trucks_out || 0)); let t = 0; const policy = POLICY_FN[policyId] || POLICY_FN.deadline_first;
    while (pending.length) {
      let i = 0; for (let k = 1; k < n; k++) if (truckFree[k] < truckFree[i]) i = k;
      t = Math.max(t, truckFree[i]);
      if (d.trucks_out && d.trucks_out_from_h > 0 && i < d.trucks_out && d.trucks_out_from_h <= t && t < d.trucks_out_until_h) { truckFree[i] = d.trucks_out_until_h; continue; }
      const waiting = pending.filter(s => s.ready_h <= t);
      if (!waiting.length) { t = Math.min(...pending.map(s => s.ready_h)); truckFree[i] = Math.max(truckFree[i], t); continue; }
      const freeCount = truckFree.filter(x => x <= t).length; const state = { t, free_trucks: freeCount, waiting, avg_cycle_h: avgCycle, decisions: {} };
      if (waiting.length > peak[1].length) peak = [t, waiting.map(w => w.id)];
      const chosen = rank ? minBy(waiting, s => [rank[s.id]]) : policy(state, ctx);
      const tt = travelTime(scenario, chosen.route, t); const delivered = t + tt; truckFree[i] = t + 2 * tt;
      const b = ctx.penalty(chosen, delivered); (breakdowns[chosen.customer_id] = breakdowns[chosen.customer_id] || []).push(b);
      records.push({ shipment_id: chosen.id, customer_id: chosen.customer_id, truck: i, dispatched_h: Math.round(t * 100) / 100, delivered_h: Math.round(delivered * 100) / 100, due_h: chosen.due_h, delay_h: Math.round(Math.max(0, delivered - chosen.due_h) * 100) / 100, penalty_krw: b.penalty_krw, blocked_by: b.blocked_by, rank_reason: state.decisions[chosen.id] || null });
      pending.splice(pending.indexOf(chosen), 1);
    }
    const perCustomer = {}, finalPenalty = {}; const deliveredOf = id => records.find(r => r.shipment_id === id).delivered_h;
    for (const cid of Object.keys(breakdowns)) { const bs = sortBy(breakdowns[cid], b => [deliveredOf(b.shipment_id)]); for (const b of applyCustomerPeriodCap(ctx.terms[cid], bs)) finalPenalty[b.shipment_id] = b.penalty_krw; perCustomer[cid] = breakdowns[cid].reduce((a, b) => a + finalPenalty[b.shipment_id], 0); }
    const recs = records.map(r => Object.assign({}, r, { penalty_krw: finalPenalty[r.shipment_id] })); const curve = []; let acc = 0;
    for (const r of sortBy(recs, r => [r.delivered_h])) { acc += r.penalty_krw; curve.push([r.delivered_h, acc]); }
    return { policy: policyId, label: POLICY_LABEL[policyId] || policyId, total_penalty_krw: Object.values(perCustomer).reduce((a, b) => a + b, 0), late_count: recs.filter(r => r.delay_h > 0).length, on_time_count: recs.filter(r => r.delay_h <= 0).length, records: recs, per_customer_krw: perCustomer, penalty_curve: curve, peak_queue_h: peak[0], peak_queue_ids: peak[1] };
  }

  function mulberry32(a) { return function () { a |= 0; a = a + 0x6D2B79F5 | 0; let t = Math.imul(a ^ a >>> 15, 1 | a); t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
  function searchBestOrder(scenario, shipments, ctx, { restarts = 6, sweeps = 2, seed = 0, start = null } = {}) {
    const rng = mulberry32(seed + 1); const ids = shipments.map(s => s.id); const evaluate = order => runPolicy(scenario, shipments, ctx, 'deadline_first', order).total_penalty_krw;
    let bestOrder = start ? start.slice() : ids.slice().sort(); let best = evaluate(bestOrder);
    for (let r = 0; r < restarts; r++) { const order = r === 0 ? bestOrder.slice() : ids.slice().sort(() => rng() - 0.5); let cur = evaluate(order);
      for (let s = 0; s < sweeps; s++) { let improved = false; for (let i = 0; i < order.length - 1; i++) { for (const j of [i + 1, Math.floor(rng() * order.length)]) { if (j === i) continue; [order[i], order[j]] = [order[j], order[i]]; const v = evaluate(order); if (v < cur) { cur = v; improved = true; } else [order[i], order[j]] = [order[j], order[i]]; } } if (!improved) break; }
      if (cur < best) { best = cur; bestOrder = order.slice(); } }
    const res = runPolicy(scenario, shipments, ctx, 'deadline_first', bestOrder); res.policy = 'search_best'; res.label = '탐색 근사 최적(참고)'; return res;
  }

  // ---------- 순위표와 보고서 ----------
  function rankingAt(ctx, shipments, scenario, customers, t, ids) {
    const set = new Set(ids); const waiting = shipments.filter(s => set.has(s.id)); const d = scenario.disruption;
    const n = scenario.trucks - ((d.trucks_out_from_h <= t && t < d.trucks_out_until_h) ? (d.trucks_out || 0) : 0); const avgCycle = 2 * avgRoute / Math.max(1, n);
    const state = { t, free_trucks: n, waiting, avg_cycle_h: avgCycle, decisions: {} };
    const rows = waiting.map(s => { const [n0, l, b] = marginalExposure(state, ctx, s); const occ = 2 * travelTime(scenario, s.route, t); return { s, n: n0, l, b, score: (l - n0) / occ }; });
    const byDeadline = sortBy(rows, r => [r.s.due_h, r.s.id]), byExposure = sortBy(rows, r => [-r.score, -r.l, r.s.due_h, r.s.id]);
    const dRank = {}, eRank = {}; byDeadline.forEach((r, i) => dRank[r.s.id] = i + 1); byExposure.forEach((r, i) => eRank[r.s.id] = i + 1);
    return byExposure.map(({ s, n: n0, l, b }) => { let why; if (b.blocked_by) why = `${b.blocked_by}. 보류해도 배상금이 늘지 않는다.`; else if (l - n0 === 0 && l === 0) why = '한 사이클 보류해도 마감 또는 유예 범위 안이다.'; else why = b.steps.filter(st => st.includes('=') || st.includes('상한') || st.includes('정액')).join(' ').slice(0, 160);
      return { shipment_id: s.id, customer_id: s.customer_id, customer_name: customers[s.customer_id].name, due_in_h: Math.round((s.due_h - t) * 10) / 10, deadline_rank: dRank[s.id], exposure_rank: eRank[s.id], penalty_if_now_krw: n0, penalty_if_deferred_krw: l, marginal_krw: l - n0, blocked_by: b.blocked_by, why, citations: b.citations.slice(0, 2) }; });
  }

  // 불가항력 최종 판단을 조건 결합으로 다시 만든다. LLM의 사유·포섭 판단은 두고 통지 시점과 사실만 현재 설정으로 바꾼다.
  function deriveJudgment(base, terms, event, override) {
    const j = Object.assign({}, base, { conditions_met: Object.assign({}, base.conditions_met || {}) }); const fm = terms.force_majeure;
    if (j.has_clause && fm) { j.notice_ok = fm.notice_hours == null ? true : (event.notice_sent_after_hours != null && event.notice_sent_after_hours <= fm.notice_hours);
      for (const c of fm.conditions || []) if (event.facts && c in event.facts) j.conditions_met[c] = !!event.facts[c]; }
    const derived = !!(j.has_clause && j.event_covered && j.notice_ok && Object.values(j.conditions_met).every(Boolean));
    j.applies = override == null ? derived : !!override; j.derived_applies = derived; j.manual_override = override != null; return j;
  }

  function buildReport({ scenario, customers, terms, extraction, judgments, shipments, llm_mode, withSearch = false, searchOpts = {} }) {
    const cmap = {}; customers.forEach(c => cmap[c.id] = c); const ctx = makeCtx(scenario, terms, judgments, customers); const policies = {};
    for (const pid of Object.keys(POLICY_FN)) policies[pid] = runPolicy(scenario, shipments, ctx, pid);
    if (withSearch) policies.search_best = searchBestOrder(scenario, shipments, ctx, Object.assign({ start: policies.exposure_first.records.map(r => r.shipment_id) }, searchOpts));
    const baseRun = policies.deadline_first; const ranking = rankingAt(ctx, shipments, scenario, cmap, baseRun.peak_queue_h, baseRun.peak_queue_ids);
    const base = baseRun.total_penalty_krw, ours = policies.exposure_first.total_penalty_krw; const savings = base - ours; const pct = base ? Math.round(savings / base * 1000) / 10 : 0;
    const applied = Object.entries(judgments).filter(([, j]) => j.applies).map(([k]) => k); const blocked = Object.entries(judgments).filter(([, j]) => j.has_clause && !j.applies).map(([k, j]) => `${k}(${!j.notice_ok ? '통지 지연' : !j.event_covered ? '사유 불해당' : '조건 미충족'})`);
    const flips = ranking.filter(r => Math.abs(r.deadline_rank - r.exposure_rank) >= 3).length;
    const log = [`시나리오 '${scenario.title}'. 고객 ${customers.length}곳, 트럭 ${scenario.trucks}대, 화물 ${shipments.length}건. 계약 읽기 출처: ${llm_mode}.`,
      `불가항력 판단(현재 설정 기준): 면책 적용 ${applied.length ? applied.join(', ') : '없음'}, 조항은 있으나 미적용 ${blocked.length ? blocked.join(', ') : '없음'}.`,
      `대기열 최대 시점(+${baseRun.peak_queue_h.toFixed(1)}h) 노출액 산출: 대기 ${ranking.length}건, 순위가 3계단 이상 갈린 화물 ${flips}건.`,
      '시뮬레이션 비교(총 배상금): ' + Object.values(policies).map(p => `${p.label} ${fmt(p.total_penalty_krw)}원`).join(', '), `기존 대비 절감 ${fmt(savings)}원(${pct}%). 브라우저 안에서 계산했다.`];
    return { scenario, customers, terms, extraction, judgments, ranking, ranking_at_h: baseRun.peak_queue_h, policies, savings_vs_deadline_krw: savings, savings_vs_deadline_pct: pct, llm_mode, llm_calls: 0, generated_at: new Date().toISOString(), agent_log: log };
  }

  return { ROUTES, computePenalty, applyCustomerPeriodCap, travelTime, makeCtx, runPolicy, searchBestOrder, rankingAt, deriveJudgment, buildReport, POLICY_LABEL, dueDate };
});
