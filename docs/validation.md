# Validation status

SSTVFlow is a working implementation under image-quality validation. It has not passed every acceptance criterion in [requirements](requirements.md). Only Robot36 and PD120 are supported.

## Automatic reception

`decoder RATE` requires no mode or reception-tuning commands. The default path acquires VIS or repeated line structure, chooses the supported mode, estimates frequency offset and line-clock error, recovers sync, and selects the pixel estimation path. The caller supplies the PCM sample rate.

Integration tests cover both modes with and without VIS, including frequency shifts of +70/-65 Hz and clock mismatches of +1000/-1000 ppm. Received reference-tone evidence enables adaptive filtering on noisy channels; clean fitted channels bypass smoothing. Manual controls are optional overrides.

## Recorded verification

- The full suite passed **124 tests** on Windows AMD64 with Python 3.14.5, including local real reception fixtures. Real-data tests explicitly skip when their fixtures are absent; a source-only checkout does not reproduce those checks until recordings are supplied or downloaded.
- Continuous subprocess PCM replay emitted rows while stdin remained open, including across a delivery pause. Measured wall-clock row latency was 31 ms median and 47 ms maximum in that replay.
- Tests cover 16/44.1/48 kHz, odd and one-byte reads, arbitrary read boundaries, lossless final PNGs, row revisions, reset/discontinuity, timing/frequency mismatch, short missed-sync intervals, fades, impulses, and white/pink noise and random-tone negative inputs.
- Two-second middle excerpts without VIS passed for both synthetic modes at -150/0/+150 Hz and at three positions in each of two real recordings. Real excerpts produced 12–13 Robot36 rows or 5–6 PD120 rows. Unknown transmitter row numbering is reported explicitly.
- The clean Robot36 detail test exceeds 28 dB RGB PSNR against its synthetic transmitter image and retains checkerboard contrast. This does not establish quality against real transmitter ground truth.
- Adaptive pixel-band checks cover a clean VIS header followed by out-of-band interference and clean recovery. Clean detail matches the acquisition-only path before interference and after recovery; error in the interfered region falls by more than 30% against the clean synthetic reference. Fragmented and large PCM deliveries produce identical images and filter transitions. Historical real-reception and fine-chroma guards also pass.
- Manual noise reduction at strength 0.6 reduces flat-field noise by at least 5% in the tested case, with mean shift below two byte values. Automatic treatment reduces standard deviation by at least 15% in a separate noisy flat-field case, with mean shift below three values. Clean-detail and clean-bypass regressions pass.
- Local received-image regressions cover full Robot36 output, early headerless acquisition, reduced grain, raw-reference frequency correction, and registered agreement with an RXSSTV output from identical audio. Receiver output is a comparison reference rather than transmitter ground truth. Speckling, interference, and texture loss remain visible.
- A real PD120 full-frame replay after the noise-treatment changes produced 496 decoded/output rows with no missing flags. This is one full-frame regression, rather than a repeat of the entire corpus.
- Python compilation and distribution-wheel build checks passed.

Private recordings, comparison images, and historical reports remain local and are excluded from Git. Public corpus manifests retain source URLs, source attribution, hashes, crop intervals, and receiver-reference information. To reproduce available checks, follow the development commands in the [README](../README.md).

## Clarity refinement measurements

Paired baseline/refined replays added phase-wrap/null-safe fractional reads, jitter-aware timing confidence, and conservative luminance-guided native chroma filtering. Stronger replacement frequency filters were rejected after increasing grain in the real captures. The existing frequency filter remains the default.

