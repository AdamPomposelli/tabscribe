import { AudioLines, Split, ListMusic, Activity, KeyRound, Hand, FileMusic, ChevronRight } from 'lucide-react'
import type { Engines } from '../api'

/** The real processing chain (backend/tabscribe/pipeline.py), drawn as connected steps. */
export function PipelineDiagram({ engines }: { engines: Engines | null }) {
  const sep = engines?.separation as { available: boolean; label: string; fallback?: string } | undefined
  const steps = [
    { icon: AudioLines, title: 'Audio', chip: 'ffmpeg', tip: 'Decoded to 44.1 kHz with ffmpeg' },
    { icon: Split, title: 'Guitar isolation', chip: sep?.label ?? 'Guitar stem', optional: true, off: engines ? !sep?.available : false,
      tip: `${sep?.label ?? 'Guitar stem model'}${sep?.fallback ? ` (fallback: ${sep.fallback})` : ''}, only for recordings with vocals or a band` },
    { icon: ListMusic, title: 'Notes', chip: engines?.vote?.label?.replace('Vote ', '').replace(/[()]/g, '') ?? '7 models', off: engines ? !engines.vote?.available : false,
      tip: 'Majority vote of Tsumugi ×4, Transkun, MuScriptor and Basic Pitch' },
    { icon: Activity, title: 'Beats', chip: 'Beat This! + DBN', tip: 'Beat This! with a madmom DBN for downbeats, then onset-guided correction' },
    { icon: KeyRound, title: 'Chords & key', chip: 'Tsumugi', tip: 'Tsumugi chord model: chords, key and meter' },
    { icon: Hand, title: 'Fingering', chip: 'Open-Fret', tip: 'Open-Fret string/fret prediction with a playability search, capo-aware' },
    { icon: FileMusic, title: 'Score & tab', chip: 'alphaTab', tip: 'Guitar Pro, MIDI and PDF, engraved with alphaTab' },
  ]
  return (
    <div className="pipe-wrap">
      <ol className="pipe">
        {steps.map((s, i) => (
          <li key={s.title} className={`pipe-step ${s.optional ? 'optional' : ''}`} title={s.tip}>
            {i > 0 && <span className="pipe-arrow" aria-hidden><ChevronRight size={14} /></span>}
            <div className="pipe-icon"><s.icon size={19} /></div>
            <div className="pipe-text">
              <div className="pipe-title">{s.title}</div>
              <span className={`pipe-chip ${s.off ? 'off' : ''}`}>{s.chip}</span>
              {s.optional && <span className="pipe-opt">optional</span>}
            </div>
          </li>
        ))}
      </ol>
    </div>
  )
}
