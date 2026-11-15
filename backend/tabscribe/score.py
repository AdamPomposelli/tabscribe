"""Build an engraving-ready score (measures, 2 voices, durations, ties, chords)."""
from __future__ import annotations

from dataclasses import dataclass, field, asdict
import numpy as np

from .rhythm import TPQ, Grid

# (ticks, base value, dotted, tuplet)
DURATIONS = [
    (3840, 1, False, None), (2880, 2, True, None), (1920, 2, False, None), (1440, 4, True, None),
    (960, 4, False, None), (720, 8, True, None), (480, 8, False, None), (360, 16, True, None),
    (240, 16, False, None), (120, 32, False, None),
]
TRIPLET_DURATIONS = [(640, 4, False, 3), (320, 8, False, 3), (160, 16, False, 3)]
BASS_MAX_PITCH = 52  # E3 and below may form the bass voice


@dataclass
class SNote:
    pitch: int
    string: int
    fret: int
    tie: bool = False
    velocity: float = 0.8


@dataclass
class SBeat:
    tick: int                 # absolute tick
    ticks: int                # length
    value: int                # 1,2,4,8,16,32
    dotted: bool = False
    tuplet: int | None = None
    notes: list[SNote] = field(default_factory=list)
    arpeggio: str | None = None

    @property
    def rest(self):
        return not self.notes


@dataclass
class SChord:
    tick: int
    name: str
    frets: list[int]          # string 1..6, -1 = not played


@dataclass
class SMeasure:
    index: int
    start: int
    length: int
    voices: list[list[SBeat]]
    chords: list[SChord] = field(default_factory=list)


@dataclass
class QNote:
    idx: int
    pitch: int
    start: int
    end: int
    velocity: float
    string: int = 0
    fret: int = 0
    voice: int = 0
    time: float = 0.0
    end_time: float = 0.0
    arpeggio: str | None = None   # 'up' | 'down' when part of a rolled chord


def split_voices(qnotes: list[QNote]) -> None:
    groups: dict[int, list[QNote]] = {}
    for n in qnotes:
        groups.setdefault(n.start, []).append(n)
    for t, ns in groups.items():
        low = min(ns, key=lambda n: n.pitch)
        for n in ns:
            n.voice = 0
        if any(n.arpeggio for n in ns):  # a rolled chord stays one chord in one voice
            continue
        if low.pitch <= BASS_MAX_PITCH and (len(ns) > 1 or low.end - low.start >= TPQ or low.string >= 5):
            low.voice = 1


def _decompose(pos_in_bar: int, length: int, triplet_ok: bool, half: int = 2 * TPQ, bar_len: int = 4 * TPQ):
    """Split a length into notatable durations, following standard engraving rules:
    a value may start on its own grid (16ths on 16ths, quarters on 8ths, halves on beats,
    whole notes on the bar line) and must not cross the middle of the bar unless it
    starts on it - otherwise it is split with a tie."""
    out = []
    while length > 0:
        choice = None
        table = DURATIONS + (TRIPLET_DURATIONS if triplet_ok else [])
        for ticks, val, dot, tup in table:
            if ticks > length:
                continue
            if tup is None:
                unit = 240 if ticks < TPQ else (480 if ticks < 2 * TPQ else (TPQ if ticks < bar_len else bar_len))
                if pos_in_bar % unit:
                    continue
                crosses_mid = pos_in_bar < half < pos_in_bar + ticks and pos_in_bar % half
                if crosses_mid and half != bar_len:
                    continue
            choice = (ticks, val, dot, tup)
            break
        if choice is None:
            choice = (length if length < 120 else 120, 32, False, None)
        out.append(choice)
        pos_in_bar += choice[0]
        length -= choice[0]
    return out


def _snap_len(t: int) -> bool:
    return t % 240 != 0 and t % 160 == 0


