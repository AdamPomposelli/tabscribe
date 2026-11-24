import { useCallback, useEffect, useRef, useState } from 'react'
import {
  Plus, Music2, Search, FileMusic, PanelLeft, Share, RefreshCw, ArrowUpDown, ChevronDown, ChevronLeft, ChevronRight,
  Eye, Pencil, AudioLines, SkipBack, Play, Pause, Timer, SlidersHorizontal, Download, Settings, Cpu,
  Guitar, Trash2, X, Gauge, Loader2, Check, Printer, Volume2, MoreHorizontal,
} from 'lucide-react'
import { api, type Engines, type Meta, type Result, type Status } from './api'
import { DEVICE, IS_MAC, bytes, setupBridge, type SetupStatus } from './setup/bridge'
import { ScoreView, type ScoreHandle, type PlaybackSource } from './components/ScoreView'
import { PianoRoll } from './components/PianoRoll'
import { EditableTitle } from './components/EditableTitle'
import { GUITAR_SOUNDS, soundById } from './sounds'
import { NewProjectFlow, ProcessingCard } from './components/NewProject'
import { PipelineDiagram } from './components/PipelineDiagram'

const fmt = (s: number) => {
  if (!isFinite(s) || s < 0) s = 0
  const m = Math.floor(s / 60), sec = Math.floor(s % 60)
  return `${m}:${sec.toString().padStart(2, '0')}`
}
const DIFFICULTIES = [['original', 'Original'], ['intermediate', 'Intermediate'], ['beginner', 'Beginner']] as const
const INSTRUMENTS = [
  { id: 'solo', label: 'Acoustic Guitar', hint: 'Solo guitar recording', separate: false },
  { id: 'mix', label: 'Guitar in a band mix', hint: 'Isolate the guitar first', separate: true },
]
const KEY_GLYPH = (acc: number) => (acc < 0 ? '♭' : acc > 0 ? '♯' : '♮')

