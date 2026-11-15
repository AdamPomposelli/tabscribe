"""Playable chord-box voicings for chord symbols.

Chord diagrams in tab books show a standard grip (open shapes, barre/CAGED shapes)
near where the hand actually is, not the raw set of notes played in the half bar.
We search every 4-fret window for the grip that covers the chord's essential tones
with the right bass on the lowest string, preferring open/compact shapes and the
fretboard area the transcription is using.
"""
from __future__ import annotations

import itertools
import re

PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
# quality -> (required intervals, optional intervals)
QUAL = {
    "": ((0, 4, 7), ()), "m": ((0, 3, 7), ()), "5": ((0, 7), ()),
    "7": ((0, 4, 10), (7,)), "m7": ((0, 3, 10), (7,)), "maj7": ((0, 4, 11), (7,)),
    "6": ((0, 4, 9), (7,)), "m6": ((0, 3, 9), (7,)),
    "sus4": ((0, 5, 7), ()), "sus2": ((0, 2, 7), ()), "7sus4": ((0, 5, 10), (7,)),
    "dim": ((0, 3, 6), ()), "dim7": ((0, 3, 6, 9), ()), "m7b5": ((0, 3, 6, 10), ()), "aug": ((0, 4, 8), ()),
    "9": ((0, 4, 10, 2), (7,)), "m9": ((0, 3, 10, 2), (7,)), "maj9": ((0, 4, 11, 2), (7,)),
    "add9": ((0, 4, 2), (7,)), "madd9": ((0, 3, 2), (7,)), "6/9": ((0, 4, 9, 2), (7,)),
    "11": ((0, 10, 5), (7, 2, 4)), "m11": ((0, 3, 10, 5), (7, 2)), "13": ((0, 4, 10, 9), (7, 2)),
    "7b9": ((0, 4, 10, 1), (7,)),
}


def parse(name: str):
    m = re.match(r"([A-G])(##|bb|#|b|x)?([^/]*)(?:/([A-G])(##|bb|#|b|x)?)?$", name)
    if not m:
        return None
    acc = {"#": 1, "b": -1, "##": 2, "x": 2, "bb": -2, None: 0}
    root = (PC[m.group(1)] + acc[m.group(2)]) % 12
    q = m.group(3)
    q = re.sub(r"[()]", "", q)
    if q not in QUAL:
        # reduce unknown qualities to their family
        q = "m7b5" if "b5" in q and q.startswith("m") else ("m7" if q.startswith("m7") else
            ("m" if q.startswith("m") and not q.startswith("maj") else ("maj7" if q.startswith("maj") else
             ("7" if q[:1].isdigit() else ""))))
    bass = (PC[m.group(4)] + acc[m.group(5)]) % 12 if m.group(4) else root
    req, opt = QUAL[q]
    return root, [(root + i) % 12 for i in req], [(root + i) % 12 for i in opt], bass


def voicing(name: str, tuning: list[int], capo: int = 0, near_fret: float | None = None, max_fret: int = 15):
    """Returns frets for strings 1..6 (high e first), -1 = muted, or None."""
    p = parse(name)
    if not p:
        return None
    root, req, opt, bass = p
    chord_tones = set(req) | set(opt)
    allowed = chord_tones | {bass}
    low_to_high = list(reversed(tuning))  # string 6 .. 1
    best = None
    for w in range(0, max_fret - 2):
        choices = []
        for open_pitch in low_to_high:
            opts = [-1]
            for f in [0] + list(range(max(1, w), w + 4)):
                if ((open_pitch + capo + f) % 12) in allowed:
                    opts.append(f)
            choices.append(sorted(set(opts)))
        for combo in itertools.product(*choices):
            played = [(i, f) for i, f in enumerate(combo) if f >= 0]
            if len(played) < 3:
                continue
            # contiguous: muted strings only at the bass side or a single inner gap
            first, last = played[0][0], played[-1][0]
            # muted strings: bass side is free, treble side (top strings left out) is common,
            # at most one muted string inside the grip
            inner_mutes = sum(1 for i in range(first, last) if combo[i] < 0)
            treble_mutes = 5 - last
            if inner_mutes > 1 or treble_mutes > 2:
                continue
            pcs = [(low_to_high[i] + capo + f) % 12 for i, f in played]
            if pcs[0] != bass:
                continue
            if bass not in chord_tones and bass in pcs[1:]:
                continue  # a slash bass outside the chord belongs to the bass only
            if not set(req) <= set(pcs):
                continue
            fretted = [f for _, f in played if f > 0]
            span = (max(fretted) - min(fretted)) if fretted else 0
            if span > 3:
                continue
            opens = sum(1 for _, f in played if f == 0)
            if opens and fretted and max(fretted) > 4:
                continue  # open strings only in open position
            fingers = len(set(fretted)) + (len(fretted) - len(set(fretted))) * 0.3
            pos = min(fretted) if fretted else 0
            cost = (0.6 * span + 0.25 * fingers - 0.45 * len(played) + 0.1 * pos + 1.2 * inner_mutes + 0.35 * treble_mutes
                    + (0.15 * abs(pos - near_fret) if near_fret is not None and fretted else 0)
                    - 0.15 * opens + (0.6 if len(played) < 4 else 0))
            if best is None or cost < best[0]:
                best = (cost, combo)
    if best is None:
        return None
    combo = best[1]
    return [combo[5 - s] for s in range(6)]  # strings 1..6 (high e first)
