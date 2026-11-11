# Hindi-Dubber (HindiDub)

Android app + free self-hosted backend that turns **any English video into a Hindi-dubbed video**.

- 🎭 **Every character gets their own Hindi voice, and it stays the same for the whole video.**
  Each speaker's voice is cloned from their own lines in the original audio.
- 🎬 **The picture is never changed.** The video stream is copied bit-for-bit. Only a Hindi audio
  track is added, and the original English track is kept as a second track.
- 🎵 Background music and sound effects are kept. Only the speech is replaced.
- ⏱️ Any length: audio is processed in chunks, and the upload is resumable.
- 💸 100% free and open-source models. No paid API keys.
- 🤖 No manual steps for the user: pick video → **Dub to Hindi** → the Hindi video is saved to `Movies/HindiDub`.

## How it works

```
Android app ──(resumable chunked upload)──► Backend (FastAPI, Docker, free HF Space)
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

## One-time setup (≈10 minutes, then fully automatic)

### 1. Free backend on Hugging Face Spaces
1. Create a free account at <https://huggingface.co> and a **write** token at
   <https://huggingface.co/settings/tokens>.
2. In this GitHub repo, go to **Settings → Secrets and variables → Actions**:
   - **Secret** `HF_TOKEN` = your token
   - **Variable** `HF_SPACE` = `your-hf-username/hindidub`
3. Go to **Actions → Backend → Run workflow**. This creates the Space and deploys the backend.
   The first Docker build takes about 20–40 minutes because it downloads all the models.
4. The API is now at `https://your-hf-username-hindidub.hf.space` (open `/health` to check it).

### 2. Get the APK
- **Actions → Android APK → Run workflow** (it also runs on every push to `android/`).
- Download the `HindiDub-apk` artifact and install `HindiDub-x.y.z.apk` on your phone.
- The server URL is **baked into the APK** from `HF_SPACE`, so users never type anything.
- For a permanent download link, push a tag: `git tag v1.0.0 && git push origin v1.0.0`.
  This creates a GitHub Release with the APK attached.

Optional release signing (needed for the Play Store): add the secrets `KEYSTORE_BASE64`
(`base64 -w0 release.jks`), `KEYSTORE_PASSWORD`, `KEY_ALIAS` and `KEY_PASSWORD`.
Without them, the release APK is signed with a debug key, which still installs fine.

## Speed and limits (be realistic)

| Where the backend runs | 10-min video | 1-hour video |
|---|---|---|
| Free HF Space (2 vCPU) | ~1–2 h | ~6–10 h |
| Free Colab / Kaggle T4 GPU, or your own PC with a GPU | ~8–15 min | ~1 h |

- A free Space sleeps after 48 h without use and wakes up on the first request (about 1 minute).
  The app waits for it automatically.
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
deploy/     Hugging Face Space deploy script
.github/workflows/  android.yml (APK build + release), backend.yml (tests + HF deploy)
```

## Development
```bash
cd backend && pip install -r requirements-dev.txt && pytest -q   # fast tests, no models needed
cd android && ./gradlew assembleDebug                             # needs Android SDK
```
