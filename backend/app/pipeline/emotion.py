"""Match the scene: measure how each original line was spoken (loud or soft,
excited or calm, fast or slow) and carry that over to the Hindi line.

* loudness: every dubbed line is set to the original line's loudness relative
  to the speaker's typical level, so shouts stay loud and whispers soft;
* style: a short mood label + pace, used by the Indic Parler-TTS voice
  description to speak the line in a fitting tone.
"""
from __future__ import annotations

import numpy as np

from .voices import estimate_pitch

TARGET_RMS = 0.08  # loudness of a "normal" dubbed line before scene matching


def line_features(wav: np.ndarray, sr: int, start: float, end: float, text: str) -> dict:
    clip = wav[int(start * sr): int(end * sr)]
    dur = max(0.05, end - start)
    rms = float(np.sqrt(np.mean(np.square(clip)) + 1e-12)) if len(clip) else 0.0
    # pitch movement: spread of pitch over short windows (lively vs flat)
    pitches = []
    win = int(0.25 * sr)
    for a in range(0, max(0, len(clip) - win), win):
        f0 = estimate_pitch(clip[a:a + win], sr)
        if f0:
            pitches.append(f0)
    spread = float(np.std(pitches) / np.mean(pitches)) if len(pitches) >= 3 else 0.0
    words = max(1, len(text.split()))
    return {"rms": rms, "pitch_spread": round(spread, 3), "words_per_s": round(words / dur, 2)}


def classify(feat: dict, typical_rms: float, text: str) -> dict:
    """-> {"mood", "pace", "loudness"} where loudness = level vs the speaker's norm."""
    rel = feat["rms"] / typical_rms if typical_rms > 0 else 1.0
    t = text.strip()
    if rel > 1.6 or (t.endswith("!") and rel > 1.15):
        mood = "excited" if feat["pitch_spread"] > 0.12 else "loud"
    elif rel < 0.55:
        mood = "soft"
    elif t.endswith("?"):
        mood = "questioning"
    elif feat["pitch_spread"] > 0.18:
        mood = "expressive"
    else:
        mood = "calm"
    wps = feat["words_per_s"]
    pace = "fast" if wps > 3.3 else "slow" if wps < 1.9 else "moderate"
    return {"mood": mood, "pace": pace, "loudness": round(float(np.clip(rel, 0.4, 2.2)), 2)}


def annotate(segments: list[dict], wav: np.ndarray, sr: int) -> None:
    """Add s["style"] to every segment (in place)."""
    feats = [line_features(wav, sr, s["start"], s["end"], s.get("text", "")) for s in segments]
    by_spk: dict[int, list[float]] = {}
    for s, f in zip(segments, feats, strict=True):
        if f["rms"] > 0:
            by_spk.setdefault(s.get("speaker", 0), []).append(f["rms"])
    typical = {k: float(np.median(v)) for k, v in by_spk.items()}
    for s, f in zip(segments, feats, strict=True):
        s["style"] = classify(f, typical.get(s.get("speaker", 0), 0.0), s.get("text", ""))


def match_loudness(clip: np.ndarray, style: dict | None) -> np.ndarray:
    """Normalise a dubbed line, then scale it like the original line."""
    if len(clip) == 0:
        return clip
    rms = float(np.sqrt(np.mean(np.square(clip)) + 1e-12))
    gain = TARGET_RMS / rms if rms > 1e-6 else 1.0
    gain *= (style or {}).get("loudness", 1.0)
    out = clip * gain
    peak = float(np.abs(out).max())
    return (out * (0.98 / peak) if peak > 0.98 else out).astype(np.float32)


_MOOD_TEXT = {
    "excited": "speaks in an excited, energetic and lively tone",
    "loud": "speaks loudly and forcefully",
    "soft": "speaks softly and gently, almost whispering",
    "questioning": "speaks in a curious, questioning tone",
    "expressive": "speaks expressively with natural emotion",
    "calm": "speaks in a calm, natural, conversational tone",
}
_PACE_TEXT = {"fast": "at a fast pace", "slow": "at a slow, relaxed pace", "moderate": "at a moderate pace"}


def describe(voice: str, pitch: str, style: dict | None) -> str:
    """Indic Parler-TTS voice description for one line."""
    style = style or {"mood": "calm", "pace": "moderate"}
    return (f"{voice} {_MOOD_TEXT.get(style['mood'], _MOOD_TEXT['calm'])} "
            f"{_PACE_TEXT.get(style['pace'], _PACE_TEXT['moderate'])}, with a {pitch} voice. "
            "The recording is very clear and close-sounding, with no background noise.")
