"""Job + upload bookkeeping (SQLite) and a single background worker thread.

One worker = one dub at a time, which is what a free CPU/GPU box can handle.
Jobs that were queued/running when the server restarted are resumed on boot.
"""
from __future__ import annotations

import json
import logging
import queue
import shutil
import sqlite3
import threading
import time
import traceback
import uuid
from pathlib import Path

from .config import Settings

log = logging.getLogger("hindidub.jobs")


class Cancelled(Exception):
    pass


class JobStore:
    def __init__(self, cfg: Settings):
        self.cfg = cfg
        cfg.data_dir.mkdir(parents=True, exist_ok=True)
        self.jobs_dir = cfg.data_dir / "jobs"
        self.uploads_dir = cfg.data_dir / "uploads"
        self.jobs_dir.mkdir(exist_ok=True)
        self.uploads_dir.mkdir(exist_ok=True)
        self._lock = threading.Lock()
        self.db = sqlite3.connect(cfg.data_dir / "jobs.db", check_same_thread=False)
        self.db.row_factory = sqlite3.Row
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS jobs(
              id TEXT PRIMARY KEY, filename TEXT, status TEXT, stage TEXT,
              progress REAL, error TEXT, stats TEXT,
              created REAL, started REAL, updated REAL);
            CREATE TABLE IF NOT EXISTS uploads(
              id TEXT PRIMARY KEY, filename TEXT, size INTEGER, created REAL);
            """
        )
        self.db.commit()

    # ---- uploads ----------------------------------------------------------
    def new_upload(self, filename: str, size: int) -> str:
        uid = uuid.uuid4().hex
        with self._lock:
            self.db.execute("INSERT INTO uploads VALUES(?,?,?,?)", (uid, filename, size, time.time()))
            self.db.commit()
        self.upload_path(uid).touch()
        return uid

    def upload_path(self, uid: str) -> Path:
        return self.uploads_dir / f"{uid}.part"

    def get_upload(self, uid: str) -> dict | None:
        row = self.db.execute("SELECT * FROM uploads WHERE id=?", (uid,)).fetchone()
        if not row:
            return None
        d = dict(row)
        p = self.upload_path(uid)
        d["received"] = p.stat().st_size if p.exists() else 0
        return d

    def finish_upload(self, uid: str) -> str:
        up = self.get_upload(uid)
        assert up is not None
        job_id = self.create_job(up["filename"])
        dst = self.job_dir(job_id) / ("input" + _ext(up["filename"]))
        shutil.move(str(self.upload_path(uid)), dst)
        with self._lock:
            self.db.execute("DELETE FROM uploads WHERE id=?", (uid,))
            self.db.commit()
        return job_id

    # ---- jobs -------------------------------------------------------------
    def create_job(self, filename: str) -> str:
        jid = uuid.uuid4().hex[:16]
        now = time.time()
        with self._lock:
            self.db.execute(
                "INSERT INTO jobs VALUES(?,?,?,?,?,?,?,?,?,?)",
                (jid, filename, "uploading", "upload", 0.0, None, "{}", now, None, now),
            )
            self.db.commit()
        self.job_dir(jid).mkdir(parents=True, exist_ok=True)
        return jid

    def job_dir(self, jid: str) -> Path:
        return self.jobs_dir / jid

    def input_path(self, jid: str) -> Path | None:
        found = sorted(self.job_dir(jid).glob("input.*"))
        return found[0] if found else None

    def result_path(self, jid: str) -> Path:
        return self.job_dir(jid) / "result.mp4"

    def update(self, jid: str, **fields) -> None:
        if "stats" in fields and not isinstance(fields["stats"], str):
            fields["stats"] = json.dumps(fields["stats"])
        fields["updated"] = time.time()
        cols = ", ".join(f"{k}=?" for k in fields)
        with self._lock:
            self.db.execute(f"UPDATE jobs SET {cols} WHERE id=?", (*fields.values(), jid))
            self.db.commit()

    def get(self, jid: str) -> dict | None:
        row = self.db.execute("SELECT * FROM jobs WHERE id=?", (jid,)).fetchone()
        if not row:
            return None
        d = dict(row)
        d["stats"] = json.loads(d["stats"] or "{}")
        d["eta_seconds"] = _eta(d)
        d["has_result"] = self.result_path(jid).exists()
        d["has_subtitles"] = self.result_path(jid).with_suffix(".hi.srt").exists()
        return d

    def pending(self) -> list[str]:
        rows = self.db.execute(
            "SELECT id FROM jobs WHERE status IN ('queued','running') ORDER BY created"
        ).fetchall()
        return [r["id"] for r in rows]

    def delete(self, jid: str) -> None:
        shutil.rmtree(self.job_dir(jid), ignore_errors=True)
        with self._lock:
            self.db.execute("DELETE FROM jobs WHERE id=?", (jid,))
            self.db.commit()

    def cleanup(self) -> None:
        cutoff = time.time() - self.cfg.retention_hours * 3600
        for row in self.db.execute(
            "SELECT id FROM jobs WHERE updated<? AND status NOT IN ('queued','running')", (cutoff,)
        ).fetchall():
            self.delete(row["id"])
        for row in self.db.execute("SELECT id FROM uploads WHERE created<?", (cutoff,)).fetchall():
            self.upload_path(row["id"]).unlink(missing_ok=True)
            with self._lock:
                self.db.execute("DELETE FROM uploads WHERE id=?", (row["id"],))
                self.db.commit()


def describe_error(exc: BaseException) -> str:
    """Never empty: type, message and the line where it happened
    (e.g. a bare AssertionError has no message at all)."""
    msg = f"{type(exc).__name__}: {exc}".strip().rstrip(":")
    frames = traceback.extract_tb(exc.__traceback__)
    if frames:
        f = frames[-1]
        msg += f" (at {Path(f.filename).name}:{f.lineno} in {f.name})"
    return msg[:500]


def _ext(name: str) -> str:
    suffix = Path(name or "").suffix.lower()
    return suffix if suffix in {".mp4", ".mkv", ".mov", ".webm", ".avi", ".m4v", ".3gp"} else ".mp4"


def _eta(job: dict) -> int | None:
    if job["status"] != "running" or not job["started"] or not job["progress"]:
        return None
    p = job["progress"]
    if p < 0.02:
        return None
    elapsed = time.time() - job["started"]
    return int(elapsed / p * (1 - p))


class Worker:
    def __init__(self, store: JobStore):
        self.store = store
        self.q: queue.Queue[str] = queue.Queue()
        self.cancelled: set[str] = set()
        self.current: str | None = None
        self._thread = threading.Thread(target=self._loop, daemon=True, name="dub-worker")

    def start(self) -> None:
        for jid in self.store.pending():
            self.q.put(jid)
        self._thread.start()
        threading.Thread(target=self._janitor, daemon=True, name="janitor").start()

    def submit(self, jid: str) -> None:
        self.store.update(jid, status="queued", stage="queued", progress=0.0)
        self.q.put(jid)

    def cancel(self, jid: str) -> None:
        self.cancelled.add(jid)

    def queue_position(self, jid: str) -> int:
        items = list(self.q.queue)
        return items.index(jid) + 1 if jid in items else 0

    def _loop(self) -> None:
        from .pipeline.runner import run_pipeline

        while True:
            jid = self.q.get()
            job = self.store.get(jid)
            if not job or jid in self.cancelled:
                self.cancelled.discard(jid)
                continue
            self.current = jid
            self.store.update(jid, status="running", started=time.time(), error=None)

            def report(stage: str, frac: float, _jid=jid) -> None:
                if _jid in self.cancelled:
                    raise Cancelled()
                self.store.update(_jid, stage=stage, progress=frac)

            try:
                video = self.store.input_path(jid)
                if video is None:
                    raise RuntimeError("Input video missing on server (it may have restarted).")
                stats = run_pipeline(video, self.store.job_dir(jid) / "work",
                                     self.store.result_path(jid), self.store.cfg, report)
                shutil.rmtree(self.store.job_dir(jid) / "work", ignore_errors=True)
                video.unlink(missing_ok=True)  # free disk; the result is all we need
                self.store.update(jid, status="done", stage="done", progress=1.0, stats=stats)
            except Cancelled:
                self.store.update(jid, status="cancelled", stage="cancelled")
            except Exception as exc:  # noqa: BLE001
                tb = traceback.format_exc()
                log.error("job %s failed: %s", jid, tb)
                (self.store.job_dir(jid) / "error.txt").write_text(tb)
                self.store.update(jid, status="failed", error=describe_error(exc))
            finally:
                self.cancelled.discard(jid)
                self.current = None

    def _janitor(self) -> None:
        while True:
            try:
                self.store.cleanup()
            except Exception:
                log.exception("cleanup failed")
            time.sleep(1800)
