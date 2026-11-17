"""Download every model once (used at Docker build time)."""
import os
import subprocess
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("COQUI_TOS_AGREED", "1")
os.environ["MPLBACKEND"] = "Agg"  # headless; Coqui imports matplotlib
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings


def ai4bharat_models() -> None:
    """Optional, better Hindi models. They may be gated on Hugging Face (need
    HF_TOKEN + accepted terms); dubbing falls back to NLLB / XTTS without them."""
    from huggingface_hub import snapshot_download

    for repo in (settings.indictrans_model, settings.parler_model):
        try:
            snapshot_download(repo)
            print(f"{repo}: ready", flush=True)
        except Exception as exc:  # noqa: BLE001
            print(f"WARNING: {repo} not available ({type(exc).__name__}); using the fallback. "
                  "Add Kaggle secret HF_TOKEN and accept the model's terms on huggingface.co "
                  "to enable it.", flush=True)


if "--only-ai4bharat" in sys.argv:
    ai4bharat_models()
    sys.exit(0)

print("whisper", settings.resolved_whisper_model(), flush=True)
from faster_whisper import WhisperModel

WhisperModel(settings.resolved_whisper_model(), device="cpu", compute_type="int8")

print("nllb", flush=True)
from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

AutoTokenizer.from_pretrained(settings.translate_model)
AutoModelForSeq2SeqLM.from_pretrained(settings.translate_model)

print("ecapa", flush=True)
from speechbrain.inference.speaker import EncoderClassifier

EncoderClassifier.from_hparams(source="speechbrain/spkrec-ecapa-voxceleb",
                               savedir=str(settings.data_dir / "models" / "ecapa"))

print("xtts", flush=True)
from TTS.api import TTS

TTS(settings.tts_model)

print("demucs", flush=True)
try:
    with tempfile.TemporaryDirectory() as d:
        import numpy as np
        import soundfile as sf

        wav = Path(d) / "s.wav"
        # Demucs normalises by the signal's std, so pure silence would divide by zero.
        t = np.linspace(0, 3, 3 * 44100, dtype="float32")
        tone = 0.1 * np.sin(2 * np.pi * 220 * t)
        sf.write(wav, np.stack([tone, tone], axis=1), 44100)
        subprocess.run([sys.executable, "-m", "demucs", "--two-stems", "vocals", "-n", "htdemucs",
                        "-d", "cpu", "-o", d, str(wav)], check=True)
except Exception as exc:  # optional model: dubbing works without it
    print(f"WARNING: Demucs (music separation) unavailable; dubbing will still work "
          f"without it: {exc}", flush=True)
ai4bharat_models()
print("all models ready", flush=True)
