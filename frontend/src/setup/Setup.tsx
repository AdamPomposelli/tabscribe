// First-run setup and component manager (Electron only): shows what Tabscribe needs on disk,
// downloads it from the app's GitHub release with progress, checks and repairs it later.
import { useCallback, useEffect, useMemo, useState } from 'react'
import { AlertTriangle, Check, CheckCircle2, Download, ExternalLink, FolderOpen, Loader2, Pause, RotateCcw, Scale, ShieldCheck, Trash2 } from 'lucide-react'
import { DEVICE, bytes, eta, setupBridge, type Progress, type SetupStatus, type VerifyResult } from './bridge'

type Mode = 'first-run' | 'manage' | 'repair'
const mode = (new URLSearchParams(location.search).get('mode') || 'first-run') as Mode

export default function Setup() {
  const [st, setSt] = useState<SetupStatus | null>(null)
  const [sel, setSel] = useState<Record<string, boolean>>({})
  const [token, setToken] = useState('')
  const [running, setRunning] = useState(false)
  const [progress, setProgress] = useState<Progress | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [verify, setVerify] = useState<VerifyResult | null>(null)
  const [verifying, setVerifying] = useState<string | null>(null)
  const [justFinished, setJustFinished] = useState(false)
  const [confirmAll, setConfirmAll] = useState(false)
  const [removingAll, setRemovingAll] = useState(false)

  const refresh = useCallback(async () => {
    if (!setupBridge) return
    const s = await setupBridge.status()
    setSt(s)
    setSel(prev => Object.fromEntries(s.components.map(c => [c.id, c.required || (c.id in prev ? prev[c.id] : (c.installed || (mode === 'first-run' && c.default)))])))
    return s
  }, [])

  useEffect(() => {
    if (!setupBridge) return
    refresh()
    const offP = setupBridge.onProgress(p => { setProgress(p); setNotice(null) })
    const offR = setupBridge.onRetry(r => setNotice(`Connection problem (${r.error}), retrying ${r.attempt}/5…`))
    const offV = setupBridge.onVerifyStep(s => setVerifying(s.file ? `${s.id}: ${s.file}` : s.id))
    return () => { offP(); offR(); offV() }
  }, [refresh])

  const runVerify = useCallback(async () => {
    if (!setupBridge) return
    setVerify(null); setError(null); setVerifying('…')
    try { setVerify(await setupBridge.verify()) } catch (e) { setError(String((e as Error).message || e)) }
    setVerifying(null)
    refresh()
  }, [refresh])

  useEffect(() => { if (mode === 'repair' && st && !verify && !verifying) runVerify() }, [st, verify, verifying, runVerify])

  const comps = useMemo(() => st?.components ?? [], [st])
  const todo = comps.filter(c => sel[c.id] && !c.installed)
  const download = todo.reduce((s, c) => s + c.download_size - c.partial, 0)
  const disk = todo.reduce((s, c) => s + c.installed_size + (c.kind === 'archive' ? c.download_size - c.partial : 0), 0)
  const installedSize = comps.filter(c => c.installed).reduce((s, c) => s + c.installed_size, 0)
  const enoughSpace = !st || disk + st.margin <= st.free
  const needsToken = todo.some(c => c.auth === 'huggingface') && !st?.hfTokenFound && !token.trim()

  async function install(ids: string[], force = false) {
    if (!setupBridge) return
    setRunning(true); setError(null); setNotice(null); setVerify(null); setJustFinished(false)
    const r = await setupBridge.install(ids, { hfToken: token.trim() || undefined, force })
    setRunning(false)
    const s = await refresh()
    if (r.ok) {
      setProgress(null)
      setJustFinished(true)
      if (mode === 'first-run' && s?.ready) setTimeout(() => setupBridge?.launch(), 900)
    } else if (r.cancelled) {
      setNotice('Paused. Downloaded data is kept: resume whenever you like.')
    } else {
      setError(r.error || 'Installation failed')
    }
  }

  if (!setupBridge) {
    return <div className="setup"><div className="setup-card"><h1>Setup</h1><p className="muted">The component installer is part of the Tabscribe desktop app.</p></div></div>
  }
  if (!st) return <div className="setup"><Loader2 className="spin" /></div>

  const bridge = setupBridge
  const repairIds = verify ? Object.entries(verify).filter(([, v]) => v.installed && !v.ok).map(([id]) => id) : []
  const missingRequired = comps.filter(c => c.required && !c.installed)

  return (
    <div className="setup">
      <div className="setup-drag" />
      <div className="setup-card">
        <header className="setup-head">
          <img src="/logo.svg" alt="" width={44} height={44} />
          <div>
            <h1>{mode === 'first-run' ? 'Welcome to Tabscribe' : 'Components'}</h1>
            <p className="muted">
              {mode === 'first-run'
                ? `Everything runs on your ${DEVICE}. Download the engine once, then Tabscribe works offline.`
                : `What is installed on this ${DEVICE}. Add, check or repair parts here.`}
            </p>
          </div>
        </header>

        <div className="comp-list">
          {comps.map(c => {
            const v = verify?.[c.id]
            const copy = COPY[c.id]
            const pct = !c.installed && c.partial > 0 ? Math.round((100 * c.partial) / c.download_size) : 0
            const active = running && progress?.component === c.id
            const locked = c.required || c.installed || running
            return (
              <div key={c.id} className={`comp ${sel[c.id] ? 'on' : ''} ${locked ? '' : 'clickable'}`}
                onClick={e => { if (!locked && !(e.target as HTMLElement).closest('a, button, input, .lic')) setSel({ ...sel, [c.id]: !sel[c.id] }) }}>
                <input type="checkbox" checked={!!sel[c.id]} disabled={locked} aria-label={copy?.title ?? c.name}
                  onChange={e => setSel({ ...sel, [c.id]: e.target.checked })} />
                <div className="comp-body">
                  <div className="comp-top">
                    <span className="comp-title">
                      <span className="comp-name">{copy?.title ?? c.name}</span>
                      {copy?.tech && <span className="chip">{copy.tech}</span>}
                      <Licence c={c} />
                    </span>
                    <span className="comp-right">
                      <span className="comp-size">
                        {c.installed ? `${bytes(c.installed_size)} on disk` : `${bytes(c.download_size)} download · ${bytes(c.installed_size)} on disk`}
                      </span>
                      {c.required && !c.installed && !active && <span className="badge off">Required</span>}
                      {!c.required && !c.installed && !active && !pct && <span className="badge off">Optional</span>}
                      {pct > 0 && !active && <span className="badge off">{pct}% downloaded</span>}
                      {active && <span className="badge"><Loader2 size={11} className="spin" /> {progress?.phase === 'extract' ? 'Unpacking' : 'Downloading'}</span>}
                      {c.installed && (!v || v.ok) && <span className="badge"><Check size={11} /> {v ? 'Verified' : 'Installed'}</span>}
                      {v && !v.ok && v.installed && <span className="badge bad"><AlertTriangle size={11} /> Damaged</span>}
                    </span>
                  </div>
                  <div className="comp-desc">{copy?.what ?? c.description}</div>
                  {(copy?.kpi || (c.installed && !c.required && !running)) && (
                    <div className="comp-foot">
                      {copy?.kpi && <span className="kpi">{copy.kpi}</span>}
                      {c.installed && !c.required && !running && (
                        <button className="link-btn" onClick={async () => { await bridge.remove(c.id); setVerify(null); refresh() }}>
                          <Trash2 size={12} /> Remove
                        </button>
                      )}
                    </div>
                  )}
                  {v && v.problems.length > 0 && v.installed && <div className="comp-problems">{v.problems.slice(0, 4).join(' · ')}</div>}
                  {c.auth === 'huggingface' && sel[c.id] && !c.installed && (
                    <div className="token-box">
                      {st.hfTokenFound
                        ? <span className="muted small">Uses your Hugging Face login on this {DEVICE} (the account must have accepted the licence).</span>
                        : <>
                          <span className="muted small">Free Hugging Face account needed: accept the licence on <a href={c.licence_url ?? '#'} target="_blank" rel="noreferrer">huggingface.co</a>, then paste a read token. It is used once and never saved.</span>
                          <input className="input" type="password" placeholder="hf_…" value={token} onChange={e => setToken(e.target.value)} autoComplete="off" spellCheck={false} />
                        </>}
                    </div>
                  )}
                </div>
              </div>
            )
          })}
        </div>

        {running && progress ? <ProgressPanel p={progress} notice={notice} onPause={() => bridge.cancel()} /> : (
          <div className="summary">
            <div className="sum-grid">
              <div><div className="muted small">To download</div><div className="sum-v">{bytes(download)}</div></div>
              <div><div className="muted small">Disk space needed</div><div className="sum-v">{bytes(disk)}</div></div>
              <div><div className="muted small">Available on this {DEVICE}</div><div className={`sum-v ${enoughSpace ? '' : 'error'}`}>{bytes(st.free)}</div></div>
              {installedSize > 0 && <div><div className="muted small">Installed</div><div className="sum-v">{bytes(installedSize)}</div></div>}
            </div>
            {!enoughSpace && <div className="setup-msg error"><AlertTriangle size={15} /> Free up {bytes(disk + st.margin - st.free)} on this disk, then press Install.</div>}
            {notice && <div className="setup-msg">{notice}</div>}
            {error && (
              <div className="setup-msg error"><AlertTriangle size={15} />
                <span>{error}</span>
              </div>
            )}
            {justFinished && !error && <div className="setup-msg ok"><CheckCircle2 size={15} /> {mode === 'first-run' ? 'Everything is installed. Opening Tabscribe…' : 'Done.'}</div>}
            {verifying && <div className="setup-msg"><Loader2 size={14} className="spin" /> Checking {verifying}</div>}
            {confirmAll && (
              <div className="setup-msg error confirm-all">
                <AlertTriangle size={15} />
                <span>Uninstall the engine and every AI model ({bytes(installedSize)})? Your projects and settings stay. You can reinstall from this screen anytime.</span>
                <span className="confirm-btns">
                  <button className="btn-ghost" disabled={removingAll} onClick={() => setConfirmAll(false)}>Cancel</button>
                  <button className="btn-danger" disabled={removingAll} onClick={async () => {
                    setRemovingAll(true); setError(null)
                    try { await bridge.removeAll() } catch (e) { setError(String((e as Error).message || e)); setRemovingAll(false); setConfirmAll(false); refresh() }
                  }}>{removingAll ? <><Loader2 size={14} className="spin" /> Uninstalling…</> : <><Trash2 size={14} /> Uninstall all</>}</button>
                </span>
              </div>
            )}
            {verify && !verifying && repairIds.length === 0 && missingRequired.length === 0 && <div className="setup-msg ok"><ShieldCheck size={15} /> All installed components are intact.</div>}

            <div className="setup-actions">
              {mode !== 'first-run' && (
                <div className="left-actions">
                  <button className="btn-ghost" onClick={() => bridge.reveal()}><FolderOpen size={14} /> Show files</button>
                  <button className="btn-ghost" disabled={!!verifying} onClick={runVerify}><ShieldCheck size={14} /> Check installation</button>
                  {installedSize > 0 && (
                    <button className="btn-ghost danger" disabled={confirmAll} onClick={() => { setConfirmAll(true); setJustFinished(false); setVerify(null) }}><Trash2 size={14} /> Uninstall all models</button>
                  )}
                </div>
              )}
              {repairIds.length > 0 && (
                <button className="btn-primary" onClick={() => install(repairIds, true)}><RotateCcw size={15} /> Repair {repairIds.length > 1 ? `${repairIds.length} components` : comps.find(c => c.id === repairIds[0])?.name}</button>
              )}
              {todo.length > 0 && (
                <button className="btn-primary" disabled={!enoughSpace || needsToken} onClick={() => install(todo.map(c => c.id))}>
                  {error || todo.some(c => c.partial > 0) ? <><RotateCcw size={15} /> Resume ({bytes(download)})</> : <><Download size={15} /> Install ({bytes(download)})</>}
                </button>
              )}
              {st.ready && todo.length === 0 && repairIds.length === 0 && (
                <button className="btn-primary" onClick={() => bridge.launch()}>{mode === 'first-run' ? 'Open Tabscribe' : 'Back to Tabscribe'}</button>
              )}
              {st.ready && todo.length > 0 && mode !== 'first-run' && (
                <button className="btn-ghost" onClick={() => bridge.launch()}>Back to Tabscribe</button>
              )}
            </div>
            <div className="muted small setup-foot">
              Downloaded from Tabscribe's GitHub release {st.version}; every file is checked against its SHA-256. Installed in {st.home}.
              {error && <> <button className="link-btn" onClick={() => bridge.logs()}>Open logs</button></>}
            </div>
          </div>
        )}
      </div>
    </div>
  )
}

