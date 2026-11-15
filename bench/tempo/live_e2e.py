"""End-to-end benchmark on the simulated live (tempo-warped) recordings: full transcription
(7-model vote) + arrangement with and without beat refinement, vs the warped Songscription MIDI."""
import sys, json, shutil, contextlib, io, time
from pathlib import Path
import numpy as np, pretty_midi as pm
sys.path.insert(0, 'bench'); sys.path.insert(0, 'bench/tempo'); sys.path.insert(0, 'backend')
from metrics import load_midi, metrics
from eval_tracker import CASES, warp_fn
from tabscribe.pipeline import transcribe_audio, arrange, Options
S = Path('/private/tmp/claude-501/-Users-adampomposelli-Documents-Github/c38ea7b1-afef-4cf0-9403-982dc247e4d6/scratchpad/tempo')

def warped_ref(case):
    ref, lim, mp = CASES[case]
    wf = warp_fn(mp)
    ns = load_midi(ref, lim or 999)
    return [(float(wf(s)), float(wf(e)), p) for s, e, p in ns], (float(wf(lim)) if lim else 999)

for case in sys.argv[1:]:
    d = S / f'e2e_{case}'; d.mkdir(exist_ok=True)
    shutil.copy(S / f'{case}.wav', d / 'audio.wav')
    t = time.time()
    with contextlib.redirect_stdout(io.StringIO()):
        tr = transcribe_audio(d / 'audio.wav', d, Options(engine='vote'))
    secs = time.time() - t
    ref, lim = warped_ref(case)
    for refine in (False, True):
        o = Options(engine='vote', beat_refine=refine)
        with contextlib.redirect_stdout(io.StringIO()):
            arrange(tr, d, o)
        m = metrics(ref, load_midi(str(d / 'score.mid'), lim))
        print(f"{case:9} refine={refine!s:5} notes {m['notes'][2]:.3f} rhythm {m['rhythm']:.3f} dur20 {m['dur20'][2]:.3f}  (transcribe {secs:.0f}s)", flush=True)
