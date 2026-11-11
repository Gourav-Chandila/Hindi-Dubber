"""Split speech from music/effects with Demucs, chunk by chunk so that
multi-hour videos never have to fit in memory at once."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np

from . import audio

MIN_SECONDS = 1.0


def needs_model(chunk: np.ndarray, sr: int) -> bool:
    """Demucs crashes on (near-)silent input (std = 0) and on very short clips.
    Such chunks have no speech to separate anyway."""
    return len(chunk) >= MIN_SECONDS * sr and float(np.std(chunk)) > 1e-5


def separate(mix_wav: Path, work: Path, chunk_seconds: int, device: str,
             progress=lambda f: None) -> tuple[Path, Path]:
    vocals_out = work / "vocals.wav"
    bg_out = work / "background.wav"
    if vocals_out.exists() and bg_out.exists():
        return vocals_out, bg_out

    data, sr = audio.load(mix_wav)
    n = len(data)
    step = chunk_seconds * sr
    chunk_dir = work / "demucs"
    chunk_dir.mkdir(exist_ok=True)
    vocals_parts, bg_parts = [], []
    starts = list(range(0, n, step)) or [0]
    for idx, a in enumerate(starts):
        chunk = data[a:a + step]
        if not needs_model(chunk, sr):
            vocals_parts.append(np.zeros_like(chunk))
            bg_parts.append(chunk)
            progress((idx + 1) / len(starts))
            continue
        part = chunk_dir / f"chunk_{idx:04d}.wav"
        audio.save(part, chunk, sr)
        out_dir = chunk_dir / f"out_{idx:04d}"
        stem_dir = out_dir / "htdemucs" / part.stem
        if not (stem_dir / "vocals.wav").exists():
            subprocess.run(
                [sys.executable, "-m", "demucs", "--two-stems", "vocals", "-n", "htdemucs",
                 "-d", device, "-o", str(out_dir), str(part)],
                check=True, capture_output=True,
            )
        v, _ = audio.load(stem_dir / "vocals.wav")
        b, _ = audio.load(stem_dir / "no_vocals.wav")
        vocals_parts.append(v)
        bg_parts.append(b)
        part.unlink(missing_ok=True)
        progress((idx + 1) / len(starts))

    audio.save(vocals_out, np.concatenate(vocals_parts)[:n], sr)
    audio.save(bg_out, np.concatenate(bg_parts)[:n], sr)
    return vocals_out, bg_out
