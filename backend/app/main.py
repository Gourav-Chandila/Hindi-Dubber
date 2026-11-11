"""HindiDub REST API."""
from __future__ import annotations

import logging
import shutil
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .config import settings
from .jobs import JobStore, Worker

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

store = JobStore(settings)
worker = Worker(store)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    worker.start()
    yield


app = FastAPI(title="HindiDub", version="1.0.0", lifespan=lifespan)

CHUNK_LIMIT = 64 * 1024 * 1024


def auth(x_api_key: str = Header(default="")) -> None:
    if settings.api_key and x_api_key != settings.api_key:
        raise HTTPException(401, "Invalid or missing X-API-Key")


class NewUpload(BaseModel):
    filename: str
    size: int


@app.get("/")
@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "hindidub", "device": settings.resolved_device(),
            "busy": worker.current is not None, "queued": worker.q.qsize()}


# ---- resumable chunked upload (used by the Android app) --------------------
@app.post("/uploads", dependencies=[Depends(auth)])
def create_upload(body: NewUpload) -> dict:
    if body.size <= 0:
        raise HTTPException(400, "Empty file")
    if body.size > settings.max_upload_bytes:
        raise HTTPException(413, f"File too large (max {settings.max_upload_bytes // 2**20} MB)")
    return {"upload_id": store.new_upload(body.filename, body.size), "received": 0}


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
def create_job(file: UploadFile) -> dict:
    jid = store.create_job(file.filename or "video.mp4")
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
