# SSTVFlow

SSTVFlow is a headless, streaming SSTV decoder that turns continuous audio into images and emits decoded rows as they arrive. It is a standalone Python component for applications that receive audio from a radio, SDR, recording, or another audio source.

Normal operation requires only the source's sample rate and its PCM audio. Mode selection, headerless acquisition, frequency correction, slant correction, pixel estimation, and noise reduction run automatically.

```sh
decoder 48000 < input.s16le > events.ndjson
```

**Status:** Robot36 and PD120 are implemented. Image-quality refinement is ongoing, especially for weak or interfered signals. Linux ARM64 is the intended deployment target; Raspberry Pi performance and Unix control-descriptor operation still need target-side validation.

## Supported modes

| Mode | Image size | Reception |
|---|---|---|
| Robot36 | 320 × 240 | Automatic VIS or repeated line-structure acquisition |
| PD120 | 640 × 496 | Automatic VIS or repeated line-structure acquisition |

Only these two modes are currently supported. Progressive RGB rows and row revisions are available during reception, followed by an authoritative lossless PNG when an image or recoverable segment ends.

## Installation

Requires Python 3.11 or newer, NumPy, SciPy, and Pillow. The installation command installs these runtime dependencies. Run the following commands from the project checkout.

### Linux / Unix

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install .
decoder 48000 < input.s16le > events.ndjson
```

### Windows PowerShell

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install .
```

Use a binary-safe caller to supply PCM. For example, save this as `decode_pcm.py` and run it with `.\.venv\Scripts\python.exe decode_pcm.py`:

```python
import subprocess
import sys

with open("input.s16le", "rb") as audio, open("events.ndjson", "wb") as events:
    subprocess.run(
        [sys.executable, "-m", "sstv_decoder.cli", "48000"],
        stdin=audio,
        stdout=events,
        check=True,
    )
```

PowerShell text pipelines can transform binary audio. The example passes file handles directly to the decoder. The installed command is `decoder`; the Python entry point is `python -m sstv_decoder.cli`. The package distribution is named `SSTVFlow`, and Python imports use `sstv_decoder`.

## Audio input

The executable reads **raw signed 16-bit little-endian mono PCM** from standard input. Each sample is exactly two bytes. Tested source rates are **16000, 44100, and 48000 Hz**.

The positional rate argument must match the source audio. An unframed byte stream carries no sample-rate metadata. WAV headers, stereo interleaving, floating-point samples, and compressed audio must be converted by the caller before streaming to the executable.

Reads can contain any number of bytes, including one byte. Unmatched bytes are retained between reads. Chunk boundaries do not define tones, lines, or images. The process keeps its decoding state across reads and transmissions until stdin reaches EOF.

For live reception, write audio bytes to stdin and continuously consume JSON events from stdout. Delivery pauses do not count as radio silence; actual silence is represented by PCM samples. EOF drains usable filter state, emits any recoverable partial result, and exits.

### Start in the middle of a transmission

Opening tones and VIS are optional. SSTVFlow can recognize repeated sync pulses, scan cadence, porch tones, and mode-specific channel structure after reception has already started.

Two-second middle excerpts have decoded successfully in the tested Robot36 and PD120 recordings. A usable excerpt must contain enough recognizable structure; heavily damaged sync or picture tones alone may prevent acquisition.

Headerless reception produces `image_partial`. Recovered rows start at local index zero, and the transmitter's original row number remains unknown. Partial first/last scans may be omitted. The decoder preserves recoverable content without assigning an invented position within the original image.

## Output and image saving

Standard output contains flushed, newline-delimited UTF-8 JSON: one event per line. Diagnostics use stderr when enabled.

| Event | Purpose |
|---|---|
| `ready` | Decoder configuration and supported modes |
| `acquisition` / `image_start` | Detected mode, acquisition evidence, and recovered-image identity |
| `row` | A newly decoded RGB888 row, encoded as base64 |
| `row_revision` | A complete replacement for an earlier row |
| `quality` / `status` | Reception estimates, correction settings, and quality indicators |
| `image_complete` / `image_partial` | Final row counts, quality summary, and base64 lossless PNG |
| `warning` / `error` | Input or control problems |

To extract PNGs from a saved event stream:

```python
import base64
import json
from pathlib import Path

count = 0
with open("events.ndjson", encoding="utf-8") as stream:
    for line in stream:
        event = json.loads(line)
        if event["type"] in ("image_complete", "image_partial"):
            count += 1
            output = Path(f"image-{count:03d}.png")
            output.write_bytes(base64.b64decode(event["png"]))
            print(output, event["type"])
```

A live image consumer retains the highest revision for each `(image_id, row_index)`. Robot36 emits provisional chroma and revises earlier rows when complementary chroma arrives. The final PNG already contains the newest row revisions.

`image_complete` means the known-start protocol-length image ended; reception can still contain missing or damaged rows. `decoded_row_count` excludes rows marked missing, while `output_row_count` includes every emitted position. These are heuristic reception classifications. See the [complete event schema](docs/events.md) for timing, confidence, flags, and partial-image semantics.

