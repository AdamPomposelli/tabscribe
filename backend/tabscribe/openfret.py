"""Open-Fret (Fretting-Transformer, T5) as a learned fingering prior.

Model: huggingface.co/mylonasc/open-fret-tab (MIT), trained on ~188k Guitar Pro tracks.
Code:  vendor/open_fret_pkg (github.com/mylonasc/open-fret @ 20fa647, MIT).

We run its *anchored* decoder (exactly one (string, fret) slot per input attack, distinct
strings within a chord, pitch preserved) and, along the best beam, record the model's
log-probability for every legal position of every note. Those distributions become an
extra emission term in Tabscribe's own beam search (fingering.py), which keeps the
physical constraints (span, ringing strings, hand movement). The raw model alone jumps
positions; the hybrid keeps its idiomatic choices where they are playable.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

from . import MODELS_DIR, ROOT, hf_file

_VENDOR = ROOT / "vendor" / "open_fret_pkg"
REPO, REVISION = "mylonasc/open-fret-tab", "main"
FILES = ["config.json", "generation_config.json", "model.safetensors", "tokenizer.json",
         "tokenizer_config.json", "training_info.json"]
_cache: dict = {}


def available() -> bool:
    try:
        import transformers  # noqa: F401
        return (_VENDOR / "open_fret").exists()
    except Exception:
        return False


def _load():
    if "model" not in _cache:
        if str(_VENDOR) not in sys.path:
            sys.path.insert(0, str(_VENDOR))
        from transformers import AutoTokenizer, T5ForConditionalGeneration
        local = MODELS_DIR / "open_fret"
        for f in FILES:
            hf_file(REPO, f, local, REVISION)
        _cache["tok"] = AutoTokenizer.from_pretrained(local)
        _cache["model"] = T5ForConditionalGeneration.from_pretrained(local).eval()
    return _cache["model"], _cache["tok"]


def note_priors(notes: list[dict], tuning: list[int], capo: int = 0, beams: int = 4,
                tpq_in: int = 960) -> dict[str, dict[tuple[int, int], float]]:
    """notes: dicts with id, start, end (ticks at `tpq_in`), pitch.
    Returns {note_id: {(string 1..6, fret): log_prob}} normalised over legal positions."""
    import torch
    model, tok = _load()
    from open_fret.events import notes_to_tokens
    from open_fret.generation import AnchoredTemplate, chunk_complete_onsets, prepare_encoder, _reorder
    from open_fret.midi_io import add_conditioning
    from open_fret.token_metadata import TokenMetadata

    scale = 480 / tpq_in
    # Durations only matter as context for the model; cap them at the next onset so
    # long acoustic sustains don't make the occupancy constraint unsatisfiable.
    onsets = sorted({n["start"] for n in notes})
    nxt = {t: (onsets[i + 1] if i + 1 < len(onsets) else t + tpq_in) for i, t in enumerate(onsets)}
    src = [{"id": str(n["id"]), "pitch": int(n["pitch"]), "start": int(round(n["start"] * scale)),
            "end": max(int(round(min(n["end"], nxt[n["start"]]) * scale)), int(round(n["start"] * scale)) + 1)}
           for n in notes]
    by_tick_pitch = {(n["start"], n["pitch"]): n["id"] for n in src}
    meta = TokenMetadata.from_tokenizer(tok, 24)
    tokens = notes_to_tokens(src)
    out: dict[str, dict[tuple[int, int], float]] = {}
    offset = 0
    with torch.inference_mode():
        for chunk in chunk_complete_onsets(tokens, 509):
            cond = add_conditioning(chunk, capo, tuning)
            template = AnchoredTemplate(tok, cond, 24)
            enc = prepare_encoder(tok, cond, 512)
            encoder = model.get_encoder()(**enc).last_hidden_state
            start = model.generation_config.decoder_start_token_id or model.config.decoder_start_token_id or 0
            prefixes, scores, cache, dists = [[start]], [0.0], None, [[]]
            for position, slot in enumerate(template.slots):
                count = len(prefixes)
                ids = torch.tensor([[p[-1]] for p in prefixes])
                res = model(encoder_outputs=(encoder.expand(count, -1, -1),),
                            attention_mask=enc["attention_mask"].expand(count, -1),
                            decoder_input_ids=ids, past_key_values=cache, use_cache=True)
                logp = res.logits[:, -1].float().log_softmax(-1)
                choices = []
                for parent, prefix in enumerate(prefixes):
                    allowed = template.allowed(position, prefix)
                    vals = logp[parent, list(allowed)].tolist()
                    dist = None
                    if slot.kind == "note":
                        z = math.log(sum(math.exp(v) for v in vals if math.isfinite(v)) or 1e-30)
                        dist = {meta.note(t): v - z for t, v in zip(allowed, vals) if math.isfinite(v)}
                    for v, t in zip(vals, allowed):
                        if math.isfinite(v):
                            choices.append((scores[parent] + v, parent, t, dist))
                choices.sort(key=lambda x: -x[0])
                sel = choices[:beams]
                new_d = []
                for _, parent, _, dist in sel:
                    new_d.append(dists[parent] + ([(slot.tick, slot.pitch, dist)] if dist is not None else []))
                prefixes = [prefixes[p] + [t] for _, p, t, _ in sel]
                scores = [s for s, _, _, _ in sel]
                dists = new_d
                if position != len(template.slots) - 1:
                    cache = _reorder(res.past_key_values, torch.tensor([p for _, p, _, _ in sel]))
            for tick, pitch, dist in dists[0]:
                nid = by_tick_pitch.get((tick + offset, pitch))
                if nid is not None:
                    agg: dict[tuple[int, int], float] = {}
                    for (st, fr, *_), v in dist.items():  # merge technique variants of one position
                        k = (int(st), int(fr))
                        agg[k] = v if k not in agg else max(agg[k], v) + math.log1p(math.exp(-abs(agg[k] - v)))
                    out[nid] = agg
            offset += sum(int(t[3:]) for t in chunk if t.startswith("TS_"))
    return out
