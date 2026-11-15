"""Local FastAPI backend: projects, transcription jobs, files."""
from __future__ import annotations

import json
import queue
import shutil
import subprocess
import threading
import time
import traceback
import uuid
from dataclasses import asdict, fields
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import DATA_DIR, ROOT, pipeline, transcribe

PROJECTS = DATA_DIR / "projects"
PROJECTS.mkdir(parents=True, exist_ok=True)
MAX_UPLOAD = 200 * 1024 * 1024
AUDIO_EXT = {".mp3", ".wav", ".flac", ".m4a", ".aac", ".ogg", ".opus", ".webm", ".mp4", ".aiff", ".aif"}

app = FastAPI(title="Tabscribe")
app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                   allow_methods=["*"], allow_headers=["*"])

_jobs: "queue.Queue[tuple[str, dict, bool]]" = queue.Queue()
_status: dict[str, dict] = {}
_lock = threading.Lock()


def _pdir(pid: str) -> Path:
    if not pid.replace("-", "").isalnum():
        raise HTTPException(400, "bad id")
    d = PROJECTS / pid
    if not d.exists():
        raise HTTPException(404, "project not found")
    return d


def _meta(pid: str) -> dict:
    return json.loads((_pdir(pid) / "meta.json").read_text())


def _save_meta(pid: str, meta: dict):
    (PROJECTS / pid / "meta.json").write_text(json.dumps(meta, indent=2))


def _opts(meta: dict) -> pipeline.Options:
    names = {f.name for f in fields(pipeline.Options)}
    return pipeline.Options(**{k: v for k, v in meta.get("options", {}).items() if k in names and k not in ("title", "artist")},
                            title=meta.get("title", ""), artist=meta.get("artist", ""))


def _worker():
    while True:
        pid, _, full = _jobs.get()
        d = PROJECTS / pid

        started = time.time()
        stages: list[str] = []

        def progress(stage, frac, msg=""):
            with _lock:
                if stage not in stages:
                    stages.append(stage)
                _status[pid] = {"state": "running", "stage": stage, "progress": round(frac, 3), "message": msg,
                                "started": started, "stages": list(stages)}
        try:
            meta = json.loads((d / "meta.json").read_text())
            opts = _opts(meta)
            meta["state"] = "running"
            _save_meta(pid, meta)
            progress("queued", 0.01, "Starting")
            tr = pipeline.transcribe_audio(d / meta["source"], d, opts, progress)
            pipeline.arrange(tr, d, opts, progress)
            meta["state"] = "done"
            meta["engine"] = tr["engine"]
            meta["updated"] = time.time()
            _save_meta(pid, meta)
            with _lock:
                _status[pid] = {"state": "done", "progress": 1.0, "stage": "done", "message": "Done",
                                "started": started, "stages": stages if "done" in stages else stages + ["done"]}
        except Exception as e:  # report, never crash the worker
            traceback.print_exc()
            meta = json.loads((d / "meta.json").read_text())
            meta["state"], meta["error"] = "error", str(e)
            _save_meta(pid, meta)
            with _lock:
                _status[pid] = {"state": "error", "progress": 0, "stage": "error", "message": str(e)}
        finally:
            _jobs.task_done()


threading.Thread(target=_worker, daemon=True).start()


def _resume_interrupted():
    """Jobs that were queued/running when the server stopped are queued again."""
    for m in PROJECTS.glob("*/meta.json"):
        try:
            meta = json.loads(m.read_text())
        except Exception:
            continue
        if meta.get("state") in ("queued", "running"):
            _status[meta["id"]] = {"state": "queued", "progress": 0, "stage": "queued", "message": "Queued"}
            _jobs.put((meta["id"], {}, False))


_resume_interrupted()


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/engines")
def engines():
    from . import separation
    sep_ok = separation.available()
    ms_ok = transcribe.muscriptor_available()
    return {
        "vote": {"available": transcribe.vote_available(), "label": f"Vote ({7 if ms_ok else 6} models)"},
        "basic-pitch": {"available": True, "label": "Basic Pitch (Spotify)"},
        "ensemble": {"available": ms_ok, "label": "Ensemble (MuScriptor + Basic Pitch)"},
        "muscriptor": {"available": ms_ok, "label": "MuScriptor (Kyutai)",
                       "help": "Optional component: install it from Settings → Components (needs a Hugging Face account that "
                               "accepted the licence on huggingface.co/MuScriptor/muscriptor-medium)"},
        "separation": {"available": sep_ok, "label": separation.engine_label(),
                       "fallback": "Demucs htdemucs_6s" if separation.demucs_available() else None},
        "tunings": list(pipeline.TUNINGS),
    }


