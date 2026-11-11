"""Orchestrates the full dubbing pipeline. Every stage writes its result to the
job's work dir, so a crashed/restarted job resumes from the last finished stage."""
from __future__ import annotations

import gc
import json
import logging
import time
from collections.abc import Callable
from pathlib import Path

import numpy as np

from ..config import Settings
from . import audio, media, timing
from .hindi_numbers import numbers_to_hindi as speakable
from .mix import mix

log = logging.getLogger("hindidub.pipeline")

MIX_SR = 44100

# (stage, weight in overall progress)
STAGES = [
    ("extract", 0.02), ("separate", 0.20), ("transcribe", 0.18), ("diarize", 0.07),
    ("references", 0.02), ("translate", 0.08), ("synthesize", 0.38), ("mix", 0.05),
]

Progress = Callable[[str, float], None]  # (stage, overall 0..1)


class PipelineError(RuntimeError):
    pass


def _overall(stage: str, frac: float) -> float:
    done = 0.0
    for name, w in STAGES:
        if name == stage:
            return round(done + w * max(0.0, min(1.0, frac)), 4)
        done += w
    return done


def run_pipeline(video: Path, work: Path, out_path: Path, cfg: Settings,
                 report: Progress) -> dict:
    work.mkdir(parents=True, exist_ok=True)
    device = cfg.resolved_device()
    stats: dict = {"device": device}

    def stage(name: str):
        t0 = time.time()
        report(name, _overall(name, 0.0))
        return lambda f: report(name, _overall(name, f)), t0

    # 1. extract -----------------------------------------------------------
    p, t0 = stage("extract")
    if not media.has_stream(video, "audio"):
        raise PipelineError("This video has no audio track to dub.")
    if not media.has_stream(video, "video"):
        raise PipelineError("No video stream found in the uploaded file.")
    total = media.duration(video)
    stats["duration_s"] = round(total, 2)
    orig = work / "orig.wav"
    if not orig.exists():
        media.extract_audio(video, orig, MIX_SR, 2)
    orig16 = work / "orig16k.wav"
    if not orig16.exists():
        media.extract_audio(video, orig16, 16000, 1)
    p(1.0)
    log.info("extract done in %.1fs", time.time() - t0)

    # 2. separate ------------------------------------------------------------
    p, t0 = stage("separate")
    if cfg.separate_music:
        vocals, background = _separate(orig, work, cfg, device, p)
        separated = True
    else:
        vocals, background, separated = orig, orig, False
    vocals16 = work / "vocals16k.wav"
    if not vocals16.exists():
        v, sr = audio.load(vocals, mono=True)
        audio.save(vocals16, audio.resample(v, sr, 16000), 16000)
    p(1.0)
    log.info("separate done in %.1fs", time.time() - t0)

    # 3. transcribe ------------------------------------------------------------
    p, t0 = stage("transcribe")
    from .transcribe import transcribe

    # Transcribe the clean vocals: far fewer hallucinations on music.
    segments = transcribe(vocals16, work, cfg.resolved_whisper_model(), device, p, total)
    stats["segments"] = len(segments)
    gc.collect()
    log.info("transcribe: %d segments in %.1fs", len(segments), time.time() - t0)

    if not segments:
        p, _ = stage("mix")
        media.mux(video, orig, out_path)
        stats["note"] = "No English speech detected; original audio kept."
        p(1.0)
        return stats

    # 4. diarize ---------------------------------------------------------------
    p, t0 = stage("diarize")
    from .diarize import diarize

    segments = diarize(vocals16, segments, work, device, cfg.speaker_threshold, cfg.max_speakers)
    speakers = sorted({s["speaker"] for s in segments})
    stats["speakers"] = len(speakers)
    p(1.0)
    gc.collect()
    log.info("diarize: %d speakers in %.1fs", len(speakers), time.time() - t0)

    # 5. references -----------------------------------------------------------
    p, _ = stage("references")
    from .references import build_references

    refs = build_references(vocals, segments, work)
    p(1.0)

    # 6. translate ------------------------------------------------------------
    p, t0 = stage("translate")
    from .translate import Translator, translate_segments

    translator = Translator(cfg.translate_model, device)
    segments = translate_segments(segments, work, translator, p)
    log.info("translate done in %.1fs", time.time() - t0)

    # 7. synthesize -----------------------------------------------------------
    p, t0 = stage("synthesize")
    dub = _synthesize(segments, refs, work, cfg, device, translator, total, p, stats)
    del translator
    gc.collect()
    log.info("synthesize done in %.1fs", time.time() - t0)

    # 8. mix + mux ------------------------------------------------------------
    p, _ = stage("mix")
    bg, sr = audio.load(background)
    final = mix(dub, bg, segments, sr, separated)
    dubbed_wav = work / "dubbed.wav"
    audio.save(dubbed_wav, final, sr)
    p(0.5)
    _write_srt(segments, out_path.with_suffix(".hi.srt"))
    media.mux(video, dubbed_wav, out_path)
    p(1.0)
    return stats


