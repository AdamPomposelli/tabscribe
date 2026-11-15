"""Cluster voting across transcribers: every note from every model is grouped by
(pitch, onset within tol); clusters seen by >= k distinct models are kept."""
import sys
import numpy as np
sys.path.insert(0, 'bench')
from metrics import load_midi, metrics

ONSET_PRIORITY = ('ms', 'tk', 'bp')   # whose onset to trust (rhythm accuracy measured: ms .92, tk .86, bp .65)
OFFSET_PRIORITY = ('tk', 'bp', 'ms')  # whose offset to trust (dur F1: tk .55, bp .28, ms .23)

def cluster_vote(models, k=2, tol=0.07, weights=None):
    allnotes = sorted([(s, e, p, m) for m, ns in models.items() for s, e, p in ns], key=lambda x: (x[2], x[0]))
    clusters = []
    for s, e, p, m in allnotes:
        c = clusters[-1] if clusters else None
        if c and c['p'] == p and s - c['s0'] <= tol and m not in c['m']:
            c['m'][m] = (s, e)
        else:
            clusters.append({'p': p, 's0': s, 'm': {m: (s, e)}})
    out = []
    for c in clusters:
        w = sum((weights or {}).get(m, 1.0) for m in c['m'])
        if w >= k:
            on = next(c['m'][m][0] for m in ONSET_PRIORITY if m in c['m'])
            off = next(c['m'][m][1] for m in OFFSET_PRIORITY if m in c['m'])
            out.append((on, max(off, on + 0.05), c['p']))
    return sorted(out)

if __name__ == '__main__':
    ref = load_midi('bench/YeuEm_ref.mid')
    M = {'tk': load_midi('bench/transkun.mid', 60), 'ms': load_midi('bench/ms_raw.mid', 60), 'bp': load_midi('bench/bp_raw.mid', 60)}
    M = {k: [n for n in v if 40 <= n[2] <= 88 and n[0] >= 0.06] for k, v in M.items()}
    for tol in (0.05, 0.07, 0.09):
        v = cluster_vote(M, 2, tol)
        print(f'tol={tol}', metrics(ref, [n for n in v if n[0] < 30]))
