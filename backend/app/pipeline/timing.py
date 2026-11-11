"""Fit synthesised Hindi speech into the original speech slots without drift.

Pure functions (numpy only) so they are unit-testable without any ML model.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class FitPlan:
    rate: float          # >1 speeds up, 1 = untouched
    needs_shorter: bool  # still too long even at max rate -> ask for paraphrase


def plan_fit(tts_seconds: float, slot_seconds: float, max_rate: float) -> FitPlan:
    if slot_seconds <= 0 or tts_seconds <= slot_seconds:
        return FitPlan(rate=1.0, needs_shorter=False)
    rate = tts_seconds / slot_seconds
    if rate <= max_rate:
        return FitPlan(rate=rate, needs_shorter=False)
    return FitPlan(rate=max_rate, needs_shorter=True)


def slot_for(segments: list[dict], i: int, total: float, gap: float = 0.05) -> float:
    """Available time for segment i: until the next segment starts (or end of file),
    so a line may borrow silence after it but never overlap the next line."""
    start = segments[i]["start"]
    nxt = segments[i + 1]["start"] if i + 1 < len(segments) else total
    return max(0.0, min(nxt, total) - start - gap)


def time_stretch(x: np.ndarray, sr: int, rate: float) -> np.ndarray:
    """Speed up speech by `rate` without changing pitch (rubberband if present,
    otherwise a phase-vocoder fallback)."""
    if abs(rate - 1.0) < 1e-3 or len(x) == 0:
        return x
    try:
        import pyrubberband as pyrb

        return pyrb.time_stretch(x, sr, rate).astype(np.float32)
    except Exception:
        return _ola_stretch(x, rate)


def _ola_stretch(x: np.ndarray, rate: float, frame: int = 1024, hop_out: int = 256) -> np.ndarray:
    """Simple WSOLA-ish overlap-add; good enough as a fallback for speech."""
    mono = x if x.ndim == 1 else x.mean(axis=1)
    hop_in = int(round(hop_out * rate))
    win = np.hanning(frame).astype(np.float32)
    n_frames = max(1, (len(mono) - frame) // hop_in + 1)
    out = np.zeros(n_frames * hop_out + frame, dtype=np.float32)
    norm = np.zeros_like(out)
    for k in range(n_frames):
        a = k * hop_in
        seg = mono[a:a + frame]
        if len(seg) < frame:
            seg = np.pad(seg, (0, frame - len(seg)))
        b = k * hop_out
        out[b:b + frame] += seg * win
        norm[b:b + frame] += win
    norm[norm < 1e-6] = 1.0
    return (out / norm)[: int(len(mono) / rate)]


def fit_to_slot(x: np.ndarray, sr: int, slot_seconds: float) -> np.ndarray:
    """Hard guarantee: never exceed the slot (short fade-out if trimming)."""
    max_len = int(slot_seconds * sr)
    if len(x) <= max_len:
        return x
    y = x[:max_len].copy()
    fade = min(len(y), int(0.03 * sr))
    if fade > 0:
        y[-fade:] *= np.linspace(1.0, 0.0, fade, dtype=np.float32)
    return y
