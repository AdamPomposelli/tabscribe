"""Evaluate a strategy on both reference songs (YeuEm 30 s, hoa whole song)."""
import sys, json, numpy as np
sys.path.insert(0, 'bench'); sys.path.insert(0, 'backend')
from metrics import load_midi, metrics
from permodel import load_models, flt
SONGS = [('YeuEm', 'bench/YeuEm_ref.mid', 'data/projects/49151cb1adc9', 30.0),
         ('hoa', 'bench/hoa_ref.mid', 'data/projects/5edf9eeec0db', 999.0)]

def run(strategy, label=''):
    out = []
    for name, ref_path, P, lim in SONGS:
        ref = load_midi(ref_path, lim)
        est = [x for x in strategy(load_models(P), P) if x[0] < lim]
        m = metrics(ref, est); out.append((name, m))
    print(f'{label:40}', '  '.join(f"{n}: notes {m['notes'][2]:.3f} rhy {m['rhythm']:.3f} dur {m['dur20'][2]:.3f}" for n, m in out))
    return out
