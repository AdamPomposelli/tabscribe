"""Playability metrics for a fingering: lower = easier, except open strings / in-position."""
import numpy as np

def playability(notes):
    """notes: list of (tick, end_tick, pitch, string, fret)."""
    groups = {}
    for n in notes: groups.setdefault(n[0], []).append(n)
    ticks = sorted(groups)
    pos_prev, shifts, big_jumps, spans, sounding_spans = None, [], 0, [], []
    for t in ticks:
        g = groups[t]
        fretted = [n[4] for n in g if n[4] > 0]
        if len(fretted) > 1: spans.append(max(fretted) - min(fretted))
        ring = [n[4] for n in notes if n[0] <= t < n[1] and n[4] > 0]
        if len(ring) > 1: sounding_spans.append(max(ring) - min(ring))
        if fretted:
            pos = min(fretted)
            if pos_prev is not None:
                d = abs(pos - pos_prev); shifts.append(d); big_jumps += d > 4
            pos_prev = pos
    frets = [n[4] for n in notes]
    return {
        'mean_shift': round(float(np.mean(shifts)), 2) if shifts else 0,
        'jumps>4': big_jumps,
        'max_chord_span': max(spans) if spans else 0,
        'mean_held_span': round(float(np.mean(sounding_spans)), 2) if sounding_spans else 0,
        'held_span>4': sum(s > 4 for s in sounding_spans),
        'mean_fret': round(float(np.mean(frets)), 2),
        'open_%': round(100 * float(np.mean([f == 0 for f in frets])), 1),
        'frets>=8_%': round(100 * float(np.mean([f >= 8 for f in frets])), 1),
    }