- In a 48-row independent synthetic text/fine-line target, clean and 24 dB SNR results retained the same measured PSNR and edge gradient at 16/48 kHz for both modes. Clean 48 kHz Robot36 pixels matched the measured source region exactly. At 12 dB SNR, Robot36 RGB PSNR improved by 0.05/0.06 dB and PD120 by 0.18/0.33 dB; edge-gradient retention did not decrease. These are modest gains on one controlled target, not a broad OCR or field-quality claim.
- UMKA's fixed flat-region adjacent RGB difference decreased from 9.97 to 9.75 byte values, about 2.2%. Registered blurred-luminance RMSE against the same-audio RXSSTV reference stayed approximately 11.98. Both local Robot36 recordings retained 240 rows without missing flags; the historical satellite geometry threshold remained satisfied. Receiver agreement and local grain are not transmitter ground truth.
- The full real PD120 frame retained 496 rows with no missing flags. Its 128.20 seconds of audio processed in 30.35 seconds on this Windows host, with maximum initial-row latency 12.7 ms in sample time, unchanged from the paired baseline. This does not validate Raspberry Pi or ARM64 performance.
- A subsequent 355.64-second user recording decoded three consecutive complete Robot36 images automatically, each 320x240 with 240 recovered rows and no missing-row flags. The user confirmed all three worked and that RXSSTV also decodes this recording. No pixel-level comparison with RXSSTV was performed. The original stereo recording remained unchanged; a PCM16 first-channel copy at the original 48 kHz rate repaired its oversized WAV length header for replay.
- Focused tests protect single-pixel luminance strokes and equal-luminance color boundaries, verify PD shared-chroma revisions before EOF, and ensure a first-Y dropout does not mark a valid second Y missing. A settled clock rejects marginal jitter observations and caps ordinary phase movements while still reacquiring a sustained clock change.

The full suite passed after these changes; Python compilation also passed. Local before/after PNGs and stage/paired metric reports are under `artifacts/clarity/`. Residual speckling remains visible; competitive decoder parity has not been established.

## Historical public corpus replay

The following results predate the subsequent phase-integration, automatic-noise, and headerless acquisition improvements. They are historical observations rather than current pipeline measurements.

| Mode / frame | Final event | Decoded rows | Output rows |
|---|---|---:|---:|
| Robot36 / 13773866_1 | complete | 240 | 240 |
| Robot36 / 13773866_2 | complete | 134 | 240 |
| Robot36 / 13778819_1 | complete | 237 | 240 |
| Robot36 / 13778819_2 | complete | 240 | 240 |
| Robot36 / 13779373_1 | complete | 240 | 240 |
| PD120 / 11086741_1 | complete | 496 | 496 |
| PD120 / 12493896_1 | complete | 496 | 496 |
| PD120 / 12493896_2 | complete | 480 | 496 |
| PD120 / 12496081_1 | complete | 496 | 496 |
| PD120 / 585915_1 | partial | 336 | 347 |

Complete means the protocol-length image ended with its beginning known. It does not mean every output row was received successfully: missing rows remain flagged and excluded from decoded_row_count. Recognizable images and expected dimensions do not establish competitive image quality.

## Performance boundary

Earlier offline Windows AMD64 measurements processed a 40-second recording in 9.84 seconds, approximately 4.06× real time, with about 113 MiB peak resident memory. Those measurements predate later DSP changes and must not be treated as current performance results. Host measurements do not establish live Raspberry Pi/ARM64 CPU or memory performance.

## Remaining acceptance work

- Improve recovery and colors in weak/interfered captures, including partial weak PD120 and damaged Robot36 receptions.
- Compare small text, edge alignment, jitter, color, and chroma against established decoder outputs from identical recordings. Competitive parity has not been established.
- Expand automatic noise-reduction assessment across real small text, fine textures, and changing reception conditions.
- Add real voice/music negative recordings and a complete back-to-back mixed-mode matrix. Current tests cover repeated full Robot36 images and mixed partial transmissions.
- Validate the inherited control-descriptor transport on Linux/Unix and measure the full decoder on ARM64.
- Expand drift, fading, impulse, and clock-mismatch quality measurements beyond acquisition and row-count checks; verify long-duration memory bounds on the deployment target.
