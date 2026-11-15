import sys, itertools
sys.path.insert(0, 'bench')
from metrics import load_midi, metrics

FILES = {'tk': 'transkun', 'ms': 'ms_raw', 'bp': 'bp_raw', 'tsd': 'tsumugi_default', 'tsg': 'tsumugi_guitar',
         'tsg15': 'tsumugi_guitar15', 'tso': 'tsumugi_other_v1_5'}

def load_all(lim=60):
    M = {k: load_midi(f'bench/{f}.mid', lim) for k, f in FILES.items()}
    return {k: [n for n in v if 40 <= n[2] <= 88 and n[0] >= 0.06] for k, v in M.items()}

def cluster(models, k, tol=0.09, onset_order=None, offset_order=None):
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
            oo = [m for m in (onset_order or list(models)) if m in c['m']]
            fo = [m for m in (offset_order or list(models)) if m in c['m']]
            out.append({'s': c['m'][oo[0]][0], 'p': c['p'], 'ends': {m: v[1] for m, v in c['m'].items()},
                        'starts': {m: v[0] for m, v in c['m'].items()}, 'e': c['m'][fo[0]][1]})
    return sorted(out, key=lambda n: (n['s'], n['p']))

if __name__ == '__main__':
    ref = load_midi('bench/YeuEm_ref.mid')
    M = load_all()
    res = []
    names = list(M)
    for r in range(3, len(names) + 1):
        for combo in itertools.combinations(names, r):
            sub = {n: M[n] for n in combo}
            for k in range(2, r + 1):
                v = cluster(sub, k)
                f = metrics(ref, [(n['s'], n['e'], n['p']) for n in v if n['s'] < 30])
                res.append((f['notes'][2], f['rhythm'], combo, k, f['notes']))
    res.sort(key=lambda x: (-x[0], -x[1]))
    for r in res[:12]: print(r)
