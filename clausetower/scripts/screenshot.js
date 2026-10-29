// 대시보드 화면 캡처. 사용: node scripts/screenshot.js out/demo/dashboard.html docs/screenshots
const { chromium } = require('playwright');
const path = require('path');
(async () => {
  const [,, htmlPath, outDir] = process.argv;
  const browser = await chromium.launch();
  const page = await browser.newPage({ viewport: { width: 1280, height: 900 }, deviceScaleFactor: 2 });
  const errors = [];
  page.on('pageerror', e => errors.push(e.message));
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  await page.goto('file://' + path.resolve(htmlPath));
  await page.addStyleTag({ content: '.appbar{position:static!important}.card{animation:none!important}' });
  await page.waitForTimeout(300);
  const scenarios = await page.$$eval('nav.tabs .tab', ts => ts.map(t => t.dataset.id));
  const shots = { kpi: '#sec-summary', board: '#sec-board', ranking: '#sec-rank', charts: '#sec-charts', gantt: '#sec-gantt' };
  for (const sid of scenarios) {
    await page.click(`.tab[data-id="${sid}"]`);
    await page.waitForTimeout(200);
    await page.screenshot({ path: `${outDir}/${sid}_full.png`, fullPage: true });
    for (const [name, sel] of Object.entries(shots)) {
      const el = await page.$(sel);
      if (el) await el.screenshot({ path: `${outDir}/${sid}_${name}.png` });
    }
    await page.click('#board-toggle [data-mode="matrix"]'); await page.waitForTimeout(150);
    await (await page.$('#sec-board')).screenshot({ path: `${outDir}/${sid}_board_matrix.png` });
    await page.click('#board-toggle [data-mode="cards"]'); await page.waitForTimeout(150);
  }
  await page.click('.tab[data-id="typhoon"]');
  await page.waitForTimeout(200);
  // 근거 펼침 장면
  await page.$$eval('#rank-body details', ds => ds.slice(0, 2).forEach(d => d.open = true));
  await page.waitForTimeout(100);
  const rk = await page.$('#sec-rank');
  await rk.screenshot({ path: `${outDir}/typhoon_ranking_open.png` });
  // 계약 상세 서랍: 항목별(기본) → 전문
  await page.click('#sec-board .foot [data-open="H"]'); await page.waitForTimeout(450); await page.screenshot({ path: `${outDir}/typhoon_drawer.png`, clip: { x: 0, y: 0, width: 1280, height: 900 } });
  await page.click('#drawer-body [data-tab="text"]'); await page.waitForTimeout(250); await page.screenshot({ path: `${outDir}/typhoon_drawer_text.png`, clip: { x: 0, y: 0, width: 1280, height: 900 } }); await page.click('#drawer-close'); await page.waitForTimeout(300);
  // 호버 툴팁 장면
  const bar = await page.$('#g-base .bar rect');
  if (bar) { const b = await bar.boundingBox(); await page.mouse.move(b.x + b.width / 2, b.y + b.height / 2); await page.waitForTimeout(150);
    const g = await page.$('#sec-gantt'); await g.screenshot({ path: `${outDir}/typhoon_gantt_hover.png` }); }
  await browser.close();
  console.log('scenarios:', scenarios.join(','), '| page errors:', errors.length ? errors.join(' | ') : 'none');
})();
