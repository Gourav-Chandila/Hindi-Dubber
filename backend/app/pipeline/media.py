"""ffmpeg / ffprobe helpers. The video stream is never re-encoded."""
from __future__ import annotations

import json
import subprocess
from pathlib import Path


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


def extract_audio(video: Path, out: Path, rate: int, channels: int) -> Path:
    run(["ffmpeg", "-y", "-v", "error", "-i", str(video), "-vn", "-map", "0:a:0",
         "-ac", str(channels), "-ar", str(rate), "-c:a", "pcm_s16le", str(out)])
    return out


def mux(video: Path, dubbed_audio: Path, out: Path, keep_original: bool = True) -> Path:
    """Copy the original video stream bit-for-bit and add the Hindi track
    (default) plus, optionally, the original English track."""
    cmd = ["ffmpeg", "-y", "-v", "error", "-i", str(video), "-i", str(dubbed_audio),
           "-map", "0:v:0", "-map", "1:a:0"]
    if keep_original:
        cmd += ["-map", "0:a:0?"]
    cmd += ["-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-metadata:s:a:0", "language=hin", "-metadata:s:a:0", "title=Hindi",
            "-disposition:a:0", "default"]
    if keep_original:
        cmd += ["-metadata:s:a:1", "language=eng", "-metadata:s:a:1", "title=English",
                "-disposition:a:1", "0"]
    cmd += ["-movflags", "+faststart", str(out)]
    run(cmd)
    return out


def video_stream_md5(path: Path) -> str:
    """MD5 of the raw (still-encoded) video packets; equal in & out => untouched."""
    out = run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0",
               "-c", "copy", "-f", "md5", "-"])
    return out.strip()
