// Tabscribe component installer: downloads the files listed in manifest.json (built by
// release/build_assets.py, shipped inside the app) into the app's data folder.
// Resumable (HTTP Range on a .part file), checksummed (sha256 + size), one file at a time,
// automatic retries with backoff, archives streamed into `tar` and swapped in atomically.
const { EventEmitter, once } = require('events')
const { spawn } = require('child_process')
const crypto = require('crypto')
const fs = require('fs')
const fsp = require('fs/promises')
const os = require('os')
const path = require('path')

const RECEIPTS = 'installed.json'
const SPACE_MARGIN = 300 * 1024 * 1024
const RETRIES = 5

class CancelledError extends Error { constructor() { super('Cancelled'); this.cancelled = true } }

class Installer extends EventEmitter {
  /** @param {{manifest: object, home: string, baseUrl?: string}} o */
  constructor({ manifest, home, baseUrl }) {
    super()
    this.manifest = manifest
    this.home = home
    this.baseUrl = baseUrl || manifest.base_url
    this.downloads = path.join(home, 'downloads')
    this.busy = false
    this.abort = null
    this.lastProgress = null
  }

  // ------------------------------------------------------------------ state
  receipts() {
    try { return JSON.parse(fs.readFileSync(path.join(this.home, RECEIPTS), 'utf8')) } catch { return { components: {} } }
  }

  saveReceipt(c, extra = {}) {
    const r = this.receipts()
    r.components[c.id] = { version: this.manifest.version, files: Object.fromEntries(c.files.map(f => [f.name, f.sha256])), installed: new Date().toISOString(), ...extra }
    fs.mkdirSync(this.home, { recursive: true })
    fs.writeFileSync(path.join(this.home, RECEIPTS) + '.tmp', JSON.stringify(r, null, 2))
    fs.renameSync(path.join(this.home, RECEIPTS) + '.tmp', path.join(this.home, RECEIPTS))
  }

  dropReceipt(id) {
    const r = this.receipts()
    delete r.components[id]
    fs.writeFileSync(path.join(this.home, RECEIPTS), JSON.stringify(r, null, 2))
  }

  /** Quick check (startup): receipt matches the manifest and the files are where they should be. */
  isInstalled(c) {
    const rec = this.receipts().components[c.id]
    if (!rec || c.files.some(f => rec.files?.[f.name] !== f.sha256)) return false
    if (c.kind === 'archive') return fs.existsSync(path.join(this.home, c.dest, 'tabscribe-runtime.json'))
    return c.files.every(f => { try { return fs.statSync(path.join(this.home, f.dest)).size === f.size } catch { return false } })
  }

  partialBytes(c) {
    if (this.isInstalled(c)) return 0
    return c.files.reduce((s, f) => {
      try { return s + Math.min(fs.statSync(this.partPath(f)).size, f.size) } catch { return s + (this.finished(f) ? f.size : 0) }
    }, 0)
  }

  finished(f) { return fs.existsSync(this.partPath(f) + '.ok') }

  freeBytes() {
    let dir = this.home
    while (!fs.existsSync(dir)) dir = path.dirname(dir)
    const s = fs.statfsSync(dir)
    return s.bavail * s.bsize
  }

  /** Bytes still needed on disk to install `ids` (downloads + unpacked archive, minus what's already there). */
  spaceNeeded(ids) {
    return this.manifest.components.filter(c => ids.includes(c.id) && !this.isInstalled(c))
      .reduce((s, c) => s + (c.download_size - this.partialBytes(c)) + (c.kind === 'archive' ? c.installed_size : 0), 0)
  }

  status() {
    const comps = this.manifest.components.map(c => ({
      id: c.id, name: c.name, kind: c.kind, description: c.description, required: !!c.required, default: c.default !== false,
      licence: c.licence, licence_url: c.licence_url || null, auth: c.auth || null,
      download_size: c.download_size, installed_size: c.installed_size,
      installed: this.isInstalled(c), partial: this.partialBytes(c),
    }))
    return {
      version: this.manifest.version, home: this.home, free: this.freeBytes(), margin: SPACE_MARGIN,
      ready: comps.every(c => !c.required || c.installed), busy: this.busy, components: comps,
      hfTokenFound: !!readHfToken(), lastProgress: this.lastProgress,
    }
  }

  // ------------------------------------------------------------------ install
  partPath(f) { return path.join(this.downloads, f.name + '.part') }
  urlOf(f) { return f.url || new URL(encodeURIComponent(f.name), this.baseUrl).href }

