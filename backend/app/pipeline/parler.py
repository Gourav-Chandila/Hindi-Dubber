"""Natural Hindi speech with AI4Bharat Indic Parler-TTS.

Trained on Hindi, so pronunciation is far more natural than XTTS. Each
character gets a fixed named Hindi speaker plus a fixed pitch, and a fixed
random seed, so the voice stays the same all video; the line's mood/pace
(from emotion.py) goes into the voice description.
"""
from __future__ import annotations

import numpy as np

from .emotion import describe

# Named Hindi speakers of Indic Parler-TTS; combined with different pitches so
# that more characters still sound distinct.
FEMALE = ["Divya", "Rani"]
MALE = ["Rohit", "Aman"]
PITCHES = ["moderate-pitched", "slightly low-pitched", "slightly high-pitched"]


def character_voices(genders: dict[int, str]) -> dict[int, dict]:
    """speaker id -> {"name", "pitch", "seed"}; distinct for every character."""
    out, counts = {}, {"female": 0, "male": 0}
    for spk in sorted(genders):
        g = genders[spk] if genders[spk] in counts else "male"
        names = FEMALE if g == "female" else MALE
        k = counts[g]
        counts[g] += 1
        out[spk] = {"name": names[k % len(names)],
                    "pitch": PITCHES[(k // len(names)) % len(PITCHES)],
                    "seed": 1000 + spk, "gender": g}
    return out


class ParlerHindiTTS:
    name = "indic-parler-tts"

    def __init__(self, model_name: str, device: str):
        import torch
        from parler_tts import ParlerTTSForConditionalGeneration
        from transformers import AutoTokenizer

        self.torch = torch
        self.device = device
        self.model = ParlerTTSForConditionalGeneration.from_pretrained(model_name).to(device).eval()
        self.tok = AutoTokenizer.from_pretrained(model_name)
        self.desc_tok = AutoTokenizer.from_pretrained(self.model.config.text_encoder._name_or_path)
        self.sample_rate = int(self.model.config.sampling_rate)
        self.voices: dict[int, dict] = {}

    def set_voices(self, voices: dict[int, dict]) -> None:
        self.voices = voices

    def synth(self, speaker_id: int, text: str, style: dict | None = None) -> np.ndarray:
        v = self.voices.get(speaker_id) or {"name": "Rohit", "pitch": PITCHES[0], "seed": 1000}
        desc = describe(v["name"], v["pitch"], style)
        d = self.desc_tok(desc, return_tensors="pt").to(self.device)
        p = self.tok(text, return_tensors="pt").to(self.device)
        self.torch.manual_seed(v["seed"])  # same character -> same timbre every line
        with self.torch.no_grad():
            gen = self.model.generate(input_ids=d.input_ids, attention_mask=d.attention_mask,
                                      prompt_input_ids=p.input_ids,
                                      prompt_attention_mask=p.attention_mask)
        return gen.cpu().float().numpy().squeeze().astype(np.float32)
