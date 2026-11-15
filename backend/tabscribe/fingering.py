"""Notes -> (string, fret) assignment.

Learned emission (tab-labeler v3, CNN trained on GuitarSet + EGSet12, CC BY 4.0,
from the autotab-rust stack) + beam search over hand positions, with fixes for
what the reference projects got wrong:
  * each onset group (chord) is ONE search state, never one note at a time
    (tab-agent-pro put chord tones on the same string);
  * one note per string, including strings still ringing from earlier notes;
  * hard fret-span cap and a span cost on top of the emission (model card: 0.5);
  * notes that cannot be placed are reported, not silently dropped.
"""
from __future__ import annotations

import itertools
from dataclasses import dataclass
import numpy as np

from . import MODELS_DIR, hf_file

STANDARD = [64, 59, 55, 50, 45, 40]  # string 1 (high e) .. string 6 (low E)
MAX_FRET = 20
SPAN_CAP = 4          # max distance between fretted notes held together
SPAN_COST = 0.5
MOVE_COST = 0.3
RING_CONFLICT = 0.5   # re-striking a string that still rings (cuts the sustain; normal in arpeggios)
OPEN_BONUS = 0.35     # open strings ring freely and free the fretting hand
OPEN_BASS_BONUS = 1.2
HIGH_FRET_COST = 0.08
BEAM = 64
MODEL_URL_REPO = "cstr/tab-labeler-onnx"
MODEL_FILE = "tab-labeler-v3-egset.onnx"
MODEL_REV = "434976baacaf194d99f09c3c784682766bedcf97"

_session = None


def _model():
    global _session
    if _session is None:
        import onnxruntime as ort
        path = hf_file(MODEL_URL_REPO, MODEL_FILE, MODELS_DIR / "tab_labeler", MODEL_REV)
        _session = ort.InferenceSession(path, providers=["CPUExecutionProvider"])
    return _session


@dataclass
class FNote:
    idx: int
    pitch: int        # sounding pitch
    start: int        # tick
    end: int          # tick
    velocity: float
    ring_end: int = 0  # how long the string is assumed to ring (model context only)


def _emissions(groups: list[list[FNote]], capo: int, all_notes: list[FNote] | None = None) -> np.ndarray | None:
    """Log-probs [G, 6, 21] for each onset group (standard-tuning model, capo-relative).

    Each column holds every pitch *sounding* at that onset (not just the new attacks):
    in fingerstyle/arpeggios the fretting hand holds a chord shape, which is what the
    model was trained to recognise.
    """
    try:
        sess = _model()
    except Exception:
        return None
    G = len(groups)
    pres = np.zeros((G, 49), np.float32)
    for g, ns in enumerate(groups):
        t = ns[0].start
        sounding = list(ns) + [n for n in (all_notes or []) if n.start < t < max(n.end, n.ring_end)]
        for n in sounding:
            p = n.pitch - capo
            if 40 <= p <= 88:
                pres[g, p - 40] = 1
    x = np.zeros((G, 49, 9, 1), np.float32)
    for g in range(G):
        for w in range(9):
            j = g + w - 4
            if 0 <= j < G:
                x[g, :, w, 0] = pres[j]
    return sess.run(None, {sess.get_inputs()[0].name: x})[0]


def let_ring(notes: list[FNote], tpq: int = 960) -> None:
    """Estimate how long each note rings on a guitar, independent of the transcriber's
    offsets (MuScriptor ends notes at the next attack; strings keep sounding):
    bass notes ring to the next bass note, others ~2 beats or until re-struck."""
    by_start = sorted(notes, key=lambda n: n.start)
    groups: dict[int, list[FNote]] = {}
    for n in by_start:
        groups.setdefault(n.start, []).append(n)
    bass_onsets = sorted(t for t, g in groups.items() if min(x.pitch for x in g) <= 52)
    for n in by_start:
        nxt_same = next((m.start for m in by_start if m.pitch == n.pitch and m.start > n.start), None)
        if n.pitch <= 52 and n is min(groups[n.start], key=lambda x: x.pitch):
            nb = next((t for t in bass_onsets if t > n.start), n.start + 4 * tpq)
            end = min(nb, n.start + 4 * tpq)
        else:
            end = n.start + 2 * tpq
        if nxt_same is not None:
            end = min(end, nxt_same)
        n.ring_end = max(n.end, end)