  cancel() { if (this.abort) this.abort.abort() }

  /** Install (or repair) components. Resolves when done; progress through 'progress' events. */
  async install(ids, { hfToken, force = false } = {}) {
    if (this.busy) throw new Error('An installation is already running')
    const todo = this.manifest.components.filter(c => ids.includes(c.id) && (force || !this.isInstalled(c)))
    const needed = this.spaceNeeded(todo.map(c => c.id))
    const free = this.freeBytes()
    if (needed + SPACE_MARGIN > free) {
      throw new Error(`Not enough disk space: ${fmt(needed + SPACE_MARGIN)} needed, ${fmt(free)} available on this disk.`)
    }
    this.busy = true
    this.abort = new AbortController()
    const signal = this.abort.signal
    fs.mkdirSync(this.downloads, { recursive: true })
    const total = todo.reduce((s, c) => s + c.download_size, 0)
    const p = { phase: 'download', component: null, file: null, fileBytes: 0, fileSize: 0, done: 0, total, speed: 0, eta: null,
      index: 0, count: todo.reduce((s, c) => s + c.files.length, 0) }
    const meter = speedMeter()
    let lastEmit = 0
    const emit = (force) => {
      const now = Date.now()
      if (!force && now - lastEmit < 100) return
      lastEmit = now
      p.speed = meter.rate()
      p.eta = p.speed > 0 ? Math.round((p.total - p.done) / p.speed) : null
      this.lastProgress = { ...p }
      this.emit('progress', this.lastProgress)
    }
    try {
      for (const c of todo) {
        p.component = c.id
        if (force) { this.dropReceipt(c.id); for (const f of c.files) rmQuiet(this.partPath(f) + '.ok') }
        const token = c.auth === 'huggingface' ? (hfToken || readHfToken()) : null
        if (c.auth === 'huggingface' && !token) throw new Error(`${c.name} needs a Hugging Face access token (accept the licence on ${c.licence_url}).`)
        for (const f of c.files) {
          p.index++
          p.file = f.name; p.fileSize = f.size; p.fileBytes = 0; p.phase = 'download'
          const base = p.done
          await this.fetchFile(f, token, signal, (n, net = true) => {
            if (net) meter.add(n - p.fileBytes)
            p.fileBytes = n; p.done = base + n; emit()
          })
          p.done = base + f.size
          emit(true)
        }
        if (c.kind === 'archive') {
          p.phase = 'extract'; p.file = null; p.fileBytes = 0; p.fileSize = c.download_size; emit(true)
          await this.extract(c, signal, (n) => { p.fileBytes = n; emit() })
        } else {
          for (const f of c.files) {
            const dest = path.join(this.home, f.dest)
            fs.mkdirSync(path.dirname(dest), { recursive: true })
            fs.renameSync(this.partPath(f), dest)
            rmQuiet(this.partPath(f) + '.ok')
          }
        }
        this.saveReceipt(c)
        this.emit('component', c.id)
      }
      p.phase = 'done'; p.file = null; emit(true)
    } catch (e) {
      if (signal.aborted) throw new CancelledError()
      throw e
    } finally {
      this.busy = false
      this.abort = null
    }
  }

  /** Download one file into downloads/<name>.part, resuming and verifying. */
  async fetchFile(f, token, signal, onBytes) {
    const part = this.partPath(f)
    if (this.finished(f) && fs.existsSync(part)) { onBytes(f.size, false); return }
    let attempt = 0
    let badSums = 0
    for (;;) {
      try {
        await this.fetchOnce(f, part, token, signal, onBytes)
        fs.writeFileSync(part + '.ok', f.sha256)
        return
      } catch (e) {
        if (signal.aborted) throw e
        if (e.checksum) {
          rmQuiet(part)
          if (++badSums > 1) throw new Error(`${f.name}: downloaded file is corrupt (${e.message}). Try again later.`)
          continue
        }
        if (e.fatal || ++attempt > RETRIES) throw new Error(`${f.name}: ${e.message}`)
        this.emit('retry', { file: f.name, attempt, error: e.message })
        await sleep(Math.min(1000 * 2 ** (attempt - 1), 15000), signal)
      }
    }
  }

