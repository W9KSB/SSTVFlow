# Real PD120 reception corpus

This corpus contains genuine ISS RF receptions from three events: April 2019, February 2025, and October 2025. Original Ogg recordings are downloaded from the archival URLs returned by the SatNOGS observation API and retained unchanged. Full WAVs and compact frame WAVs contain decoded mono 48 kHz PCM16 audio. No SSTV is newly synthesized and no amplitude normalization is applied.

Every saved frame has independently measured VIS95 with valid even parity. The measurement uses recorded calibration and 1100/1300Hz header tones and was performed without reading decoder implementation source. `manifest.json` preserves original URLs, observer/station identifiers, dates, source intervals, hashes, header evidence, and reference-image sources.

Observations 12496081 and 12493896 contain World Space Week 2025 images and mixed-in voice interference reported by multiple operators. Observation 11086741 contains the February 2025 Fram2Ham ISS exercise; the event asked receivers to post images to ARISS instead of social media, so its reference images are retained for local validation. Observation 585915 is the April 2019 weak-audio-modulation event, for which an operator reported successful independent decoding after 17dB audio amplification. The reference images show mostly coherent pictures with various interference lines; none is described as a pristine pixel-exact transmitter original.

Reference JPEGs/PNGs are independent received decodes. The starwatcher forum JPEG is explicitly paired by its owner with the source observation. SatNOGS PNGs are paired by their observation API records. Preserve attribution and URLs. SatNOGS API documentation states that API data are distributed under CC BY-SA; no separate forum-JPEG license was verified.

Frame crops include the full expected acquisition duration of a PD120 image: 0.91s calibration/VIS header plus 248 pairs at 508.48ms each. This ensures adequate source time span; it does not assert that every line survived RF interference or passed this project's decoder.
