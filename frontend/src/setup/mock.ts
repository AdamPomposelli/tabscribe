// Dev-only stand-in for the Electron installer: `npm run dev`, then open /setup.html?mock
// (add &mode=manage to see the component manager). Never bundled in production builds.
import type { Progress, SetupBridge, SetupStatus } from './bridge'

export function mockBridge(): SetupBridge {
  const comps: SetupStatus['components'] = [
    { id: 'runtime', name: 'Transcription engine', kind: 'archive', description: 'Python 3.11, PyTorch and the transcription libraries, ffmpeg', required: true, default: true, licence: 'CPython (PSF-2.0); Python packages under their own licences; ffmpeg LGPL-2.1+', licence_url: null, auth: null, download_size: 612e6, installed_size: 1.71e9, installed: false, partial: 0 },
    { id: 'models', name: 'AI models', kind: 'files', description: 'Beat This! beat tracker, Tsumugi x4 transcription + chord/key model, Open-Fret and tab-labeler fingering', required: true, default: true, licence: 'MIT / CC BY 4.0', licence_url: null, auth: null, download_size: 455e6, installed_size: 455e6, installed: false, partial: 120e6 },
    { id: 'demucs', name: 'Guitar isolation (Demucs)', kind: 'files', description: 'Separates the guitar from a full band mix before transcribing (optional, per project)', required: false, default: true, licence: 'MIT', licence_url: null, auth: null, download_size: 55e6, installed_size: 55e6, installed: false, partial: 0 },
    { id: 'muscriptor', name: 'MuScriptor (extra vote model)', kind: 'files', description: 'Adds a 7th model to the vote. Non-commercial licence.', required: false, default: false, licence: 'CC BY-NC 4.0, gated on Hugging Face', licence_url: 'https://huggingface.co/MuScriptor/muscriptor-medium', auth: 'huggingface', download_size: 1.23e9, installed_size: 1.23e9, installed: false, partial: 0 },
  ]
  const st: SetupStatus = { managed: true, version: 'assets-mock', home: '~/Library/Application Support/Tabscribe', free: 14e9, margin: 3e8, ready: false, busy: false, components: comps, hfTokenFound: false, lastProgress: null }
  const listeners = new Set<(p: Progress) => void>()
  let cancel = false
  return {
    status: async () => ({ ...st, components: comps.map(c => ({ ...c })), ready: comps.every(c => !c.required || c.installed) }),
    install: async ids => {
      cancel = false
      const todo = comps.filter(c => ids.includes(c.id) && !c.installed)
      const total = todo.reduce((s, c) => s + c.download_size, 0)
      let done = 0
      for (const c of todo) {
        for (let b = c.partial; b <= c.download_size; b += c.download_size / 40) {
          if (cancel) { c.partial = b; return { ok: false, cancelled: true } }
          await new Promise(r => setTimeout(r, 60))
          listeners.forEach(f => f({ phase: 'download', component: c.id, file: `${c.id}.bin`, fileBytes: b, fileSize: c.download_size, done: done + b, total, speed: 24e6, eta: (total - done - b) / 24e6, index: 1, count: 1 }))
        }
        done += c.download_size
        if (c.kind === 'archive') {
          for (let b = 0; b <= c.download_size; b += c.download_size / 10) {
            await new Promise(r => setTimeout(r, 80))
            listeners.forEach(f => f({ phase: 'extract', component: c.id, file: null, fileBytes: b, fileSize: c.download_size, done, total, speed: 0, eta: null, index: 1, count: 1 }))
          }
        }
        c.installed = true; c.partial = 0
      }
      return { ok: true }
    },
    cancel: async () => { cancel = true },
    verify: async () => Object.fromEntries(comps.map(c => [c.id, { ok: c.id !== 'models', installed: c.installed, problems: c.id === 'models' && c.installed ? ['models/tsumugi/best_model.pth: checksum mismatch'] : [] }])),
    remove: async id => { const c = comps.find(x => x.id === id); if (c) c.installed = false },
    removeAll: async () => { comps.forEach(c => { c.installed = false; c.partial = 0 }); location.search = '?mock&mode=first-run' },
    launch: async () => { location.href = '/' },
    open: async () => { location.href = '/setup.html?mock&mode=manage' },
    reveal: async () => {}, logs: async () => {},
    onProgress: cb => { listeners.add(cb); return () => listeners.delete(cb) },
    onRetry: () => () => {},
    onVerifyStep: () => () => {},
  }
}