  async fetchOnce(f, part, token, signal, onBytes) {
    let offset = 0
    try { offset = fs.statSync(part).size } catch { /* new */ }
    if (offset > f.size) { rmQuiet(part); offset = 0 }
    let hash = crypto.createHash('sha256')
    if (offset > 0) await hashFile(part, hash, signal)  // resume: re-hash what we already have
    onBytes(offset, false)
    if (offset < f.size) {
      const headers = { 'User-Agent': 'Tabscribe-installer', Accept: 'application/octet-stream' }
      if (offset) headers.Range = `bytes=${offset}-`
      if (token) headers.Authorization = `Bearer ${token}`
      const res = await fetch(this.urlOf(f), { headers, signal, redirect: 'follow' })
      if (res.status === 416) { rmQuiet(part); throw new Error('server refused to resume') }
      if (res.status === 401 || res.status === 403) {
        throw Object.assign(new Error(token ? 'access denied: accept the model licence on Hugging Face with this account, then retry'
          : `access denied (HTTP ${res.status})`), { fatal: true })
      }
      if (res.status === 404) throw Object.assign(new Error(`not found on the server (HTTP 404) — ${this.urlOf(f)}`), { fatal: true })
      if (!res.ok) throw new Error(`HTTP ${res.status}`)
      const append = offset > 0 && res.status === 206
      if (!append && offset > 0) {  // server ignored Range: start over
        offset = 0
        hash = crypto.createHash('sha256')
        onBytes(0, false)
      }
      const out = fs.createWriteStream(part, { flags: append ? 'a' : 'w' })
      let n = offset
      try {
        for await (const chunk of res.body) {
          hash.update(chunk)
          n += chunk.length
          if (n > f.size) throw Object.assign(new Error('larger than expected'), { checksum: true })
          if (!out.write(chunk)) await once(out, 'drain')  // rejects on a write error
          onBytes(n)
        }
      } finally {
        await new Promise(resolve => out.end(resolve))
      }
      if (n < f.size) throw new Error('connection closed early')
    }
    const sum = hash.digest('hex')
    if (sum !== f.sha256) throw Object.assign(new Error(`sha256 ${sum.slice(0, 12)}… ≠ ${f.sha256.slice(0, 12)}…`), { checksum: true })
  }

  /** Concatenate the archive parts into `tar -xJ`, unpack beside the old copy, then swap. */
  async extract(c, signal, onBytes) {
    const staging = path.join(this.home, `.staging-${c.id}`)
    await fsp.rm(staging, { recursive: true, force: true })
    fs.mkdirSync(staging, { recursive: true })
    await new Promise((resolve, reject) => {
      const tar = spawn('/usr/bin/tar', ['-xJf', '-', '-C', staging], { stdio: ['pipe', 'ignore', 'pipe'] })
      let err = ''
      tar.stderr.on('data', d => { err += d })
      tar.on('error', reject)
      tar.on('close', code => (code === 0 ? resolve() : reject(new Error(`Unpacking failed (tar ${code}): ${err.slice(-300)}`))))
      const onAbort = () => tar.kill('SIGTERM')
      signal.addEventListener('abort', onAbort, { once: true })
      ;(async () => {
        let n = 0
        for (const f of c.files) {
          for await (const chunk of fs.createReadStream(this.partPath(f), { highWaterMark: 1 << 20 })) {
            if (signal.aborted) return
            n += chunk.length
            if (!tar.stdin.write(chunk)) await new Promise(r => tar.stdin.once('drain', r))
            onBytes(n)
          }
        }
        tar.stdin.end()
      })().catch(e => { tar.kill(); reject(e) })
    })
    const unpacked = path.join(staging, c.dest)
    if (!fs.existsSync(path.join(unpacked, 'tabscribe-runtime.json'))) throw new Error('Unpacked archive is incomplete')
    const final = path.join(this.home, c.dest)
    const old = `${final}.old`
    await fsp.rm(old, { recursive: true, force: true })
    if (fs.existsSync(final)) fs.renameSync(final, old)
    fs.renameSync(unpacked, final)
    await fsp.rm(old, { recursive: true, force: true })
    await fsp.rm(staging, { recursive: true, force: true })
    for (const f of c.files) { rmQuiet(this.partPath(f)); rmQuiet(this.partPath(f) + '.ok') }
  }

