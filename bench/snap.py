"""Grid snapping of onset groups as rigid units (rolled chords anchored on their last note)."""
import sys, json, numpy as np
sys.path.insert(0, 'bench'); sys.path.insert(0, 'backend')
from metrics import load_midi, metrics
from permodel import load_models, flt
from tabscribe import transcribe

ONS = ('tsd', 'tsg', 'tsg15', 'tk', 'tso', 'ms', 'bp')

def align(notes, win=0.06):
    notes = sorted(notes); out = []; i = 0
    while i < len(notes):
        j = i
        while j + 1 < len(notes) and notes[j + 1][0] - notes[i][0] <= win: j += 1
        grp = notes[i:j + 1]; t = float(np.median([g[0] for g in grp])); out += [(t, e, p) for s, e, p in grp]; i = j + 1
    return out

def snap_time(beats, t, div):
    i = int(np.clip(np.searchsorted(beats, t) - 1, 0, len(beats) - 2))
    f = (t - beats[i]) / (beats[i + 1] - beats[i])
    q = round(f * div) / div
    return beats[i] + q * (beats[i + 1] - beats[i]), abs(f - q)

def rolls(notes, max_gap=0.13, max_span=0.35):
    """indices of rolled-chord chains on (start,end,pitch) lists (onset-sorted)."""
    order = sorted(range(len(notes)), key=lambda i: (notes[i][0], notes[i][2]))
    used, out = set(), []
    for a in range(len(order)):
        if order[a] in used: continue
        for direction in (1, -1):
            chain = [order[a]]
            for b in order[a + 1:]:
                x, y = notes[chain[-1]], notes[b]
                if y[0] - x[0] > max_gap or y[0] - notes[chain[0]][0] > max_span: break
                if y[0] - x[0] < 0.012 or b in used: continue
                if (y[2] - x[2]) * direction > 0: chain.append(b)
            if len(chain) >= 3 and all(notes[k][1] >= notes[chain[-1]][0] + 0.1 for k in chain):
                out.append(chain); used.update(chain); break
    return out

def snap(notes, beats, div=4, thr=0.3, roll_thr=0.45):
    notes = sorted(notes)
    out = list(notes)
    in_roll = set()
    for chain in rolls(notes):
        last = max(chain, key=lambda k: notes[k][0])
        t, d = snap_time(beats, notes[last][0], div)
        if d * div <= roll_thr:
            delta = t - notes[last][0]
            for k in chain: out[k] = (notes[k][0] + delta, notes[k][1], notes[k][2])
        in_roll.update(chain)
    for k, (s, e, p) in enumerate(notes):
        if k in in_roll: continue
        t, d = snap_time(beats, s, div)
        if d * div <= thr: out[k] = (t, e, p)
    return out

if __name__ == '__main__':
    from twosongs import SONGS
    data = [(n, load_midi(r, lim), load_models(P), np.array(json.load(open(f'{P}/result.json'))['grid']['beats']), lim) for n, r, P, lim in SONGS]
    transcribe.ONSET_PRIORITY = ONS
    for div, thr, rthr in [(4, 0, 0), (4, 0.2, 0.45), (4, 0.3, 0.45), (4, 0.4, 0.45), (4, 0.5, 0.5), (2, 0.3, 0.45), (4, 0.3, 0.0), (4, 0.4, 0.6)]:
        s = []
        for n, ref, M, beats, lim in data:
            v = align(flt(transcribe.vote(M, k=4, tol=0.12)))
            est = [x for x in snap(v, beats, div, thr, rthr) if x[0] < lim] if thr or rthr else [x for x in v if x[0] < lim]
            m = metrics(ref, est); s.append(f"{n}: notes {m['notes'][2]:.3f} rhy {m['rhythm']:.3f} dur {m['dur20'][2]:.3f}")
        print(f'div={div} thr={thr} roll={rthr}  ', '  '.join(s))
