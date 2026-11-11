"""ffmpeg / ffprobe helpers. The video stream is never re-encoded."""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ENGLISH_TAGS = {"eng", "en", "english"}


class MediaError(RuntimeError):
    pass


def run(cmd: list[str]) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise MediaError(f"{cmd[0]} failed ({proc.returncode}): {proc.stderr[-2000:]}")
    return proc.stdout


def probe(path: Path) -> dict:
    out = run(["ffprobe", "-v", "error", "-print_format", "json",
               "-show_format", "-show_streams", str(path)])
    return json.loads(out)


def duration(path: Path) -> float:
    return float(probe(path)["format"]["duration"])


def has_stream(path: Path, kind: str) -> bool:
    return any(s.get("codec_type") == kind for s in probe(path).get("streams", []))


def audio_streams(path: Path) -> list[dict]:
    """Audio tracks in order: [{index, language, title, channels}]."""
    out = []
    streams = [s for s in probe(path).get("streams", []) if s.get("codec_type") == "audio"]
    for k, s in enumerate(streams):
        tags = {str(key).lower(): str(v) for key, v in (s.get("tags") or {}).items()}
        out.append({"index": k, "language": tags.get("language", "").strip().lower(),
                    "title": tags.get("title", "").strip(), "channels": s.get("channels", 0)})
    return out


def tagged_english(streams: list[dict]) -> int | None:
    """Index of the track tagged/titled English, if any."""
    for s in streams:
        if s["language"] in ENGLISH_TAGS:
            return s["index"]
    for s in streams:
        if re.search(r"\b(english|eng)\b", s["title"].lower()):
            return s["index"]
    return None


def extract_audio(video: Path, out: Path, rate: int, channels: int, stream: int = 0,
                  start: float | None = None, seconds: float | None = None) -> Path:
    cmd = ["ffmpeg", "-y", "-v", "error"]
    if start is not None:
        cmd += ["-ss", f"{start:.2f}"]
    cmd += ["-i", str(video), "-vn", "-map", f"0:a:{stream}"]
    if seconds is not None:
        cmd += ["-t", f"{seconds:.2f}"]
    cmd += ["-ac", str(channels), "-ar", str(rate), "-c:a", "pcm_s16le", str(out)]
    run(cmd)
    return out


def mux(video: Path, dubbed_audio: Path, out: Path, source_stream: int = 0) -> Path:
    """Copy the video stream bit-for-bit; Hindi becomes audio track 1 (default)
    and EVERY original audio track (English, German, ...) is kept after it
    with its language tag. Original tracks are re-encoded to AAC so any
    source codec (AC3, DTS, Opus...) fits in MP4."""
    originals = audio_streams(video)
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(video), "-i", str(dubbed_audio),
           "-map", "0:v:0", "-map", "1:a:0", "-map", "0:a?",
           "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
           "-metadata:s:a:0", "language=hin", "-metadata:s:a:0", "title=Hindi",
           "-disposition:a:0", "default"]
    for s in originals:
        o = 1 + s["index"]  # output position of this original track
        cmd += [f"-disposition:a:{o}", "0"]
        if s["index"] == source_stream and s["language"] not in ENGLISH_TAGS:
            cmd += [f"-metadata:s:a:{o}", "language=eng", f"-metadata:s:a:{o}", "title=English"]
    cmd += ["-movflags", "+faststart", str(out)]
    run(cmd)
    return out


def video_stream_md5(path: Path) -> str:
    """MD5 of the raw (still-encoded) video packets; equal in & out => untouched."""
    out = run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0",
               "-c", "copy", "-f", "md5", "-"])
    return out.strip()
