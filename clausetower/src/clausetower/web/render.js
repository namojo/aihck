// 공용 렌더 코드. dashboard.py(오프라인 HTML)와 site/app.js(웹 데모)가 함께 쓴다.
const fmt = n => (n ?? 0).toLocaleString('ko-KR') + '원';
const man = n => (n / 10000).toLocaleString('ko-KR', { maximumFractionDigits: 0 }) + '만';
const CUST = ['--c1', '--c2', '--c3', '--c4', '--c5', '--c6', '--c7', '--c8'];
let COLOR_IDX = {}; const ccolor = id => `var(${CUST[(COLOR_IDX[id] || 0) % 8]})`;
const $ = s => document.querySelector(s);
const tip = $('#tip');
function showTip(e, html) { tip.innerHTML = html; tip.style.display = 'block'; const x = Math.min(e.clientX + 14, window.innerWidth - 340); tip.style.left = x + 'px'; tip.style.top = (e.clientY + 14) + 'px'; }
function hideTip() { tip.style.display = 'none'; }
function esc(s) { return String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c])); }
const BASIS = { per_hour: '시간당', per_calendar_day: '일당(역일)', per_business_day: '일당(영업일)', tiered_per_day: '누진(일)', flat_per_shipment: '건당 정액' };
const BASE = { shipment_value: '건별 화물가액', monthly_fee: '월 서비스료', contract_value: '계약금액' };
let BOARD_MODE = 'cards'; let LAST_R = null; let CONTRACT_TEXTS = (window.CT_DATA && window.CT_DATA.contracts) || {};

function renderReport(R) {
  LAST_R = R; COLOR_IDX = {}; R.customers.forEach((c, i) => COLOR_IDX[c.id] = i);
  renderSummary(R); renderBoard(R); renderRanking(R); renderCurve(R); renderPolicyBars(R);
  renderGantt(R, 'g-base', R.policies.deadline_first); renderGantt(R, 'g-ours', R.policies.exposure_first); renderLog(R);
  const f = $('#foot'); if (f) f.textContent = `생성 ${String(R.generated_at).replace('T', ' ').slice(0, 16)} · 계약 읽기 ${R.llm_mode} · 트럭 ${R.scenario.trucks}대 · 화물 ${R.policies.deadline_first.records.length}건`;
}

// ---------- 상황 요약 + KPI ----------
function renderSummary(R) {
  const base = R.policies.deadline_first, ours = R.policies.exposure_first, best = R.policies.search_best; const ev = R.scenario.event;
  $('#sc-title').textContent = R.scenario.title; $('#sc-desc').textContent = R.scenario.description;
  const facts = Object.entries(ev.facts || {}).map(([k, v]) => `<span class="chip ${v ? 'fm' : 'none'}">${esc(k)}: ${v ? '충족' : '미충족'}</span>`).join('');
  $('#sc-event').innerHTML = `<span class="chip tower">사건 · ${esc(ev.event_type)}</span><span class="chip">고객 통지 · ${ev.notice_sent_after_hours == null ? '안 함' : '발생 ' + ev.notice_sent_after_hours + '시간 뒤'}</span>${facts}`;
  const maxP = Math.max(base.total_penalty_krw, ours.total_penalty_krw, 1);
  $('#kpis').innerHTML = `
    <div class="kpi base"><div class="l"><span>${esc(base.label)}</span><span>지연 ${base.late_count}/${base.records.length}건</span></div><div class="v">${fmt(base.total_penalty_krw)}</div><div class="d">마감이 급한 화물부터 보낸 결과</div><div class="bar"><i style="width:${base.total_penalty_krw / maxP * 100}%"></i></div></div>
    <div class="kpi ours"><div class="l"><span>${esc(ours.label)}</span><span>지연 ${ours.late_count}/${ours.records.length}건</span></div><div class="v">${fmt(ours.total_penalty_krw)}</div><div class="d">물리는 돈이 큰 화물부터 보낸 결과</div><div class="bar"><i style="width:${ours.total_penalty_krw / maxP * 100}%"></i></div></div>
    <div class="kpi save"><div class="l"><span>절감</span><span>기존 대비</span></div><div class="v">−${R.savings_vs_deadline_pct}%</div><div class="d">${fmt(R.savings_vs_deadline_krw)} 덜 물린다</div></div>
    ${best ? `<div class="kpi"><div class="l"><span>탐색 근사 최적</span><span>참고</span></div><div class="v">${fmt(best.total_penalty_krw)}</div><div class="d">우선순위 지역 탐색이 찾은 상한선. ClauseTower는 그 ${best.total_penalty_krw ? Math.round(best.total_penalty_krw / Math.max(1, ours.total_penalty_krw) * 100) : 100}% 수준</div></div>` : ''}`;
  const hot = R.customers.map(c => ({ c, d: (base.per_customer_krw[c.id] || 0) - (ours.per_customer_krw[c.id] || 0), b: base.per_customer_krw[c.id] || 0 })).filter(x => x.b > 0).sort((a, b) => b.b - a.b).slice(0, 3);
  $('#hot').innerHTML = hot.length ? `<span>기존 방식에서 가장 많이 물리는 고객</span>` + hot.map(x => `<span class="chip"><i class="dot" style="background:${ccolor(x.c.id)}"></i>${esc(x.c.name)} ${fmt(x.b)}${x.d > 0 ? ` <b style="color:var(--good)">−${fmt(x.d)}</b>` : ''}</span>`).join('') : '<span>이 설정에서는 어느 고객도 물리지 않는다.</span>';
}

