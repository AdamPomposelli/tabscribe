"""Chord recognition, v2: half-bar segmentation, compact vocabulary, key prior,
Viterbi smoothing and key-aware spelling (E#, B# in sharp keys).

Built to match how engraved guitar transcriptions label harmony: one symbol per
half bar (or per bar when it does not change), plain qualities (maj, m, 7, m7,
maj7, sus2/sus4, dim, m7b5), inversions as slash chords, extensions only when
the evidence is strong.
"""
from __future__ import annotations

import numpy as np

# quality -> (intervals, required, prior cost)
QUALITIES = {
    "":     ((0, 4, 7), 0.00),
    "m":    ((0, 3, 7), 0.00),
    "7":    ((0, 4, 7, 10), 0.06),
    "m7":   ((0, 3, 7, 10), 0.05),
    "maj7": ((0, 4, 7, 11), 0.10),
    "sus4": ((0, 5, 7), 0.10),
    "sus2": ((0, 2, 7), 0.14),
    "dim":  ((0, 3, 6), 0.18),
    "m7b5": ((0, 3, 6, 10), 0.16),
    "m9":   ((0, 3, 7, 10, 2), 0.20),
    "add9": ((0, 4, 7, 2), 0.20),
}
MAJOR_SCALE = (0, 2, 4, 5, 7, 9, 11)
# diatonic triad qualities by scale degree in major (I ii iii IV V vi vii°)
DIATONIC_MAJOR = {0: ("", "maj7"), 2: ("m", "m7"), 4: ("m", "m7"), 5: ("", "maj7"), 7: ("", "7", "sus4"),
                  9: ("m", "m7"), 11: ("dim", "m7b5")}
LETTERS = ["C", "D", "E", "F", "G", "A", "B"]
LETTER_PC = [0, 2, 4, 5, 7, 9, 11]
SHARP_KEYS_ORDER = [7, 2, 9, 4, 11, 6, 1]  # G D A E B F# C#
FLAT_KEYS_ORDER = [5, 10, 3, 8, 1, 6, 11]  # F Bb Eb Ab Db Gb Cb


def key_scale_names(tonic: int, mode: str, accidentals: int) -> dict[int, str]:
    """Pitch-class -> spelled name for the 7 scale degrees of the key (so E# in F# major)."""
    rel = tonic if mode == "major" else (tonic + 3) % 12
    # letter of the tonic of the relative major
    if accidentals >= 0:
        names = {0: "C", 7: "G", 2: "D", 9: "A", 4: "E", 11: "B", 6: "F#", 1: "C#"}
    else:
        names = {0: "C", 5: "F", 10: "Bb", 3: "Eb", 8: "Ab", 1: "Db", 6: "Gb", 11: "Cb"}
    tname = names.get(rel, "C")
    li = LETTERS.index(tname[0])
    out = {}
    for k, step in enumerate(MAJOR_SCALE):
        pc = (rel + step) % 12
        letter = LETTERS[(li + k) % 7]
        diff = (pc - LETTER_PC[LETTERS.index(letter)]) % 12
        acc = {0: "", 1: "#", 2: "##", 11: "b", 10: "bb"}.get(diff, "")
        out[pc] = letter + acc
    return out


def spell(pc: int, key_names: dict[int, str], accidentals: int) -> str:
    if pc in key_names:
        return key_names[pc]
    sharp = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    flat = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
    return (flat if accidentals < 0 else sharp)[pc]


def profile(notes, a, b):
    """Attack-weighted pitch-class profile + bass for the segment [a, b) (ticks)."""
    w = np.zeros(12)
    seg = b - a
    tol = 120  # notes played "on" the boundary often land a few ms early
    attacks = [n for n in notes if a - tol <= n.start < b - tol]
    ringing = [n for n in notes if n.start < a - tol and n.end > a]
    for n in attacks:
        w[n.pitch % 12] += 1.0 + 0.5 * min(1.0, (n.end - n.start) / seg)
    for n in ringing:
        w[n.pitch % 12] += 0.35
    early = [n for n in attacks if n.start < a + seg / 2] or ringing
    bass = min(early, key=lambda n: n.pitch).pitch % 12 if early else None
    return w, bass


def candidates(tonic: int, mode: str):
    rel = tonic if mode == "major" else (tonic + 3) % 12
    out = []
    for root in range(12):
        deg = (root - rel) % 12
        for q, (iv, cost) in QUALITIES.items():
            diatonic = deg in DIATONIC_MAJOR and q in DIATONIC_MAJOR[deg]
            in_scale = all(((root + i - rel) % 12) in MAJOR_SCALE for i in iv)
            prior = cost + (0.0 if diatonic else (0.08 if in_scale else 0.22))
            out.append((root, q, iv, prior))
    return out


def emission(w, bass, cand):
    root, q, iv, prior = cand
    tot = w.sum()
    if tot <= 0:
        return 9.0
    p = w / tot
    tones = {(root + i) % 12 for i in iv}
    covered = sum(p[t] for t in tones)
    missing = sum(1 for t in tones if p[t] < 0.02)
    if (root + 7) % 12 in tones and p[(root + 7) % 12] < 0.02 and len(iv) >= 3:
        missing -= 0.6  # the fifth is often omitted
    cost = (1 - covered) * 2.2 + 0.35 * missing + prior
    if p[root] < 0.02:
        cost += 0.5
    if bass is not None:
        if bass == root:
            cost -= 0.25
        elif bass not in tones:
            cost += 0.15
    return cost


def recognise(notes, bar_len: int, n_bars: int, key: dict, beats_per_bar: int, change_cost: float = 0.25):
    """Returns [(tick, name)] - one symbol per half bar (merged when unchanged)."""
    half = bar_len // 2 if beats_per_bar % 2 == 0 else bar_len
    segs = [(a, a + half) for a in range(0, n_bars * bar_len, half)]
    cands = candidates(key["tonic"], key["mode"])
    E = []
    profs = []
    for a, b in segs:
        w, bass = profile(notes, a, b)
        profs.append((w, bass))
        E.append([emission(w, bass, c) for c in cands])
    E = np.array(E)
    # Viterbi: staying is free, changing costs `change_cost` (halved on a bar line)
    S, C = E.shape
    D = E[0].copy(); back = np.zeros((S, C), int)
    for s in range(1, S):
        on_bar = segs[s][0] % bar_len == 0
        cc = change_cost * (0.6 if on_bar else 1.0)
        best_prev = D.argmin()
        stay = D
        move = D[best_prev] + cc
        choose_stay = stay <= move
        back[s] = np.where(choose_stay, np.arange(C), best_prev)
        D = np.minimum(stay, move) + E[s]
    path = [int(D.argmin())]
    for s in range(S - 1, 0, -1):
        path.append(int(back[s][path[-1]]))
    path.reverse()
    names = key_scale_names(key["tonic"], key["mode"], key["accidentals"])
    out, prev = [], None
    for (a, b), ci, (w, bass) in zip(segs, path, profs):
        if w.sum() <= 0:
            continue
        root, q, iv, _ = cands[ci]
        name = spell(root, names, key["accidentals"]) + q
        tones = {(root + i) % 12 for i in iv}
        if bass is not None and bass != root and (bass in tones or (bass - root) % 12 in (10, 11, 2)):
            name += "/" + spell(bass, names, key["accidentals"])
        if name != prev:
            out.append((a, name))
            prev = name
    return out
