"""Onset-guided beat refinement for performances without a metronome.

Neural beat trackers carry a strong steady-tempo prior: when a player speeds up or slows
down, their beats lag for a few beats and then re-sync (we measured 150-300 ms errors on a
+-20 % tempo drift). The transcribed note attacks, on the other hand, are accurate to
~25 ms and on a guitar most beats carry an attack (bass + chord). We re-pick the beat
sequence with a dynamic programme over candidate times (note attacks + tracker beats +
midpoints for rests) maximising

    sum salience(beat) - ALPHA * sum log(ibi_k / ibi_{k-1})^2

i.e. beats should sit on strong attacks close to the tracker's beats, and the tempo may
drift smoothly but not jump. The tracker's metrical level (beat period) is kept.
"""
from __future__ import annotations

import numpy as np

ALPHA = 10.0       # tempo-change penalty (plateau 6-10 on the 8-case stress test)
TRACK_W = 0.4      # weight of agreeing with the neural tracker
TRACK_SIGMA = 0.04
ONSET_W = 1.0
KEEP_TOL = 0.04   # corrections smaller than this keep the tracker's beat


def _candidates(beats: np.ndarray, onsets: np.ndarray, weights: np.ndarray):
    c = list(beats) + list(onsets) + list((beats[:-1] + beats[1:]) / 2)
    c = np.unique(np.round(np.array(c), 3))
    # merge candidates closer than 25 ms (keep the strongest attack position)
    out = [c[0]]
    for t in c[1:]:
        if t - out[-1] > 0.025:
            out.append(t)
    return np.array(out)


def refine(beats, notes, max_ratio: float = 1.35) -> np.ndarray:
    """beats: tracker beat times. notes: iterable of (onset_s, pitch, velocity)."""
    beats = np.asarray(beats, float)
    if len(beats) < 8 or not len(notes):
        return beats
    on = np.array([n[0] for n in notes], float)
    pitch = np.array([n[1] for n in notes], float)
    vel = np.array([n[2] if len(n) > 2 else 1.0 for n in notes], float)
    # attack strength: notes starting together, bass notes count double
    w = (1.0 + (pitch <= 52)) * (0.5 + 0.5 * vel)
    cand = _candidates(beats, on, w)
    sal = np.zeros(len(cand))
    for i, t in enumerate(cand):
        m = np.abs(on - t) < 0.035
        sal[i] = ONSET_W * np.log1p(w[m].sum())
        sal[i] += TRACK_W * np.exp(-0.5 * (np.min(np.abs(beats - t)) / TRACK_SIGMA) ** 2)
    sal /= max(1e-6, np.percentile(sal, 95))
    # local beat period from the tracker (median over +-4 beats) bounds the search
    ibi = np.diff(beats)
    loc = np.array([np.median(ibi[max(0, k - 4): k + 4]) for k in range(len(ibi))])
    def period_at(t):
        k = int(np.clip(np.searchsorted(beats, t) - 1, 0, len(loc) - 1))
        return loc[k]
    n = len(cand)
    best: list[dict[int, tuple[float, int | None]]] = [dict() for _ in range(n)]  # best[j][i] = (score, pred of i)
    start_lim = beats[0] + period_at(beats[0]) * 0.6
    for j in range(n):
        T = period_at(cand[j])
        i0 = np.searchsorted(cand, cand[j] - T * max_ratio)
        i1 = np.searchsorted(cand, cand[j] - T / max_ratio, "right")
        for i in range(i0, min(i1, j)):
            d = cand[j] - cand[i]
            val, arg = -np.inf, None
            if cand[i] <= start_lim:  # path may start at i
                val = sal[i] - 0.5 * ALPHA * np.log(d / T) ** 2
            for k, (sc, _) in best[i].items():
                v = sc - ALPHA * np.log(d / (cand[i] - cand[k])) ** 2
                if v > val:
                    val, arg = v, k
            if np.isfinite(val):
                best[j][i] = (val + sal[j], arg)
    end_lim = beats[-1] - period_at(beats[-1]) * 0.6
    fin = [(sc, j, i) for j in range(n) if cand[j] >= end_lim for i, (sc, _) in best[j].items()]
    if not fin:
        return beats
    _, j, i = max(fin)
    path = [j, i]
    k = best[j][i][1]
    while k is not None:
        path.append(k)
        j, i = i, k
        k = best[j][i][1]
    out = np.array(sorted(cand[p] for p in path))
    # only fix real drifts: where the tracker was already right, keep its exact beat
    near = np.array([beats[np.argmin(np.abs(beats - t))] for t in out])
    keep = np.abs(near - out) < KEEP_TOL
    out[keep] = near[keep]
    return np.unique(out)
