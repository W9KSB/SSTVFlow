"""Independent synthetic Robot36 audio for receiver validation.

This transmitter implements the supplied Robot36 protocol timings directly; it
does not import receiver code or reuse receiver constants. Pixel values use
limited-range BT.601 YCbCr and the SSTV 1500..2300 Hz intensity mapping.
"""

from __future__ import annotations

from collections.abc import Sequence

import numpy as np
from PIL import Image, ImageDraw, ImageFont


def make_test_image() -> Image.Image:
    """Return a 320x240 RGB target with bars, gray ramp, fine lines, and text."""
    pixels = np.zeros((240, 320, 3), dtype=np.uint8)
    bars = (
        (255, 255, 255), (255, 255, 0), (0, 255, 255), (0, 255, 0),
        (255, 0, 255), (255, 0, 0), (0, 0, 255), (0, 0, 0),
    )
    for index, color in enumerate(bars):
        pixels[:64, index * 40:(index + 1) * 40] = color
    ramp = np.rint(np.linspace(0, 255, 320)).astype(np.uint8)
    pixels[64:104] = ramp[None, :, None]
    for y in range(104, 152):
        # Different periods reveal filtering, row alignment, and timing drift.
        for x in range(320):
            period = (1, 2, 4, 8)[x // 80]
            pixels[y, x] = 255 if ((x // period) + (y // period)) % 2 else 0
    pixels[152:] = (20, 25, 35)
    result = Image.fromarray(pixels)
    draw = ImageDraw.Draw(result)
    font = ImageFont.load_default()
    for y, text in (
        (158, "ROBOT 36  /  320 x 240"),
        (176, "Fine text: ABCDEFGHIJKLMNOPQRSTUVWXYZ"),
        (194, "0123456789  []{} <> +-=/  SSTV"),
        (212, "Color, luminance, edge and timing target"),
    ):
        draw.text((8, y), text, fill=(245, 245, 245), font=font)
    draw.rectangle((0, 0, 319, 239), outline=(255, 255, 255))
    return result


def generate_robot36(
    image: Image.Image | np.ndarray | None = None,
    *,
    sample_rate: int = 48000,
    rows: int | None = None,
    offset_hz: float = 0.0,
    drift_hz_per_second: float = 0.0,
    timing_scale: float = 1.0,
    noise_snr_db: float | None = None,
    fades: Sequence[tuple[float, float, float]] = (),
    impulses: Sequence[tuple[float, float]] = (),
    missed_sync_lines: Sequence[int] = (),
    seed: int = 0,
) -> np.ndarray:
    """Return continuous-phase float32 mono PCM, with a complete VIS header.

    ``image`` contains 0..255 RGB values and must be 320 pixels wide with
    1..240 rows. The default is :func:`make_test_image`. ``rows`` limits the
    transmitted rows; when available, the following image row still participates
    in the final pair's chroma average. An unpaired final image row is duplicated
    for that average. A complete transmission contains 240 rows.

    ``timing_scale`` multiplies every protocol duration. Frequency offset and
    linear frequency drift apply to the entire transmission, including VIS.
    ``noise_snr_db`` sets whole-signal RMS SNR after fading. Each fade is
    ``(start_seconds, duration_seconds, gain)`` with gain between 0 and 1 and
    smooth 5 ms edges. Each impulse is ``(time_seconds, amplitude)`` and affects
    one sample. ``missed_sync_lines`` replaces those zero-based line sync tones
    with 1500 Hz. Impairments use output time, after timing scaling.

    Clean peak amplitude is 0.8. Noise and impulses may exceed +/-1; callers
    converting to integer PCM should clip explicitly. Seed controls only noise.
    """
    if isinstance(sample_rate, bool) or not isinstance(sample_rate, (int, np.integer)) or sample_rate < 8000:
        raise ValueError("sample_rate must be an integer of at least 8000 Hz")
    if not np.isfinite(timing_scale) or timing_scale <= 0:
        raise ValueError("timing_scale must be finite and positive")
    if not np.isfinite(offset_hz) or not np.isfinite(drift_hz_per_second):
        raise ValueError("frequency offset and drift must be finite")
    if noise_snr_db is not None and not np.isfinite(noise_snr_db):
        raise ValueError("noise_snr_db must be finite")

    source = make_test_image() if image is None else image
    if isinstance(source, Image.Image):
        source = source.convert("RGB")
    rgb = np.asarray(source, dtype=np.float64)
    if rgb.ndim != 3 or rgb.shape[1:] != (320, 3) or not 1 <= rgb.shape[0] <= 240:
        raise ValueError("image must have shape (1..240, 320, 3)")
    if not np.all(np.isfinite(rgb)) or np.any(rgb < 0) or np.any(rgb > 255):
        raise ValueError("image RGB values must be finite and between 0 and 255")
    line_count = rgb.shape[0] if rows is None else rows
    if isinstance(line_count, bool) or not isinstance(line_count, (int, np.integer)) or not 1 <= line_count <= rgb.shape[0]:
        raise ValueError("rows must be an integer between 1 and the image height")
    missing = set(missed_sync_lines)
    if any(isinstance(line, bool) or not isinstance(line, (int, np.integer)) or not 0 <= line < line_count for line in missing):
        raise ValueError("missed_sync_lines must contain transmitted zero-based row indices")

    red, green, blue = np.moveaxis(rgb, -1, 0)
    luminance = 16 + (0.299 * red + 0.587 * green + 0.114 * blue) * 219 / 255
    cb = 128 + (-0.168736 * red - 0.331264 * green + 0.5 * blue) * 224 / 255
    cr = 128 + (0.5 * red - 0.418688 * green - 0.081312 * blue) * 224 / 255

    parts: list[np.ndarray] = []
    elapsed = 0.0
    samples_written = 0

    def append_tone(frequency: float | np.ndarray, seconds: float) -> None:
        nonlocal elapsed, samples_written
        elapsed += seconds * timing_scale
        end_sample = round(elapsed * sample_rate)
        count = end_sample - samples_written
        if np.isscalar(frequency):
            parts.append(np.full(count, frequency, dtype=np.float64))
        else:
            # Each transmitted pixel holds its frequency for equal time. Sample
            # pixel centers without accumulating per-pixel rounding errors.
            indices = np.minimum(
                ((np.arange(count) + 0.5) * len(frequency) / max(count, 1)).astype(int),
                len(frequency) - 1,
            )
            parts.append(frequency[indices])
        samples_written = end_sample

    append_tone(1900, 0.300)
    append_tone(1200, 0.010)
    append_tone(1900, 0.300)
    append_tone(1200, 0.030)
    vis_bits = [(8 >> bit) & 1 for bit in range(7)]
    for bit in vis_bits:
        append_tone(1100 if bit else 1300, 0.030)
    append_tone(1100 if sum(vis_bits) % 2 else 1300, 0.030)
    append_tone(1200, 0.030)

    for line in range(line_count):
        append_tone(1500 if line in missing else 1200, 0.009)
        append_tone(1500, 0.003)
        append_tone(1500 + luminance[line] * 800 / 255, 0.088)
        append_tone(1500 if line % 2 == 0 else 2300, 0.0045)
        append_tone(1900, 0.0015)
        pair_start = line - line % 2
        pair_end = min(pair_start + 1, rgb.shape[0] - 1)
        chroma = cr if line % 2 == 0 else cb
        pair = (chroma[pair_start] + chroma[pair_end]) / 2
        horizontal_pairs = pair.reshape(160, 2).mean(axis=1)
        append_tone(1500 + horizontal_pairs * 800 / 255, 0.044)

    frequencies = np.concatenate(parts)
    times = np.arange(len(frequencies), dtype=np.float64) / sample_rate
    frequencies += offset_hz + drift_hz_per_second * times
    if np.any(frequencies <= 0) or np.any(frequencies >= sample_rate / 2):
        raise ValueError("offset/drift makes a tone nonpositive or exceeds Nyquist")
    phase = np.cumsum(frequencies) * (2 * np.pi / sample_rate)
    pcm = 0.8 * np.sin(phase)

    for start, duration, gain in fades:
        if not all(np.isfinite(value) for value in (start, duration, gain)) or start < 0 or duration <= 0 or not 0 <= gain <= 1:
            raise ValueError("fades require finite start >= 0, duration > 0, and 0 <= gain <= 1")
        first = min(round(start * sample_rate), len(pcm))
        last = min(round((start + duration) * sample_rate), len(pcm))
        count = last - first
        envelope = np.full(count, gain)
        edge = min(round(0.005 * sample_rate), count // 2)
        if edge:
            ramp = gain + (1 - gain) * (1 + np.cos(np.linspace(0, np.pi, edge))) / 2
            envelope[:edge] = ramp
            envelope[-edge:] = ramp[::-1]
        pcm[first:last] *= envelope
    if noise_snr_db is not None:
        power = np.mean(pcm * pcm)
        noise_rms = np.sqrt(power) * 10 ** (-noise_snr_db / 20)
        pcm += np.random.default_rng(seed).normal(0, noise_rms, len(pcm))
    for when, amplitude in impulses:
        if not np.isfinite(when) or when < 0 or not np.isfinite(amplitude):
            raise ValueError("impulses require finite time >= 0 and finite amplitude")
        index = round(when * sample_rate)
        if index < len(pcm):
            pcm[index] += amplitude
    return pcm.astype(np.float32)
