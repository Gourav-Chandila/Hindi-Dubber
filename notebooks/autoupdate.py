"""Live code updates for the running Kaggle server (exec()'d from tunnel.py).

Every few minutes: fetch the branch from GitHub; if there is a new commit
and no dub is running, apply it and restart only the API server (~20 s).
Models stay on disk and the venv is reused, so nothing is reinstalled
(dependencies are re-synced only when requirements.txt changed).
Jobs are stored in SQLite, so anything queued survives the restart.
"""
import subprocess
import threading
import time

import requests

SRC = "/tmp/hindidub-src"
CHECK_EVERY_SECONDS = 300


class _ServerHandle:
    """Stands in for the notebook's `server` Popen so the keep-alive loop
    never mistakes a planned restart for a crash."""

    def __init__(self, proc):
        self.proc = proc
        self.args = proc.args
        self.restarting = False

    def poll(self):
        return None if self.restarting else self.proc.poll()

    def terminate(self):
        self.proc.terminate()


def _git(*args, timeout=60):
    return subprocess.run(["git", "-C", SRC, *args], capture_output=True, text=True,
                          timeout=timeout).stdout.strip()


def _health():
    try:
        return requests.get("http://127.0.0.1:7860/health", timeout=5).json()
    except Exception:
        return None


def _restart(handle):
    handle.restarting = True
    try:
        handle.proc.terminate()
        try:
            handle.proc.wait(30)
        except subprocess.TimeoutExpired:
            handle.proc.kill()
            handle.proc.wait()
        handle.proc = subprocess.Popen(
            handle.args, cwd=f"{SRC}/backend", env=ENV,  # noqa: F821 (notebook global)
            stdout=open("/tmp/server.log", "a"), stderr=subprocess.STDOUT)
        for _ in range(90):
            if _health():
                return True
            if handle.proc.poll() is not None:
                return False
            time.sleep(2)
        return False
    finally:
        handle.restarting = False


def _keep_tunnel():
    """Restart the public tunnel if it died, and re-announce the address so
    the app can always find it (ntfy keeps messages ~12 h)."""
    global ngrok_proc, PUBLIC_URL
    if "PUBLIC_URL" not in globals():
        return
    if ngrok_proc.poll() is not None:  # noqa: F821
        print("Tunnel stopped - restarting it ...", flush=True)
        try:
            ngrok_proc, PUBLIC_URL = _start_cloudflare()  # noqa: F821
        except Exception:
            ngrok_proc, PUBLIC_URL = _start_ngrok()  # noqa: F821
        print("✅ HindiDub server is LIVE at", PUBLIC_URL, flush=True)
    publish_url(PUBLIC_URL)  # noqa: F821


def _watch(handle):
    branch = _git("rev-parse", "--abbrev-ref", "HEAD")
    rounds = 0
    while True:
        time.sleep(CHECK_EVERY_SECONDS)
        rounds += 1
        try:
            if rounds % 12 == 0 or ngrok_proc.poll() is not None:  # noqa: F821 (hourly)
                _keep_tunnel()
        except Exception as exc:
            print("tunnel check failed:", exc, flush=True)
        try:
            _git("fetch", "-q", "--depth", "1", "origin", branch)
            new, cur = _git("rev-parse", "FETCH_HEAD"), _git("rev-parse", "HEAD")
            if not new or new == cur:
                continue
            h = _health()
            if h and (h.get("busy") or h.get("queued")):
                continue  # never interrupt a dub; try again next round
            changed = _git("diff", "--name-only", cur, new).split()
            _git("reset", "-q", "--hard", new)
            if "backend/requirements.txt" in changed:
                subprocess.run(["uv", "pip", "install", "-q", "--python", PY,  # noqa: F821
                                "-r", f"{SRC}/backend/requirements.txt"], check=False)
            ok = _restart(handle)
            print(f"🔄 Server updated to {new[:7]}: {'OK' if ok else 'FAILED, see log below'}",
                  flush=True)
            if not ok:
                print(open("/tmp/server.log").read()[-3000:], flush=True)
        except Exception as exc:
            print("auto-update check failed:", exc, flush=True)


if not isinstance(globals().get("server"), _ServerHandle):
    server = _ServerHandle(server)  # noqa: F821 - wraps the notebook's Popen
    threading.Thread(target=_watch, args=(server,), daemon=True, name="autoupdate").start()
    print("🔄 Auto-update on: new GitHub commits are applied within ~5 min when idle.", flush=True)
