"""Start the public ngrok tunnel to the local HindiDub server.

Run from the Kaggle notebook with exec(), so it uses the notebook's
NGROK_AUTHTOKEN / NGROK_DOMAIN variables. Calls the ngrok agent directly
(newer agents renamed the "domain" setting to "url", which broke pyngrok's
connect()); tries --url first and falls back to --domain for older agents.
"""
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

PUBLIC_URL = f"https://{NGROK_DOMAIN}"  # noqa: F821  (defined in the notebook)
ngrok_proc = None
# ERR_NGROK_334 = the domain is still held by another session (an older run
# that is shutting down, or a second session). Wait for it to go away.
for attempt in range(12):
    if attempt:
        print(f"ngrok domain still in use by another session - retrying ({attempt}/11) ...",
              flush=True)
        time.sleep(15)
    for flag in ("--url", "--domain"):
        ngrok_proc = subprocess.Popen(
            [ngrok_path, "http", "7860", f"{flag}={NGROK_DOMAIN}",  # noqa: F821
             "--authtoken", NGROK_AUTHTOKEN, "--log", "stdout"],  # noqa: F821
            stdout=open("/tmp/ngrok.log", "w"), stderr=subprocess.STDOUT)
        for _ in range(25):
            time.sleep(1)
            if ngrok_proc.poll() is not None:
                break
            try:
                r = requests.get(f"{PUBLIC_URL}/health", timeout=5,
                                 headers={"ngrok-skip-browser-warning": "1"})
                if r.ok and r.json().get("service") == "hindidub":
                    break
            except Exception:
                pass
        else:
            ngrok_proc.kill()
            ngrok_proc.wait()  # so poll() reports it as stopped
            continue
        if ngrok_proc.poll() is None:
            break
    if ngrok_proc.poll() is None:
        break  # tunnel is up
    if "ERR_NGROK_334" not in open("/tmp/ngrok.log").read():
        break  # a different error: don't keep retrying
if ngrok_proc.poll() is not None:
    log_text = open("/tmp/ngrok.log").read()
    print(log_text[-3000:])
    if "ERR_NGROK_334" in log_text:
        raise RuntimeError(
            "Your ngrok domain is used by ANOTHER running session. In Kaggle open "
            "'View Active Events' (bottom-left), stop every other HindiDub session, then run again.")
    raise RuntimeError("ngrok tunnel failed - see log above")

print("✅ HindiDub server is LIVE at", PUBLIC_URL)

# Apply future GitHub fixes to this running server automatically.
exec(open("/tmp/hindidub-src/notebooks/autoupdate.py").read())
