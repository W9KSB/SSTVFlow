import numpy as np
import pytest
from sstv_decoder.dsp import FrequencyBuffer
from sstv_decoder.sync import fit_reference_offset, robot_porch_matches


def history(samples,rate):
    result=FrequencyBuffer(rate)
    result.append(np.arange(len(samples)),samples,np.abs(samples))
    return result


@pytest.mark.parametrize('offset',[-150.,2.4,150.])
def test_raw_reference_fit_estimates_true_offset_with_dc(offset):
    rate=16000
    samples=.3*np.cos(2*np.pi*(1200+offset)*np.arange(400)/rate+.7)+.13
    fitted=fit_reference_offset(history(samples,rate),rate,100,1200,offset+10)
    assert fitted is not None
    assert abs(fitted[0]-offset)<.03
    assert fitted[1]>.999


def test_raw_reference_fit_rejects_silence_noise_and_search_boundary():
    rate=16000
    for samples in (np.zeros(400),np.random.default_rng(2).normal(0,.1,400),
                    .3*np.sin(2*np.pi*1500*np.arange(400)/rate)):
        assert fit_reference_offset(history(samples,rate),rate,100,1200,0) is None


@pytest.mark.parametrize('tone,expected',[(1200,False),(1500,True),(1900,False)])
def test_porch_requires_expected_tone_and_rejects_competitors(tone,expected):
    rate=16000
    samples=.3*np.cos(2*np.pi*(tone+70)*np.arange(400)/rate+.6)+.1
    assert robot_porch_matches(history(samples,rate),rate,0,70)==expected
