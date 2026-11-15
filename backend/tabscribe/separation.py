"""Guitar isolation before transcription (opt-in, for songs with vocals or a band).

Primary: BS-RoFormer SW, a 6-stem BS-RoFormer (bass, drums, other, vocals, guitar, piano).
It won the blind listening test against Demucs htdemucs_6s, MelBand-RoFormer guitar and their
ensembles (guitar-extract-research/REPORT.md). Inference copies python-audio-separator 0.48's
RoFormer path (9.3 s Hamming-windowed chunks, 2x overlap, fp32), so the stem matches what was heard.
Fallback: Demucs htdemucs_6s, used when the SW weights are missing or SW fails.

Only used for mixes: on solo guitar recordings separation removes attack transients and hurts
transcription, so it is opt-in.
"""
from __future__ import annotations

import os
from pathlib import Path
import numpy as np
import soundfile as sf

from . import MODELS_DIR, hf_file

# --- BS-RoFormer SW ---------------------------------------------------------------------------
SW_REPO = "enerjazzer/BS-ROFO-SW-Fixed"   # mirror of jarredou's checkpoint (original account deleted)
SW_REV = "a443a2985534b3bc815ef54a5d446c6a0390f974"
SW_FILE = "BS-Rofo-SW-Fixed.ckpt"          # 699 MB, sha256 24e7d35e...916e
SW_DIR = MODELS_DIR / "bs_roformer_sw"
SW_STEMS = ["bass", "drums", "other", "vocals", "guitar", "piano"]
SW_CONFIG = dict(  # model section of BS-Rofo-SW-Fixed.yaml, as passed by python-audio-separator's RoformerLoader
    dim=256, depth=12, stereo=True, num_stems=6, time_transformer_depth=1, freq_transformer_depth=1,
    linear_transformer_depth=0,
    freqs_per_bands=(2,) * 24 + (4,) * 12 + (12,) * 8 + (24,) * 8 + (48,) * 8 + (128, 129),
    dim_head=64, heads=8, attn_dropout=0.1, ff_dropout=0.1, flash_attn=True, mlp_expansion_factor=4,
    sage_attention=False, zero_dc=True, use_torch_checkpoint=False, skip_connection=False,
    stft_n_fft=2048, stft_hop_length=512, stft_win_length=2048,
)
SW_SR = 44100
SW_DIM_T = 801      # inference.dim_t -> chunk = 512 * 800 = 409600 samples (9.3 s)
SW_OVERLAP = 2      # inference.num_overlap

# --- Demucs htdemucs_6s (fallback) -------------------------------------------------------------
WEIGHTS = "5c90dfd2-34c22ccb.th"  # htdemucs_6s (demucs/remote/files.txt)

_sw_model = None
_demucs_model = None


def _offline() -> bool:
    return os.environ.get("HF_HUB_OFFLINE") == "1"


def sw_available() -> bool:
    """SW weights installed, or (development checkout, online) downloadable on first use."""
    try:
        import einops  # noqa: F401
    except Exception:
        return False
    return (SW_DIR / SW_FILE).exists() or not _offline()


def demucs_available() -> bool:
    """Demucs importable and, in the packaged app (offline), its weights installed."""
    try:
        import demucs  # noqa: F401
    except Exception:
        return False
    if not _offline():
        return True  # checkout: downloaded on first use
    home = Path(os.environ.get("TORCH_HOME") or Path.home() / ".cache" / "torch")
    return (home / "hub" / "checkpoints" / WEIGHTS).exists()


def available() -> bool:
    return sw_available() or demucs_available()


def engine_label() -> str:
    if sw_available():
        return "BS-RoFormer SW"
    return "Demucs htdemucs_6s" if demucs_available() else "unavailable"


def _device():
    import torch
    return "mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu")


