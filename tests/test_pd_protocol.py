"""PD120 geometry and independently transmitted channel/color fixtures."""
import numpy as np
import pytest
from scipy.signal import hilbert

from pd_signals import generate_pd120, make_pd_test_image
from sstv_decoder.color import frequency_to_byte, ycrcb_to_rgb
from sstv_decoder.pd120 import (
    WIDTH, HEIGHT, PAIRS, VIS_CODE, PAIR_SECONDS,
    channel_layout, extract_first, extract_second,
)


@pytest.mark.parametrize("rate", [16000, 44100, 48000])
def test_pd_geometry_fractional_timing(rate):
    assert (WIDTH, HEIGHT, PAIRS, VIS_CODE) == (640, 496, 248, 95)
    assert PAIR_SECONDS == pytest.approx(.508480)
    start = 123.25
    period = .508480 * rate * 1.0007
    layout = channel_layout(rate, start, period, horizontal_ms=.125)
    for name, seconds in (("y_first", .022080), ("cr", .143680),
                          ("cb", .265280), ("y_second", .386880)):
        position, duration = layout[name]
        assert position == pytest.approx(start + seconds * rate * 1.0007 + .000125 * rate)
        assert duration == pytest.approx(.121600 * rate * 1.0007)
    assert sum(layout["y_second"]) == pytest.approx(start + period + .000125 * rate)


@pytest.mark.parametrize("rate,start,period,horizontal", [
    (0, 0, 1, 0), (48000, 0, -1, 0), (48000, np.nan, 1, 0),
    (48000, 0, np.inf, 0), (48000, 0, 1, np.nan),
])
def test_pd_geometry_rejects_invalid_timing(rate, start, period, horizontal):
    with pytest.raises(ValueError):
        channel_layout(rate, start, period, horizontal)


def test_full_width_chroma_shared_without_reusing_second_luminance():
    # Alternating chroma at every horizontal pixel must remain distinguishable;
    # PD does not use Robot's 160/320 horizontal chroma reduction.
    values = (np.full(640, 81.481), np.tile([240., 109.786], 320),
              np.tile([90.202, 240.], 320), np.full(640, 40.966))
    quality = [.98, .85, .91, .94]
    calls = []
    layout = channel_layout(48000, 17.125, .508480 * 48000, .3)

    def reader(start, duration, count):
        index = len(calls)
        calls.append((start, duration, count))
        return values[index], quality[index]

    first = extract_first(reader, 48000, 17.125, .508480 * 48000, .3)
    second = extract_second(reader, 48000, 17.125, .508480 * 48000,
                            first[1], first[2], .3)
    assert first[3] == .85
    assert second[3] == .94
    assert second[1] is first[1] and second[2] is first[2]
    assert first[0] is values[0] and second[0] is values[3]
    assert calls == [(*segment, 640) for segment in layout.values()]
    np.testing.assert_array_equal(first[1], values[1])
    np.testing.assert_array_equal(first[2], values[2])


def test_first_luminance_damage_does_not_contaminate_shared_chroma_quality():
    qualities = iter((.1, .95, .9))

    def reader(start, duration, count):
        return np.full(count, 128.), next(qualities)

    y, cr, cb, (yq, cq) = extract_first(
        reader, 48000, 0, .508480 * 48000, separate_quality=True)
    assert yq == .1
    assert cq == .9
    second = extract_second(lambda *args: (y, .98), 48000, 0,
                            .508480 * 48000, cr, cb)
    assert min(second[3], cq) == .9


def measured_frequency(pcm, rate):
    """Offline analytic-signal measurement independent of the receiver DSP."""
    phase = np.unwrap(np.angle(hilbert(pcm.astype(np.float64))))
    return np.diff(phase) * rate / (2 * np.pi)