PRIOR_WEIGHT = 1.0  # weight of the Open-Fret (Fretting-Transformer) prior, see openfret.py


def assign(notes: list[FNote], tuning=STANDARD, capo: int = 0, max_fret: int = MAX_FRET,
           priors: dict | None = None, prior_weight: float | None = None):
    """Returns {note.idx: (string 1..6, fret)} and the list of unplaced note idx.

    priors: optional {note.idx: {(string 1..6, fret): log_prob}} from a learned tab model."""
    pw = PRIOR_WEIGHT if prior_weight is None else prior_weight
    let_ring(notes)
    groups_d: dict[int, list[FNote]] = {}
    for n in notes:
        groups_d.setdefault(n.start, []).append(n)
    ticks = sorted(groups_d)
    groups = [sorted(groups_d[t], key=lambda n: -n.pitch) for t in ticks]
    use_model = list(tuning) == STANDARD
    em = _emissions(groups, capo, notes) if use_model else None

    def candidates(n: FNote):
        out = []
        for s, open_p in enumerate(tuning):
            f = n.pitch - open_p - capo
            if 0 <= f <= max_fret:
                out.append((s, f))
        return out

    # state: (cost, hand_pos, ringing: tuple[(string, fret, end)], assignment dict, unplaced list)
    beam = [(0.0, 0, (), {}, [])]
    for gi, (tick, grp) in enumerate(zip(ticks, groups)):
        cands = [candidates(n) for n in grp]
        new_beam = {}
        for cost, pos, ringing, asg, unpl in beam:
            ring = {s: (f, e) for s, f, e in ringing if e > tick}
            # try full placement, then progressively drop the quietest notes if impossible
            order = sorted(range(len(grp)), key=lambda i: grp[i].velocity)
            for drop_n in range(len(grp) + 1):
                dropped = set(order[:drop_n])
                idxs = [i for i in range(len(grp)) if i not in dropped and cands[i]]
                found = False
                for combo in itertools.product(*[cands[i] for i in idxs]):
                    strings = [c[0] for c in combo]
                    if len(set(strings)) != len(strings):
                        continue
                    fretted = [c[1] for c in combo if c[1] > 0]
                    held = fretted + [f for s, (f, e) in ring.items() if f > 0 and s not in strings]
                    if held and max(held) - min(held) > SPAN_CAP:
                        continue
                    if fretted and max(fretted) - min(fretted) > SPAN_CAP:
                        continue
                    c = cost
                    for i, (s, f) in zip(idxs, combo):
                        if em is not None and f + 1 < 21:
                            c += -float(em[gi, s, f + 1])
                        else:
                            c += 0.03 * f + (1.5 if em is not None else 0.0)
                        c += HIGH_FRET_COST * max(0, f - 12)
                        if priors is not None and pw:
                            lp = priors.get(grp[i].idx, {}).get((s + 1, f))
                            c += pw * (-lp if lp is not None else 6.0)
                        if f == 0:
                            # open bass strings sustain while the hand moves (fingerstyle staple)
                            c -= OPEN_BONUS + (OPEN_BASS_BONUS if grp[i].pitch <= 52 else 0.0)
                        if s in ring:
                            c += RING_CONFLICT
                    if fretted:
                        c += SPAN_COST * (max(fretted) - min(fretted))
                        new_pos = min(fretted)
                        c += MOVE_COST * abs(new_pos - pos) if pos else 0.0
                    else:
                        new_pos = pos
                    c += 6.0 * drop_n  # dropping a note is expensive
                    new_ring = {s: v for s, v in ring.items()}
                    for i, (s, f) in zip(idxs, combo):
                        new_ring[s] = (f, grp[i].end)
                    key = (new_pos, tuple(sorted((s, f) for s, (f, e) in new_ring.items())))
                    if key in new_beam and new_beam[key][0] <= c:
                        found = True
                        continue
                    a2 = dict(asg)
                    for i, (s, f) in zip(idxs, combo):
                        a2[grp[i].idx] = (s + 1, f)
                    u2 = unpl + [grp[i].idx for i in range(len(grp)) if i in dropped or not cands[i]]
                    new_beam[key] = (c, new_pos, tuple((s, f, e) for s, (f, e) in new_ring.items()), a2, u2)
                    found = True
                if found:
                    break
        beam = sorted(new_beam.values(), key=lambda b: b[0])[:BEAM] or beam
    best = beam[0]
    return best[3], best[4]
