import numpy as np

from app.pipeline.separate import needs_model


def test_silence_and_short_chunks_skip_demucs():
    sr = 44100
    assert not needs_model(np.zeros((sr * 5, 2), np.float32), sr)
    assert not needs_model(np.random.default_rng(0).standard_normal((sr // 2, 2)).astype(np.float32), sr)
    assert needs_model(np.random.default_rng(0).standard_normal((sr * 5, 2)).astype(np.float32) * 0.1, sr)
