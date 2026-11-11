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
        continue
    if ngrok_proc.poll() is None:
        break
else:
    print(open("/tmp/ngrok.log").read()[-3000:])
    raise RuntimeError("ngrok tunnel failed - see log above")

print("✅ HindiDub server is LIVE at", PUBLIC_URL)

# Apply future GitHub fixes to this running server automatically.
exec(open("/tmp/hindidub-src/notebooks/autoupdate.py").read())
