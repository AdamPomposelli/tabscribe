import sys, json, numpy as np
sys.path.insert(0, 'bench'); sys.path.insert(0, 'backend')
from metrics import load_midi, metrics
from permodel import load_models, flt
from tabscribe import transcribe

def beat_pos(beats, t):
    i = int(np.clip(np.searchsorted(beats, t) - 1, 0, len(beats) - 2))
    return i, (t - beats[i]) / (beats[i + 1] - beats[i])

def quant(notes, beats, div=4, snap_frac=1.0, ends=False):
    out = []
    for s, e, p in notes:
        i, f = beat_pos(beats, s)
        q = round(f * div) / div
        if abs(f - q) * div <= snap_frac / 2:
            s2 = beats[i] + q * (beats[i + 1] - beats[i]) if i + 1 < len(beats) else s
        else:
            s2 = s
        out.append((s2, e, p))
    return out

if __name__ == '__main__':
    ref_path, P = sys.argv[1], sys.argv[2]
    ref = load_midi(ref_path, 999)
    beats = np.array(json.load(open(f'{P}/result.json'))['grid']['beats'])
    M = load_models(P)
    v = flt(transcribe.vote(M, k=4))
    print('raw vote          ', metrics(ref, v)['notes'], metrics(ref, v)['rhythm'])
    for div in (2, 4, 6, 12):
        for sf in (1.0, 0.6, 0.4):
            qv = quant(v, beats, div, sf)
            m = metrics(ref, qv)
            print(f'div={div:2} snap={sf}  ', m['notes'], m['rhythm'])
