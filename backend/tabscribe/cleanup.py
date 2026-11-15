"""Note-event cleanup: removes the typical polyphonic-transcription artefacts.

Combines ideas from the reference projects (range filter, short-note removal,
same-pitch merge, octave fix) with two targeted filters for guitar:
  * overtone suppression - partials (+12, +19, +24, +28 semitones) of a louder
    note that is already sounding are discarded;
  * re-attack merge - a same-pitch note that starts while the previous one is
    still ringing, without a clear onset peak, is merged into it.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
import numpy as np

OVERTONES = (12, 19, 24, 28, 31)
FPS = 22050 / 256  # Basic Pitch frame rate
MIDI_OFFSET = 21


@dataclass(frozen=True)
class Note:
    start: float
    end: float
    pitch: int
    velocity: float  # 0..1 amplitude/confidence
    onset_strength: float = 1.0


@dataclass
class CleanupParams:
    min_pitch: int = 40           # E2 (standard tuning); lowered for drop tunings
    max_pitch: int = 88           # E6
    min_duration: float = 0.06
    min_velocity: float = 0.40
    rel_velocity: float = 0.30     # drop notes quieter than this * local max
    overtone_ratio: float = 1.0    # overtone kept only if louder than ratio * fundamental
    overtone_window: float = 0.10  # onset distance considered "same attack"
    reattack_onset: float = 0.60   # min onset strength to accept a re-attack
    merge_gap: float = 0.05
    cut_in: float = 0.06           # notes 'starting' before this are the tail of a cut recording


def params_for(engine: str, **kw) -> CleanupParams:
    """Basic Pitch needs the full artefact cleanup; MuScriptor emits clean symbolic notes
    without amplitudes/onset posteriors, so only range/duration/cut-in filters apply."""
    if engine == "vote":  # majority of 7 models: the vote itself is the filter
        return CleanupParams(min_velocity=0.0, rel_velocity=0.0, overtone_ratio=-1.0,
                             reattack_onset=0.0, min_duration=0.03, **kw)
    if engine == "ensemble":  # already confirmed by two models: keep only light filters
        return CleanupParams(min_velocity=0.2, rel_velocity=0.15, overtone_ratio=-1.0,
                             reattack_onset=0.0, **kw)
    if engine.startswith("muscriptor"):
        return CleanupParams(min_velocity=0.0, rel_velocity=0.0, overtone_ratio=-1.0,
                             reattack_onset=0.0, min_duration=0.03, **kw)
    return CleanupParams(**kw)


def onset_strength(note_start: float, pitch: int, onsets: np.ndarray | None) -> float:
    if onsets is None:
        return 1.0
    f = int(round(note_start * FPS))
    k = pitch - MIDI_OFFSET
    if not 0 <= k < onsets.shape[1]:
        return 0.0
    lo, hi = max(0, f - 2), min(onsets.shape[0], f + 3)
    return float(onsets[lo:hi, k].max()) if hi > lo else 0.0


def clean(notes: list[Note], p: CleanupParams | None = None) -> list[Note]:
    p = p or CleanupParams()
    notes = sorted(notes, key=lambda n: (n.start, n.pitch))

    # 1. cut-in tail (audio starting mid-sound has no measurable attack), range, duration, level
    notes = [n for n in notes if n.start >= p.cut_in and p.min_pitch <= n.pitch <= p.max_pitch
             and n.end - n.start >= p.min_duration and n.velocity >= p.min_velocity]

    # 2. relative level: compare with the loudest note in a +-0.5 s neighbourhood
    starts = np.array([n.start for n in notes])
    vels = np.array([n.velocity for n in notes])
    keep = []
    for i, n in enumerate(notes):
        m = (starts > n.start - 0.5) & (starts < n.start + 0.5)
        if n.velocity >= p.rel_velocity * vels[m].max():
            keep.append(n)
    notes = keep

    # 3. overtone suppression
    out = [] if p.overtone_ratio >= 0 else list(notes)
    for n in (notes if p.overtone_ratio >= 0 else []):
        is_partial = False
        for q in notes:
            if q is n or q.pitch >= n.pitch or (n.pitch - q.pitch) not in OVERTONES:
                continue
            sounding = q.start - p.overtone_window <= n.start <= q.end
            if not sounding:
                continue
            same_attack = abs(q.start - n.start) <= p.overtone_window
            # partial of a simultaneous attack, or a later onset-less partial of a ringing note
            if (same_attack and n.velocity < p.overtone_ratio * q.velocity + 0.1) or \
               (not same_attack and n.onset_strength < p.reattack_onset and n.velocity < q.velocity):
                is_partial = True
                break
        if not is_partial:
            out.append(n)
    notes = out

    # 4. same-pitch re-attack merge
    by_pitch: dict[int, list[Note]] = {}
    for n in notes:
        by_pitch.setdefault(n.pitch, []).append(n)
    merged = []
    for pitch, ns in by_pitch.items():
        cur = ns[0]
        for n in ns[1:]:
            ringing = n.start <= cur.end + p.merge_gap
            if ringing and n.onset_strength < p.reattack_onset:
                cur = replace(cur, end=max(cur.end, n.end), velocity=max(cur.velocity, n.velocity))
            else:
                merged.append(cur)
                cur = n
        merged.append(cur)
    return sorted(merged, key=lambda n: (n.start, n.pitch))
