// Captures the real Tabscribe UI for the README demo (see brand/demo/README.md).
// Needs a backend serving the built frontend on demo data (invented titles, no real songs):
//   TABSCRIBE_DATA=<demo data> .venv/bin/python -m uvicorn tabscribe.server:app --app-dir backend --port 8790
//
//   node brand/demo/capture.mjs <playwright dir> <out dir> <audio file> [base url]
//
// Every PNG is a real screenshot, 1920×1080 at device scale 2, dark. boxes.json says where the
// elements the camera aims at are, in CSS px.
import { createRequire } from 'node:module';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';

const [playwrightDir, out, audio, base = 'http://127.0.0.1:8790'] = process.argv.slice(2);
if (!playwrightDir || !out || !audio) throw new Error('usage: capture.mjs <playwright dir> <out dir> <audio file> [base url]');
const { chromium } = createRequire(join(playwrightDir, 'package.json'))('playwright');
mkdirSync(out, { recursive: true });

const browser = await chromium.launch({ channel: 'chrome', args: ['--autoplay-policy=no-user-gesture-required'] });
const context = await browser.newContext({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 2, colorScheme: 'dark', locale: 'en-US' });
await context.addInitScript(() => {
  if (!localStorage.getItem('fs.panelWidth')) localStorage.setItem('fs.panelWidth', '320');
});
const page = await context.newPage();
const shot = (name) => page.screenshot({ path: join(out, `${name}.png`), animations: 'disabled' });
const settle = (ms = 900) => page.waitForTimeout(ms);
const boxes = {};
const box = async (name, locator) => {
  const b = await locator.first().boundingBox();
  if (!b) throw new Error(`capture: could not find ${name}`);
  boxes[name] = b;
  return b;
};
const union = (...bs) => {
  const x = Math.min(...bs.map((b) => b.x)), y = Math.min(...bs.map((b) => b.y));
  return { x, y, width: Math.max(...bs.map((b) => b.x + b.width)) - x, height: Math.max(...bs.map((b) => b.y + b.height)) - y };
};
const scoreReady = async () => {
  await page.locator('.at-surface svg, .at-surface canvas').first().waitFor({ timeout: 60_000 });
  await page.getByText('Rendering score…').waitFor({ state: 'detached', timeout: 60_000 }).catch(() => {});
  await settle(1500);
};

// 1. A project: score + tab, chord boxes, the piano roll.
await page.goto(base);
await page.getByRole('button', { name: 'Morning Light' }).first().click();
await scoreReady();
// play a few seconds so the cursor and the falling notes are mid-song, then pause
await page.getByTitle('Play / pause (space)').click();
await settle(6500);
await page.getByTitle('Play / pause (space)').click();
await settle(800);
await box('score', page.locator('.score-scroll, .score-wrap').first());
await box('panel', page.locator('.panel'));
await box('capo', page.getByText('is the easiest position').locator('xpath=..'));
await box('roll', page.locator('.pianoroll'));
await box('transport', page.locator('.transport').first());
await box('seg', page.getByTitle('Play the original recording').locator('xpath=..'));
const diagrams = await page.locator('.at-surface').first().boundingBox();
boxes.firstSystem = { x: diagrams.x, y: diagrams.y, width: Math.min(diagrams.width, 1200), height: 420 };
await shot('score');

// 2. The original recording, synced.
await page.getByTitle('Play the original recording').click();
await settle(1500);
await shot('original');
await page.getByTitle('Play the transcription').click();
await settle(1500);

// 3. Guitar sounds.
const soundBtn = page.locator('.dropdown-btn', { hasText: 'Guitar sound' });
await soundBtn.click();
await settle(500);
await box('soundMenu', soundBtn.locator('xpath=..').locator('.menu'));
await box('soundBtn', soundBtn);
await shot('sounds');
await page.keyboard.press('Escape');
await page.mouse.click(1700, 600);
await settle(400);

// 4. Export.
await page.getByRole('button', { name: /^Download/ }).first().click();
await settle(500);
const dl = page.locator('.menu').filter({ hasText: /Guitar Pro|MIDI/ }).first();
await box('downloadMenu', dl);
await shot('download');
await page.keyboard.press('Escape');
await page.mouse.click(1700, 600);
await settle(400);

// 5. Settings: the pipeline, step by step.
await page.getByTitle('Settings').click();
await page.locator('.pipe').waitFor();
await settle(600);
await box('pipeline', page.locator('.pipe-wrap'));
await shot('pipeline');
await page.keyboard.press('Escape');
await settle(400);

// 6. A new project: trim, what's in the recording, ready, then the real job running.
await page.getByRole('button', { name: 'New project' }).first().click();
await page.locator('.onb input[type=file]').setInputFiles(audio);
await page.getByText('Trim your audio').waitFor();
await page.locator('.trim-handle').first().waitFor();
await settle(2500);
// pull the handles in a little, the way someone skips an intro and an outro
const handles = page.locator('.trim-handle');
for (const [i, dx] of [[0, 120], [1, -160]]) {
  const h = await handles.nth(i).boundingBox();
  await page.mouse.move(h.x + h.width / 2, h.y + h.height / 2);
  await page.mouse.down();
  await page.mouse.move(h.x + h.width / 2 + dx, h.y + h.height / 2, { steps: 8 });
  await page.mouse.up();
  await settle(300);
}
await box('trim', page.locator('.trim, .trimmer, .onb-body').filter({ has: page.locator('.trim-handle') }).last());
await box('onbTitle', page.getByText('Trim your audio'));
await shot('onb-trim');
await page.getByRole('button', { name: 'Continue' }).click();
await page.getByText('What’s in your recording?').waitFor();
await settle(700);
await box('cards', page.locator('.onb-cards'));
await box('bandCard', page.locator('.onb-card').nth(1));
await shot('onb-source');
await page.locator('.onb-card').nth(1).click();
await page.getByText('Ready to transcribe').waitFor();
await settle(700);
await page.locator('.onb-input').first().fill('Paper Boats');
await box('summary', page.locator('.onb-summary'));
await shot('onb-ready');
await page.getByRole('button', { name: 'Start transcription' }).click();
await page.locator('.proc-card').waitFor({ timeout: 60_000 });
// wait until the job is past the first two stages, so the tracker shows progress
await page.waitForFunction(() => document.querySelectorAll('.proc-step.done').length >= 2, null, { timeout: 300_000 });
await settle(1200);
await box('proc', page.locator('.proc-card'));
await shot('processing');

writeFileSync(join(out, 'boxes.json'), JSON.stringify(boxes, null, 2));
console.log(JSON.stringify(boxes, null, 2));
await browser.close();
