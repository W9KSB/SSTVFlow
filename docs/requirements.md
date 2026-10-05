Build a generic, headless SSTV decoder optimized for maximum image quality and genuine line-by-line decoding during live reception.

The decoder must remain a standalone component with no application-specific dependencies.

The initial implementation must support ONLY:

- Robot 36
- PD120

Do not add additional SSTV modes until these two modes are implemented, tested, and producing excellent results.

Image quality is the primary acceptance criterion.

A decoder that technically recognizes the mode and completes an image but produces blurry detail, incorrect colors, slanted lines, poor synchronization, or unstable alignment is not considered successful.

The quality target is:

- sharp fine detail
- readable small text
- accurate and stable colors
- straight vertical edges
- correct horizontal alignment
- minimal row jitter
- correct chroma reconstruction
- automatic mistuning correction
- automatic slant correction
- reliable recovery through noise
- reliable recovery through fading
- reliable recovery through missed sync pulses
- resilience to transmitter/receiver clock mismatch

Do not sacrifice clean-signal image quality merely to make weak signals appear smoother.

# DEVELOPMENT PRIORITY

Implement in this order:

1. Robot 36
2. PD120

Robot 36 must be fully functional and validated before substantial PD120-specific work begins.

Once Robot 36 is working, improve it until its real-world output quality is competitive with strong established desktop SSTV decoders.

Then implement PD120 using the same reusable DSP, timing, synchronization, and image-processing infrastructure wherever practical.

Do not implement unrelated modes, generic mode tables for dozens of formats, speculative future compatibility, or unnecessary abstraction before Robot 36 and PD120 meet the acceptance criteria.

Optimize the architecture so more modes can be added later, but do not let future extensibility interfere with current image quality.

# EXECUTABLE CONTRACT

Run as a persistent process:

    decoder <sample_rate_hz>

At minimum support:

- 16000 Hz
- 44100 Hz
- 48000 Hz

The decoder must remain running across multiple SSTV transmissions.

It must not require restarting between images.

# AUDIO INPUT CONTRACT

Receive raw signed 16-bit little-endian mono PCM through standard input.

Each sample occupies exactly two bytes.

Sample values range from:

    -32768 through 32767

stdin contains PCM audio only.

There are:

- no WAV headers
- no packet headers
- no timestamps
- no framing
- no separators
- no embedded commands

The calling application selects the desired receiver/audio channel before sending PCM.

Reads may contain arbitrary byte counts.

If a read ends with one unmatched byte, preserve it and combine it with the next read.

Chunk boundaries have no protocol meaning.

A read may begin or end:

- inside an SSTV tone
- inside a sync pulse
- inside a scan line
- inside a pixel interval
- anywhere in an image

Preserve all decoder and DSP state across reads.

This includes:

- filter state
- resampler state
- frequency-estimator state
- PLL state if used
- synchronization state
- clock/slant estimator state
- VIS acquisition state
- line timing state
- chroma state
- image state

Use sample counts and the declared sample rate as the decoder timebase.

Never use stdin delivery speed as signal timing.

Temporary pauses in input delivery are not transmission boundaries.

Actual silence must arrive as PCM samples.

Support multiple consecutive transmissions without restarting.

EOF must:

- drain usable buffered DSP samples
- finalize recoverable images
- emit partial completion if appropriate
- cleanly terminate

# CONTROL INTERFACE

stdin must remain raw PCM only.

Runtime control commands must therefore use a separate interface.

Implement either:

- a secondary file descriptor using newline-delimited JSON, or
- a Unix-domain socket using newline-delimited JSON

Document the selected mechanism clearly.

The control interface must support at minimum:

- reset decoder
- force Robot 36
- force PD120
- return to automatic mode detection
- manually specify frequency offset
- enable automatic frequency correction
- disable automatic frequency correction
- manually specify slant/timing correction
- enable automatic slant correction
- disable automatic slant correction
- adjust horizontal phase/offset
- enable optional impulse rejection
- disable optional impulse rejection
- enable optional noise reduction
- disable optional noise reduction
- report known audio discontinuity/sample loss
- query decoder status

A control reset must clearly define which state is discarded.

A stream discontinuity event must preserve already recovered image rows whenever possible.

# GENUINE STREAMING REQUIREMENT

This must be a true streaming decoder.

Decode and emit image rows while the SSTV transmission is still being received.

Never require:

- a complete recording
- nominal mode duration
- complete image reception
- EOF