export default function App() {
  const [projects, setProjects] = useState<Meta[]>([])
  const [currentId, setCurrentId] = useState<string | null>(() => localStorage.getItem('fs.current'))
  const [meta, setMeta] = useState<Meta | null>(null)
  const [result, setResult] = useState<Result | null>(null)
  const [status, setStatus] = useState<Status | null>(null)
  const [version, setVersion] = useState('0')
  const [reloadKey, setReloadKey] = useState(0)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [panelOpen, setPanelOpen] = useState(() => localStorage.getItem('fs.panelOpen') !== '0')
  const [panelWidth, setPanelWidth] = useState(() => Number(localStorage.getItem('fs.panelWidth')) || 280)
  const [showNew, setShowNew] = useState(false)
  const [showSettings, setShowSettings] = useState(false)
  const [showEngines, setShowEngines] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [engines, setEngines] = useState<Engines | null>(null)
  const [query, setQuery] = useState('')

  const [source, setSource] = useState<PlaybackSource>('transcribed')
  const [playing, setPlaying] = useState(false)
  const [ready, setReady] = useState(false)
  const [time, setTime] = useState(0)
  const [total, setTotal] = useState(0)
  const timeRef = useRef(0)
  const [speed, setSpeed] = useState(1)
  const [metronome, setMetronome] = useState(false)
  const [volume, setVolume] = useState(0.9)
  const [rollMode, setRollMode] = useState<'score' | 'raw'>('raw')
  const [rollExpanded, setRollExpanded] = useState(false)
  const scoreRef = useRef<ScoreHandle>(null)
  // guitar sound: remembered in the backend (the desktop app's origin can change between launches),
  // with a local copy so the right sound is used from the first render
  const [soundId, setSoundId] = useState(() => soundById(localStorage.getItem('fs.sound')).id)
  useEffect(() => {
    api.prefs().then(p => {
      if (p.guitar_sound) { const id = soundById(p.guitar_sound).id; setSoundId(id); localStorage.setItem('fs.sound', id) }
    }).catch(() => {})
  }, [])
  const chooseSound = (id: string) => {
    setSoundId(id)
    localStorage.setItem('fs.sound', id)
    api.savePrefs({ guitar_sound: id }).catch(() => {})
  }

  // narrow windows: the sidebar would leave no room for the score, so it starts hidden
  useEffect(() => {
    const mq = window.matchMedia('(max-width: 820px)')
    const h = () => { if (mq.matches) setSidebarOpen(false) }
    h(); mq.addEventListener('change', h)
    return () => mq.removeEventListener('change', h)
  }, [])

  const refreshProjects = useCallback(() => api.projects().then(setProjects).catch(() => {}), [])
  useEffect(() => { refreshProjects(); api.engines().then(setEngines).catch(() => {}) }, [refreshProjects])
  useEffect(() => { localStorage.setItem('fs.panelOpen', panelOpen ? '1' : '0') }, [panelOpen])
  useEffect(() => { localStorage.setItem('fs.panelWidth', String(panelWidth)) }, [panelWidth])

  // load current project + poll while processing
  useEffect(() => {
    timeRef.current = 0; setTime(0); setTotal(0)
    if (!currentId) { setMeta(null); setResult(null); return }
    localStorage.setItem('fs.current', currentId)
    let stop = false
    let timer: number | undefined
    const load = async () => {
      try {
        const p = await api.project(currentId)
        if (stop) return
        setMeta(p.meta)
        setStatus(p.status)
        if (p.status.state === 'done' && p.result) {
          setResult(p.result)
          setVersion(String(p.meta.updated))
          refreshProjects()
        } else if (p.status.state === 'queued' || p.status.state === 'running') {
          timer = window.setTimeout(load, 600)
        } else refreshProjects()
      } catch {
        if (!stop) { setCurrentId(null); localStorage.removeItem('fs.current') }
      }
    }
    load()
    return () => { stop = true; clearTimeout(timer) }
  }, [currentId, reloadKey, refreshProjects])

  const onPosition = useCallback((t: number, tot: number) => {
    timeRef.current = t
    setTime(t)
    setTotal(tot)
  }, [])

  useMetronome(metronome && playing, result, timeRef, volume)

  // keyboard: space = play/pause
  useEffect(() => {
    const h = (e: KeyboardEvent) => {
      const el = e.target as HTMLElement
      if (e.code === 'Space' && !['INPUT', 'SELECT', 'TEXTAREA'].includes(el.tagName) && !el.isContentEditable) {
        e.preventDefault(); scoreRef.current?.playPause()
      }
    }
    window.addEventListener('keydown', h)
    return () => window.removeEventListener('keydown', h)
  }, [])

  const rearrange = async (body: Parameters<typeof api.arrange>[1]) => {
    if (!currentId) return
    scoreRef.current?.stop()
    await api.arrange(currentId, body)
    setStatus({ state: 'queued', progress: 0, stage: 'queued', message: 'Queued' })
    setReloadKey(k => k + 1)  // re-runs the loader below, which polls until the job is done
  }

  const rename = async (title: string) => {
    if (!currentId || !title.trim() || title === meta?.title) return
    const r = await api.rename(currentId, title.trim())
    setMeta(r.meta)
    setResult(res => (res ? { ...res, title: r.meta.title } : res))
    refreshProjects()
  }

  const switchSource = (s: PlaybackSource) => {
    if (s === source) return
    const wasPlaying = playing
    setSource(s)
    scoreRef.current?.setSource(s, timeRef.current, wasPlaying)  // same position, keeps playing
  }

  const seek = (t: number) => { timeRef.current = t; setTime(t); scoreRef.current?.seekTime(t) }

  const busy = status?.state === 'queued' || status?.state === 'running'
  const opts = meta?.options
  const displayTempo = result ? Math.round(result.tempo * speed) : 0
  const duration = total || result?.duration || 0
  const shown = projects.filter(p => !query || p.title.toLowerCase().includes(query.toLowerCase()))
  const hasScore = !!(currentId && result && !busy)

  return (
    <div className={`app ${sidebarOpen ? '' : 'sidebar-collapsed'}`}>
      {/* ------------------------------------------------------------ sidebar */}
      <aside className="sidebar">
        <div className="brand-row">
          <div className="brand"><img src="/logo.svg" alt="" width={26} height={26} /><span>tabscribe</span></div>
          <button className="icon-btn" onClick={() => setSidebarOpen(false)} title="Hide sidebar"><PanelLeft size={18} /></button>
        </div>
        <button className="btn-primary new-btn" onClick={() => setShowNew(true)}><Plus size={18} /> New project</button>
        <label className="search-box">
          <Search size={16} />
          <input placeholder="Search projects" value={query} onChange={e => setQuery(e.target.value)} />
          {query && <button className="icon-btn xs" onClick={() => setQuery('')} title="Clear"><X size={14} /></button>}
        </label>
        <div className="nav-label">Projects <span className="muted">{projects.length || ''}</span></div>
        <div className="recents">
          {shown.map(p => (
            <button key={p.id} className={`recent ${p.id === currentId ? 'active' : ''}`} onClick={() => setCurrentId(p.id)} title={p.title}>
              <FileMusic size={17} className={p.id === currentId ? 'accent' : ''} />
              <span className="ellipsis">{p.title}</span>
              {(p.state === 'queued' || p.state === 'running') && <Loader2 size={14} className="spin" />}
            </button>
          ))}
          {projects.length === 0 && <div className="muted small pad">No projects yet</div>}
          {projects.length > 0 && shown.length === 0 && <div className="muted small pad">No match for “{query}”</div>}
        </div>
      </aside>

      <div className="content">
        <header className="topbar">
          <div className="topbar-left">
            {!sidebarOpen && <button className="icon-btn" onClick={() => setSidebarOpen(true)} title="Show sidebar"><PanelLeft size={18} /></button>}
            <div className="seg view-seg">
              <button className="on" title="View"><Eye size={16} /> <span className="lbl">View</span></button>
              <button disabled title="Editing is coming soon"><Pencil size={15} /> <span className="lbl">Edit</span> <span className="soon">Soon</span></button>
            </div>
          </div>
          <div className="transport">
            <div className="transport-row">
              <div className="seg src-seg">
                <button className={source === 'transcribed' ? 'on' : ''} onClick={() => switchSource('transcribed')} title="Play the transcription"><Music2 size={16} /> <span className="lbl">Transcribed</span></button>
                <button className={source === 'original' ? 'on' : ''} onClick={() => switchSource('original')} title="Play the original recording"><AudioLines size={16} /> <span className="lbl">Original</span></button>
              </div>
              <button className="icon-btn back-btn" disabled={!hasScore} onClick={() => scoreRef.current?.stop()} title="Back to start"><SkipBack size={17} /></button>
              <button className="play-btn" disabled={!hasScore || (!ready && source === 'transcribed')} onClick={() => scoreRef.current?.playPause()} title="Play / pause (space)">
                {playing ? <Pause size={18} fill="#111" /> : <Play size={18} fill="#111" />}
              </button>
              <span className="time">{fmt(time)}<span className="time-total"> / {fmt(duration)}</span></span>
              <div className="transport-extra">
                <button className={`icon-btn ${metronome ? 'on' : ''}`} disabled={!hasScore} title={metronome ? 'Metronome on (clicks on every beat)' : 'Metronome off'}
                  onClick={() => setMetronome(m => !m)}><Timer size={17} /></button>
                <VolumeButton value={volume} onChange={v => { setVolume(v); scoreRef.current?.setVolume(v) }} />
                <SpeedButton tempo={displayTempo} speed={speed} onChange={s => { setSpeed(s); scoreRef.current?.setSpeed(s) }} />
                {result && <span className="pill key-pill" title="Key">{KEY_GLYPH(result.key.accidentals)} {result.key.name}</span>}
              </div>
              <MoreMenu hasScore={hasScore} metronome={metronome} onMetronome={() => setMetronome(m => !m)}
                volume={volume} onVolume={v => { setVolume(v); scoreRef.current?.setVolume(v) }}
                tempo={displayTempo} speed={speed} onSpeed={s => { setSpeed(s); scoreRef.current?.setSpeed(s) }}
                keyName={result ? `${KEY_GLYPH(result.key.accidentals)} ${result.key.name}` : undefined} />
            </div>
            <Seekbar time={time} duration={duration} disabled={!hasScore} onSeek={seek} />
          </div>
          <div className="topbar-right">
            {currentId && <ShareButton id={currentId} title={meta?.title ?? 'score'} disabled={!hasScore} />}
            {currentId && <DownloadButton id={currentId} title={meta?.title ?? 'score'} disabled={!hasScore}
              onPrint={() => { scoreRef.current?.print().catch(() => window.print()) }} />}
            <button className="icon-btn boxed" onClick={() => setShowSettings(true)} title="Settings"><Settings size={18} /></button>
          </div>
        </header>
        <div className="content-body">
      {/* ------------------------------------------------------- project panel */}
      {currentId && meta && panelOpen && (
        <section className="panel" style={{ width: panelWidth }}>
          <EditableTitle className="panel-title" value={meta.title} onSave={rename} />
          <Dropdown
            label={<><Guitar size={15} /> Instruments</>}
            items={INSTRUMENTS.map(i => ({ key: i.id, label: i.label, hint: i.hint, active: !!opts?.separate === i.separate }))}
            onSelect={k => { const i = INSTRUMENTS.find(x => x.id === k)!; if (!!opts?.separate !== i.separate) rearrange({ separate: i.separate }) }}
            small
          />
          <div className="panel-actions">
            <ActionRow icon={<RefreshCw size={18} />} title="Re-transcribe" sub={`Engine: ${engineLabel(opts?.engine, meta.engine)}`} onClick={() => setShowEngines(true)} />
            <TransposeRow value={opts?.transpose ?? 0} capo={opts?.capo ?? 0} tuning={opts?.tuning ?? 'standard'} tunings={engines?.tunings ?? ['standard']}
              onChange={b => rearrange(b)} disabled={busy} />
            <CapoRow capo={opts?.capo ?? 0} hint={result?.capo_suggestion} keyName={result?.key?.name}
              onChange={c => rearrange({ capo: c })} disabled={busy} />
          </div>
          <Dropdown
            label={<span className="diff-label"><Volume2 size={16} /> <span className="muted">Guitar sound</span></span>}
            value={soundById(soundId).short}
            items={GUITAR_SOUNDS.map(g => ({ key: g.id, label: g.label, hint: g.hint, active: g.id === soundId }))}
            onSelect={chooseSound}
            block
          />
          <Dropdown
            label={<span className="diff-label"><Timer size={16} /> <span className="muted">Time signature</span></span>}
            value={(opts?.beats_per_bar ?? 0) ? `${opts?.beats_per_bar}/4` : `Auto${result ? ` ${result.beats_per_bar}/4` : ''}`}
            items={[0, 2, 3, 4].map(b => ({ key: String(b), label: b ? `${b}/4` : 'Auto-detect', active: (opts?.beats_per_bar ?? 0) === b }))}
            onSelect={k => Number(k) !== (opts?.beats_per_bar ?? 0) && rearrange({ beats_per_bar: Number(k) })}
            block
          />
          <Dropdown
            label={<span className="diff-label"><Gauge size={16} /> <span className="muted">Difficulty</span></span>}
            value={DIFFICULTIES.find(d => d[0] === (opts?.difficulty ?? 'original'))?.[1]}
            items={DIFFICULTIES.map(([k, l]) => ({ key: k, label: l, active: (opts?.difficulty ?? 'original') === k }))}
            onSelect={k => k !== opts?.difficulty && rearrange({ difficulty: k })}
            block
          />
          {result && (
            <div className="panel-stats muted small">
              {result.stats.placed} notes · {result.stats.bars} bars · key {result.key.name} · {engineLabel(result.engine)}{result.arranger?.startsWith('open-fret+') ? ' · Open-Fret fingering' : ''}
            </div>
          )}
          <div className="panel-bottom">
            <button className="link-row danger" onClick={() => setConfirmDelete(true)}>
              <Trash2 size={17} /> Delete project
            </button>
          </div>
        </section>
      )}
      {currentId && meta && (
        <PanelHandle open={panelOpen} width={panelWidth} onToggle={() => setPanelOpen(o => !o)} onResize={setPanelWidth} />
      )}
      {/* --------------------------------------------------------------- main */}
      <main className="main">
        <div className={`workspace ${rollExpanded ? 'roll-expanded' : ''} ${hasScore ? '' : 'no-roll'}`}>
          <div className={`score-area ${currentId && busy ? 'dark' : ''}`}>
            {!currentId && <Welcome onNew={() => setShowNew(true)} />}
            {currentId && busy && <ProcessingCard key={currentId} status={status} meta={meta} />}
            {currentId && status?.state === 'error' && (
              <div className="center-msg"><h3>Transcription failed</h3><p className="muted">{meta?.error}</p>
                <button className="btn-primary" onClick={() => rearrange({})}><RefreshCw size={16} /> Try again</button></div>
            )}
            {hasScore && (
              <ScoreView
                ref={scoreRef}
                gpUrl={api.file(currentId!, 'score.gp5', version)}
                audioUrl={api.file(currentId!, 'audio.wav')}
                result={result!}
                title={meta?.title ?? ''}
                onRename={rename}
                onPosition={onPosition}
                onPlaying={setPlaying}
                onReady={setReady}
                soundFont={soundById(soundId).url}
              />
            )}
          </div>
          {hasScore && (
            <PianoRoll result={result!} timeRef={timeRef} mode={rollMode} onMode={setRollMode}
              expanded={rollExpanded} onExpand={() => setRollExpanded(e => !e)} onSeek={seek} />
          )}
        </div>
      </main>
        </div>
      </div>

      {showNew && <NewProjectFlow engines={engines} onClose={() => setShowNew(false)} onCreated={m => { setShowNew(false); setResult(null); setStatus({ state: 'queued', progress: 0, stage: 'queued' }); setCurrentId(m.id); refreshProjects() }} />}
      {showEngines && (
        <EnginesModal engines={engines} current={opts} onClose={() => setShowEngines(false)}
          onApply={b => { setShowEngines(false); rearrange(b) }} canApply={!!currentId && !busy} />
      )}
      {showSettings && <SettingsModal engines={engines} onClose={() => setShowSettings(false)} />}
      {confirmDelete && meta && currentId && (
        <Modal title="Delete project?" onClose={() => setConfirmDelete(false)}>
          <p className="modal-text">“{meta.title}” and its transcription, tabs and audio will be permanently deleted from this computer. This can’t be undone.</p>
          <div className="modal-actions">
            <button className="btn-ghost" autoFocus onClick={() => setConfirmDelete(false)}>Cancel</button>
            <button className="btn-danger" onClick={() => {
              setConfirmDelete(false)
              scoreRef.current?.stop()
              api.remove(currentId).then(() => { setCurrentId(null); localStorage.removeItem('fs.current'); refreshProjects() })
            }}><Trash2 size={16} /> Delete</button>
          </div>
        </Modal>
      )}
    </div>
  )
}

