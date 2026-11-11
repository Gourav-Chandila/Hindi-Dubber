import numpy as np

from app.pipeline import timing


def test_fits_without_change():
    plan = timing.plan_fit(2.0, 3.0, 1.35)
    assert plan.rate == 1.0 and not plan.needs_shorter


def test_speeds_up_within_limit():
    plan = timing.plan_fit(3.9, 3.0, 1.35)
    assert abs(plan.rate - 1.3) < 1e-6 and not plan.needs_shorter


def test_asks_for_shorter_when_too_long():
    plan = timing.plan_fit(6.0, 3.0, 1.35)
    assert plan.rate == 1.35 and plan.needs_shorter


def test_slot_never_overlaps_next_line():
    segs = [{"start": 0.0, "end": 1.0}, {"start": 2.5, "end": 4.0}]
    assert abs(timing.slot_for(segs, 0, 10.0) - 2.45) < 1e-6
    assert abs(timing.slot_for(segs, 1, 10.0) - 7.45) < 1e-6


def test_stretch_shortens_audio():
    sr = 24000
    x = np.sin(np.linspace(0, 2000, sr * 2)).astype(np.float32)
    y = timing._ola_stretch(x, 1.25)
    assert abs(len(y) / len(x) - 0.8) < 0.02


def test_fit_to_slot_hard_limit():
    sr = 1000
    y = timing.fit_to_slot(np.ones(5000, np.float32), sr, 2.0)
    assert len(y) == 2000 and y[-1] == 0.0
