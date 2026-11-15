"""Polyphonic note transcription engines.

* basic_pitch - Spotify Basic Pitch (ICASSP 2022), ONNX, runs everywhere; used by
  all four reference projects. High recall, cleaned up by `cleanup.py`.
* muscriptor  - Kyutai x Mirelo MuScriptor transformer (MT3-style tokens), the
  strongest model seen (autotab-rust). Weights are gated on HuggingFace
  (CC BY-NC 4.0): needs `HF_TOKEN` and accepting the licence once.
"""
from __future__ import annotations

import os

import numpy as np
from pathlib import Path

from .cleanup import Note, onset_strength

_bp_model = None


def basic_pitch(path: Path, onset_threshold=0.5, frame_threshold=0.3) -> tuple[list[Note], dict]:
    global _bp_model
    from basic_pitch import ICASSP_2022_MODEL_PATH
    from basic_pitch.inference import predict, Model

    if _bp_model is None:
        _bp_model = Model(os.path.join(os.path.dirname(ICASSP_2022_MODEL_PATH), "nmp.onnx"))
    out, _midi, events = predict(
        str(path), _bp_model, onset_threshold=onset_threshold, frame_threshold=frame_threshold,
        minimum_note_length=58, minimum_frequency=75, maximum_frequency=1400, melodia_trick=True,
    )
    onsets = out["onset"]
    notes = [Note(float(s), float(e), int(p), float(a), onset_strength(float(s), int(p), onsets))
             for s, e, p, a, _bends in events]
    return notes, {"engine": "basic-pitch", "raw_count": len(notes)}


def muscriptor_weights(size: str = "medium") -> Path | None:
    """Weights installed by the app's setup (models/muscriptor/<size>/model.safetensors + config.json)."""
    from . import MODELS_DIR
    p = MODELS_DIR / "muscriptor" / size / "model.safetensors"
    return p if p.exists() and (p.parent / "config.json").exists() else None


def muscriptor_available() -> bool:
    try:
        import muscriptor  # noqa: F401
        if muscriptor_weights():
            return True
        if os.environ.get("HF_HUB_OFFLINE") == "1":
            return False
        from huggingface_hub import get_token
        return bool(os.environ.get("HF_TOKEN") or get_token())
    except Exception:
        return False


_ms_models: dict = {}

GUITAR_GROUPS = ["acoustic_guitar", "clean_electric_guitar", "distorted_electric_guitar"]


def muscriptor(path: Path, size: str = "medium", progress=None) -> tuple[list[Note], dict]:
    """Run upstream MuScriptor, hard-constrained to the guitar instrument groups."""
    from muscriptor import TranscriptionModel, NoteEndEvent
    from muscriptor.transcription_model import ProgressEvent

    if size not in _ms_models:
        local = muscriptor_weights(size)
        _ms_models[size] = TranscriptionModel.load_model(str(local) if local else size)
    model = _ms_models[size]
    notes = []
    for ev in model.transcribe(str(path), instruments=GUITAR_GROUPS):
        if isinstance(ev, NoteEndEvent):
            st = ev.start_event
            notes.append(Note(float(st.start_time), float(ev.end_time), int(st.pitch), 0.8, 1.0))
        elif isinstance(ev, ProgressEvent) and progress:
            progress(ev.completed / max(ev.total, 1))
    return notes, {"engine": f"muscriptor-{size}", "raw_count": len(notes)}


def ensemble(ms_notes: list[Note], bp_notes: list[Note], tol: float = 0.07) -> list[Note]:
    """Keep MuScriptor notes confirmed by Basic Pitch (same pitch, onset within `tol`).

    The two models fail differently (MuScriptor: spurious re-attacks of held notes;
    Basic Pitch: overtones and ghost notes), so their agreement is far more precise
    than either alone. Velocity/onset strength come from the matching Basic Pitch note.
    On YeuEm vs a pro transcription: F1 0.89 vs 0.79 (MuScriptor) / 0.82 (Basic Pitch + cleanup).
    """
    by_pitch: dict[int, list[Note]] = {}
    for n in bp_notes:
        by_pitch.setdefault(n.pitch, []).append(n)
    out = []
    for n in ms_notes:
        best = None
        for m in by_pitch.get(n.pitch, []):
            d = abs(m.start - n.start)
            if d <= tol and (best is None or d < abs(best.start - n.start)):
                best = m
        if best is not None:
            out.append(Note(n.start, n.end, n.pitch, best.velocity, best.onset_strength))
    return out


# --------------------------------------------------------------------------- more engines
import subprocess
import tempfile

from . import ROOT

TSUMUGI_DIR = ROOT / "vendor" / "tsumugi"
# A checkout keeps Tsumugi in its own venv; the packaged runtime has its deps (torch 2.15 gives
# identical notes and chords on the reference songs), so it runs with the backend's own Python.
TSUMUGI_PY = ROOT / ".venv-tsumugi" / "bin" / "python"
if not TSUMUGI_PY.exists():
    import sys as _sys
    TSUMUGI_PY = Path(_sys.executable)


def _tsumugi_ckpt_dir() -> Path:
    from . import MODELS_DIR
    installed = MODELS_DIR / "tsumugi"
    return installed if installed.exists() else TSUMUGI_DIR / "checkpoints"


TSUMUGI_CKPT_DIR = _tsumugi_ckpt_dir()
TSUMUGI_TYPES = {"tsd": "default", "tsg": "guitar", "tsg15": "guitar_v1_5", "tso": "other_v1_5"}
TSUMUGI_CKPT = {"default": "best_model.pth", "guitar": "best_model_guitar.pth",
                "guitar_v1_5": "best_model_guitar_v1_5.pth", "other_v1_5": "best_model_other_v1_5.pth"}


