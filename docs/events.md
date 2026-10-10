# Output event schema, version 1

One JSON object per line, UTF-8, flushed promptly. Every event has `type`. Positions are absolute input sample coordinates (including known externally reported sample loss); fractional positions account for FIR delay and interpolation. `sample_position` is the processed input position; delivery wall-clock time is never protocol timing.

| Type | Principal fields |
|---|---|
| `ready` | `sample_rate`, `supported_modes`, `decoder_version`, `demodulator`, `pixel_estimator`, `dsp_delay_samples`, `control_interface` |
| `acquisition` | `candidate_mode`, `acquisition_source` (`VIS` or `line_structure`), `confidence`, `vis_code`, `vis_confidence` when present, `frequency_offset_hz`, `timing_confidence`, `sample_position` |
| `image_start` | `image_id`, `mode`, `width`, `nominal_height`, `acquisition_source`, `acquisition_confidence`, `beginning_known`, `transmitter_row_numbering_known` |
| `row` | `image_id`, `row_index`, `width`, `revision:0`, `rgb`, `row_confidence`, `quality_flags`, timing/provenance fields |
| `row_revision` | same row fields, increasing `revision`, plus `reason`; complete replacement, not a delta |
| `quality` | current status plus signal RMS, DC estimate, clipping, low level/silence, envelope variability noise estimate, impulse sample count |
| `status` | active mode, sample position, row count, measured/applied frequency offset, confidence/lock/reference, line period, clock ppm, timing confidence/lock/phase, configured corrections |
| `image_complete` / `image_partial` | image/mode/reason, counts, width/height, `png`, final frequency/clock status, quality summary |
| `warning` / `error` | `code`, `message` when useful, and problem-specific metadata |

`image_id` is a unique opaque hex UUID. Supported mode names are exactly `Robot24`, `Robot36`, `Robot72`, `MartinM1`, `MartinM2`, `PD120`, and `PD180`. Robot24 uses 160x120; Robot36/Robot72 use 320x240; Martin modes use 320x256; PD modes use 640x496. Martin and PD preserve their protocol header rows rather than cropping them.

`rgb` is base64 of RGB888 bytes, left to right: exactly `width * 3` decoded bytes. `row_index` is zero-based within this recovered image segment. `protocol_row_index` is `null` when the transmitter position is unknown; `physical_scan_line` counts Robot scans or PD pairs, separately from output rows. `received_row_sequence` and `original_position_known` make this distinction explicit.

Clients retain the highest revision for every `(image_id,row_index)`. Robot36's first row of a chroma pair is provisional; `paired_chroma_received` replaces it when the complementary scan arrives, usually one physical line later. Robot24 and Robot72 carry both chroma channels on every scan. Revisions start at zero and increase monotonically. PD rows already have shared Cr/Cb when emitted. During noisy reception, the second Y may improve the common chroma filter's edge guidance; `shared_chroma_refined` replaces the first row so both rows use the same refined chroma. Its original audio-end position is retained for provenance.

Flags include `timing_recovered`, `low_signal_quality`, `missing`, `chroma_phase_unknown`, `chroma_phase_inferred`, and `interpolated_chroma`. Inferred timing does not imply directly measured synchronization. Provisional chroma is explicitly flagged. A known VIS/scan timeline can preserve chroma phase through damaged separators; that inference is flagged. Unknown/missing signal is not classified as directly decoded content. Confidence values are heuristic 0..1 scores, not calibrated probabilities.

`line_start_sample`, `row_audio_end_sample`, and `emitted_at_sample` support row-latency measurement. For Robot and Martin, end is the physical scan's required end; for PD's first row it is the end of Cb, before the second Y scan ends. `estimated_line_period_samples` follows the mode's nominal physical scan period: Robot24 200.0125 ms, Robot36 150 ms, Robot72 300 ms, MartinM1 446.446 ms, MartinM2 226.798 ms, PD120 508.48 ms, and PD180 754.24 ms. `sample_clock_error_ppm` describes timing, separately from audio frequency correction.

`sync_jitter_samples` reports weighted RMS residual in the current robust line fit. `timing_confidence` accounts for that residual and observation confidence as well as inlier count. An inconsistent new fit can lower reported confidence while the decoder retains its previously learned clock through the disturbance.

`frequency_reference_source` can report `raw_sync_fit` when qualified raw reference tones establish the frequency correction. Its confidence aggregates received fit evidence; it remains heuristic. Earlier acquisition can change an unknown-start segment's recovered framing, while `protocol_row_index` correctly remains `null`.

Quality events are throttled to one per received audio second. Envelope noise is an approximate variability indicator, not a measured RF SNR; impulse counts are heuristic. Detailed development observations go to stderr with `--diagnostics`.

`auto_noise_reduction` reports the configured automatic mode. `reference_noise_ratio` reports unexplained power in received constant-tone PCM, or `null` before a usable observation; it is not a calibrated RF SNR. `automatically_noise_reduced_channels` counts channels treated since process start. `noise_reduction_strength` is the separate manual override value, normally zero during automatic operation. The `ready` event also reports the automatic mode.

The `png` in completion is the authoritative lossless RGB image built from newest row revisions. Partial height covers recovered output positions; original vertical placement remains unknown if header-free. Missing rows/spans remain explicitly represented in metadata. `decoded_row_count` excludes rows flagged missing, `output_row_count` includes every emitted output position, and `recovered_row_count` counts inferred timing. `unknown_tail_rows` is only meaningful for a known beginning. A protocol-length result can still have missing flagged rows: `image_complete` does **not** certify flawless reception.

Reasons currently emitted: `normal_end`, `next_image_started`, `eof`, `lost_signal`, `manual_reset`, `audio_discontinuity`, `unrecoverable_sync_loss`. An unknown-start segment is always `image_partial`, even if 240/496 local rows arrive. Nominal elapsed time alone never starts or completes an image; validated acquisition and progressively extracted channels are required.
