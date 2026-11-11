"""Pick one clean reference clip per speaker. The SAME clip is used for every
line of that speaker -> the cloned Hindi voice never drifts."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from . import audio

TARGET_SECONDS = 10.0
MIN_SECONDS = 3.0


def pick_reference_segments(segments: list[dict], wav: np.ndarray, sr: int) -> dict[int, list[dict]]:
    """For each speaker choose the loudest/cleanest segments until ~10 s."""
    by_spk: dict[int, list[tuple[float, dict]]] = {}
    for s in segments:
        dur = s["end"] - s["start"]
        if dur < 1.0:
            continue
        clip = wav[int(s["start"] * sr): int(s["end"] * sr)]
        score = audio.rms(clip) * min(dur, 8.0)  # prefer loud, longer, single-speaker lines
        by_spk.setdefault(s["speaker"], []).append((score, s))
    chosen: dict[int, list[dict]] = {}
    for spk, items in by_spk.items():
        items.sort(key=lambda t: t[0], reverse=True)
        total, picks = 0.0, []
        for _, s in items:
            picks.append(s)
            total += s["end"] - s["start"]
            if total >= TARGET_SECONDS:
                break
        chosen[spk] = sorted(picks, key=lambda s: s["start"])
    return chosen


def build_references(vocals: Path, segments: list[dict], work: Path) -> dict[int, str]:
    ref_dir = work / "speakers"
    index = ref_dir / "index.json"
    if index.exists():
        return {int(k): v for k, v in json.loads(index.read_text()).items()}
    ref_dir.mkdir(exist_ok=True)
    wav, sr = audio.load(vocals, mono=True)
    wav = wav[:, 0]
    refs: dict[int, str] = {}
    picks = pick_reference_segments(segments, wav, sr)
    gap = np.zeros(int(0.2 * sr), dtype=np.float32)
    for spk in sorted({s["speaker"] for s in segments}):
        segs = picks.get(spk) or [s for s in segments if s["speaker"] == spk][:3]
        parts = []
        for s in segs:
            parts += [wav[int(s["start"] * sr): int(min(s["end"], s["start"] + 12) * sr)], gap]
        clip = np.concatenate(parts) if parts else np.zeros(int(MIN_SECONDS * sr), np.float32)
        clip = clip[: int(15 * sr)]
        peak = np.abs(clip).max() or 1.0
        path = ref_dir / f"speaker_{spk:02d}.wav"
        audio.save(path, clip / peak * 0.9, sr)
        refs[spk] = str(path)
    index.write_text(json.dumps(refs, indent=1))
    return refs
