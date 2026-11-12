"""D: a line that needs speed-up first gets a shorter translation."""
import numpy as np

from app.config import Settings
from app.pipeline import runner


class FakeTTS:
    sample_rate = runner.MIX_SR

    def synth(self, speaker, text):  # 0.1 s of audio per character
        return np.ones(int(len(text) * 0.1 * self.sample_rate), np.float32) * 0.1


def test_shorter_translation_used_before_speeding_up():
    calls = []

    def translator(texts, shorter=False):
        calls.append(shorter)
        return ["छोटा वाक्य"]  # 10 chars -> 1.0 s

    seg = {"speaker": 0, "text": "A long English line", "hi": "यह एक लंबा वाक्य है"}  # 19 chars -> 1.9 s
    out = runner._render_line(FakeTTS(), seg, slot=1.7, cfg=Settings(), translator=translator)
    assert calls == [True] and seg.get("shortened")  # 1.9/1.7 = 1.12x > 1.08 -> shortened
    assert len(out) / runner.MIX_SR <= 1.7


def test_short_enough_line_is_left_alone():
    def translator(texts, shorter=False):
        raise AssertionError("should not ask for a shorter line")

    seg = {"speaker": 0, "text": "Hi", "hi": "नमस्ते"}
    out = runner._render_line(FakeTTS(), seg, slot=2.0, cfg=Settings(), translator=translator)
    assert abs(len(out) / runner.MIX_SR - 0.6) < 0.01


def test_dubbing_continues_when_music_separation_fails(tmp_path):
    import subprocess

    def broken_separator(*args, **kwargs):
        raise subprocess.CalledProcessError(1, ["demucs"], stderr=b"SSL: CERTIFICATE_VERIFY_FAILED")

    orig = tmp_path / "orig.wav"
    vocals, bg, separated, note = runner.separate_or_fallback(
        orig, tmp_path, Settings(), "cpu", lambda f: None, separator=broken_separator)
    assert (vocals, bg, separated) == (orig, orig, False) and note.startswith("skipped")
