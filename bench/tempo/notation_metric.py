"""Notation accuracy: are notes written at the right beat position (same 16th/triplet slot)?
Reference positions come from Songscription's tempo map; ours from the quantized ticks.
Bar phase is ignored (best integer beat shift), so this scores the beat grid, not the bar choice."""
import numpy as np, pretty_midi as pm


def ref_positions(midi_path, warp=None, lim=None):
    m = pm.PrettyMIDI(midi_path)
    beats = m.get_beats()
    out = []
    for i in m.instruments:
        for n in i.notes:
            if lim and n.start >= lim: continue
            out.append((float(np.interp(n.start, beats, np.arange(len(beats)))), n.pitch))
    return out


def f1(ref, est, tol=0.07):
    """ref/est: (beat_position, pitch). Greedy match per pitch, best integer shift."""
    best = 0
    for shift in range(-8, 9):
        used = set(); hit = 0
        by_p = {}
        for k, (b, p) in enumerate(est): by_p.setdefault(p, []).append((b + shift, k))
        for b, p in ref:
            c = [(abs(eb - b), k) for eb, k in by_p.get(p, []) if k not in used and abs(eb - b) <= tol]
            if c:
                used.add(min(c)[1]); hit += 1
        f = 2 * hit / (len(ref) + len(est)) if ref and est else 0
        best = max(best, f)
    return round(best, 3)
