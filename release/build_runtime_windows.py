#!/usr/bin/env python3
"""Build Tabscribe's Windows (x64) engine runtime + its install manifest.

The AI models are the same files on every platform, so Windows reuses the macOS assets release
(same base_url, same model entries); only the engine differs. This script:

  1. unpacks python-build-standalone CPython 3.11 for x86_64-pc-windows-msvc,
  2. pip-installs release/requirements-macos-arm64.lock minus the macOS-only packages
     (PyTorch from PyPI is the CPU build on Windows),
  3. adds an LGPL ffmpeg/ffprobe build (BtbN/FFmpeg-Builds),
  4. smoke-tests it, packs runtime/ into tabscribe-runtime-windows-x64.tar.gz (split if > 1.9 GB),
  5. writes manifest-win32-x64.json (desktop/ copy ships inside the Windows app).

    python release/build_runtime_windows.py --tag assets-2026.11.1

Run it on Windows x64 (the GitHub Actions workflow .github/workflows/windows.yml does).
Then upload release/out/<tag>/tabscribe-runtime-windows-x64.tar.gz* to the <tag> release.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_assets import (BUILD, CACHE, HERE, LOCK, PART_SIZE, REPO_ROOT, dir_size, download, entry,  # noqa: E402
                          log, run)

PBS_URL = ("https://github.com/astral-sh/python-build-standalone/releases/download/20261110/"
           "cpython-3.11.18%2B20261110-x86_64-pc-windows-msvc-install_only_stripped.tar.gz")
PBS_SHA256 = "f31751f4a8483f5ac7cd77ad83f8dfb80d9f2a7245bff1585e27516c777fb46f"
# packages of the macOS lock that don't exist / aren't needed on Windows
# (basic-pitch uses onnxruntime there instead of Core ML; uvicorn runs on asyncio without uvloop)
SKIP = {"coremltools", "uvloop"}
RUNTIME_NAME = "tabscribe-runtime-windows-x64.tar.gz"
FFMPEG_REPO = "BtbN/FFmpeg-Builds"


def win_lock() -> Path:
    out = BUILD / "requirements-windows-x64.txt"
    keep = []
    for line in LOCK.read_text().splitlines():
        name = re.split(r"[=<>@ \[]", line.strip(), maxsplit=1)[0].lower()
        if line.strip() and not line.startswith("#") and name in SKIP:
            continue
        keep.append(line)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(keep) + "\n")
    return out


def py_env(rt: Path, build: bool = False) -> dict:
    """Environment for the runtime's Python. build=True keeps the machine's PATH (pip needs git and
    the MSVC tools to build madmom); the smoke test runs without it, like the app does."""
    sysroot = os.environ.get("SystemRoot", r"C:\Windows")
    dirs = [str(rt), str(rt / "Scripts"), str(rt / "bin"), str(Path(sysroot) / "System32"), sysroot]
    path = os.pathsep.join(dirs + ([os.environ.get("PATH", "")] if build else []))
    env = {**os.environ, "PATH": path, "PIP_DISABLE_PIP_VERSION_CHECK": "1", "PYTHONNOUSERSITE": "1", "PYTHONUTF8": "1"}
    env.pop("VIRTUAL_ENV", None)
    env.pop("PYTHONPATH", None)
    return env


def build_runtime() -> Path:
    rt = BUILD / "runtime-win"
    shutil.rmtree(rt, ignore_errors=True)
    pbs = download(PBS_URL, CACHE / "cpython-3.11-x86_64-pc-windows-msvc.tar.gz", PBS_SHA256)
    stage = BUILD / "pbs-win"
    shutil.rmtree(stage, ignore_errors=True)
    stage.mkdir(parents=True)
    with tarfile.open(pbs) as t:
        t.extractall(stage, filter="data")
    (stage / "python").rename(rt)
    shutil.rmtree(stage)
    py = rt / "python.exe"
    env = py_env(rt, build=True)
    run([py, "-m", "pip", "install", "--no-warn-script-location", "-r", win_lock()], env=env)
    return rt


def latest_ffmpeg() -> tuple[str, str]:
    """(version, download url) of the newest LGPL static win64 release build from BtbN."""
    req = urllib.request.Request(f"https://api.github.com/repos/{FFMPEG_REPO}/releases/latest",
                                 headers={"User-Agent": "tabscribe-release-builder", "Accept": "application/vnd.github+json"})
    if os.environ.get("GITHUB_TOKEN"):
        req.add_header("Authorization", f"Bearer {os.environ['GITHUB_TOKEN']}")
    with urllib.request.urlopen(req) as r:
        rel = json.load(r)
    best = None
    for a in rel["assets"]:
        m = re.match(r"^ffmpeg-n(\d+)\.(\d+)(?:\.(\d+))?-latest-win64-lgpl-\d+\.\d+\.zip$", a["name"])
        if m:
            ver = tuple(int(x or 0) for x in m.groups())
            if best is None or ver > best[0]:
                best = (ver, a["browser_download_url"])
    if not best:
        sys.exit(f"no LGPL win64 ffmpeg build in {FFMPEG_REPO} {rel.get('tag_name')}")
    return ".".join(str(x) for x in best[0]), best[1]


def add_ffmpeg(rt: Path) -> str:
    version, url = latest_ffmpeg()
    z = download(url, CACHE / Path(url).name)
    bin_dir = rt / "bin"
    bin_dir.mkdir(exist_ok=True)
    lic = rt / "share" / "licenses" / "ffmpeg"
    lic.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(z) as zf:
        for n in zf.namelist():
            base = n.rsplit("/", 1)[-1]
            if n.endswith(("/bin/ffmpeg.exe", "/bin/ffprobe.exe")):
                (bin_dir / base).write_bytes(zf.read(n))
            elif base == "LICENSE.txt":
                (lic / "LICENSE.txt").write_bytes(zf.read(n))
    if not (bin_dir / "ffmpeg.exe").exists():
        sys.exit("ffmpeg.exe not found in " + url)
    (lic / "SOURCE.txt").write_text(f"ffmpeg {version}, LGPL build (no GPL/nonfree parts) by {FFMPEG_REPO}: {url}\n"
                                    f"Source code: https://ffmpeg.org/releases/ and https://github.com/{FFMPEG_REPO}\n")
    log(f"ffmpeg {version} from {url}")
    return f"ffmpeg {version} LGPL build from {FFMPEG_REPO} ({url})"


def finish_runtime(rt: Path, version: str) -> str:
    env = py_env(rt)
    py = rt / "python.exe"
    site = rt / "Lib" / "site-packages"
    # madmom ships CC BY-NC-SA model files; Tabscribe only uses its DBN code (BSD). Keep the package importable.
    mm = site / "madmom" / "models"
    for p in mm.iterdir():
        if p.name not in ("__init__.py", "LICENSE", "README.txt"):
            shutil.rmtree(p) if p.is_dir() else p.unlink()
    (mm / "README.txt").write_text("Model files removed from this redistribution (CC BY-NC-SA 4.0); Tabscribe only uses madmom's DBN code.\n")
    # C++ headers are only for building extensions: smaller download, shorter paths (Windows MAX_PATH)
    shutil.rmtree(site / "torch" / "include", ignore_errors=True)
    for junk in rt.rglob("__pycache__"):
        shutil.rmtree(junk, ignore_errors=True)
    ffmpeg_note = add_ffmpeg(rt)
    lic = subprocess.run([py, "-c", (
        "import importlib.metadata as m\n"
        "for d in sorted(m.distributions(), key=lambda d: d.metadata['Name'].lower()):\n"
        "    md = d.metadata; l = md.get('License-Expression') or md.get('License') or ''\n"
        "    l = l.splitlines()[0][:80] if l else ', '.join(c.split(' :: ')[-1] for c in md.get_all('Classifier') or [] if c.startswith('License'))\n"
        "    print(f\"{md['Name']}=={md['Version']}  {l}\")")], capture_output=True, text=True, check=True, env=env).stdout
    (rt / "THIRD_PARTY.txt").write_text("Python packages in this runtime (name==version  licence):\n\n" + lic, encoding="utf-8")
    subprocess.run([str(py), "-m", "compileall", "-q", "-j0", str(site)], env=env, stdout=subprocess.DEVNULL)
    (rt / "tabscribe-runtime.json").write_text(json.dumps({"version": version, "python": "3.11.18", "platform": "win32-x64",
                                                           "built": time.strftime("%Y-%m-%d")}, indent=2))
    smoke_test(rt)
    longest = max((str(p.relative_to(rt)) for p in rt.rglob("*")), key=len)
    log(f"longest path inside runtime/: {len(longest)} chars ({longest})")
    if len(longest) > 170:
        log("WARNING: long paths may hit MAX_PATH under %APPDATA%\\Tabscribe on some machines")
    return ffmpeg_note


def smoke_test(rt: Path):
    env = py_env(rt)
    run([rt / "python.exe", "-c", "import torch, torchaudio, basic_pitch, beat_this, madmom.features.downbeats, transkun, muscriptor, "
         "demucs, dlchordx, einops, uvicorn, fastapi, onnxruntime, transformers, librosa, guitarpro, pretty_midi; "
         "print('imports ok, torch', torch.__version__)"], env=env)
    run([rt / "bin" / "ffmpeg.exe", "-hide_banner", "-version"], env=env, stdout=subprocess.DEVNULL)
    run([rt / "bin" / "ffprobe.exe", "-hide_banner", "-version"], env=env, stdout=subprocess.DEVNULL)


def archive_runtime(rt: Path, out: Path) -> list[dict]:
    full = BUILD / RUNTIME_NAME
    log("compressing runtime (gzip -6)...")
    with tarfile.open(full, "w:gz", compresslevel=6) as t:
        t.add(rt, arcname="runtime")
    for old in out.glob(RUNTIME_NAME + "*"):
        old.unlink()
    files = []
    if full.stat().st_size <= PART_SIZE:
        dst = out / RUNTIME_NAME
        shutil.move(str(full), dst)
        files.append(entry(dst, RUNTIME_NAME))
    else:
        with open(full, "rb") as f:
            i = 0
            while chunk := f.read(PART_SIZE):
                pn = f"{RUNTIME_NAME}.part{i:02d}"
                (out / pn).write_bytes(chunk)
                files.append(entry(out / pn, pn))
                i += 1
        full.unlink()
    return files


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--tag", required=True, help="assets release the runtime is added to, e.g. assets-2026.11.1")
    ap.add_argument("--skip-runtime", action="store_true", help="reuse release/build/runtime-win (no pip install)")
    args = ap.parse_args()
    if sys.platform != "win32":
        sys.exit("build on Windows x64 (the runtime is a Windows build)")

    base_manifest = json.loads((REPO_ROOT / "desktop" / "manifest.json").read_text())
    if base_manifest["version"] != args.tag:
        sys.exit(f"desktop/manifest.json is for {base_manifest['version']}, not {args.tag}: models must come from the same release")
    out = HERE / "out" / args.tag
    out.mkdir(parents=True, exist_ok=True)

    rt = BUILD / "runtime-win"
    if not (args.skip_runtime and rt.exists()):
        rt = build_runtime()
    ffmpeg_note = finish_runtime(rt, args.tag)
    rt_size = dir_size(rt)
    rt_files = archive_runtime(rt, out)

    comps = []
    for c in base_manifest["components"]:
        if c["id"] == "runtime":
            c = {**c, "files": rt_files, "download_size": sum(f["size"] for f in rt_files), "installed_size": rt_size,
                 "description": "Python 3.11, PyTorch (CPU) and the transcription libraries, ffmpeg",
                 "licence": "CPython (PSF-2.0); Python packages under their own licences (BSD/MIT/Apache-2.0, see "
                            f"runtime/THIRD_PARTY.txt); {ffmpeg_note}. madmom's CC BY-NC-SA models are removed."}
        comps.append(c)
    manifest = {**base_manifest, "platform": "win32-x64", "created": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "components": comps}
    text = json.dumps(manifest, indent=2)
    (out / "manifest-win32-x64.json").write_text(text)
    (REPO_ROOT / "desktop" / "manifest-win32-x64.json").write_text(text)
    log(f"done: runtime {sum(f['size'] for f in rt_files) / 1e6:.0f} MB download, {rt_size / 1e6:.0f} MB installed; "
        f"manifest -> desktop/manifest-win32-x64.json")


if __name__ == "__main__":
    main()