before outputting useful image data.

Robot 36 and PD120 must visibly build line-by-line during live reception.

Do not fake streaming by buffering nearly the entire transmission and releasing rows at the end.

Use bounded lookahead only where technically necessary for:

- filtering
- sync validation
- timing estimation
- chroma reconstruction
- adjacent-line processing

Measure and distinguish:

- acquisition latency
- steady-state row latency

Rows should normally be emitted shortly after sufficient audio for that row has arrived.

Allow provisional rows.

A row may later be replaced using a row_revision event if additional information improves:

- timing
- horizontal placement
- slant estimate
- chroma reconstruction
- color alignment

A final refinement pass is allowed after reception finishes.

However, the live progressive image must already be useful and correctly aligned.

Do not repeatedly reprocess the entire recording from the beginning.

Steady-state computation should remain approximately proportional to newly arriving audio.

# INTERNAL TIMEBASE

Maintain an absolute internal sample timeline.

Every important protocol event should be associated with an absolute or fractional sample position.

Examples:

- VIS start
- VIS bit centers
- sync edges
- line starts
- porch transitions
- channel boundaries
- pixel sampling locations

Do not base protocol timing on stdin chunk positions.

Support fractional-sample timing where necessary.

# RECOMMENDED INTERNAL ARCHITECTURE

Keep the following logical stages separated:

1. PCM ingestion
2. signal conditioning
3. optional resampling/internal-rate conversion
4. tone/frequency estimation
5. protocol-tone detection
6. VIS acquisition
7. sync detection
8. frequency-offset estimation
9. sample-clock/line-period estimation
10. line timing prediction
11. mode-specific channel extraction
12. pixel reconstruction
13. color reconstruction
14. row-quality estimation
15. image-state management
16. output event generation

Avoid coupling DSP operations directly to stdin read sizes.

# DSP QUALITY

Implement tone-frequency measurement with enough time resolution to preserve fine SSTV detail.

Evaluate multiple suitable methods using actual recordings.

Candidates include:

- analytic-signal / Hilbert-phase estimation
- quadrature phase discrimination
- PLL-based tracking
- short-window frequency estimators
- hybrid methods

Do not select an algorithm merely because it is theoretically elegant.

Compare methods based on actual decoded image quality.

Important image-quality criteria include:

- text readability
- horizontal detail
- straight vertical edges
- low pixel smear
- stable color
- low row jitter
- accurate sync placement

Preserve rapid frequency transitions representing fine image detail.

Do not excessively smooth frequency estimates.

Apply appropriate input band limiting without damaging SSTV timing or detail.

Preserve:

- sync pulse edges
- porch intervals
- pixel transitions
- channel boundaries

Maintain DSP filter state continuously across arbitrary input chunks.

If resampling is used, preserve resampler state across chunks.

Explicitly account for DSP group delay.

Do not allow filter delay to silently shift:

- sync timing
- luminance
- chrominance
- pixel positions

# INPUT QUALITY MONITORING

Detect and report:

- DC offset
- clipping
- extremely low input level
- excessive noise
- impulsive interference
- prolonged silence

Do not automatically normalize every signal in a way that changes protocol tone measurements.

If AGC is implemented internally, it must not alter frequency information or protocol timing.

Avoid speech-oriented processing.

Do not use processing designed for voice such as:

- echo cancellation
- voice enhancement
- speech denoising
- aggressive speech AGC

if it damages SSTV tones.

# NOISE REDUCTION

Provide optional SSTV-appropriate noise reduction.

It must be:

- adjustable
- bypassable
- conservative by default

Clean-signal detail must remain intact.

A denoising algorithm that makes weak images smoother but noticeably damages fine detail on clean images is unacceptable as the default.

Provide optional impulse-noise rejection.

Impulse rejection should target isolated broadband spikes without unnecessarily affecting valid SSTV transitions.

# FREQUENCY OFFSET CORRECTION

Automatically estimate receiver/transmitter audio frequency offset.

Use known SSTV protocol tones where confidence is high.

Potential references include:

- leader tones
- break tones
- VIS tones
- sync tones
- known reference intervals

Estimate initial offset during acquisition.

Continue tracking slow drift during reception.

Use confidence-weighted measurements.

Do not allow:

- picture content
- random noise
- RF fading
- false sync candidates
- isolated interference

to pull a stable frequency estimate significantly away from its established value.

Reject low-confidence measurements.

Frequency correction must not create visible:

- brightness drift
- hue drift
- color shifts
- row-to-row instability

Expose diagnostics including:

- measured offset in Hz
- applied offset in Hz
- confidence
- lock status
- reference source used

Support manual frequency offset adjustment through the control interface.

# FREQUENCY ERROR VS CLOCK ERROR

Treat audio-frequency offset and sample-clock mismatch as separate problems.

Do not use frequency correction as a substitute for timing correction.

Do not use slant correction as a substitute for frequency correction.

Maintain separate estimates for:

- frequency offset
- actual line period
- sample-clock error
- line-start phase

# VIS DETECTION

Support automatic VIS detection.

Validate the full expected VIS structure.

Use:

- leader detection
- break detection
- start-bit timing
- VIS data-bit timing
- parity validation
- stop condition

Perform false-trigger rejection.

Random voice, music, noise, carrier tones, or arbitrary narrowband signals must not frequently trigger false SSTV acquisitions.

Robot 36 and PD120 must both be detectable automatically when valid VIS is present.

Expose VIS confidence.

# MISSING OR DAMAGED VIS

VIS failure must not automatically prevent image recovery.

When the header is missing or damaged, attempt acquisition using repeated line structure.

For Robot 36 and PD120, use evidence such as:

- sync frequency
- sync duration
- line period
- porch timing
- channel duration
- channel arrangement

Score candidate modes.

If Robot 36 and PD120 cannot be distinguished confidently, report ambiguity.

Do not invent certainty.

# SYNC DETECTION

Detect line sync using more than tone frequency alone.

Use combinations of:

- expected sync frequency
- duration
- timing window
- expected cadence
- surrounding protocol structure
- historical line prediction

Assign confidence to each candidate.

Reject false sync caused by:

- image content
- narrowband interference
- noise bursts
- unrelated tones

Once line timing is established, predicted timing should constrain later sync searches strongly.

A single false sync pulse must not move the entire remainder of the image.

# LINE TIMING

Estimate the actual received line period.

Do not assume the nominal protocol period exactly matches the incoming signal.

Estimate transmitter/receiver clock mismatch.

Use robust estimation.

Appropriate techniques may include:

- regression
- weighted regression
- robust fitting
- outlier rejection
- Kalman-style estimation
- PLL-style timing estimation

Choose based on stability and measured image quality.

A handful of poor sync measurements must not ruin the timing model.

# AUTOMATIC SLANT CORRECTION

Correct image slant automatically during live reception.

Maintain an estimate of the actual line period and compare it with the nominal mode timing.

Track gradual timing error.

Apply corrections continuously without producing visible row jumps.

Do not convert tiny sync measurement noise into horizontal row jitter.

Timing correction should be deliberately smoother than individual noisy measurements.

Maintain at least:

- estimated line period
- sample-clock error
- predicted next line start
- line-start phase
- timing confidence

Use fractional-sample alignment when needed.

Integer-sample-only alignment is not acceptable if it causes visible stair-stepping or jitter.

# SYNC LOSS AND RECOVERY

Maintain predicted timing through short fades or missed sync pulses.

Do not immediately abandon timing lock because a single line sync is missing.

When sync returns, reacquire smoothly.

One missed sync pulse must not shift every following row.

Use expected cadence to infer missing line starts where confidence is sufficient.

Mark inferred timing appropriately in row-quality metadata.

# HORIZONTAL ALIGNMENT

Do not assume the detected sync edge equals pixel zero.

Follow the actual Robot 36 and PD120 protocol timing.

Account for:

- sync duration
- porch interval
- channel transition timing
- filter/group delay
- frequency-estimator delay
- pixel sampling phase

Correct horizontal placement precisely.

Allow manual horizontal offset adjustment.

Where useful, estimate fractional horizontal sampling phase that maximizes stable vertical detail.

Prevent slow horizontal wandering over the image.

# ROBOT 36 IMPLEMENTATION

Robot 36 is the first and highest-priority mode.

Implement the documented Robot 36 transmission structure exactly.

Correctly handle:

- VIS code
- line synchronization
- luminance timing
- chrominance timing
- alternating chroma behavior
- color scaling
- line timing
- pixel timing

Robot 36 chroma reconstruction is especially important.

Do not simply stretch chroma samples independently per line if the protocol shares or alternates chroma information across adjacent rows.

Maintain the required chroma phase/parity state explicitly.

A missed or damaged line must not permanently reverse chroma interpretation for subsequent rows.

