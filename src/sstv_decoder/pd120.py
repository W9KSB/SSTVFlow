"""PD two-row physical scans and fractional channel extraction.

Dayton 2000 pages 8-9 give every PD sub-mode the same structure: a 20 ms sync,
a 2.080 ms porch, and four equal scans - Y(first), Cr, Cb, Y(second). Cr and Cb
are shared by both rows, and each channel is as wide as the mode's raster.
Only the channel length and geometry differ: PD50 320x256 at 91.520 ms,
PD90 320x256 at 170.240 ms, PD120 640x496 at 121.600 ms, PD160 512x400 at
195.584 ms, PD180 640x496 at 183.040 ms, PD240 640x496 at 244.480 ms, and
PD290 800x616 at 228.800 ms. Each channel length follows from its mode period,
so the profile table remains the single authority.
The caller supplies its pixel reader and owns timing, frequency correction,
signal acquisition, and progressive row publication.
"""
import math

from .modes import MODES

WIDTH = 640
HEIGHT = 496
PAIRS = HEIGHT // 2
VIS_CODE = 95
SYNC_SECONDS = .020
PORCH_SECONDS = .002080
CHANNEL_SECONDS = .121600
PAIR_SECONDS = SYNC_SECONDS + PORCH_SECONDS + 4 * CHANNEL_SECONDS


def mode_timing(mode):
    """Return ``(width, height, channel_seconds)`` for a PD sub-mode."""
    profile = MODES.get(mode)
    if profile is None or profile.family != "pd":
        raise ValueError("PD extraction mode must be a PD sub-mode")
    return profile.width, profile.height, (profile.period - SYNC_SECONDS - PORCH_SECONDS) / 4


def channel_layout(rate, start, actual_period, horizontal_ms=0, *, mode="PD120"):
    """Return ``channel: (start_sample, duration_samples)`` for a physical pair.

    ``start`` is its sync edge and ``actual_period`` is the measured pair period
    in samples. Durations and relative starts scale with that measured period;
    horizontal adjustment is an absolute time shift in milliseconds. Positions
    remain fractional, so repeated pairs do not accumulate integer rounding.
    """
    if not all(math.isfinite(v) for v in (rate, start, actual_period, horizontal_ms)):
        raise ValueError("PD120 timing values must be finite")
    if rate <= 0 or actual_period <= 0:
        raise ValueError("PD120 rate and pair period must be positive")
    _, _, channel_seconds = mode_timing(mode)
    pair_seconds = SYNC_SECONDS + PORCH_SECONDS + 4 * channel_seconds
    samples_per_protocol_second = actual_period / pair_seconds
    first = start + (SYNC_SECONDS + PORCH_SECONDS) * samples_per_protocol_second
    first += horizontal_ms * .001 * rate
    duration = channel_seconds * samples_per_protocol_second
    return {name: (first + index * duration, duration)
            for index, name in enumerate(("y_first", "cr", "cb", "y_second"))}


def extract_first(pixel_reader, rate, start, period, horizontal_ms=0, chroma_reader=None,
                  *, separate_quality=False, mode="PD120"):
    """Read the first Y and both shared chroma scans, returning Y/Cr/Cb/quality.

    ``pixel_reader(start, duration, count)`` returns intensity values and scalar
    quality after the caller's frequency correction. With ``separate_quality``,
    the last result is (Y quality, shared chroma quality), so a damaged first Y
    does not invalidate the second Y. Otherwise it is their minimum for this row.
    This row is complete once the Cb scan arrives, before the second Y finishes.
    """
    width = mode_timing(mode)[0]
    layout = channel_layout(rate, start, period, horizontal_ms, mode=mode)
    y, yq = pixel_reader(*layout["y_first"], width)
    chroma_reader=chroma_reader or pixel_reader
    cr, crq = chroma_reader(*layout["cr"], width)
    cb, cbq = chroma_reader(*layout["cb"], width)
    chroma_quality = min(crq, cbq)
    return y, cr, cb, (yq, chroma_quality) if separate_quality else min(yq, chroma_quality)


def extract_second(pixel_reader, rate, start, period, cr, cb, horizontal_ms=0, *, mode="PD120"):
    """Read second Y and reuse first-row chroma without resampling or mutation.

    Returned quality covers the new Y scan. The caller combines it with the
    stored shared-chroma quality from :func:`extract_first` when publishing.
    """
    width = mode_timing(mode)[0]
    layout = channel_layout(rate, start, period, horizontal_ms, mode=mode)
    y, quality = pixel_reader(*layout["y_second"], width)
    return y, cr, cb, quality
