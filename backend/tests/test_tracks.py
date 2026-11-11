"""Multi-audio files (e.g. Telegram: German + English): pick English, keep all."""
import shutil
import subprocess

import numpy as np
import pytest

from app.config import Settings
from app.pipeline import audio, media
from app.pipeline.runner import choose_english_track

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg missing")


def _video(path, tags):
    """Video with one sine track per entry; freq 300, 600, 900 Hz..."""
    cmd = ["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "testsrc=size=160x120:rate=10"]
    for k in range(len(tags)):
        cmd += ["-f", "lavfi", "-i", f"sine=frequency={300 * (k + 1)}:sample_rate=44100"]
    cmd += ["-t", "3", "-map", "0:v"]
    for k in range(len(tags)):
        cmd += ["-map", f"{k + 1}:a"]
    cmd += ["-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac"]
    for k, lang in enumerate(tags):
        if lang:
            cmd += [f"-metadata:s:a:{k}", f"language={lang}"]
    cmd += [str(path)]
    subprocess.run(cmd, check=True)


def _dominant_hz(wav):
    x, sr = audio.load(wav, mono=True)
    spec = np.abs(np.fft.rfft(x[:, 0]))
    return np.argmax(spec) * sr / len(x)


def test_picks_tagged_english_even_if_not_first(tmp_path):
    v = tmp_path / "multi.mkv"
    _video(v, ["ger", "eng", "fre"])
    idx, how = choose_english_track(v, tmp_path, Settings(), "cpu", 3.0)
    assert idx == 1 and how == "tagged English"
    wav = media.extract_audio(v, tmp_path / "a.wav", 44100, 1, stream=idx)
    assert abs(_dominant_hz(wav) - 600) < 20  # really the English (2nd) track


def test_untagged_tracks_use_language_detection(tmp_path):
    v = tmp_path / "untagged.mkv"
    _video(v, [None, None])
    idx, how = choose_english_track(v, tmp_path, Settings(), "cpu", 3.0,
                                    scorer=lambda clips: [0.05, 0.93])
    assert idx == 1 and how.startswith("detected English")


def test_mux_keeps_all_tracks_and_video(tmp_path):
    v = tmp_path / "multi.mkv"
    _video(v, ["ger", "eng"])
    dub = tmp_path / "dub.wav"
    audio.save(dub, np.zeros((44100 * 3, 2), np.float32), 44100)
    out = tmp_path / "out.mp4"
    media.mux(v, dub, out, source_stream=1)
    langs = [s["language"] for s in media.audio_streams(out)]
    assert langs == ["hin", "ger", "eng"]
    assert media.video_stream_md5(v) == media.video_stream_md5(out)