type Lic = { what: string; who: string; licence: string; url?: string; note?: string }
type Copy = { title: string; tech?: string; what: string; kpi?: string; licences: Lic[] }

// Plain-language copy per component (the manifest keeps the technical description).
// KPIs are measured numbers from the repo's benchmarks only (note F1 vs a pro transcription).
const COPY: Record<string, Copy> = {
  runtime: {
    title: 'Core engine', tech: 'Python · PyTorch · ffmpeg',
    what: `Runs Tabscribe on your ${DEVICE}. Needed for everything.`,
    licences: [
      { what: 'Python 3.11', who: 'Python Software Foundation', licence: 'PSF-2.0', url: 'https://github.com/astral-sh/python-build-standalone' },
      { what: 'PyTorch and Python libraries', who: 'their authors', licence: 'BSD / MIT / Apache-2.0', note: 'Full list in runtime/THIRD_PARTY.txt' },
      { what: 'ffmpeg 9.0.2 (reads your audio files)', who: 'FFmpeg developers', licence: 'LGPL-2.1+', url: 'https://ffmpeg.org/legal.html', note: 'Built from the official source, LGPL-only' },
      { what: 'madmom (beat timing)', who: 'CPJKU', licence: 'BSD-2-Clause', url: 'https://github.com/CPJKU/madmom', note: 'Its CC BY-NC-SA models are removed: only the code is used' },
    ],
  },
  models: {
    title: 'Transcription AI', tech: 'Tsumugi · Beat This! · Open-Fret',
    what: 'Hears the notes, beats and chords, then picks playable fingerings. Needed.',
    kpi: 'Note accuracy 0.97 (F1) on our test song',
    licences: [
      { what: 'Tsumugi (notes, chords, key)', who: 'anime-song', licence: 'MIT', url: 'https://huggingface.co/anime-song/instrument_agnostic_amt' },
      { what: 'Beat This! (beats)', who: 'CPJKU', licence: 'MIT', url: 'https://github.com/CPJKU/beat_this' },
      { what: 'Open-Fret (fingering)', who: 'mylonasc', licence: 'MIT', url: 'https://huggingface.co/mylonasc/open-fret-tab', note: 'Author notes the training data rights are not established' },
      { what: 'tab-labeler v3 (fingering)', who: 'cstr', licence: 'CC BY 4.0', url: 'https://huggingface.co/cstr/tab-labeler-onnx' },
    ],
  },
  bs_roformer_sw: {
    title: 'Isolate the guitar from a band', tech: 'BS-RoFormer SW',
    what: 'For songs with vocals, drums or bass: pulls the guitar out first. Not needed for solo guitar.',
    kpi: 'Note F1 0.71 → 0.84 on a guitar + vocals song',
    licences: [{ what: 'BS-RoFormer SW weights', who: 'jarredou (mirror: enerjazzer)', licence: 'Unknown (one mirror says CC BY-NC-SA 4.0)',
      url: 'https://huggingface.co/enerjazzer/BS-ROFO-SW-Fixed', note: 'Downloaded from Hugging Face, not re-hosted, because its licence is unclear. Sounded sharpest in a blind listening test.' }],
  },
  demucs: {
    title: 'Lighter guitar isolation', tech: 'Demucs',
    what: 'Smaller, about 4× faster backup. Used when the main isolation is not installed.',
    kpi: 'Note F1 0.71 → 0.83 on a guitar + vocals song',
    licences: [{ what: 'Demucs htdemucs_6s', who: 'Meta AI Research', licence: 'MIT', url: 'https://github.com/facebookresearch/demucs' }],
  },
  muscriptor: {
    title: 'Extra AI model', tech: 'MuScriptor',
    what: 'Adds a 7th voter and a faster engine. Free Hugging Face account needed.',
    kpi: 'Faster engine: note F1 0.89 vs 0.82 without it',
    licences: [{ what: 'MuScriptor medium', who: 'Kyutai × Mirelo', licence: 'CC BY-NC 4.0 (non-commercial)', url: 'https://huggingface.co/MuScriptor/muscriptor-medium',
      note: 'Downloaded from Hugging Face with your account. On our two test songs the vote scores the same with or without it.' }],
  },
}

