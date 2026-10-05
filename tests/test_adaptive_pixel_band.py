import base64
import numpy as np
from sstv_decoder.decoder import Decoder
from signals import generate_robot36, make_test_image
from test_decoder import pcm_bytes, final_rows


class TrackingDecoder(Decoder):
    def __init__(self, *args, **kwargs):
        self.bands = []
        super().__init__(*args, **kwargs)

    def _pixel_band_reference(self, start, scale):
        super()._pixel_band_reference(start, scale)
        self.bands.append((self.next_line, self.active_pixel_band))


class AcquisitionOnlyDecoder(Decoder):
    def _pixel_band_reference(self, start, scale):
        pass


def receive(pcm, decoder_type=TrackingDecoder, method='quadrature', chunk=8192):
    events = []
    decoder = decoder_type(16000, events.append, method=method)
    data = pcm_bytes(pcm)
    for i in range(0,len(data),chunk):
        decoder.feed(data[i:i+chunk])
    decoder.eof()
    rows = final_rows(events)
    image = np.stack([np.frombuffer(base64.b64decode(rows[i]), np.uint8).reshape(320,3)
                      for i in sorted(rows)])
    return decoder, image


def test_clean_vis_later_interference_then_clean_detail_recovery():
    rate = 16000
    image = np.asarray(make_test_image())[104:152]
    clean = generate_robot36(image, sample_rate=rate)
    pcm = clean.copy()
    first, last = round((.91 + 8*.15)*rate), round((.91 + 24*.15)*rate)
    t = np.arange(last-first)/rate
    pcm[first:last] += .65*np.sin(2*np.pi*3050*t + .2)
    decoder, actual = receive(pcm)
    _, baseline = receive(pcm, AcquisitionOnlyDecoder)
    assert all(band == 'quadrature' for row,band in decoder.bands[:8])
    assert any(band == 'narrow' for row,band in decoder.bands[10:24])
    assert all(band == 'quadrature' for row,band in decoder.bands[34:])
    np.testing.assert_array_equal(actual[:6], baseline[:6])
    np.testing.assert_array_equal(actual[36:], baseline[36:])
    _, expected = receive(clean, AcquisitionOnlyDecoder)
    error = lambda received: np.mean((received[12:22].astype(float)-expected[12:22])**2)
    assert error(actual) < error(baseline)*.7
    fragmented, fragmented_image = receive(pcm, chunk=1001)
    large, large_image = receive(pcm, chunk=65536)
    assert fragmented.bands == large.bands == decoder.bands
    np.testing.assert_array_equal(fragmented_image,actual)
    np.testing.assert_array_equal(large_image,actual)


def test_band_hysteresis_rejects_isolated_pulse_and_requires_clean_recovery():
    class Reference:
        def __init__(self):
            self.error = 0
        def interval(self,begin,end):
            return np.full(80,1200+self.error)
    decoder = Decoder(16000,lambda event:None)
    decoder.history,decoder.protocol_history = Reference(),Reference()
    decoder.initial_pixel_band = 'quadrature'
    def reference(broad,narrow):
        decoder.history.error,decoder.protocol_history.error = broad,narrow
        decoder._pixel_band_reference(0,1)
    for errors in ((10,10),(10,10),(500,50),(10,10),(10,10)):
        reference(*errors)
        assert decoder.active_pixel_band == 'quadrature'
    reference(500,50)
    reference(500,50)
    assert decoder.active_pixel_band == 'narrow'
    for _ in range(6):
        reference(10,10)
        assert decoder.active_pixel_band == 'narrow'
    reference(100,90)
    for _ in range(7):
        reference(10,10)
        assert decoder.active_pixel_band == 'narrow'
    reference(10,10)
    assert decoder.active_pixel_band == 'quadrature'


def test_clean_fine_pixels_preserve_acquisition_only_output():
    pcm = generate_robot36(np.asarray(make_test_image())[104:128], sample_rate=16000)
    decoder, actual = receive(pcm)
    _, baseline = receive(pcm, AcquisitionOnlyDecoder)
    assert all(band == 'quadrature' for _,band in decoder.bands)
    np.testing.assert_array_equal(actual, baseline)


def test_explicit_narrow_retains_requested_filter():
    pcm = generate_robot36(rows=12, sample_rate=16000)
    decoder, _ = receive(pcm, method='narrow')
    assert all(band == 'narrow' for _,band in decoder.bands)
