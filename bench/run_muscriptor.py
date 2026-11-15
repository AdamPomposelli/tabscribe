import sys, time, json
sys.path.insert(0, 'backend')
from dataclasses import asdict
from pathlib import Path
from tabscribe import transcribe
import pretty_midi as pm
t = time.time()
notes, info = transcribe.muscriptor(Path('bench/YeuEm.mp3'), 'medium', progress=lambda f: print(f'progress {f:.0%}', flush=True))
print('notes', len(notes), 'seconds', round(time.time() - t, 1), flush=True)
json.dump([asdict(n) for n in notes], open('bench/ms_medium_notes.json', 'w'))
m = pm.PrettyMIDI(); inst = pm.Instrument(24)
inst.notes = [pm.Note(100, n.pitch, n.start, n.end) for n in notes]; m.instruments.append(inst); m.write('bench/ms_medium.mid')