def _midi_notes(path: Path, vel_default: float = 0.8) -> list[Note]:
    import pretty_midi
    pm = pretty_midi.PrettyMIDI(str(path))
    return [Note(float(n.start), float(n.end), int(n.pitch), n.velocity / 127.0 if n.velocity else vel_default, 1.0)
            for inst in pm.instruments if not inst.is_drum for n in inst.notes if n.pitch >= 0]


def _device() -> str:
    import torch
    return "mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu")


def transkun_available() -> bool:
    try:
        import transkun  # noqa: F401
        return True
    except Exception:
        return False


def transkun(wav: Path) -> list[Note]:
    """Transkun v2 (Yan et al.): neural semi-CRF, decodes each note as a whole interval,
    which gives by far the best note *offsets* of all models tested."""
    import sys
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "tk.mid"
        # `python -m` rather than the `transkun` console script: its shebang is an absolute path,
        # which breaks once the packaged runtime is installed somewhere else
        subprocess.run([sys.executable, "-m", "transkun.transcribe", str(wav), str(out), "--device", "cpu"], check=True,
                       capture_output=True, timeout=1800)
        return _midi_notes(out)


def tsumugi_available() -> bool:
    return (TSUMUGI_PY.exists() and (TSUMUGI_DIR / "instrument_agnostic_amt").exists()
            and (TSUMUGI_CKPT_DIR / TSUMUGI_CKPT["default"]).exists())


def tsumugi(wav: Path, model_type: str) -> list[Note]:
    """Tsumugi (anime-song, MIT): instrument-agnostic semi-CRF extending Transkun,
    with a dedicated guitar model. Runs in its own venv (pinned torch)."""
    with tempfile.TemporaryDirectory() as td:
        out = Path(td) / "ts.mid"
        cmd = [str(TSUMUGI_PY), "-m", "instrument_agnostic_amt.amt.cli.infer", "--type", model_type,
               "--checkpoint", str(TSUMUGI_CKPT_DIR / TSUMUGI_CKPT[model_type]),
               "--audio", str(wav), "--output-midi", str(out), "--device", _device(), "--disable-tqdm"]
        subprocess.run(cmd, check=True, capture_output=True, cwd=TSUMUGI_DIR, timeout=1800)
        return _midi_notes(out)


# Measured on the reference clip (see bench/): which model to trust for each attribute.
# Chosen on BOTH reference songs (YeuEm + hoadanhdanhguitar): MuScriptor onsets drift by ~90 ms
# on some 5 s chunk boundaries, Tsumugi's are the most reliable once chord notes are aligned.
ONSET_PRIORITY = ("tsd", "tsg", "tsg15", "tk", "tso", "ms", "bp")
OFFSET_PRIORITY = ("tk", "tso", "tsg", "tsd", "tsg15", "bp", "ms")   # duration F1: tk .577, tso .564, tsg .449 ...


def align_chords(notes: list[Note], win: float = 0.06, protect: set[int] | None = None) -> list[Note]:
    """Notes of one chord get one onset (median): transcribers spread a strummed chord over a
    few tens of ms, a score writes it as one attack. Rolled-chord members (`protect`) keep
    their stagger (they get an arpeggio sign instead)."""
    protect = protect or set()
    order = sorted(range(len(notes)), key=lambda i: notes[i].start)
    out = list(notes)
    i = 0
    while i < len(order):
        if order[i] in protect:
            i += 1
            continue
        group = [order[i]]
        j = i + 1
        while j < len(order) and notes[order[j]].start - notes[order[i]].start <= win:
            if order[j] not in protect:
                group.append(order[j])
            j += 1
        t = float(np.median([notes[k].start for k in group]))
        for k in group:
            n = notes[k]
            out[k] = Note(t, max(n.end, t + 0.05), n.pitch, n.velocity, n.onset_strength)
        i = j
    return out


def vote(models: dict[str, list[Note]], k: int | None = None, tol: float = 0.12,
         min_pitch: int = 40, max_pitch: int = 88, cut_in: float = 0.06) -> list[Note]:
    """Majority vote across transcribers. Every note of every model is grouped by
    (pitch, onset within `tol`); a group seen by >= k distinct models becomes a note.
    Onset/offset are taken from the models measured most accurate for each.

    YeuEm vs pro transcription: majority of 7 models -> note F1 0.974 (best single model 0.947);
    median over every subset of >= 4 models 0.962 - i.e. robust, not a lucky combination."""
    k = k or (len(models) // 2 + 1)
    pool = sorted([(n, m) for m, ns in models.items() for n in ns
                   if min_pitch <= n.pitch <= max_pitch and n.start >= cut_in],
                  key=lambda x: (x[0].pitch, x[0].start))
    groups: list[dict] = []
    for n, m in pool:
        g = groups[-1] if groups else None
        if g and g["p"] == n.pitch and n.start - g["s0"] <= tol and m not in g["m"]:
            g["m"][m] = n
        else:
            groups.append({"p": n.pitch, "s0": n.start, "m": {m: n}})
    out = []
    for g in groups:
        if len(g["m"]) < k:
            continue
        on = next(g["m"][m] for m in ONSET_PRIORITY if m in g["m"])
        off = next(g["m"][m] for m in OFFSET_PRIORITY if m in g["m"])
        vel = g["m"].get("bp", g["m"].get("tk", on)).velocity
        out.append(Note(on.start, max(off.end, on.start + 0.05), g["p"], vel, len(g["m"]) / len(models)))
    return sorted(out, key=lambda n: (n.start, n.pitch))


def vote_available() -> bool:
    """The vote needs Transkun + Tsumugi; MuScriptor is an optional 7th model."""
    return transkun_available() and tsumugi_available()