  // ------------------------------------------------------------------ verify / remove
  /** Full check: re-hash every installed model file; run the engine's Python on an import test. */
  async verify(onStep = () => {}) {
    const results = {}
    for (const c of this.manifest.components) {
      if (!this.isInstalled(c)) { results[c.id] = { ok: false, installed: false, problems: ['not installed'] }; continue }
      const problems = []
      if (c.kind === 'archive') {
        onStep(c.id, null)
        const py = path.join(this.home, c.dest, 'bin', 'python3')
        const r = await runQuiet(py, ['-c', 'import torch, numpy, fastapi, uvicorn, basic_pitch, beat_this, transkun, onnxruntime, transformers'])
        if (r.code !== 0) problems.push(`engine does not start: ${r.err.trim().split('\n').pop() || 'exit ' + r.code}`)
        const ff = await runQuiet(path.join(this.home, c.dest, 'bin', 'ffmpeg'), ['-hide_banner', '-version'])
        if (ff.code !== 0) problems.push('ffmpeg missing or broken')
      } else {
        for (const f of c.files) {
          onStep(c.id, f.name)
          const p = path.join(this.home, f.dest)
          try {
            const h = crypto.createHash('sha256')
            await hashFile(p, h)
            if (h.digest('hex') !== f.sha256) problems.push(`${f.dest}: checksum mismatch`)
          } catch { problems.push(`${f.dest}: missing`) }
        }
      }
      results[c.id] = { ok: problems.length === 0, installed: true, problems }
    }
    return results
  }

  async remove(id) {
    const c = this.manifest.components.find(x => x.id === id)
    if (!c || c.required) throw new Error('This component cannot be removed')
    this.dropReceipt(id)
    for (const f of c.files) {
      if (f.dest) rmQuiet(path.join(this.home, f.dest))
      rmQuiet(this.partPath(f)); rmQuiet(this.partPath(f) + '.ok')
    }
  }

  /** Uninstall everything: the engine, every model, partial downloads and model caches.
   *  Projects (data/), settings and logs stay. The app goes back to the first-run setup. */
  async removeAll() {
    if (this.busy) throw new Error('An installation is running: pause it first')
    const dirs = new Set(['models', 'downloads', 'cache'])
    for (const c of this.manifest.components) {
      if (c.dest) dirs.add(c.dest)
      for (const f of c.files) if (f.dest) dirs.add(f.dest.split('/')[0])
    }
    dirs.delete('data'); dirs.delete('logs'); dirs.delete('')
    for (const d of dirs) await fsp.rm(path.join(this.home, d), { recursive: true, force: true })
    rmQuiet(path.join(this.home, RECEIPTS))
    this.lastProgress = null
  }
}

// ------------------------------------------------------------------ helpers
function readHfToken() {
  if (process.env.HF_TOKEN) return process.env.HF_TOKEN
  for (const p of [path.join(os.homedir(), '.cache', 'huggingface', 'token')]) {
    try { const t = fs.readFileSync(p, 'utf8').trim(); if (t) return t } catch { /* none */ }
  }
  return null
}

async function hashFile(p, hash, signal) {
  for await (const chunk of fs.createReadStream(p, { highWaterMark: 1 << 22 })) {
    if (signal?.aborted) throw new CancelledError()
    hash.update(chunk)
  }
}

function speedMeter(windowMs = 4000) {
  const samples = []
  return {
    add(n) { samples.push([Date.now(), n]) },
    rate() {
      const now = Date.now()
      while (samples.length && now - samples[0][0] > windowMs) samples.shift()
      if (!samples.length) return 0
      const bytes = samples.reduce((s, x) => s + x[1], 0)
      return bytes / Math.max((now - samples[0][0]) / 1000, 0.5)
    },
  }
}

function sleep(ms, signal) {
  return new Promise((resolve, reject) => {
    const t = setTimeout(resolve, ms)
    signal?.addEventListener('abort', () => { clearTimeout(t); reject(new CancelledError()) }, { once: true })
  })
}

function rmQuiet(p) { try { fs.rmSync(p, { force: true }) } catch { /* gone */ } }

function runQuiet(cmd, args) {
  return new Promise(resolve => {
    let err = ''
    const p = spawn(cmd, args, { stdio: ['ignore', 'ignore', 'pipe'], env: { PATH: '/usr/bin:/bin', HOME: os.homedir(), PYTHONNOUSERSITE: '1' } })
    p.stderr.on('data', d => { err += d })
    p.on('error', e => resolve({ code: -1, err: e.message }))
    p.on('close', code => resolve({ code, err }))
  })
}

function fmt(b) {
  return b >= 1e9 ? `${(b / 1e9).toFixed(2)} GB` : `${Math.round(b / 1e6)} MB`
}

module.exports = { Installer, CancelledError, fmt }
