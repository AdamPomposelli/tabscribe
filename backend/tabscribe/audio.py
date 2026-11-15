"""Audio decoding through ffmpeg (any format in, float32 PCM out)."""
from __future__ import annotations

import subprocess
from pathlib import Path
import numpy as np
import soundfile as sf


def decode_to_wav(src: Path, dst: Path, sr: int = 44100, channels: int = 2) -> Path:
    cmd = ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-i", str(src),
           "-vn", "-ac", str(channels), "-ar", str(sr), "-c:a", "pcm_f32le", str(dst)]
    subprocess.run(cmd, check=True, timeout=300)
    return dst


def load_mono(path: Path, sr: int | None = None) -> tuple[np.ndarray, int]:
    y, file_sr = sf.read(str(path), dtype="float32", always_2d=True)
    y = y.mean(axis=1)
    if sr and sr != file_sr:
        import librosa
        y = librosa.resample(y, orig_sr=file_sr, target_sr=sr)
        file_sr = sr
    return y, file_sr


def duration(path: Path) -> float:
    info = sf.info(str(path))
    return info.frames / info.samplerate
