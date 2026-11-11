"""English speech recognition with faster-whisper (VAD + timestamps)."""
from __future__ import annotations

import json
from pathlib import Path


def transcribe(wav16k: Path, work: Path, model_name: str, device: str,
               progress=lambda f: None, total_seconds: float = 0.0) -> list[dict]:
    cache = work / "transcript.json"
    if cache.exists():
        return json.loads(cache.read_text())

    from faster_whisper import WhisperModel

    compute = "float16" if device == "cuda" else "int8"
    model = WhisperModel(model_name, device=device, compute_type=compute)
    # faster-whisper streams the file internally, so long inputs are fine.
    seg_iter, _info = model.transcribe(
        str(wav16k), language="en", vad_filter=True,
        vad_parameters={"min_silence_duration_ms": 400},
        word_timestamps=False, condition_on_previous_text=False, beam_size=5,
    )
    segments: list[dict] = []
    for s in seg_iter:
        text = s.text.strip()
        if not text:
            continue
        segments.append({"start": round(s.start, 3), "end": round(s.end, 3), "text": text})
        if total_seconds:
            progress(min(1.0, s.end / total_seconds))
    cache.write_text(json.dumps(segments, ensure_ascii=False, indent=1))
    return segments
