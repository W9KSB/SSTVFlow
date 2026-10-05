import base64
import numpy as np
from sstv_decoder.decoder import Decoder
from signals import generate_robot36
from test_decoder import pcm_bytes, final_rows
from sstv_decoder.pixels import coherent_pixel_frequency, adaptive_channel_noise_reduction
from sstv_decoder.sync import reference_noise_ratio
from sstv_decoder.dsp import FrequencyBuffer
import pytest


def run(pcm,strength):
    events=[]
    decoder=Decoder(16000,events.append)
    if strength is not None:
        decoder.control({"command":"noise_reduction","strength":strength})
    decoder.feed(pcm_bytes(pcm))
    decoder.eof()
    rows=final_rows(events)
    return np.stack([np.frombuffer(base64.b64decode(rows[i]),np.uint8).reshape(320,3)
                     for i in sorted(rows)])


def test_noise_bypass_preserves_clean_pixels():
    pcm=generate_robot36(sample_rate=16000,rows=10)
    assert np.array_equal(run(pcm,None),run(pcm,0))


def test_optional_noise_reduction_reduces_flat_field_noise():
    image=np.full((20,320,3),128,np.uint8)
    pcm=generate_robot36(image,sample_rate=16000,noise_snr_db=24)
    direct=run(pcm,0)[4:,8:-8].astype(float)
    reduced=run(pcm,.6)[4:,8:-8].astype(float)
    assert np.std(reduced)<np.std(direct)*.95
    assert abs(np.mean(reduced)-np.mean(direct))<2


def test_coherent_pixels_reject_phase_poles_without_cross_pixel_blur():
    expected=np.tile([1500.,2300.],160)
    frequencies=np.broadcast_to(expected,(13,320)).copy()
    amplitudes=np.ones_like(frequencies)
    previous=amplitudes.copy()
    frequencies[6]=15000
    amplitudes[6]=1e-8
    actual=coherent_pixel_frequency(frequencies,amplitudes,previous,48000)
    np.testing.assert_allclose(actual,expected,atol=1e-4)
    assert np.max(abs(np.mean(frequencies,axis=0)-expected))>900


def test_local_noise_filter_preserves_a_strong_edge():
    rng=np.random.default_rng(8)
    source=np.r_[np.full(160,1550.),np.full(160,2250.)]
    received=source+rng.normal(0,60,320)
    filtered=adaptive_channel_noise_reduction(received)
    assert np.std(filtered[10:145])<np.std(received[10:145])*.75
    assert np.mean(filtered[170:310])-np.mean(filtered[10:145])>650
    assert np.argmax(np.diff(filtered))==159


def test_reference_noise_detects_additive_noise_in_a_constant_tone():
    rate=16000
    samples=.5*np.sin(2*np.pi*1200*np.arange(320)/rate+.3)
    def measure(pcm):
        history=FrequencyBuffer(rate)
        history.append(np.arange(len(pcm)),pcm,np.abs(pcm))
        return reference_noise_ratio(history,rate,100,1200,0)
    assert measure(samples)<1e-10
    assert measure(samples+np.random.default_rng(1).normal(0,.12,len(samples)))>.02


def test_automatic_noise_reduction_activates_without_controls():
    image=np.full((20,320,3),128,np.uint8)
    pcm=generate_robot36(image,sample_rate=16000,noise_snr_db=12)
    automatic=run(pcm,None)[4:,8:-8].astype(float)
    direct=run(pcm,0)[4:,8:-8].astype(float)
    assert np.std(automatic)<np.std(direct)*.85
    assert abs(np.mean(automatic)-np.mean(direct))<3


def test_noise_control_validates_then_switches_between_auto_and_manual():
    decoder=Decoder(16000,lambda event:None)
    decoder.control({"command":"noise_reduction","strength":0})
    assert not decoder.status()["auto_noise_reduction"]
    with pytest.raises(ValueError):
        decoder.control({"command":"noise_reduction","auto":True,"strength":.6})
    assert not decoder.status()["auto_noise_reduction"]
    decoder.control({"command":"noise_reduction","auto":True})
    assert decoder.status()["auto_noise_reduction"]