// ---------- 계약 케이스 보드 ----------
function termsSummary(t) {
  const rate = t.basis === 'flat_per_shipment' ? `${man(t.flat_amount_krw || 0)}원/건${t.flat_escalation ? ` → ${t.flat_escalation.after_hours}h 초과 ${man(t.flat_escalation.amount_krw)}원` : ''}`
    : t.basis === 'tiered_per_day' ? t.tiers.map(z => `${z.from_day}~${z.to_day ?? ''}일 ${z.rate_pct}%`).join(' · ') : `${t.rate_pct}% / ${t.basis === 'per_hour' ? '시간' : '일'}`;
  const cap = t.cap_pct != null ? { label: `${t.cap_pct}%`, pct: t.cap_pct, scope: t.cap_scope } : t.cap_amount_krw != null ? { label: `${man(t.cap_amount_krw)}원`, pct: null, scope: t.cap_scope } : null;
  return { rate, cap };
}
function verdictOf(j) { if (!j || !j.has_clause) return { cls: 'none', ic: '–', t: '면책 조항 없음' }; if (j.applies) return { cls: 'ok', ic: '✓', t: j.manual_override ? '면책 적용 (사람 결정)' : '면책 적용' }; return { cls: 'no', ic: '!', t: '면책 미적용 · ' + (!j.event_covered ? '사유 불해당' : !j.notice_ok ? '통지 지연' : '조건 미충족') + (j.manual_override ? ' (사람 결정)' : '') }; }

