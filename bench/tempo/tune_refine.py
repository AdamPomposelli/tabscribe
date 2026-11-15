import sys, io, contextlib, itertools, numpy as np
sys.path.insert(0, 'bench/tempo')
import eval_refine as er
C = ['yeu', 'hoa', 'yeu_live', 'hoa_live', 'yeu_live2', 'hoa_live2', 'yeu_live3', 'hoa_live3']
base = {}
import json
from eval_tracker import evaluate
for c in C:
    d = json.load(open(f'{er.S}/bt_{c}.json')); base[c] = evaluate(c, d['beats'], d['downbeats'])[1]['F']
print('baseline', {c: base[c] for c in C}, 'mean %.3f' % np.mean(list(base.values())))
rows = []
for a, tw, sg in itertools.product([2, 4, 6, 10], [0.4, 0.8, 1.5], [0.04, 0.06, 0.1]):
    with contextlib.redirect_stdout(io.StringIO()):
        r = er.run(C, ALPHA=a, TRACK_W=tw, TRACK_SIGMA=sg)
    f = {c: r[c]['F'] for c in C}
    rows.append((np.mean(list(f.values())), min(f[c] - base[c] for c in C), a, tw, sg, f))
rows.sort(key=lambda r: -r[0])
for r in rows[:6]: print('mean %.3f worst-delta %+.3f  ALPHA %s TRACK_W %s SIGMA %s' % r[:5], r[5])
