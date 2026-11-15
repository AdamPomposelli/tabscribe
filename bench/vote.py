"""Model voting experiments: which combination of transcribers matches the reference best."""
import sys, json, itertools
import numpy as np, pretty_midi as pm
sys.path.insert(0, 'bench')
from metrics import load_midi, metrics

def match(a, b, tol=0.06):
    """greedy one-to-one match on (pitch, onset)"""
    used, pairs = set(), {}
    for i, (s, e, p) in enumerate(a):
        best = None
        for j, (s2, e2, p2) in enumerate(b):
            if j in used or p2 != p or abs(s2 - s) > tol: continue
            if best is None or abs(s2 - s) < abs(b[best][0] - s): best = j
        if best is not None:
            used.add(best); pairs[i] = best
    return pairs

def vote(models, k, anchor=0, tol=0.06):
    """notes from models[anchor] supported by at least k models (anchor included);
    plus notes from others supported by k models but missing in anchor."""
    out = []
    names = list(models)
    base = models[names[anchor]]
    sup = {n: match(base, models[n], tol) for n in names if n != names[anchor]}
    for i, note in enumerate(base):
        if 1 + sum(i in sup[n] for n in sup) >= k: out.append(note)
    return out

if __name__ == '__main__':
    ref = load_midi('bench/YeuEm_ref.mid')
    M = {'tk': load_midi('bench/transkun.mid', 60), 'ms': load_midi('bench/ms_raw.mid', 60), 'bp': load_midi('bench/bp_raw.mid', 60)}
    M = {k: [n for n in v if 40 <= n[2] <= 88 and n[0] >= 0.06] for k, v in M.items()}
    for k in M: print(k, metrics(ref, [n for n in M[k] if n[0] < 30]))
    for anchor in range(3):
        for kk in (2, 3):
            names = list(M)
            v = vote(M, kk, anchor)
            print(f'anchor={names[anchor]} k>={kk}', metrics(ref, [n for n in v if n[0] < 30]))