function renderBoard(R) {
  const el = $('#board'); const tg = $('#board-toggle'); if (tg && !tg.dataset.bound) { tg.dataset.bound = '1'; tg.querySelectorAll('button').forEach(b => b.addEventListener('click', () => { BOARD_MODE = b.dataset.mode; renderBoard(LAST_R); })); }
  if (tg) tg.querySelectorAll('button').forEach(b => b.classList.toggle('on', b.dataset.mode === BOARD_MODE));
  const base = R.policies.deadline_first, ours = R.policies.exposure_first;
  if (BOARD_MODE === 'matrix') {
    el.className = 'matrix'; el.innerHTML = `<table><colgroup><col style="width:11%"><col style="width:14%"><col style="width:6%"><col style="width:8%"><col style="width:16%"><col style="width:11%"><col style="width:13%"><col style="width:10.5%"><col style="width:10.5%"></colgroup>
      <thead><tr><th>고객</th><th>과금 방식 · 요율</th><th class="n">유예</th><th>상한</th><th>불가항력 사유</th><th>통지 시한 · 조건</th><th>이번 사건</th><th class="n">기존</th><th class="n">ClauseTower</th></tr></thead><tbody>` +
      R.customers.map(c => { const t = R.terms[c.id], j = R.judgments[c.id], s = termsSummary(t), v = verdictOf(j); const fm = t.force_majeure;
        const notice = fm ? (fm.notice_hours != null ? `${fm.notice_hours}h 이내` : '시한 없음') : '–';
        const cond = fm && fm.conditions.length ? `<div><span class="chip warn" title="${esc(fm.conditions.join('\n'))}">조건 ${fm.conditions.length}</span></div>` : '';
        return `<tr><td><i class="dot" style="display:inline-block;width:9px;height:9px;border-radius:50%;background:${ccolor(c.id)};margin-right:6px"></i><b>${esc(c.name)}</b></td>
          <td><div>${BASIS[t.basis] || t.basis}</div><div style="color:var(--ink-2)">${esc(s.rate)}${t.base !== 'shipment_value' ? ` <small>(${BASE[t.base]})</small>` : ''}</div></td>
          <td class="n">${t.grace_hours}h</td><td>${s.cap ? s.cap.label + (s.cap.scope === 'customer_period' ? '<div><small>고객 합계</small></div>' : '') : '<b style="color:var(--hot)">없음</b>'}</td>
          <td>${fm ? esc(fm.covered_events.join(' · ')) : '<span class="chip none">없음</span>'}</td><td>${notice}${cond}</td>
          <td><span class="vd ${v.cls}">${v.cls === 'ok' ? '✓' : v.cls === 'no' ? '!' : '–'} ${v.t.replace(' (사람 결정)', '<br><small>(사람 결정)</small>')}</span></td>
          <td class="n num">${fmt(base.per_customer_krw[c.id] || 0)}</td><td class="n num"><b>${fmt(ours.per_customer_krw[c.id] || 0)}</b></td></tr>`; }).join('') + '</tbody></table>';
    return;
  }
  el.className = 'board';
  el.innerHTML = R.customers.map(c => {
    const t = R.terms[c.id], j = R.judgments[c.id], x = R.extraction[c.id] || {}, s = termsSummary(t), v = verdictOf(j); const fm = t.force_majeure;
    const capCell = s.cap ? `<div class="v">${s.cap.label}</div><div class="s">${s.cap.scope === 'customer_period' ? '고객 합계 기준' : '건별'}</div>${s.cap.pct != null ? `<div class="capbar"><i style="width:${Math.min(100, s.cap.pct * 5)}%"></i></div>` : ''}` : `<div class="v" style="color:var(--hot)">없음</div><div class="s">시간이 갈수록 계속 물린다</div>`;
    const fmCell = fm ? `<div class="chips" style="margin-top:4px">${fm.covered_events.map(e => `<span class="chip">${esc(e)}</span>`).join('')}</div><div class="s" style="margin-top:6px">통지 ${fm.notice_hours != null ? `<b>${fm.notice_hours}시간 이내</b>` : '시한 없음'}${fm.conditions.length ? ` · 조건 ${fm.conditions.map(z => `<span class="chip warn">${esc(z)}</span>`).join(' ')}` : ''}</div>` : `<div class="v" style="color:var(--ink-3)">조항 없음</div><div class="s">사유를 불문하고 물린다</div>`;
    const reason = j ? esc(j.reasoning) : '';
    return `<article class="ccard" data-cid="${c.id}">
      <div class="top"><i class="dot" style="width:11px;height:11px;border-radius:50%;background:${ccolor(c.id)}"></i><span class="nm">${esc(c.name)}</span><span class="seg2">${esc(c.segment)}</span><span class="sp"></span>${x.confidence != null ? `<span class="chip ${x.confidence >= .85 ? 'tower' : 'warn'}" title="추출 확신도">읽기 ${Math.round(x.confidence * 100)}%</span>` : ''}</div>
      <div class="facts">
        <div class="fact"><div class="k">과금 방식</div><div class="v">${BASIS[t.basis] || t.basis}</div><div class="s">${esc(s.rate)}</div></div>
        <div class="fact"><div class="k">유예</div><div class="v">${t.grace_hours ? t.grace_hours + '시간' : '없음'}</div><div class="s">${t.grace_hours ? '이 안의 지연은 0원' : '지연 즉시 과금'}</div></div>
        <div class="fact"><div class="k">상한</div>${capCell}</div>
        <div class="fact"><div class="k">기준금액</div><div class="v">${BASE[t.base]}</div><div class="s">${t.base_amount_krw ? man(t.base_amount_krw) + '원' : '건마다 다름'}</div></div>
        <div class="fact wide"><div class="k">불가항력(면책)</div>${fmCell}</div>
      </div>
      <div class="verdict ${v.cls}"><span class="ic">${v.ic}</span><div><span class="t">이번 사건: ${v.t}</span>${reason ? `<span class="more lnk" data-more="${c.id}">이유</span><div class="rs" id="rs-${c.id}" style="display:none;margin-top:4px;color:var(--ink-2)">${reason}</div>` : ''}</div></div>
      <div class="foot"><span class="pen">페널티 <b>${fmt(base.per_customer_krw[c.id] || 0)}</b><span class="arr">→</span><b style="color:var(--tower)">${fmt(ours.per_customer_krw[c.id] || 0)}</b></span><button class="lnk" data-open="${c.id}">원문 ${Object.keys(t.citations || {}).length + (fm ? 1 : 0)}곳 보기 →</button></div>
    </article>`; }).join('');
  el.querySelectorAll('[data-more]').forEach(b => b.addEventListener('click', () => { const d = document.getElementById('rs-' + b.dataset.more); d.style.display = d.style.display === 'none' ? '' : 'none'; }));
  el.querySelectorAll('[data-open]').forEach(b => b.addEventListener('click', () => openContract(R, b.dataset.open)));
}

