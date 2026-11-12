"""HindiDub REST API."""
from __future__ import annotations

import logging
import shutil
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

from fastapi import Depends, FastAPI, Form, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .config import settings
from .jobs import JobStore, Worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

store = JobStore(settings)
worker = Worker(store)


def _code_version() -> str:
    """Short git commit of the running code (shows on /health)."""
    import subprocess

    try:
        return subprocess.run(["git", "rev-parse", "--short=7", "HEAD"], capture_output=True,
                              text=True, timeout=5, cwd=Path(__file__).parent).stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001
        return "unknown"


VERSION = _code_version()
STARTED = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())


@asynccontextmanager
async def lifespan(_app: FastAPI):
    worker.start()
    yield


app = FastAPI(title="HindiDub", version="1.0.0", lifespan=lifespan)

CHUNK_LIMIT = 64 * 1024 * 1024
_last_activity = time.time()


@app.middleware("http")
async def track_activity(request: Request, call_next):
    # /health is polled by the Kaggle keep-alive loop, so it must not count as activity.
    global _last_activity
    if request.url.path not in ("/", "/health"):
        _last_activity = time.time()
    return await call_next(request)


def auth(x_api_key: str = Header(default="")) -> None:
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(401, "Invalid or missing X-API-Key")


class NewUpload(BaseModel):
    filename: str
    size: int
    speakers: int = Field(0, ge=0, le=20)  # exact number of characters, 0 = auto
    voice_mode: Literal["studio", "clone"] = "studio"


@app.get("/")
@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "hindidub", "version": VERSION, "started": STARTED,
            "device": settings.resolved_device(),
            "busy": worker.current is not None, "queued": worker.q.qsize(),
            "idle_seconds": int(time.time() - _last_activity)}


# ---- resumable chunked upload (used by the Android app) --------------------
@app.post("/uploads", dependencies=[Depends(auth)])
def create_upload(body: NewUpload) -> dict:
    if body.size <= 0:
        raise HTTPException(400, "Empty file")
    if body.size > settings.max_upload_bytes:
        raise HTTPException(413, f"File too large (max {settings.max_upload_bytes // 2**20} MB)")
    options = {"speakers": body.speakers, "voice_mode": body.voice_mode}
    return {"upload_id": store.new_upload(body.filename, body.size, options), "received": 0}


@app.get("/uploads/{uid}", dependencies=[Depends(auth)])
def upload_status(uid: str) -> dict:
    up = store.get_upload(uid)
    if not up:
        raise HTTPException(404, "Unknown upload")
    return {"upload_id": uid, "received": up["received"], "size": up["size"]}


@app.put("/uploads/{uid}", dependencies=[Depends(auth)])
async def upload_chunk(uid: str, request: Request, offset: int = Query(...)) -> dict:
    up = store.get_upload(uid)
    if not up:
        raise HTTPException(404, "Unknown upload")
    if offset != up["received"]:
        # Client is out of sync (e.g. after a network drop): tell it where to resume.
        raise HTTPException(409, {"received": up["received"]})
    written = 0
    with open(store.upload_path(uid), "ab") as f:
        async for part in request.stream():
            written += len(part)
            if written > CHUNK_LIMIT or up["received"] + written > up["size"]:
                f.truncate(up["received"])
                raise HTTPException(413, "Chunk too large")
            f.write(part)
    return {"upload_id": uid, "received": up["received"] + written}


@app.post("/uploads/{uid}/complete", dependencies=[Depends(auth)])
def complete_upload(uid: str) -> dict:
    up = store.get_upload(uid)
    if not up:
        raise HTTPException(404, "Unknown upload")
    if up["received"] != up["size"]:
        raise HTTPException(409, {"received": up["received"], "size": up["size"]})
    jid = store.finish_upload(uid)
    worker.submit(jid)
    return {"job_id": jid}


# ---- simple one-shot upload (curl / scripts) -------------------------------
@app.post("/jobs", dependencies=[Depends(auth)])
def create_job(file: UploadFile, speakers: int = Form(0, ge=0, le=20),
               voice_mode: Literal["studio", "clone"] = Form("studio")) -> dict:
    jid = store.create_job(file.filename or "video.mp4")
    store.set_job_options(jid, {"speakers": speakers, "voice_mode": voice_mode})
    from .jobs import _ext

    dst = store.job_dir(jid) / ("input" + _ext(file.filename or ""))
    with open(dst, "wb") as f:
        shutil.copyfileobj(file.file, f, 8 * 2**20)
    worker.submit(jid)
    return {"job_id": jid}


@app.get("/jobs/{jid}", dependencies=[Depends(auth)])
def job_status(jid: str) -> dict:
    job = store.get(jid)
    if not job:
        raise HTTPException(404, "Unknown job")
    job["queue_position"] = worker.queue_position(jid)
    return job


@app.get("/jobs/{jid}/result", dependencies=[Depends(auth)])
def job_result(jid: str) -> FileResponse:
    path = store.result_path(jid)
    if not path.exists():
        raise HTTPException(404, "Result not ready")
    return FileResponse(path, media_type="video/mp4", filename=f"hindi_dub_{jid}.mp4")


@app.get("/jobs/{jid}/subtitles", dependencies=[Depends(auth)])
def job_subtitles(jid: str) -> FileResponse:
    path = store.result_path(jid).with_suffix(".hi.srt")
    if not path.exists():
        raise HTTPException(404, "Subtitles not ready")
    return FileResponse(path, media_type="application/x-subrip", filename=f"hindi_{jid}.srt")


@app.get("/jobs/{jid}/error", dependencies=[Depends(auth)])
def job_error(jid: str) -> dict:
    """Full traceback of a failed job, for debugging."""
    path = store.job_dir(jid) / "error.txt"
    if not path.exists():
        raise HTTPException(404, "No error recorded")
    return {"job_id": jid, "traceback": path.read_text()[-8000:]}


@app.delete("/jobs/{jid}", dependencies=[Depends(auth)])
def delete_job(jid: str) -> dict:
    job = store.get(jid)
    if not job:
        raise HTTPException(404, "Unknown job")
    if job["status"] in ("queued", "running"):
        worker.cancel(jid)
        store.update(jid, status="cancelled", stage="cancelled")
        return {"cancelled": True}
    store.delete(jid)
    return {"deleted": True}
