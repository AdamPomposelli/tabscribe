"""Classify false positives / misses of a note list vs the reference."""
import sys, collections, numpy as np, pretty_midi as pm, mir_eval
sys.path.insert(0, 'bench')

def classify(ref, est, tol=0.05):
    R = np.array([[s, max(e, s + .02)] for s, e, p in ref]); RP = np.array([pm.note_number_to_hz(p) for s, e, p in ref])
    E = np.array([[s, max(e, s + .02)] for s, e, p in est]); EP = np.array([pm.note_number_to_hz(p) for s, e, p in est])
    mt = mir_eval.transcription.match_notes(R, RP, E, EP, onset_tolerance=tol, offset_ratio=None)
    mr = {i for i, j in mt}; me = {j for i, j in mt}
    fp = collections.Counter(); fn = collections.Counter()
    for j, (s, e, p) in enumerate(est):
        if j in me: continue
        snd = [r for r in ref if r[0] - 0.08 <= s <= r[1] + 0.03]
        near = [r for r in ref if abs(r[0] - s) <= 0.12]
        if any(r[2] == p and abs(r[0] - s) <= 0.12 for r in ref): c = 'timing 50-120ms'
        elif any(r[2] == p for r in snd): c = 're-attack of held ref note'
        elif any(abs(p - r[2]) in (12, 24) for r in near + snd): c = 'octave error'
        elif any(abs(p - r[2]) in (1, 2) for r in near): c = 'semitone/tone off'
        elif any(abs(p - r[2]) in (7, 19) for r in snd): c = 'fifth/overtone'
        else: c = 'extra note'
        fp[c] += 1
    for i, (s, e, p) in enumerate(ref):
        if i in mr: continue
        near = [x for x in est if abs(x[0] - s) <= 0.12]
        snd = [x for x in est if x[0] - 0.08 <= s <= x[1] + 0.03]
        if any(x[2] == p for x in near): c = 'timing 50-120ms'
        elif any(x[2] == p for x in snd): c = 'merged into held est note'
        elif any(abs(p - x[2]) in (12, 24) for x in near): c = 'octave error'
        elif any(abs(p - x[2]) in (1, 2) for x in near): c = 'semitone/tone off'
        else: c = 'missing'
        fn[c] += 1
    return fp, fn, len(mt)

if __name__ == '__main__':
    from metrics import load_midi
    from permodel import load_models, flt
    from tabscribe import transcribe
    ref = load_midi(sys.argv[1], 999)
    M = load_models(sys.argv[2])
    est = flt(transcribe.vote(M, k=4))
    fp, fn, n = classify(ref, est)
    print('matched', n, 'ref', len(ref), 'est', len(est))
    print('FALSE POSITIVES', dict(fp.most_common()))
    print('MISSES        ', dict(fn.most_common()))