// ---------- 계약서 원문 서랍 ----------
function openContract(R, cid) {
  const c = R.customers.find(x => x.id === cid); const t = R.terms[cid]; const j = R.judgments[cid]; let text = CONTRACT_TEXTS[cid] || (window.CT_APP && window.CT_APP.contractText && window.CT_APP.contractText(cid)) || '';
  const quotes = Object.values(t.citations || {}).map(q => q.quote).concat(t.force_majeure ? [t.force_majeure.citation.quote] : []).concat(j && j.citation ? [j.citation.quote] : []);
  const heads = [...new Set(quotes.flatMap(q => q.split('…').map(p => p.trim()).filter(p => p.length >= 8)))];
  let html = esc(text); for (const h of heads) { const eh = esc(h); if (html.includes(eh)) html = html.split(eh).join(`<mark>${eh}</mark>`); }
  html = html.split('\n').map(l => l.startsWith('## ') ? `<h4>${l.slice(3)}</h4>` : l.startsWith('# ') ? `<h3>${l.slice(2)}</h3>` : l.trim() ? `<p style="margin:4px 0">${l}</p>` : '').join('');
  $('#drawer-title').textContent = `${c.name} 계약서 원문`; $('#drawer-sub').textContent = `노란 표시는 추출과 판단에 인용된 문장 ${heads.length}곳`;
  $('#drawer-body').innerHTML = html || '<p>원문이 없다.</p>'; $('#drawer').classList.add('open'); $('#scrim').classList.add('on');
}
function closeDrawer() { $('#drawer').classList.remove('open'); $('#scrim').classList.remove('on'); }
document.addEventListener('DOMContentLoaded', () => { const s = $('#scrim'); if (s) s.addEventListener('click', closeDrawer); const b = $('#drawer-close'); if (b) b.addEventListener('click', closeDrawer); });
document.addEventListener('keydown', e => { if (e.key === 'Escape') closeDrawer(); });