Consumers must keep draining stdout. A blocked output pipe applies backpressure, and a caller's unbounded event queue can exhaust its own memory.

## How decoding works

1. **Continuous demodulation:** stateful FIR filters form an analytic signal and estimate audio frequency. Exact filter delay is accounted for on the input sample timeline.
2. **Automatic acquisition:** VIS identifies a supported mode when available. Without VIS, repeated sync/cadence and channel evidence establish the mode. Raw-tone checks help recover short references distorted by noisy phase estimates.
3. **Separate frequency and timing correction:** qualified raw reference-tone fits estimate mistuning. A robust line-clock model estimates sample-clock mismatch and slant. Bounded matched-sync searches and timing prediction help bridge short sync losses.
4. **Pixel estimation:** short fractional pixel apertures preserve sampling alignment. Amplitude-weighted phase integration suppresses unstable observations near signal nulls. Clean channels can use tightly gated raw sine fitting to retain fine detail.
5. **Chroma reconstruction:** Robot36 separates luminance and alternating Cr/Cb scans, reconstructs shared chroma, and revises provisional rows. PD120 extracts two luminance rows with shared full-width chroma per physical scan pair.
6. **Progressive output:** completed rows emit during reception. A bounded audio history and fixed-size image state retain the data needed for tracking, reconstruction, revisions, and the final PNG.

The implementation follows published SSTV protocol timings and standard DSP/color-conversion techniques, including the [Dayton SSTV specification](https://www.classicsstv.com/downloads/daytonpaper.pdf). It is independently implemented using NumPy, SciPy, and Pillow. Further timing, buffer, and estimator details are in the [architecture document](docs/architecture.md).

### Automatic noise reduction

Received constant-tone references establish whether reception is noisy. A local variance-dependent filter reduces grain in flat channel regions while retaining stronger edges. Clean fitted channels bypass smoothing. Noise estimation also works after headerless acquisition and updates from subsequent sync observations.

Images that start on the wider pixel filter can automatically select narrower filtering during interference and restore the wider path after sustained clean sync references. Timing and received sample positions remain unchanged; no additional tuning control is required. An initial narrow-filter selection remains in effect for that image.

This is still being refined: grain, horizontal interference, and texture loss can remain. Noise reduction cannot recreate information that was not received reliably.

## Optional controls

The default command needs no tuning controls. Advanced callers can override frequency, slant, horizontal displacement, display settings, and noise treatment, or report a stream discontinuity.

| Option | Use |
|---|---|
| `--noise-reduction 0` | Disable automatic and manual noise reduction |
| `--noise-reduction 0.6` | Replace automatic treatment with a manual median blend, strength 0–1 |
| `--diagnostics` | Write detailed accepted-sync/timing observations to stderr |
| `--control-fd N` | Read runtime JSON commands from a separate inherited descriptor |
| `--demodulator hilbert` / `narrow` | Select an alternative estimator or explicit narrow bandpass |
| `--pixel-estimator phase` / `sinefit` | Override adaptive pixel estimation for comparison |

Forced `sinefit` is an experimental clean-signal comparison setting; individual short-window fits can be unreliable in noise. Normal automatic reception selects its pixel path from received reference evidence.

Runtime commands are newline-delimited JSON on the control descriptor, separate from PCM. For example:

```json
{"command":"status"}
{"command":"noise_reduction","auto":true}
{"command":"reset"}
{"command":"discontinuity","lost_samples":480}
```

A discontinuity closes a recoverable segment and resets tracking for reacquisition. `reset` closes the current image and resets reception state while preserving configured controls and the process.

The inherited descriptor transport is intended for Linux/Unix callers. Its runtime operation on Linux and Windows descriptor compatibility are not yet validated. See [control commands and the caller example](docs/control.md).

## Python integration

The same streaming coordinator is available directly:

```python
from sstv_decoder.decoder import Decoder

def on_event(event):
    # Handle progressive rows/revisions and final PNG events here.
    print(event["type"])

decoder = Decoder(48000, on_event)
with open("input.s16le", "rb") as audio:
    while data := audio.read(4096):
        decoder.feed(data)
decoder.eof()
```

For a live source, call `feed()` as PCM bytes arrive and call `eof()` when the stream finishes. `control()` accepts the same command objects described in the control documentation. The development API and event schema may evolve while quality work continues.

## Current limitations

Difficult weak/interfered receptions can still produce speckling, texture loss, and incomplete images. Competitive-decoder quality comparison and ARM64 deployment performance remain unverified.

## License

SSTVFlow is licensed under the [PolyForm Noncommercial License 1.0.0](LICENSE). It permits use, modification, and sharing for purposes allowed by the license. Commercial use requires separate permission from the copyright holder.

This is source-available software with a noncommercial restriction, so it does not meet the [Open Source Definition](https://opensource.org/osd). Third-party dependencies retain their own licenses.
