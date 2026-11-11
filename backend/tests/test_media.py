"""End-to-end check that muxing never touches the video stream."""
import shutil
import subprocess

import numpy as np
import pytest

from app.pipeline import audio, media

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg missing")


def _make_video(path):
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10",
         "-f", "lavfi", "-i", "sine=frequency=440:sample_rate=44100", "-t", "3",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(path)],
        check=True,
    )


def test_mux_keeps_video_bit_exact(tmp_path):
    src = tmp_path / "in.mp4"
    _make_video(src)
    wav = tmp_path / "a.wav"
    media.extract_audio(src, wav, 44100, 2)
    data, sr = audio.load(wav)
    audio.save(tmp_path / "dub.wav", np.zeros_like(data), sr)
    out = tmp_path / "out.mp4"
    media.mux(src, tmp_path / "dub.wav", out)

    assert media.video_stream_md5(src) == media.video_stream_md5(out)
    streams = media.probe(out)["streams"]
    audio_streams = [s for s in streams if s["codec_type"] == "audio"]
    assert len(audio_streams) == 2
    assert audio_streams[0]["tags"]["language"] == "hin"
    assert audio_streams[1]["tags"]["language"] == "eng"
    assert abs(media.duration(out) - media.duration(src)) < 0.2
