"""Guitar-physics durations: a note rings until its acoustic end, but is cut when
the same string is struck again (strings come from the fingering model)."""
import sys, json, numpy as np
sys.path.insert(0, 'bench'); sys.path.insert(0, 'backend')
from metrics import load_midi, metrics
from durations import clusters, first
from quant import grid_for, q
from tabscribe import fingering, rhythm

def string_rule(notes, grid, damp=0.0, order=('tk', 'bp', 'ms')):
    ticks = [int(round(grid.time_to_tick(n['s']) / 240) * 240) for n in notes]
    fn = [fingering.FNote(i, n['p'], t, int(grid.time_to_tick(first(n['ends'], order))), 0.8) for i, (n, t) in enumerate(zip(notes, ticks))]
    asg, _ = fingering.assign(fn)
    out = []
    for i, n in enumerate(notes):
        e = first(n['ends'], order)
        if i in asg:
            s_ = asg[i][0]
            later = [notes[j]['s'] for j in asg if asg[j][0] == s_ and notes[j]['s'] > n['s'] + 0.03]
            if later:
                e = min(e, min(later) - damp)
        out.append((n['s'], max(e, n['s'] + 0.05), n['p']))
    return out, asg

if __name__ == '__main__':
    ref = load_midi('bench/YeuEm_ref.mid')
    M = {'tk': load_midi('bench/transkun.mid', 60), 'ms': load_midi('bench/ms_raw.mid', 60), 'bp': load_midi('bench/bp_raw.mid', 60)}
    M = {k: [n for n in v if 40 <= n[2] <= 88 and n[0] >= 0.06] for k, v in M.items()}
    notes = clusters(M)
    g = grid_for([(n['s'], first(n['ends'], ('tk', 'bp', 'ms')), n['p']) for n in notes])
    cut = lambda ns: [x for x in ns if x[0] < 30]
    est, asg = string_rule(notes, g)
    print('string rule        ', metrics(ref, cut(est)))
    qe = [(q(g, s, 4), q(g, e, 4), p) for s, e, p in est]
    print('string rule + quant', metrics(ref, cut(qe)))
