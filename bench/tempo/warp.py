"""Simulate a live performance without a metronome: time-warp a recording with a known,
smooth-but-irregular tempo curve (drift, push/pull, ritardando) using WSOLA (pitch kept).
The exact time map lets us warp the reference MIDI too, so the truth stays known."""
import json, sys
import numpy as np, soundfile as sf, librosa


def speed_curve(t, seed=0, depth=1.0):
    rng = np.random.default_rng(seed)
    p = rng.uniform(0, 2 * np.pi, 4)
    s = (1 + depth * (0.12 * np.sin(2 * np.pi * t / 29 + p[0])      # slow drift +-12%
                      + 0.06 * np.sin(2 * np.pi * t / 9.1 + p[1])   # phrase push/pull
                      + 0.03 * np.sin(2 * np.pi * t / 3.3 + p[2])))  # local rubato
    return s


def make_map(dur, seed=0, depth=1.0, dt=0.001):
    """forward map original time -> performed time (integral of 1/speed)."""
    t = np.arange(0, dur + 1, dt)
    s = speed_curve(t, seed, depth)
    w = np.concatenate([[0], np.cumsum(dt / s[:-1])])
    return t, w


def wsola(y, sr, t_orig, t_warp, frame=2048, hop=512, tol=256):
    win = np.hanning(frame)
    n_out = int(t_warp[-1] * sr) - frame
    out = np.zeros(n_out + frame); norm = np.zeros(n_out + frame)
    prev = None
    for k in range(0, n_out, hop):
        src = int(np.interp((k + frame / 2) / sr, t_warp, t_orig) * sr - frame / 2)
        if src < tol or src + frame + tol >= len(y):
            continue
        if prev is not None:  # best continuation of the previous frame within +-tol
            ref = y[prev + hop: prev + hop + frame]
            seg = y[src - tol: src + tol + frame]
            c = np.correlate(seg, ref, 'valid')
            src = src - tol + int(np.argmax(c))
        out[k:k + frame] += y[src:src + frame] * win; norm[k:k + frame] += win
        prev = src
    return out / np.maximum(norm, 1e-3)


if __name__ == '__main__':
    src, dst, seed, depth = sys.argv[1], sys.argv[2], int(sys.argv[3]), float(sys.argv[4])
    y, sr = librosa.load(src, sr=44100, mono=True)
    t, w = make_map(len(y) / sr, seed, depth)
    sf.write(dst, wsola(y, sr, t, w), sr)
    json.dump({"t": t[::10].round(4).tolist(), "w": w[::10].round(5).tolist()}, open(dst + '.map.json', 'w'))