Track separately:

- physical received scan line
- output image row
- Robot chroma phase/parity

Recover correct phase after missed lines whenever protocol evidence permits.

Interpolate chroma appropriately while preserving luminance sharpness.

Do not unnecessarily blur the luminance channel.

Handle:

- first image row
- last image row
- missing adjacent chroma
- partial captures
- mid-image acquisition

explicitly.

Progressive live rows and final output must show consistent colors.

Robot 36 must be the first mode used for detailed regression and image-quality optimization.

# PD120 IMPLEMENTATION

Implement PD120 only after the common DSP and timing infrastructure is stable with Robot 36.

Follow PD120's documented protocol exactly.

Correctly implement:

- VIS identification
- sync structure
- line timing
- channel order
- Y/chrominance timing
- color conversion
- pixel dimensions
- image dimensions
- chroma handling

Do not infer PD120 behavior from Robot 36 assumptions.

Treat PD120 as its own documented protocol family while sharing generic DSP infrastructure.

Because PD120 has substantially higher image resolution, use it as a stringent test for:

- fine-detail preservation
- pixel-phase accuracy
- line-start precision
- sample-clock estimation
- slant correction
- edge sharpness
- color registration

Small systematic timing errors that are barely visible in Robot 36 may become obvious in PD120 and must be corrected.

# COLOR RECONSTRUCTION

Implement each mode's actual color model and scaling.

Do not use arbitrary color correction merely to make images visually pleasing.

Protocol decoding must produce technically correct RGB values first.

Display adjustments must remain separate.

Support optional post-processing controls such as:

- brightness
- contrast
- gamma
- saturation

These must default to neutral.

Do not bake them into SSTV decoding.

# PIXEL SAMPLING

Map tone frequency to protocol-defined pixel values accurately.

Avoid naive averaging over excessively long windows.

The estimator must preserve fine horizontal transitions.

Evaluate:

- sample-center strategy
- integration-window width
- overlapping windows
- fractional timing
- interpolation

against real recordings.

Pixel extraction should be stable without artificially reducing spatial resolution.

# ROW JITTER CONTROL

Do not independently realign every row based solely on its latest noisy sync measurement.

Maintain a global timing model.

Individual sync observations should update the model according to confidence.

The result should preserve:

- straight vertical edges
- stable text
- smooth image geometry

while still adapting to real transmitter clock error.

# MID-TRANSMISSION ACQUISITION

Support reception beginning in the middle of an SSTV image.

Recover as much useful content as possible.

Do not invent an original vertical row number if it cannot be known.

Track separately:

- received row sequence
- output row sequence
- known protocol row index
- estimated protocol row index
- unknown original position

Expose uncertainty in metadata.

Partial images are valid results.

Do not discard them just because the header or first rows were missed.

# SIGNAL LOSS

Distinguish between:

1. continuous but noisy RF
2. RF fading
3. loss of synchronization
4. silence
5. externally reported missing audio samples

Raw PCM cannot reveal dropped samples upstream.

Use the control interface for known discontinuities.

After a reported discontinuity:

- preserve already recovered rows
- invalidate timing assumptions that require continuous sample numbering where necessary
- safely reacquire timing
- mark affected regions
- report partial/recovered status

Do not silently assume continuity after the caller reports sample loss.

# IMAGE CONCEALMENT AND CONFIDENCE

Do not fabricate apparently valid image content simply to fill gaps.

Track whether row regions are:

- directly decoded
- timing-recovered
- interpolated
- concealed
- missing

A compact per-row or per-span quality representation is acceptable.

Per-pixel metadata is not required unless useful.

# OUTPUT CONTRACT

Emit newline-delimited JSON through stdout.

stdout must contain machine-readable JSON only.

Human-readable logs and diagnostics must go to stderr.

Flush important events promptly.

Every JSON event must contain a type field.

Support at minimum:

- ready
- acquisition
- image_start
- row
- row_revision
- quality
- status
- image_complete
- image_partial
- warning
- error

# READY EVENT

After initialization, emit:

    {
      "type": "ready",
      ...
    }

Include at minimum:

- sample rate
- supported modes
- decoder version

# ACQUISITION EVENT

When acquisition begins or changes, emit useful information including:

- candidate mode
- acquisition source
- VIS result if available
- confidence
- frequency offset
- timing confidence

# IMAGE START EVENT

Each image must receive a unique image ID.

image_start must include at minimum:

- image ID
- mode
- width
- nominal height
- acquisition source
- acquisition confidence
- whether the beginning of the image is known
- whether row numbering from the transmitter is known

# ROW EVENT

Each row event must contain:

- type
- image ID
- zero-based output row index
- width
- revision number
- base64-encoded RGB888 pixel bytes
- row confidence
- quality flags

Decoded RGB payload length before base64 encoding must equal:

    width * 3

bytes.

revision begins at zero.

# ROW REVISION EVENT

When a previously emitted row is improved, emit row_revision.

Include:

- image ID
- row index
- new revision number
- complete replacement RGB888 row
- reason for revision
- updated confidence

Revision numbers must increase monotonically.

The latest revision supersedes all earlier revisions.

# QUALITY AND STATUS EVENTS

Expose useful live diagnostics including where available:

- mode
- frequency offset
- applied frequency correction
- signal level
- noise estimate
- clipping state
- sync confidence
- timing lock state
- estimated line period
- sample-clock error
- slant correction
- horizontal phase
- rows decoded
- rows recovered
- rows missing
- VIS confidence

Avoid excessive event spam.

Throttle purely informational status events to a sensible rate.

# IMAGE COMPLETION

Emit either:

- image_complete
- image_partial

Completion metadata should include:

- image ID
- mode
- completion reason
- decoded-row count
- missing-row count
- recovered-row count
- final frequency estimate
- final timing/clock estimate
- overall quality summary

Possible completion reasons should include clear values such as:

- normal_end
- next_image_started
- eof
- timeout
- lost_signal
- manual_reset
- unrecoverable_sync_loss

Do not label an image complete merely because nominal transmission duration elapsed if the protocol evidence does not support completion.

# FINAL IMAGE

The final authoritative image must be lossless.

Provide either:

1. PNG encoded as base64 in the completion event, or
2. a documented lossless RGB representation sufficient for the caller to construct the exact final image

Do not use JPEG as the authoritative result.

The final image must reflect the newest revision of every row.

If a final refinement pass changes rows, those changes must appear in final output.

# DIAGNOSTIC MODE

Provide optional detailed development diagnostics.

Useful diagnostics include:

- detected protocol tones
- tone-frequency estimates
- VIS bit decisions
- VIS confidence
- sync candidates
- sync candidate scores
- rejected sync candidates
- accepted sync positions
- predicted line positions
- measured line periods
- frequency-offset measurements
- sample-clock estimates
- slant estimates
- fractional line corrections
- horizontal phase estimates

Detailed diagnostics must not contaminate stdout JSON.

Send them to stderr or a separate diagnostic output.

# VALIDATION REQUIREMENTS

Validation must use real SSTV recordings.

Synthetic generated SSTV signals are useful for controlled tests, but synthetic self-round-trips alone do not prove decoding quality.

Maintain a regression corpus containing multiple real Robot 36 and PD120 recordings.

Include clean recordings and impaired recordings.

Whenever practical, compare the exact same recording with established SSTV decoder output.

Evaluation should consider:

- readable text
- fine-line detail
- edge sharpness
- vertical-edge straightness
- color fidelity
- chroma registration
- line jitter
- slant
- recovered content

Visual inspection is required.

Where a trustworthy reference image exists, also measure useful objective metrics such as:

- PSNR
- SSIM
- edge preservation
- geometric alignment error

Do not optimize solely for PSNR or SSIM.

A visually sharper and correctly aligned image may be preferable even if a generic metric favors smoothing.

# ROBOT 36 ACCEPTANCE TESTS

Robot 36 must be tested against:

- clean recordings
- low-SNR recordings
- fading
- frequency offset
- slow frequency drift
- clock mismatch
- slanted source recordings
- impulsive noise
- damaged VIS
- missing VIS
- missed sync pulse
- multiple missed sync pulses
- truncated image
- mid-image start
- back-to-back Robot 36 transmissions

Verify specifically:

- correct chroma phase
- no permanent color swap after damaged rows
- stable vertical edges
- correct slant removal
- live row output

# PD120 ACCEPTANCE TESTS

PD120 must receive equivalent testing.

Pay particular attention to:

- fine text
- fine horizontal detail
- edge sharpness
- color registration
- long-term timing drift
- cumulative slant
- horizontal sampling phase

Because PD120 has much higher image resolution than Robot 36, it should expose small systematic timing errors.

Do not accept a decoder that produces visibly soft PD120 images when the source recording contains sharper information.