// ---------- 물리는 순서 ----------
function renderRanking(R) {
  $('#rank-at').textContent = `+${R.ranking_at_h.toFixed(1)}h`;
  const maxM = Math.max(1, ...R.ranking.map(r => r.marginal_krw));
  const rowsArr = R.ranking.map(r => {
    const diff = r.deadline_rank - r.exposure_rank;
    const delta = diff > 0 ? `<span class="delta up">▲${diff}</span>` : diff < 0 ? `<span class="delta down">▼${-diff}</span>` : '<span class="delta flat">–</span>';
    const chip = r.blocked_by === '불가항력 면책' ? '<span class="chip fm">면책</span>' : r.blocked_by === '유예기간 내' ? '<span class="chip grace">유예</span>' : (r.marginal_krw > 0 ? '<span class="chip hot">물림</span>' : '<span class="chip none">여유</span>');
    const cites = r.citations.map(c => `<blockquote><b>${esc(c.clause)}</b> ${esc(c.quote)}</blockquote>`).join('');
    return `<tr class="${Math.abs(diff) >= 3 ? 'flip' : ''}"><td class="n"><span class="rk ${r.exposure_rank <= 3 ? 'top' : ''}">${r.exposure_rank}</span></td><td class="n">${r.deadline_rank} ${delta}</td><td class="nw"><span class="mono"><b>${r.shipment_id}</b></span></td><td class="nw"><i class="dot" style="display:inline-block;width:9px;height:9px;border-radius:50%;background:${ccolor(r.customer_id)};margin-right:6px"></i>${esc(r.customer_name)}</td>
      <td class="n">${r.due_in_h.toFixed(1)}h</td><td class="n">${fmt(r.penalty_if_now_krw)}</td><td class="n">${fmt(r.penalty_if_deferred_krw)}</td><td class="n"><div class="row" style="justify-content:flex-end;gap:8px;flex-wrap:nowrap"><div class="mbar"><i style="width:${r.marginal_krw / maxM * 100}%"></i></div><b>${fmt(r.marginal_krw)}</b></div></td>
      <td>${chip} <span style="color:var(--ink-2);font-size:12.5px">${esc(r.why)}</span>${cites ? `<details class="cite"><summary>계약서 근거</summary>${cites}</details>` : ''}</td></tr>`;
  });
  const LIMIT = 10, all = rowsArr.length;
  const draw = (n) => { $('#rank-body').innerHTML = rowsArr.slice(0, n).join(''); const m = $('#rank-more'); m.style.display = all > LIMIT ? '' : 'none'; m.textContent = n < all ? `나머지 ${all - n}건 펼치기` : '상위 10건만 보기'; m.onclick = () => draw(n < all ? all : LIMIT); };
  draw(LIMIT);
  const flips = R.ranking.filter(r => Math.abs(r.deadline_rank - r.exposure_rank) >= 3).length;
  $('#rank-sub').innerHTML = `대기 <b>${all}건</b> 중 순위가 3계단 이상 갈린 화물 <b>${flips}건</b>(왼쪽 노란 띠). <b>물리는 돈</b>은 한 사이클 미룰 때 늘어나는 페널티다.`;
}

