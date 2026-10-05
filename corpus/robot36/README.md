# Real Robot 36 reception corpus

These are real ISS RF receptions from ARISS Expedition 74 Series 31 (April 10–14, 2026), downloaded from SatNOGS. Original `.ogg` recordings are unchanged. Full `.wav` files are decoded mono 48 kHz PCM16 audio, without newly generating SSTV. `frame_*.wav` files contain approximately 37.4 seconds from the original capture around one complete image.

`manifest.json` records source URLs, observer and station identities, acquisition times, source intervals, hashes, and independently measured VIS bits. Every saved frame crop has recorded VIS 8 and valid even parity. This measurement uses the received header tones, independently of the decoder under development. The stale SatNOGS PD120 transmitter label for observation 13773866 is contradicted by its measured VIS 8.

Reference JPEGs were posted by receivers on the linked Libre Space Community discussion. These are visual comparisons from independent decodes, not pixel-exact transmitter originals. Preserve uploader credit and source URLs; no specific JPEG license has been verified. SatNOGS API documentation states that its API data are distributed under CC BY-SA; the exact API documentation URL is recorded in the manifest.

The corpus includes clear reception (13773866), a lower-elevation receiver (13778819), and a noisier reference (13779372). Automated SatNOGS demodulated PNGs are excluded as references because operators reported that the network SSTV flowgraph did not support Robot 36 for this event. The protocol implementation source was never read or copied to acquire or measure this corpus.
