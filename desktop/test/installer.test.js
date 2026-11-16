// Headless tests of installer.js against release/serve_local.py (GitHub-like redirects + Range,
// one dropped connection per file). Run: node --test desktop/test/
const { test, before, after } = require('node:test')
const assert = require('node:assert')
const { spawn, execFileSync } = require('child_process')
const crypto = require('crypto')
const fs = require('fs')
const os = require('os')
const path = require('path')
const { Installer } = require('../installer')

const TAG = '_installer-test'
const OUT = path.join(__dirname, '..', '..', 'release', 'out', TAG)
const PORT = 8898
let server, home
const sha = b => crypto.createHash('sha256').update(b).digest('hex')

function makeManifest() {
  fs.rmSync(OUT, { recursive: true, force: true })
  fs.mkdirSync(OUT, { recursive: true })
  const a = crypto.randomBytes(3_000_000), b = crypto.randomBytes(2_500_000)
  fs.writeFileSync(path.join(OUT, 'a.bin'), a)
  fs.writeFileSync(path.join(OUT, 'b.bin'), b)
  // a fake "runtime" archive, split in two parts like a > 2 GB one would be
  const src = fs.mkdtempSync(path.join(os.tmpdir(), 'ts-rt-'))
  fs.mkdirSync(path.join(src, 'runtime', 'bin'), { recursive: true })
  fs.writeFileSync(path.join(src, 'runtime', 'tabscribe-runtime.json'), '{"version":"t"}')
  fs.writeFileSync(path.join(src, 'runtime', 'bin', 'payload'), crypto.randomBytes(2_000_000))
  execFileSync('/bin/sh', ['-c', `tar -cf - -C "${src}" runtime | xz -0 -c > "${OUT}/rt.tar.xz"`])
  const xz = fs.readFileSync(path.join(OUT, 'rt.tar.xz'))
  const half = Math.floor(xz.length / 2)
  fs.writeFileSync(path.join(OUT, 'rt.tar.xz.part00'), xz.subarray(0, half))
  fs.writeFileSync(path.join(OUT, 'rt.tar.xz.part01'), xz.subarray(half))
  const f = (name, buf, dest) => ({ name, size: buf.length, sha256: sha(buf), ...(dest ? { dest } : {}) })
  return {
    schema: 1, version: TAG, base_url: `http://127.0.0.1:${PORT}/download/`,
    components: [
      { id: 'runtime', name: 'Runtime', required: true, kind: 'archive', dest: 'runtime', installed_size: 2_000_100,
        files: [f('rt.tar.xz.part00', xz.subarray(0, half)), f('rt.tar.xz.part01', xz.subarray(half))], download_size: xz.length },
      { id: 'models', name: 'Models', required: true, kind: 'files', files: [f('a.bin', a, 'models/x/a.bin')], download_size: a.length, installed_size: a.length },
      { id: 'extra', name: 'Extra', required: false, kind: 'files', files: [f('b.bin', b, 'models/y/b.bin')], download_size: b.length, installed_size: b.length },
    ],
  }
}

let manifest
before(async () => {
  manifest = makeManifest()
  home = fs.mkdtempSync(path.join(os.tmpdir(), 'ts-home-'))
  server = spawn('python3', [path.join(__dirname, '..', '..', 'release', 'serve_local.py'), TAG, '--port', String(PORT), '--drop-after', '1', '--rate', '20'], { stdio: ['ignore', 'pipe', 'inherit'] })
  await new Promise(r => server.stdout.once('data', r))
})
after(() => { server?.kill(); fs.rmSync(OUT, { recursive: true, force: true }); fs.rmSync(home, { recursive: true, force: true }) })

test('fresh install: resumes after a dropped connection, verifies, unpacks split archive', async () => {
  const inst = new Installer({ manifest, home })
  assert.equal(inst.status().ready, false)
  const retries = []
  let last
  inst.on('retry', r => retries.push(r))
  inst.on('progress', p => { last = p })
  await inst.install(['runtime', 'models'])
  assert.ok(retries.length >= 1, 'expected a retry after the dropped connection')
  assert.equal(last.phase, 'done')
  assert.equal(last.done, last.total)
  const st = inst.status()
  assert.equal(st.ready, true)
  assert.deepEqual(st.components.map(c => c.installed), [true, true, false])
  assert.ok(fs.existsSync(path.join(home, 'runtime', 'bin', 'payload')))
  assert.equal(sha(fs.readFileSync(path.join(home, 'models/x/a.bin'))), manifest.components[1].files[0].sha256)
  assert.deepEqual(fs.readdirSync(path.join(home, 'downloads')), [], 'downloads cleaned up')
})

