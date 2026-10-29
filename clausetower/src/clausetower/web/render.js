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
  renderSummary(R); renderActions(R); renderBoard(R); renderRanking(R); renderCurve(R); renderPolicyBars(R);
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
  const hotEl = $('#hot'); if (hotEl) hotEl.innerHTML = hot.length ? `<span>기존 방식에서 가장 많이 물리는 고객</span>` + hot.map(x => `<span class="chip"><i class="dot" style="background:${ccolor(x.c.id)}"></i>${esc(x.c.name)} ${fmt(x.b)}${x.d > 0 ? ` <b style="color:var(--good)">−${fmt(x.d)}</b>` : ''}</span>`).join('') : '<span>이 설정에서는 어느 고객도 물리지 않는다.</span>';
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
        return `<tr data-cid="${c.id}"><td data-item="basis"><i class="dot" style="display:inline-block;width:9px;height:9px;border-radius:50%;background:${ccolor(c.id)};margin-right:6px"></i><b>${esc(c.name)}</b><div><button class="lnk" style="font-size:11.5px">상세 →</button></div></td>
          <td data-item="basis"><div>${BASIS[t.basis] || t.basis}</div><div style="color:var(--ink-2)">${esc(s.rate)}${t.base !== 'shipment_value' ? ` <small>(${BASE[t.base]})</small>` : ''}</div></td>
          <td class="n" data-item="grace">${t.grace_hours}h</td><td data-item="cap">${s.cap ? s.cap.label + (s.cap.scope === 'customer_period' ? '<div><small>고객 합계</small></div>' : '') : '<b style="color:var(--hot)">없음</b>'}</td>
          <td data-item="fm">${fm ? esc(fm.covered_events.join(' · ')) : '<span class="chip none">없음</span>'}</td><td data-item="fm">${notice}${cond}</td>
          <td data-item="judge"><span class="vd ${v.cls}">${v.cls === 'ok' ? '✓' : v.cls === 'no' ? '!' : '–'} ${v.t.replace(' (사람 결정)', '<br><small>(사람 결정)</small>')}</span></td>
          <td class="n num" data-item="judge">${fmt(base.per_customer_krw[c.id] || 0)}</td><td class="n num" data-item="judge"><b>${fmt(ours.per_customer_krw[c.id] || 0)}</b></td></tr>`; }).join('') + '</tbody></table>';
    el.querySelectorAll('td[data-item]').forEach(td => td.addEventListener('click', () => openContract(R, td.parentElement.dataset.cid, td.dataset.item)));
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
        <div class="fact" data-item="basis" title="항목 상세"><div class="k">과금 방식</div><div class="v">${BASIS[t.basis] || t.basis}</div><div class="s">${esc(s.rate)}</div></div>
        <div class="fact" data-item="grace" title="항목 상세"><div class="k">유예</div><div class="v">${t.grace_hours ? t.grace_hours + '시간' : '없음'}</div><div class="s">${t.grace_hours ? '이 안의 지연은 0원' : '지연 즉시 과금'}</div></div>
        <div class="fact" data-item="cap" title="항목 상세"><div class="k">상한</div>${capCell}</div>
        <div class="fact" data-item="base" title="항목 상세"><div class="k">기준금액</div><div class="v">${BASE[t.base]}</div><div class="s">${t.base_amount_krw ? man(t.base_amount_krw) + '원' : '건마다 다름'}</div></div>
        <div class="fact wide" data-item="fm" title="항목 상세"><div class="k">불가항력(면책)</div>${fmCell}</div>
      </div>
      <div class="verdict ${v.cls}"><span class="ic">${v.ic}</span><div><span class="t">이번 사건: ${v.t}</span>${reason ? `<span class="more lnk" data-more="${c.id}">이유</span> <span class="more lnk" data-open="${c.id}" data-item="judge">판단 상세</span><div class="rs" id="rs-${c.id}" style="display:none;margin-top:4px;color:var(--ink-2)">${reason}</div>` : ''}</div></div>
      <div class="foot"><span class="pen">페널티 <b>${fmt(base.per_customer_krw[c.id] || 0)}</b><span class="arr">→</span><b style="color:var(--tower)">${fmt(ours.per_customer_krw[c.id] || 0)}</b></span><button class="lnk" data-open="${c.id}">항목별 상세 · 원문 ${Object.keys(t.citations || {}).length + (fm ? 1 : 0)}곳 →</button></div>
    </article>`; }).join('');
  el.querySelectorAll('[data-more]').forEach(b => b.addEventListener('click', () => { const d = document.getElementById('rs-' + b.dataset.more); d.style.display = d.style.display === 'none' ? '' : 'none'; }));
  el.querySelectorAll('[data-open]').forEach(b => b.addEventListener('click', () => openContract(R, b.dataset.open, b.dataset.item)));
  el.querySelectorAll('.fact[data-item]').forEach(f => f.addEventListener('click', () => openContract(R, f.closest('.ccard').dataset.cid, f.dataset.item)));
}

// ---------- 지금 조치 ----------
// 사건 직후 운영자가 바로 할 일 셋: 보낼 화물, 보낼 통지, 채우면 면책이 살아나는 조건. 모두 금액과 조항을 붙인다.
function renderActions(R) {
  const el = $('#actions'); if (!el) return;
  const app = window.CT_APP; const ev = R.scenario.event; const ours = R.policies.exposure_first; const sent = ev.notice_sent_after_hours;
  const top = R.ranking.slice(0, 3);
  const ships = top.map(r => `<li><span class="rk top">${r.exposure_rank}</span><div class="t"><b class="mono">${esc(r.shipment_id)}</b> <i class="dot" style="background:${ccolor(r.customer_id)}"></i>${esc(r.customer_name)}<div class="s">마감까지 ${r.due_in_h.toFixed(1)}h · 마감 순위 ${r.deadline_rank}위 · ${esc(r.why)}</div></div><b class="amt">${fmt(r.marginal_krw)}</b></li>`).join('');
  const notices = R.customers.map(c => { const t = R.terms[c.id], j = R.judgments[c.id], fm = t && t.force_majeure; if (!fm || fm.notice_hours == null || !j || !j.has_clause || !j.event_covered) return null;
    const ok = sent != null && sent <= fm.notice_hours; const unmet = Object.values(j.conditions_met || {}).filter(v => !v).length; return { c, fm, ok, unmet, money: ours.per_customer_krw[c.id] || 0, applies: j.applies }; }).filter(Boolean);
  const late = notices.filter(x => !x.ok).sort((a, b) => b.money - a.money), okN = notices.filter(x => x.ok);
  const noticeItems = late.map(x => `<li><span class="ic no">!</span><div class="t"><b>${esc(x.c.name)}</b> <span class="s">${x.fm.notice_hours}h 이내 통지 조건${sent == null ? ' · 아직 통지 안 함' : ` · ${sent}h에 통지해 시한을 놓침`}</span><div class="s">${esc(x.fm.citation.clause)} · ${x.money ? `시한을 지켰다면 ${fmt(x.money)}을 안 물린다` : '지금은 물리는 화물이 없다'}${x.unmet ? ` · 통지 외 조건 ${x.unmet}개도 걸려 있다(아래 ③)` : ''}</div><div class="row acts"><button class="lnk" data-openc="${x.c.id}" data-item="fm">조항 보기</button>${app ? `<button class="lnk" data-act="notice" data-h="${x.fm.notice_hours}">통지 ${x.fm.notice_hours}h로 시뮬레이션</button>` : ''}</div></div></li>`).join('')
    + okN.map(x => `<li class="ok"><span class="ic ok">✓</span><div class="t"><b>${esc(x.c.name)}</b> <span class="s">${x.fm.notice_hours}h 이내 · ${sent}h에 통지해 충족</span></div></li>`).join('');
  const conds = []; R.customers.forEach(c => { const t = R.terms[c.id], j = R.judgments[c.id]; if (!t.force_majeure || !j || !j.has_clause || !j.event_covered || !j.notice_ok || j.applies) return;
    Object.entries(j.conditions_met || {}).filter(([, v]) => !v).forEach(([k]) => conds.push({ c, k, t, money: ours.per_customer_krw[c.id] || 0 })); });
  conds.sort((a, b) => b.money - a.money);
  const condItems = conds.map(x => `<li><span class="ic warn">?</span><div class="t"><b>${esc(x.c.name)}</b> <span class="s">${esc(x.k)}</span><div class="s">${esc(x.t.force_majeure.citation.clause)} · ${x.money ? `채우면 ${fmt(x.money)} → 0원` : '지금은 물리는 화물이 없다'}</div><div class="row acts"><button class="lnk" data-openc="${x.c.id}" data-item="fm">조항 보기</button>${app ? `<button class="lnk" data-act="fact" data-k="${esc(x.k)}">충족으로 바꿔 보기</button>` : ''}</div></div></li>`).join('');
  const stuck = R.customers.map(c => ({ c, j: R.judgments[c.id], money: ours.per_customer_krw[c.id] || 0 })).filter(x => x.money > 0 && (!x.j || !x.j.has_clause || !x.j.event_covered)).sort((a, b) => b.money - a.money);
  const stuckSum = stuck.reduce((a, x) => a + x.money, 0);
  const recover = late.reduce((a, x) => a + x.money, 0) + conds.reduce((a, x) => a + x.money, 0);
  el.innerHTML = `
    <div class="act"><div class="ah"><span class="no">1</span><h3>지금 보낼 화물</h3><span class="s">한 사이클 미루면 가장 많이 물리는 순</span></div><ul>${ships || '<li class="s">대기 화물이 없다.</li>'}</ul><div class="af"><button class="lnk" data-goto-sec="sec-rank">전체 순서 ${R.ranking.length}건 →</button></div></div>
    <div class="act"><div class="ah"><span class="no">2</span><h3>지금 보낼 통지</h3><span class="s">면책 사유에는 해당하는데 통지 시한이 걸린 계약</span></div><ul>${noticeItems || '<li class="s">통지 시한이 걸린 계약이 없다.</li>'}</ul><div class="af">${late.length ? `<b>${late.length}건 시한 문제</b>` : '<b class="good">통지 요건 모두 충족</b>'}${app && late.length ? ' · 왼쪽 "고객 통지 시점"으로 조정' : ''}</div></div>
    <div class="act"><div class="ah"><span class="no">3</span><h3>채우면 살아나는 면책</h3><span class="s">정성 조건(입증 자료 등) 하나로 갈리는 계약</span></div><ul>${condItems || '<li class="s">조건이 걸린 계약이 없다.</li>'}${stuck.length ? `<li class="muted"><span class="ic none">–</span><div class="t"><b>그대로 물리는 고객</b> <span class="s">면책 조항이 없거나 사유가 다름</span><div class="s">${stuck.map(x => esc(x.c.name) + ' ' + fmt(x.money)).join(' · ')} · 배차 순서로만 줄인다</div></div></li>` : ''}</ul><div class="af">${recover ? `<b>통지·조건으로 살릴 수 있는 돈 ${fmt(recover)}</b>` : '<b>조건으로 더 살릴 돈은 없다</b>'}${stuckSum ? ` · 배차로만 ${fmt(stuckSum)}` : ''}</div></div>`;
  el.querySelectorAll('[data-openc]').forEach(b => b.addEventListener('click', () => openContract(R, b.dataset.openc, b.dataset.item)));
  el.querySelectorAll('[data-goto-sec]').forEach(b => b.addEventListener('click', () => { const t = document.getElementById(b.dataset.gotoSec); if (t) t.scrollIntoView({ behavior: 'smooth', block: 'start' }); }));
  if (app) { el.querySelectorAll('[data-act="notice"]').forEach(b => b.addEventListener('click', () => app.setNotice(+b.dataset.h))); el.querySelectorAll('[data-act="fact"]').forEach(b => b.addEventListener('click', () => app.setFact(b.dataset.k, true))); }
}

// ---------- 계약서 서랍: 항목별 상세 + 전문 ----------
const ITEM_LABEL = { basis: '과금 방식 · 요율', base: '기준금액', grace: '유예', cap: '상한', rounding: '단위 올림', escalation: '가중 정액', fm: '불가항력(면책)', judge: '이번 사건 판단' };
function contractItems(R, cid) {
  const t = R.terms[cid], j = R.judgments[cid], x = R.extraction[cid] || {}, fm = t.force_majeure, ev = R.scenario.event, s = termsSummary(t); const C = t.citations || {}; const used = new Set();
  const take = (...keys) => { for (const k of keys) if (C[k]) { used.add(k); return C[k]; } return null; };
  const items = [];
  items.push({ key: 'basis', v: `<b>${BASIS[t.basis] || t.basis}</b> · ${esc(s.rate)}`, d: t.basis === 'per_business_day' ? '영업일 기준이라 주말은 세지 않는다' : t.basis === 'per_hour' ? '시간 단위라 짧은 지연도 바로 물린다' : t.basis === 'flat_per_shipment' ? '지연 1건마다 정액이라 한 사이클만 미뤄도 바로 물린다' : t.basis === 'tiered_per_day' ? '지연이 길어질수록 요율이 오른다' : '역일 기준, 하루 단위', c: take('rate', 'basis') });
  if (t.flat_escalation) items.push({ key: 'escalation', v: `<b>${t.flat_escalation.after_hours}시간 초과 시 ${man(t.flat_escalation.amount_krw)}원/건</b>`, d: '지연이 길어지면 정액이 뛴다', c: take('escalation') });
  items.push({ key: 'base', v: `<b>${BASE[t.base]}</b>${t.base_amount_krw ? ' · ' + fmt(t.base_amount_krw) : ''}`, d: t.base === 'shipment_value' ? '건마다 화물가액이 달라 같은 지연도 금액이 다르다' : '화물가액과 무관하게 고정 금액에 요율을 곱한다', c: take('base', 'basis') });
  items.push({ key: 'grace', v: t.grace_hours ? `<b>${t.grace_hours}시간</b> · 이 안의 지연은 0원` : '<b>없음</b> · 지연 즉시 과금', d: t.grace_hours ? '유예 안에 들어오는 화물은 미뤄도 돈이 안 물린다' : '', c: take('grace'), none: !t.grace_hours && !C.grace ? '유예 조항이 없다(계약서에 언급 없음)' : null });
  items.push({ key: 'cap', v: s.cap ? `<b>${s.cap.label}</b> · ${s.cap.scope === 'customer_period' ? '고객·기간 합계 기준' : '건별'}` : '<b>없음</b> · 시간이 갈수록 계속 물린다', d: s.cap && s.cap.scope === 'customer_period' ? '합계 상한에 닿으면 그 뒤 지연은 더 안 물린다' : s.cap ? '건별로 상한에 닿으면 그 화물은 더 미뤄도 된다' : '', c: take('cap'), none: !s.cap && !C.cap ? '상한 조항이 없다' : null });
  items.push({ key: 'rounding', v: t.partial_unit_rounds_up ? '<b>1단위 미만도 1단위로 올림</b>' : '<b>비례 계산</b>', d: t.partial_unit_rounds_up ? '10분 지연도 한 단위로 물린다' : '', c: take('rounding', 'partial') });
  if (fm) items.push({ key: 'fm', v: `<div class="chips">${fm.covered_events.map(e => `<span class="chip">${esc(e)}</span>`).join('')}</div><div class="kv"><span>통지 시한</span><b>${fm.notice_hours != null ? fm.notice_hours + '시간 이내' : '없음'}</b></div>${fm.conditions.length ? `<div class="kv"><span>정성 조건</span><b>${fm.conditions.map(z => `<span class="chip warn">${esc(z)}</span>`).join(' ')}</b></div>` : '<div class="kv"><span>정성 조건</span><b>없음</b></div>'}`, d: '', c: fm.citation });
  else items.push({ key: 'fm', v: '<b>조항 없음</b> · 사유를 불문하고 물린다', d: '', c: take('fm', 'force_majeure'), none: '불가항력 면책 조항이 없다' });
  if (j) { const condRows = Object.entries(j.conditions_met || {}).map(([k, v]) => `<div class="chk ${v ? 'ok' : 'no'}"><i>${v ? '✓' : '✗'}</i>조건 "${esc(k)}" ${v ? '충족' : '미충족'}</div>`).join('');
    const vv = verdictOf(j);
    items.push({ key: 'judge', v: `<div class="verdict ${vv.cls}" style="margin:0 0 8px"><span class="ic">${vv.ic}</span><div><span class="t">${vv.t}</span></div></div>
      <div class="chk ${j.has_clause ? 'ok' : 'no'}"><i>${j.has_clause ? '✓' : '✗'}</i>면책 조항 ${j.has_clause ? '있음' : '없음'}</div>
      ${j.has_clause ? `<div class="chk ${j.event_covered ? 'ok' : 'no'}"><i>${j.event_covered ? '✓' : '✗'}</i>사건 "${esc(ev.event_type)}"이 면책 사유에 ${j.event_covered ? '해당' : '해당하지 않음'}</div>
      <div class="chk ${j.notice_ok ? 'ok' : 'no'}"><i>${j.notice_ok ? '✓' : '✗'}</i>통지 ${fm && fm.notice_hours != null ? `${fm.notice_hours}h 이내 요건 · ${ev.notice_sent_after_hours == null ? '통지 안 함' : ev.notice_sent_after_hours + 'h에 통지'}` : '요건 없음'} → ${j.notice_ok ? '충족' : '미충족'}</div>${condRows}` : ''}
      <p class="rs">${esc(j.reasoning)}</p>`, d: '', c: j.citation || null });
  }
  const rest = Object.entries(C).filter(([k]) => !used.has(k)).map(([k, c]) => ({ key: 'c_' + k, label: '그 밖의 근거 · ' + k, v: '', d: '', c }));
  const amb = (x.ambiguities || []).filter(a => a && !a.startsWith('정답지')); const notes = [t.notes, ...amb].filter(Boolean);
  return { items: items.concat(rest), notes, confidence: x.confidence };
}
let DRAWER = { cid: null, tab: 'items' };
function openContract(R, cid, focus) {
  const c = R.customers.find(x => x.id === cid); if (!c) return; const text = CONTRACT_TEXTS[cid] || (window.CT_APP && window.CT_APP.contractText && window.CT_APP.contractText(cid)) || '';
  const { items, notes, confidence } = contractItems(R, cid);
  // 전문: 인용 문장을 <mark id>로 표시하고, 항목 쪽 인용이 어느 mark로 가는지 연결한다
  const quotes = items.filter(i => i.c).map(i => i.c.quote); const heads = [...new Set(quotes.flatMap(q => q.split('…').map(p => p.trim()).filter(p => p.length >= 8)))];
  let html = esc(text); const markId = {}; heads.forEach((h, i) => { const eh = esc(h); if (html.includes(eh)) { markId[h] = 'mk-' + i; html = html.split(eh).join(`<mark id="mk-${i}">${eh}</mark>`); } });
  const full = html.split('\n').map(l => l.startsWith('## ') ? `<h4>${l.slice(3)}</h4>` : l.startsWith('# ') ? `<h3>${l.slice(2)}</h3>` : l.trim() ? `<p style="margin:4px 0">${l}</p>` : '').join('');
  const gotoId = q => { for (const h of q.split('…').map(p => p.trim())) if (markId[h]) return markId[h]; return null; };
  const list = items.map(it => { const g = it.c ? gotoId(it.c.quote) : null;
    return `<section class="ditem ${focus === it.key ? 'focus' : ''}" data-key="${it.key}"><div class="k">${esc(it.label || ITEM_LABEL[it.key] || it.key)}</div><div class="b">${it.v ? `<div class="v">${it.v}</div>` : ''}${it.d ? `<div class="d">${it.d}</div>` : ''}
      ${it.c ? `<blockquote><b>${esc(it.c.clause)}</b> ${esc(it.c.quote)}${g ? ` <button class="lnk" data-goto="${g}">원문에서 보기 →</button>` : ' <span class="s">(원문과 글자 단위로 일치하는 구절을 찾지 못함)</span>'}</blockquote>` : it.none ? `<div class="none">${esc(it.none)}</div>` : ''}</div></section>`; }).join('');
  const notesHtml = notes.length ? `<section class="ditem" data-key="notes"><div class="k">읽기 메모</div><div class="b">${notes.map(n => `<div class="d">${esc(n)}</div>`).join('')}</div></section>` : '';
  $('#drawer-title').textContent = `${c.name} 계약 상세`; $('#drawer-sub').textContent = `${c.segment || ''} · 항목 ${items.length}개 · 인용 ${heads.length}곳${confidence != null ? ` · 읽기 확신도 ${Math.round(confidence * 100)}%` : ''}`;
  $('#drawer-body').innerHTML = `<div class="dtabs"><button class="${DRAWER.tab === 'items' ? 'on' : ''}" data-tab="items">항목별</button><button class="${DRAWER.tab === 'text' ? 'on' : ''}" data-tab="text">계약서 전문</button></div>
    <div class="dpane" data-pane="items">${list}${notesHtml}</div><div class="dpane" data-pane="text">${full || '<p>원문이 없다.</p>'}</div>`;
  DRAWER.cid = cid; if (focus) DRAWER.tab = 'items'; setDrawerTab(DRAWER.tab);
  const body = $('#drawer-body'); body.querySelectorAll('[data-tab]').forEach(b => b.addEventListener('click', () => setDrawerTab(b.dataset.tab)));
  body.querySelectorAll('[data-goto]').forEach(b => b.addEventListener('click', () => { setDrawerTab('text'); const m = document.getElementById(b.dataset.goto); if (m) { m.scrollIntoView({ block: 'center' }); m.classList.remove('flash'); void m.offsetWidth; m.classList.add('flash'); } }));
  $('#drawer').classList.add('open'); $('#scrim').classList.add('on');
  if (focus) { const f = body.querySelector(`.ditem[data-key="${focus}"]`); if (f) setTimeout(() => f.scrollIntoView({ block: 'start' }), 50); } else body.scrollTop = 0;
}
function setDrawerTab(tab) { DRAWER.tab = tab; const body = $('#drawer-body'); body.querySelectorAll('[data-tab]').forEach(b => b.classList.toggle('on', b.dataset.tab === tab)); body.querySelectorAll('.dpane').forEach(p => p.style.display = p.dataset.pane === tab ? '' : 'none'); }
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
    const cites = r.citations.map(c => `<blockquote><b>${esc(c.clause)}</b> ${esc(c.quote)}</blockquote>`).join('') + (r.citations.length ? `<button class="lnk" data-openc="${r.customer_id}" style="margin-top:6px">${esc(r.customer_name)} 계약 항목별 상세 →</button>` : '');
    return `<tr class="${Math.abs(diff) >= 3 ? 'flip' : ''}"><td class="n"><span class="rk ${r.exposure_rank <= 3 ? 'top' : ''}">${r.exposure_rank}</span></td><td class="n">${r.deadline_rank} ${delta}</td><td class="nw"><span class="mono"><b>${r.shipment_id}</b></span></td><td class="nw"><i class="dot" style="display:inline-block;width:9px;height:9px;border-radius:50%;background:${ccolor(r.customer_id)};margin-right:6px"></i>${esc(r.customer_name)}</td>
      <td class="n">${r.due_in_h.toFixed(1)}h</td><td class="n">${fmt(r.penalty_if_now_krw)}</td><td class="n">${fmt(r.penalty_if_deferred_krw)}</td><td class="n"><div class="row" style="justify-content:flex-end;gap:8px;flex-wrap:nowrap"><div class="mbar"><i style="width:${r.marginal_krw / maxM * 100}%"></i></div><b>${fmt(r.marginal_krw)}</b></div></td>
      <td>${chip} <span style="color:var(--ink-2);font-size:12.5px">${esc(r.why)}</span>${cites ? `<details class="cite"><summary>계약서 근거</summary>${cites}</details>` : ''}</td></tr>`;
  });
  const LIMIT = 10, all = rowsArr.length;
  const draw = (n) => { $('#rank-body').innerHTML = rowsArr.slice(0, n).join(''); $('#rank-body').querySelectorAll('[data-openc]').forEach(b => b.addEventListener('click', () => openContract(R, b.dataset.openc, 'judge'))); const m = $('#rank-more'); m.style.display = all > LIMIT ? '' : 'none'; m.textContent = n < all ? `나머지 ${all - n}건 펼치기` : '상위 10건만 보기'; m.onclick = () => draw(n < all ? all : LIMIT); };
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