# CHUNK-BOUNDARY INVARIANCE

The decoder output must not depend materially on stdin read boundaries.

Test identical PCM using:

- entire recording in large chunks
- fixed 4096-byte chunks
- fixed odd-size chunks
- randomized chunk sizes
- sample-by-sample reads
- one-byte reads

The resulting image must be equivalent apart from harmless timing differences in event delivery.

DSP state must remain correct across all chunk patterns.

# TRUE STREAMING TEST

Prove genuine streaming operation.

Feed a recording to stdin at approximately real-time speed.

Keep stdin open.

Verify that:

- image_start occurs before transmission completion
- rows appear progressively
- many rows are emitted before the complete recording has been sent
- the decoder does not wait for EOF

Measure:

- time from usable acquisition audio to image_start
- time from completion of a physical row in the input to row event emission

# BACK-TO-BACK IMAGE TEST

Feed:

- Robot 36 followed by Robot 36
- Robot 36 followed by PD120
- PD120 followed by Robot 36
- PD120 followed by PD120

without restarting the process.

Verify correct image separation and state reset.

No timing, frequency, mode, or chroma state from one image may corrupt the next image.

# FALSE ACQUISITION TESTS

Feed negative inputs such as:

- silence
- white noise
- pink noise
- continuous 1200 Hz tone
- continuous 1500 Hz tone
- continuous 1900 Hz tone
- continuous 2300 Hz tone
- voice recordings
- music
- random narrowband tones

The decoder must not fabricate valid-looking SSTV images.

False mode acquisition should be rare and recoverable.

# CLOCK-MISMATCH TESTS

Deliberately resample otherwise valid recordings to simulate receiver/transmitter clock differences.

Test both positive and negative error.

Verify:

- automatic line-period estimation
- automatic slant correction
- stable horizontal alignment
- no cumulative image lean
- no excessive row jitter

# FREQUENCY-OFFSET TESTS

Shift SSTV tone frequencies artificially.

Test several positive and negative offsets.

Verify:

- automatic offset acquisition
- correct grayscale/brightness mapping
- correct color
- stable tracking
- recovery after offset changes slowly during the image

Frequency tracking must not confuse clock mismatch with frequency offset.

# PERFORMANCE

Target Linux ARM64 as a primary deployment environment.

The decoder must sustain live decoding with processing headroom on reasonable Raspberry Pi-class hardware.

Measure:

- average CPU usage
- peak CPU usage
- memory consumption
- acquisition latency
- row latency

Avoid unbounded buffering.

Retain only the source information necessary for:

- bounded lookahead
- row revision
- final refinement
- diagnostics

if configured.

Do not retain the complete raw recording indefinitely unless an explicit debug option requests it.

# IMPLEMENTATION QUALITY

Use clear modular code.

Add unit tests for:

- timing calculations
- VIS decoding
- parity
- tone mapping
- frequency/pixel conversion
- Robot 36 channel timing
- Robot 36 chroma reconstruction
- PD120 channel timing
- color conversion
- row revision logic
- stream chunk handling
- odd-byte input handling
- discontinuity handling

Add integration tests using real PCM recordings.

Document:

- build procedure
- executable usage
- control interface
- JSON event schema
- diagnostics
- test procedure
- expected performance

# PROTOCOL IMPLEMENTATION

Implement Robot 36 and PD120 independently from documented SSTV protocol specifications and general DSP principles.

Do not copy another decoder's source code or implementation.

It is acceptable and encouraged to compare output quality against established decoders using identical recordings.

The goal is to independently produce a decoder whose output quality equals or exceeds common existing implementations.

# FINAL ACCEPTANCE STANDARD

The project is NOT complete merely when:

- VIS detection works
- both modes are recognized
- images are recognizable
- nominal dimensions are correct
- the decoder produces PNG files
- unit tests pass

The project is complete only when real Robot 36 and PD120 recordings produce consistently high-quality results.

The strongest clean recordings should produce:

- sharp detail
- readable fine text
- accurate colors
- straight vertical features
- negligible visible slant
- stable horizontal alignment
- low row jitter

Impaired recordings should degrade gracefully.

Timing or sync failures should not unnecessarily destroy the remainder of an otherwise recoverable image.

Most importantly:

Prioritize image quality over mode count, implementation convenience, theoretical elegance, or premature abstraction.

Get Robot 36 excellent.

Then get PD120 excellent.

Do not add more SSTV modes until both have been validated thoroughly.
