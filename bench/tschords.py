"""Run Tsumugi's beat/chord/key model on a note list and convert its chords to our ticks."""
import sys, json, subprocess, tempfile, numpy as np
sys.path.insert(0, 'backend')
from pathlib import Path
import pretty_midi
ROOT = Path(__file__).resolve().parents[1]
TS = ROOT / 'vendor' / 'tsumugi'; PY = ROOT / '.venv-tsumugi' / 'bin' / 'python'

def run(notes):
    """notes: (start, end, pitch) seconds. Returns the prediction dict."""
    with tempfile.TemporaryDirectory() as td:
        m = pretty_midi.PrettyMIDI(); inst = pretty_midi.Instrument(24)
        inst.notes = [pretty_midi.Note(90, int(p), float(s), float(max(e, s + 0.05))) for s, e, p in notes]
        m.instruments.append(inst); mid = Path(td) / 'in.mid'; m.write(str(mid)); out = Path(td) / 'out.json'
        subprocess.run([str(PY), '-m', 'instrument_agnostic_amt.beat_chord.cli.infer', '--checkpoint',
                        str(TS / 'checkpoints' / 'best_beat_chord_key.pth'), '--midi_path', str(mid), '--output_path', str(out),
                        '--disable_beat_mapped_midi', '--device', 'mps'], cwd=TS, check=True, capture_output=True)
        return json.loads(out.read_text())

def conv(lbl):
    if lbl in ('N', 'X', ''): return None
    main, _, bass = lbl.partition('/')
    root, _, q = main.partition(':')
    q = {'maj': '', 'min': 'm'}.get(q, q)
    return root + q + ('/' + bass if bass else '')
