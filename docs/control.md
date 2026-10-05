# Control interface

Launch `decoder RATE --control-fd N`. N must be an inherited read descriptor >=3, separate from stdin/stdout/stderr. Commands are newline-delimited JSON objects; the line limit is 65536 bytes. Invalid commands produce an `error` event and leave the process running. Successful commands produce a `status` acknowledgment on stdout. Commands do not go into the PCM stream.

| Operation | JSON command |
|---|---|
| Query | `{"command":"status"}` |
| Reset | `{"command":"reset"}` |
| Automatic selection | `{"command":"mode","mode":"auto"}` |
| Force Robot 36 | `{"command":"mode","mode":"Robot36"}` |
| Force PD120 | `{"command":"mode","mode":"PD120"}` |
| Manual frequency correction | `{"command":"frequency","auto":false,"offset_hz":75}` |
| Automatic frequency correction | `{"command":"frequency","auto":true}` |
| Manual timing/slant | `{"command":"slant","auto":false,"ppm":1000}` |
| Automatic timing/slant | `{"command":"slant","auto":true}` |
| Horizontal displacement | `{"command":"horizontal","offset_ms":0.05}` |
| Impulse rejection on/off | `{"command":"impulse_rejection","enabled":true}` / `false` |
| Automatic noise reduction (default) | `{"command":"noise_reduction","auto":true}` |
| Manual noise reduction | `{"command":"noise_reduction","strength":0.25}` |
| Noise reduction off | `{"command":"noise_reduction","strength":0}` |
| Known sample loss | `{"command":"discontinuity","lost_samples":480}` |
| Unknown amount of loss | `{"command":"discontinuity","lost_samples":null}` |
| Neutral display settings | `{"command":"display","brightness":0,"contrast":1,"gamma":1,"saturation":1}` |

`auto` and `enabled` must be JSON booleans. Numeric controls reject NaN, infinity, and out-of-range values. Frequency offset is -300..300 Hz; it is the observed positive/negative audio shift that is subtracted during decoding. Slant is -20000..20000 ppm; positive ppm lengthens the physical scan period. Horizontal offset is -5..5 ms; positive values sample later. Manual noise strength is 0..1; automatic treatment is the default. Brightness -1..1, contrast 0..4, gamma .1..5, saturation 0..4; defaults are neutral.

Forcing a mode selects the accepted protocol family but still requires valid line structure. It does not manufacture synchronization. Switching mode closes the active recoverable image as partial. Switching manual timing preserves the predicted phase of the next physical scan rather than jumping the whole image.

Reset closes the active image (`manual_reset`), discards pending PCM bytes, analytic/FIR history, protocol/VIS acquisition, timing observations, row/chroma state, and automatic frequency lock. The absolute consumed-sample counter and configured controls persist. It does not restart the process.

Automatic noise reduction checks constant-tone references before filtering channel values with a local variance-dependent estimate; clean fitted channels bypass it. Noise estimation also works with headerless acquisition. A manual strength disables automatic treatment and blends a three-sample median within each extracted channel. Chroma uses the requested strength; luminance uses 35% of that strength to reduce damage to fine detail. Zero disables both treatments. `auto:true` rejects a simultaneous manual strength. Changes apply to subsequently extracted rows; existing published rows are not silently modified.

A discontinuity processes usable pending PCM, preserves recovered rows in an authoritative `image_partial` PNG (`audio_discontinuity`), discards waveform/timing state, and reacquires a new segment. A supplied loss count advances the absolute sample timeline; unknown loss is flagged as unknown continuity. Segments are **not stitched into a falsely continuous image**. Control application occurs at a processing boundary; this version has no sample-exact scheduled control command. Already queued upstream audio cannot be inferred from raw PCM. A caller should report discontinuities promptly and retain their own stream-boundary accounting.

Linux/Unix caller:

```python
import json
import os
import subprocess

read_fd, write_fd = os.pipe()
proc = subprocess.Popen(
    ["decoder", "48000", "--control-fd", str(read_fd)],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    pass_fds=(read_fd,),
)
os.close(read_fd)

def control(message):
    os.write(write_fd, (json.dumps(message) + "\n").encode("utf-8"))

# Drain stdout and stderr continuously in separate reader tasks/threads.
# Write raw PCM bytes to proc.stdin; never write these commands there.
control({"command": "status"})
```

The control descriptor can close independently of PCM. PCM EOF drains usable DSP samples, emits recoverable final/partial results, and terminates cleanly. Controls are local capabilities inherited by the process; there is no network listener.
