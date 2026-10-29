// 웹 데모 스모크 테스트: 조작 패널, 출처 전환, 라이브 AI 흐름(API는 가짜 응답으로 가로챔). 사용: node scripts/smoke_web.js site/index.html docs/screenshots/web
const { chromium } = require('playwright'); const path = require('path'); const fs = require('fs');
(async () => {
  const [,, htmlPath, outDir] = process.argv; fs.mkdirSync(outDir, { recursive: true });
  const browser = await chromium.launch(); const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 2 });
  const errors = []; page.on('pageerror', e => errors.push(e.message)); page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  // 가짜 Anthropic 응답: 요청의 tool 이름에 맞춰 스키마에 맞는 결과를 돌려준다
  const fakeExtraction = cid => ({ terms: { customer_id: cid, basis: 'per_hour', rate_pct: 0.08, grace_hours: 3, base: 'shipment_value', cap_pct: 8, cap_scope: 'shipment', partial_unit_rounds_up: true, tiers: [],
        force_majeure: { covered_events: ['천재지변', '파업'], notice_hours: 36, conditions: [], citation: { clause: '제12조', quote: '태풍, 지진, 홍수 등 천재지변 또는 파업으로 인한 지연에 대하여 수행사는 책임을 지지 아니한다' } },
        citations: { rate: { clause: '제7조 제1항', quote: '지연된 매 1시간마다 해당 주문 상품가액의 0.08%를 배상한다' }, grace: { clause: '제7조 제2항', quote: '배송 시한 경과 후 3시간 이내의 지연은 배상 대상에서 제외한다' }, cap: { clause: '제7조 제3항', quote: '배상금 총액은 해당 주문 상품가액의 8%를 초과하지 아니한다' } } }, confidence: 0.9, ambiguities: [] });
  const fakeJudgment = (cid, user) => ({ customer_id: cid, has_clause: true, event_covered: user.includes('파업'), notice_ok: true, conditions_met: {}, applies: user.includes('파업'), reasoning: '가짜 응답: 파업은 면책 사유에 해당한다.', citation: { clause: '제12조', quote: '파업' } });
  // 로컬 도우미 흉내
  await page.route('http://127.0.0.1:8787/**', async route => { const u = route.request().url(); if (u.endsWith('/health')) return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ok: true, mode: 'claude-code', model: 'claude-opus-5-5' }) });
    const body = JSON.parse(route.request().postData()); const out = u.endsWith('/extract') ? fakeExtraction(body.customer_id) : fakeJudgment(body.customer_id, body.event.description + body.event.event_type);
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(out) }); });
  // 사내 OpenAI 호환 게이트웨이 흉내
  await page.route('https://llm.company.local/**', async route => { const body = JSON.parse(route.request().postData()); const tool = body.tools[0].function.name; const user = body.messages[1].content; const cid = (user.match(/고객 ID: (\w+)/) || [])[1] || 'X';
    const args = tool === 'submit_extraction' ? fakeExtraction(cid) : fakeJudgment(cid, user); return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ choices: [{ message: { tool_calls: [{ function: { name: tool, arguments: JSON.stringify(args) } }] } }] }) }); });
  await page.route('https://api.anthropic.com/**', async route => {
    const body = JSON.parse(route.request().postData()); const tool = body.tools[0].name; const user = body.messages[0].content; const cid = (user.match(/고객 ID: (\w+)/) || [])[1] || 'X';
    const input = tool === 'submit_extraction' ? { terms: { customer_id: cid, basis: 'per_hour', rate_pct: 0.08, grace_hours: 3, base: 'shipment_value', cap_pct: 8, cap_scope: 'shipment', partial_unit_rounds_up: true, tiers: [],
        force_majeure: { covered_events: ['천재지변', '파업'], notice_hours: 36, conditions: [], citation: { clause: '제12조', quote: '태풍, 지진, 홍수 등 천재지변 또는 파업으로 인한 지연에 대하여 수행사는 책임을 지지 아니한다' } },
        citations: { rate: { clause: '제7조 제1항', quote: '지연된 매 1시간마다 해당 주문 상품가액의 0.08%를 배상한다' }, grace: { clause: '제7조 제2항', quote: '배송 시한 경과 후 3시간 이내의 지연은 배상 대상에서 제외한다' }, cap: { clause: '제7조 제3항', quote: '배상금 총액은 해당 주문 상품가액의 8%를 초과하지 아니한다' } } }, confidence: 0.9, ambiguities: [] }
      : { customer_id: cid, has_clause: true, event_covered: user.includes('파업'), notice_ok: true, conditions_met: {}, applies: user.includes('파업'), reasoning: '가짜 응답: 파업은 면책 사유에 해당한다.', citation: { clause: '제12조', quote: '파업' } };
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ content: [{ type: 'tool_use', name: tool, input }], usage: { input_tokens: 1, output_tokens: 1 } }) });
  });
  await page.goto('file://' + path.resolve(htmlPath)); await page.addStyleTag({ content: '.appbar{position:static!important}.card{animation:none!important}' }); await page.waitForTimeout(400);
  const kpi = async () => page.$eval('#kpis', el => el.innerText.replace(/\s+/g, ' ').slice(0, 160));
  console.log('초기:', await kpi());
  await page.screenshot({ path: `${outDir}/web_overview.png`, clip: { x: 0, y: 0, width: 1280, height: 900 } });
  // 1) 통지 시점을 10시간으로 → 세움건설 통지 요건 충족 → 면책 적용 → 숫자 변화
  await page.$eval('#c-notice', el => { el.value = 10; el.dispatchEvent(new Event('input')); }); await page.waitForTimeout(300);
  console.log('통지 10h:', await kpi()); const note1 = await page.$eval('#src-note', el => el.innerText); console.log('  ', note1.slice(0, 120));
  // 2) 입증 자료 체크 → 청람제약 면책
  const fact = await page.$('[data-fact]'); if (fact) { await fact.check(); await page.waitForTimeout(300); console.log('입증 자료:', await kpi()); }
  // 3) 출처 전환
  await page.selectOption('#c-source', 'golden'); await page.waitForTimeout(300); console.log('정답지 출처:', await kpi());
  // 4) 사람이 면책 뒤집기
  await page.selectOption('[data-ovr="D"]', 'yes'); await page.waitForTimeout(300); console.log('D 면책 뒤집음:', (await page.$eval('#src-note', el => el.innerText)).slice(0, 100));
  await page.fill('#m-type', '지진'); await page.$eval('#m-type', el => el.dispatchEvent(new Event('change'))); await page.waitForTimeout(200); console.log('사건 직접 입력:', await page.$eval('#sc-title', el => el.innerText));
  // 5) 탐색
  await page.click('#btn-search'); await page.waitForTimeout(4000); console.log('탐색 후:', await kpi());
  // 6) 라이브 AI: 계약 업로드 흐름(API 키 백엔드)
  await page.selectOption('#k-backend', 'api'); await page.fill('#k-key', 'sk-ant-test-0000'); await page.click('#k-save'); await page.click('#u-sample'); await page.click('#u-run');
  await page.waitForFunction(() => document.querySelector('#u-out').innerText.includes('추가했다') || document.querySelector('#u-out').innerText.includes('실패'), null, { timeout: 15000 });
  console.log('업로드:', (await page.$eval('#u-out', el => el.innerText)).slice(0, 200));
  console.log('  NaN 정책:', await page.evaluate(() => Object.entries(window.CT_LAST.policies).filter(([k, p]) => Number.isNaN(p.total_penalty_krw)).map(([k]) => k)));
  console.log('  업로드 고객 terms:', await page.evaluate(() => JSON.stringify(window.CT_APP.currentTerms().I || null).slice(0, 300)));
  const hasI = await page.$eval('#rank-body', el => el.innerText.includes('I0')); console.log('  순위표에 업로드 고객 화물 등장:', hasI);
  await page.$eval('#live', el => el.scrollIntoView()); await page.waitForTimeout(200);
  const live = await page.$('#live'); await live.screenshot({ path: `${outDir}/web_live_upload.png` });
  // 7) 라이브 AI: 사건 재판단
  await page.click('#e-sample'); await page.click('#e-run');
  await page.waitForFunction(() => document.querySelector('#e-out').innerText.includes('완료') || document.querySelector('#e-out').innerText.includes('실패'), null, { timeout: 20000 });
  console.log('사건 재판단:', (await page.$eval('#e-out', el => el.innerText)).slice(0, 200)); console.log('  제목:', await page.$eval('#sc-title', el => el.innerText));
  const board = await page.$('main > section:nth-of-type(2)'); await board.screenshot({ path: `${outDir}/web_board_cards.png` });
  await page.click('#board-toggle [data-mode="matrix"]'); await page.waitForTimeout(200); await board.screenshot({ path: `${outDir}/web_board_matrix.png` }); await page.click('#board-toggle [data-mode="cards"]');
  await page.click('[data-open="H"]'); await page.waitForTimeout(400); await page.screenshot({ path: `${outDir}/web_drawer.png`, clip: { x: 0, y: 0, width: 1280, height: 900 } }); await page.click('#drawer-close'); await page.waitForTimeout(300);
  await page.click('#e-reset'); await page.click('#u-remove'); await page.waitForTimeout(300); console.log('되돌림:', await kpi());
  // 8) 로컬 도우미 백엔드
  await page.selectOption('#k-backend', 'helper'); await page.click('#h-check'); await page.waitForTimeout(300); console.log('도우미 상태:', await page.$eval('#k-status', el => el.innerText));
  await page.fill('#u-name', '도우미고객'); await page.click('#u-run'); await page.waitForFunction(() => /추가했다|실패/.test(document.querySelector('#u-out').innerText), null, { timeout: 15000 }); console.log('도우미 업로드:', (await page.$eval('#u-out', el => el.innerText)).slice(0, 80));
  await page.click('#e-run'); await page.waitForFunction(() => /완료|실패/.test(document.querySelector('#e-out').innerText), null, { timeout: 20000 }); console.log('도우미 재판단:', (await page.$eval('#e-out', el => el.innerText)).slice(0, 80));
  await page.$eval('#live', el => el.scrollIntoView()); await page.waitForTimeout(200); const lv = await page.$('#live'); await lv.screenshot({ path: `${outDir}/web_live_helper.png` });
  // 9) 사내 OpenAI 호환 백엔드
  await page.selectOption('#k-backend', 'custom'); await page.fill('#c-url', 'https://llm.company.local/v1'); await page.$eval('#c-url', el => el.dispatchEvent(new Event('change'))); await page.fill('#c-model', 'company-llm'); await page.$eval('#c-model', el => el.dispatchEvent(new Event('change')));
  await page.click('#u-remove'); await page.fill('#u-name', '사내LLM고객'); await page.click('#u-run'); await page.waitForFunction(() => /추가했다|실패/.test(document.querySelector('#u-out').innerText), null, { timeout: 15000 }); console.log('사내 LLM 업로드:', (await page.$eval('#u-out', el => el.innerText)).slice(0, 80));
  await page.click('#e-reset'); await page.click('#u-remove'); await page.waitForTimeout(200);
  await page.click('.tab[data-id="wms_outage"]'); await page.waitForTimeout(300); console.log('WMS 탭:', await kpi(), '| 출처 옵션:', await page.$$eval('#c-source option', o => o.map(x => x.value)));
  await browser.close(); console.log('page errors:', errors.length ? errors.join(' | ') : 'none');
})();
