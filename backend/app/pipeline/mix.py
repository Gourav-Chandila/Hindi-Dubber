"""Place dubbed lines at their original start times and mix with the background."""
from __future__ import annotations

import numpy as np

from . import audio


def place(track: np.ndarray, clip: np.ndarray, start_sample: int) -> None:
    if start_sample >= len(track) or len(clip) == 0:
        return
    end = min(len(track), start_sample + len(clip))
    track[start_sample:end] += clip[: end - start_sample]


def speech_mask(segments: list[dict], n: int, sr: int, pad: float = 0.15) -> np.ndarray:
    mask = np.zeros(n, dtype=np.float32)
    for s in segments:
        a = max(0, int((s["start"] - pad) * sr))
        b = min(n, int((s["end"] + pad) * sr))
        mask[a:b] = 1.0
    # Smooth edges (~80 ms) so ducking does not click.
    k = max(1, int(0.08 * sr))
    kernel = np.ones(k, dtype=np.float32) / k
    return np.clip(np.convolve(mask, kernel, mode="same"), 0.0, 1.0)


def mix(dub: np.ndarray, background: np.ndarray, segments: list[dict], sr: int,
        separated: bool) -> np.ndarray:
    """dub: mono (n,), background: (n, ch). If the background still contains the
    English voices (no separation) it is ducked hard under the Hindi speech."""
    n = len(background)
    dub = dub[:n] if len(dub) >= n else np.pad(dub, (0, n - len(dub)))
    duck_depth = 0.25 if separated else 0.9
    gain = 1.0 - duck_depth * speech_mask(segments, n, sr)
    out = background * gain[:, None] + dub[:, None]
    return normalise_loudness(out, sr)


def normalise_loudness(x: np.ndarray, sr: int, target_lufs: float = -16.0) -> np.ndarray:
    try:
        import pyloudnorm as pyln

        meter = pyln.Meter(sr)
        loud = meter.integrated_loudness(x)
        if np.isfinite(loud):
            x = pyln.normalize.loudness(x, loud, target_lufs)
    except Exception:
        r = audio.rms(x)
        if r > 0:
            x = x * (0.1 / r)
    peak = np.abs(x).max()
    if peak > 0.98:
        x = x * (0.98 / peak)
    return x.astype(np.float32)