@app.get("/api/projects")
def list_projects(q: str = ""):
    out = []
    for d in PROJECTS.iterdir():
        m = d / "meta.json"
        if m.exists():
            meta = json.loads(m.read_text())
            if q and q.lower() not in meta.get("title", "").lower():
                continue
            out.append({k: meta.get(k) for k in ("id", "title", "artist", "state", "created", "updated", "duration")})
    return sorted(out, key=lambda m: m.get("updated") or m.get("created") or 0, reverse=True)


@app.post("/api/projects")
async def create_project(file: UploadFile = File(...), title: str = Form(""), separate: bool = Form(False),
                         engine: str = Form("auto"), start: float = Form(0.0), end: float = Form(0.0),
                         beats_per_bar: int = Form(0), tuning: str = Form("standard"), capo: int = Form(0),
                         key: str = Form(""), difficulty: str = Form("original")):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in AUDIO_EXT:
        raise HTTPException(415, f"Unsupported file type {ext}")
    pid = uuid.uuid4().hex[:12]
    d = PROJECTS / pid
    d.mkdir(parents=True)
    src = d / f"source{ext}"
    size = 0
    with src.open("wb") as f:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > MAX_UPLOAD:
                shutil.rmtree(d)
                raise HTTPException(413, "File too large")
            f.write(chunk)
    if beats_per_bar not in (0, 2, 3, 4) or not 0 <= capo <= 12 or tuning not in pipeline.TUNINGS \
            or difficulty not in ("original", "intermediate", "beginner") or (key and pipeline.parse_key(key) is None):
        shutil.rmtree(d)
        raise HTTPException(400, "Invalid options")
    trim = None
    if start > 0 or end > 0:  # keep only the chosen range: everything downstream sees the trimmed audio
        if end and end <= start:
            shutil.rmtree(d)
            raise HTTPException(400, "Trim end must be after start")
        cut = d / "source_trim.flac"
        cmd = ["ffmpeg", "-nostdin", "-loglevel", "error", "-y", "-ss", f"{max(start, 0):.3f}", "-i", str(src)]
        if end > 0:
            cmd += ["-t", f"{end - max(start, 0):.3f}"]
        cmd += ["-vn", "-c:a", "flac", str(cut)]
        try:
            subprocess.run(cmd, check=True, timeout=300)
        except (subprocess.SubprocessError, OSError) as e:
            shutil.rmtree(d)
            raise HTTPException(400, f"Could not trim this audio: {e}")
        src.unlink()
        src, trim = cut, [round(max(start, 0), 3), round(end, 3) if end > 0 else None]
    meta = {"id": pid, "title": title or Path(file.filename).stem, "artist": "", "source": src.name,
            "filename": file.filename, "trim": trim, "created": time.time(), "updated": time.time(), "state": "queued",
            "options": asdict(pipeline.Options(engine=engine, separate=separate, beats_per_bar=beats_per_bar,
                                               tuning=tuning, capo=capo, key=key, difficulty=difficulty))}
    _save_meta(pid, meta)
    _status[pid] = {"state": "queued", "progress": 0, "stage": "queued", "message": "Queued"}
    _jobs.put((pid, {}, True))
    return meta


@app.get("/api/projects/{pid}")
def get_project(pid: str):
    meta = _meta(pid)
    res = _pdir(pid) / "result.json"
    return {"meta": meta, "status": _status.get(pid, {"state": meta.get("state")}),
            "result": json.loads(res.read_text()) if res.exists() and meta.get("state") == "done" else None}


PREFS = DATA_DIR / "prefs.json"
PREF_KEYS = {"guitar_sound"}


def _prefs() -> dict:
    try:
        return json.loads(PREFS.read_text())
    except (OSError, ValueError):
        return {}


