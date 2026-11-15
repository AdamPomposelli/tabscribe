"""Accuracy of a beat tracker output (json) vs Songscription beats, on the original and
on the tempo-warped 'live' versions; also through Tabscribe's grid repair (build_grid)."""
import sys, json, numpy as np
sys.path.insert(0, 'bench/tempo'); sys.path.insert(0, 'backend')
from beat_metrics import ref_beats, score
from tabscribe import rhythm

S = '/private/tmp/claude-501/-Users-adampomposelli-Documents-Github/c38ea7b1-afef-4cf0-9403-982dc247e4d6/scratchpad/tempo'
CASES = {  # name: (reference midi, limit s, map json or None)
    'yeu': ('bench/YeuEm_ref.mid', 30, None), 'hoa': ('bench/hoa_ref.mid', None, None),
    'yeu_live': ('bench/YeuEm_ref.mid', 30, f'{S}/yeu_live.wav.map.json'),
    'hoa_live': ('bench/hoa_ref.mid', None, f'{S}/hoa_live.wav.map.json'),
}
for k in (2, 3):
    CASES[f'yeu_live{k}'] = ('bench/YeuEm_ref.mid', 30, f'{S}/yeu_live{k}.wav.map.json')
    CASES[f'hoa_live{k}'] = ('bench/hoa_ref.mid', None, f'{S}/hoa_live{k}.wav.map.json')


HARMONIC = False


def warp_fn(mp):
    if not mp: return None
    m = json.load(open(mp)); t, w = np.array(m['t']), np.array(m['w'])
    return lambda x: np.interp(np.asarray(x), t, w)


def evaluate(case, beats, downbeats):
    ref, lim, mp = CASES[case]
    wf = warp_fn(mp)
    rb, rd = ref_beats(ref, warp=wf, lim=lim)
    if HARMONIC:  # downbeats where the chords change (1 beat off Songscription's bar lines)
        rd = rb[(1 if 'hoa' in case else 3)::4]
    raw = score(rb, rd, beats, downbeats)
    g = rhythm.build_grid(np.asarray(beats), np.asarray(downbeats), rb[0], rb[-1], 0)
    gb = g.beats[g.first_beat_index:]
    grid = score(rb, rd, gb, gb[::g.beats_per_bar])
    return raw, grid


if __name__ == '__main__':
    case, path = sys.argv[1], sys.argv[2]
    d = json.load(open(path))
    raw, grid = evaluate(case, d['beats'], d['downbeats'])
    print(f"{case:9} raw  {raw}\n{'':9} grid {grid}  ({d.get('seconds', '?')} s)")