// ---------- 누적 곡선 ----------
function renderCurve(R) {
  const W = 620, H = 270, P = { l: 66, r: 16, t: 16, b: 34 };
  const series = [['deadline_first', 'var(--penalty)', '기존'], ['exposure_first', 'var(--tower)', 'ClauseTower'], ['search_best', 'var(--neutral)', '탐색 근사 최적']].filter(s => R.policies[s[0]]);
  const all = series.flatMap(s => R.policies[s[0]].penalty_curve); const xmax = Math.max(1, ...all.map(p => p[0])) * 1.02, ymax = Math.max(1, ...all.map(p => p[1])) * 1.08;
  const x = v => P.l + (v / xmax) * (W - P.l - P.r), y = v => H - P.b - (v / ymax) * (H - P.t - P.b);
  let g = ''; for (let i = 0; i <= 4; i++) { const v = ymax * i / 4; g += `<line x1="${P.l}" x2="${W - P.r}" y1="${y(v)}" y2="${y(v)}" stroke="var(--line)"/><text x="${P.l - 8}" y="${y(v) + 4}" text-anchor="end" font-size="11" fill="var(--ink-3)">${man(v)}</text>`; }
  for (let h = 0; h <= xmax; h += 12) g += `<text x="${x(h)}" y="${H - P.b + 18}" text-anchor="middle" font-size="11" fill="var(--ink-3)">+${h}h</text>`;
  g += `<line x1="${P.l}" x2="${W - P.r}" y1="${y(0)}" y2="${y(0)}" stroke="var(--line-2)"/>`;
  const labels = [];
  series.forEach(([k, c, l]) => { const pts = [[0, 0], ...R.policies[k].penalty_curve]; let d = ''; pts.forEach((p, i) => { const px = x(p[0]), py = y(p[1]); d += (i ? `H${px}V${py}` : `M${px},${py}`); });
    g += `<path d="${d}" fill="none" stroke="${c}" stroke-width="2.2" ${k === 'search_best' ? 'stroke-dasharray="4 4"' : ''}/>`; const last = pts[pts.length - 1]; labels.push({ x: x(last[0]) - 4, y: y(last[1]) - 6, t: `${l} ${man(last[1])}`, c }); });
  labels.sort((a, b) => b.y - a.y); for (let i = 1; i < labels.length; i++) if (labels[i - 1].y - labels[i].y < 14) labels[i].y = labels[i - 1].y - 14;
  labels.forEach(L => g += `<text x="${L.x}" y="${L.y}" text-anchor="end" font-size="12" fill="var(--ink-2)">${L.t}</text>`);
  $('#curve').innerHTML = `<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="누적 페널티 곡선">${g}<rect id="curve-hit" x="${P.l}" y="${P.t}" width="${W - P.l - P.r}" height="${H - P.t - P.b}" fill="transparent"/><line id="xh" y1="${P.t}" y2="${H - P.b}" stroke="var(--line-2)" stroke-dasharray="2 3" style="display:none"/></svg>`;
  const svg = $('#curve svg'), hit = $('#curve-hit'), xh = $('#xh');
  hit.addEventListener('mousemove', e => { const r = svg.getBoundingClientRect(); const hx = (e.clientX - r.left) / r.width * W; const h = (hx - P.l) / (W - P.l - P.r) * xmax; xh.setAttribute('x1', hx); xh.setAttribute('x2', hx); xh.style.display = '';
    showTip(e, `<b>+${h.toFixed(1)}h</b><br>` + series.map(([k, c, l]) => { let v = 0; for (const p of R.policies[k].penalty_curve) { if (p[0] <= h) v = p[1]; else break; } return `<span style="color:${c}">●</span> ${l}: ${fmt(v)}`; }).join('<br>')); });
  hit.addEventListener('mouseleave', () => { xh.style.display = 'none'; hideTip(); });
}

// ---------- 정책 막대 ----------
function renderPolicyBars(R) {
  const order = ['deadline_first', 'fifo', 'value_first', 'exposure_abs', 'exposure_first', 'search_best'].filter(k => R.policies[k]);
  const max = Math.max(1, ...order.map(k => R.policies[k].total_penalty_krw)); const W = 620, rowH = 34; let g = '', i = 0;
  order.forEach(k => { const p = R.policies[k]; const w = (p.total_penalty_krw / max) * (W - 190 - 150); const c = k === 'exposure_first' ? 'var(--tower)' : k === 'deadline_first' ? 'var(--penalty)' : k === 'search_best' ? 'var(--neutral)' : 'var(--line-2)';
    g += `<text x="180" y="${i * rowH + 21}" text-anchor="end" font-size="12.5" fill="${k === 'exposure_first' ? 'var(--ink)' : 'var(--ink-2)'}" font-weight="${k === 'exposure_first' ? 600 : 400}">${esc(p.label)}</text><rect x="190" y="${i * rowH + 7}" width="${Math.max(2, w)}" height="20" rx="5" fill="${c}"/><text x="${196 + w}" y="${i * rowH + 21}" font-size="12.5" fill="var(--ink)">${fmt(p.total_penalty_krw)} <tspan fill="var(--ink-3)">· 지연 ${p.late_count}건</tspan></text>`; i++; });
  $('#bars').innerHTML = `<svg viewBox="0 0 ${W} ${order.length * rowH + 6}" width="100%" role="img" aria-label="정책별 총 페널티">${g}</svg>`;
}

