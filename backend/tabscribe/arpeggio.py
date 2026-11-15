"""Rolled-chord (arpeggiato) detection.

A strummed/rolled chord shows up in any transcription as 3+ notes whose onsets are
staggered by a few tens of ms, moving in one direction across the strings, and which
all keep ringing together afterwards. Quantization would scatter them over several
16ths (even across a bar line); in notation they are ONE chord with an arpeggio sign
(wavy line + arrow). A melodic arpeggio (fingerstyle pattern) is not a rolled chord:
its notes are further apart and/or are cut as the line moves on.
"""
from __future__ import annotations

MAX_GAP = 0.16      # s between consecutive notes of the roll
MAX_SPAN = 0.35     # s from first to last note
MIN_NOTES = 3
MIN_STEP = 0.03     # a roll is evenly spread: every step at least this long
MAX_STEP_RATIO = 3.5
MIN_OVERLAP = 0.6   # every note must still ring at least this fraction of the way to the last onset + 100 ms


def detect(notes, beat_strength=None):
    """notes: objects with .time, .end_time, .pitch, .start (tick) - sorted by time.
    Returns a list of (indices, direction 'up'|'down', anchor_tick)."""
    order = sorted(range(len(notes)), key=lambda i: (notes[i].time, notes[i].pitch))
    out, used, i = [], set(), 0
    while i < len(order):
        best = None
        for direction in ("up", "down"):
            chain = [order[i]]
            for j in order[i + 1:]:
                a, b = notes[chain[-1]], notes[j]
                if b.time - a.time > MAX_GAP or b.time - notes[chain[0]].time > MAX_SPAN:
                    break
                if b.time - a.time < 0.012:   # simultaneous attack = plain chord tone, not a roll step
                    continue
                if (b.pitch > a.pitch) == (direction == "up") and b.pitch != a.pitch:
                    chain.append(j)
            if len(chain) >= MIN_NOTES and (best is None or len(chain) > len(best[0])):
                best = (chain, direction)
        if best:
            chain, direction = best
            last_on = notes[chain[-1]].time
            steps = [notes[b].time - notes[a].time for a, b in zip(chain, chain[1:])]
            even = min(steps) >= MIN_STEP and max(steps) / max(min(steps), 1e-3) <= MAX_STEP_RATIO
            rings = even and all(notes[k].end_time >= last_on + 0.05 for k in chain)
            if rings and not used.intersection(chain):
                ticks = [notes[k].start for k in chain]
                # anchor on the most common quantized position, ties -> strongest metrical position
                strength = beat_strength or (lambda t: (t % 960 == 0) * 2 + (t % 480 == 0))
                anchor = max(set(ticks), key=lambda t: (ticks.count(t), strength(t), t))
                out.append((chain, direction, anchor))
                used.update(chain)
                i += 1
                continue
        i += 1
    return out


class _Raw:
    __slots__ = ("time", "end_time", "pitch", "start")

    def __init__(self, n):
        self.time, self.end_time, self.pitch, self.start = n.start, n.end, n.pitch, 0


def raw_roll_members(notes) -> set[int]:
    """Indices (into `notes`, objects with start/end/pitch in seconds) that belong to a rolled chord."""
    wrapped = [_Raw(n) for n in notes]
    return {k for chain, _d, _a in detect(wrapped) for k in chain}
