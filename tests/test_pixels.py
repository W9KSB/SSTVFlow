"""Local raw PCM fits isolate neighboring pixel frequencies."""

import numpy as np
import pytest

from sstv_decoder.pixels import fit_pixel_frequencies


@pytest.mark.parametrize("rate,count", [(16000, 3), (16000, 4), (48000, 8),
                                        (48000, 13), (48000, 14)])
def test_clean_short_windows(rate, count):
    rng = np.random.default_rng(8)
    frequencies = rng.uniform(1500, 2300, 400)
    phases = rng.uniform(-np.pi, np.pi, 400)
    samples = .8 * np.sin(2 * np.pi * frequencies[:, None]
                          * np.arange(count) / rate + phases[:, None])
    actual, residual, confidence = fit_pixel_frequencies(samples, rate)
    np.testing.assert_allclose(actual, frequencies, atol=.06)
    assert np.max(residual) < 1e-9
    np.testing.assert_allclose(confidence, 1 - residual)


def test_sharp_continuous_phase_alternating_pixels():
    rate, count = 48000, 13
    frequencies = np.tile([1500., 2300.], 320)
    instantaneous = np.repeat(frequencies, count)
    samples = .8 * np.sin(np.cumsum(instantaneous) * 2 * np.pi / rate)
    actual, residual, _ = fit_pixel_frequencies(samples.reshape(-1, count), rate)
    np.testing.assert_allclose(actual, frequencies, atol=.06)
    assert np.max(residual) < 1e-9


def test_offset_irregular_times_and_nonuniform_candidates():
    rate = 48000
    frequencies = np.array([1633.42, 2018.11, 2272.78])
    times = np.array([0., 1, 2.2, 3.3, 4.1, 5.2, 6.]) / rate
    times = np.broadcast_to(times, (3, len(times))) + np.array([0., 2., 4.])[:, None]
    samples = .7 * np.sin(2 * np.pi * frequencies[:, None] * times + .6)
    candidates = np.sort(np.r_[np.arange(1400., 2401., 10), 1627.])
    actual, _, _ = fit_pixel_frequencies(samples, rate, sample_times=times,
                                         candidate_frequencies=candidates)
    np.testing.assert_allclose(actual, frequencies, atol=.06)
    offset = 73.4
    shifted = .7 * np.sin(2 * np.pi * (frequencies + offset)[:, None]
                          * np.arange(13) / rate + .6)
    actual, _, _ = fit_pixel_frequencies(shifted, rate, offset_hz=offset)
    np.testing.assert_allclose(actual, frequencies + offset, atol=.06)


def test_silence_and_empty_batch():
    actual, residual, confidence = fit_pixel_frequencies(np.zeros((3, 4)), 16000)
    np.testing.assert_array_equal(actual, 1900)
    np.testing.assert_array_equal(residual, 1)
    np.testing.assert_array_equal(confidence, 0)
    assert all(result.shape == (0,) for result in
               fit_pixel_frequencies(np.empty((0, 4)), 16000))


def test_range_boundary_and_nonsinusoidal_residual():
    rate = 16000
    samples = np.sin(2 * np.pi * 2500 * np.arange(12) / rate)[None, :]
    actual, residual, _ = fit_pixel_frequencies(samples, rate)
    np.testing.assert_array_equal(actual, [2400])
    assert 0 < residual[0] < 1


@pytest.mark.parametrize("kwargs", [
    {"samples": [1, 2, 3]}, {"samples": [[1, 2]]},
    {"samples": [[1j, 2j, 3j]]},
    {"samples": [[1, np.nan, 3]]}, {"sample_rate": 0},
    {"offset_hz": np.inf}, {"candidate_frequencies": [1400, 1400, 1500]},
    {"candidate_frequencies": [0, 1400, 1500]},
    {"candidate_frequencies": [1400, 1500, 8000]},
    {"sample_times": [0, 1, 1, 2]}, {"sample_times": [0, 1]},
])
def test_rejects_invalid_inputs(kwargs):
    arguments = {"samples": np.ones((2, 4)), "sample_rate": 16000}
    arguments.update(kwargs)
    with pytest.raises(ValueError):
        fit_pixel_frequencies(**arguments)
