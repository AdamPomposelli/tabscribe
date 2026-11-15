"""Learned offset selection with honest leave-one-bar-out cross-validation.

For each voted note we generate candidate end times (each model's offset + structural
candidates from the score context), all snapped to a 16th grid. A logistic model scores
candidates; the best-scoring one is the note's end. Each bar is predicted by a model
trained on the *other* bars only."""
import sys, json, numpy as np
sys.path.insert(0, 'bench'); sys.path.insert(0, 'backend')
from metrics import load_midi, metrics
from bigvote import load_all, cluster
from vote import match
from quant import grid_for
from tabscribe import rhythm, fingering
from sklearn.linear_model import LogisticRegression

TPQ = rhythm.TPQ
MODELS = ['tk', 'ms', 'bp', 'tsd', 'tsg', 'tsg15', 'tso']
STRUCT = ['next_onset', 'next_same_string', 'next_bass', 'next_bass_m8', 'next_downbeat', 'next_downbeat_m8', 'next_top']
CANDS = MODELS + STRUCT

def build(notes, grid):
    beats = lambda t: grid.time_to_tick(t) / TPQ
    on = [round(beats(n['s']) * 4) / 4 for n in notes]
    bar = grid.beats_per_bar
    groups = {}
    for i, o in enumerate(on): groups.setdefault(o, []).append(i)
    bass_on = sorted(o for o, ix in groups.items() if min(notes[i]['p'] for i in ix) <= 52)
    top_on = sorted(groups)
    fn = [fingering.FNote(i, n['p'], int(on[i] * TPQ), int(beats(n['e']) * TPQ), 0.8) for i, n in enumerate(notes)]
    asg, _ = fingering.assign(fn)
    rows = []
    for i, n in enumerate(notes):
        o = on[i]
        nxt = lambda arr: next((x for x in arr if x > o + 1e-6), o + 4)
        ac = [beats(n['ends'][m]) for m in ('tk', 'tso', 'tsg') if m in n['ends']]
        acm = float(np.median(ac)) if ac else beats(n['e'])
        same_str = [on[j] for j in asg if i in asg and asg[j][0] == asg[i][0] and on[j] > o + 1e-6]
        c = {}
        for m in MODELS:
            if m in n['ends']: c[m] = beats(n['ends'][m])
        c['next_onset'] = nxt(top_on)
        c['next_same_string'] = min(same_str) if same_str else None
        c['next_bass'] = nxt(bass_on)
        c['next_bass_m8'] = nxt(bass_on) - 0.5
        db = (np.floor(o / bar) + 1) * bar
        c['next_downbeat'], c['next_downbeat_m8'] = db, db - 0.5
        top_of_group = n['p'] == max(notes[j]['p'] for j in groups[o])
        c['next_top'] = nxt(top_on) if top_of_group else None
        for k in list(c):
            if c[k] is None or c[k] <= o + 0.2: c.pop(k); continue
            c[k] = round(c[k] * 4) / 4
        feats_note = [n['p'] / 88, float(n['p'] <= 52), float(top_of_group), len(n['ends']) / 7, (acm - o) / 4]
        rows.append({'i': i, 'on': o, 'bar': int(o // bar), 'cands': c, 'fn': feats_note, 'acm': acm})
    return rows

def cand_features(r, name, val):
    o = r['on']
    onehot = [float(name == k) for k in CANDS]
    dur = val - o
    agree = sum(1 for v in r['cands'].values() if abs(v - val) < 0.13) / len(r['cands'])
    return onehot + r['fn'] + [dur / 4, abs(val - r['acm']) / 4, agree, float(dur <= 0.5)]

def evaluate(notes, rows, grid, ref):
    beats_to_t = lambda b: grid.tick_to_time(b * TPQ)
    mm = match(ref, [(n['s'], 0, n['p']) for n in notes], 0.06)
    label = {}
    for ri, (s, e, p) in enumerate(ref):
        if ri in mm:
            j = mm[ri]; tol = max(0.05, 0.2 * (e - s))
            label[j] = {k: abs(beats_to_t(v) - e) <= tol for k, v in rows[j]['cands'].items()}
    bars = sorted({r['bar'] for r in rows})
    chosen = {}
    for b in bars:
        X, y = [], []
        for r in rows:
            if r['bar'] == b or r['i'] not in label: continue
            for k, v in r['cands'].items():
                X.append(cand_features(r, k, v)); y.append(label[r['i']][k])
        clf = LogisticRegression(C=1.0, max_iter=2000).fit(X, y)
        for r in rows:
            if r['bar'] != b: continue
            best = max(r['cands'].items(), key=lambda kv: clf.decision_function([cand_features(r, *kv)])[0])
            chosen[r['i']] = best[1]
    return chosen, label

if __name__ == '__main__':
    ref = load_midi('bench/YeuEm_ref.mid'); M = load_all(); notes = cluster(M, 4, onset_order=['ms', 'tsd', 'tk'])
    for n in notes: n['e'] = n['ends'].get('tk', float(np.median(list(n['ends'].values()))))
    g = grid_for([(n['s'], n['e'], n['p']) for n in notes])
    # restrict training/eval to the region covered by the reference (first 30 s)
    notes = [n for n in notes if n['s'] < 30]
    rows = build(notes, g)
    oracle = sum(1 for r in rows if True)
    chosen, label = evaluate(notes, rows, g, ref)
    cov = sum(any(l.values()) for l in label.values()) / max(1, len(label))
    print(f'oracle coverage of candidates (within 20%): {cov:.3f}')
    est = [(n['s'], g.tick_to_time(chosen[i] * TPQ), n['p']) for i, n in enumerate(notes)]
    print('learned selector (leave-one-bar-out):', metrics(ref, est))
