"""Writers: Guitar Pro 5 (rendered by alphaTab in the UI), MIDI, JSON."""
from __future__ import annotations

import guitarpro as gp
import pretty_midi

from .rhythm import TPQ
from .score import SMeasure

GP_DURATION = {1: gp.Duration.whole, 2: gp.Duration.half, 4: gp.Duration.quarter,
               8: gp.Duration.eighth, 16: gp.Duration.sixteenth, 32: gp.Duration.thirtySecond}


def _gp_text(s: str) -> str:
    """GP5 stores text in cp1252: keep what fits, strip accents from the rest ('Cỏ dại' -> 'Co dai')."""
    try:
        s.encode("cp1252")
        return s
    except UnicodeEncodeError:
        import unicodedata
        out = "".join(c if c.isascii() or _fits(c) else unicodedata.normalize("NFKD", c)[0] for c in s)
        return out.encode("cp1252", "replace").decode("cp1252")


def _fits(c: str) -> bool:
    try:
        c.encode("cp1252")
        return True
    except UnicodeEncodeError:
        return False


def write_gp5(path, measures: list[SMeasure], *, title: str, artist: str, tempo: int, beats_per_bar: int,
              key_accidentals: int, key_minor: bool, tuning: list[int], capo: int, instrument_program: int = 24,
              track_name: str = "Acoustic Guitar"):
    song = gp.Song()
    song.title, song.artist = _gp_text(title), _gp_text(artist)
    song.subtitle = ""
    song.words = ""
    song.tab = "Transcribed by Tabscribe"
    song.tempo = int(round(tempo))
    song.tempoName = ""
    song.tracks, song.measureHeaders = [], []
    for i, m in enumerate(measures):
        h = gp.MeasureHeader()
        h.number = i + 1
        h.timeSignature.numerator = beats_per_bar
        h.timeSignature.denominator = gp.Duration(value=4)
        try:
            h.keySignature = gp.KeySignature((key_accidentals, 1 if key_minor else 0))
        except ValueError:
            pass
        song.addMeasureHeader(h)

    strings = [gp.GuitarString(n + 1, v) for n, v in enumerate(tuning)]
    track = gp.Track(song, number=1, name=track_name, strings=strings)
    track.offset = capo
    track.fretCount = 24
    track.channel.instrument = instrument_program
    track.channel.channel, track.channel.effectChannel = 0, 1
    track.measures = [gp.Measure(track, h) for h in song.measureHeaders]

    for m, gm in zip(measures, track.measures):
        chords = {c.tick: c for c in m.chords}
        for vi, beats in enumerate(m.voices[:2]):
            voice = gm.voices[vi]
            for b in beats:
                dur = gp.Duration(value=b.value, isDotted=b.dotted)
                if b.tuplet:
                    dur.tuplet = gp.Tuplet(3, 2)
                beat = gp.Beat(voice, duration=dur, status=gp.BeatStatus.normal if b.notes else gp.BeatStatus.rest)
                used = set()
                for n in b.notes:
                    if n.string in used:
                        continue
                    used.add(n.string)
                    note = gp.Note(beat, value=n.fret, string=n.string,
                                   type=gp.NoteType.tie if n.tie else gp.NoteType.normal,
                                   velocity=gp.Velocities.forte)
                    beat.notes.append(note)
                if b.arpeggio:
                    # GP5 stroke = rolled chord; the UI renders it as an arpeggio (wavy line + arrow)
                    beat.effect.stroke = gp.BeatStroke(
                        gp.BeatStrokeDirection.up if b.arpeggio == "up" else gp.BeatStrokeDirection.down, 16)
                if vi == 0 and b.tick in chords and not getattr(beat.effect, "chord", None):
                    c = chords.pop(b.tick)
                    ch = gp.Chord(6)
                    ch.name = c.name
                    fretted = [f for f in c.frets if f > 0]
                    ch.firstFret = min(fretted) if fretted and max(fretted) > 4 else 1
                    ch.strings = list(c.frets)
                    beat.effect.chord = ch
                voice.beats.append(beat)
            if not voice.beats:
                voice.beats.append(gp.Beat(voice, duration=gp.Duration(value=1), status=gp.BeatStatus.rest))
    song.tracks.append(track)
    gp.write(song, str(path), version=(5, 1, 0))


SNAP_TOLERANCE = 0.05  # s


def write_midi(path, qnotes, grid, program: int = 24, quantized: bool = True):
    pm = pretty_midi.PrettyMIDI(initial_tempo=grid.bpm)
    inst = pretty_midi.Instrument(program=program, name="Guitar")
    for n in qnotes:
        s, e = (grid.tick_to_time(n.start), grid.tick_to_time(n.end)) if quantized else (n.time, n.end_time)
        if quantized and (getattr(n, "arpeggio", None) or abs(s - n.time) > SNAP_TOLERANCE):
            # rolled chords and deliberate off-grid attacks (anticipations, unmarked rolls) keep
            # their real timing; everything already near the grid is snapped to it
            s = n.time
        inst.notes.append(pretty_midi.Note(int(min(127, 40 + n.velocity * 87)), n.pitch, s, max(e, s + 0.03)))
    pm.instruments.append(inst)
    pm.write(str(path))