def _separate(orig: Path, work: Path, cfg: Settings, device: str, p) -> tuple[Path, Path]:
    from .separate import separate

    return separate(orig, work, cfg.chunk_seconds, device, p)


def _synthesize(segments, refs, work: Path, cfg: Settings, device: str, translator,
                total: float, p, stats: dict) -> np.ndarray:
    from .tts import HindiTTS

    tts = HindiTTS(cfg.tts_model, device)
    for spk, ref in refs.items():
        tts.register(spk, ref)
    seg_dir = work / "tts"
    seg_dir.mkdir(exist_ok=True)
    track = np.zeros(int(total * MIX_SR) + MIX_SR, dtype=np.float32)
    shortened = trimmed = failed = 0
    from .mix import place

    for i, s in enumerate(segments):
        cached = seg_dir / f"seg_{i:05d}.wav"
        if cached.exists():
            clip, _ = audio.load(cached, mono=True)
            clip = clip[:, 0]
        else:
            slot = timing.slot_for(segments, i, total)
            try:
                clip = _render_line(tts, s, slot, cfg, translator)
            except Exception:  # noqa: BLE001 - one bad line must not sink a long video
                failed += 1
                log.exception("line %d failed, leaving it silent: %r", i, s.get("hi"))
                if failed > max(3, len(segments) // 5):
                    raise
                continue
            if clip is None:
                continue
            audio.save(cached, clip, MIX_SR)
        place(track, clip, int(s["start"] * MIX_SR))
        if s.get("shortened"):
            shortened += 1
        if s.get("trimmed"):
            trimmed += 1
        p((i + 1) / len(segments))
    stats["lines_shortened"] = shortened
    stats["lines_trimmed"] = trimmed
    stats["lines_failed"] = failed
    del tts
    return track


def _render_line(tts, s: dict, slot: float, cfg: Settings, translator) -> np.ndarray | None:
    text = (s.get("hi") or "").strip()
    if not text or slot <= 0.1:
        return None
    wav = audio.resample(tts.synth(s["speaker"], speakable(text)), tts.sample_rate, MIX_SR)
    plan = timing.plan_fit(len(wav) / MIX_SR, slot, cfg.max_stretch)
    if plan.needs_shorter:
        short = translator([s["text"]], shorter=True)[0]
        if short and short != text:
            wav2 = audio.resample(tts.synth(s["speaker"], speakable(short)), tts.sample_rate, MIX_SR)
            if len(wav2) < len(wav):
                wav, s["hi"], s["shortened"] = wav2, short, True
                plan = timing.plan_fit(len(wav) / MIX_SR, slot, cfg.max_stretch)
    wav = timing.time_stretch(wav, MIX_SR, plan.rate)
    fitted = timing.fit_to_slot(wav, MIX_SR, slot)
    if len(fitted) < len(wav):
        s["trimmed"] = True
    return fitted


def _fmt(t: float) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    sec, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{sec:02d},{ms:03d}"


def _write_srt(segments: list[dict], path: Path) -> None:
    lines = []
    for n, s in enumerate(segments, 1):
        lines += [str(n), f"{_fmt(s['start'])} --> {_fmt(s['end'])}", s.get("hi", ""), ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    (path.parent / "segments.json").write_text(json.dumps(segments, ensure_ascii=False, indent=1))
