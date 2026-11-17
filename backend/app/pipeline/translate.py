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


class IndicTrans2Translator:
    """AI4Bharat IndicTrans2 (en -> hi): trained for Indian languages, gives more
    natural Hindi than NLLB. Same call signature as Translator."""

    name = "indictrans2"

    def __init__(self, model_name: str, device: str):
        import torch
        from IndicTransToolkit import IndicProcessor
        from transformers import AutoModelForSeq2SeqLM, AutoTokenizer

        self.tok = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
        dtype = torch.float16 if device == "cuda" else torch.float32
        self.model = AutoModelForSeq2SeqLM.from_pretrained(
            model_name, trust_remote_code=True, torch_dtype=dtype).to(device).eval()
        self.ip = IndicProcessor(inference=True)
        self.device = device
        self.use_cache = True

    def __call__(self, texts: list[str], shorter: bool = False, batch: int = 16) -> list[str]:
        import torch

        out: list[str] = []
        for i in range(0, len(texts), batch):
            chunk = self.ip.preprocess_batch(texts[i:i + batch], src_lang="eng_Latn",
                                             tgt_lang="hin_Deva")
            enc = self.tok(chunk, truncation=True, padding="longest", max_length=256,
                           return_tensors="pt", return_attention_mask=True).to(self.device)
            kwargs = dict(min_length=0, max_length=256, num_beams=5, num_return_sequences=1,
                          length_penalty=0.5 if shorter else 1.0)
            with torch.no_grad():
                try:
                    gen = self.model.generate(**enc, use_cache=self.use_cache, **kwargs)
                except Exception:  # noqa: BLE001 - some transformers versions break the cache
                    if not self.use_cache:
                        raise
                    self.use_cache = False
                    gen = self.model.generate(**enc, use_cache=False, **kwargs)
            decoded = self.tok.batch_decode(gen.detach().cpu().tolist(), skip_special_tokens=True,
                                            clean_up_tokenization_spaces=True)
            out += self.ip.postprocess_batch(decoded, lang="hin_Deva")
        return [t.strip() for t in out]


def make_translator(engine: str, indictrans_model: str, nllb_model: str, device: str,
                    log=None, indictrans_cls=None, nllb_cls=None):
    """IndicTrans2 when available (better Hindi), else NLLB. Never fails just
    because the better model can't be downloaded (e.g. needs a HF token)."""
    indictrans_cls = indictrans_cls or IndicTrans2Translator
    nllb_cls = nllb_cls or Translator
    if engine in ("auto", "indictrans2"):
        try:
            return indictrans_cls(indictrans_model, device), "indictrans2"
        except Exception as exc:  # noqa: BLE001
            if log:
                log.warning("IndicTrans2 unavailable (%s); using NLLB. If the model is gated, "
                            "add a Hugging Face token (HF_TOKEN) and accept its terms.", exc)
    return nllb_cls(nllb_model, device), "nllb"


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
