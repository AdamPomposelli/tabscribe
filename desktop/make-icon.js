// Renders ../frontend/public/logo.svg to build/icon.png (1024²) with Electron itself.
const { app, BrowserWindow } = require('electron')
const fs = require('fs'), path = require('path')
app.whenReady().then(async () => {
  const svg = fs.readFileSync(path.join(__dirname, '..', 'frontend', 'public', 'logo.svg'), 'utf8')
  const w = new BrowserWindow({ width: 1024, height: 1024, show: false, frame: false, transparent: true, webPreferences: { offscreen: true } })
  // macOS icon grid: 824px squircle centred in 1024px, the logo itself is the plate
  const html = `<html><body style="margin:0;background:transparent"><div style="width:1024px;height:1024px;display:grid;place-items:center">
    <img src="data:image/svg+xml;base64,${Buffer.from(svg).toString('base64')}" style="width:824px;height:824px"></div></body></html>`
  await w.loadURL('data:text/html;base64,' + Buffer.from(html).toString('base64'))
  await new Promise(r => setTimeout(r, 400))
  const img = await w.webContents.capturePage()
  fs.mkdirSync(path.join(__dirname, 'build'), { recursive: true })
  fs.writeFileSync(path.join(__dirname, 'build', 'icon.png'), img.resize({ width: 1024, height: 1024 }).toPNG())
  app.quit()
})
