# Third-party components in Tabscribe

Tabscribe's own code is © Adam Pomposelli. It bundles or downloads, on first run, the
components below. Each one keeps its own licence; the full list of Python packages with
their licences is in `runtime/THIRD_PARTY.txt` inside the installed engine
(`~/Library/Application Support/Tabscribe/runtime`).

## Shipped inside the app

| Component | Licence | Source |
|---|---|---|
| Electron | MIT | electronjs.org |
| React, lucide-react | MIT / ISC | npm |
| alphaTab | MPL-2.0 | github.com/CoderLine/alphaTab |
| Open-Fret code (`vendor/open_fret_pkg`) | MIT | github.com/mylonasc/open-fret @ 20fa647 |
| Tsumugi code (`vendor/tsumugi`) | MIT | github.com/anime-song/instrument_agnostic_amt |
| Guitar SoundFonts | GPL-3.0 + FreePats exception, CC0, GeneralUser GS licence, Apache-2.0 (AOSP) | texts in `frontend/dist/soundfont/guitars/licenses` |

## Downloaded on first run (from Tabscribe's GitHub release)

| Component | Licence | Upstream |
|---|---|---|
| CPython 3.11 (python-build-standalone) | PSF-2.0 (+ bundled OpenSSL, SQLite, … licences) | github.com/astral-sh/python-build-standalone |
| PyTorch, torchaudio, NumPy, SciPy, librosa, FastAPI, uvicorn, transformers, onnxruntime, … | BSD / MIT / Apache-2.0 | PyPI — see `runtime/THIRD_PARTY.txt` |
| Basic Pitch (code + model) | Apache-2.0 | github.com/spotify/basic-pitch |
| Transkun v2 (code + bundled weights) | MIT | github.com/Yujia-Yan/Transkun |
| Beat This! final0 weights | MIT ("code and published model weights") | github.com/CPJKU/beat_this |
| madmom (DBN code only; its CC BY-NC-SA model files are removed) | BSD-2-Clause | github.com/CPJKU/madmom |
| Tsumugi checkpoints ×4 + beat/chord/key model | MIT (Hugging Face repo licence) | huggingface.co/anime-song/instrument_agnostic_amt |
| Open-Fret weights | MIT (author notes training-data rights are not established) | huggingface.co/mylonasc/open-fret-tab |
| tab-labeler v3 (ONNX) | CC BY 4.0 — © its authors, redistributed unchanged | huggingface.co/cstr/tab-labeler-onnx |
| Demucs htdemucs_6s (optional) | MIT | github.com/facebookresearch/demucs |
| ffmpeg (LGPL-2.1+ build, decoders only used) | LGPL-2.1-or-later — source: ffmpeg.org/releases, build flags in `release/build_assets.py` | ffmpeg.org |

## Optional, fetched from Hugging Face with the user's own account

| Component | Licence |
|---|---|
| MuScriptor medium weights | CC BY-NC 4.0 (non-commercial), gated: each user accepts the licence on huggingface.co/MuScriptor/muscriptor-medium |
