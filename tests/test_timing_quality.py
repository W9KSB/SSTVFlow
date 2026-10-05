"""Protect learned geometry without preventing a coherent clock correction."""
import numpy as np
import pytest

from sstv_decoder.timing import LineClock


def settled_clock(rate=48000):
    clock = LineClock(rate, 123.25)
    for line in range(24):
        assert clock.observe(line, 123.25 + line * clock.nominal)
    assert clock.status(24)["timing_locked"]
    return clock


def test_low_confidence_jitter_does_not_pull_a_settled_clock():
    clock = settled_clock()
    origin, period = clock.origin, clock.period
    for line, jitter in enumerate(np.random.default_rng(4).normal(0, 12, 56), 24):
        assert not clock.observe(line, 123.25 + line * 7200 + jitter, .65)
    assert clock.origin == origin and clock.period == period
    assert clock.predict(80) == pytest.approx(123.25 + 80 * 7200)


@pytest.mark.parametrize("rate", [16000, 48000])
def test_in_gate_outlier_cannot_snap_a_settled_row(rate):
    clock = settled_clock(rate)
    predicted = clock.predict(24)
    assert clock.observe(24, predicted + rate * .000250, .95)
    assert abs(clock.predict(24) - predicted) <= rate * .000010 + 1e-8


def test_jitter_reduces_timing_confidence_even_when_points_are_inliers():
    clock = LineClock(48000, 123.25)
    for line in range(64):
        clock.observe(line, 123.25 + line * 7200 + (-1)**line * 10, .7)
    status = clock.status(64)
    assert status["sync_jitter_samples"] > 9
    assert status["timing_confidence"] < .5
    assert not status["timing_locked"]


def test_coherent_clock_change_can_reacquire_after_lock():
    clock = settled_clock()
    for line in range(24, 160):
        position = 123.25 + line * 7200 + (line - 23) * 7200 * .0004
        assert clock.observe(line, position, .95)
    assert clock.status(160)["sample_clock_error_ppm"] == pytest.approx(400, abs=1)
    expected = 123.25 + 160 * 7200 + (160 - 23) * 7200 * .0004
    assert clock.predict(160) == pytest.approx(expected, abs=.5)


def test_unusable_confidence_cannot_poison_the_fit():
    clock = settled_clock()
    count = len(clock.observations)
    for confidence in (0, .1, float("nan"), float("inf")):
        assert not clock.observe(24, clock.predict(24), confidence)
    assert len(clock.observations) == count
