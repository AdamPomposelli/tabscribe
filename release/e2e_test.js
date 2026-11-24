#!/usr/bin/env node
// End-to-end test of a packaged Tabscribe.app against locally served release assets:
// empty data folder, no Homebrew on PATH, clicks Install in the real setup screen, follows
// the progress, lets the app open, transcribes a song through the installed engine.
//
//   python3 release/serve_local.py assets-2026.11.1 --drop-after 150 &
//   node release/e2e_test.js --app desktop/dist/mac-arm64/Tabscribe.app --audio bench/YeuEm.mp3 --out /tmp/e2e
//   node release/e2e_test.js --app desktop/dist/win-unpacked/Tabscribe.exe ...   (Windows)
//
// Screenshots (setup, mid-download, app) and a JSON report land in --out.
const { spawn, execFileSync } = require('child_process')
const fs = require('fs')
const path = require('path')

const arg = (k, d) => { const i = process.argv.indexOf(`--${k}`); return i > 0 ? process.argv[i + 1] : d }
const APP = path.resolve(arg('app', 'desktop/dist/mac-arm64/Tabscribe.app'))
const AUDIO = path.resolve(arg('audio', 'bench/YeuEm.mp3'))
const OUT = path.resolve(arg('out', '/tmp/tabscribe-e2e'))
const HOME_DIR = path.join(OUT, 'data')
const ASSETS = arg('assets', 'http://127.0.0.1:8899/download/')
const DEBUG_PORT = 9333
const TITLES = { bs_roformer_sw: 'BS-RoFormer', demucs: 'Demucs', muscriptor: 'MuScriptor' }
const sleep = ms => new Promise(r => setTimeout(r, ms))
const log = (...a) => console.log(new Date().toISOString().slice(11, 19), ...a)
const report = { steps: [] }
const step = (name, data = {}) => { report.steps.push({ name, t: Date.now(), ...data }); log(name, Object.keys(data).length ? JSON.stringify(data) : '') }

class Page {
  constructor(ws) {
    this.ws = ws; this.id = 0; this.pending = new Map()
    ws.onmessage = m => { const d = JSON.parse(m.data); this.pending.get(d.id)?.resolve(d); this.pending.delete(d.id) }
    // the page navigating away (setup -> app) closes the socket: fail pending calls instead of hanging
    ws.onclose = () => { for (const p of this.pending.values()) p.reject(new Error('page closed')); this.pending.clear(); this.closed = true }
  }
  static async open(urlPrefix, timeout = 60000) {
    const t0 = Date.now()
    for (;;) {
      try {
        const list = await (await fetch(`http://127.0.0.1:${DEBUG_PORT}/json`)).json()
        const t = list.find(x => x.type === 'page' && x.url.startsWith(urlPrefix))
        if (t) {
          const ws = new WebSocket(t.webSocketDebuggerUrl)
          await new Promise((res, rej) => { ws.onopen = res; ws.onerror = rej })
          return new Page(ws)
        }
      } catch { /* app still starting */ }
      if (Date.now() - t0 > timeout) throw new Error(`no page ${urlPrefix}`)
      await sleep(500)
    }
  }
  send(method, params = {}) {
    const id = ++this.id
    if (this.closed) return Promise.reject(new Error('page closed'))
    return new Promise((resolve, reject) => {
      // a call racing a navigation may never get an answer
      const t = setTimeout(() => { this.pending.delete(id); reject(new Error(`${method} timed out`)) }, 15000)
      this.pending.set(id, { resolve: d => { clearTimeout(t); resolve(d) }, reject: e => { clearTimeout(t); reject(e) } })
      this.ws.send(JSON.stringify({ id, method, params }))
    })
  }
  async eval(expr) {
    const r = await this.send('Runtime.evaluate', { expression: expr, awaitPromise: true, returnByValue: true })
    if (r.result?.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description || 'eval failed')
    return r.result?.result?.value
  }
  async shot(name) {
    const r = await this.send('Page.captureScreenshot', { format: 'png' })
    fs.writeFileSync(path.join(OUT, name), Buffer.from(r.result.data, 'base64'))
    step('screenshot', { file: name })
  }
  close() { this.ws.close() }
}

