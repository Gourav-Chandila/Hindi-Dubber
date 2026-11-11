"""English -> Hindi translation with Meta NLLB-200 (free, runs locally)."""
from __future__ import annotations

import json
from pathlib import Path


class Translator:
    def __init__(self, model_name: str, device: str):
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        self.tok = AutoTokenizer.from_pretrained(model_name, src_lang="eng_Latn")
        self.model = AutoModelForSeq2SeqLM.from_pretrained(model_name).to(device).eval()
        self.device = device
        self.hin = self.tok.convert_tokens_to_ids("hin_Deva")

    def __call__(self, texts: list[str], shorter: bool = False, batch: int = 16) -> list[str]:
        import torch

        out: list[str] = []
        for i in range(0, len(texts), batch):
            chunk = texts[i:i + batch]
            enc = self.tok(chunk, return_tensors="pt", padding=True, truncation=True,
                           max_length=400).to(self.device)
            with torch.no_grad():
                gen = self.model.generate(
                    **enc, forced_bos_token_id=self.hin, num_beams=4,
                    max_new_tokens=400,
                    # A lower length penalty favours shorter Hindi when a line
                    # does not fit its time slot.
                    length_penalty=0.5 if shorter else 1.0,
                )
            out += self.tok.batch_decode(gen, skip_special_tokens=True)
        return [t.strip() for t in out]


def translate_segments(segments: list[dict], work: Path, translator: Translator,
                       progress=lambda f: None, batch: int = 16) -> list[dict]:
    cache = work / "translated.json"
    if cache.exists():
        return json.loads(cache.read_text())
    result = []
    for i in range(0, len(segments), batch):
        chunk = segments[i:i + batch]
        hindi = translator([s["text"] for s in chunk], batch=batch)
        result += [dict(s, hi=h) for s, h in zip(chunk, hindi, strict=True)]
        progress(min(1.0, (i + batch) / max(1, len(segments))))
    cache.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    return result
