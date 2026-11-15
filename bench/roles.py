"""Duration by musical role: melody (top line) -> MuScriptor offset (score-like, legato);
bass / inner held notes -> Transkun offset (acoustic ring), cut when the string is re-struck."""
import sys
sys.path.insert(0, 'bench'); sys.path.insert(0, 'backend')
from metrics import load_midi, metrics
from durations import clusters, first
from quant import grid_for, q
from strings import string_rule

def is_melody(n, notes, min_pitch, win=0.06):
    group = [m for m in notes if abs(m['s'] - n['s']) <= win]
    return n['p'] >= min_pitch and n['p'] == max(m['p'] for m in group)

def role_rule(notes, grid, min_pitch=60, string_cut=True):
    base, asg = string_rule(notes, grid) if string_cut else ([(n['s'], first(n['ends'], ('tk', 'bp', 'ms')), n['p']) for n in notes], {})
    out = []
    for n, (s, e, p) in zip(notes, base):
        if is_melody(n, notes, min_pitch) and 'ms' in n['ends']:
            e = n['ends']['ms'] if not string_cut else min(n['ends']['ms'], max(e, n['ends']['ms']))
        out.append((s, max(e, s + 0.05), p))
    return out

if __name__ == '__main__':
    ref = load_midi('bench/YeuEm_ref.mid')
    M = {'tk': load_midi('bench/transkun.mid', 60), 'ms': load_midi('bench/ms_raw.mid', 60), 'bp': load_midi('bench/bp_raw.mid', 60)}
    M = {k: [n for n in v if 40 <= n[2] <= 88 and n[0] >= 0.06] for k, v in M.items()}
    notes = clusters(M)
    g = grid_for([(n['s'], first(n['ends'], ('tk', 'bp', 'ms')), n['p']) for n in notes])
    cut = lambda ns: [x for x in ns if x[0] < 30]
    for mp in (55, 58, 60, 62, 64):
        for sc in (False, True):
            est = role_rule(notes, g, mp, sc)
            qe = [(q(g, s, 4), q(g, e, 4), p) for s, e, p in est]
            print(f'melody>={mp} stringcut={sc!s:5}', metrics(ref, cut(est))['dur20'], ' quant:', metrics(ref, cut(qe))['dur20'])
