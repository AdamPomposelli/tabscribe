import sys, json, time, numpy as np
sys.path.insert(0, 'bench/tempo'); sys.path.insert(0, 'backend')
from eval_tracker import evaluate, CASES, warp_fn
from tabscribe import beatfix, rhythm
def repair(b): return rhythm.repair(b)
S = '/private/tmp/claude-501/-Users-adampomposelli-Documents-Github/c38ea7b1-afef-4cf0-9403-982dc247e4d6/scratchpad/tempo'
PROJ = {'yeu': '49151cb1adc9', 'hoa': '5edf9eeec0db'}

def notes_for(case):
    raw = json.load(open(f"data/projects/{PROJ[case.split('_')[0]]}/result.json"))['raw_notes']
    wf = warp_fn(CASES[case][2]) or (lambda x: np.asarray(x))
    t = wf([n['time'] for n in raw])
    return [(float(a), n['pitch'], n['velocity']) for a, n in zip(t, raw)]

def run(cases, tracker='bt', **kw):
    for k, v in kw.items(): setattr(beatfix, k, v)
    out = {}
    for c in cases:
        d = json.load(open(f'{S}/{tracker}_{c}.json'))
        t = time.time(); rb = beatfix.refine(repair(d['beats']), notes_for(c)); dt = time.time() - t
        raw, grid = evaluate(c, rb, d['downbeats'])
        out[c] = grid
        print(f"{c:9} refined grid F {grid['F']} CMLt {grid['CMLt']:.3f} med {grid['med_ms']} p90 {grid['p90_ms']}  ({dt:.2f}s)")
    return out

if __name__ == '__main__':
    run(['yeu', 'hoa', 'yeu_live', 'hoa_live'], sys.argv[1] if len(sys.argv) > 1 else 'bt')
