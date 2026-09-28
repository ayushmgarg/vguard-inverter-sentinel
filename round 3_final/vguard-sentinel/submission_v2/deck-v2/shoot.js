const puppeteer = require('puppeteer-core');
const path = require('path');
const OUT = process.argv[2];
const URL = 'file:///' + 'C:/AyushGarg/projects/hackathons/v-guard_2026/round 3_final/vguard-sentinel-main/Sentinel-Live.html'.replace(/ /g, '%20');
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const browser = await puppeteer.launch({
    executablePath: 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe',
    headless: 'new',
    args: ['--use-angle=d3d11', '--enable-gpu', '--ignore-gpu-blocklist', '--window-size=1920,1080'],
  });
  const page = await browser.newPage();
  await page.setViewport({ width: 1920, height: 1080, deviceScaleFactor: 1 });
  page.on('console', (m) => { if (m.type() === 'error') console.log('ERR', m.text()); });
  await page.evaluateOnNewDocument(() => localStorage.setItem('sentinel.tab', 'village'));
  await page.goto(URL, { waitUntil: 'load' });
  await sleep(4000);
  const snap = async (name) => { await page.screenshot({ path: path.join(OUT, name + '.png') }); console.log('shot', name); };
  const ev = (fn, ...a) => page.evaluate(fn, ...a);
  const clickText = (sel, txt) => ev((s, t) => { const b = [...document.querySelectorAll(s)].find((x) => x.textContent.trim().includes(t)); if (b) b.click(); return !!b; }, sel, txt);

  // ---- village ----
  await ev(() => { const s = window.__sentinel; s.engine.jumpTo(s.village, 19 * 60 + 40); s.village.bus.emit(); });
  await sleep(3500); await snap('v_overview_outage');
  await ev(() => { const s = window.__sentinel; s.engine.jumpTo(s.village, 22 * 60 + 12); s.village.bus.emit(); });
  await sleep(3000); await snap('v_home6_dark');
  await clickText('button', 'X-ray'); await sleep(3000); await snap('v_xray');
  await clickText('button', 'X-ray'); await sleep(800);
  await ev(() => document.querySelectorAll('.roster-row')[0].click()); await sleep(3500); await snap('v_home1_inside');
  await clickText('button', 'Power corner'); await sleep(3500); await snap('v_home1_corner');
  await ev(() => document.querySelector('.hp-head .icon-btn').click()); await sleep(800);
  await ev(() => document.querySelectorAll('.roster-row')[5].click()); await sleep(3500); await snap('v_home6_inside');
  await ev(() => document.querySelector('.hp-head .icon-btn').click()); await sleep(500);

  // ---- bench ----
  await clickText('.tab', 'Inverter'); await sleep(4000);
  await snap('b_overview_mains');
  await ev(() => { const s = window.__sentinel; const h = s.bench.houses[0]; s.engine.forceAppliance(h, 'iron', true); });
  await sleep(1500);
  await ev(() => { const s = window.__sentinel; s.engine.setGrid(s.bench, 'off'); });
  await sleep(700); await snap('b_transfer_slowmo');
  await sleep(3500); await snap('b_battery_mode');
  await clickText('.viewbar button', 'Relay'); await sleep(2500); await snap('b_relay');
  await clickText('.viewbar button', 'Sentinel board'); await sleep(2500); await snap('b_board');
  await clickText('.viewbar button', 'Inside'); await sleep(2500); await snap('b_inside');
  await ev(() => { const s = window.__sentinel; const h = s.bench.houses[0]; h.bat.soc = 0.38; s.engine.evaluate(s.bench, h, 'bench'); });
  await clickText('.viewbar button', 'Contactors'); await sleep(3000); await snap('b_shed');
  await clickText('.viewbar button', 'Overview'); await sleep(2500); await snap('b_overview_shed');
  await ev(() => { const s = window.__sentinel; s.engine.resetMcu(s.bench, s.bench.houses[0]); });
  await sleep(600); await snap('b_failsafe_reset');
  await clickText('.viewbar button', 'X-ray'); await sleep(2500); await snap('b_xray');

  // ---- engineering ----
  await clickText('.tab', 'Engineering'); await sleep(1500); await snap('e_top');
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
