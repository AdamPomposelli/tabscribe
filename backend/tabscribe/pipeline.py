"""End-to-end pipeline: audio -> notes -> beat grid -> fingering -> score -> files."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Callable

import numpy as np

from . import audio, cleanup, fingering, harmony, rhythm, score, export, transcribe
from .cleanup import Note
from .rhythm import TPQ

TUNINGS = {
    "standard": [64, 59, 55, 50, 45, 40],
    "drop_d": [64, 59, 55, 50, 45, 38],
    "half_step_down": [63, 58, 54, 49, 44, 39],
    "open_g": [62, 59, 55, 50, 43, 38],
    "dadgad": [62, 57, 55, 50, 45, 38],
}


@dataclass
class Options:
    engine: str = "auto"            # auto | ensemble | basic-pitch | muscriptor
    muscriptor_size: str = "medium"
    separate: bool = False          # isolate guitar from a mix (BS-RoFormer SW, Demucs htdemucs_6s fallback)
    difficulty: str = "original"    # original | intermediate | beginner
    transpose: int = 0
    tuning: str = "standard"
    capo: int = 0
    title: str = ""
    artist: str = ""
    learned_fingering: bool = True
    beats_per_bar: int = 0          # time signature override: 0 = auto-detect, else 2 / 3 / 4
    beat_refine: bool = True        # onset-guided beat correction for live / no-metronome playing
    key: str = ""                   # key signature override ("F", "Dm", "F#m"...); "" = detect automatically


def parse_key(name: str) -> dict | None:
    """'Bb' / 'F#m' / 'Dm' -> the same dict as harmony.estimate_key, or None if not a key."""
    name = (name or "").strip()
    minor = name.endswith("m")
    root = name[:-1] if minor else name
    pcs = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
    if not root or root[0] not in pcs or len(root) > 2 or (len(root) == 2 and root[1] not in "#b"):
        return None
    t = (pcs[root[0]] + (1 if root.endswith("#") else -1 if root.endswith("b") and len(root) == 2 else 0)) % 12
    acc = harmony.KEY_SIG_MAJOR[(t + 3) % 12 if minor else t]
    if root.endswith("b") and len(root) == 2 and acc > 0:  # spelled with flats (Ebm, not D#m)
        acc -= 12
    elif root.endswith("#") and acc < 0:  # spelled with sharps (C#, not Db)
        acc += 12
    return {"tonic": t, "mode": "minor" if minor else "major", "name": name, "accidentals": acc}


def _log(progress, stage, frac, msg=""):
    if progress:
        progress(stage, frac, msg)


def transcribe_audio(src: Path, workdir: Path, opts: Options, progress: Callable | None = None) -> dict:
    """Heavy part (models). Caches notes + beats in workdir so edits re-run instantly."""
    workdir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    wav = workdir / "audio.wav"
    if not wav.exists():
        _log(progress, "decode", 0.02, "Decoding audio")
        audio.decode_to_wav(src, wav)
    analysis_audio = wav
    if opts.separate:
        from . import separation
        label = separation.engine_label()
        _log(progress, "separate", 0.08, f"Isolating guitar ({label})")
        stem = workdir / "guitar_stem.wav"
        if not stem.exists():
            if not separation.available():
                raise RuntimeError("Guitar isolation is not installed: add it in Settings → Components")
            separation.isolate_guitar(wav, stem, progress=lambda f: _log(progress, "separate", 0.08 + 0.04 * f,
                                                                        f"Isolating guitar ({label})"))
        analysis_audio = stem

    engine = opts.engine
    if engine == "auto":
        if transcribe.vote_available():
            engine = "vote"
        elif transcribe.muscriptor_available():
            engine = "ensemble"
        else:
            engine = "basic-pitch"
    _log(progress, "transcribe", 0.3, f"Transcribing notes ({engine})")
    sep = "_sep" if opts.separate else ""

    def cached(name, fn):
        path = workdir / f"notes_{name}{sep}.json"
        if path.exists():
            return [Note(**d) for d in json.loads(path.read_text())]
        notes = fn()
        path.write_text(json.dumps([asdict(n) for n in notes]))
        return notes

    def run_bp():
        return transcribe.basic_pitch(analysis_audio)[0]

    def run_ms():
        return transcribe.muscriptor(analysis_audio, opts.muscriptor_size,
                                     progress=lambda f: _log(progress, "transcribe", 0.3 + 0.35 * f,
                                                             f"Transcribing notes (MuScriptor {opts.muscriptor_size})"))[0]

    harmony_notes = None  # high-recall evidence for chord naming
    if engine == "vote":
        steps = [("bp", "basic-pitch", run_bp)]
        if transcribe.muscriptor_available():  # optional 7th model (non-commercial weights)
            steps.append(("ms", f"muscriptor-{opts.muscriptor_size}", run_ms))
        steps.append(("tk", "transkun", lambda: transcribe.transkun(analysis_audio)))
        steps += [(key, f"tsumugi-{t}", (lambda t=t: transcribe.tsumugi(analysis_audio, t)))
                  for key, t in transcribe.TSUMUGI_TYPES.items()]
        models = {}
        for i, (key, name, fn) in enumerate(steps):
            _log(progress, "transcribe", 0.12 + 0.55 * i / len(steps), f"Transcribing ({i + 1}/{len(steps)}): {name}")
            models[key] = cached(name, fn)
        voted = transcribe.vote(models, k=4)  # 4 of 7, or 4 of 6 without MuScriptor (same note F1 on both reference songs)
        from . import arpeggio
        raw = transcribe.align_chords(voted, 0.06, protect=arpeggio.raw_roll_members(voted))
        harmony_notes = models.get("ms")
    elif engine == "ensemble":
        bp = cached("basic-pitch", run_bp)
        ms = cached(f"muscriptor-{opts.muscriptor_size}", run_ms)
        raw = transcribe.ensemble(ms, bp)
        harmony_notes = ms
    elif engine == "muscriptor":
        raw = cached(f"muscriptor-{opts.muscriptor_size}", run_ms)
        harmony_notes = raw
    else:
        raw = cached("basic-pitch", run_bp)
    info = {"engine": engine, "raw_count": len(raw)}

    beats_cache = workdir / "beats.json"
    b = json.loads(beats_cache.read_text()) if beats_cache.exists() else {}
    if b.get("tracker") == rhythm.tracker_name():
        beats, downbeats = np.array(b["beats"]), np.array(b["downbeats"])
    else:
        _log(progress, "beats", 0.7, "Tracking beats and downbeats")
        beats, downbeats = rhythm.track_beats(wav)
        beats_cache.write_text(json.dumps({"beats": beats.tolist(), "downbeats": downbeats.tolist(),
                                           "tracker": rhythm.tracker_name()}))
    chord_pred = None
    from . import tschords
    if tschords.available():
        cpath = workdir / f"tschords_{engine}{sep}.json"
        if cpath.exists():
            chord_pred = json.loads(cpath.read_text())
        else:
            _log(progress, "chords", 0.75, "Recognising chords, key and meter (Tsumugi beat/chord model)")
            try:
                chord_pred = tschords.run(raw)
                cpath.write_text(json.dumps(chord_pred))
            except Exception as e:
                print(f"[tabscribe] chord model skipped: {e}")
    return {"raw": raw, "harmony_notes": harmony_notes, "chord_pred": chord_pred, "beats": beats, "downbeats": downbeats, "engine": engine, "info": info,
            "seconds": round(time.time() - t0, 2), "duration": audio.duration(wav)}


def simplify(qnotes: list[score.QNote], level: str) -> list[score.QNote]:
    if level == "original":
        return qnotes
    groups: dict[int, list[score.QNote]] = {}
    for n in qnotes:
        groups.setdefault(n.start, []).append(n)
    out = []
    for t, ns in sorted(groups.items()):
        ns = sorted(ns, key=lambda n: n.pitch)
        if level == "intermediate":
            keep = {ns[0].idx, ns[-1].idx}
            if len(ns) > 2:
                keep.add(max(ns[1:-1], key=lambda n: n.velocity).idx)
            out += [n for n in ns if n.idx in keep]
        else:  # beginner: melody line + bass on beats
            out.append(ns[-1])
            if len(ns) > 1 and ns[0].pitch <= score.BASS_MAX_PITCH and t % TPQ == 0:
                out.append(ns[0])
    if level == "beginner":  # snap to 8ths
        for n in out:
            n.start = int(round(n.start / 480) * 480)
            n.end = max(n.start + 480, int(round(n.end / 480) * 480))
        seen, ded = set(), []
        for n in out:
            if (n.start, n.pitch) not in seen:
                seen.add((n.start, n.pitch)); ded.append(n)
        out = ded
    return out


def arrange(tr: dict, workdir: Path, opts: Options, progress: Callable | None = None) -> dict:
    """Light part: cleanup, grid, quantize, fingering, harmony, score, exports (~1 s)."""
    tuning = TUNINGS.get(opts.tuning, TUNINGS["standard"])
    _log(progress, "arrange", 0.85, "Cleaning notes and quantizing")
    params = cleanup.params_for(tr["engine"], min_pitch=min(tuning) + opts.capo - opts.transpose)
    notes = cleanup.clean(tr["raw"], params)
    notes = [Note(n.start, n.end, n.pitch + opts.transpose, n.velocity, n.onset_strength) for n in notes]
    if not notes:
        raise RuntimeError("No notes detected in this audio.")

    from . import tschords
    meter = opts.beats_per_bar if opts.beats_per_bar in (2, 3, 4) else (tschords.meter(tr["chord_pred"]) if tr.get("chord_pred") else 0)
    beats = np.asarray(tr["beats"], float)
    if opts.beat_refine and len(beats) >= 8:
        from . import beatfix
        beats = beatfix.refine(rhythm.repair(beats), [(n.start, n.pitch, n.velocity) for n in tr["raw"]])
    grid = rhythm.build_grid(beats, tr["downbeats"], notes[0].start, max(n.end for n in notes), beats_per_bar=meter)
    ticks, _subdiv = rhythm.quantize_onsets(grid, [n.start for n in notes])
    ends, _ = rhythm.quantize_onsets(grid, [n.end for n in notes])
    q = []
    for i, (n, t, e) in enumerate(zip(notes, ticks, ends)):
        if t < 0:
            continue
        q.append(score.QNote(i, n.pitch, t, max(e, t + 120), n.velocity, time=n.start, end_time=n.end))
    # one note per pitch per tick
    seen, dedup = set(), []
    for n in sorted(q, key=lambda n: (n.start, n.pitch, -n.velocity)):
        if (n.start, n.pitch) not in seen:
            seen.add((n.start, n.pitch)); dedup.append(n)
    # rolled chords: gather the staggered attacks into one chord with an arpeggio sign
    from . import arpeggio
    rolls = arpeggio.detect(dedup)
    for chain, direction, anchor in rolls:
        for k in chain:
            n = dedup[k]
            n.start, n.end, n.arpeggio = anchor, max(n.end, anchor + 240), direction
    seen, merged = set(), []
    for n in sorted(dedup, key=lambda n: (n.start, n.pitch, -n.velocity)):
        if (n.start, n.pitch) not in seen:
            seen.add((n.start, n.pitch)); merged.append(n)
    q = simplify(merged, opts.difficulty)

    _log(progress, "fingering", 0.9, "Choosing strings and frets")
    max_fret = 7 if opts.difficulty == "beginner" else fingering.MAX_FRET
    fnotes = [fingering.FNote(n.idx, n.pitch, n.start, n.end, n.velocity) for n in q]
    priors, arranger = None, "tabscribe"
    if opts.learned_fingering:
        from . import openfret
        if openfret.available():
            try:
                _log(progress, "fingering", 0.9, "Arranging fingering (Open-Fret + playability search)")
                raw_pr = openfret.note_priors([{"id": n.idx, "start": n.start, "end": n.end, "pitch": n.pitch} for n in q],
                                              tuning, opts.capo)
                priors = {int(k): v for k, v in raw_pr.items()}
                arranger = "open-fret+tabscribe"
            except Exception as e:  # the learned prior is an improvement, never a requirement
                print(f"[tabscribe] Open-Fret prior skipped: {e}")
    asg, unplaced = fingering.assign(fnotes, tuning, opts.capo, max_fret, priors=priors)
    q = [n for n in q if n.idx in asg]
    for n in q:
        n.string, n.fret = asg[n.idx]

    score.split_voices(q)
    key = parse_key(opts.key) or harmony.estimate_key(notes)
    bar_len = grid.beats_per_bar * TPQ
    n_bars = max(n.end for n in q) // bar_len + 1
    measures = score.build_measures(q, grid, n_bars)

    # chords: the ensemble keeps only notes both models agree on (best for the staff) but
    # drops harmony evidence; MuScriptor's full output names chords far better (14/15 vs 10/15 roots)
    if tr.get("harmony_notes"):
        hq = [score.QNote(-1, n.pitch + opts.transpose, int(grid.time_to_tick(n.start)),
                          int(grid.time_to_tick(n.end)), n.velocity) for n in tr["harmony_notes"]]
        hq = [n for n in hq if n.start >= 0]
    else:
        hq = q
    if tr.get("chord_pred"):
        bar_chords, prev = [], None
        for c in tr["chord_pred"]["chords"]:
            name = tschords.label_to_name(c["label"], key, opts.transpose)
            tick = int(round(grid.time_to_tick(c["start"] + 0.02) / 480) * 480)  # chord changes on 8th positions
            if name and name != prev and tick >= 0:
                if bar_chords and bar_chords[-1][0] == tick:
                    bar_chords[-1] = (tick, name)
                else:
                    bar_chords.append((tick, name))
                prev = name
    else:
        bar_chords = harmony.chords_per_bar(hq, bar_len, n_bars, key["accidentals"])
    segs = [(t, t + bar_len) for t, _ in bar_chords]
    for k in range(len(segs) - 1):
        segs[k] = (segs[k][0], min(segs[k][1], segs[k + 1][0]))
    score.attach_chords(measures, q, [nm for _, nm in bar_chords], segs, tuning, opts.capo)

    # where should the capo go? (independent of the capo currently chosen)
    from . import capo as capo_mod
    # judge on the notes as they'd be without any capo (the current one already dropped the low ones)
    pitches = [n.pitch for n in q] if not opts.capo else [
        n.pitch + opts.transpose for n in cleanup.clean(tr["raw"], cleanup.params_for(
            tr["engine"], min_pitch=min(tuning) - opts.transpose))]
    capo_hint = capo_mod.suggest([(nm, b - a) for (_, nm), (a, b) in zip(bar_chords, segs)],
                                 pitches, tuning, key["tonic"], key["mode"] == "minor")

    _log(progress, "export", 0.95, "Writing Guitar Pro / MIDI")
    title = opts.title or "Untitled"
    export.write_gp5(workdir / "score.gp5", measures, title=title, artist=opts.artist,
                     tempo=round(grid.bpm), beats_per_bar=grid.beats_per_bar,
                     key_accidentals=key["accidentals"], key_minor=key["mode"] == "minor",
                     tuning=tuning, capo=opts.capo)
    export.write_midi(workdir / "score.mid", q, grid, quantized=True)
    export.write_midi(workdir / "performance.mid", q, grid, quantized=False)

    result = {
        "title": title, "artist": opts.artist, "engine": tr["engine"], "duration": tr["duration"],
        "tempo": round(grid.bpm), "key": key, "beats_per_bar": grid.beats_per_bar,
        "tuning": tuning, "capo": opts.capo, "options": asdict(opts),
        "grid": grid.to_json(),
        "notes": [{"pitch": n.pitch, "tick": n.start, "end_tick": n.end, "time": round(n.time, 4),
                   "end_time": round(n.end_time, 4), "string": n.string, "fret": n.fret, "voice": n.voice,
                   "velocity": round(n.velocity, 3), "arpeggio": n.arpeggio} for n in q],
        "raw_notes": [{"pitch": n.pitch, "time": round(n.start, 4), "end_time": round(n.end, 4),
                       "velocity": round(n.velocity, 3)} for n in tr["raw"]],
        "chords": [{"tick": c.tick, "name": c.name, "frets": c.frets} for m in measures for c in m.chords],
        "arranger": arranger,
        "capo_suggestion": capo_hint,
        "stats": {"raw": len(tr["raw"]), "clean": len(notes), "placed": len(q), "unplaced": len(unplaced),
                  "bars": n_bars, "transcribe_seconds": tr["seconds"], "rolled_chords": len(rolls)},
    }
    (workdir / "result.json").write_text(json.dumps(result))
    _log(progress, "done", 1.0, "Done")
    return result


def run(src: Path, workdir: Path, opts: Options, progress: Callable | None = None) -> dict:
    return arrange(transcribe_audio(src, workdir, opts, progress), workdir, opts, progress)
