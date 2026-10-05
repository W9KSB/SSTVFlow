"""Independent PD120 transmitter fixtures from Dayton 2000 pages 9-10 and 14.

No receiver imports or timing constants are used. Each physical scan transmits
two independent full-width luminance rows and their averaged full-width chroma.
"""
from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def make_pd_test_image() -> Image.Image:
    """640x496 RGB bars, grayscale, fine lines, row contrast, and text."""
    pixels = np.zeros((496, 640, 3), dtype=np.uint8)
    bars = ((255, 255, 255), (255, 255, 0), (0, 255, 255), (0, 255, 0),
            (255, 0, 255), (255, 0, 0), (0, 0, 255), (0, 0, 0))
    for index, color in enumerate(bars):
        pixels[:128, index * 80:(index + 1) * 80] = color
    pixels[128:208] = np.rint(np.linspace(0, 255, 640)).astype(np.uint8)[None, :, None]
    y, x = np.indices((128, 640))
    period = np.asarray((1, 2, 4, 8))[x // 160]
    pixels[208:336] = (((x // period + y // period) % 2) * 255)[..., None]
    # Alternating dark/bright neutral rows expose accidentally reused luminance.
    pixels[336:384:2] = 32
    pixels[337:384:2] = 224
    pixels[384:] = (20, 25, 35)
    result = Image.fromarray(pixels)
    draw = ImageDraw.Draw(result)
    font = ImageFont.load_default()
    for top, text in ((392, "PD120 / 640 x 496 / 248 PHYSICAL PAIRS"),
                      (416, "Full-width chroma: RGB CMY / ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
                      (440, "0123456789 []{} <> +-=/ / Independent protocol target"),
                      (464, "Separate Y rows / shared Cr and Cb / fine edges and timing")):
        draw.text((12, top), text, fill=(245, 245, 245), font=font)
    draw.rectangle((0, 0, 639, 495), outline=(255, 255, 255))
    return result


def generate_pd120(
    image: Image.Image | np.ndarray | None = None,
    *,
    sample_rate: int = 48000,
    rows: int | None = None,
    pairs: int | None = None,
    include_header: bool = True,
    offset_hz: float = 0.0,
    drift_hz_per_second: float = 0.0,
    timing_scale: float = 1.0,
    noise_snr_db: float | None = None,
    fades: Sequence[tuple[float, float, float]] = (),
    impulses: Sequence[tuple[float, float]] = (),
    missed_sync_pairs: Sequence[int] = (),
    seed: int = 0,
) -> np.ndarray:
    """Return continuous-phase float32 PCM with an optional valid VIS 95 header.

    RGB input is 640 pixels wide and 1..496 rows tall. ``rows`` truncates output
    after that many logical rows; an odd count ends after the final Cb scan,
    before second Y. ``pairs`` instead requests that many complete physical
    pairs. They are mutually exclusive. For shared chroma, an available next
    source row participates even if it will not be transmitted; an unpaired
    final source row is duplicated. Horizontal chroma is never downsampled.

    ``timing_scale`` multiplies all durations including header bits. Offset and
    drift apply to header and pixels. Missed sync replaces a zero-based physical
    pair's 20 ms 1200 Hz tone with 1500 Hz. Fades (start, duration, gain), impulses
    (time, amplitude), and noise use output seconds. Fades have 5 ms soft edges.
    Clean peak amplitude is .8; noisy output may exceed +/-1. Clip explicitly
    when converting it to integer PCM. Seed controls only additive noise.
    """
    def integer(value):
        return not isinstance(value, bool) and isinstance(value, (int, np.integer))

    if not integer(sample_rate) or sample_rate < 8000:
        raise ValueError("sample_rate must be an integer of at least 8000 Hz")
    if not np.isfinite(timing_scale) or timing_scale <= 0:
        raise ValueError("timing_scale must be finite and positive")
    if not np.isfinite(offset_hz) or not np.isfinite(drift_hz_per_second):
        raise ValueError("frequency offset and drift must be finite")
    if noise_snr_db is not None and not np.isfinite(noise_snr_db):
        raise ValueError("noise_snr_db must be finite")
    if not isinstance(include_header, bool):
        raise ValueError("include_header must be boolean")
    source = make_pd_test_image() if image is None else image
    if isinstance(source, Image.Image):
        source = source.convert("RGB")
    rgb = np.asarray(source, dtype=np.float64)
    if rgb.ndim != 3 or rgb.shape[1:] != (640, 3) or not 1 <= rgb.shape[0] <= 496:
        raise ValueError("image must have shape (1..496, 640, 3)")
    if not np.all(np.isfinite(rgb)) or np.any(rgb < 0) or np.any(rgb > 255):
        raise ValueError("image RGB values must be finite and between 0 and 255")
    if rows is not None and pairs is not None:
        raise ValueError("rows and pairs are mutually exclusive")
    if pairs is not None and (not integer(pairs) or not 1 <= pairs <= rgb.shape[0] // 2):
        raise ValueError("pairs must fit complete source pairs")
    row_count = pairs * 2 if pairs is not None else rgb.shape[0] if rows is None else rows
    if not integer(row_count) or not 1 <= row_count <= rgb.shape[0]:
        raise ValueError("rows must be an integer between 1 and the image height")
    missing = set(missed_sync_pairs)
    if any(not integer(n) or not 0 <= n < (row_count + 1) // 2 for n in missing):
        raise ValueError("missed_sync_pairs must contain transmitted pair indices")

    red, green, blue = np.moveaxis(rgb, -1, 0)
    # Limited-range BT.601, independently encoded from Appendix B's equations.
    luminance = 16 + (.299 * red + .587 * green + .114 * blue) * 219 / 255
    cr = 128 + (.5 * red - .418688 * green - .081312 * blue) * 224 / 255
    cb = 128 + (-.168736 * red - .331264 * green + .5 * blue) * 224 / 255
    parts = []
    elapsed = 0.0
    written = 0

    def tone(frequency, seconds):
        nonlocal elapsed, written
        elapsed += seconds * timing_scale
        end = round(elapsed * sample_rate)
        count = end - written
        if np.isscalar(frequency):
            values = np.full(count, frequency, dtype=np.float64)
        else:
            indices = np.minimum(((np.arange(count) + .5) * len(frequency) /
                                  max(count, 1)).astype(int), len(frequency) - 1)
            values = frequency[indices]
        parts.append(values)
        written = end

    if include_header:
        tone(1900, .300)
        tone(1200, .010)
        tone(1900, .300)
        tone(1200, .030)
        bits = [(95 >> bit) & 1 for bit in range(7)]
        for bit in bits:
            tone(1100 if bit else 1300, .030)
        tone(1100 if sum(bits) % 2 else 1300, .030)
        tone(1200, .030)
    for first in range(0, row_count, 2):
        second = min(first + 1, rgb.shape[0] - 1)
        tone(1500 if first // 2 in missing else 1200, .020)
        tone(1500, .002080)
        tone(1500 + luminance[first] * 800 / 255, .121600)
        tone(1500 + (cr[first] + cr[second]) * .5 * 800 / 255, .121600)
        tone(1500 + (cb[first] + cb[second]) * .5 * 800 / 255, .121600)
        if first + 1 < row_count:
            tone(1500 + luminance[second] * 800 / 255, .121600)

    frequencies = np.concatenate(parts)
    times = np.arange(len(frequencies), dtype=np.float64) / sample_rate
    frequencies += offset_hz + drift_hz_per_second * times
    if np.any(frequencies <= 0) or np.any(frequencies >= sample_rate / 2):
        raise ValueError("offset/drift makes a tone nonpositive or exceeds Nyquist")
    pcm = .8 * np.sin(np.cumsum(frequencies) * (2 * np.pi / sample_rate))
    for start, duration, gain in fades:
        if not all(np.isfinite(v) for v in (start, duration, gain)) or start < 0 or duration <= 0 or not 0 <= gain <= 1:
            raise ValueError("fades require finite start >= 0, duration > 0, and gain in 0..1")
        first = min(round(start * sample_rate), len(pcm))
        last = min(round((start + duration) * sample_rate), len(pcm))
        envelope = np.full(last - first, gain)
        edge = min(round(.005 * sample_rate), len(envelope) // 2)
        if edge:
            ramp = gain + (1 - gain) * (1 + np.cos(np.linspace(0, np.pi, edge))) / 2
            envelope[:edge] = ramp
            envelope[-edge:] = ramp[::-1]
        pcm[first:last] *= envelope
    if noise_snr_db is not None:
        noise_rms = np.sqrt(np.mean(pcm * pcm)) * 10 ** (-noise_snr_db / 20)
        pcm += np.random.default_rng(seed).normal(0, noise_rms, len(pcm))
    for when, amplitude in impulses:
        if not np.isfinite(when) or when < 0 or not np.isfinite(amplitude):
            raise ValueError("impulses require finite time >= 0 and finite amplitude")
        index = round(when * sample_rate)
        if index < len(pcm):
            pcm[index] += amplitude
    return pcm.astype(np.float32)
