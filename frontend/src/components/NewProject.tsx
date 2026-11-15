import { useCallback, useEffect, useRef, useState } from 'react'
import {
  X, Upload, Play, Pause, Guitar, Layers, AudioLines, FileMusic, Loader2, Check, Gauge, Music2,
} from 'lucide-react'
import { api, type Engines, type Meta, type Status } from '../api'

/** m:ss (or m:ss.t with tenths) */
export const fmtTime = (s: number, tenths = false) => {
  if (!isFinite(s) || s < 0) s = 0
  const m = Math.floor(s / 60)
  const sec = s - m * 60
  const whole = Math.floor(sec)
  const base = `${m}:${whole.toString().padStart(2, '0')}`
  return tenths ? `${base}.${Math.floor((sec - whole) * 10)}` : base
}
const parseTime = (v: string): number | null => {
  const t = v.trim()
  if (!t) return null
  const parts = t.split(':')
  if (parts.length > 2 || parts.some(p => p === '' || isNaN(Number(p)))) return null
  return parts.length === 2 ? Number(parts[0]) * 60 + Number(parts[1]) : Number(parts[0])
}

const KEYS = ['C', 'G', 'D', 'A', 'E', 'B', 'F#', 'Db', 'Ab', 'Eb', 'Bb', 'F',
  'Am', 'Em', 'Bm', 'F#m', 'C#m', 'G#m', 'Dm', 'Gm', 'Cm', 'Fm', 'Bbm', 'Ebm']
const RESULTS = [
  { id: 'original', label: 'Full transcription', hint: 'Every note the guitar plays' },
  { id: 'intermediate', label: 'Simplified', hint: 'Bass, melody and one inner voice' },
  { id: 'beginner', label: 'Beginner', hint: 'Melody and bass, eighth notes, first frets' },
]
const SOURCES = [
  { separate: false, icon: Guitar, title: 'Solo guitar', text: 'Just the guitar, nothing else playing.', sub: 'Transcribed as it is.' },
  { separate: true, icon: Layers, title: 'Guitar with vocals or band', text: 'The guitar is part of a song with other sounds.', sub: 'We isolate the guitar first, then transcribe it.' },
]

type Step = 0 | 1 | 2 | 3

