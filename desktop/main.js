// Tabscribe desktop shell.
//
// Packaged app ("managed" mode): the code (backend, vendor, built UI) ships read-only in
// Tabscribe.app/Contents/Resources/engine; the heavy parts (Python engine, models) are
// installed on first run from the app's GitHub release by installer.js into
// ~/Library/Application Support/Tabscribe, where projects and logs live too.
// Development (`npm start` in a checkout): runs the checkout's .venv as before.
// Set TABSCRIBE_MANAGED=1 to try the installer from a checkout.
const { app, BrowserWindow, ipcMain, ShareMenu, shell, dialog, session, Menu, protocol, net } = require('electron')
const { spawn } = require('child_process')
const { pathToFileURL } = require('url')
const path = require('path')
const fs = require('fs')
const os = require('os')
const http = require('http')
const { Installer, CancelledError } = require('./installer')

const MANAGED = app.isPackaged || process.env.TABSCRIBE_MANAGED === '1'
const ENGINE = app.isPackaged ? path.join(process.resourcesPath, 'engine') : path.resolve(__dirname, '..')
const UI_DIR = path.join(ENGINE, 'frontend', 'dist')
// TABSCRIBE_DATA_DIR: install somewhere else (tests, a second profile)
const HOME = process.env.TABSCRIBE_DATA_DIR || (MANAGED ? app.getPath('userData') : ENGINE)

let installer = null
if (MANAGED) {
  const manifest = JSON.parse(fs.readFileSync(path.join(__dirname, 'manifest.json'), 'utf8'))
  // TABSCRIBE_ASSETS_URL: test a release from a local server before uploading it
  installer = new Installer({ manifest, home: HOME, baseUrl: process.env.TABSCRIBE_ASSETS_URL })
}

let backend = null
let port = 0
let win = null
let quitting = false

// Prefer the same port on every launch: the page's origin (and with it localStorage: panel width,
// last project...) stays the same. Fall back to any free port if it's taken.
const PREFERRED_PORT = 47615

function freePort(want = PREFERRED_PORT) {
  return new Promise((resolve, reject) => {
    const s = require('net').createServer()
    s.unref()
    s.on('error', err => (want ? freePort(0).then(resolve, reject) : reject(err)))
    s.listen(want, '127.0.0.1', () => { const p = s.address().port; s.close(() => resolve(p)) })
  })
}

function waitFor(url, timeoutMs = 120000) {
  const t0 = Date.now()
  return new Promise((resolve, reject) => {
    const tryOnce = () => {
      if (!backend) return reject(new Error('The transcription engine exited while starting'))
      http.get(url, res => { res.resume(); res.statusCode < 500 ? resolve() : retry() }).on('error', retry)
    }
    const retry = () => (Date.now() - t0 > timeoutMs ? reject(new Error('The transcription engine did not start in time')) : setTimeout(tryOnce, 300))
    tryOnce()
  })
}

function backendCommand() {
  if (!MANAGED) {
    const py = path.join(ENGINE, '.venv', 'bin', 'python')
    if (!fs.existsSync(py)) throw new Error(`Python environment not found at ${py}. Run ./run.sh once in ${ENGINE}.`)
    // GUI apps don't inherit the shell PATH on macOS: ffmpeg lives in Homebrew
    const PATH = ['/opt/homebrew/bin', '/usr/local/bin', process.env.PATH || ''].join(':')
    return { py, logDir: path.join(ENGINE, 'logs'), env: { ...process.env, PATH, PYTHONUNBUFFERED: '1' } }
  }
  const rt = path.join(HOME, 'runtime')
  const cache = path.join(HOME, 'cache')
  // nothing from the user's shell (Homebrew, pyenv, conda...) can leak into the engine
  const env = {
    HOME: os.homedir(), USER: os.userInfo().username, TMPDIR: os.tmpdir(), LANG: 'en_US.UTF-8',
    PATH: [path.join(rt, 'bin'), '/usr/bin', '/bin', '/usr/sbin', '/sbin'].join(':'),
    PYTHONUNBUFFERED: '1', PYTHONNOUSERSITE: '1', PYTHONPYCACHEPREFIX: path.join(cache, 'pycache'),
    TABSCRIBE_DATA: path.join(HOME, 'data'), TABSCRIBE_MODELS: path.join(HOME, 'models'),
    TORCH_HOME: path.join(HOME, 'models', 'torch'), HF_HOME: path.join(cache, 'huggingface'),
    HF_HUB_OFFLINE: '1', TRANSFORMERS_OFFLINE: '1', HF_HUB_DISABLE_TELEMETRY: '1',
    NUMBA_CACHE_DIR: path.join(cache, 'numba'), MPLCONFIGDIR: path.join(cache, 'matplotlib'),
  }
  return { py: path.join(rt, 'bin', 'python3'), logDir: path.join(HOME, 'logs'), env }
}

