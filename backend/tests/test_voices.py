import numpy as np

from app.pipeline.diarize import cluster_embeddings
from app.pipeline.voices import FEMALE_VOICES, MALE_VOICES, assign_voices, estimate_pitch

SR = 16000


def _voice(f0, seconds=2.0):
    t = np.arange(int(seconds * SR)) / SR
    # harmonic-rich "voice" so autocorrelation behaves like speech
    return sum(np.sin(2 * np.pi * f0 * k * t) / k for k in range(1, 6)).astype(np.float32) * 0.3


def test_pitch_estimate():
    assert abs(estimate_pitch(_voice(115), SR) - 115) < 8
    assert abs(estimate_pitch(_voice(220), SR) - 220) < 12
    assert estimate_pitch(np.zeros(SR, np.float32), SR) == 0.0


def test_each_character_gets_a_distinct_gender_matched_voice():
    available = FEMALE_VOICES + MALE_VOICES + ["Some Other"]
    v = assign_voices({0: 210.0, 1: 110.0, 2: 125.0, 3: 230.0}, available)
    assert v[0]["gender"] == "female" and v[0]["voice"] in FEMALE_VOICES
    assert v[1]["gender"] == "male" and v[1]["voice"] in MALE_VOICES
    assert v[2]["voice"] in MALE_VOICES and v[3]["voice"] in FEMALE_VOICES
    assert len({x["voice"] for x in v.values()}) == 4  # all different


def test_assignment_survives_missing_voice_names():
    v = assign_voices({0: 200.0, 1: 100.0}, ["Alpha", "Beta"])
    assert {v[0]["voice"], v[1]["voice"]} == {"Alpha", "Beta"}


def test_forced_number_of_characters():
    rng = np.random.default_rng(3)
    centres = [rng.standard_normal(192) for _ in range(3)]
    emb = np.vstack([c + 0.05 * rng.standard_normal((10, 192)) for c in centres])
    # threshold so strict that auto mode would split everyone apart...
    auto = cluster_embeddings(emb, threshold=0.9999, max_speakers=20)
    assert len(set(auto)) > 3
    # ...but the user said "3 characters"
    forced = cluster_embeddings(emb, threshold=0.9999, max_speakers=20, n_speakers=3)
    assert len(set(forced)) == 3