export function NewProjectFlow({ engines, onClose, onCreated }: {
  engines: Engines | null; onClose: () => void; onCreated: (m: Meta) => void
}) {
  const [step, setStep] = useState<Step>(0)
  const [file, setFile] = useState<File | null>(null)
  const [duration, setDuration] = useState(0)
  const [range, setRange] = useState<[number, number]>([0, 0])
  const [separate, setSeparate] = useState<boolean | null>(null)
  const [title, setTitle] = useState('')
  const [difficulty, setDifficulty] = useState('original')
  const [key, setKey] = useState('')
  const [bpb, setBpb] = useState(0)
  const [tuning, setTuning] = useState('standard')
  const [capo, setCapo] = useState(0)
  const [sending, setSending] = useState(false)
  const [err, setErr] = useState('')
  const sepAvailable = engines ? engines.separation?.available !== false : true

  const pick = (f?: File) => {
    if (!f) return
    setFile(f); setTitle(f.name.replace(/\.[^.]+$/, '')); setDuration(0); setRange([0, 0]); setErr('')
    setStep(1)
  }

  useEffect(() => {
    const k = (e: KeyboardEvent) => { if (e.key === 'Escape' && !sending) onClose() }
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [onClose, sending])

  const trimmed = duration > 0 && (range[0] > 0.05 || range[1] < duration - 0.05)
  const start = async () => {
    if (!file) return
    setSending(true); setErr('')
    try {
      onCreated(await api.create(file, {
        title, separate: !!separate, start: trimmed ? range[0] : 0, end: trimmed ? range[1] : 0,
        beats_per_bar: bpb, tuning, capo, key, difficulty,
      }))
    } catch (e) { setErr(String((e as Error).message)); setSending(false) }
  }

  const canContinue = step === 0 ? !!file : step === 1 ? !!file : step === 2 ? separate !== null : !sending
  const next = () => {
    if (step === 3) start()
    else if (canContinue) setStep((step + 1) as Step)
  }

  return (
    <div className="onb" role="dialog" aria-modal="true" aria-label="New project">
      <div className="onb-drag" />
      <button className="icon-btn onb-close" onClick={onClose} disabled={sending} title="Cancel (Esc)"><X size={20} /></button>
      <div className="onb-inner">
        <div className="onb-progress">
          {[1, 2, 3].map(i => <div key={i} className={i <= step ? 'on' : ''} />)}
        </div>
        <div className="onb-body">
          {step === 0 && <PickStep onPick={pick} />}
          {step === 1 && file && (
            <>
              <div className="onb-step">Step 1</div>
              <h1 className="onb-title">Trim your audio</h1>
              <p className="onb-sub"><b>{file.name}</b> · drag the handles to choose what to transcribe.</p>
              <Trimmer file={file} range={range} onRange={setRange}
                onDuration={d => { setDuration(d); setRange(r => (r[1] > 0 ? r : [0, d])) }} />
            </>
          )}
          {step === 2 && (
            <>
              <div className="onb-step">Step 2</div>
              <h1 className="onb-title">What’s in your recording?</h1>
              <div className="onb-cards">
                {SOURCES.map(s => {
                  const disabled = s.separate && !sepAvailable
                  return (
                    <button key={s.title} className={`onb-card ${separate === s.separate ? 'on' : ''}`} disabled={disabled}
                      onClick={() => { setSeparate(s.separate); setTimeout(() => setStep(3), 160) }}>
                      <s.icon size={30} strokeWidth={1.6} />
                      <div className="onb-card-title">{s.title}</div>
                      <div className="onb-card-text">{s.text}</div>
                      <div className="onb-card-sub">{disabled ? 'Guitar isolation isn’t installed on this computer' : s.sub}</div>
                    </button>
                  )
                })}
              </div>
            </>
          )}
          {step === 3 && file && (
            <>
              <div className="onb-step">Step 3</div>
              <h1 className="onb-title">Ready to transcribe</h1>
              <div className="onb-summary">
                <SummaryRow icon={<AudioLines size={20} />} label="Recording" value={file.name}
                  sub={duration ? `${fmtTime(range[0])} – ${fmtTime(range[1])}${trimmed ? ` · ${fmtTime(range[1] - range[0])} selected` : ''}` : undefined}
                  onEdit={() => setStep(1)} />
                <SummaryRow icon={separate ? <Layers size={20} /> : <Guitar size={20} />} label="Source"
                  value={separate ? 'Guitar with vocals or band' : 'Solo guitar'}
                  sub={separate ? 'Guitar isolated first' : undefined} onEdit={() => setStep(2)} />
                <ResultRow value={difficulty} onChange={setDifficulty} />
              </div>
              <div className="onb-details-head">Details <span className="muted">Optional</span></div>
              <div className="onb-details">
                <label className="onb-field wide">Title
                  <input className="onb-input" value={title} onChange={e => setTitle(e.target.value)} placeholder="Song title" />
                </label>
                <label className="onb-field">Key signature
                  <select className="onb-input" value={key} onChange={e => setKey(e.target.value)}>
                    <option value="">Auto-detect</option>
                    <optgroup label="Major">{KEYS.filter(k => !k.endsWith('m')).map(k => <option key={k} value={k}>{k.replace('b', '♭').replace('#', '♯')} major</option>)}</optgroup>
                    <optgroup label="Minor">{KEYS.filter(k => k.endsWith('m')).map(k => <option key={k} value={k}>{k.slice(0, -1).replace('b', '♭').replace('#', '♯')} minor</option>)}</optgroup>
                  </select>
                </label>
                <label className="onb-field">Time signature
                  <select className="onb-input" value={bpb} onChange={e => setBpb(Number(e.target.value))}>
                    <option value={0}>Auto-detect</option>
                    {[2, 3, 4].map(b => <option key={b} value={b}>{b}/4</option>)}
                  </select>
                </label>
                <label className="onb-field">Tuning
                  <select className="onb-input" value={tuning} onChange={e => setTuning(e.target.value)}>
                    {(engines?.tunings ?? ['standard']).map(t => <option key={t} value={t}>{tuningLabel(t)}</option>)}
                  </select>
                </label>
                <label className="onb-field">Capo
                  <select className="onb-input" value={capo} onChange={e => setCapo(Number(e.target.value))}>
                    {Array.from({ length: 13 }, (_, i) => <option key={i} value={i}>{i === 0 ? 'No capo' : `Fret ${i}`}</option>)}
                  </select>
                </label>
              </div>
            </>
          )}
          {err && <div className="error onb-err">{err}</div>}
        </div>
        <div className="onb-foot">
          <button className="btn-ghost onb-btn" onClick={() => (step === 0 ? onClose() : setStep((step - 1) as Step))} disabled={sending}>
            {step === 0 ? 'Cancel' : 'Back'}
          </button>
          {step === 3
            ? <button className="btn-primary onb-btn" onClick={start} disabled={sending}>
                {sending ? <Loader2 size={18} className="spin" /> : <Music2 size={18} />} Start transcription
              </button>
            : step > 0 && <button className="btn-primary onb-btn" onClick={next} disabled={!canContinue}>Continue</button>}
        </div>
      </div>
    </div>
  )
}

const tuningLabel = (t: string) => ({ standard: 'Standard (EADGBE)', drop_d: 'Drop D', half_step_down: 'Half step down', open_g: 'Open G', dadgad: 'DADGAD' } as Record<string, string>)[t] ?? t.replace(/_/g, ' ')

function PickStep({ onPick }: { onPick: (f?: File) => void }) {
  const [drag, setDrag] = useState(false)
  return (
    <>
      <div className="onb-step">New project</div>
      <h1 className="onb-title">Choose a guitar recording</h1>
      <label className={`onb-drop ${drag ? 'drag' : ''}`}
        onDragOver={e => { e.preventDefault(); setDrag(true) }} onDragLeave={() => setDrag(false)}
        onDrop={e => { e.preventDefault(); setDrag(false); onPick(e.dataTransfer.files[0]) }}>
        <input type="file" accept="audio/*,video/*,.mp3,.wav,.flac,.m4a,.ogg" hidden onChange={e => onPick(e.target.files?.[0])} />
        <div className="onb-drop-icon"><Upload size={26} /></div>
        <div className="onb-drop-title">Drop an audio file or click to browse</div>
        <div className="muted">MP3, WAV, FLAC, M4A, OGG, or a video file</div>
      </label>
    </>
  )
}

function SummaryRow({ icon, label, value, sub, onEdit }: { icon: React.ReactNode; label: string; value: string; sub?: string; onEdit: () => void }) {
  return (
    <div className="onb-row">
      <div className="onb-row-icon">{icon}</div>
      <div className="onb-row-text">
        <div className="muted">{label}</div>
        <div className="onb-row-value ellipsis">{value}</div>
        {sub && <div className="muted">{sub}</div>}
      </div>
      <button className="onb-edit" onClick={onEdit}>Edit</button>
    </div>
  )
}

function ResultRow({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const [open, setOpen] = useState(false)
  const cur = RESULTS.find(r => r.id === value) ?? RESULTS[0]
  return (
    <div className="onb-row col">
      <div className="onb-row-main">
        <div className="onb-row-icon"><FileMusic size={20} /></div>
        <div className="onb-row-text">
          <div className="muted">Result</div>
          <div className="onb-row-value">{cur.label} <span className="muted">· score + tab</span></div>
        </div>
        <button className="onb-edit" onClick={() => setOpen(o => !o)}>{open ? 'Done' : 'Edit'}</button>
      </div>
      {open && (
        <div className="onb-result-choices">
          {RESULTS.map(r => (
            <button key={r.id} className={`choice-item ${r.id === value ? 'on' : ''}`} onClick={() => { onChange(r.id); setOpen(false) }}>
              <Gauge size={16} /><div><div>{r.label}</div><div className="muted small">{r.hint}</div></div>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

// --------------------------------------------------------------- trimmer
const BARS = 160

function Trimmer({ file, range, onRange, onDuration }: {
  file: File; range: [number, number]; onRange: (r: [number, number]) => void; onDuration: (d: number) => void
}) {
  const [peaks, setPeaks] = useState<number[] | null>(null)
  const [duration, setDuration] = useState(0)
  const [failed, setFailed] = useState(false)
  const [playing, setPlaying] = useState(false)
  const [head, setHead] = useState(range[0])
  const audioRef = useRef<HTMLAudioElement>(null)
  const waveRef = useRef<HTMLDivElement>(null)
  const [url] = useState(() => URL.createObjectURL(file))
  const rangeRef = useRef(range)
  rangeRef.current = range
  useEffect(() => () => URL.revokeObjectURL(url), [url])

  // decode once for the waveform
  useEffect(() => {
    let alive = true
    const ctx = new AudioContext()
    file.arrayBuffer().then(b => ctx.decodeAudioData(b)).then(buf => {
      if (!alive) return
      const ch = buf.getChannelData(0)
      const step = Math.max(1, Math.floor(ch.length / BARS))
      const out: number[] = []
      for (let i = 0; i < BARS; i++) {
        let m = 0
        for (let j = i * step, e = Math.min(ch.length, j + step); j < e; j += 16) m = Math.max(m, Math.abs(ch[j]))
        out.push(m)
      }
      const max = Math.max(...out, 1e-6)
      setPeaks(out.map(v => Math.max(0.06, Math.sqrt(v / max))))
      setDuration(buf.duration)
      onDuration(buf.duration)
    }).catch(() => alive && setFailed(true)).finally(() => { void ctx.close() })
    return () => { alive = false }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [file])

  // playback inside the selection
  useEffect(() => {
    if (!playing) return
    let raf = 0
    const tick = () => {
      const a = audioRef.current
      if (!a) return
      if (a.currentTime >= rangeRef.current[1]) { a.pause(); a.currentTime = rangeRef.current[0]; setPlaying(false); setHead(rangeRef.current[0]); return }
      setHead(a.currentTime)
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [playing])

  const toggle = () => {
    const a = audioRef.current
    if (!a) return
    if (playing) { a.pause(); setPlaying(false); return }
    if (a.currentTime < range[0] || a.currentTime >= range[1] - 0.05) a.currentTime = range[0]
    a.play().then(() => setPlaying(true)).catch(() => {})
  }

  const frac = useCallback((clientX: number) => {
    const r = waveRef.current!.getBoundingClientRect()
    return Math.max(0, Math.min(1, (clientX - r.left) / r.width))
  }, [])
  const MIN = Math.min(1, duration)
  const dragHandle = (which: 0 | 1) => (e: React.PointerEvent) => {
    e.preventDefault(); e.stopPropagation()
    const move = (ev: PointerEvent) => {
      const t = frac(ev.clientX) * duration
      const [s, en] = rangeRef.current
      const nr: [number, number] = which === 0 ? [Math.min(t, en - MIN), en] : [s, Math.max(t, s + MIN)]
      onRange(nr)
      const a = audioRef.current
      if (a && which === 0 && !playing) { a.currentTime = nr[0]; setHead(nr[0]) }
    }
    const up = () => { window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up) }
    window.addEventListener('pointermove', move); window.addEventListener('pointerup', up)
  }
  const seekTo = (e: React.PointerEvent) => {
    const t = frac(e.clientX) * duration
    if (t < range[0] || t > range[1]) return
    const a = audioRef.current
    if (a) a.currentTime = t
    setHead(t)
  }

  const l = duration ? (range[0] / duration) * 100 : 0
  const r = duration ? (range[1] / duration) * 100 : 100
  return (
    <div className="trim">
      <audio ref={audioRef} src={url} preload="auto" onPause={() => setPlaying(false)} />
      <div className="trim-row">
        <button className="play-btn big" onClick={toggle} disabled={!duration && !failed} title="Play the selection">
          {playing ? <Pause size={22} fill="#111" /> : <Play size={22} fill="#111" />}
        </button>
        <div className="trim-wave" ref={waveRef} onPointerDown={seekTo}>
          {!peaks && !failed && <div className="trim-loading"><Loader2 size={18} className="spin" /> Reading audio…</div>}
          {failed && <div className="trim-loading">Can’t preview this file here. The whole recording will be transcribed.</div>}
          {peaks && (
            <>
              <div className="trim-bars">
                {peaks.map((p, i) => {
                  const pos = ((i + 0.5) / BARS) * 100
                  return <div key={i} className={pos < l || pos > r ? 'out' : ''} style={{ height: `${p * 100}%` }} />
                })}
              </div>
              <div className="trim-shade l" style={{ left: 0, width: `${l}%` }} />
              <div className="trim-shade r" style={{ left: `${r}%`, right: 0 }} />
              <div className="trim-sel" style={{ left: `${l}%`, width: `${r - l}%` }} />
              <div className="trim-handle" style={{ left: `${l}%` }} onPointerDown={dragHandle(0)} role="slider" aria-label="Start" aria-valuenow={range[0]}><span /></div>
              <div className="trim-handle" style={{ left: `${r}%` }} onPointerDown={dragHandle(1)} role="slider" aria-label="End" aria-valuenow={range[1]}><span /></div>
              <div className="trim-head" style={{ left: `${(head / duration) * 100}%` }} />
            </>
          )}
        </div>
      </div>
      {duration > 0 && (
        <div className="trim-times">
          <TimeBox label="Start" value={range[0]} onCommit={v => onRange([Math.max(0, Math.min(v, range[1] - MIN)), range[1]])} />
          <div className="muted trim-len">{fmtTime(range[1] - range[0])} selected</div>
          <TimeBox label="End" value={range[1]} onCommit={v => onRange([range[0], Math.min(duration, Math.max(v, range[0] + MIN))])} />
        </div>
      )}
    </div>
  )
}

function TimeBox({ label, value, onCommit }: { label: string; value: number; onCommit: (v: number) => void }) {
  const [text, setText] = useState(fmtTime(value))
  const [focus, setFocus] = useState(false)
  useEffect(() => { if (!focus) setText(fmtTime(value)) }, [value, focus])
  const commit = () => { const v = parseTime(text); if (v !== null) onCommit(v); setFocus(false) }
  return (
    <label className="time-box">
      <span className="muted">{label}</span>
      <input value={text} onFocus={() => setFocus(true)} onChange={e => setText(e.target.value)} onBlur={commit}
        onKeyDown={e => { if (e.key === 'Enter') (e.target as HTMLInputElement).blur() }} />
    </label>
  )
}

// ------------------------------------------------------- processing card
const TRACK = [
  { id: 'received', label: 'File received', stages: ['queued'] },
  { id: 'separate', label: 'Isolating guitar', stages: ['separate'] },
  { id: 'notes', label: 'Detecting notes', stages: ['decode', 'transcribe'] },
  { id: 'beats', label: 'Tracking beats', stages: ['beats', 'chords'] },
  { id: 'score', label: 'Creating score', stages: ['arrange', 'fingering', 'export', 'done'] },
]

export function ProcessingCard({ status, meta }: { status: Status | null; meta: Meta | null }) {
  const [now, setNow] = useState(Date.now())
  const [firstSeen] = useState(Date.now())
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 500); return () => clearInterval(t) }, [])
  const steps = TRACK.filter(s => s.id !== 'separate' || meta?.options?.separate)
  const stage = status?.state === 'queued' ? 'queued' : status?.stage ?? 'queued'
  // the file is already received when this card shows, so the first step is always done
  const active = Math.max(1, steps.findIndex(s => s.stages.includes(stage)))
  const started = status?.started ? status.started * 1000 : firstSeen
  const elapsed = Math.max(0, (now - started) / 1000)
  return (
    <div className="proc-wrap">
      <div className="proc-card">
        <FileMusic size={44} strokeWidth={1.5} className="accent" />
        <div className="proc-title">Transcribing {meta?.title ?? ''}</div>
        <div className="muted">Time elapsed: {fmtTime(elapsed)}</div>
        <div className="proc-track">
          {steps.map((s, i) => {
            const state = i < active ? 'done' : i === active ? 'active' : 'todo'
            return (
              <div key={s.id} className={`proc-step ${state}`}>
                <div className="proc-line left" />
                <div className="proc-line right" />
                <div className="proc-dot">
                  {state === 'done' ? <Check size={18} strokeWidth={2.6} /> : state === 'active' ? <span className="proc-dots"><i /><i /><i /></span> : null}
                </div>
                <div className="proc-label">{s.label}</div>
              </div>
            )
          })}
        </div>
        <div className="proc-msg">{status?.state === 'queued' ? 'Waiting for the previous job to finish…' : status?.message || 'Starting…'}</div>
        <p className="proc-note">Runs on this computer. Processing time depends on the length of the recording, about a minute for a short song.</p>
      </div>
    </div>
  )
}

