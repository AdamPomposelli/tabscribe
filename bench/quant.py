"""Quantize note onsets/offsets on the tracked beat grid and score."""
import sys, json, numpy as np
sys.path.insert(0, 'bench'); sys.path.insert(0, 'backend')
from metrics import load_midi, metrics
from cluster import cluster_vote
from tabscribe import rhythm

def grid_for(notes, beats_json='data/projects/49151cb1adc9/beats.json'):
    b = json.load(open(beats_json))
    return rhythm.build_grid(np.array(b['beats']), np.array(b['downbeats']), notes[0][0], max(n[1] for n in notes))

def q(grid, t, div):
    x = grid.time_to_tick(t) / rhythm.TPQ * div
    return grid.tick_to_time(round(x) / div * rhythm.TPQ)

def quantize(notes, grid, on_div=4, off_div=2, min_len_div=4):
    out = []
    for s, e, p in notes:
        qs = q(grid, s, on_div)
        qe = q(grid, e, off_div) if off_div else e
        qe = max(qe, grid.tick_to_time(grid.time_to_tick(qs) + rhythm.TPQ / min_len_div))
        out.append((qs, qe, p))
    return out

if __name__ == '__main__':
    ref = load_midi('bench/YeuEm_ref.mid')
    M = {'tk': load_midi('bench/transkun.mid', 60), 'ms': load_midi('bench/ms_raw.mid', 60), 'bp': load_midi('bench/bp_raw.mid', 60)}
    M = {k: [n for n in v if 40 <= n[2] <= 88 and n[0] >= 0.06] for k, v in M.items()}
    v = cluster_vote(M, 2, 0.09)
    g = grid_for(v)
    cut = lambda ns: [n for n in ns if n[0] < 30]
    print('unquantized      ', metrics(ref, cut(v)))
    for on_div, off_div in [(4, None), (4, 4), (4, 2), (2, 2), (4, 1)]:
        print(f'on 1/{on_div} off 1/{off_div}', metrics(ref, cut(quantize(v, g, on_div, off_div))))
