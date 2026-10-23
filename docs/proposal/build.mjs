// proposal.html → proposal.pdf (+ preview PNGs). 실행: node docs/proposal/build.mjs
import { chromium } from '/opt/node22/lib/node_modules/playwright/index.mjs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import fs from 'node:fs';

const here = path.dirname(fileURLToPath(import.meta.url));
const html = path.join(here, 'proposal.html');
const pdf = path.join(here, 'proposal.pdf');
const previewDir = path.join(here, 'preview');
fs.mkdirSync(previewDir, { recursive: true });

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 794, height: 1123 }, deviceScaleFactor: 1 });
await page.goto('file://' + html, { waitUntil: 'load' });
await page.evaluate(() => document.fonts.ready);
await page.emulateMedia({ media: 'print' });
await page.pdf({ path: pdf, format: 'A4', printBackground: true, preferCSSPageSize: true,
  margin: { top: 0, right: 0, bottom: 0, left: 0 } });

// 페이지별 미리보기 PNG와 넘침 검사
const report = await page.evaluate(() => {
  const out = [];
  document.querySelectorAll('.page').forEach((p, i) => {
    const r = p.getBoundingClientRect();
    const footer = p.querySelector('.footer');
    const fTop = footer ? footer.getBoundingClientRect().top : r.bottom;
    let maxBottom = 0;
    p.querySelectorAll(':scope > *:not(.footer)').forEach((el) => {
      const b = el.getBoundingClientRect().bottom;
      if (b > maxBottom) maxBottom = b;
    });
    out.push({ page: i + 1, height: Math.round(r.height), contentBottom: Math.round(maxBottom - r.top),
      footerTop: Math.round(fTop - r.top), overflow: maxBottom > fTop - 2 });
  });
  return out;
});
for (const row of report) {
  const el = (await page.$$('.page'))[row.page - 1];
  await el.screenshot({ path: path.join(previewDir, `page-${String(row.page).padStart(2, '0')}.png`) });
}
console.table(report);
await browser.close();
console.log('wrote', pdf);
