import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'
import * as alphaTab from '@coderline/alphatab'
import type { Result } from '../api'
import { ChordDiagram } from './ChordDiagram'
import { EditableTitle } from './EditableTitle'

export type PlaybackSource = 'transcribed' | 'original'

export type ScoreHandle = {
  playPause: () => void
  stop: () => void
  setSource: (s: PlaybackSource, atTime?: number, resume?: boolean) => void
  setSpeed: (s: number) => void
  setMetronome: (on: boolean) => void
  setVolume: (v: number) => void
  seekTime: (seconds: number) => void
}

type Props = {
  gpUrl: string
  audioUrl: string
  result: Result
  title: string
  onRename: (title: string) => void
  onPosition: (audioTime: number, total: number) => void
  onPlaying: (playing: boolean) => void
  onReady: (ready: boolean) => void
  /** URL of the guitar SoundFont used by the synthesizer (can change while the score is open) */
  soundFont: string
}

type Overlay = { key: string; x: number; y: number; name: string; frets: number[] }

/** tick (score) -> seconds in the original recording, through the tracked beat grid. */
export function tickToTime(r: Result, tick: number) {
  const b = r.grid.beats
  const pos = tick / r.grid.tpq + r.grid.first_beat_index
  const i = Math.max(0, Math.min(b.length - 2, Math.floor(pos)))
  return b[i] + (pos - i) * (b[i + 1] - b[i])
}

export function timeToTick(r: Result, t: number) {
  const b = r.grid.beats
  let i = 0
  while (i < b.length - 2 && b[i + 1] <= t) i++
  const frac = (t - b[i]) / (b[i + 1] - b[i])
  return (i - r.grid.first_beat_index + frac) * r.grid.tpq
}