def _read_stereo(wav_path: Path, sr_target: int) -> np.ndarray:
    """(channels=2, samples) float32 at sr_target."""
    y, sr = sf.read(str(wav_path), dtype="float32", always_2d=True)
    y = y.T
    if sr != sr_target:
        import librosa
        y = librosa.resample(y, orig_sr=sr, target_sr=sr_target)
    if y.shape[0] == 1:
        y = np.repeat(y, 2, axis=0)
    return np.ascontiguousarray(y[:2])


def _load_sw():
    global _sw_model
    if _sw_model is None:
        import torch
        from .roformer.bs_roformer import BSRoformer
        path = hf_file(SW_REPO, SW_FILE, SW_DIR, SW_REV)
        model = BSRoformer(**SW_CONFIG)
        model.load_state_dict(torch.load(path, map_location="cpu", weights_only=True))
        _sw_model = model.to(_device()).eval()
    return _sw_model


def _chunk_starts(n: int, chunk: int, step: int) -> list[int]:
    starts = []
    for off in range(0, n, step):
        if off + chunk >= n:
            tail = max(n - chunk, 0)
            if not starts or starts[-1] != tail:
                starts.append(tail)
            break
        starts.append(off)
    return starts


def _isolate_sw(wav_path: Path, out_path: Path, progress=None) -> Path:
    import torch
    from scipy.signal import windows
    model = _load_sw()
    dev = next(model.parameters()).device
    mix = _read_stereo(wav_path, SW_SR)
    peak = float(np.abs(mix).max())
    gain = 0.9 / peak if peak > 0.9 else 1.0  # python-audio-separator normalises the mix to a 0.9 peak
    x = torch.from_numpy(mix * gain)
    chunk = SW_CONFIG["stft_hop_length"] * (SW_DIM_T - 1)
    step = chunk // SW_OVERLAP
    window = torch.tensor(windows.hamming(chunk), dtype=torch.float32)
    gi = SW_STEMS.index("guitar")
    result = torch.zeros(x.shape)
    counter = torch.zeros(x.shape[-1])
    starts = _chunk_starts(x.shape[-1], chunk, step)
    with torch.no_grad():
        for i, s in enumerate(starts):
            part = x[:, s:s + chunk]
            y = model(part.to(dev)[None])[0][gi].float().cpu()  # (2, len)
            n = min(part.shape[-1], y.shape[-1], chunk)
            result[:, s:s + n] += y[:, :n] * window[:n]
            counter[s:s + n] += window[:n]
            if progress:
                progress((i + 1) / len(starts))
    guitar = (result / counter.clamp(min=1e-10)) / gain
    sf.write(str(out_path), guitar.numpy().T, SW_SR, subtype="FLOAT")
    return out_path


def _isolate_demucs(wav_path: Path, out_path: Path) -> Path:
    global _demucs_model
    import torch
    from demucs.pretrained import get_model
    from demucs.apply import apply_model

    if _demucs_model is None:
        _demucs_model = get_model("htdemucs_6s")
        _demucs_model.eval()
    sr = _demucs_model.samplerate
    wav = torch.from_numpy(_read_stereo(wav_path, sr))
    ref = wav.mean(0)
    wav = (wav - ref.mean()) / (ref.std() + 1e-8)
    with torch.no_grad():
        sources = apply_model(_demucs_model, wav[None], device=_device(), shifts=1, split=True, overlap=0.25, progress=False)[0]
    sources = sources * (ref.std() + 1e-8) + ref.mean()
    guitar = sources[_demucs_model.sources.index("guitar")].cpu().numpy().T
    sf.write(str(out_path), guitar, sr, subtype="FLOAT")
    return out_path


def isolate_guitar(wav_path: Path, out_path: Path, progress=None) -> Path:
    """Write the guitar stem of `wav_path` to `out_path` (BS-RoFormer SW, else Demucs)."""
    if sw_available():
        try:
            return _isolate_sw(wav_path, out_path, progress)
        except Exception as e:
            if not demucs_available():
                raise
            print(f"[tabscribe] BS-RoFormer SW failed ({e}); falling back to Demucs htdemucs_6s")
    return _isolate_demucs(wav_path, out_path)
