"""Guitar-stem benchmark: run Tabscribe's transcription (vote engine) on each separated guitar
stem and score note F1 against the hoa reference (whole song).

usage: python bench/stem_bench.py <listen_dir> <work_dir> [ref.mid]
  listen_dir: folder of v01_*.wav ... stems (plus optional v00_mix.wav = unseparated mix)
Prints one row per stem: raw voted notes and final score.mid, F1 onset+pitch (50 ms) and rhythm.
"""
import sys, io, json, time, contextlib
from pathlib import Path
sys.path.insert(0, 'bench'); sys.path.insert(0, 'backend')
from metrics import load_midi, metrics
from tabscribe.pipeline import transcribe_audio, arrange, Options

listen, work = Path(sys.argv[1]), Path(sys.argv[2])
ref_path = sys.argv[3] if len(sys.argv) > 3 else 'bench/hoa_ref.mid'
LIM = 999.0
ref = load_midi(ref_path, LIM)
rows = {}
for wav in sorted(listen.glob('00_*.wav')) + sorted(listen.glob('v*.wav')):  # notes cached per workdir
    d = work / wav.stem
    d.mkdir(parents=True, exist_ok=True)
    o = Options(engine='vote', title=wav.stem)
    t = time.time()
    with contextlib.redirect_stdout(io.StringIO()):
        tr = transcribe_audio(wav, d, o)
        arrange(tr, d, o)
    raw = [(n.start, n.end, n.pitch) for n in tr['raw'] if n.start < LIM]
    mr = metrics(ref, raw)
    mf = metrics(ref, load_midi(str(d / 'score.mid'), LIM))
    rows[wav.stem] = dict(raw_notes_f1=mr['notes'][2], raw_p=mr['notes'][0], raw_r=mr['notes'][1],
                          score_notes_f1=mf['notes'][2], score_rhythm=mf['rhythm'], n_raw=len(raw),
                          seconds=round(time.time() - t, 1))
    print(f"{wav.stem:28} raw F1 {mr['notes'][2]:.3f} (P {mr['notes'][0]:.3f} R {mr['notes'][1]:.3f}, n={len(raw)})"
          f" | score F1 {mf['notes'][2]:.3f} rhythm {mf['rhythm']:.3f}", flush=True)
(work / 'results.json').write_text(json.dumps(rows, indent=1))