function engineLabel(opt?: string, used?: string) {
  const names: Record<string, string> = { vote: 'Vote', muscriptor: 'MuScriptor', 'basic-pitch': 'Basic Pitch', ensemble: 'Ensemble', auto: 'Auto' }
  return names[used ?? opt ?? 'auto'] ?? 'Auto'
}

// ------------------------------------------------------------------ pieces
function ActionRow({ icon, title, sub, onClick }: { icon: React.ReactNode; title: string; sub?: string; onClick: () => void }) {
  return (
    <button className="action-row" onClick={onClick}>
      {icon}
      <div><div>{title}</div>{sub && <div className="accent small">{sub}</div>}</div>
    </button>
  )
}

function TransposeRow({ value, capo, tuning, tunings, onChange, disabled }: {
  value: number; capo: number; tuning: string; tunings: string[]; disabled: boolean
  onChange: (b: { transpose?: number; capo?: number; tuning?: string }) => void
}) {
  const [open, setOpen] = useState(false)
  const [t, setT] = useState(value), [c, setC] = useState(capo), [tu, setTu] = useState(tuning)
  useEffect(() => { setT(value); setC(capo); setTu(tuning) }, [value, capo, tuning])
  return (
    <div>
      <button className="action-row" onClick={() => setOpen(!open)}>
        <ArrowUpDown size={18} />
        <div><div>Transpose</div>{(value !== 0 || capo !== 0 || tuning !== 'standard') &&
          <div className="accent small">{value > 0 ? `+${value}` : value} st · capo {capo} · {tuning.replace(/_/g, ' ')}</div>}</div>
      </button>
      {open && (
        <div className="transpose-box">
          <label>Semitones <div className="stepper"><button onClick={() => setT(Math.max(-12, t - 1))}>−</button><span>{t > 0 ? `+${t}` : t}</span><button onClick={() => setT(Math.min(12, t + 1))}>+</button></div></label>
          <label>Capo <div className="stepper"><button onClick={() => setC(Math.max(0, c - 1))}>−</button><span>{c}</span><button onClick={() => setC(Math.min(12, c + 1))}>+</button></div></label>
          <label>Tuning <select value={tu} onChange={e => setTu(e.target.value)}>{tunings.map(x => <option key={x} value={x}>{x.replace(/_/g, ' ')}</option>)}</select></label>
          <button className="btn-primary sm" disabled={disabled} onClick={() => { setOpen(false); onChange({ transpose: t, capo: c, tuning: tu }) }}>Apply</button>
        </div>
      )}
    </div>
  )
}