async function startBackend() {
  if (backend) return
  const { py, logDir, env } = backendCommand()
  if (!fs.existsSync(path.join(UI_DIR, 'index.html'))) throw new Error('Frontend not built: run "npm run build" in frontend/.')
  port = await freePort()
  fs.mkdirSync(logDir, { recursive: true })
  const log = fs.openSync(path.join(logDir, 'desktop-backend.log'), 'a')
  fs.writeSync(log, `\n--- ${new Date().toISOString()} starting engine (${py})\n`)
  const child = spawn(py, ['-m', 'uvicorn', 'tabscribe.server:app', '--app-dir', path.join(ENGINE, 'backend'),
    '--host', '127.0.0.1', '--port', String(port)], { cwd: ENGINE, env, stdio: ['ignore', log, log] })
  backend = child
  child.on('error', () => { if (backend === child) backend = null })
  child.on('exit', code => {
    if (backend !== child) return
    backend = null
    if (quitting || !win || code === null) return
    const buttons = MANAGED ? ['Check installation', 'Quit'] : ['Quit']
    dialog.showMessageBox(win, {
      type: 'error', message: 'The transcription engine stopped', buttons,
      detail: `Exit code ${code}. Details: ${path.join(logDir, 'desktop-backend.log')}`,
    }).then(r => { if (MANAGED && r.response === 0) showSetup('repair'); else app.quit() })
  })
  await waitFor(`http://127.0.0.1:${port}/api/engines`)
}

function stopBackend() {
  const child = backend
  backend = null
  if (!child) return Promise.resolve()
  return new Promise(resolve => {
    child.once('exit', resolve)
    try { child.kill('SIGTERM') } catch { resolve() }
    setTimeout(() => { try { child.kill('SIGKILL') } catch { /* gone */ } resolve() }, 5000)
  })
}

async function openApp() {
  win.loadFile(path.join(__dirname, 'loading.html'))
  await startBackend()
  await win.loadURL(`http://127.0.0.1:${port}/`)
}

function showSetup(mode) {
  return win.loadURL(`tabscribe://app/setup.html?mode=${encodeURIComponent(mode)}`)
}