function Licence({ c }: { c: { id: string; licence: string } }) {
  const lic = COPY[c.id]?.licences
  return (
    <span className="lic" tabIndex={0} aria-label="Licence details">
      <Scale size={13} />
      <span className="tip" role="tooltip">
        <span className="tip-head">Licences</span>
        {lic ? lic.map(l => (
          <span key={l.what} className="tip-row">
            <span><b>{l.what}</b> · {l.who}</span>
            <span className="tip-lic">{l.url ? <a href={l.url} target="_blank" rel="noreferrer">{l.licence} <ExternalLink size={10} /></a> : l.licence}</span>
            {l.note && <span className="tip-note">{l.note}</span>}
          </span>
        )) : <span className="tip-row">{c.licence}</span>}
      </span>
    </span>
  )
}

function ProgressPanel({ p, notice, onPause }: { p: Progress; notice: string | null; onPause: () => void }) {
  const overall = p.total ? p.done / p.total : 0
  const file = p.fileSize ? p.fileBytes / p.fileSize : 0
  return (
    <div className="summary">
      <div className="prog-block">
        <div className="prog-line"><span>{p.phase === 'extract' ? 'Unpacking the engine' : 'Downloading'}</span>
          <span className="muted">{bytes(p.done)} of {bytes(p.total)} · {Math.floor(overall * 100)}%</span></div>
        <div className="bar big"><div style={{ width: `${overall * 100}%` }} /></div>
        <div className="prog-line muted small">
          <span>{p.phase === 'download' && p.speed > 0 ? `${bytes(p.speed)}/s` : ' '}</span>
          <span>{p.phase === 'download' ? eta(p.eta) : ''}</span>
        </div>
      </div>
      <div className="prog-block">
        <div className="prog-line small"><span className="ellipsis">{p.phase === 'extract' ? 'Unpacking files' : p.file}</span>
          <span className="muted">{p.phase === 'download' ? `file ${p.index} of ${p.count} · ` : ''}{bytes(p.fileBytes)} / {bytes(p.fileSize)}</span></div>
        <div className="bar"><div style={{ width: `${file * 100}%` }} /></div>
      </div>
      {notice && <div className="setup-msg">{notice}</div>}
      <div className="setup-actions">
        <button className="btn-ghost" onClick={onPause} disabled={p.phase === 'extract'}><Pause size={14} /> Pause</button>
      </div>
    </div>
  )
}