async function main() {
  const keepAlive = setInterval(() => {}, 1000)  // a pending CDP call alone doesn't keep node running
  fs.rmSync(OUT, { recursive: true, force: true })
  fs.mkdirSync(OUT, { recursive: true })
  const WIN = process.platform === 'win32'
  const exe = WIN ? APP : path.join(APP, 'Contents', 'MacOS', 'Tabscribe')
  // a "clean machine": no Homebrew/pyenv/system Python on PATH, no Python env vars, empty data folder
  const sysroot = process.env.SystemRoot || 'C:\\Windows'
  const env = WIN
    ? { SystemRoot: sysroot, windir: sysroot, PATH: `${sysroot}\\System32;${sysroot}`, TEMP: process.env.TEMP, TMP: process.env.TMP,
        USERPROFILE: process.env.USERPROFILE, APPDATA: process.env.APPDATA, LOCALAPPDATA: process.env.LOCALAPPDATA,
        TABSCRIBE_DATA_DIR: HOME_DIR, TABSCRIBE_ASSETS_URL: ASSETS, HF_TOKEN: '' }
    : { HOME: process.env.HOME, USER: process.env.USER, TMPDIR: process.env.TMPDIR, PATH: '/usr/bin:/bin:/usr/sbin:/sbin',
        TABSCRIBE_DATA_DIR: HOME_DIR, TABSCRIBE_ASSETS_URL: ASSETS, HF_TOKEN: '' }
  const app = spawn(exe, [`--remote-debugging-port=${DEBUG_PORT}`], { env, stdio: ['ignore', 'pipe', 'pipe'] })
  app.stdout.on('data', d => fs.appendFileSync(path.join(OUT, 'electron.log'), d))
  app.stderr.on('data', d => fs.appendFileSync(path.join(OUT, 'electron.log'), d))
  const t0 = Date.now()
  try {
    const setup = await Page.open('tabscribe://app/setup.html')
    await sleep(1500)
    const summary = await setup.eval(`[...document.querySelectorAll('.comp')].map(c => c.querySelector('.comp-name').textContent + ' | ' + c.querySelector('.comp-size').textContent + ' | checked=' + c.querySelector('input').checked)`)
    const totals = await setup.eval(`[...document.querySelectorAll('.sum-grid > div')].map(d => d.innerText.replace(/\\n/g, ': '))`)
    step('setup screen', { components: summary, totals })
    await setup.shot('1-setup.png')
    await setup.eval(`document.querySelector('.lic').classList.add('open')`)
    await sleep(300)
    await setup.shot('1b-licence-tooltip.png')
    await setup.eval(`document.querySelector('.lic').classList.remove('open')`)
    // --toggle id1,id2: flip optional components (e.g. skip one fetched from Hugging Face on a slow line)
    for (const id of (arg('toggle', '') || '').split(',').filter(Boolean)) {
      const i = await setup.eval(`[...document.querySelectorAll('.comp')].findIndex(c => c.innerText.includes(${JSON.stringify(TITLES[id] || id)}))`)
      if (i >= 0) await setup.eval(`document.querySelectorAll('.comp input')[${i}].click()`)
      step('toggled', { id, index: i })
    }
    await sleep(300)
    await setup.eval(`[...document.querySelectorAll('button')].find(b => /Install|Resume/.test(b.textContent)).click()`)
    step('clicked install')
    let shotTaken = false, lastLine = ''
    const samples = []
    for (;;) {
      await sleep(2000)
      let line
      try {
        if ((await setup.eval('location.protocol')) !== 'tabscribe:') break  // same target, now showing the app
        line = await setup.eval(`(document.querySelector('.prog-block') ? [...document.querySelectorAll('.prog-line')].map(e => e.innerText.replace(/\\n/g, ' ')).join(' | ') : (document.querySelector('.setup-msg')?.innerText || 'idle'))`)
      } catch (e) {
        if (setup.closed) break
        continue  // evaluated during a navigation: ask again
      }
      if (line !== lastLine) { log('  ', line); lastLine = line; samples.push(line) }
      if (/error|failed|denied/i.test(line) && !/retrying/i.test(line)) throw new Error('install failed: ' + line)
      if (!shotTaken && /Downloading/.test(line) && /\d+%/.test(line) && !/ 0%/.test(line)) { await setup.shot('2-progress.png'); shotTaken = true }
      if (Date.now() - t0 > 60 * 60 * 1000) throw new Error('install timeout')
    }
    report.progress_samples = samples.filter((_, i) => i % 5 === 0).slice(0, 60)
    step('install finished', { seconds: Math.round((Date.now() - t0) / 1000) })
    setup.close()

    const page = await Page.open('http://127.0.0.1:', 240000)
    for (let i = 0; i < 480 && !/^http:\/\/127/.test(await page.eval('location.href').catch(() => '')); i++) await sleep(500)
    const base = await page.eval('location.origin')
    step('app opened', { base })
    const engines = await (await fetch(`${base}/api/engines`)).json()
    step('engines', engines)
    // the engine must not touch Homebrew or the checkout's venvs (macOS: lsof; Windows: the
    // listening process must be the runtime's python.exe)
    if (WIN) {
      const port = new URL(base).port
      const pid = execFileSync('powershell', ['-NoProfile', '-Command',
        `(Get-NetTCPConnection -LocalPort ${port} -State Listen).OwningProcess | Select-Object -First 1`]).toString().trim()
      const exePath = execFileSync('powershell', ['-NoProfile', '-Command', `(Get-Process -Id ${pid}).Path`]).toString().trim()
      step('engine process', { pid, python: exePath })
      if (!exePath.toLowerCase().startsWith(path.join(HOME_DIR, 'runtime').toLowerCase())) throw new Error('engine is not the installed runtime: ' + exePath)
    } else {
      const pid = execFileSync('/usr/sbin/lsof', ['-ti', `tcp:${new URL(base).port}`, '-sTCP:LISTEN']).toString().trim().split('\n')[0]
      const libs = execFileSync('/usr/sbin/lsof', ['-p', pid]).toString()
      const leaks = libs.split('\n').filter(l => /\/opt\/homebrew|\/usr\/local\/|fretscribe\/\.venv/.test(l))
      step('engine process', { pid, python: (libs.match(/\S+\/runtime\/bin\/python3\.11/) || [])[0], foreign_files: leaks.length })
      if (leaks.length) throw new Error('engine uses files outside the app:\n' + leaks.slice(0, 5).join('\n'))
    }

    const fd = new FormData()
    fd.append('file', new Blob([fs.readFileSync(AUDIO)]), path.basename(AUDIO))
    fd.append('engine', 'auto')
    const meta = await (await fetch(`${base}/api/projects`, { method: 'POST', body: fd })).json()
    step('uploaded', { id: meta.id, title: meta.title })
    const t1 = Date.now()
    let st
    for (;;) {
      await sleep(3000)
      st = await (await fetch(`${base}/api/projects/${meta.id}/status`)).json()
      if (st.state === 'done' || st.state === 'error') break
      log('   transcribing:', st.stage, st.progress, st.message || '')
      if (Date.now() - t1 > 30 * 60 * 1000) throw new Error('transcription timeout')
    }
    if (st.state !== 'done') throw new Error('transcription failed: ' + st.message)
    const proj = await (await fetch(`${base}/api/projects/${meta.id}`)).json()
    const r = proj.result
    step('transcribed', { seconds: Math.round((Date.now() - t1) / 1000), engine: r.engine, notes: r.notes.length, key: r.key?.name, tempo: r.tempo,
      chords: [...new Set(r.chords.map(c => c.name))].slice(0, 12), bars_per: r.beats_per_bar })
    if (process.argv.includes('--separate')) {
      const fd2 = new FormData()
      fd2.append('file', new Blob([fs.readFileSync(AUDIO)]), 'isolated-' + path.basename(AUDIO))
      fd2.append('engine', 'auto'); fd2.append('separate', 'true')
      const m2 = await (await fetch(`${base}/api/projects`, { method: 'POST', body: fd2 })).json()
      const t2 = Date.now()
      let s2
      for (;;) {
        await sleep(3000)
        s2 = await (await fetch(`${base}/api/projects/${m2.id}/status`)).json()
        if (s2.state === 'done' || s2.state === 'error') break
        if (Date.now() - t2 > 30 * 60 * 1000) throw new Error('separation timeout')
      }
      if (s2.state !== 'done') throw new Error('transcription with guitar isolation failed: ' + s2.message)
      const r2 = (await (await fetch(`${base}/api/projects/${m2.id}`)).json()).result
      step('transcribed with guitar isolation', { seconds: Math.round((Date.now() - t2) / 1000), separation: engines.separation?.label, notes: r2.notes.length })
    }
    await page.eval(`location.reload()`).catch(() => {})
    await sleep(6000)
    await page.shot('3-app.png').catch(e => step('screenshot skipped', { error: e.message }))  // a hidden window may not paint
    report.ok = true
  } catch (e) {
    report.ok = false
    report.error = String(e.stack || e)
    console.error(e)
  } finally {
    fs.writeFileSync(path.join(OUT, 'report.json'), JSON.stringify(report, null, 2))
    app.kill('SIGTERM')
    await sleep(3000)
  }
  process.exit(report.ok ? 0 : 1)
}

main()
