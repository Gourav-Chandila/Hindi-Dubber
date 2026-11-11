# Hindi-Dubber (HindiDub)

Android app + free self-hosted backend that turns **any English video into a Hindi-dubbed video**.

- 🎭 **Every character gets their own Hindi voice, and it stays the same for the whole video.**
  Each speaker's voice is cloned from their own lines in the original audio.
- 🎬 **The picture is never changed.** The video stream is copied bit-for-bit. Only a Hindi audio
  track is added, and the original English track is kept as a second track.
- 🎵 Background music and sound effects are kept. Only the speech is replaced.
- ⏱️ Any length: audio is processed in chunks, and the upload is resumable.
- 💸 100% free: open-source models on Kaggle's free GPU. No paid API keys.
- 🤖 No manual steps for the user: pick video → **Dub to Hindi** → the Hindi video is saved to `Movies/HindiDub`.

## How it works

```
Android app ──(resumable chunked upload)──► Backend (FastAPI on a free Kaggle GPU, via ngrok)
                                              1. ffmpeg      extract audio
                                              2. Demucs      split voices / music
                                              3. Whisper     English speech → text + timestamps
                                              4. ECAPA       who is speaking (clustered over the WHOLE video)
                                              5. per-speaker 10 s reference clip of their real voice
                                              6. NLLB-200    English → Hindi
                                              7. XTTS-v2     Hindi speech in each character's cloned voice
                                              8. fit timing (time-stretch / shorter translation), mix with music
                                              9. ffmpeg      mux: -c:v copy (video untouched) + Hindi + English
Android app ◄──(download)── result.mp4 (+ Hindi .srt)
```

**Why the voices stay consistent:** speaker embeddings from the whole video are clustered
together, so a character has one speaker id from start to finish. Each id is always
synthesised from the same reference clip and conditioning latents, at a low sampling
temperature.

| Part | Model | Licence |
|---|---|---|
| Speech-to-text | faster-whisper (`small` on CPU, `large-v3` on GPU) | MIT |
| Voice/music split | Demucs htdemucs | MIT |
| Speaker ID | SpeechBrain ECAPA-TDNN | Apache-2.0 |
| Translation | Meta NLLB-200 distilled 600M | CC-BY-NC-4.0 |
| Hindi voice cloning | Coqui XTTS-v2 | Coqui Public Model Licence (non-commercial) |

> ⚠️ NLLB and XTTS-v2 are free **for non-commercial use only**.

## One-time setup (≈15 minutes)

The server runs **free on a Kaggle GPU** and is reached through a **free fixed ngrok URL**.

### 1. ngrok (free fixed URL)
1. Sign up at <https://dashboard.ngrok.com/signup>.
2. Copy your **authtoken**: <https://dashboard.ngrok.com/get-started/your-authtoken>
3. Claim your free **static domain**: <https://dashboard.ngrok.com/domains> (e.g. `abc-xyz.ngrok-free.app`).

### 2. Kaggle (free GPU, 30 h/week)
1. Sign up at <https://www.kaggle.com> and **verify your phone number** (needed for Internet + GPU).
2. **Create → New Notebook → File → Import Notebook**, then import `notebooks/hindidub_kaggle.ipynb` from this repo.
3. Settings: **Accelerator = GPU T4 x2**, **Internet = On**.
4. **Add-ons → Secrets**: add and tick `NGROK_AUTHTOKEN`, `NGROK_DOMAIN`, and `HINDIDUB_API_KEY`
   (any long random password).

### 3. GitHub (bakes the URL + key into the APK)
**Settings → Secrets and variables → Actions**:
- Variable `NGROK_DOMAIN` = your ngrok domain
- Secret `HINDIDUB_API_KEY` = the same password as in Kaggle

Then **Actions → Android APK → Run workflow** and install the APK from the `HindiDub-apk` artifact.

### Every time you dub
1. In Kaggle: **Save Version → Save & Run All (Commit)**. It runs in the background and is ready in about 10 minutes.
2. On your phone: open HindiDub → pick a video → **Dub to Hindi**.
3. The notebook stops by itself after 45 minutes of no work, to save your GPU hours.

<details><summary>Alternative: Hugging Face Space (needs HF PRO)</summary>

Set the secret `HF_TOKEN` and the variables `HF_SPACE=user/hindidub` and `HF_DEPLOY=true`, then run **Actions → Backend**.
</details>

## Speed and limits (be realistic)

| Where the backend runs | 10-min video | 1-hour video |
|---|---|---|
| **Kaggle free T4 GPU (default)** | ~8–15 min | ~1 h |
| CPU only (2 vCPU) | ~1–2 h | ~6–10 h |

- A Kaggle session lasts at most 12 h, and the free quota is 30 GPU-hours a week.
- One video is processed at a time, and the others queue.
- No lip-sync: the picture is deliberately untouched, so mouths won't match the Hindi.
- Up to 8 distinct speakers by default (`HD_MAX_SPEAKERS`).

### Faster: run the backend on a GPU
```bash
cd backend
docker build --build-arg TORCH_INDEX=https://download.pytorch.org/whl/cu121 -t hindidub .
docker run --gpus all -p 7860:7860 -e HD_DEVICE=cuda hindidub
```
Then set the server URL in the app (⚙️ icon) to `http://<your-pc-ip>:7860`.

## API (for scripts)
```bash
curl -F file=@movie.mp4 https://<space>.hf.space/jobs            # -> {"job_id": "..."}
curl https://<space>.hf.space/jobs/<job_id>                       # status, stage, progress, ETA
curl -o hindi.mp4 https://<space>.hf.space/jobs/<job_id>/result
curl -o hindi.srt https://<space>.hf.space/jobs/<job_id>/subtitles
```
Set `HD_API_KEY` on the server to require an `X-API-Key` header. The app has a field for it.

### Backend settings (environment variables)
| Var | Default | Meaning |
|---|---|---|
| `HD_DEVICE` | `auto` | `cpu` / `cuda` |
| `HD_WHISPER_MODEL` | `auto` | `small` on CPU, `large-v3` on GPU |
| `HD_SEPARATE` | `true` | keep music by splitting voices out (slower on CPU) |
| `HD_MAX_SPEAKERS` | `8` | max distinct voices |
| `HD_SPEAKER_THRESHOLD` | `0.70` | higher = more speakers |
| `HD_MAX_STRETCH` | `1.35` | max speed-up to fit a line in its slot |
| `HD_MAX_UPLOAD_MB` | `4096` | upload limit |
| `HD_RETENTION_HOURS` | `24` | finished jobs are auto-deleted |

## Repo layout
```
android/    Kotlin + Jetpack Compose app (WorkManager background upload/poll/download, ExoPlayer)
backend/    FastAPI + pipeline (app/pipeline/*), Dockerfile, tests
notebooks/  Kaggle notebook that runs the server on a free GPU
deploy/     optional Hugging Face Space deploy script
.github/workflows/  android.yml (APK build + release), backend.yml (tests + HF deploy)
```

## Development
```bash
cd backend && pip install -r requirements-dev.txt && pytest -q   # fast tests, no models needed
cd android && ./gradlew assembleDebug                             # needs Android SDK
```
