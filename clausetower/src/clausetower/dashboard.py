"""단일 HTML 대시보드. 외부 자원 없이 열린다(심사장 오프라인 대비). 데이터는 JSON으로 내장하고 차트는 인라인 SVG다."""

from __future__ import annotations

import json
from pathlib import Path

from .schemas import Report

CSS = """
:root{--surface:#fcfcfb;--plane:#f9f9f7;--ink:#0b0b0b;--ink2:#52514e;--muted:#898781;--grid:#e1e0d9;--axis:#c3c2b7;--ring:rgba(11,11,11,.10);
--ours:#2a78d6;--base:#eb6834;--search:#898781;--good:#0ca30c;--warn:#fab219;--serious:#ec835a;--crit:#d03b3b;
--c1:#2a78d6;--c2:#eb6834;--c3:#1baf7a;--c4:#eda100;--c5:#e87ba4;--c6:#008300;--c7:#6250d6;--c8:#e34948}
*{box-sizing:border-box}body{margin:0;background:var(--plane);color:var(--ink);font:15px/1.55 -apple-system,"Apple SD Gothic Neo","Malgun Gothic","Noto Sans KR",Segoe UI,sans-serif}
header{background:var(--surface);border-bottom:1px solid var(--grid);padding:18px 28px;display:flex;align-items:baseline;gap:18px;flex-wrap:wrap}
header h1{margin:0;font-size:22px;letter-spacing:-.01em}header .tag{color:var(--ink2)}header .tabs{margin-left:auto;display:flex;gap:6px}
.tab{border:1px solid var(--axis);background:var(--surface);border-radius:999px;padding:6px 14px;cursor:pointer;font-size:14px}.tab.on{background:var(--ink);color:#fff;border-color:var(--ink)}.more{border:1px solid var(--axis);background:var(--surface);border-radius:8px;padding:6px 14px;cursor:pointer;font-size:13px;color:var(--ours)}
main{max-width:1280px;margin:0 auto;padding:22px 28px 60px}section{background:var(--surface);border:1px solid var(--grid);border-radius:12px;padding:20px 22px;margin:0 0 18px}
h2{margin:0 0 6px;font-size:17px}h2 small{font-weight:400;color:var(--ink2);margin-left:8px;font-size:13px}.sub{color:var(--ink2);margin:0 0 14px;font-size:14px}
.kpis{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px}.kpi{border:1px solid var(--grid);border-radius:10px;padding:14px 16px;background:var(--plane)}
.kpi .l{color:var(--ink2);font-size:13px}.kpi .v{font-size:26px;font-weight:600;font-variant-numeric:tabular-nums;letter-spacing:-.01em;margin-top:2px}.kpi .d{font-size:13px;color:var(--ink2)}
.kpi.ours{border-color:var(--ours)}.kpi.save .v{color:#006300}
table{border-collapse:collapse;width:100%;font-size:14px;font-variant-numeric:tabular-nums}th{color:var(--ink2);font-weight:500;text-align:left;border-bottom:1px solid var(--axis);padding:8px 8px}
td{border-bottom:1px solid var(--grid);padding:8px 8px;vertical-align:top}td.n,th.n{text-align:right;white-space:nowrap}td.nw{white-space:nowrap}tr.flip td{background:#fff7ec}
.chip{display:inline-block;border-radius:6px;padding:1px 8px;font-size:12px;border:1px solid var(--ring);background:#fff;white-space:nowrap}
.chip.fm{border-color:var(--good);color:#006300}.chip.grace{border-color:var(--c3);color:#0b6b4a}.chip.hot{border-color:var(--crit);color:var(--crit)}
.arrow{font-weight:600}.arrow.up{color:var(--crit)}.arrow.down{color:#006300}
details summary{cursor:pointer;color:var(--ours);font-size:13px}blockquote{margin:6px 0 0;padding:6px 10px;border-left:3px solid var(--grid);color:var(--ink2);font-size:13px}
.grid2{display:grid;grid-template-columns:1fr 1fr;gap:18px}@media(max-width:900px){.grid2{grid-template-columns:1fr}}
svg text{font-family:inherit}.legend{display:flex;gap:16px;flex-wrap:wrap;font-size:13px;color:var(--ink2);margin:4px 0 8px}.legend i{display:inline-block;width:12px;height:12px;border-radius:3px;margin-right:6px;vertical-align:-1px}
.tip{position:fixed;pointer-events:none;background:#fff;border:1px solid var(--axis);border-radius:8px;padding:8px 10px;font-size:13px;box-shadow:0 4px 14px rgba(0,0,0,.08);display:none;z-index:9;max-width:320px}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(290px,1fr));gap:12px}.card{border:1px solid var(--grid);border-radius:10px;padding:12px 14px;background:var(--plane)}
.card h3{margin:0 0 6px;font-size:15px}.card .meta{font-size:13px;color:var(--ink2);line-height:1.6}.card .j{margin-top:8px;font-size:13px;padding:8px 10px;border-radius:8px;background:#fff;border:1px solid var(--grid)}
.log li{margin:4px 0;color:var(--ink2)}.log li b{color:var(--ink)}footer{color:var(--muted);font-size:12px;text-align:center;padding:10px}
.gantt-wrap{overflow-x:auto}
"""

JS = r"""
const DATA = __DATA__;
const fmt = n => n.toLocaleString('ko-KR') + '원';
const man = n => (n/10000).toLocaleString('ko-KR', {maximumFractionDigits:0}) + '만';
const CUST = ['--c1','--c2','--c3','--c4','--c5','--c6','--c7','--c8'];
const ccolor = id => `var(${CUST['ABCDEFGH'.indexOf(id) % 8]})`;
let cur = DATA[0].scenario.id;
const $ = s => document.querySelector(s);
const tip = $('#tip');
function showTip(e, html){ tip.innerHTML = html; tip.style.display='block'; tip.style.left=(e.clientX+14)+'px'; tip.style.top=(e.clientY+14)+'px'; }
function hideTip(){ tip.style.display='none'; }
function esc(s){ return String(s).replace(/[&<>"]/g, c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c])); }

function render(){
  const R = DATA.find(d => d.scenario.id === cur);
  document.querySelectorAll('nav.tabs .tab').forEach(t => t.classList.toggle('on', t.dataset.id === cur));
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
    html = (HTML.replace("__CSS__", CSS).replace("__TABS__", tabs).replace("__CLEGEND__", legend)
            .replace("__JS__", JS.replace("__DATA__", data.replace("</", "<\\/"))))
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    return out_path