async function createWindow() {
  win = new BrowserWindow({
    width: 1440, height: 900, minWidth: 980, minHeight: 640,
    title: process.env.TABSCRIBE_DATA_DIR ? `Tabscribe — TEST PROFILE (${HOME})` : 'Tabscribe', backgroundColor: '#0e0e10', show: false,
    titleBarStyle: process.platform === 'darwin' ? 'hiddenInset' : 'default',
    trafficLightPosition: { x: 16, y: 20 },
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'), contextIsolation: true, nodeIntegration: false, sandbox: true,
      additionalArguments: MANAGED ? ['--tabscribe-managed'] : [],
    },
  })
  win.on('closed', () => { win = null })
  win.loadFile(path.join(__dirname, 'loading.html'))
  win.once('ready-to-show', () => win.show())
  // keep the test-profile title even when pages set their own <title>
  if (process.env.TABSCRIBE_DATA_DIR) win.on('page-title-updated', e => e.preventDefault())
  // external links open in the default browser, never inside the app
  win.webContents.setWindowOpenHandler(({ url }) => { if (/^https:\/\//.test(url)) shell.openExternal(url); return { action: 'deny' } })
  try {
    if (MANAGED && !installer.status().ready) await showSetup('first-run')
    else await openApp()
  } catch (e) {
    const r = await dialog.showMessageBox(win, {
      type: 'error', message: 'Tabscribe could not start', detail: String(e.message || e),
      buttons: MANAGED ? ['Check installation', 'Quit'] : ['Quit'],
    })
    if (MANAGED && r.response === 0) showSetup('repair')
    else app.quit()
  }
}

// ----------------------------------------------------------------------------- setup IPC
// Only our own pages (the bundled setup page and the local engine) may drive the installer.
function trusted(e) {
  const u = e.senderFrame?.url || ''
  return u.startsWith('tabscribe://app/') || (port && u.startsWith(`http://127.0.0.1:${port}/`))
}
function handle(channel, fn) {
  ipcMain.handle(channel, async (e, ...args) => {
    if (!trusted(e)) throw new Error('not allowed')
    if (!installer && channel !== 'setup:status') throw new Error('The installer is only available in the packaged app')
    return fn(e, ...args)
  })
}

handle('setup:status', () => (installer ? { managed: true, ...installer.status() } : { managed: false }))
handle('setup:install', async (e, { ids, hfToken, force }) => {
  const send = (ch, x) => { if (!e.sender.isDestroyed()) e.sender.send(ch, x) }
  const onProgress = p => send('setup:progress', p)
  const onRetry = r => send('setup:retry', r)
  installer.on('progress', onProgress)
  installer.on('retry', onRetry)
  try {
    if (ids.includes('runtime') && (force || !installer.status().components.find(c => c.id === 'runtime').installed)) await stopBackend()
    await installer.install(ids, { hfToken, force })
    return { ok: true }
  } catch (err) {
    return { ok: false, cancelled: err instanceof CancelledError, error: String(err.message || err) }
  } finally {
    installer.off('progress', onProgress)
    installer.off('retry', onRetry)
  }
})
handle('setup:cancel', () => installer.cancel())
handle('setup:verify', async e => installer.verify((id, file) => { if (!e.sender.isDestroyed()) e.sender.send('setup:verify-step', { id, file }) }))
handle('setup:remove', (_e, id) => installer.remove(id))
handle('setup:launch', async () => {
  if (backend) { await win.loadURL(`http://127.0.0.1:${port}/`); return }
  await openApp()
})
handle('setup:open', () => showSetup('manage'))
handle('setup:reveal', () => shell.openPath(HOME))
handle('setup:logs', () => shell.openPath(path.join(HOME, 'logs')))

// ----------------------------------------------------------------------------- downloads & share
// Downloads ask where to save (like any Mac app)
function setupDownloads() {
  session.defaultSession.on('will-download', (_e, item) => {
    item.setSaveDialogOptions({ title: 'Save', defaultPath: path.join(app.getPath('downloads'), item.getFilename()) })
  })
}

// Native share sheet (AirDrop, Messages, Mail…): fetch the file from the backend into a temp folder
ipcMain.handle('share', async (_e, files) => {
  if (process.platform !== 'darwin' || !win) return false
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'tabscribe-share-'))
  const paths = []
  for (const f of files) {
    const u = new URL(f.url)
    if (u.hostname !== '127.0.0.1' || Number(u.port) !== port) continue  // only our own backend
    const res = await fetch(u.href)
    const p = path.join(dir, path.basename(f.name).replace(/[\\/:*?"<>|]/g, '-'))
    fs.writeFileSync(p, Buffer.from(await res.arrayBuffer()))
    paths.push(p)
  }
  if (!paths.length) return false
  new ShareMenu({ filePaths: paths }).popup({ window: win })
  return true
})

// The setup screen is part of the built UI (frontend/setup.html), served from the app bundle:
// it must work before the Python engine exists.
protocol.registerSchemesAsPrivileged([{ scheme: 'tabscribe', privileges: { standard: true, secure: true, supportFetchAPI: true } }])

app.setName('Tabscribe')
app.whenReady().then(() => {
  protocol.handle('tabscribe', req => {
    const rel = decodeURIComponent(new URL(req.url).pathname).replace(/^\/+/, '')
    const file = path.normalize(path.join(UI_DIR, rel))
    if (!file.startsWith(UI_DIR + path.sep)) return new Response('forbidden', { status: 403 })
    return net.fetch(pathToFileURL(file).href)
  })
  if (process.platform === 'darwin') Menu.setApplicationMenu(Menu.buildFromTemplate([
    { role: 'appMenu' }, { role: 'fileMenu' }, { role: 'editMenu' },
    { label: 'View', submenu: [{ role: 'reload' }, { role: 'toggleDevTools' }, { type: 'separator' }, { role: 'resetZoom' }, { role: 'zoomIn' }, { role: 'zoomOut' }, { type: 'separator' }, { role: 'togglefullscreen' }] },
    { role: 'windowMenu' },
  ]))
  setupDownloads()
  createWindow()
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) createWindow() })
})
app.on('window-all-closed', () => { if (process.platform !== 'darwin') app.quit() })
app.on('before-quit', () => { quitting = true; installer?.cancel(); stopBackend() })
app.on('will-quit', () => { stopBackend() })
process.on('exit', () => { try { backend?.kill('SIGTERM') } catch { /* gone */ } })