test('pause keeps the partial file, resume finishes it; optional component can be removed', async () => {
  const inst = new Installer({ manifest, home })
  inst.on('progress', p => { if (p.fileBytes > 600_000 && p.fileBytes < 2_000_000) inst.cancel() })
  await assert.rejects(inst.install(['extra']), e => e.cancelled === true)
  const partial = inst.status().components.find(c => c.id === 'extra').partial
  assert.ok(partial > 0, 'partial bytes kept')
  inst.removeAllListeners('progress')
  await inst.install(['extra'])
  assert.equal(inst.status().components.find(c => c.id === 'extra').installed, true)
  await inst.remove('extra')
  assert.equal(fs.existsSync(path.join(home, 'models/y/b.bin')), false)
  await assert.rejects(inst.remove('models'))
})

test('verify detects a damaged file, forced reinstall repairs it', async () => {
  const inst = new Installer({ manifest, home })
  fs.appendFileSync(path.join(home, 'models/x/a.bin'), 'x')
  assert.equal(inst.isInstalled(manifest.components[1]), false, 'size change detected quickly')
  fs.truncateSync(path.join(home, 'models/x/a.bin'), manifest.components[1].files[0].size)
  const buf = fs.readFileSync(path.join(home, 'models/x/a.bin')); buf[10] ^= 0xff; fs.writeFileSync(path.join(home, 'models/x/a.bin'), buf)
  const v = await inst.verify()
  assert.equal(v.models.ok, false)
  assert.match(v.models.problems[0], /checksum/)
  await inst.install(['models'], { force: true })
  assert.equal((await inst.verify()).models.ok, true)
})

test('a file that does not match its sha256 is rejected', async () => {
  const bad = JSON.parse(JSON.stringify(manifest))
  bad.components[2].files[0].sha256 = '0'.repeat(64)
  const inst = new Installer({ manifest: bad, home })
  await assert.rejects(inst.install(['extra']), /corrupt/)
  assert.equal(inst.status().components.find(c => c.id === 'extra').installed, false)
})

test('refuses to start without enough disk space', async () => {
  const big = JSON.parse(JSON.stringify(manifest))
  big.components[2].download_size = 1e15
  const inst = new Installer({ manifest: big, home })
  await assert.rejects(inst.install(['extra']), /Not enough disk space/)
})

test('uninstall all removes the engine, models, downloads and caches, keeps projects and logs', async () => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'ts-home-'))
  const manifest = { version: 't', base_url: 'http://127.0.0.1/', components: [
    { id: 'runtime', name: 'Runtime', required: true, kind: 'archive', dest: 'runtime', files: [{ name: 'rt.tar.xz', size: 1, sha256: 'x' }], download_size: 1, installed_size: 1 },
    { id: 'models', name: 'Models', required: true, kind: 'files', files: [{ name: 'a.bin', size: 1, sha256: 'y', dest: 'models/x/a.bin' }], download_size: 1, installed_size: 1 },
  ] }
  for (const d of ['runtime/bin', 'models/x', 'downloads', 'cache/huggingface', 'data/projects/p1', 'logs']) fs.mkdirSync(path.join(home, d), { recursive: true })
  fs.writeFileSync(path.join(home, 'models/x/a.bin'), 'a')
  fs.writeFileSync(path.join(home, 'data/projects/p1/project.json'), '{}')
  fs.writeFileSync(path.join(home, 'installed.json'), JSON.stringify({ components: { runtime: {}, models: {} } }))
  const inst = new Installer({ manifest, home })
  await inst.removeAll()
  assert.deepStrictEqual(fs.readdirSync(home).sort(), ['data', 'logs'])
  assert.ok(fs.existsSync(path.join(home, 'data/projects/p1/project.json')))
  assert.strictEqual(inst.status().ready, false)
  fs.rmSync(home, { recursive: true, force: true })
})
