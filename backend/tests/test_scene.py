import numpy as np

from app.config import Settings
from app.pipeline import audio, emotion, runner
from app.pipeline.parler import character_voices
from app.pipeline.translate import make_translator

SR = 16000


def _tone(f0, sec, amp):
    t = np.arange(int(sec * SR)) / SR
    return (amp * sum(np.sin(2 * np.pi * f0 * k * t) / k for k in range(1, 5))).astype(np.float32)


def test_classify_moods_and_pace():
    loud = {"rms": 0.3, "pitch_spread": 0.2, "words_per_s": 4.0}
    soft = {"rms": 0.03, "pitch_spread": 0.05, "words_per_s": 1.5}
    calm = {"rms": 0.1, "pitch_spread": 0.05, "words_per_s": 2.5}
    assert emotion.classify(loud, 0.1, "Run!")["mood"] == "excited"
    assert emotion.classify(loud, 0.1, "Run!")["pace"] == "fast"
    assert emotion.classify(soft, 0.1, "Come here")["mood"] == "soft"
    assert emotion.classify(soft, 0.1, "Come here")["pace"] == "slow"
    assert emotion.classify(calm, 0.1, "Where is he?")["mood"] == "questioning"
    assert emotion.classify(calm, 0.1, "Okay.")["mood"] == "calm"


def test_shout_stays_louder_than_whisper_after_dubbing():
    wav = np.concatenate([_tone(150, 2, 0.6), np.zeros(SR, np.float32), _tone(150, 2, 0.08),
                          np.zeros(SR, np.float32), _tone(150, 2, 0.2)])
    segs = [{"start": 0, "end": 2, "text": "Stop right there!", "speaker": 0},
            {"start": 3, "end": 5, "text": "it is okay", "speaker": 0},
            {"start": 6, "end": 8, "text": "fine", "speaker": 0}]
    emotion.annotate(segs, wav, SR)
    assert segs[0]["style"]["loudness"] > 1.5 > segs[2]["style"]["loudness"] > segs[1]["style"]["loudness"]
    tts_line = _tone(200, 1, 0.3)  # TTS output has the same level for every line
    rms = [float(np.sqrt(np.mean(emotion.match_loudness(tts_line, s["style"]) ** 2))) for s in segs]
    assert rms[0] > rms[2] > rms[1]


def test_describe_and_distinct_parler_voices():
    d = emotion.describe("Divya", "moderate-pitched", {"mood": "soft", "pace": "slow"})
    assert d.startswith("Divya") and "softly" in d and "slow" in d
    v = character_voices({0: "female", 1: "male", 2: "male", 3: "female", 4: "male"})
    combos = {(x["name"], x["pitch"]) for x in v.values()}
    assert len(combos) == 5  # every character sounds different
    assert v[0]["name"] in ("Divya", "Rani") and v[1]["name"] in ("Rohit", "Aman")


def test_translator_falls_back_to_nllb():
    class Broken:
        def __init__(self, *a):
            raise OSError("gated repo: 401")

    class Nllb:
        def __init__(self, *a):
            pass

    t, name = make_translator("auto", "x", "y", "cpu", indictrans_cls=Broken, nllb_cls=Nllb)
    assert name == "nllb" and isinstance(t, Nllb)


def test_voice_falls_back_to_xtts_when_parler_missing(tmp_path, monkeypatch):
    import app.pipeline.tts as tts_mod

    class FakeXTTS:
        name = "xtts"
        sample_rate = 24000

        def __init__(self, *a):
            self.studio = {}

        def studio_voices(self):
            return ["Ana Florence", "Damien Black"]

        def register_studio(self, spk, voice):
            self.studio[spk] = voice

    monkeypatch.setattr(tts_mod, "HindiTTS", FakeXTTS)
    refs = {}
    for spk, f0 in ((0, 220), (1, 110)):
        p = tmp_path / f"s{spk}.wav"
        audio.save(p, _tone(f0, 2, 0.3), SR)
        refs[spk] = str(p)
    stats = {}
    tts = runner._load_tts(refs, Settings(), "cpu", stats, "studio")  # parler_tts not installed here
    assert stats["tts_engine"] == "xtts-studio" and tts.studio == {0: "Ana Florence", 1: "Damien Black"}


def test_kokoro_voices_distinct_and_pace():
    from app.pipeline import kokoro_tts

    v = kokoro_tts.character_voices({0: "female", 1: "male", 2: "male", 3: "female", 4: "male"})
    assert len({(x["voice"], x["speed"]) for x in v.values()}) == 5
    assert v[0]["voice"].startswith("hf_") and v[1]["voice"].startswith("hm_")
    assert kokoro_tts.line_speed(1.0, {"pace": "fast"}) > 1.0 > kokoro_tts.line_speed(1.0, {"pace": "slow"})


def test_kokoro_used_when_parler_missing(tmp_path, monkeypatch):
    from app.pipeline import kokoro_tts

    class FakeKokoro:
        name = "kokoro"
        sample_rate = 24000

        def __init__(self, device):
            self.voices = {}

        def set_voices(self, v):
            self.voices = v

    monkeypatch.setattr(kokoro_tts, "KokoroHindiTTS", FakeKokoro)
    p = tmp_path / "s0.wav"
    audio.save(p, _tone(220, 2, 0.3), SR)
    stats = {}
    tts = runner._load_tts({0: str(p)}, Settings(), "cpu", stats, "studio")
    assert stats["tts_engine"] == "kokoro" and tts.voices[0]["voice"].startswith("hf_")
