"""Natural Hindi voices with Kokoro-82M (Apache-2.0, no Hugging Face token needed).

Used automatically when Indic Parler-TTS can't be loaded (it may need a token
and accepted terms), so dubbing never falls back straight to the more robotic
XTTS voices. Kokoro bundles its own espeak-ng for Hindi pronunciation.
"""
from __future__ import annotations

import numpy as np

FEMALE = ["hf_alpha", "hf_beta"]
MALE = ["hm_omega", "hm_psi"]
# With more characters than voices, reuse a voice at a slightly different speed.
SPEED_VARIANTS = [1.0, 0.93, 1.07]
PACE_SPEED = {"fast": 1.07, "slow": 0.93, "moderate": 1.0}


def character_voices(genders: dict[int, str]) -> dict[int, dict]:
    out, counts = {}, {"female": 0, "male": 0}
    for spk in sorted(genders):
        g = genders[spk] if genders[spk] in counts else "male"
        names = FEMALE if g == "female" else MALE
        k = counts[g]
        counts[g] += 1
        out[spk] = {"voice": names[k % len(names)],
                    "speed": SPEED_VARIANTS[(k // len(names)) % len(SPEED_VARIANTS)], "gender": g}
    return out


def line_speed(base: float, style: dict | None) -> float:
    return round(base * PACE_SPEED.get((style or {}).get("pace", "moderate"), 1.0), 3)


class KokoroHindiTTS:
    name = "kokoro"
    sample_rate = 24000
    native_speed = True  # can speak faster itself -> no robotic time-stretching

    def __init__(self, device: str, repo_id: str = "hexgrad/Kokoro-82M"):
        from kokoro import KPipeline

        self.pipe = KPipeline(lang_code="h", repo_id=repo_id, device=device)
        self.voices: dict[int, dict] = {}

    def set_voices(self, voices: dict[int, dict]) -> None:
        self.voices = voices

    def synth(self, speaker_id: int, text: str, style: dict | None = None,
              rate: float = 1.0) -> np.ndarray:
        v = self.voices.get(speaker_id) or {"voice": MALE[0], "speed": 1.0}
        parts = []
        for r in self.pipe(text, voice=v["voice"], speed=line_speed(v["speed"], style) * rate):
            if r.audio is not None:
                parts.append(r.audio.detach().cpu().float().numpy())
        return np.concatenate(parts).astype(np.float32) if parts else np.zeros(0, np.float32)
