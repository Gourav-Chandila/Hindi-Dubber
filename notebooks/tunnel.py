"""Make the local HindiDub server reachable from the phone.

Run from the Kaggle notebook with exec(), so it uses the notebook's globals.
Uses a free Cloudflare quick tunnel (no account, no monthly data cap); its
address changes every run, so it is announced on a private ntfy.sh topic
derived from the HindiDub API key, where the app looks it up. Falls back to
the fixed ngrok domain (free plan: 1 GB/month) if Cloudflare fails.
"""
import json
import os
import subprocess
import time

import requests
from pyngrok import conf, installer, ngrok

ngrok.kill()  # stop any agent left from an earlier attempt (free plan = 1 session)
subprocess.run(["pkill", "-x", "ngrok"], check=False)
time.sleep(1)

ngrok_path = conf.get_default().ngrok_path
if not os.path.exists(ngrok_path):
    installer.install_ngrok(ngrok_path)

# Optional Hugging Face token (Kaggle secret HF_TOKEN) for the gated AI4Bharat
# models (better Hindi translation + voice). Restart the API server with it.
try:
    from kaggle_secrets import UserSecretsClient

    _hf_token = UserSecretsClient().get_secret("HF_TOKEN")
except Exception:
    _hf_token = ""
if _hf_token and ENV.get("HF_TOKEN") != _hf_token:  # noqa: F821
    ENV["HF_TOKEN"] = _hf_token  # noqa: F821
    _proc = getattr(server, "proc", server)  # noqa: F821
    _proc.terminate()
    try:
        _proc.wait(30)
    except subprocess.TimeoutExpired:
        _proc.kill()
    _new = subprocess.Popen(_proc.args, cwd="/tmp/hindidub-src/backend", env=ENV,  # noqa: F821
                            stdout=open("/tmp/server.log", "a"), stderr=subprocess.STDOUT)
    if hasattr(server, "proc"):  # noqa: F821
        server.proc = _new  # noqa: F821
    else:
        server = _new
    for _ in range(60):
        try:
            requests.get("http://127.0.0.1:7860/health", timeout=3)
            break
        except Exception:
            time.sleep(2)
    # fetch the AI4Bharat models in the background so the first dub isn't slowed down
    subprocess.Popen([PY, "scripts/prefetch_models.py", "--only-ai4bharat"],  # noqa: F821
                     cwd="/tmp/hindidub-src/backend", env=ENV,  # noqa: F821
                     stdout=open("/tmp/prefetch_ai4bharat.log", "w"), stderr=subprocess.STDOUT)
    print("🔑 Hugging Face token loaded - better Hindi models enabled", flush=True)
elif not _hf_token:
    print("ℹ️ No HF_TOKEN secret: using standard Hindi models (add it for better Hindi).",
          flush=True)

import hashlib
import re

# The app finds the server through a private ntfy.sh topic derived from the
# HindiDub API key, so the tunnel address may change on every run.
_key = API_KEY or NGROK_DOMAIN  # noqa: F821  (notebook globals)
NTFY_TOPIC = "hindidub-" + hashlib.sha256(_key.encode()).hexdigest()[:24]


def _healthy(url):
    try:
        r = requests.get(f"{url}/health", timeout=8, headers={"ngrok-skip-browser-warning": "1"})
        return r.ok and r.json().get("service") == "hindidub"
    except Exception:
        return False


def _published_url():
    try:
        lines = requests.get(f"https://ntfy.sh/{NTFY_TOPIC}/json?poll=1&since=12h",
                             timeout=10).text.strip().splitlines()
        msgs = [json.loads(x) for x in lines if x.strip()]
        msgs = [m["message"] for m in msgs if m.get("event") == "message"]
        return msgs[-1].strip() if msgs else None
    except Exception:
        return None


def publish_url(url):
    try:
        requests.post(f"https://ntfy.sh/{NTFY_TOPIC}", data=url.encode(), timeout=10,
                      headers={"Title": "hindidub-server", "Tags": "hindidub"})
        return True
    except Exception as exc:
        print("could not publish server address:", exc, flush=True)
        return False


def _start_cloudflare():
    """Free Cloudflare quick tunnel: no account, no monthly data cap."""
    exe = "/tmp/cloudflared"
    if not os.path.exists(exe):
        subprocess.run(["curl", "-sSL", "-o", exe, "https://github.com/cloudflare/cloudflared/"
                        "releases/latest/download/cloudflared-linux-amd64"], check=True)
        os.chmod(exe, 0o755)
    proc = subprocess.Popen([exe, "tunnel", "--no-autoupdate", "--url", "http://127.0.0.1:7860"],
                            stdout=open("/tmp/cloudflared.log", "w"), stderr=subprocess.STDOUT)
    url = None
    for _ in range(60):
        time.sleep(1)
        if proc.poll() is not None:
            break
        m = re.search(r"https://[a-z0-9-]+\.trycloudflare\.com", open("/tmp/cloudflared.log").read())
        if m:
            url = m.group(0)
            if _healthy(url):
                return proc, url
    proc.kill()
    print(open("/tmp/cloudflared.log").read()[-2000:], flush=True)
    raise RuntimeError("cloudflare tunnel did not come up" + (f" ({url})" if url else ""))


def _start_ngrok():
    """Fallback: the fixed ngrok domain (free plan: 1 GB/month)."""
    public = f"https://{NGROK_DOMAIN}"  # noqa: F821
    proc = None
    for attempt in range(12):
        if attempt:
            print(f"ngrok domain still in use by another session - retrying ({attempt}/11) ...",
                  flush=True)
            time.sleep(15)
        for flag in ("--url", "--domain"):
            proc = subprocess.Popen(
                [ngrok_path, "http", "7860", f"{flag}={NGROK_DOMAIN}",  # noqa: F821
                 "--authtoken", NGROK_AUTHTOKEN, "--log", "stdout"],  # noqa: F821
                stdout=open("/tmp/ngrok.log", "w"), stderr=subprocess.STDOUT)
            for _ in range(25):
                time.sleep(1)
                if proc.poll() is not None or _healthy(public):
                    break
            else:
                proc.kill()
                proc.wait()
                continue
            if proc.poll() is None:
                return proc, public
        if "ERR_NGROK_334" not in open("/tmp/ngrok.log").read():
            break
    print(open("/tmp/ngrok.log").read()[-3000:], flush=True)
    raise RuntimeError("ngrok tunnel failed - see log above")


# Don't start a duplicate if another session is already serving.
_existing = _published_url()
if _existing and _healthy(_existing):
    server.terminate()  # noqa: F821
    raise SystemExit(f"Another session is ALREADY serving HindiDub at {_existing} - use the app "
                     "now. This duplicate run stops here to save your GPU hours.")

try:
    ngrok_proc, PUBLIC_URL = _start_cloudflare()  # name kept: the keep-alive cell stops it
    TUNNEL = "cloudflare"
except Exception as exc:
    print("Cloudflare tunnel failed, trying ngrok:", exc, flush=True)
    ngrok_proc, PUBLIC_URL = _start_ngrok()
    TUNNEL = "ngrok"
publish_url(PUBLIC_URL)
print(f"🌐 Tunnel: {TUNNEL} - the app finds this address automatically.", flush=True)
print("✅ HindiDub server is LIVE at", PUBLIC_URL)

# Apply future GitHub fixes to this running server automatically.
exec(open("/tmp/hindidub-src/notebooks/autoupdate.py").read())