// ---------- 간트 ----------
function renderGantt(R, id, P) {
  const W = 980, rowH = 22, L = 46, T = 18, B = 24; const n = R.scenario.trucks; const xmax = Math.max(...P.records.map(r => r.delivered_h)) + 2; const x = v => L + (v / xmax) * (W - L - 10);
  let g = ''; for (let h = 0; h <= xmax; h += 6) g += `<line x1="${x(h)}" x2="${x(h)}" y1="${T}" y2="${T + n * rowH}" stroke="var(--line)"/><text x="${x(h)}" y="${T + n * rowH + 16}" font-size="11" text-anchor="middle" fill="var(--ink-3)">+${h}h</text>`;
  for (let i = 0; i < n; i++) g += `<text x="${L - 6}" y="${T + i * rowH + 15}" font-size="11" text-anchor="end" fill="var(--ink-3)">T${i + 1}</text>`;
  const d = R.scenario.disruption; if (d.trucks_out) g += `<rect x="${x(d.trucks_out_from_h)}" y="${T}" width="${x(d.trucks_out_until_h) - x(d.trucks_out_from_h)}" height="${d.trucks_out * rowH}" fill="url(#hatch)" opacity=".55"/><text x="${x(d.trucks_out_from_h) + 4}" y="${T + 12}" font-size="11" fill="var(--ink-2)">결항 ${d.trucks_out}대</text>`;
  P.records.forEach(r => { const y = T + r.truck * rowH + 3; const w = Math.max(2, x(r.delivered_h) - x(r.dispatched_h)); const late = r.delay_h > 0; const nm = (R.customers.find(c => c.id === r.customer_id) || {}).name || r.customer_id;
    g += `<g class="bar" data-tip="${esc(`<b>${r.shipment_id}</b> ${nm}<br>출발 +${r.dispatched_h}h → 도착 +${r.delivered_h}h (마감 +${r.due_h}h)<br>지연 ${r.delay_h}h · 페널티 ${fmt(r.penalty_krw)}${r.blocked_by ? ' · ' + r.blocked_by : ''}${r.rank_reason ? '<br>' + r.rank_reason : ''}`)}"><rect x="${x(r.dispatched_h)}" y="${y}" width="${w}" height="${rowH - 6}" rx="4" fill="${ccolor(r.customer_id)}" stroke="${late ? 'var(--hot)' : 'var(--card)'}" stroke-width="${late ? 2 : 1}"/>${r.penalty_krw > 0 ? `<text x="${x(r.dispatched_h) + 3}" y="${y + 12}" font-size="10" fill="#fff">${r.shipment_id}</text>` : ''}</g>`; });
  const el = document.getElementById(id); el.innerHTML = `<svg viewBox="0 0 ${W} ${T + n * rowH + B}" width="100%" role="img" aria-label="${esc(P.label)} 배차 간트"><defs><pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="6" stroke="var(--line-2)" stroke-width="2"/></pattern></defs>${g}</svg>`;
  el.querySelectorAll('.bar').forEach(b => { b.addEventListener('mousemove', e => showTip(e, b.dataset.tip)); b.addEventListener('mouseleave', hideTip); });
  document.getElementById(id + '-t').innerHTML = `<b>${esc(P.label)}</b> · 총 ${fmt(P.total_penalty_krw)} · 지연 ${P.late_count}건(빨간 테두리)`;
}
function renderLog(R) { $('#log').innerHTML = R.agent_log.map((l, i) => `<li>${esc(l)}</li>`).join(''); }
