"""Small numpy audio utilities shared by the pipeline."""
from __future__ import annotations

from pathlib import Path

import numpy as np
import soundfile as sf


def load(path: Path, mono: bool = False) -> tuple[np.ndarray, int]:
    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    if mono:
        data = data.mean(axis=1, keepdims=True)
    return data, sr


def save(path: Path, data: np.ndarray, sr: int) -> Path:
    sf.write(str(path), data, sr, subtype="PCM_16")
    return path


def resample(x: np.ndarray, sr_in: int, sr_out: int) -> np.ndarray:
    if sr_in == sr_out:
        return x
    from math import gcd

    from scipy.signal import resample_poly

    g = gcd(sr_in, sr_out)
    return resample_poly(x, sr_out // g, sr_in // g, axis=0).astype(np.float32)


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(x)) + 1e-12))
