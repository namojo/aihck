// 데모 UI를 자동 조작해 스크린샷(기획서 화면용)과 녹화본을 만든다.
// 사용: RFPHARNESS_DEMO_DELAY=0.8 python -m rfpharness serve --port 8787 --llm mock &  node docs/demo/record.mjs
import { chromium } from '/opt/node22/lib/node_modules/playwright/index.mjs';
import { mkdirSync, existsSync, readdirSync, renameSync } from 'node:fs';
import { execFileSync } from 'node:child_process';
import path from 'node:path';

const BASE = process.env.DEMO_URL || 'http://127.0.0.1:8787';
const IMG = 'docs/proposal/img';
const VID = 'docs/demo';
mkdirSync(IMG, { recursive: true }); mkdirSync(VID, { recursive: true });

const browser = await chromium.launch();
const ctx = await browser.newContext({ viewport: { width: 1440, height: 1000 }, deviceScaleFactor: 2, recordVideo: { dir: VID, size: { width: 1440, height: 1000 } } });
const page = await ctx.newPage();
const shot = (name) => page.screenshot({ path: `${IMG}/${name}.png` });
const pause = (ms) => page.waitForTimeout(ms);
const toResults = () => page.evaluate(() => document.querySelector('#tiles').scrollIntoView({ block: 'start' }));

await page.goto(BASE);
await page.waitForSelector('#sample:not([disabled])');
await pause(1200);
await shot('screen-0-intake');

await page.click('#sample');
await page.waitForSelector('#progress:not(.hidden)');
await page.waitForSelector('#st-extract.running, #st-extract.done', { timeout: 20000 });
await pause(300);
await shot('screen-1-upload');            // 진행 중(파싱 완료, 추출 진행)
await page.waitForSelector('#results:not(.hidden)', { timeout: 60000 });
await pause(800);
await shot('screen-1b-progress-done');
await toResults();
await pause(300);

// 요구사항 탭: 본문(숨은 요구사항) 필터 → 행 클릭 → 원문 드로어
await page.click('.chip[data-src="prose"]');
await pause(400);
const row = page.locator('#pane-req tr.clickable').nth(1);
await row.click();
await page.waitForSelector('#drawer.open');
await toResults();
await pause(600);
await shot('screen-2-requirements');
await page.click('#drawer .close');
await page.click('.chip[data-src="all"]');
await pause(300);
await shot('screen-2b-requirements-all');

// 위험 조항 탭
await page.click('.tab[data-tab="risk"]');
await toResults();
await pause(600);
await shot('screen-3-risks');

// 목차 탭
await page.click('.tab[data-tab="toc"]');
await toResults();
await pause(600);
await shot('screen-4-toc');

// 커버리지 탭
await page.click('.tab[data-tab="cov"]');
await toResults();
await pause(600);
await shot('screen-4b-coverage');
await pause(1500);

await ctx.close();
await browser.close();

// webm → mp4 (Playwright 번들 ffmpeg)
const webm = readdirSync(VID).filter(f => f.endsWith('.webm')).map(f => path.join(VID, f)).sort((a, b) => a < b ? 1 : -1)[0];
if (webm) {
  const ffmpegDir = '/opt/pw-browsers';
  const cand = existsSync(ffmpegDir) ? readdirSync(ffmpegDir).filter(d => d.startsWith('ffmpeg')) : [];
  const ffmpeg = cand.length ? path.join(ffmpegDir, cand[0], 'ffmpeg-linux') : 'ffmpeg';
  try {
    execFileSync(ffmpeg, ['-y', '-loglevel', 'error', '-i', webm, '-vf', 'scale=1280:-2', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '28', path.join(VID, 'demo.mp4')]);
    renameSync(webm, path.join(VID, 'demo.webm'));
    console.log('video: docs/demo/demo.mp4');
  } catch (e) {
    console.log('mp4 변환 실패, webm만 남김:', e.message);
    renameSync(webm, path.join(VID, 'demo.webm'));
  }
}
console.log('screenshots:', readdirSync(IMG).join(', '));
