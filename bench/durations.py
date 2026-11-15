"""Duration-rule experiments on the cluster-voted notes."""
import sys, numpy as np
sys.path.insert(0, 'bench')
from metrics import load_midi, metrics

def clusters(models, k=2, tol=0.09):
    allnotes = sorted([(s, e, p, m) for m, ns in models.items() for s, e, p in ns], key=lambda x: (x[2], x[0]))
    cl = []
    for s, e, p, m in allnotes:
        c = cl[-1] if cl else None
        if c and c['p'] == p and s - c['s0'] <= tol and m not in c['m']:
            c['m'][m] = (s, e)
        else:
            cl.append({'p': p, 's0': s, 'm': {m: (s, e)}})
    out = []
    for c in cl:
        if len(c['m']) >= k:
            on = next(c['m'][m][0] for m in ('ms', 'tk', 'bp') if m in c['m'])
            out.append({'s': on, 'p': c['p'], 'ends': {m: v[1] for m, v in c['m'].items()}})
    return sorted(out, key=lambda n: (n['s'], n['p']))

def first(d, order):
    return next(d[m] for m in order if m in d)

RULES = {
    'tk>bp>ms': lambda n, ns: first(n['ends'], ('tk', 'bp', 'ms')),
    'min(tk,ms)': lambda n, ns: min(first(n['ends'], ('tk', 'bp', 'ms')), n['ends'].get('ms', 1e9)),
    'median': lambda n, ns: float(np.median(list(n['ends'].values()))),
}

def top_voice_rule(notes, gap=0.03):
    """Top line = highest note of each onset group; it ends at the next top-line onset
    (legato melody) unless the acoustic end is earlier. Other notes keep the acoustic end."""
    groups = {}
    for n in notes:
        groups.setdefault(round(n['s'], 2), []).append(n)
    keys = sorted(groups)
    top = [max(groups[k], key=lambda n: n['p']) for k in keys]
    out = []
    for n in notes:
        ac = first(n['ends'], ('tk', 'bp', 'ms'))
        e = ac
        if any(n is t for t in top):
            later = [t['s'] for t in top if t['s'] > n['s'] + gap and t['p'] >= 55]
            if later and n['p'] >= 55:
                e = min(ac, later[0])
        out.append((n['s'], max(e, n['s'] + 0.05), n['p']))
    return out

if __name__ == '__main__':
    ref = load_midi('bench/YeuEm_ref.mid')
    M = {'tk': load_midi('bench/transkun.mid', 60), 'ms': load_midi('bench/ms_raw.mid', 60), 'bp': load_midi('bench/bp_raw.mid', 60)}
    M = {k: [n for n in v if 40 <= n[2] <= 88 and n[0] >= 0.06] for k, v in M.items()}
    notes = clusters(M)
    cut = lambda ns: [x for x in ns if x[0] < 30]
    for name, rule in RULES.items():
        print(f'{name:12}', metrics(ref, cut([(n['s'], max(rule(n, notes), n['s'] + .05), n['p']) for n in notes])))
    print('top-voice   ', metrics(ref, cut(top_voice_rule(notes))))
