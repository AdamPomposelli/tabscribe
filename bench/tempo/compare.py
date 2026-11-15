"""Compare beat trackers on the 8-case stress test (2 originals + 6 simulated live takes):
beat F-measure through Tabscribe's grid, with and without onset-guided refinement."""
import sys, json, io, contextlib, numpy as np
sys.path.insert(0, 'bench/tempo'); sys.path.insert(0, 'backend')
from eval_tracker import evaluate
import eval_refine as er
from tabscribe import beatfix, rhythm
S = er.S
C = ['yeu', 'hoa', 'yeu_live', 'hoa_live', 'yeu_live2', 'hoa_live2', 'yeu_live3', 'hoa_live3']
TRACKERS = sys.argv[1:] or ['bt', 'beat_this_dbn', 'madmom', 'md_beat_this', 'wavebeat', 'mixxx', 'beat_this_live']
print(f"{'tracker':16} {'orig F':>7} {'live F':>7} {'live+fix':>9} {'down S/H':>10} {'sec/60s':>8}")
for t in TRACKERS:
    fo, fl, fr, dn, secs = [], [], [], [], []
    for c in C:
        try:
            d = json.load(open(f'{S}/{t}_{c}.json'))
        except FileNotFoundError:
            continue
        b = np.asarray(d['beats'], float)
        if len(b) > 4 and np.median(np.diff(b)) < 0.45:  # double tempo (Mixxx) -> every 2nd beat
            b = b[::2]
        _, g = evaluate(c, b, d['downbeats'])
        _, g2 = evaluate(c, beatfix.refine(rhythm.repair(b), er.notes_for(c)), d['downbeats'])
        (fo if '_' not in c else fl).append(g['F'])
        if '_' in c: fr.append(g2['F'])
        if '_' not in c:
            import eval_tracker as et
            et.HARMONIC = True; dh = et.evaluate(c, b, d['downbeats'])[0]['downF']; et.HARMONIC = False
            dn.append((g['downF'], dh))
        secs.append(float(d.get('seconds', 0)) / (83 if 'hoa' in c else 74) * 60)
    if fo:
        print(f"{t:16} {np.mean(fo):7.3f} {np.mean(fl):7.3f} {np.mean(fr):9.3f} {np.mean([x[0] for x in dn]):5.2f}/{np.mean([x[1] for x in dn]):4.2f} {np.mean(secs):8.1f}")
