import numpy as np
import pytest

from sstv_decoder.dsp import FrequencyBuffer


def test_fractional_phase_interpolation_does_not_manufacture_tone_at_wrap():
    rate = 16000
    history = FrequencyBuffer(rate)
    history.append(np.arange(4), np.array([0., 7900., -7900., 1800.]), np.ones(4))
    correlation = history.read_correlation([1.5], rate)
    hz = np.angle(correlation) * rate / (2 * np.pi)
    assert abs(hz[0]) == pytest.approx(8000)
    assert history.read([1.5])[0] == 0  # Linear Hz interpolation loses the phase.


def test_fractional_correlation_weights_ignore_amplitude_null():
    rate = 48000
    history = FrequencyBuffer(rate)
    history.append(np.arange(4), np.array([1900., 1900., 15000., 1900.]),
                   np.array([1., 1., 1e-9, 1.]))
    correlation = history.read_correlation([1.5], rate)
    hz = np.angle(correlation) * rate / (2 * np.pi)
    assert hz[0] == pytest.approx(1900, abs=1e-4)


def test_correlation_history_wrap_and_expired_positions():
    rate = 16000
    history = FrequencyBuffer(rate, seconds=8 / rate)
    for start in (0, 4, 8):
        history.append(np.arange(start, start + 4), np.full(4, 1900.), np.ones(4))
    actual = history.read_correlation([5.25, 9.75], rate)
    np.testing.assert_allclose(np.angle(actual) * rate / (2 * np.pi), 1900)
    with pytest.raises(ValueError):
        history.read_correlation([4.5], rate)  # Prior amplitude has expired.


def test_ordinary_fractional_phase_estimator_is_preserved():
    rate = 48000
    history = FrequencyBuffer(rate)
    history.append(np.arange(4), np.array([1700., 1800., 2100., 2200.]),
                   np.array([.5, .6, .7, .8]))
    positions = np.array([1.125, 2.75])
    expected = (history.read(positions, True) * history.read(positions-1, True)
                * np.exp(2j*np.pi*history.read(positions)/rate))
    np.testing.assert_allclose(history.read_correlation(positions,rate),expected,atol=1e-15)