function CapoRow({ capo, hint, keyName, onChange, disabled }: {
  capo: number; hint?: Result['capo_suggestion']; keyName?: string; disabled: boolean; onChange: (c: number) => void
}) {
  const suggested = hint?.capo ?? 0
  return (
    <div className="capo-row">
      <div className="capo-head">
        <span>Capo</span>
        <div className="stepper">
          <button disabled={disabled || capo <= 0} onClick={() => onChange(capo - 1)}>−</button>
          <span>{capo === 0 ? 'None' : capo}</span>
          <button disabled={disabled || capo >= 12} onClick={() => onChange(capo + 1)}>+</button>
        </div>
      </div>
      {hint && (suggested !== capo ? (
        <button className="capo-hint" disabled={disabled} onClick={() => onChange(suggested)}
          title={hint.shapes.join(' · ')}>
          <span className="accent">{suggested === 0 ? 'Suggested: no capo' : `Suggested: capo ${suggested}`}</span>
          {suggested > 0 && hint.key_shape && <span className="muted small">{keyName} played as {hint.key_shape} shapes: {hint.shapes.slice(0, 5).join(', ')}</span>}
        </button>
      ) : (
        <div className="capo-hint ok"><span className="muted small">{capo === 0 ? 'No capo needed' : `Capo ${capo} is the easiest position${hint.key_shape ? ` (${hint.key_shape} shapes)` : ''}`}</span></div>
      ))}
    </div>
  )
}

