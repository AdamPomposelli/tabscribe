import sys, pickle, itertools, numpy as np, pretty_midi as pm, mir_eval
sys.path.insert(0, 'backend')
from tabscribe.cleanup import Note, CleanupParams, clean, onset_strength
out, raw = pickle.load(open('bench/bp_raw.pkl', 'rb'))
onsets = out['onset']
notes = [Note(s, e, int(p), float(a), onset_strength(s, int(p), onsets)) for s, e, p, a, _ in raw]
ref = pm.PrettyMIDI('bench/YeuEm_ref.mid').instruments[0].notes
R = np.array([[n.start, n.end] for n in ref]); RP = np.array([pm.note_number_to_hz(n.pitch) for n in ref])
def f1(ns, tol=0.08):
    ns = [n for n in ns if n.start < 30]
    E = np.array([[n.start, n.end] for n in ns]); EP = np.array([pm.note_number_to_hz(n.pitch) for n in ns])
    return mir_eval.transcription.precision_recall_f1_overlap(R, RP, E, EP, onset_tolerance=tol, offset_ratio=None)[:3]
print('raw', [round(x, 3) for x in f1(notes)], len([n for n in notes if n.start < 30]))
print('default', [round(x, 3) for x in f1(clean(notes))])
best = []
for mv, rv, orat, ro in itertools.product([0.35, 0.4, 0.45, 0.5], [0.3], [0.8, 1.0, 1.2, 1.5], [0.5, 0.6, 0.7]):
    pr = CleanupParams(min_velocity=mv, rel_velocity=rv, overtone_ratio=orat, reattack_onset=ro)
    p, r, f = f1(clean(notes, pr)); best.append((f, p, r, mv, rv, orat, ro))
best.sort(reverse=True)
for b in best[:8]: print([round(x, 3) for x in b])
