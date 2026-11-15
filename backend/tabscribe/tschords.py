"""Tsumugi beat/chord/key model (anime-song, MIT) run on our transcription.

Input is a MIDI of the transcribed notes (not audio). Output: chord segments with
bass, key and meter. On the two reference songs it names chords far closer to a
professional transcription than template matching (hoa: 79 % roots vs 61 %).
"""
from __future__ import annotations

import json
import re
import subprocess
import tempfile
from pathlib import Path

from . import transcribe
from .chords import key_scale_names, spell

CKPT = "best_beat_chord_key.pth"
URL = "https://huggingface.co/anime-song/instrument_agnostic_amt/resolve/main/" + CKPT
PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def available() -> bool:
    return transcribe.tsumugi_available()


def _ensure_ckpt() -> Path:
    path = transcribe.TSUMUGI_CKPT_DIR / CKPT
    if not path.exists():
        from urllib.request import urlretrieve
        path.parent.mkdir(parents=True, exist_ok=True)
        urlretrieve(URL, path)
    return path


def run(notes) -> dict:
    """notes: objects with start, end, pitch (seconds)."""
    import pretty_midi
    with tempfile.TemporaryDirectory() as td:
        m = pretty_midi.PrettyMIDI()
        inst = pretty_midi.Instrument(24)
        inst.notes = [pretty_midi.Note(90, int(n.pitch), float(n.start), float(max(n.end, n.start + 0.05))) for n in notes]
        m.instruments.append(inst)
        mid, out = Path(td) / "in.mid", Path(td) / "out.json"
        m.write(str(mid))
        subprocess.run([str(transcribe.TSUMUGI_PY), "-m", "instrument_agnostic_amt.beat_chord.cli.infer",
                        "--checkpoint", str(_ensure_ckpt()), "--midi_path", str(mid), "--output_path", str(out),
                        "--disable_beat_mapped_midi", "--device", transcribe._device()],
                       cwd=transcribe.TSUMUGI_DIR, check=True, capture_output=True, timeout=600)
        d = json.loads(out.read_text())
    return {"chords": [{"start": c["start"], "end": c["end"], "label": c["chord"]} for c in d.get("chords", [])],
            "meters": [m.get("meter") for m in d.get("meters", [])],
            "keys": [k.get("key") for k in d.get("keys", [])]}


QUALITY_MAP = {"": "", "maj": "", "min": "m", "M7": "maj7", "maj7": "maj7", "7": "7", "m7": "m7", "min7": "m7",
               "sus4": "sus4", "sus2": "sus2", "dim": "dim", "m7b5": "m7b5", "hdim7": "m7b5", "aug": "aug",
               "7(9)": "9", "m7(9)": "m9", "m7(11)": "m11", "M7(9)": "maj9", "add9": "add9", "madd9": "madd9",
               "69": "6/9", "6": "6", "m6": "m6", "7(b9)": "7b9", "7(13)": "13", "7sus4": "7sus4", "dim7": "dim7"}


def _pc(name: str) -> int:
    m = re.match(r"([A-G])([#b]*)", name)
    return (PC[m.group(1)] + m.group(2).count("#") - m.group(2).count("b")) % 12


def label_to_name(label: str, key: dict, transpose: int = 0) -> str | None:
    """'C#:7(b9)/F' -> key-aware spelled symbol, optionally transposed."""
    if not label or label in ("N", "X"):
        return None
    main, _, bass = label.partition("/")
    root, _, q = main.partition(":")
    q = QUALITY_MAP.get(q, q)
    names = key_scale_names(key["tonic"], key["mode"], key["accidentals"])
    out = spell((_pc(root) + transpose) % 12, names, key["accidentals"]) + q
    if bass:
        out += "/" + spell((_pc(bass) + transpose) % 12, names, key["accidentals"])
    return out


def meter(pred: dict) -> int:
    nums = [int(m.split("/")[0]) for m in pred.get("meters", []) if m and m.split("/")[0].isdigit()]
    if not nums:
        return 0
    best = max(set(nums), key=nums.count)
    return best if best in (2, 3, 4) else (3 if best in (6, 9) else 4)