function Dropdown({ label, value, items, onSelect, small, block }: {
  label: React.ReactNode; value?: string; small?: boolean; block?: boolean
  items: { key: string; label: string; hint?: string; active?: boolean }[]; onSelect: (k: string) => void
}) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    const h = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false) }
    document.addEventListener('mousedown', h)
    return () => document.removeEventListener('mousedown', h)
  }, [])
  return (
    <div className={`dropdown ${small ? 'small' : ''} ${block ? 'block' : ''}`} ref={ref}>
      <button className="dropdown-btn" onClick={() => setOpen(!open)}>
        <span className="dd-label">{label}</span>{value && <span className="dd-value">{value}</span>}<ChevronDown size={15} />
      </button>
      {open && (
        <div className="menu">
          {items.map(i => (
            <button key={i.key} className="menu-item" onClick={() => { setOpen(false); onSelect(i.key) }}>
              <div><div>{i.label}</div>{i.hint && <div className="muted small">{i.hint}</div>}</div>
              {i.active && <Check size={15} className="accent" />}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

function SpeedButton({ tempo, speed, onChange }: { tempo: number; speed: number; onChange: (s: number) => void }) {
  const { open, setOpen, ref } = usePopover()
  return (
    <div className="dropdown" ref={ref}>
      <button className={`pill ${speed !== 1 ? 'pill-on' : ''}`} onClick={() => setOpen(!open)} title="Playback speed">♩ = {tempo || '–'}</button>
      {open && (
        <div className="menu narrow center">
          <div className="menu-head">Playback speed</div>
          {[0.5, 0.75, 0.9, 1, 1.1, 1.25].map(s => (
            <button key={s} className="menu-item" onClick={() => { onChange(s); setOpen(false) }}>
              <span>{Math.round(s * 100)}%</span>{s === speed && <Check size={14} className="accent" />}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

/** Secondary transport controls, shown in a menu when the top bar is too narrow for them. */
function MoreMenu({ hasScore, metronome, onMetronome, volume, onVolume, tempo, speed, onSpeed, keyName }: {
  hasScore: boolean; metronome: boolean; onMetronome: () => void; volume: number; onVolume: (v: number) => void
  tempo: number; speed: number; onSpeed: (s: number) => void; keyName?: string
}) {
  const { open, setOpen, ref } = usePopover()
  return (
    <div className="dropdown transport-more" ref={ref}>
      <button className={`icon-btn ${open ? 'on' : ''}`} onClick={() => setOpen(!open)} title="More playback controls"><MoreHorizontal size={18} /></button>
      {open && (
        <div className="menu right more-menu">
          <button className="menu-item" disabled={!hasScore} onClick={onMetronome}>
            <span className="more-label"><Timer size={16} /> Metronome</span>
            <span className={`switch ${metronome ? 'on' : ''}`} />
          </button>
          <div className="menu-head">Speed · ♩ = {tempo || '–'}</div>
          <div className="speed-grid">
            {[0.5, 0.75, 0.9, 1, 1.1, 1.25].map(s => (
              <button key={s} className={s === speed ? 'on' : ''} onClick={() => onSpeed(s)}>{Math.round(s * 100)}%</button>
            ))}
          </div>
          <div className="menu-head">Volume · {Math.round(volume * 100)}%</div>
          <div className="pad-x"><input className="range" type="range" min={0} max={1} step={0.01} value={volume} onChange={e => onVolume(Number(e.target.value))} /></div>
          {keyName && <div className="menu-head more-key">Key <b>{keyName}</b></div>}
        </div>
      )}
    </div>
  )
}

function VolumeButton({ value, onChange }: { value: number; onChange: (v: number) => void }) {
  const { open, setOpen, ref } = usePopover()
  return (
    <div className="dropdown" ref={ref}>
      <button className={`icon-btn ${open ? 'on' : ''}`} onClick={() => setOpen(!open)} title="Volume"><SlidersHorizontal size={17} /></button>
      {open && (
        <div className="menu narrow center pad">
          <div className="menu-head">Volume · {Math.round(value * 100)}%</div>
          <input className="range" type="range" min={0} max={1} step={0.01} value={value} onChange={e => onChange(Number(e.target.value))} />
        </div>
      )}
    </div>
  )
}

function Welcome({ onNew }: { onNew: () => void }) {
  return (
    <div className="center-msg">
      <img src="/logo.svg" width={56} height={56} alt="" />
      <h2>Turn any guitar recording into score + tab</h2>
      <p className="muted">Everything runs on this computer: a multi-model transcription vote, beat & downbeat tracking that follows live playing, chord detection and playable fingering.</p>
      <button className="btn-primary" onClick={onNew}><Plus size={18} /> New project</button>
    </div>
  )
}

function Modal({ title, children, onClose, wide }: { title: string; children: React.ReactNode; onClose: () => void; wide?: boolean }) {
  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') onClose() }
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [onClose])
  return (
    <div className="modal-bg" onMouseDown={e => e.target === e.currentTarget && onClose()}>
      <div className={`modal ${wide ? 'wide' : ''}`}>
        <div className="modal-head"><h3>{title}</h3><button className="icon-btn" onClick={onClose}><X size={18} /></button></div>
        {children}
      </div>
    </div>
  )
}

function EnginesModal({ engines, current, onClose, onApply, canApply }: {
  engines: Engines | null; current?: Meta['options']; onClose: () => void; canApply: boolean
  onApply: (b: { engine: string; muscriptor_size: string }) => void
}) {
  const [engine, setEngine] = useState(current?.engine ?? 'auto')
  const [size, setSize] = useState(current?.muscriptor_size ?? 'medium')
  const ms = engines?.muscriptor
  return (
    <Modal title="AI engines" onClose={onClose}>
      <div className="engine-list">
        {(['auto', 'vote', 'ensemble', 'muscriptor', 'basic-pitch'] as const).map(e => {
          const avail = e === 'vote' ? !!engines?.vote?.available : e === 'muscriptor' || e === 'ensemble' ? !!ms?.available : true
          return (
            <button key={e} className={`choice-item ${engine === e ? 'on' : ''}`} disabled={!avail} onClick={() => setEngine(e)}>
              <Cpu size={16} />
              <div>
                <div>{{ auto: 'Auto (best available)', vote: `Vote — ${ms?.available ? '7 models (Tsumugi ×4, Transkun, MuScriptor, Basic Pitch)' : '6 models (Tsumugi ×4, Transkun, Basic Pitch)'}`, ensemble: 'Ensemble — MuScriptor + Basic Pitch', 'basic-pitch': 'Basic Pitch — Spotify', muscriptor: 'MuScriptor — Kyutai × Mirelo' }[e]}</div>
                <div className="muted small">
                  {e === 'auto' && 'The model vote when its models are installed, otherwise the best available'}
                  {e === 'vote' && `Majority vote of ${ms?.available ? 7 : 6} transcribers (4 must agree) — most accurate (note F1 0.97 on the reference clip), ~75 s per song`}
                  {e === 'ensemble' && (avail ? 'Keeps the notes both models agree on — faster than the vote (F1 0.89 on the reference clip)' : ms?.help)}
                  {e === 'basic-pitch' && 'Fast polyphonic model (ONNX), high recall, cleaned for overtones and re-attacks'}
                  {e === 'muscriptor' && (avail ? 'Transformer transcription restricted to guitar (non-commercial weights)' : ms?.help)}
                </div>
              </div>
            </button>
          )
        })}
      </div>
      {(engine === 'muscriptor' || engine === 'ensemble' || engine === 'vote' || engine === 'auto') && (
        <label className="row-label">Model size
          <select value={size} onChange={e => setSize(e.target.value)}>
            <option value="small">Small (0.4 GB)</option><option value="medium">Medium (1.2 GB)</option><option value="large">Large (5.5 GB)</option>
          </select>
        </label>
      )}
      <div className="pipeline">
        <div className="settings-head">Pipeline</div>
        <ol className="pipeline-steps">
          <li><b>Guitar isolation</b> <span className="muted">— {engines?.separation?.label ?? 'guitar stem model'} (only for band mixes)</span></li>
          <li><b>Transcription</b> <span className="muted">— majority vote of Tsumugi ×4, Transkun, MuScriptor, Basic Pitch</span></li>
          <li><b>Cleanup</b> <span className="muted">— overtones, re-attacks, chord-onset alignment</span></li>
          <li><b>Beats &amp; downbeats</b> <span className="muted">— Beat This! + DBN (bar phase and meter)</span></li>
          <li><b>Tempo normalisation</b> <span className="muted">— beats re-aligned on the note attacks so live playing without a metronome lands on a clean grid</span></li>
          <li><b>Quantization</b> <span className="muted">— 16ths / triplets per beat, rolled chords</span></li>
          <li><b>Fingering</b> <span className="muted">— Open-Fret + tab-labeler beam search, capo-aware</span></li>
          <li><b>Harmony</b> <span className="muted">— chords, key, capo suggestion</span></li>
          <li><b>Engraving</b> <span className="muted">— Guitar Pro, MIDI, PDF</span></li>
        </ol>
      </div>
      <button className="btn-primary" disabled={!canApply} onClick={() => onApply({ engine, muscriptor_size: size })}><RefreshCw size={16} /> Re-transcribe</button>
    </Modal>
  )
}

// ------------------------------------------------------------ new pieces
const safeName = (t: string) => (t || 'score').replace(/[\\/:*?"<>|]+/g, '-').trim()

const EXPORTS: { file: string; ext: string; label: string; hint: string }[] = [
  { file: 'score.gp5', ext: 'gp5', label: 'Guitar Pro (.gp5)', hint: 'Score + tab — MuseScore, TuxGuitar, Guitar Pro' },
  { file: 'score.mid', ext: 'mid', label: 'MIDI — score', hint: 'Quantized to the beat grid' },
  { file: 'performance.mid', ext: 'mid', label: 'MIDI — performance', hint: 'Original timing of the recording' },
]

function usePopover() {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!open) return
    const h = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false) }
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape') setOpen(false) }
    document.addEventListener('mousedown', h); document.addEventListener('keydown', k)
    return () => { document.removeEventListener('mousedown', h); document.removeEventListener('keydown', k) }
  }, [open])
  return { open, setOpen, ref }
}

function DownloadButton({ id, title, disabled, onPrint }: { id: string; title: string; disabled: boolean; onPrint: () => void }) {
  const { open, setOpen, ref } = usePopover()
  return (
    <div className="dropdown" ref={ref}>
      <button className="btn-primary top-btn" disabled={disabled} onClick={() => setOpen(!open)}>
        <Download size={17} /> <span className="btn-text">Download</span> <ChevronDown size={15} />
      </button>
      {open && (
        <div className="menu right">
          {EXPORTS.map(x => (
            <a key={x.file} className="menu-item" href={api.file(id, x.file)} download={`${safeName(title)}${x.file === 'performance.mid' ? ' (performance)' : ''}.${x.ext}`} onClick={() => setOpen(false)}>
              <div><div>{x.label}</div><div className="muted small">{x.hint}</div></div><Download size={15} />
            </a>
          ))}
          <button className="menu-item" onClick={() => { setOpen(false); setTimeout(onPrint, 50) }}>
            <div><div>PDF / Print</div><div className="muted small">Score and tablature, page layout</div></div><Printer size={15} />
          </button>
        </div>
      )}
    </div>
  )
}

type Bridge = { share?: (files: { url: string; name: string }[]) => Promise<boolean>; isDesktop?: boolean }
const bridge = (window as unknown as { tabscribe?: Bridge }).tabscribe

function ShareButton({ id, title, disabled }: { id: string; title: string; disabled: boolean }) {
  const { open, setOpen, ref } = usePopover()
  const [note, setNote] = useState('')
  const flash = (m: string) => { setNote(m); setTimeout(() => setNote(''), 2200) }
  const shareFile = async (file: string, ext: string) => {
    setOpen(false)
    const name = `${safeName(title)}.${ext}`
    const url = new URL(api.file(id, file), location.href).href
    try {
      if (bridge?.share) { if (await bridge.share([{ url, name }])) return }
      const blob = await (await fetch(url)).blob()
      const f = new File([blob], name, { type: blob.type || 'application/octet-stream' })
      if (navigator.canShare?.({ files: [f] })) { await navigator.share({ files: [f], title }); return }
      const a = document.createElement('a'); a.href = url; a.download = name; a.click()
      flash('Sharing isn’t available here — file saved instead')
    } catch (e) {
      if ((e as Error).name !== 'AbortError') flash('Could not share this file')
    }
  }
  return (
    <div className="dropdown" ref={ref}>
      <button className="btn-secondary top-btn" disabled={disabled} onClick={() => setOpen(!open)} title={IS_MAC ? 'Share via AirDrop, Messages, Mail…' : 'Share or save the file'}>
        <Share size={16} /> <span className="btn-text">Share</span>
      </button>
      {open && (
        <div className="menu right">
          <button className="menu-item" onClick={() => shareFile('score.gp5', 'gp5')}>
            <div><div>Share tab (.gp5)</div><div className="muted small">{IS_MAC ? 'AirDrop, Messages, Mail…' : 'Guitar Pro, TuxGuitar, MuseScore…'}</div></div><Share size={15} />
          </button>
          <button className="menu-item" onClick={() => shareFile('score.mid', 'mid')}>
            <div><div>Share MIDI</div><div className="muted small">For a DAW or notation app</div></div><Share size={15} />
          </button>
        </div>
      )}
      {note && <div className="toast">{note}</div>}
    </div>
  )
}

function Seekbar({ time, duration, disabled, onSeek }: { time: number; duration: number; disabled: boolean; onSeek: (t: number) => void }) {
  const ref = useRef<HTMLDivElement>(null)
  const [hover, setHover] = useState<number | null>(null)
  const [drag, setDrag] = useState(false)
  const at = (clientX: number) => {
    const r = ref.current!.getBoundingClientRect()
    return Math.max(0, Math.min(1, (clientX - r.left) / r.width)) * duration
  }
  useEffect(() => {
    if (!drag) return
    const move = (e: PointerEvent) => onSeek(at(e.clientX))
    const up = () => setDrag(false)
    window.addEventListener('pointermove', move); window.addEventListener('pointerup', up)
    return () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up) }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [drag, duration])
  const pct = duration ? Math.min(100, (time / duration) * 100) : 0
  return (
    <div ref={ref} className={`seekbar ${disabled ? 'disabled' : ''} ${drag ? 'drag' : ''}`}
      onPointerDown={e => { if (disabled || !duration) return; onSeek(at(e.clientX)); setDrag(true) }}
      onPointerMove={e => !disabled && duration && setHover(at(e.clientX))} onPointerLeave={() => setHover(null)}>
      <div className="seek-track"><div className="seek-fill" style={{ width: `${pct}%` }} /><div className="seek-thumb" style={{ left: `${pct}%` }} /></div>
      {hover !== null && !drag && <div className="seek-tip" style={{ left: `${(hover / duration) * 100}%` }}>{fmt(hover)}</div>}
    </div>
  )
}

/** Edge between the project panel and the score: hover shows it, click collapses/expands, drag resizes. */
function PanelHandle({ open, width, onToggle, onResize }: { open: boolean; width: number; onToggle: () => void; onResize: (w: number) => void }) {
  const start = useRef<{ x: number; w: number; moved: boolean } | null>(null)
  const [dragging, setDragging] = useState(false)
  useEffect(() => {
    const move = (e: PointerEvent) => {
      const s = start.current
      if (!s) return
      if (Math.abs(e.clientX - s.x) > 3) { s.moved = true; setDragging(true) }
      if (s.moved && open) onResize(Math.max(220, Math.min(460, s.w + e.clientX - s.x)))
    }
    const up = () => {
      const s = start.current
      start.current = null
      setDragging(false)
      document.body.classList.remove('resizing')
      if (s && !s.moved) onToggle()
    }
    window.addEventListener('pointermove', move); window.addEventListener('pointerup', up)
    return () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up) }
  }, [open, onToggle, onResize])
  return (
    <div className={`panel-handle ${open ? 'open' : 'closed'} ${dragging ? 'dragging' : ''}`}
      title={open ? 'Click to hide the panel · drag to resize' : 'Click to show the panel'}
      onPointerDown={e => { e.preventDefault(); start.current = { x: e.clientX, w: width, moved: false }; if (open) document.body.classList.add('resizing') }}
      onDoubleClick={e => { e.preventDefault(); if (open) onResize(280) }}>
      <div className="handle-line" />
      <div className="handle-knob">{open ? <ChevronLeft size={13} /> : <ChevronRight size={13} />}</div>
    </div>
  )
}

/** Click track on the tracked beats (works for both the synth and the original recording). */
function useMetronome(on: boolean, result: Result | null, timeRef: React.MutableRefObject<number>, volume: number) {
  useEffect(() => {
    if (!on || !result) return
    const ctx = new AudioContext()
    const beats = result.grid.beats
    const first = result.grid.first_beat_index
    const bpb = result.beats_per_bar
    let last = timeRef.current
    let raf = 0
    const click = (accent: boolean) => {
      const o = ctx.createOscillator(), g = ctx.createGain()
      o.frequency.value = accent ? 1760 : 1175
      g.gain.setValueAtTime(0.0001, ctx.currentTime)
      g.gain.exponentialRampToValueAtTime(0.5 * volume + 0.05, ctx.currentTime + 0.002)
      g.gain.exponentialRampToValueAtTime(0.0001, ctx.currentTime + 0.06)
      o.connect(g).connect(ctx.destination); o.start(); o.stop(ctx.currentTime + 0.07)
    }
    const loop = () => {
      const t = timeRef.current
      if (t > last && t - last < 0.25) {
        for (let i = 0; i < beats.length; i++) {
          if (beats[i] > last && beats[i] <= t) click(i >= first && (i - first) % bpb === 0)
        }
      }
      last = t
      raf = requestAnimationFrame(loop)
    }
    raf = requestAnimationFrame(loop)
    return () => { cancelAnimationFrame(raf); void ctx.close() }
  }, [on, result, timeRef, volume])
}

function ComponentsSection() {
  const [st, setSt] = useState<SetupStatus | null>(null)
  useEffect(() => { setupBridge?.status().then(setSt).catch(() => {}) }, [])
  if (!setupBridge) return null
  const installed = st?.components.filter(c => c.installed) ?? []
  const missing = st?.components.filter(c => !c.installed) ?? []
  return (
    <div className="settings-section">
      <div className="settings-head">Components</div>
      <div className="muted small">
        {st ? <>{installed.length} installed ({bytes(installed.reduce((s, c) => s + c.installed_size, 0))})
          {missing.length > 0 && <> · available: {missing.map(c => c.name).join(', ')}</>}</> : `Engine and AI models installed on this ${DEVICE}.`}
      </div>
      <div><button className="btn-ghost" onClick={() => setupBridge?.open()}>Manage, check or repair…</button></div>
    </div>
  )
}

function SettingsModal({ engines, onClose }: { engines: Engines | null; onClose: () => void }) {
  const installed = engines ? Object.entries(engines).filter(([k]) => k !== 'tunings') as [string, { available: boolean; label: string }][] : []
  return (
    <Modal title="Settings" onClose={onClose} wide>
      <div className="settings-section">
        <div className="settings-head">Transcription models</div>
        <PipelineDiagram engines={engines} />
        <div className="muted small">Choose the engine per project with “Re-transcribe” in the project panel.</div>
        <div className="model-list">
          {installed.map(([k, v]) => (
            <div key={k} className="model-row"><span>{v.label}</span>
              <span className={`badge ${v.available ? '' : 'off'}`}>{v.available ? 'Installed' : 'Not installed'}</span></div>
          ))}
        </div>
      </div>
      <ComponentsSection />
      <div className="settings-section">
        <div className="settings-head">Keyboard</div>
        <div className="kbd-row"><kbd>Space</kbd> Play / pause</div>
        <div className="kbd-row"><kbd>Scroll</kbd> over the piano roll to scrub</div>
        <div className="kbd-row"><kbd>Double-click</kbd> a title to rename it</div>
      </div>
    </Modal>
  )
}
