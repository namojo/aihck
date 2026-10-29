// 공용 렌더 코드. dashboard.py(오프라인 HTML)와 site/app.js(웹 데모)가 함께 쓴다.
const fmt = n => n.toLocaleString('ko-KR') + '원';
const man = n => (n/10000).toLocaleString('ko-KR', {maximumFractionDigits:0}) + '만';
const CUST = ['--c1','--c2','--c3','--c4','--c5','--c6','--c7','--c8'];
let COLOR_IDX = {}; const ccolor = id => `var(${CUST[(COLOR_IDX[id] || 0) % 8]})`;
const $ = s => document.querySelector(s);
const tip = $('#tip');
function showTip(e, html){ tip.innerHTML = html; tip.style.display='block'; tip.style.left=(e.clientX+14)+'px'; tip.style.top=(e.clientY+14)+'px'; }
function hideTip(){ tip.style.display='none'; }
function esc(s){ return String(s).replace(/[&<>"]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

function renderReport(R){
  COLOR_IDX = {}; R.customers.forEach((c, i) => COLOR_IDX[c.id] = i);
  const base = R.policies.deadline_first, ours = R.policies.exposure_first, best = R.policies.search_best;
  $('#sc-title').textContent = R.scenario.title;
  $('#sc-desc').textContent = R.scenario.description;
  const ev = R.scenario.event;
  $('#sc-event').innerHTML = `<b>사건 유형</b> ${esc(ev.event_type)} · <b>고객 통지</b> ${ev.notice_sent_after_hours==null?'안 함':'발생 '+ev.notice_sent_after_hours+'시간 뒤'}`
    + Object.entries(ev.facts||{}).map(([k,v])=>` · <b>${esc(k)}</b> ${v?'예':'아니오'}`).join('');
  $('#kpis').innerHTML = `
    <div class="kpi"><div class="l">${esc(base.label)}</div><div class="v">${fmt(base.total_penalty_krw)}</div><div class="d">지연 ${base.late_count}건 / ${base.records.length}건</div></div>
    <div class="kpi ours"><div class="l">${esc(ours.label)}</div><div class="v">${fmt(ours.total_penalty_krw)}</div><div class="d">지연 ${ours.late_count}건 / ${ours.records.length}건</div></div>
    <div class="kpi save"><div class="l">절감</div><div class="v">${fmt(R.savings_vs_deadline_krw)}</div><div class="d">기존 대비 −${R.savings_vs_deadline_pct}%</div></div>
    ${best?`<div class="kpi"><div class="l">${esc(best.label)}</div><div class="v">${fmt(best.total_penalty_krw)}</div><div class="d">우선순위 지역 탐색 결과. 상한선 참고용</div></div>`:''}`;
  renderRanking(R); renderCurve(R); renderPolicyBars(R); renderCustomers(R); renderGantt(R, 'g-base', base); renderGantt(R, 'g-ours', ours); renderEvidence(R); renderLog(R);
  $('#foot').textContent = `생성 ${R.generated_at.replace('T',' ').slice(0,16)} · LLM 모드 ${R.llm_mode} · LLM 호출 ${R.llm_calls}회 · 시뮬레이션 트럭 ${R.scenario.trucks}대, 화물 ${base.records.length}건`;
}

function renderRanking(R){
  $('#rank-at').textContent = `+${R.ranking_at_h.toFixed(1)}h`;
  const rows = R.ranking.map(r => {
    const diff = r.deadline_rank - r.exposure_rank;
    const arrow = diff>0 ? `<span class="arrow up">▲${diff}</span>` : diff<0 ? `<span class="arrow down">▼${-diff}</span>` : '<span class="arrow">–</span>';
    const chip = r.blocked_by==='불가항력 면책' ? '<span class="chip fm">불가항력 면책</span>' : r.blocked_by==='유예기간 내' ? '<span class="chip grace">유예기간 내</span>' : (r.marginal_krw>0 ? '<span class="chip hot">물림</span>':'<span class="chip">여유</span>');
    const cites = r.citations.map(c=>`<blockquote><b>${esc(c.clause)}</b> ${esc(c.quote)}</blockquote>`).join('');
    return `<tr class="${Math.abs(diff)>=3?'flip':''}"><td class="n">${r.exposure_rank}</td><td class="n">${r.deadline_rank} ${arrow}</td><td class="nw"><b>${r.shipment_id}</b></td><td class="nw">${esc(r.customer_name)}</td>
      <td class="n">${r.due_in_h.toFixed(1)}h</td><td class="n">${fmt(r.penalty_if_now_krw)}</td><td class="n">${fmt(r.penalty_if_deferred_krw)}</td><td class="n"><b>${fmt(r.marginal_krw)}</b></td>
      <td>${chip} <span style="color:var(--ink2);font-size:13px">${esc(r.why)}</span>${cites?`<details><summary>계약서 근거</summary>${cites}</details>`:''}</td></tr>`;
  }).join('');
  const LIMIT = 15, all = R.ranking.length;
  const rowsArr = rows.split('</tr>').filter(x => x.trim()).map(x => x + '</tr>');
  const draw = (n) => { $('#rank-body').innerHTML = rowsArr.slice(0, n).join('');
    $('#rank-more').style.display = all > LIMIT ? '' : 'none';
    $('#rank-more').textContent = n < all ? `나머지 ${all - n}건 펼치기` : '상위 15건만 보기';
    $('#rank-more').onclick = () => draw(n < all ? all : LIMIT); };
  draw(LIMIT);
  const flips = R.ranking.filter(r=>Math.abs(r.deadline_rank-r.exposure_rank)>=3).length;
  $('#rank-sub').textContent = `대기 ${R.ranking.length}건. 마감 순위와 노출 순위가 3계단 이상 갈린 화물 ${flips}건(배경색). '물리는 돈' = 한 사이클 미룰 때 늘어나는 페널티.`;
}

function renderCurve(R){
  const W=600,H=260,P={l:64,r:16,t:14,b:34};
  const series=[['deadline_first','var(--base)','기존'],['exposure_first','var(--ours)','ClauseTower'],['search_best','var(--search)','탐색 근사 최적']].filter(s=>R.policies[s[0]]);
  const all=series.flatMap(s=>R.policies[s[0]].penalty_curve);
  const xmax=Math.max(...all.map(p=>p[0]))*1.02, ymax=Math.max(1,...all.map(p=>p[1]))*1.08;
  const x=v=>P.l+(v/xmax)*(W-P.l-P.r), y=v=>H-P.b-(v/ymax)*(H-P.t-P.b);
  let g='';
  for(let i=0;i<=4;i++){const v=ymax*i/4;g+=`<line x1="${P.l}" x2="${W-P.r}" y1="${y(v)}" y2="${y(v)}" stroke="var(--grid)"/><text x="${P.l-8}" y="${y(v)+4}" text-anchor="end" font-size="11" fill="var(--muted)">${man(v)}</text>`;}
  for(let h=0;h<=xmax;h+=12){g+=`<text x="${x(h)}" y="${H-P.b+18}" text-anchor="middle" font-size="11" fill="var(--muted)">+${h}h</text>`;}
  g+=`<line x1="${P.l}" x2="${W-P.r}" y1="${y(0)}" y2="${y(0)}" stroke="var(--axis)"/>`;
  const labels=[];
  series.forEach(([k,c,l])=>{const pts=[[0,0],...R.policies[k].penalty_curve];let d='';pts.forEach((p,i)=>{const px=x(p[0]),py=y(p[1]);d+=(i?`H${px}V${py}`:`M${px},${py}`);});
    g+=`<path d="${d}" fill="none" stroke="${c}" stroke-width="2" ${k==='search_best'?'stroke-dasharray="4 4"':''}/>`;const last=pts[pts.length-1];labels.push({x:x(last[0])-4,y:y(last[1])-6,t:`${l} ${man(last[1])}`,c});});
  labels.sort((a,b)=>b.y-a.y);for(let i=1;i<labels.length;i++){if(labels[i-1].y-labels[i].y<14)labels[i].y=labels[i-1].y-14;}
  labels.forEach(L=>{g+=`<text x="${L.x}" y="${L.y}" text-anchor="end" font-size="12" fill="var(--ink2)">${L.t}</text>`;});
  $('#curve').innerHTML=`<svg viewBox="0 0 ${W} ${H}" width="100%" role="img" aria-label="누적 페널티 곡선">${g}<rect id="curve-hit" x="${P.l}" y="${P.t}" width="${W-P.l-P.r}" height="${H-P.t-P.b}" fill="transparent"/><line id="xh" y1="${P.t}" y2="${H-P.b}" stroke="var(--axis)" stroke-dasharray="2 3" style="display:none"/></svg>`;
  const svg=$('#curve svg'), hit=$('#curve-hit'), xh=$('#xh');
  hit.addEventListener('mousemove',e=>{const r=svg.getBoundingClientRect();const hx=(e.clientX-r.left)/r.width*W;const h=(hx-P.l)/(W-P.l-P.r)*xmax;xh.setAttribute('x1',hx);xh.setAttribute('x2',hx);xh.style.display='';
    showTip(e,`<b>+${h.toFixed(1)}h</b><br>`+series.map(([k,c,l])=>{const pts=R.policies[k].penalty_curve;let v=0;for(const p of pts){if(p[0]<=h)v=p[1];else break;}return `<span style="color:${c}">●</span> ${l}: ${fmt(v)}`;}).join('<br>'));});
  hit.addEventListener('mouseleave',()=>{xh.style.display='none';hideTip();});
}

function renderPolicyBars(R){
  const order=['deadline_first','fifo','value_first','exposure_abs','exposure_first','search_best'].filter(k=>R.policies[k]);
  const max=Math.max(...order.map(k=>R.policies[k].total_penalty_krw));const W=600,rowH=30;
  let g='',i=0;
  order.forEach(k=>{const p=R.policies[k];const w=(p.total_penalty_krw/max)*(W-170-80);const c=k==='exposure_first'?'var(--ours)':k==='deadline_first'?'var(--base)':k==='search_best'?'var(--search)':'var(--axis)';
    g+=`<text x="160" y="${i*rowH+20}" text-anchor="end" font-size="13" fill="var(--ink2)">${esc(p.label)}</text><rect x="170" y="${i*rowH+6}" width="${Math.max(2,w)}" height="18" rx="3" fill="${c}"/><text x="${176+w}" y="${i*rowH+20}" font-size="13" fill="var(--ink)">${fmt(p.total_penalty_krw)} · 지연 ${p.late_count}건</text>`;i++;});
  $('#bars').innerHTML=`<svg viewBox="0 0 ${W} ${order.length*rowH+6}" width="100%" role="img" aria-label="정책별 총 페널티">${g}</svg>`;
}

function renderCustomers(R){
  const base=R.policies.deadline_first, ours=R.policies.exposure_first;
  $('#cust-body').innerHTML=R.customers.map(c=>{const j=R.judgments[c.id];const t=R.terms[c.id];
    const chip=!j.has_clause?'<span class="chip">면책 조항 없음</span>':j.applies?'<span class="chip fm">면책 적용</span>':`<span class="chip hot">면책 미적용 · ${!j.event_covered?'사유 불해당':!j.notice_ok?'통지 지연':'조건 미충족'}</span>`;
    const cap=t.cap_pct!=null?`상한 ${t.cap_pct}%`:t.cap_amount_krw!=null?`상한 ${man(t.cap_amount_krw)}원`:'<b>상한 없음</b>';
    return `<tr><td><i style="display:inline-block;width:10px;height:10px;border-radius:3px;background:${ccolor(c.id)};margin-right:6px"></i>${esc(c.name)}</td><td style="font-size:13px;color:var(--ink2)">${esc(t.basis)} · ${t.rate_pct!=null?t.rate_pct+'%':t.flat_amount_krw?man(t.flat_amount_krw)+'원/건':'누진'} · 유예 ${t.grace_hours}h · ${cap}</td><td>${chip}</td><td class="n">${fmt(base.per_customer_krw[c.id]||0)}</td><td class="n"><b>${fmt(ours.per_customer_krw[c.id]||0)}</b></td></tr>`;}).join('');
}

function renderGantt(R, id, P){
  const W=900,rowH=22,L=46,T=18,B=24;const n=R.scenario.trucks;const xmax=Math.max(...P.records.map(r=>r.delivered_h))+2;const x=v=>L+(v/xmax)*(W-L-10);
  let g='';for(let h=0;h<=xmax;h+=6){g+=`<line x1="${x(h)}" x2="${x(h)}" y1="${T}" y2="${T+n*rowH}" stroke="var(--grid)"/><text x="${x(h)}" y="${T+n*rowH+16}" font-size="11" text-anchor="middle" fill="var(--muted)">+${h}h</text>`;}
  for(let i=0;i<n;i++){g+=`<text x="${L-6}" y="${T+i*rowH+15}" font-size="11" text-anchor="end" fill="var(--muted)">T${i+1}</text>`;}
  const d=R.scenario.disruption;if(d.trucks_out){g+=`<rect x="${x(d.trucks_out_from_h)}" y="${T}" width="${x(d.trucks_out_until_h)-x(d.trucks_out_from_h)}" height="${d.trucks_out*rowH}" fill="url(#hatch)" opacity=".5"/><text x="${x(d.trucks_out_from_h)+4}" y="${T+12}" font-size="11" fill="var(--ink2)">결항 ${d.trucks_out}대</text>`;}
  P.records.forEach(r=>{const y=T+r.truck*rowH+3;const w=Math.max(2,x(r.delivered_h)-x(r.dispatched_h));const late=r.delay_h>0;
    g+=`<g class="bar" data-tip="${esc(`<b>${r.shipment_id}</b> ${R.customers.find(c=>c.id===r.customer_id).name}<br>출발 +${r.dispatched_h}h → 도착 +${r.delivered_h}h (마감 +${r.due_h}h)<br>지연 ${r.delay_h}h · 페널티 ${fmt(r.penalty_krw)}${r.blocked_by?' · '+r.blocked_by:''}${r.rank_reason?'<br>'+r.rank_reason:''}`)}">
      <rect x="${x(r.dispatched_h)}" y="${y}" width="${w}" height="${rowH-6}" rx="3" fill="${ccolor(r.customer_id)}" stroke="${late?'var(--crit)':'var(--surface)'}" stroke-width="${late?2:1}"/>
      ${r.penalty_krw>0?`<text x="${x(r.dispatched_h)+3}" y="${y+12}" font-size="10" fill="#fff">${r.shipment_id}</text>`:''}</g>`;});
  const el=document.getElementById(id);el.innerHTML=`<svg viewBox="0 0 ${W} ${T+n*rowH+B}" width="100%" role="img" aria-label="${esc(P.label)} 배차 간트"><defs><pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)"><line x1="0" y1="0" x2="0" y2="6" stroke="var(--axis)" stroke-width="2"/></pattern></defs>${g}</svg>`;
  el.querySelectorAll('.bar').forEach(b=>{b.addEventListener('mousemove',e=>showTip(e,b.dataset.tip));b.addEventListener('mouseleave',hideTip);});
  document.getElementById(id+'-t').textContent=`${P.label} · 총 ${fmt(P.total_penalty_krw)} · 지연 ${P.late_count}건(빨간 테두리)`;
}

function renderEvidence(R){
  $('#cards').innerHTML=R.customers.map(c=>{const t=R.terms[c.id],j=R.judgments[c.id],x=R.extraction[c.id];
    const fm=t.force_majeure?`면책 사유: ${t.force_majeure.covered_events.join(', ')}${t.force_majeure.notice_hours!=null?` · 통지 ${t.force_majeure.notice_hours}h 이내`:' · 통지 시한 없음'}${t.force_majeure.conditions.length?` · 조건: ${t.force_majeure.conditions.join(', ')}`:''}`:'면책 조항 없음';
    const cites=Object.entries(t.citations).map(([k,v])=>`<blockquote><b>${esc(v.clause)}</b> ${esc(v.quote)}</blockquote>`).join('')+(t.force_majeure?`<blockquote><b>${esc(t.force_majeure.citation.clause)}</b> ${esc(t.force_majeure.citation.quote)}</blockquote>`:'');
    return `<div class="card"><h3><i style="display:inline-block;width:10px;height:10px;border-radius:3px;background:${ccolor(c.id)};margin-right:6px"></i>${esc(c.name)} <small style="color:var(--muted);font-weight:400">${esc(c.segment)}</small></h3>
      <div class="meta">${esc(t.basis)} · ${t.rate_pct!=null?'요율 '+t.rate_pct+'%':''}${t.flat_amount_krw?'건당 '+man(t.flat_amount_krw)+'원':''}${t.tiers.length?'누진 '+t.tiers.map(z=>z.rate_pct+'%').join('/'):''} · 유예 ${t.grace_hours}h<br>${t.cap_pct!=null?'상한 '+t.cap_pct+'%':t.cap_amount_krw!=null?'상한 '+man(t.cap_amount_krw)+'원':'<b style="color:var(--crit)">상한 없음</b>'}${t.cap_scope==='customer_period'?' (고객 합계)':''} · 기준 ${t.base==='shipment_value'?'건별 화물가액':t.base==='monthly_fee'?'월 서비스료':'계약금액'}<br>${fm}<br><span style="color:var(--muted)">추출 확신도 ${(x.confidence*100).toFixed(0)}%${x.ambiguities.length?' · 모호점 '+x.ambiguities.length:''}</span></div>
      <div class="j"><b>이번 사건 판단:</b> ${!j.has_clause?'면책 조항 없음':j.applies?'<span style="color:#006300">면책 적용</span>':'<span style="color:var(--crit)">면책 미적용</span>'} — ${esc(j.reasoning)}</div>
      <details><summary>계약서 원문 ${Object.keys(t.citations).length+(t.force_majeure?1:0)}곳</summary>${cites}</details></div>`;}).join('');
}
function renderLog(R){ $('#log').innerHTML=R.agent_log.map((l,i)=>`<li><b>${i+1}.</b> ${esc(l)}</li>`).join(''); }
