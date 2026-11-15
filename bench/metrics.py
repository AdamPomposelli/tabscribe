"""Full comparison vs the reference: notes (onset+pitch), durations (onset+offset), rhythm."""
import sys, json, numpy as np, pretty_midi as pm, mir_eval

def load_midi(p, lim=30.0):
    m = pm.PrettyMIDI(p)
    return [(n.start, n.end, n.pitch) for i in m.instruments if not i.is_drum for n in i.notes if n.start < lim]

def arr(ns):
    return (np.array([[s, max(e, s + 0.02)] for s, e, p in ns]).reshape(-1, 2),
            np.array([pm.note_number_to_hz(p) for s, e, p in ns]))

def metrics(ref, est, tol=0.05):
    R, RP = arr(ref); E, EP = arr(est)
    out = {}
    for name, kw in (('notes', dict(offset_ratio=None)), ('dur20', dict(offset_ratio=0.2)), ('dur50', dict(offset_ratio=0.5))):
        p, r, f, _ = mir_eval.transcription.precision_recall_f1_overlap(R, RP, E, EP, onset_tolerance=tol, **kw)
        out[name] = (round(p, 3), round(r, 3), round(f, 3))
    # rhythm: onset-only F1 ignoring pitch (were attacks placed at the right times?)
    ro = np.unique(np.round(R[:, 0], 3)); eo = np.unique(np.round(E[:, 0], 3))
    out['rhythm'] = round(mir_eval.onset.f_measure(ro, eo, window=tol)[0], 3)
    return out

if __name__ == '__main__':
    ref = load_midi(sys.argv[1])
    for p in sys.argv[2:]:
        print(f'{p.split("/")[-1]:28}', metrics(ref, load_midi(p)))