def build_measures(qnotes: list[QNote], grid: Grid, n_bars: int) -> list[SMeasure]:
    bar_len = grid.beats_per_bar * TPQ
    measures = [SMeasure(i, i * bar_len, bar_len, [[], []]) for i in range(n_bars)]
    for v in (0, 1):
        vn = sorted([n for n in qnotes if n.voice == v], key=lambda n: (n.start, -n.pitch))
        events: dict[int, list[QNote]] = {}
        for n in vn:
            events.setdefault(n.start, []).append(n)
        ticks = sorted(events)
        # Engraving rules (as pro guitar transcriptions write fingerstyle):
        #  * upper voice is legato: a note lasts until the next attack unless the gap is > 1 beat
        #  * bass rings until the next bass note but never past the half bar (keeps values simple)
        spans = []
        half = bar_len // 2 if grid.beats_per_bar % 2 == 0 else bar_len
        for i, t in enumerate(ticks):
            nxt = ticks[i + 1] if i + 1 < len(ticks) else None
            end = max(n.end for n in events[t])
            if v == 1:
                half_end = (t // half + 1) * half
                end = min(nxt, half_end) if nxt is not None else half_end
                if nxt is not None and nxt - half_end < TPQ // 2:
                    end = nxt  # avoid an 8th rest right before the next bass note
            elif nxt is not None:
                if nxt - end <= TPQ:
                    end = nxt
                end = min(end, nxt)
            else:
                end = max(end, t + TPQ)
            end = max(end, t + 240)
            # land notes on 8th positions when they end inside a beat (no stray 16th rests)
            if v == 0 and nxt is not None and end != nxt and end % 480:
                end = min(nxt, (end // 480 + 1) * 480)
            spans.append((t, end, events[t]))
        cursor = 0
        for t, end, ns in spans:
            if t > cursor:
                _emit(measures, v, cursor, t, [], bar_len)
            _emit(measures, v, t, end, ns, bar_len)
            cursor = end
        if cursor < n_bars * bar_len:
            _emit(measures, v, cursor, n_bars * bar_len, [], bar_len)
    return measures


def _emit(measures, voice, start, end, ns, bar_len):
    first = True
    t = start
    while t < end:
        bar = t // bar_len
        if bar >= len(measures):
            return
        bar_end = (bar + 1) * bar_len
        seg_end = min(end, bar_end)
        triplet_ok = _snap_len(t) or _snap_len(seg_end) or _snap_len(seg_end - t)
        half = bar_len // 2 if (bar_len // TPQ) % 2 == 0 else bar_len
        for ticks, val, dot, tup in _decompose(t - bar * bar_len, seg_end - t, triplet_ok, half, bar_len):
            notes = [SNote(n.pitch, n.string, n.fret, tie=not first, velocity=n.velocity) for n in ns]
            arp = next((n.arpeggio for n in ns if n.arpeggio), None) if first else None
            measures[bar].voices[voice].append(SBeat(t, ticks, val, dot, tup, notes, arp))
            first = False
            t += ticks
        t = seg_end


def attach_chords(measures: list[SMeasure], qnotes: list[QNote], chord_names, segments,
                  tuning: list[int] | None = None, capo: int = 0):
    """Chord symbol + a standard playable grip near where the hand is (see voicings.py)."""
    from .voicings import voicing
    tuning = tuning or [64, 59, 55, 50, 45, 40]
    for (a, b), name in zip(segments, chord_names):
        if not name:
            continue
        bar = a // measures[0].length if measures else 0
        if bar >= len(measures):
            continue
        played = [n for n in qnotes if a <= n.start < b]
        fretted = sorted(n.fret for n in played if n.fret > 0)
        near = fretted[len(fretted) // 2] if fretted else None
        frets = voicing(name, tuning, capo, near_fret=near)
        if frets is None:  # fall back to what is actually played
            frets = [-1] * 6
            for n in sorted(played, key=lambda n: n.start):
                if frets[n.string - 1] == -1:
                    frets[n.string - 1] = n.fret
        measures[bar].chords.append(SChord(a, name, frets))


def to_json(measures: list[SMeasure]) -> list[dict]:
    return [asdict(m) for m in measures]
