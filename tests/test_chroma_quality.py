import numpy as np

from sstv_decoder.color import guided_chroma_noise_reduction
from sstv_decoder.decoder import Decoder
from pd_signals import generate_pd120
from test_decoder import pcm_bytes


def test_native_chroma_noise_is_reduced_without_mutating_luminance():
    rng = np.random.default_rng(2)
    cr, cb = rng.normal(128, 10, (2, 640))
    y = np.full((2, 640), 128.)
    saved = y.copy()
    r, b = guided_chroma_noise_reduction(cr, cb, y)
    assert np.std(r) < np.std(cr) * .85
    assert np.std(b) < np.std(cb) * .85
    assert abs(r.mean() - cr.mean()) < .5
    assert abs(b.mean() - cb.mean()) < .5
    np.testing.assert_array_equal(y, saved)


def test_both_shared_rows_protect_luminance_and_isoluminant_color_edges():
    y = np.full((2, 160), 100.)
    y[1, 80] = 230  # Single-pixel stroke only in the second luminance row.
    cr = np.full(160, 110.)
    cr[80] = 150
    cb = np.full(160, 128.)
    r, _ = guided_chroma_noise_reduction(cr, cb, y)
    assert abs(r[80] - cr[80]) < .01
    # Even when Y has no edge, large color transitions remain in place.
    cr, cb = np.r_[np.full(80, 32.), np.full(80, 224.)], cb
    r, _ = guided_chroma_noise_reduction(cr, cb, np.full((2, 160), 100.))
    np.testing.assert_allclose(r, cr, atol=.01)


def test_pd_first_y_dropout_does_not_mark_good_second_y_missing():
    rate = 16000
    pcm = generate_pd120(sample_rate=rate, rows=4)
    pcm[round((.91 + .022080) * rate):round((.91 + .143680) * rate)] = 0
    events = []
    decoder = Decoder(rate, events.append)
    decoder.feed(pcm_bytes(pcm))
    decoder.eof()
    first = next(e for e in events if e['type'] == 'row' and e['row_index'] == 0)
    second = next(e for e in events if e['type'] == 'row' and e['row_index'] == 1)
    assert 'missing' in first['quality_flags']
    assert 'missing' not in second['quality_flags']
    assert second['row_confidence'] > .9


def test_noisy_pd_shared_chroma_revision_is_progressive():
    rate = 16000
    pcm = generate_pd120(sample_rate=rate, rows=8, noise_snr_db=12)
    events = []
    decoder = Decoder(rate, events.append)
    decoder.feed(pcm_bytes(pcm))
    decoder.eof()
    revisions = [e for e in events if e['type'] == 'row_revision']
    assert revisions
    assert all(e['reason'] == 'shared_chroma_refined' for e in revisions)
    initial = next(e for e in events if e['type'] == 'row')
    assert initial['emitted_at_sample'] / rate < .91 + .386880 + .04
