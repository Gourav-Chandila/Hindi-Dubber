"""Studio voice mode: give every character its own clean, built-in XTTS voice.

Cloning from a short, noisy movie clip often sounds unreal and similar
characters end up sounding alike. Studio mode instead picks a different
professionally recorded XTTS voice per character, matched to the
character's gender (estimated from the pitch of their real voice), so
voices are clear and easy to tell apart, and stay the same all video.
"""
from __future__ import annotations

import numpy as np

# Built-in XTTS v2 speakers, ordered so that consecutive picks sound very different.
FEMALE_VOICES = [
    "Claribel Dervla", "Ana Florence", "Gracie Wise", "Daisy Studious", "Sofia Hellen",
    "Tammie Ema", "Brenda Stern", "Henriette Usha", "Gitta Nikolina", "Tanja Adelina",
    "Alison Dietlinde", "Annmarie Nele", "Asya Anara", "Tammy Grit", "Narelle Moon",
]
MALE_VOICES = [
    "Damien Black", "Andrew Chipper", "Craig Gutsy", "Viktor Eka", "Abrahan Mack",
    "Dionisio Schuyler", "Royston Min", "Baldur Sanjin", "Ludvig Milivoj", "Kumar Dahl",
    "Aaron Dreschner", "Badr Odhiambo", "Gilberto Mathias", "Torcull Diarmuid", "Wulf Carlevaro",
]
FEMALE_ABOVE_HZ = 165.0  # typical split between adult male and female speaking pitch


def estimate_pitch(x: np.ndarray, sr: int, fmin: float = 70.0, fmax: float = 400.0) -> float:
    """Median fundamental frequency (Hz) over voiced frames; 0 if none found."""
    x = np.asarray(x, dtype=np.float32)
    if x.ndim > 1:
        x = x.mean(axis=1)
    frame, hop = int(0.04 * sr), int(0.02 * sr)
    if len(x) < frame:
        return 0.0
    lag_min, lag_max = int(sr / fmax), int(sr / fmin)
    energy_floor = 0.1 * np.sqrt(np.mean(x ** 2) + 1e-12)
    pitches = []
    for start in range(0, len(x) - frame, hop):
        f = x[start:start + frame] * np.hanning(frame)
        if np.sqrt(np.mean(f ** 2)) < energy_floor:
            continue  # silence
        ac = np.correlate(f, f, mode="full")[frame - 1:]
        if ac[0] <= 0:
            continue
        seg = ac[lag_min:lag_max]
        if len(seg) == 0:
            continue
        lag = lag_min + int(np.argmax(seg))
        if ac[lag] / ac[0] < 0.3:
            continue  # not clearly periodic -> unvoiced
        pitches.append(sr / lag)
    return float(np.median(pitches)) if pitches else 0.0


def assign_voices(pitches: dict[int, float], available: list[str]) -> dict[int, dict]:
    """Map speaker id -> {"voice", "gender", "pitch_hz"}; every speaker gets a
    different voice while any are left, chosen in order of first appearance."""
    have = set(available)
    pools = {
        "female": [v for v in FEMALE_VOICES if v in have],
        "male": [v for v in MALE_VOICES if v in have],
    }
    used: set[str] = set()
    spare = [v for v in available if v not in FEMALE_VOICES and v not in MALE_VOICES]
    out: dict[int, dict] = {}
    for spk in sorted(pitches):
        gender = "female" if pitches[spk] >= FEMALE_ABOVE_HZ else "male"
        other = "male" if gender == "female" else "female"
        candidates = [v for v in pools[gender] + spare + pools[other] if v not in used]
        if not candidates:  # more characters than voices: reuse, still deterministic
            candidates = pools[gender] or available
            voice = candidates[len(out) % len(candidates)]
        else:
            voice = candidates[0]
        used.add(voice)
        out[spk] = {"voice": voice, "gender": gender, "pitch_hz": round(pitches[spk], 1)}
    return out
