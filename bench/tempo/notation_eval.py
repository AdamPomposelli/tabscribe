"""Notation F1 (right 16th slot, beat domain) on originals + simulated live takes."""
import sys, json, contextlib, io, shutil
from pathlib import Path
sys.path.insert(0, 'bench'); sys.path.insert(0, 'bench/tempo'); sys.path.insert(0, 'backend')
from notation_metric import ref_positions, f1
from eval_tracker import CASES
from tabscribe import pipeline
from tabscribe.pipeline import arrange, Options
S = Path('/private/tmp/claude-501/-Users-adampomposelli-Documents-Github/c38ea7b1-afef-4cf0-9403-982dc247e4d6/scratchpad/tempo')
PROJ = {'yeu': '49151cb1adc9', 'hoa': '5edf9eeec0db'}
for case in ['yeu', 'hoa', 'yeu_live', 'hoa_live', 'yeu_live3', 'hoa_live3']:
    if '_' in case:
        d = S / f'e2e_{case}'
    else:
        d = S / f'orig_{case}'; d.mkdir(exist_ok=True); src = Path(f'data/projects/{PROJ[case]}')
        for f in src.glob('notes_*.json'): shutil.copy(f, d / f.name)
        for f in ('audio.wav', 'tschords_vote.json'): shutil.copy(src / f, d / f)
    ref_mid, lim, _ = CASES[case]
    ref = ref_positions(ref_mid, lim=lim)
    end = max(b for b, _ in ref)
    with contextlib.redirect_stdout(io.StringIO()):
        tr = pipeline.transcribe_audio(d / 'audio.wav', d, Options(engine='vote'))
    row = []
    for refine in (False, True):
        with contextlib.redirect_stdout(io.StringIO()):
            r = arrange(tr, d, Options(engine='vote', beat_refine=refine))
        est = [(n['tick'] / 960, n['pitch']) for n in r['notes'] if n['tick'] / 960 <= end + 8]
        row.append(f1(ref, est))
    print(f"{case:10} notation F1  dbn {row[0]:.3f}  dbn+fix {row[1]:.3f}", flush=True)
