"""Beat / downbeat tracking and quantization onto a musical grid.

None of the reference projects tracked beats (they snapped to a grid starting at
t=0 with a fixed BPM). Here the grid follows the performer: beats and downbeats
come from `beat_this` (CPJKU, ISMIR 2024) with madmom's DBN, are corrected against the
transcribed attacks (beatfix.py, for performances without a metronome), gaps are repaired, and every note is
placed on the tick grid by interpolating between the actual beat times, so a
rubato performance still lands on clean 8ths/16ths/triplets.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
import numpy as np

from . import MODELS_DIR, hf_file

TPQ = 960  # ticks per quarter note
_tracker = None


def _load_beat_this(device: str):
    import beat_this.inference as bi
    from beat_this.model.beat_tracker import BeatThis
    from safetensors.torch import load_file

    local = MODELS_DIR / "beat_this"
    cfg_path = hf_file("safe-models/beat-this-final0", "config.json", local)
    w_path = hf_file("safe-models/beat-this-final0", "model.safetensors", local)

    def load_model(_ckpt, dev):
        m = BeatThis(**json.load(open(cfg_path)))
        m.load_state_dict(load_file(w_path), strict=False)  # only rotary buffers are recomputed
        return m.to(dev).eval()

    bi.load_model = load_model
    return bi.File2Beats(checkpoint_path="final0", device=device, dbn=_has_dbn())


def _has_dbn() -> bool:
    """beat_this + madmom's DBN post-processing (BSD code, no madmom model weights): best of
    7 trackers on our live-performance stress test (beat F 0.949 vs 0.894 without, downbeats
    1.00 vs 0.88), ~1.5 s extra per minute. Falls back to plain peak picking."""
    try:
        import madmom.features.downbeats  # noqa: F401
        return True
    except Exception:
        return False


def tracker_name() -> str:
    return "beat_this-final0" + ("+dbn" if _has_dbn() else "")


def track_beats(audio_path) -> tuple[np.ndarray, np.ndarray]:
    global _tracker
    if _tracker is None:
        import torch
        dev = "cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() and not _has_dbn() else "cpu")  # the DBN needs float64 (no MPS)
        _tracker = _load_beat_this(dev)
    beats, downbeats = _tracker(str(audio_path))
    return np.asarray(beats, float), np.asarray(downbeats, float)


@dataclass
class Grid:
    beats: np.ndarray            # beat times (s), repaired + extended
    bar_starts: list[int]        # indices into beats where bars start
    beats_per_bar: int
    bpm: float
    first_beat_index: int = 0    # index of beat that is tick 0 (bar 1, beat 1)
    pickup_beats: int = 0
    tempo_curve: list[tuple[int, float]] = field(default_factory=list)  # (tick, bpm)

    def time_to_tick(self, t: float) -> float:
        b = self.beats
        i = np.searchsorted(b, t) - 1
        i = int(np.clip(i, 0, len(b) - 2))
        frac = (t - b[i]) / (b[i + 1] - b[i])
        return (i - self.first_beat_index + frac) * TPQ

    def tick_to_time(self, tick: float) -> float:
        pos = tick / TPQ + self.first_beat_index
        i = int(np.clip(np.floor(pos), 0, len(self.beats) - 2))
        return float(self.beats[i] + (pos - i) * (self.beats[i + 1] - self.beats[i]))

    def to_json(self) -> dict:
        return {"beats": [round(float(x), 4) for x in self.beats], "first_beat_index": self.first_beat_index,
                "beats_per_bar": self.beats_per_bar, "bpm": round(self.bpm, 2), "tpq": TPQ}


def repair(beats: np.ndarray) -> np.ndarray:
    """Fill beats the tracker skipped (e.g. half-time in a sparse intro). The expected period
    is the song's median beat: on the live-performance stress test a local (drifting)
    period was worse, half-time intros become ambiguous once the tempo drifts."""
    beats = np.asarray(beats, float)
    if len(beats) < 3:
        return beats
    med = float(np.median(np.diff(beats)))
    fixed = [beats[0]]
    for a, b in zip(beats[:-1], beats[1:]):
        k = int(round((b - a) / med))
        if k >= 2:
            fixed.extend(a + (b - a) * j / k for j in range(1, k))
        fixed.append(b)
    return np.array(fixed)


def build_grid(beats: np.ndarray, downbeats: np.ndarray, notes_start: float, notes_end: float,
               beats_per_bar: int = 0) -> Grid:
    """beats_per_bar: 0 = detect from downbeats, else force the meter (2, 3 or 4)."""
    forced = beats_per_bar
    if len(beats) < 4:  # no usable pulse: fall back to 100 bpm
        beats = np.arange(0, notes_end + 2, 0.6)
        downbeats = beats[::4]
    beats = repair(beats)
    med = float(np.median(np.diff(beats)))
    # extend so every note lies inside the grid
    pre = []
    t = beats[0] - med
    while t > notes_start - 2 * med:
        pre.insert(0, t); t -= med
    post = []
    t = beats[-1] + med
    while t < notes_end + 2 * med:
        post.append(t); t += med
    beats = np.concatenate([pre, beats, post])

    # meter: most common number of beats between downbeats
    db_idx = sorted({int(np.argmin(np.abs(beats - d))) for d in downbeats})
    gaps = np.diff(db_idx)
    beats_per_bar = forced or (int(np.bincount(gaps).argmax()) if len(gaps) else 4)
    if beats_per_bar not in (2, 3, 4, 6):
        beats_per_bar = 4
    # phase: align bars to the downbeat phase that occurs most often
    phase = int(np.bincount([i % beats_per_bar for i in db_idx]).argmax()) if db_idx else 0
    # first beat at/after the first note's beat, on the right phase -> bar 1
    first_note_beat = int(np.clip(np.searchsorted(beats, notes_start - 0.07) , 0, len(beats) - 1))
    start = first_note_beat - ((first_note_beat - phase) % beats_per_bar)
    pickup = 0
    if start < first_note_beat:
        # notes begin mid-bar: keep a full bar of rest rather than an anacrusis (as engravers do for transcriptions)
        pass
    start = max(start, 0)
    bar_starts = list(range(start, len(beats) - 1, beats_per_bar))
    bpm = 60.0 / med
    g = Grid(beats=beats, bar_starts=bar_starts, beats_per_bar=beats_per_bar, bpm=bpm,
             first_beat_index=start, pickup_beats=pickup)
    # smoothed tempo per bar (for playback with the synth)
    curve = []
    for bi_ in bar_starts:
        seg = np.diff(beats[bi_:bi_ + beats_per_bar + 1])
        if len(seg):
            curve.append(((bi_ - start) * TPQ, 60.0 / float(np.mean(seg))))
    g.tempo_curve = curve
    return g


# ---------------------------------------------------------------- quantization
SUBDIV_STRAIGHT = 4   # 16ths
SUBDIV_TRIPLET = 3    # 8th-note triplets
TRIPLET_PENALTY = 0.07   # (in beats) bias towards straight subdivisions (triplets only when clearly played)


def quantize_onsets(grid: Grid, times: list[float]) -> tuple[list[int], dict[int, int]]:
    """Return quantized ticks and, per beat index, the chosen subdivision (3 or 4)."""
    raw = [grid.time_to_tick(t) / TPQ for t in times]  # in beats
    by_beat: dict[int, list[int]] = {}
    for i, r in enumerate(raw):
        by_beat.setdefault(int(np.floor(r + 1 / 8)), []).append(i)
    ticks = [0] * len(times)
    subdiv: dict[int, int] = {}
    for beat, idxs in by_beat.items():
        best = None
        for sd in (SUBDIV_STRAIGHT, SUBDIV_TRIPLET):
            q = [round((raw[i] - beat) * sd) / sd for i in idxs]
            err = sum(abs(raw[i] - beat - qq) for i, qq in zip(idxs, q)) / len(idxs)
            if sd == SUBDIV_TRIPLET:
                err += TRIPLET_PENALTY
                # a triplet beat needs at least two distinct off-grid positions to be credible
                if len({qq for qq in q if qq not in (0.0, 1.0)}) < 1:
                    err += 1
            if best is None or err < best[0]:
                best = (err, sd, q)
        _, sd, q = best
        subdiv[beat] = sd
        for i, qq in zip(idxs, q):
            ticks[i] = int(round((beat + qq) * TPQ))
    return ticks, subdiv
