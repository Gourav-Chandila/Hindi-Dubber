"""Hindi speech synthesis with Coqui XTTS-v2 cross-lingual voice cloning.

Each speaker id is always synthesised from its own fixed reference clip and
pre-computed conditioning latents, so a character's Hindi voice is identical
throughout the video.
"""
from __future__ import annotations

import os

import numpy as np

os.environ.setdefault("COQUI_TOS_AGREED", "1")  # non-commercial CPML licence


class Speaker:
    def __init__(self, gpt_cond_latent, speaker_embedding):
        self.gpt_cond_latent = gpt_cond_latent
        self.speaker_embedding = speaker_embedding


class HindiTTS:
    sample_rate = 24000

    def __init__(self, model_name: str, device: str):
        from TTS.api import TTS

        self.api = TTS(model_name).to(device)
        self.model = self.api.synthesizer.tts_model
        self.speakers: dict[int, Speaker] = {}

    def register(self, speaker_id: int, ref_wav: str) -> None:
        if speaker_id in self.speakers:
            return
        lat, emb = self.model.get_conditioning_latents(audio_path=[ref_wav])
        self.speakers[speaker_id] = Speaker(lat, emb)

    def synth(self, speaker_id: int, text: str, speed: float = 1.0) -> np.ndarray:
        spk = self.speakers[speaker_id]
        out = self.model.inference(
            text, "hi", spk.gpt_cond_latent, spk.speaker_embedding,
            temperature=0.65,           # lower = more stable, consistent timbre
            repetition_penalty=5.0,
            speed=speed,
            enable_text_splitting=True,
        )
        return np.asarray(out["wav"], dtype=np.float32)
