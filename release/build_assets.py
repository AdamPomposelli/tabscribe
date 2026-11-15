#!/usr/bin/env python3
"""Build Tabscribe's downloadable release assets + the install manifest.

Everything heavy the app needs at run time (Python engine, ffmpeg, model weights) is
collected here, checksummed and written to release/out/<tag>/ ready to be uploaded as
GitHub release assets (see publish_assets.sh). The manifest (name, url, size, sha256,
licence of every file) is also copied to desktop/manifest.json so it ships inside the app:
the installer never asks a third-party host what to download.

    python3 release/build_assets.py --repo OWNER/REPO --tag assets-2026.11.1
    python3 release/build_assets.py ... --skip-runtime      # reuse release/build/runtime
    python3 release/build_assets.py ... --host-muscriptor   # re-host the gated MuScriptor weights (read the licence first)

Only the standard library is used; run it with any python3 >= 3.9 on an arm64 Mac.
Build-time downloads (python-build-standalone, ffmpeg source, PyPI wheels, upstream
weights) are pinned and verified; users never touch those hosts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parent
BUILD = HERE / "build"
CACHE = BUILD / "cache"
LOCK = HERE / "requirements-macos-arm64.lock"

PBS_URL = ("https://github.com/astral-sh/python-build-standalone/releases/download/20261110/"
           "cpython-3.11.18%2B20261110-aarch64-apple-darwin-install_only_stripped.tar.gz")
PBS_SHA256 = "3afb0567b2a2b30b3a7341bd143cb4e8a69f3d8e95d4641218eaa45f0fabbd07"
FFMPEG_VERSION = "9.0.2"
FFMPEG_URL = f"https://ffmpeg.org/releases/ffmpeg-{FFMPEG_VERSION}.tar.xz"
FFMPEG_SHA256 = "8c3850283eb25fa026482078a04051e0be17347b09ef81a0849bec15a96e002e"  # ffmpeg-9.0.2.tar.xz
PART_SIZE = 1900 * 1024 * 1024  # GitHub: 2 GiB max per release asset

HF = "https://huggingface.co"
MUSCRIPTOR_REV = "f32236969308476e01fd3aae67357de5feb05a2d"

# (dest relative to the app's data folder, local file in this checkout or None, upstream URL)
CORE_MODELS = [
    ("models/beat_this/config.json", "models/beat_this/config.json", f"{HF}/safe-models/beat-this-final0/resolve/main/config.json"),
    ("models/beat_this/model.safetensors", "models/beat_this/model.safetensors", f"{HF}/safe-models/beat-this-final0/resolve/main/model.safetensors"),
    *[(f"models/open_fret/{f}", f"models/open_fret/{f}", f"{HF}/mylonasc/open-fret-tab/resolve/main/{f}")
      for f in ("config.json", "generation_config.json", "model.safetensors", "tokenizer.json", "tokenizer_config.json", "training_info.json")],
    ("models/tab_labeler/tab-labeler-v3-egset.onnx", "models/tab_labeler/tab-labeler-v3-egset.onnx",
     f"{HF}/cstr/tab-labeler-onnx/resolve/434976baacaf194d99f09c3c784682766bedcf97/tab-labeler-v3-egset.onnx"),
    *[(f"models/tsumugi/{f}", f"vendor/tsumugi/checkpoints/{f}", f"{HF}/anime-song/instrument_agnostic_amt/resolve/main/{f}")
      for f in ("best_model.pth", "best_model_guitar.pth", "best_model_guitar_v1_5.pth", "best_model_other_v1_5.pth", "best_beat_chord_key.pth")],
]
DEMUCS = [("models/torch/hub/checkpoints/5c90dfd2-34c22ccb.th", None,
           "https://dl.fbaipublicfiles.com/demucs/hybrid_transformer/5c90dfd2-34c22ccb.th")]
BS_ROFORMER_SW_REV = "a443a2985534b3bc815ef54a5d446c6a0390f974"
BS_ROFORMER_SW = [("models/bs_roformer_sw/BS-Rofo-SW-Fixed.ckpt", "models/bs_roformer_sw/BS-Rofo-SW-Fixed.ckpt",
                   f"{HF}/enerjazzer/BS-ROFO-SW-Fixed/resolve/{BS_ROFORMER_SW_REV}/BS-Rofo-SW-Fixed.ckpt")]
MUSCRIPTOR = [(f"models/muscriptor/medium/{f}",
               str(Path.home() / f".cache/huggingface/hub/models--MuScriptor--muscriptor-medium/snapshots/{MUSCRIPTOR_REV}/{f}"),
               f"{HF}/MuScriptor/muscriptor-medium/resolve/{MUSCRIPTOR_REV}/{f}")
              for f in ("config.json", "model.safetensors")]

LICENCES = {
    "runtime": "CPython (PSF-2.0); Python packages under their own licences (BSD/MIT/Apache-2.0, see runtime/THIRD_PARTY.txt); "
               "ffmpeg " + FFMPEG_VERSION + " built LGPL-2.1+ (source: " + FFMPEG_URL + "). madmom's CC BY-NC-SA models are removed.",
    "models": "Beat This! final0 (MIT, CPJKU); Open-Fret (MIT, mylonasc); tab-labeler v3 (CC BY 4.0, cstr); Tsumugi (MIT, anime-song)",
    "demucs": "Demucs htdemucs_6s (MIT, Meta AI Research)",
    "bs_roformer_sw": "BS-RoFormer SW 6-stem weights (jarredou, mirrored by enerjazzer): no licence stated "
                      "(Hugging Face card: 'unknown'); not re-hosted, downloaded from Hugging Face. Model code: MIT",
    "muscriptor": "MuScriptor medium weights: CC BY-NC 4.0 (Kyutai x Mirelo), non-commercial, gated on Hugging Face",
}


def log(*a):
    print("[build]", *a, flush=True)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1 << 22):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path, expect_sha: str | None = None, token: str | None = None) -> Path:
    if dest.exists() and (expect_sha is None or sha256(dest) == expect_sha):
        return dest
    dest.parent.mkdir(parents=True, exist_ok=True)
    log("download", url)
    req = urllib.request.Request(url, headers={"User-Agent": "tabscribe-release-builder"})
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    tmp = dest.with_suffix(dest.suffix + ".part")
    with urllib.request.urlopen(req) as r, open(tmp, "wb") as f:
        shutil.copyfileobj(r, f, 1 << 22)
    got = sha256(tmp)
    if expect_sha and got != expect_sha:
        tmp.unlink()
        sys.exit(f"checksum mismatch for {url}: {got} != {expect_sha}")
    tmp.rename(dest)
    return dest


def run(cmd, **kw):
    log("$", " ".join(str(c) for c in cmd))
    subprocess.run([str(c) for c in cmd], check=True, **kw)


# ----------------------------------------------------------------------------- runtime
def build_ffmpeg(prefix: Path):
    """Minimal static LGPL ffmpeg (decode anything -> wav). Only macOS system libraries."""
    src_tar = download(FFMPEG_URL, CACHE / f"ffmpeg-{FFMPEG_VERSION}.tar.xz", FFMPEG_SHA256)
    if FFMPEG_SHA256 is None:
        log(f"ffmpeg tarball sha256 = {sha256(src_tar)} (pin it in FFMPEG_SHA256)")
    out = CACHE / f"ffmpeg-{FFMPEG_VERSION}-bin" / "ffmpeg"
    probe = out.with_name("ffprobe")  # pydub (Transkun's audio loader) shells out to ffprobe
    if not (out.exists() and probe.exists()):
        work = BUILD / "ffmpeg-src"
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)
        run(["tar", "-xf", src_tar, "-C", work])
        src = work / f"ffmpeg-{FFMPEG_VERSION}"
        flags = "-mmacosx-version-min=12.0"
        run(["./configure", "--prefix=" + str(work / "install"), "--cc=clang", "--arch=arm64",
             "--disable-autodetect", "--enable-zlib", "--disable-network", "--disable-doc", "--disable-debug",
             "--disable-ffplay", "--enable-static", "--disable-shared",
             "--disable-gpl", "--disable-nonfree", "--disable-indevs", "--disable-outdevs",
             f"--extra-cflags={flags}", f"--extra-ldflags={flags}"], cwd=src)
        run(["make", f"-j{os.cpu_count() or 8}", "ffmpeg", "ffprobe"], cwd=src)
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src / "ffmpeg", out)
        shutil.copy2(src / "ffprobe", probe)
        shutil.copy2(src / "COPYING.LGPLv2.1", out.parent / "COPYING.LGPLv2.1")
        shutil.rmtree(work, ignore_errors=True)
    (prefix / "bin").mkdir(parents=True, exist_ok=True)
    shutil.copy2(out, prefix / "bin" / "ffmpeg")
    shutil.copy2(probe, prefix / "bin" / "ffprobe")
    lic = prefix / "share" / "licenses" / "ffmpeg"
    lic.mkdir(parents=True, exist_ok=True)
    shutil.copy2(out.parent / "COPYING.LGPLv2.1", lic / "COPYING.LGPLv2.1")
    (lic / "SOURCE.txt").write_text(f"ffmpeg {FFMPEG_VERSION}, built LGPL-only (no --enable-gpl/nonfree) from {FFMPEG_URL}\n"
                                    "by release/build_assets.py (configure flags are in that script).\n")


def build_runtime(version: str) -> Path:
    rt = BUILD / "runtime"
    shutil.rmtree(rt, ignore_errors=True)
    BUILD.mkdir(parents=True, exist_ok=True)
    pbs = download(PBS_URL, CACHE / "cpython-3.11-aarch64-apple-darwin.tar.gz", PBS_SHA256)
    stage = BUILD / "pbs"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir()
    run(["tar", "-xzf", pbs, "-C", stage])
    (stage / "python").rename(rt)
    shutil.rmtree(stage)
    py = rt / "bin" / "python3"
    env = {**os.environ, "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PYTHONNOUSERSITE": "1"}
    env.pop("VIRTUAL_ENV", None)
    run([py, "-m", "pip", "install", "--no-warn-script-location", "-r", LOCK], env=env)
    return finish_runtime(rt, version)


def finish_runtime(rt: Path, version: str) -> Path:
    """Post-install steps (idempotent): licence cleanup, ffmpeg, notices, bytecode, smoke test."""
    py = rt / "bin" / "python3"
    env = {**os.environ, "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PYTHONNOUSERSITE": "1"}
    env.pop("VIRTUAL_ENV", None)
    site = next((rt / "lib").glob("python3.*/site-packages"))
    # madmom ships CC BY-NC-SA model files; Tabscribe only uses its DBN code (BSD). Keep the package importable.
    mm = site / "madmom" / "models"
    for p in mm.iterdir():
        if p.name not in ("__init__.py", "LICENSE", "README.txt"):
            shutil.rmtree(p) if p.is_dir() else p.unlink()
    (mm / "README.txt").write_text("Model files removed from this redistribution (CC BY-NC-SA 4.0); Tabscribe only uses madmom's DBN code.\n")
    for junk in rt.rglob("__pycache__"):
        shutil.rmtree(junk, ignore_errors=True)
    build_ffmpeg(rt)
    # list of installed distributions + licences (for the About box / compliance)
    lic = subprocess.run([py, "-c", (
        "import importlib.metadata as m\n"
        "for d in sorted(m.distributions(), key=lambda d: d.metadata['Name'].lower()):\n"
        "    md = d.metadata; l = md.get('License-Expression') or md.get('License') or ''\n"
        "    l = l.splitlines()[0][:80] if l else ', '.join(c.split(' :: ')[-1] for c in md.get_all('Classifier') or [] if c.startswith('License'))\n"
        "    print(f\"{md['Name']}=={md['Version']}  {l}\")")], capture_output=True, text=True, check=True, env=env).stdout
    (rt / "THIRD_PARTY.txt").write_text("Python packages in this runtime (name==version  licence):\n\n" + lic)
    # precompile for a fast first launch; a few test files use newer syntax (e.g. torch's py312 tests): ignore those
    subprocess.run([str(py), "-m", "compileall", "-q", "-j0", str(site)], env=env, stdout=subprocess.DEVNULL)
    (rt / "tabscribe-runtime.json").write_text(json.dumps({"version": version, "python": "3.11.18", "built": time.strftime("%Y-%m-%d")}, indent=2))
    smoke_test(rt)
    return rt


def smoke_test(rt: Path):
    py = rt / "bin" / "python3"
    env = {"PATH": f"{rt / 'bin'}:/usr/bin:/bin", "HOME": os.environ["HOME"], "PYTHONNOUSERSITE": "1"}
    run([py, "-c", "import torch, torchaudio, basic_pitch, beat_this, madmom.features.downbeats, transkun, muscriptor, demucs, "
                   "dlchordx, einops, uvicorn, fastapi, onnxruntime, transformers, librosa, guitarpro, pretty_midi; print('imports ok')"], env=env)
    run([rt / "bin" / "ffmpeg", "-hide_banner", "-version"], env=env, stdout=subprocess.DEVNULL)
    run([rt / "bin" / "ffprobe", "-hide_banner", "-version"], env=env, stdout=subprocess.DEVNULL)
    # nothing may point outside the runtime (Homebrew, /usr/local, this build folder)
    bad = []
    for p in rt.rglob("*"):
        if p.is_file() and not p.is_symlink() and (p.suffix in (".so", ".dylib") or p.parent.name == "bin"):
            with open(p, "rb") as f:
                if f.read(4) not in (b"\xcf\xfa\xed\xfe", b"\xca\xfe\xba\xbe"):
                    continue
            out = subprocess.run(["otool", "-arch", "arm64", "-L", str(p)], capture_output=True, text=True).stdout
            own = subprocess.run(["otool", "-arch", "arm64", "-D", str(p)], capture_output=True, text=True).stdout.splitlines()[1:]  # install name, not a dependency
            for line in out.splitlines()[1:]:
                lib = line.strip().split(" (")[0]
                if lib in own or line.rstrip().endswith(":"):
                    continue
                if lib.startswith(("/opt/", "/usr/local/", str(BUILD), "/Users/")):
                    bad.append(f"{p.relative_to(rt)} -> {lib}")
    if bad:
        sys.exit("runtime links outside itself:\n  " + "\n  ".join(bad[:20]))
    log("runtime self-contained: OK")


def dir_size(p: Path) -> int:
    return sum(f.stat().st_size for f in p.rglob("*") if f.is_file() and not f.is_symlink())


def archive_runtime(rt: Path, out: Path) -> tuple[list[dict], int]:
    """runtime/ -> tabscribe-runtime-macos-arm64.tar.xz, split in < 2 GiB parts if needed."""
    name = "tabscribe-runtime-macos-arm64.tar.xz"
    full = BUILD / name
    log("compressing runtime (xz -6, all cores)...")
    with open(full, "wb") as f:
        tar = subprocess.Popen(["tar", "-cf", "-", "-C", str(rt.parent), rt.name], stdout=subprocess.PIPE)
        subprocess.run(["xz", "-T0", "-6", "-c"], stdin=tar.stdout, stdout=f, check=True)
        if tar.wait():
            sys.exit("tar failed")
    size = full.stat().st_size
    files = []
    if size <= PART_SIZE:
        dst = out / name
        dst.unlink(missing_ok=True)
        full.rename(dst)
        files.append(entry(dst, name))
    else:
        with open(full, "rb") as f:
            i = 0
            while chunk := f.read(PART_SIZE):
                pn = f"{name}.part{i:02d}"
                (out / pn).write_bytes(chunk)
                files.append(entry(out / pn, pn))
                i += 1
        full.unlink()
    return files, dir_size(rt)


def entry(path: Path, asset: str, dest: str | None = None, url: str | None = None) -> dict:
    e = {"name": asset, "size": path.stat().st_size, "sha256": sha256(path)}
    if dest:
        e["dest"] = dest
    if url:
        e["url"] = url
    return e


def asset_name(dest: str) -> str:
    # flat, unique GitHub asset name derived from the install path
    return dest.removeprefix("models/").replace("/", "--")


def collect(spec, out: Path, host: bool, hf_token: str | None, auth: str | None = None) -> list[dict]:
    files = []
    for dest, local, url in spec:
        src = REPO_ROOT / local if local else None
        if not (src and src.exists()):
            src = download(url, CACHE / "models" / dest, token=hf_token if auth else None)
        if host:
            dst = out / asset_name(dest)
            dst.unlink(missing_ok=True)
            os.link(src, dst) if src.stat().st_dev == out.stat().st_dev else shutil.copy2(src, dst)
            files.append(entry(dst, dst.name, dest))
        else:
            files.append(entry(src, asset_name(dest), dest, url))
    return files


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", required=True, help="GitHub OWNER/REPO that will host the assets")
    ap.add_argument("--tag", required=True, help="release tag for the assets, e.g. assets-2026.11.1")
    ap.add_argument("--skip-runtime", action="store_true", help="reuse release/build/runtime (no pip/ffmpeg rebuild)")
    ap.add_argument("--host-muscriptor", action="store_true",
                    help="re-host the gated CC BY-NC MuScriptor weights on GitHub (default: users fetch them from Hugging Face with their own token)")
    args = ap.parse_args()
    if sys.platform != "darwin" or os.uname().machine != "arm64":
        sys.exit("build on an Apple-silicon Mac (the runtime is macOS arm64)")

    out = HERE / "out" / args.tag
    out.mkdir(parents=True, exist_ok=True)
    hf_token = os.environ.get("HF_TOKEN")
    if not hf_token:
        tok = Path.home() / ".cache" / "huggingface" / "token"
        hf_token = tok.read_text().strip() if tok.exists() else None

    rt = BUILD / "runtime"
    if not args.skip_runtime or not rt.exists():
        rt = build_runtime(args.tag)
    else:
        rt = finish_runtime(rt, args.tag)
    rt_files, rt_size = archive_runtime(rt, out)

    comps = [
        {"id": "runtime", "name": "Transcription engine", "required": True, "kind": "archive", "dest": "runtime",
         "description": "Python 3.11, PyTorch and the transcription libraries, ffmpeg", "installed_size": rt_size,
         "licence": LICENCES["runtime"], "files": rt_files},
        {"id": "models", "name": "AI models", "required": True, "kind": "files",
         "description": "Beat This! beat tracker, Tsumugi x4 transcription + chord/key model, Open-Fret and tab-labeler fingering",
         "licence": LICENCES["models"], "files": collect(CORE_MODELS, out, True, hf_token)},
        {"id": "bs_roformer_sw", "name": "Guitar isolation (BS-RoFormer SW)", "required": False, "default": True,
         "kind": "files",
         "description": "Cleaner guitar stem than Demucs (699 MB, about 1 min per minute of audio); Demucs stays the fallback",
         "licence": LICENCES["bs_roformer_sw"], "licence_url": "https://huggingface.co/enerjazzer/BS-ROFO-SW-Fixed",
         "files": collect(BS_ROFORMER_SW, out, False, hf_token)},
        {"id": "demucs", "name": "Guitar isolation, light (Demucs)", "required": False, "default": False, "kind": "files",
         "description": "Separates the guitar from a full band mix before transcribing (optional, per project)",
         "licence": LICENCES["demucs"], "files": collect(DEMUCS, out, True, hf_token)},
    ]
    ms = {"id": "muscriptor", "name": "MuScriptor (extra vote model)", "required": False, "default": False, "kind": "files",
          "description": "Kyutai x Mirelo transformer: adds a 7th model to the vote and the MuScriptor / Ensemble engines. "
                         "Non-commercial licence.", "licence": LICENCES["muscriptor"],
          "licence_url": "https://huggingface.co/MuScriptor/muscriptor-medium"}
    if args.host_muscriptor:
        ms["files"] = collect(MUSCRIPTOR, out, True, hf_token, auth="huggingface")
    else:
        if not hf_token:
            sys.exit("MuScriptor's size/sha256 come from Hugging Face: set HF_TOKEN (licence accepted) or run `hf auth login`")
        ms["auth"] = "huggingface"
        ms["files"] = collect(MUSCRIPTOR, out, False, hf_token, auth="huggingface")
    comps.append(ms)
    for c in comps:
        c["download_size"] = sum(f["size"] for f in c["files"])
        c.setdefault("installed_size", c["download_size"])

    manifest = {"schema": 1, "app": "Tabscribe", "version": args.tag, "platform": "darwin-arm64",
                "base_url": f"https://github.com/{args.repo}/releases/download/{args.tag}/",
                "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "components": comps}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    shutil.copy2(out / "manifest.json", REPO_ROOT / "desktop" / "manifest.json")
    total = sum(c["download_size"] for c in comps)
    log(f"done: {out}  ({total / 1e9:.2f} GB to download if every component is picked)")
    for c in comps:
        log(f"  {c['id']:11} download {c['download_size'] / 1e6:8.1f} MB   installed {c['installed_size'] / 1e6:8.1f} MB"
            f"   {'hosted on GitHub' if all('url' not in f for f in c['files']) else 'from upstream' + (' (user token)' if c.get('auth') else '')}")


if __name__ == "__main__":
    main()
