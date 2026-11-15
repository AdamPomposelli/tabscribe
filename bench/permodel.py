"""Per-model and vote metrics for a project vs a reference MIDI (whole song)."""
import sys, json
sys.path.insert(0, 'bench'); sys.path.insert(0, 'backend')
from metrics import load_midi, metrics
from tabscribe.cleanup import Note
from tabscribe import transcribe
NAMES = {'bp': 'basic-pitch', 'ms': 'muscriptor-medium', 'tk': 'transkun', 'tsd': 'tsumugi-default',
         'tsg': 'tsumugi-guitar', 'tsg15': 'tsumugi-guitar_v1_5', 'tso': 'tsumugi-other_v1_5'}

def load_models(P):
    return {k: [Note(**d) for d in json.load(open(f'{P}/notes_{v}.json'))] for k, v in NAMES.items()}

def flt(ns, lim=1e9):
    return [(n.start, n.end, n.pitch) for n in ns if 40 <= n.pitch <= 88 and 0.06 <= n.start < lim]

if __name__ == '__main__':
    ref_path, P = sys.argv[1], sys.argv[2]
    lim = float(sys.argv[3]) if len(sys.argv) > 3 else 1e9
    ref = load_midi(ref_path, lim)
    M = load_models(P)
    for k, v in M.items(): print(f'{k:6}', metrics(ref, flt(v, lim)))
    for k in (2, 3, 4, 5):
        print(f'vote k>={k}', metrics(ref, flt(transcribe.vote(M, k=k), lim)))
