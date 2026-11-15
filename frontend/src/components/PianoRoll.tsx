import { useEffect, useRef } from 'react'
import { Maximize2, Minimize2 } from 'lucide-react'
import type { Result } from '../api'
import { tickToTime } from './ScoreView'

type Props = {
  result: Result
  timeRef: React.MutableRefObject<number>
  mode: 'score' | 'raw'
  onMode: (m: 'score' | 'raw') => void
  expanded: boolean
  onExpand: () => void
  onSeek: (seconds: number) => void
}

const LOW = 21, HIGH = 108 // A0..C8
const isBlack = (p: number) => [1, 3, 6, 8, 10].includes(p % 12)
const PX_PER_SEC = 90

export function PianoRoll({ result, timeRef, mode, onMode, expanded, onExpand, onSeek }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const notesRef = useRef<{ p: number; s: number; e: number }[]>([])
  const chordsRef = useRef<{ t: number; name: string }[]>([])

  useEffect(() => {
    chordsRef.current = result.chords.map(c => ({ t: tickToTime(result, c.tick), name: c.name }))
    notesRef.current = mode === 'score'
      ? result.notes.map(n => ({ p: n.pitch, s: tickToTime(result, n.tick), e: tickToTime(result, n.end_tick) }))
      : result.raw_notes.map(n => ({ p: n.pitch, s: n.time, e: n.end_time }))
  }, [result, mode])

  // trackpad / wheel over the falling notes scrubs the playback position (like dragging the roll)
  const seekRef = useRef(onSeek)
  seekRef.current = onSeek
  useEffect(() => {
    const c = canvasRef.current
    if (!c) return
    let pending: number | null = null
    let raf = 0
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const px = e.deltaMode === 1 ? e.deltaY * 16 : e.deltaY
      const base = pending ?? timeRef.current
      pending = Math.max(0, Math.min(result.duration, base - px / PX_PER_SEC))
      timeRef.current = pending
      if (!raf) raf = requestAnimationFrame(() => {
        raf = 0
        if (pending !== null) { seekRef.current(pending); pending = null }
      })
    }
    c.addEventListener('wheel', onWheel, { passive: false })
    return () => { c.removeEventListener('wheel', onWheel); cancelAnimationFrame(raf) }
  }, [result, timeRef])

  useEffect(() => {
    let raf = 0
    const draw = () => {
      const c = canvasRef.current
      if (c) {
        const dpr = window.devicePixelRatio || 1
        const w = c.clientWidth, h = c.clientHeight
        if (c.width !== w * dpr || c.height !== h * dpr) { c.width = w * dpr; c.height = h * dpr }
        const g = c.getContext('2d')!
        g.setTransform(dpr, 0, 0, dpr, 0, 0)
        render(g, w, h, notesRef.current, timeRef.current, chordsRef.current)
      }
      raf = requestAnimationFrame(draw)
    }
    raf = requestAnimationFrame(draw)
    return () => cancelAnimationFrame(raf)
  }, [timeRef])

  return (
    <div className="pianoroll">
      <div className="pianoroll-toggle">
        <div className="seg">
          <button className={mode === 'score' ? 'on' : ''} onClick={() => onMode('score')}>Score-derived</button>
          <button className={mode === 'raw' ? 'on' : ''} onClick={() => onMode('raw')}>Raw performance</button>
        </div>
        <button className="icon-btn" onClick={onExpand} title={expanded ? 'Collapse' : 'Expand'}>
          {expanded ? <Minimize2 size={16} /> : <Maximize2 size={16} />}
        </button>
      </div>
      <canvas ref={canvasRef} className="pianoroll-canvas" />
    </div>
  )
}

function keyLayout(w: number) {
  const whites: number[] = []
  for (let p = LOW; p <= HIGH; p++) if (!isBlack(p)) whites.push(p)
  const ww = w / whites.length
  const pos = new Map<number, { x: number; w: number; black: boolean }>()
  whites.forEach((p, i) => pos.set(p, { x: i * ww, w: ww, black: false }))
  for (let p = LOW; p <= HIGH; p++) if (isBlack(p)) {
    const left = pos.get(p - 1)!
    pos.set(p, { x: left.x + ww * 0.68, w: ww * 0.64, black: true })
  }
  return { pos, ww }
}

function render(g: CanvasRenderingContext2D, w: number, h: number, notes: { p: number; s: number; e: number }[], now: number,
  chords: { t: number; name: string }[] = []) {
  const kbH = Math.min(80, h * 0.32)
  const top = h - kbH
  const { pos, ww } = keyLayout(w)
  g.fillStyle = '#0b0b0c'
  g.fillRect(0, 0, w, top)
  // octave lines (at each C)
  g.strokeStyle = '#1d1d20'
  g.lineWidth = 1
  for (let p = LOW; p <= HIGH; p++) if (p % 12 === 0) {
    const x = Math.round(pos.get(p)!.x) + 0.5
    g.beginPath(); g.moveTo(x, 0); g.lineTo(x, top); g.stroke()
  }
  // chord names on the left, falling with the notes (like a lead sheet lane)
  g.font = '600 13px Inter, system-ui, sans-serif'
  g.textAlign = 'left'
  for (let i = 0; i < chords.length; i++) {
    const c = chords[i]
    const y = top - (c.t - now) * PX_PER_SEC
    if (y < -20 || y > top + 20) continue
    g.strokeStyle = 'rgba(255,255,255,0.06)'
    g.beginPath(); g.moveTo(0, Math.round(y) + 0.5); g.lineTo(w, Math.round(y) + 0.5); g.stroke()
    const current = c.t <= now && (i + 1 >= chords.length || chords[i + 1].t > now)
    g.fillStyle = current ? '#ffffff' : 'rgba(255,255,255,0.72)'
    g.fillText(c.name, 10, Math.min(top - 6, y - 5))
  }
  const active = new Set<number>()
  for (const n of notes) {
    if (n.e < now - 0.05 || n.s > now + top / PX_PER_SEC) continue
    if (n.s <= now && n.e >= now) active.add(n.p)
    const k = pos.get(n.p)
    if (!k) continue
    const y1 = top - (n.s - now) * PX_PER_SEC
    const y0 = top - (n.e - now) * PX_PER_SEC
    g.fillStyle = n.s <= now && n.e >= now ? '#3fe0b0' : '#14a37f'
    const x = k.black ? k.x : k.x + 1
    const kw = k.black ? k.w : k.w - 2
    roundRect(g, x, Math.max(y0, -4), kw, Math.min(y1, top) - Math.max(y0, -4), 3)
  }
  // keyboard
  for (const [p, k] of pos) if (!k.black) {
    g.fillStyle = active.has(p) ? '#3fe0b0' : '#f2f2f2'
    g.fillRect(k.x, top, k.w - 1, kbH)
  }
  for (const [p, k] of pos) if (k.black) {
    g.fillStyle = active.has(p) ? '#22b58c' : '#151515'
    g.fillRect(k.x, top, k.w, kbH * 0.62)
  }
  g.fillStyle = '#777'
  g.font = '9px Inter, system-ui, sans-serif'
  g.textAlign = 'center'
  const c4 = pos.get(60)!
  g.fillText('C4', c4.x + ww / 2, h - 5)
}

function roundRect(g: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
  if (h <= 0) return
  r = Math.min(r, h / 2, w / 2)
  g.beginPath()
  g.moveTo(x + r, y)
  g.arcTo(x + w, y, x + w, y + h, r)
  g.arcTo(x + w, y + h, x, y + h, r)
  g.arcTo(x, y + h, x, y, r)
  g.arcTo(x, y, x + w, y, r)
  g.fill()
}
