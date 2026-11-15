"""Iterative tempo normalization: track -> warp audio to constant tempo -> re-track -> map back."""
import sys, json, time, numpy as np, soundfile as sf, librosa
sys.path.insert(0, 'backend'); sys.path.insert(0, 'bench/tempo')
from tabscribe import rhythm
from warp import wsola


def clean_beats(b):
    b = np.asarray(b, float)
    g = rhythm.build_grid(b, b[::4], b[0], b[-1], 4)  # gap repair only
    return g.beats


def beat_map(beats, dur, period):
    """original time -> normalized time: beat i lands on i*period (+ linear extrapolation)."""
    b = beats
    tgt = (np.arange(len(b))) * period + 1.0
    t = np.concatenate([[0], b, [dur + 1]])
    w = np.concatenate([[tgt[0] - (b[0] - 0) * period / (b[1] - b[0])], tgt,
                        [tgt[-1] + (dur + 1 - b[-1]) * period / (b[-1] - b[-2])]])
    return t, w


def run(path, iters=2, out_prefix=None):
    y, sr = librosa.load(path, sr=44100, mono=True)
    dur = len(y) / sr
    b, d = rhythm.track_beats(path)
    t0 = time.time()
    hist = [(b, d)]
    for k in range(iters):
        cb = clean_beats(b)
        period = float(np.median(np.diff(cb)))
        t, w = beat_map(cb, dur, period)
        if w[0] < 0: w = w - w[0]
        yn = wsola(y, sr, t, w)
        tmp = (out_prefix or '/tmp/fs_norm') + f'_it{k}.wav'
        sf.write(tmp, yn, sr)
        bn, dn = rhythm.track_beats(tmp)
        b = np.interp(bn, w, t); d = np.interp(dn, w, t)  # back to original time
        hist.append((b, d))
    return hist, time.time() - t0


if __name__ == '__main__':
    hist, sec = run(sys.argv[1], int(sys.argv[3]), sys.argv[2])
    for k, (b, d) in enumerate(hist):
        json.dump({"beats": list(map(float, b)), "downbeats": list(map(float, d)), "seconds": round(sec, 2)},
                  open(f"{sys.argv[2]}_iter{k}.json", 'w'))
