// electron-builder afterSign hook: without a "Developer ID Application" certificate the app is
// left unsigned, which macOS (Apple silicon) reports as "damaged" once downloaded. Sign it ad hoc
// instead, so users can open it with right-click → Open (or System Settings → Open Anyway).
const { execFileSync } = require('child_process')
const path = require('path')

exports.default = async function afterSign(ctx) {
  if (ctx.electronPlatformName !== 'darwin') return
  const app = path.join(ctx.appOutDir, `${ctx.packager.appInfo.productFilename}.app`)
  let info = ''
  try { info = execFileSync('codesign', ['-dv', '--verbose=2', app], { stdio: ['ignore', 'pipe', 'pipe'] }).toString() } catch (e) { info = String(e.stderr || '') }
  if (/Authority=Developer ID Application/.test(info)) return
  console.log('  • no Developer ID signature: signing ad hoc', app)
  execFileSync('codesign', ['--force', '--deep', '--sign', '-', '--entitlements', path.join(__dirname, '..', 'entitlements.mac.plist'), app], { stdio: 'inherit' })
}