@app.get("/api/prefs")
def get_prefs():
    """App preferences that must survive restarts (the desktop app's origin isn't stable)."""
    return _prefs()


@app.put("/api/prefs")
def put_prefs(body: dict):
    prefs = _prefs()
    for k, v in body.items():
        if k in PREF_KEYS and isinstance(v, str) and len(v) <= 100:
            prefs[k] = v
    PREFS.write_text(json.dumps(prefs, indent=2))
    return prefs


class RenameBody(BaseModel):
    title: str | None = None
    artist: str | None = None


@app.patch("/api/projects/{pid}")
def rename_project(pid: str, body: RenameBody):
    """Rename without re-arranging (instant)."""
    meta = _meta(pid)
    res = _pdir(pid) / "result.json"
    result = json.loads(res.read_text()) if res.exists() else None
    for k in ("title", "artist"):
        v = getattr(body, k)
        if v is not None:
            v = v.strip()[:200]
            if k == "title" and not v:
                raise HTTPException(400, "title cannot be empty")
            meta[k] = v
            meta.setdefault("options", {})[k] = v
            if result is not None:
                result[k] = v
    _save_meta(pid, meta)
    if result is not None:
        res.write_text(json.dumps(result))
    return {"ok": True, "meta": meta}


@app.get("/api/projects/{pid}/status")
def status(pid: str):
    meta = _meta(pid)
    return _status.get(pid, {"state": meta.get("state"), "progress": 1.0 if meta.get("state") == "done" else 0})


class ArrangeBody(BaseModel):
    difficulty: str | None = None
    transpose: int | None = None
    capo: int | None = None
    tuning: str | None = None
    engine: str | None = None
    separate: bool | None = None
    muscriptor_size: str | None = None
    beats_per_bar: int | None = None
    title: str | None = None
    artist: str | None = None


@app.post("/api/projects/{pid}/arrange")
def rearrange(pid: str, body: ArrangeBody):
    meta = _meta(pid)
    opts = meta.setdefault("options", {})
    for k in ("title", "artist"):
        if getattr(body, k) is not None:
            meta[k] = getattr(body, k)
    for k, v in body.model_dump(exclude_none=True).items():
        if k not in ("title", "artist"):
            opts[k] = v
    if body.transpose is not None and not -12 <= body.transpose <= 12:
        raise HTTPException(400, "transpose out of range")
    if body.beats_per_bar is not None and body.beats_per_bar not in (0, 2, 3, 4):
        raise HTTPException(400, "beats_per_bar must be 0 (auto), 2, 3 or 4")
    if body.capo is not None and not 0 <= body.capo <= 12:
        raise HTTPException(400, "capo out of range")
    meta["state"] = "queued"
    meta["updated"] = time.time()
    meta.pop("error", None)
    _save_meta(pid, meta)
    _status[pid] = {"state": "queued", "progress": 0, "stage": "queued", "message": "Queued"}
    _jobs.put((pid, {}, False))  # cached notes/beats make non-engine changes near-instant
    return {"ok": True}


@app.delete("/api/projects/{pid}")
def delete_project(pid: str):
    shutil.rmtree(_pdir(pid))
    _status.pop(pid, None)
    return {"ok": True}


FILES = {"score.gp5": "application/octet-stream", "score.mid": "audio/midi", "performance.mid": "audio/midi",
         "result.json": "application/json", "audio.wav": "audio/wav", "guitar_stem.wav": "audio/wav"}


@app.get("/api/projects/{pid}/files/{name}")
def get_file(pid: str, name: str):
    d = _pdir(pid)
    meta = _meta(pid)
    if name == "source":
        return FileResponse(d / meta["source"], filename=meta.get("filename"))
    if name not in FILES or not (d / name).exists():
        raise HTTPException(404, "file not found")
    base = "".join(c for c in meta.get("title", "score") if c.isalnum() or c in " -_").strip() or "score"
    download = {"score.gp5": f"{base}.gp5", "score.mid": f"{base}.mid", "performance.mid": f"{base} (performance).mid"}
    return FileResponse(d / name, media_type=FILES[name], filename=download.get(name))


# serve the built web UI (frontend/dist) when present
_dist = ROOT / "frontend" / "dist"
if _dist.exists():
    app.mount("/", StaticFiles(directory=_dist, html=True), name="ui")
