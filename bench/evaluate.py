"""Score a transcription MIDI against the reference with mir_eval (first `limit` seconds)."""
import sys, numpy as np, pretty_midi as pm, mir_eval

def load(path, limit):
    m = pm.PrettyMIDI(path)
    notes = [n for i in m.instruments if not i.is_drum for n in i.notes if n.start < limit]
    iv = np.array([[n.start, max(n.end, n.start + 0.05)] for n in notes]) if notes else np.zeros((0, 2))
    p = np.array([pm.note_number_to_hz(n.pitch) for n in notes])
    return iv, p

def best_offset(ref, est):
    """Global time shift maximising onset matches (handles leading-silence differences)."""
    best = (0, -1)
    for off in np.arange(-1.0, 1.0, 0.01) if True else []:
        if len(est[0]) == 0: break
        if (ref[0] - off).min() < 0: continue
        _, _, f, _ = mir_eval.transcription.precision_recall_f1_overlap(ref[0] - off, ref[1], est[0], est[1], onset_tolerance=0.05, offset_ratio=None)
        if f > best[1]: best = (off, f)
    return best[0]

def score(ref_path, est_path, limit=30.0, align=True):
    ref, est = load(ref_path, limit), load(est_path, limit)
    off = best_offset(ref, est) if align else 0.0
    eiv = est[0]; ref = (ref[0] - off, ref[1])
    out = {'n_ref': len(ref[1]), 'n_est': len(est[1]), 'offset': round(float(off), 2)}
    for tol in (0.05, 0.1):
        p, r, f, _ = mir_eval.transcription.precision_recall_f1_overlap(ref[0], ref[1], eiv, est[1], onset_tolerance=tol, offset_ratio=None)
        out[f'F1@{int(tol*1000)}ms'] = round(f, 3); out[f'P@{int(tol*1000)}'] = round(p, 3); out[f'R@{int(tol*1000)}'] = round(r, 3)
    # pitch-class/chroma-agnostic of octave: onset-only metric
    return out

if __name__ == '__main__':
    print(score(sys.argv[1], sys.argv[2], float(sys.argv[3]) if len(sys.argv) > 3 else 30.0))