export const ScoreView = forwardRef<ScoreHandle, Props>(function ScoreView(
  { gpUrl, audioUrl, result, title, onRename, onPosition, onPlaying, onReady, soundFont }, ref,
) {
  const scrollRef = useRef<HTMLDivElement>(null)
  const hostRef = useRef<HTMLDivElement>(null)
  const apiRef = useRef<alphaTab.AlphaTabApi | null>(null)
  const audioRef = useRef<HTMLAudioElement>(null)
  const sourceRef = useRef<PlaybackSource>('transcribed')
  const resultRef = useRef(result)
  const scrollTimer = useRef<number | undefined>(undefined)
  const [overlays, setOverlays] = useState<Overlay[]>([])
  const [loading, setLoading] = useState(true)
  resultRef.current = result
  const soundRef = useRef(soundFont)
  const [soundLoading, setSoundLoading] = useState(false)

  // ---------------------------------------------------------------- setup
  useEffect(() => {
    const host = hostRef.current!
    const api = new alphaTab.AlphaTabApi(host, {
      core: { includeNoteBounds: false, engine: 'svg', fontDirectory: '/font/' },
      display: {
        layoutMode: alphaTab.LayoutMode.Page,
        staveProfile: alphaTab.StaveProfile.Default,
        scale: 0.62,
        stretchForce: 0.6,
        systemPaddingTop: 76,
        firstSystemPaddingTop: 44,
        padding: [24, 6, 30, 6],
        resources: {
          mainGlyphColor: '#111111',
          staffLineColor: '#5c5c5c',
          barSeparatorColor: '#333333',
          barNumberColor: '#555555',
          secondaryGlyphColor: '#111111',
          effectFont: '15px Arial, Helvetica, sans-serif',
          tablatureFont: '14px Arial, Helvetica, sans-serif',
          engravingSettings: {
            chordDiagramStringSpacing: 3.1,
            chordDiagramFretSpacing: 3.4,
            chordDiagramPaddingX: 1,
            chordDiagramPaddingY: 1,
          },
        },
      },
      notation: {
        elements: {
          scoreTitle: false, scoreSubTitle: false, scoreArtist: false, scoreAlbum: false,
          scoreWords: false, scoreMusic: false, scoreWordsAndMusic: false, scoreCopyright: false,
          guitarTuning: false, chordDiagrams: false, effectDynamics: false, effectCapo: false,
        },
      },
      player: {
        enablePlayer: true,
        playerMode: alphaTab.PlayerMode.EnabledSynthesizer,
        enableCursor: true,
        enableAnimatedBeatCursor: true,
        enableUserInteraction: true,
        soundFont: soundFont,
        scrollElement: scrollRef.current!,
        scrollOffsetY: -80,
      },
    } as unknown as alphaTab.Settings)
    apiRef.current = api
    // chord boxes: alphaTab prints the fret of every string above the box; keep it discreet
    api.settings.display.resources.elementFonts.set(alphaTab.NotationElement.ChordDiagramFretboardNumbers,
      new alphaTab.model.Font('Arial', 6.5, alphaTab.model.FontStyle.Plain))
    // chord symbols and the track label in an upright sans-serif, like printed tab books
    const sans = (size: number, bold = false) => new alphaTab.model.Font('Helvetica Neue, Arial, sans-serif', size,
      alphaTab.model.FontStyle.Plain, bold ? alphaTab.model.FontWeight.Bold : alphaTab.model.FontWeight.Regular)
    const ef = api.settings.display.resources.elementFonts
    ef.set(alphaTab.NotationElement.EffectChordNames, sans(13))
    ef.set(alphaTab.NotationElement.TrackNames, sans(12))
    api.updateSettings()

    api.scoreLoaded.on((score) => {
      const r = resultRef.current
      // engraving style close to pro tab books: chord boxes above each chord, track name on the
      // first system, no dynamics
      const st = score.stylesheet
      st.globalDisplayChordDiagramsInScore = true
      st.globalDisplayChordDiagramsOnTop = false
      st.hideDynamics = true
      st.singleTrackTrackNamePolicy = alphaTab.model.TrackNamePolicy.FirstSystem
      st.firstSystemTrackNameOrientation = alphaTab.model.TrackNameOrientation.Horizontal
      st.firstSystemTrackNameMode = alphaTab.model.TrackNameMode.FullName
      for (const staff of score.tracks[0].staves) for (const c of staff.chords?.values() ?? []) c.showFingering = false
      // rolled chords: GP5 only stores a "stroke"; show it as an arpeggio (wavy line + arrow),
      // direction from the transcription (ascending pitch = roll upwards)
      const arp = new Map<number, 'up' | 'down'>()
      for (const n of r.notes) if (n.arpeggio) arp.set(n.tick, n.arpeggio)
      for (const bar of score.tracks[0].staves[0].bars) for (const v of bar.voices) for (const b of v.beats) {
        if (b.brushType === alphaTab.model.BrushType.None) continue
        const dir = arp.get(b.absolutePlaybackStart) ?? (b.brushType === alphaTab.model.BrushType.BrushUp ? 'up' : 'down')
        b.brushType = dir === 'up' ? alphaTab.model.BrushType.ArpeggioUp : alphaTab.model.BrushType.ArpeggioDown
      }
      // per-bar sync points: the recording's real bar start times (from beat tracking)
      const barTicks = r.grid.tpq * r.beats_per_bar
      score.masterBars.forEach((mb, i) => {
        const a = new alphaTab.model.Automation()
        a.type = alphaTab.model.AutomationType.SyncPoint
        a.ratioPosition = 0
        const data = new alphaTab.model.SyncPointData()
        data.barOccurence = 0
        data.millisecondOffset = Math.max(0, tickToTime(r, i * barTicks) * 1000)
        a.syncPointValue = data
        mb.syncPoints = []
        mb.addSyncPoint(a)
      })
    })
    // alphaTab always appends a "rendered by alphaTab" line; drop it from the page
    const stripCredit = new MutationObserver(() => {
      host.querySelectorAll('text').forEach(t => { if (t.textContent === 'rendered by alphaTab') t.remove() })
    })
    stripCredit.observe(host, { childList: true, subtree: true })
    // re-layout when the score area changes width (panel resized/collapsed, window resized)
    // compares against the width of the last render (not the last event), so a series of small
    // steps (panel animation, slow window drag) still ends in a re-layout at the final width
    let renderedW = 0, rz: number | undefined
    const ro = new ResizeObserver(([e]) => {
      const w = Math.round(e.contentRect.width)
      if (!renderedW) { renderedW = w; return }
      clearTimeout(rz)
      rz = window.setTimeout(() => {
        const now = Math.round(scrollRef.current?.clientWidth ?? w)
        if (Math.abs(now - renderedW) < 4 || !apiRef.current?.score) return
        renderedW = now
        apiRef.current.render()
      }, 120)
    })
    ro.observe(scrollRef.current!)
    api.renderStarted.on(() => setLoading(true))
    api.postRenderFinished.on(() => {
      setLoading(false)
      setOverlays([])
    })
    api.playerReady.on(() => onReady(true))
    api.playerStateChanged.on((e) => onPlaying(e.state === alphaTab.synth.PlayerState.Playing))
    api.playerPositionChanged.on((e) => {
      if (sourceRef.current === 'transcribed') {
        const r = resultRef.current
        const tEnd = tickToTime(r, e.endTick)
        onPosition(tickToTime(r, e.currentTick), Math.max(tEnd, r.duration))
      }
    })
    return () => { stripCredit.disconnect(); ro.disconnect(); clearTimeout(rz); api.destroy(); apiRef.current = null }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // ------------------------------------------------------------- guitar sound
  useEffect(() => {
    const api = apiRef.current
    if (!api || soundRef.current === soundFont) return
    soundRef.current = soundFont
    // keep the setting current too: alphaTab builds a new synthesizer (loading
    // settings.player.soundFont) whenever playback switches back from the original recording
    api.settings.player.soundFont = soundFont
    // swap the synth's SoundFont; keep playing the transcription if it was playing
    const resume = sourceRef.current === 'transcribed' && api.playerState === alphaTab.synth.PlayerState.Playing
    if (resume) api.pause()
    setSoundLoading(true)
    let fallback = 0
    const done = () => {
      api.soundFontLoaded.off(done)
      clearTimeout(fallback)
      setSoundLoading(false)
      if (resume && soundRef.current === soundFont) window.setTimeout(() => api.play(), 60)
    }
    api.soundFontLoaded.on(done)
    fallback = window.setTimeout(done, 30000)  // load failed: don't leave the spinner up
    api.loadSoundFont(soundFont, false)
    return () => { api.soundFontLoaded.off(done); clearTimeout(fallback) }
  }, [soundFont])

  // ------------------------------------------------------------- load file
  useEffect(() => {
    const api = apiRef.current
    if (!api) return
    let cancelled = false
    setLoading(true)
    fetch(gpUrl).then(r => r.arrayBuffer()).then(buf => {
      if (!cancelled) api.load(new Uint8Array(buf))
    })
    return () => { cancelled = true }
  }, [gpUrl])


  // --------------------------------------------------- original audio sync
  useEffect(() => {
    const audio = audioRef.current!
    let raf = 0
    const tick = () => {
      raf = requestAnimationFrame(tick)  // reschedule first: an alphaTab hiccup must not kill the loop
      if (sourceRef.current !== 'original') return
      onPosition(audio.currentTime, audio.duration || resultRef.current.duration)
      try {
        const out = apiRef.current?.player?.output as unknown as alphaTab.synth.IExternalMediaSynthOutput | undefined
        if (out && 'handler' in out && (out as unknown as { handler?: unknown }).handler) out.updatePosition?.(audio.currentTime * 1000)
      } catch { /* output being swapped */ }
    }
    raf = requestAnimationFrame(tick)
    const onPlay = () => sourceRef.current === 'original' && onPlaying(true)
    const onPause = () => sourceRef.current === 'original' && onPlaying(false)
    audio.addEventListener('play', onPlay)
    audio.addEventListener('pause', onPause)
    audio.addEventListener('ended', onPause)
    return () => {
      cancelAnimationFrame(raf)
      audio.removeEventListener('play', onPlay)
      audio.removeEventListener('pause', onPause)
      audio.removeEventListener('ended', onPause)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  function attachExternalHandler() {
    const api = apiRef.current
    const audio = audioRef.current!
    const out = api?.player?.output as unknown as alphaTab.synth.IExternalMediaSynthOutput | undefined
    if (!out || !('handler' in out)) return
    out.handler = {
      get backingTrackDuration() { return (audio.duration || resultRef.current.duration) * 1000 },
      get playbackRate() { return audio.playbackRate },
      set playbackRate(v: number) { audio.playbackRate = v },
      get masterVolume() { return audio.volume },
      set masterVolume(v: number) { audio.volume = v },
      seekTo(t: number) { audio.currentTime = t / 1000 },
      play() { void audio.play() },
      pause() { audio.pause() },
    }
  }

  useImperativeHandle(ref, () => ({
    playPause() {
      // in both modes alphaTab drives playback (external-media handler controls the <audio>)
      apiRef.current?.playPause()
    },
    stop() {
      apiRef.current?.stop()
      if (sourceRef.current === 'original') audioRef.current!.currentTime = 0
    },
    setSource(s, atTime, resume) {
      const api = apiRef.current
      if (!api || s === sourceRef.current) return
      const a = audioRef.current!
      const t = atTime ?? (sourceRef.current === 'original' ? a.currentTime : tickToTime(resultRef.current, api.tickPosition))
      api.pause()
      a.pause()
      sourceRef.current = s
      // resume from the same spot in the other source once its MIDI/backing track is ready
      // (the original recording is moved directly: setting alphaTab's position while it swaps
      // its output recurses inside alphaTab)
      const restore = () => {
        if (sourceRef.current !== s) return
        if (s === 'original') {
          try { api.tickPosition = Math.max(0, timeToTick(resultRef.current, t)) } catch { /* swapping */ }
          a.currentTime = t
        } else {
          try { api.tickPosition = Math.max(0, timeToTick(resultRef.current, t)) } catch { /* not ready */ }
        }
        onPosition(t, resultRef.current.duration)
        // keep playing across the switch, but only once the synthesizer has its MIDI and its
        // SoundFont: playing earlier runs silently (and the new synth loads the chosen sound)
        if (!resume) return
        const t0 = performance.now()
        const go = () => {
          if (sourceRef.current !== s) return
          if (s === 'transcribed' && !api.isReadyForPlayback && performance.now() - t0 < 15000) { setTimeout(go, 50); return }
          try { api.play() } catch { /* not ready */ }
        }
        setTimeout(go, 80)
      }
      if (s === 'original') a.currentTime = t
      else {
        let done = false
        const once = () => { if (done) return; done = true; setTimeout(restore, 150) }
        api.midiLoaded.on(once)
        setTimeout(() => { api.midiLoaded.off(once); if (!done) { done = true; restore() } }, 1500)
      }
      api.settings.player.playerMode = s === 'original'
        ? alphaTab.PlayerMode.EnabledExternalMedia : alphaTab.PlayerMode.EnabledSynthesizer
      api.updateSettings()
      api.loadMidiForScore()
      if (s === 'original') {
        // output is swapped asynchronously when the player mode changes
        const wait = (n: number) => {
          const out = api.player?.output as unknown as { handler?: unknown } | undefined
          if (out && 'handler' in out) { attachExternalHandler(); api.updateSyncPoints(); setTimeout(restore, 250) }
          else if (n > 0) setTimeout(() => wait(n - 1), 50)
        }
        wait(40)
      }
    },
    setSpeed(v) {
      const api = apiRef.current
      if (api) api.playbackSpeed = v
      if (audioRef.current) audioRef.current.playbackRate = v
    },
    setMetronome(on) {
      const api = apiRef.current
      if (api) api.metronomeVolume = on ? 1 : 0
    },
    setVolume(v) {
      const api = apiRef.current
      if (api) api.masterVolume = v
      if (audioRef.current) audioRef.current.volume = v
    },
    seekTime(t) {
      const api = apiRef.current
      if (sourceRef.current === 'original') audioRef.current!.currentTime = t
      else if (api) api.tickPosition = Math.max(0, timeToTick(resultRef.current, t))
      // keep the cursor in view while scrubbing (alphaTab only auto-scrolls during playback)
      clearTimeout(scrollTimer.current)
      scrollTimer.current = window.setTimeout(() => apiRef.current?.scrollToCursor(), 60)
    },
  }))

  return (
    <div className="score-scroll" ref={scrollRef}>
      <div className="score-page">
        <EditableTitle as="h1" className="score-title" value={title} onSave={onRename} />
        <div className="score-meta">
          <span className="score-capo">{result.capo ? `Capo ${result.capo}` : ''}</span>
          <div className="score-credit">Transcribed by <span className="credit-brand">
          <img src="/logo.svg" alt="" width={14} height={14} /> tabscribe</span>
          </div>
        </div>
        <div className="score-host-wrap">
          <div ref={hostRef} className="score-host" />
          <div className="chord-overlays">
            {overlays.map(o => (
              <div key={o.key} className="chord-overlay" style={{ left: o.x - 8, top: o.y - 30 }}>
                <ChordDiagram frets={o.frets} />
              </div>
            ))}
          </div>
        </div>
        {loading && <div className="score-loading">Rendering score…</div>}
        {!loading && soundLoading && <div className="score-loading">Loading guitar sound…</div>}
      </div>
      <audio ref={audioRef} src={audioUrl} preload="auto" />
    </div>
  )
})
