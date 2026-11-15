"""Tabscribe - local audio to guitar score + tablature."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# The packaged app keeps its code read-only inside Tabscribe.app and points these at
# ~/Library/Application Support/Tabscribe (see desktop/main.js). A checkout uses the repo folders.
MODELS_DIR = Path(os.environ.get("TABSCRIBE_MODELS") or ROOT / "models")
DATA_DIR = Path(os.environ.get("TABSCRIBE_DATA") or ROOT / "data")


def hf_file(repo: str, filename: str, local_dir: Path, revision: str | None = None) -> str:
    """A model file from `local_dir` (installed by the app's setup), else downloaded from
    the Hugging Face Hub into it (development checkout)."""
    p = Path(local_dir) / filename
    if p.exists():
        return str(p)
    from huggingface_hub import hf_hub_download
    return hf_hub_download(repo, filename, revision=revision, local_dir=local_dir)
