"""End-to-end benchmark of the real pipeline on both reference songs."""
import sys, json, shutil, contextlib, io
from pathlib import Path
sys.path.insert(0, 'bench'); sys.path.insert(0, 'backend')
from metrics import load_midi, metrics
import hoa_chords as hc, chord_bench as cb
from tabscribe.pipeline import transcribe_audio, arrange, Options
S = Path('/private/tmp/claude-501/-Users-adampomposelli-Documents-Github/c38ea7b1-afef-4cf0-9403-982dc247e4d6/scratchpad/full')
SONGS = [('YeuEm', 'data/projects/49151cb1adc9', 'bench/YeuEm_ref.mid', 30.0),
         ('hoa', 'data/projects/5edf9eeec0db', 'bench/hoa_ref.mid', 999.0)]

def refrolls(ref):
    R, i = [], 0
    while i < len(ref):
        grp = [ref[i]]; j = i + 1
        while j < len(ref) and 0.04 <= ref[j][0] - grp[-1][0] <= 0.09: grp.append(ref[j]); j += 1
        if len(grp) >= 3: R.append(grp[0][0]); i = j
        else: i += 1
    return R

def run(fresh_chords=True, opts_kw=None):
    rows = {}
    for name, P, refp, lim in SONGS:
        d = S / name
        d.mkdir(parents=True, exist_ok=True)
        for f in Path(P).glob('notes_*.json'): shutil.copy(f, d / f.name)
        for f in ('audio.wav', 'beats.json'): shutil.copy(Path(P) / f, d / f)
        if fresh_chords:
            for f in d.glob('tschords_*.json'): f.unlink()
        o = Options(engine='vote', title=name, **(opts_kw or {}))
        with contextlib.redirect_stdout(io.StringIO()):
            r = arrange(transcribe_audio(Path(P) / 'source.mp3', d, o), d, o)
        ref = load_midi(refp, lim); est = load_midi(str(d / 'score.mid'), lim)
        m = metrics(ref, est)
        if name == 'hoa':
            chord = '%.3f/%.3f' % hc.score(r)[:2]
        else:
            chord = '%d/15' % cb.score_output(r)
        R = refrolls(sorted(ref))
        E = sorted({n['time'] for n in r['notes'] if n.get('arpeggio') and n['time'] < lim})
        Et = []
        for t in E:
            if not Et or t - Et[-1] > 0.3: Et.append(t)
        hit = sum(1 for t in R if any(abs(t - e) < 0.2 for e in Et))
        rows[name] = dict(notes=m['notes'][2], rhythm=m['rhythm'], dur20=m['dur20'][2], chords=chord,
                          rolls=f'{hit}/{len(R)} (ours {len(Et)})', meter=r['beats_per_bar'], key=r['key']['name'])
        print(f"{name:6} notes {m['notes'][2]:.3f} rhythm {m['rhythm']:.3f} dur20 {m['dur20'][2]:.3f} | chords {chord} | rolls {hit}/{len(R)} (ours {len(Et)}) | meter {r['beats_per_bar']}/4 key {r['key']['name']}")
    return rows

if __name__ == '__main__':
    run()
