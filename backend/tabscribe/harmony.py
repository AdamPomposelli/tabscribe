"""Key estimation and chord naming from the transcribed notes.

Key: Krumhansl-Kessler profiles on duration-weighted pitch classes.
Chords: template matching over each half-bar, root biased towards the bass
note, with extended qualities (maj7/9/13/sus) as seen on pro transcriptions.
"""
from __future__ import annotations

import numpy as np

NAMES_SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
NAMES_FLAT = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]

MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

# number of sharps(+)/flats(-) for major keys by tonic pitch class
KEY_SIG_MAJOR = {0: 0, 7: 1, 2: 2, 9: 3, 4: 4, 11: 5, 6: 6, 1: -5, 8: -4, 3: -3, 10: -2, 5: -1}


def estimate_key(notes) -> dict:
    pc = np.zeros(12)
    for n in notes:
        pc[n.pitch % 12] += (n.end - n.start) * (1.5 if n.pitch < 55 else 1.0)
    if pc.sum() == 0:
        return {"tonic": 0, "mode": "major", "name": "C", "accidentals": 0}
    best = None
    for t in range(12):
        for mode, prof in (("major", MAJOR), ("minor", MINOR)):
            r = np.corrcoef(pc, np.roll(prof, t))[0, 1]
            if best is None or r > best[0]:
                best = (r, t, mode)
    _, t, mode = best
    rel_major = t if mode == "major" else (t + 3) % 12
    acc = KEY_SIG_MAJOR[rel_major]
    names = NAMES_FLAT if acc < 0 else NAMES_SHARP
    return {"tonic": t, "mode": mode, "name": names[t] + ("m" if mode == "minor" else ""), "accidentals": acc}


# (suffix, intervals, weight-of-required) - order matters for ties (simpler first)
TEMPLATES = [
    ("", (0, 4, 7)), ("m", (0, 3, 7)), ("5", (0, 7)),
    ("7", (0, 4, 7, 10)), ("maj7", (0, 4, 7, 11)), ("m7", (0, 3, 7, 10)),
    ("sus4", (0, 5, 7)), ("sus2", (0, 2, 7)), ("6", (0, 4, 7, 9)), ("m6", (0, 3, 7, 9)),
    ("add9", (0, 4, 7, 2)), ("madd9", (0, 3, 7, 2)),
    ("maj9", (0, 4, 7, 11, 2)), ("m9", (0, 3, 7, 10, 2)), ("9", (0, 4, 7, 10, 2)),
    ("13", (0, 4, 10, 2, 9)), ("7sus4", (0, 5, 7, 10)),
    ("dim", (0, 3, 6)), ("m7b5", (0, 3, 6, 10)), ("aug", (0, 4, 8)),
]
COMPLEXITY = {s: 0.04 * (len(iv) - 3) for s, iv in TEMPLATES}


def name_chord(weights: np.ndarray, bass_pc: int | None, accidentals: int, with_score: bool = False):
    total = weights.sum()
    if total <= 0 or (weights > 0.05 * total).sum() < 2:
        return (None, 0.0) if with_score else None
    w = weights / total
    best = None
    for root in range(12):
        for suffix, iv in TEMPLATES:
            tones = {(root + i) % 12 for i in iv}
            covered = sum(w[t] for t in tones)
            missing = sum(1 for t in tones if w[t] < 0.03)
            # the 5th may be omitted in extended chords
            if missing and (root + 7) % 12 in tones and w[(root + 7) % 12] < 0.03 and len(iv) >= 4:
                missing -= 1
            score = covered - 0.22 * missing - COMPLEXITY[suffix]
            if bass_pc is not None and bass_pc == root:
                score += ROOT_BONUS
            if w[root] < 0.03:
                score -= 0.3
            if best is None or score > best[0]:
                best = (score, root, suffix)
    score, root, suffix = best
    if score < 0.45:
        return (None, score) if with_score else None
    names = NAMES_FLAT if accidentals < 0 else NAMES_SHARP
    name = names[root] + suffix
    if bass_pc is not None and bass_pc != root and bass_pc in {(root + i) % 12 for i in (4, 3, 7, 10, 11)}:
        name += "/" + names[bass_pc]
    return (name, score) if with_score else name


BASS_WEIGHT = 0.6      # extra weight of the bass note (root anchor)
ROOT_BONUS = 0.12      # template score bonus when the bass is the chord root
RING_WEIGHT = 0.35     # notes ringing in from before the segment


def _segment_profile(notes, a, b):
    """Attack-weighted pitch-class profile. Sustain lengths are unreliable across
    transcription models (MuScriptor shortens bass notes), attacks are not."""
    w = np.zeros(12)
    seg = b - a
    attacks = [n for n in notes if a <= n.start < b]
    ringing = [n for n in notes if n.start < a < n.end]
    for n in attacks:
        w[n.pitch % 12] += 1.0 + 0.5 * min(1.0, (n.end - n.start) / (seg / 2))
    for n in ringing:
        w[n.pitch % 12] += RING_WEIGHT
    # bass: lowest note attacked in the first half (else lowest ringing at the start)
    early = [n for n in attacks if n.start < a + seg / 2] or ringing
    bass = min(early, key=lambda n: n.pitch).pitch % 12 if early else None
    if bass is not None:
        w[bass] += BASS_WEIGHT
    return w, bass


def chords_per_bar(notes, bar_len: int, n_bars: int, accidentals: int, split_margin: float = 0.12):
    """One chord per bar; split in halves only when the harmony clearly changes mid-bar."""
    out = []  # (tick, name)
    prev = None
    for bar in range(n_bars):
        a, b = bar * bar_len, (bar + 1) * bar_len
        full, s_full = name_chord(*_segment_profile(notes, a, b), accidentals, with_score=True)
        h = bar_len // 2
        n1, s1 = name_chord(*_segment_profile(notes, a, a + h), accidentals, with_score=True)
        n2, s2 = name_chord(*_segment_profile(notes, a + h, b), accidentals, with_score=True)
        root = lambda nm: nm.split("/")[0].rstrip("0123456789").replace("maj", "").replace("sus", "").replace("add", "").replace("m", "")[:2] if nm else None
        if n1 and n2 and root(n1) != root(n2) and (s1 + s2) / 2 > s_full + split_margin:
            parts = [(a, n1), (a + h, n2)]
        else:
            parts = [(a, full)]
        for t, nm in parts:
            if nm and nm != prev:
                out.append((t, nm))
            if nm:
                prev = nm
    return out
