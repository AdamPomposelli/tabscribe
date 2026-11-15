"""Capo suggestion: where should the capo go to make this piece easy to play?

Guitarists put a capo on so that a song in an awkward key (F#, Bb, Eb...) can be played
with open-position shapes (E, A, D, G, C and their minors/7ths). We test every capo
position and score it on what actually makes the arrangement easy or impossible:

1. Range (hard constraint): with the capo on fret c, nothing below open low string + c can
   be played. Losing the song's bass notes is never acceptable, so it's a heavy penalty.
2. Chord shapes: for each chord (weighted by how long it lasts) we find the grip
   `voicings.voicing` would draw with that capo and rate it: open shape < partial barre
   < full barre / high position.
3. Open strings in the notes: the share of notes that land on an open string relative to
   the capo (ringing open strings are what makes capo arrangements sound and feel easy).
4. A small cost for higher capo positions (shorter scale, thinner sound).
"""
from __future__ import annotations

from . import voicings

MAX_CAPO = 7


def _shape_cost(frets: list[int] | None) -> float:
    if not frets:
        return 1.6
    played = [f for f in frets if f >= 0]
    fretted = [f for f in played if f > 0]
    opens = len(played) - len(fretted)
    if not fretted:
        return 0.0
    lo, hi = min(fretted), max(fretted)
    on_lowest = sum(1 for f in fretted if f == lo)
    barre = opens == 0 and on_lowest >= 2
    if opens and hi <= 3:
        return 0.0 if len(fretted) <= 3 else 0.2
    if opens and hi <= 5:
        return 0.45
    return (1.0 if barre else 0.8) + 0.04 * lo


FLAT_KEYS = {5, 10, 3, 8, 1}  # F, Bb, Eb, Ab, Db major


def _shape_name(name: str, capo: int, tonic: int | None) -> str:
    """Chord name as the hand sees it (relative to the capo), spelled in the shape key."""
    flats = None if tonic is None else ((tonic - capo) % 12 in FLAT_KEYS)
    return transpose_name(name, -capo, flats)


SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FLAT = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
# shapes guitarists actually name: prefer the open-chord spelling
PREF = {1: "C#", 3: "Eb", 6: "F#", 8: "G#", 10: "Bb"}


def transpose_name(name: str, semis: int, flats: bool | None = None) -> str:
    import re
    m = re.match(r"([A-G])(##|bb|#|b)?([^/]*)(?:/([A-G])(##|bb|#|b)?)?$", name)
    if not m or semis % 12 == 0:
        return name
    acc = {"#": 1, "b": -1, "##": 2, "bb": -2, None: 0}

    def sp(letter, a):
        pc = (voicings.PC[letter] + acc[a] + semis) % 12
        if flats is None:
            return PREF.get(pc, SHARP[pc])
        return (FLAT if flats else SHARP)[pc]
    out = sp(m.group(1), m.group(2)) + m.group(3)
    if m.group(4):
        out += "/" + sp(m.group(4), m.group(5))
    return out


def evaluate(chords: list[tuple[str, float]], pitches: list[int], tuning: list[int], capo: int) -> dict:
    low = min(tuning) + capo
    lost = sum(1 for p in pitches if p < low)
    total_w = sum(w for _, w in chords) or 1.0
    cache: dict[str, float] = {}
    shape = 0.0
    for name, w in chords:
        if name not in cache:
            cache[name] = _shape_cost(voicings.voicing(name, tuning, capo, max_fret=12))
        shape += cache[name] * w
    shape /= total_w
    opens = {o + capo for o in tuning}
    open_frac = sum(1 for p in pitches if p in opens) / max(1, len(pitches))
    # a fretted note on an open-string pitch (when it's not the only option) still lets
    # the hand stay put; the frets under the capo a hand needs most often are 0..4
    near = sum(1 for p in pitches if any(0 <= p - o - capo <= 4 for o in tuning)) / max(1, len(pitches))
    cost = (8.0 * lost / max(1, len(pitches)) + (2.0 if lost else 0.0)
            + 1.0 * shape + 0.8 * (1 - open_frac) + 0.4 * (1 - near) + 0.05 * capo)
    return {"capo": capo, "cost": round(cost, 3), "lost_notes": lost, "shape_cost": round(shape, 3),
            "open_string_share": round(open_frac, 3)}


def suggest(chords: list[tuple[str, float]], pitches: list[int], tuning: list[int],
            tonic: int | None = None, minor: bool = False) -> dict:
    """chords: (sounding chord name, duration weight). pitches: sounding note pitches.
    Returns the best capo, the ranked alternatives and the shapes the hand plays."""
    rows = [evaluate(chords, pitches, tuning, c) for c in range(0, MAX_CAPO + 1)]
    rows.sort(key=lambda r: r["cost"])
    best = rows[0]
    seen, shapes = set(), []
    for name, _ in chords:
        s = _shape_name(name, best["capo"], tonic if not minor or tonic is None else (tonic + 3) % 12) if best["capo"] else name
        if s not in seen:
            seen.add(s)
            shapes.append(s)
    key_shape = None
    if tonic is not None:
        rel = (tonic if not minor else (tonic + 3) % 12) - best["capo"]
        names = FLAT if rel % 12 in FLAT_KEYS else SHARP
        key_shape = names[(tonic - best["capo"]) % 12] + ("m" if minor else "")
    return {"capo": best["capo"], "shapes": shapes[:8], "key_shape": key_shape, "ranking": rows[:4]}