def tone_median(frequency, rate, start, duration):
    # Avoid boundary transients: retain the central half of a channel or bit.
    a = round((start + duration * .25) * rate)
    b = round((start + duration * .75) * rate)
    return float(np.median(frequency[a:b]))


@pytest.mark.parametrize("rate", [16000, 44100, 48000])
def test_independent_pcm_header_and_shared_chroma_order(rate):
    rgb = np.empty((2, 640, 3), np.uint8)
    rgb[0] = (255, 0, 0)
    rgb[1] = (0, 0, 255)
    pcm = generate_pd120(rgb, sample_rate=rate)
    assert len(pcm) == round((.910 + .508480) * rate)
    frequency = measured_frequency(pcm, rate)
    assert tone_median(frequency, rate, .640, .030) == pytest.approx(1100, abs=.2)
    assert tone_median(frequency, rate, .820, .030) == pytest.approx(1100, abs=.2)
    assert tone_median(frequency, rate, .850, .030) == pytest.approx(1300, abs=.2)
    assert tone_median(frequency, rate, .880, .030) == pytest.approx(1200, abs=.2)
    measured = [tone_median(frequency, rate, .910 + start, .121600)
                for start in (.022080, .143680, .265280, .386880)]
    channels = frequency_to_byte(measured)
    np.testing.assert_allclose(channels, [81.481, 174.893, 165.101, 40.966], atol=.08)
    first = ycrcb_to_rgb(channels[0], channels[1], channels[2])
    second = ycrcb_to_rgb(channels[3], channels[1], channels[2])
    np.testing.assert_allclose(first, [151, 24, 151], atol=1)
    np.testing.assert_allclose(second, [104, 0, 104], atol=1)


def test_fixture_full_resolution_and_odd_row_truncation():
    assert np.asarray(make_pd_test_image()).shape == (496, 640, 3)
    rate = 16000
    partial = generate_pd120(sample_rate=rate, rows=3)
    assert len(partial) == round((.910 + .508480 + .386880) * rate)
    complete = generate_pd120(sample_rate=rate, pairs=2)
    assert len(complete) == round((.910 + 2 * .508480) * rate)
    np.testing.assert_array_equal(partial, complete[:len(partial)])
    headerless = generate_pd120(sample_rate=rate, pairs=2, include_header=False)
    assert len(headerless) == round(2 * .508480 * rate)


def test_fixture_offset_drift_timing_noise_and_missed_sync():
    rate = 16000
    scale = 1.001
    clean = generate_pd120(sample_rate=rate, pairs=3, timing_scale=scale,
                          offset_hz=70, drift_hz_per_second=3, missed_sync_pairs=[1])
    assert len(clean) == round((.910 + 3 * .508480) * scale * rate)
    frequency = measured_frequency(clean, rate)
    for pair, expected in ((0, 1200), (1, 1500), (2, 1200)):
        start = (.910 + pair * .508480) * scale
        duration = .020 * scale
        tone = tone_median(frequency, rate, start, duration)
        assert tone == pytest.approx(expected + 70 + 3 * (start + duration / 2), abs=.4)
    a = generate_pd120(sample_rate=rate, pairs=1, noise_snr_db=20, seed=2)
    b = generate_pd120(sample_rate=rate, pairs=1, noise_snr_db=20, seed=2)
    c = generate_pd120(sample_rate=rate, pairs=1, noise_snr_db=20, seed=3)
    np.testing.assert_array_equal(a, b)
    assert not np.array_equal(a, c)


@pytest.mark.parametrize("options", [
    {"rows": 0}, {"pairs": 0}, {"rows": 2, "pairs": 1},
    {"sample_rate": True}, {"timing_scale": np.inf},
    {"offset_hz": np.nan}, {"noise_snr_db": np.nan},
    {"rows": 2, "missed_sync_pairs": [1]}, {"include_header": "true"},
])
def test_fixture_rejects_invalid_input(options):
    with pytest.raises(ValueError):
        generate_pd120(**options)
