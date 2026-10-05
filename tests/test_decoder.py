import base64
import numpy as np
import pytest
from sstv_decoder.decoder import Decoder
from sstv_decoder.color import frequency_to_byte, ycrcb_to_rgb
from sstv_decoder.protocol import decode_vis
from sstv_decoder.timing import LineClock
from sstv_decoder.image import ImageState
from signals import generate_robot36, make_test_image


def pcm_bytes(pcm):
    return np.rint(np.clip(pcm,-1,32767/32768)*32768).astype("<i2").tobytes()


def decode(data, rate=16000, chunk=4096, eof=True):
    events=[]
    decoder=Decoder(rate,events.append)
    for start in range(0,len(data),chunk):
        decoder.feed(data[start:start+chunk])
    if eof:
        decoder.eof()
    return decoder,events


def final_rows(events):
    result={}
    for e in events:
        if e["type"] in ("row","row_revision"):
            assert len(base64.b64decode(e["rgb"]))==e["width"]*3
            result[e["row_index"]]=e["rgb"]
    return result


def test_vis_parity():
    bits=[1300,1300,1300,1100,1300,1300,1300,1100]
    assert decode_vis(bits)==8
    assert decode_vis(np.array(bits)+100,100)==8
    bits[-1]=1300
    assert decode_vis(bits) is None
    assert decode_vis([1200]*8) is None


def test_mapping_color():
    assert np.array_equal(frequency_to_byte([1500,2300]),[0,255])
    assert np.array_equal(ycrcb_to_rgb([16,235],[128,128],[128,128]),[[0,0,0],[255,255,255]])


def test_line_clock_rejects_outlier_and_estimates_fractional_period():
    clock=LineClock(48000,123.25)
    for n in range(100):
        clock.observe(n,123.25+n*7200*1.0007+(-1)**n*.2)
    assert abs(clock.status(100)["sample_clock_error_ppm"]-700)<3
    assert not clock.observe(100,clock.predict(100)+500)


@pytest.mark.parametrize("rate",[16000,44100,48000])
def test_progressive_robot36(rate):
    data=pcm_bytes(generate_robot36(sample_rate=rate,rows=8))
    decoder,events=decode(data,rate,eof=False)
    assert any(e["type"]=="image_start" for e in events)
    rows=final_rows(events)
    assert len(rows)>=7
    assert any(e["type"]=="row_revision" for e in events)
    assert not any(e["type"] in ("image_complete","image_partial") for e in events)
    decoder.eof()
    assert events[-1]["type"]=="image_partial"


def test_chunk_and_odd_byte_invariance():
    data=pcm_bytes(generate_robot36(sample_rate=16000,rows=4))
    expected=final_rows(decode(data,chunk=len(data))[1])
    assert expected
    for size in [4096,137,2,1]:
        assert final_rows(decode(data,chunk=size)[1])==expected
    rng=np.random.default_rng(1)
    events=[]
    decoder=Decoder(16000,events.append)
    start=0
    while start<len(data):
        size=int(rng.integers(1,9000))
        decoder.feed(data[start:start+size])
        start+=size
    decoder.eof()
    assert final_rows(events)==expected


def test_missed_sync_does_not_swap_chroma():
    clean=generate_robot36(sample_rate=16000,rows=12)
    bad=generate_robot36(sample_rate=16000,rows=12,missed_sync_lines=[3,4])
    a=final_rows(decode(pcm_bytes(clean))[1])
    _,events=decode(pcm_bytes(bad))
    b=final_rows(events)
    assert len(b)==12
    assert any("timing_recovered" in e.get("quality_flags",[]) for e in events)
    for line in range(6,12):
        x=np.frombuffer(base64.b64decode(a[line]),np.uint8).astype(float)
        y=np.frombuffer(base64.b64decode(b[line]),np.uint8).astype(float)
        assert np.mean(abs(x-y))<2


def test_offset_and_clock_are_separate():
    data=pcm_bytes(generate_robot36(sample_rate=16000,rows=40,offset_hz=70,timing_scale=1.001))
    decoder,events=decode(data,eof=False)
    status=decoder.status()
    assert abs(status["frequency_offset_hz"]-70)<5
    assert abs(status["sample_clock_error_ppm"]-1000)<100
    assert len(final_rows(events))>=39


def test_missing_vis_and_mid_image():
    pcm=generate_robot36(sample_rate=16000,rows=20)
    _,events=decode(pcm_bytes(pcm[round((.91+5*.15)*16000):]))
    start=next(e for e in events if e["type"]=="image_start")
    assert not start["transmitter_row_numbering_known"]
    assert len(final_rows(events))>=12


def test_revision_and_authoritative_image():
    events=[]
    state=ImageState(events.append,"Robot36",320,240,"test",1,False)
    a=np.zeros((320,3),np.uint8)
    state.row(0,a,1,[])
    state.row(0,a+128,1,[],"test")
    state.finish("eof",{})
    assert [e["revision"] for e in events if "revision" in e]==[0,1]
    from PIL import Image
    import io
    pixels=np.asarray(Image.open(io.BytesIO(base64.b64decode(events[-1]["png"]))))
    assert np.all(pixels==128)


def test_reset_discontinuity_and_control_validation():
    decoder,events=decode(pcm_bytes(generate_robot36(sample_rate=16000,rows=6)),eof=False)
    decoder.control({"command":"discontinuity","lost_samples":42})
    assert any(e["type"]=="image_partial" and e["completion_reason"]=="audio_discontinuity" for e in events)
    assert decoder.image is None
    for command in [{"command":"frequency","auto":"false"},
                    {"command":"horizontal","offset_ms":float("nan")},
                    {"command":"mode","mode":"MartinM1"}]:
        with pytest.raises(ValueError):
            decoder.control(command)
    decoder.control({"command":"reset"})
    decoder.eof()


@pytest.mark.parametrize("tone",[None,1200,1500,1900,2300])
def test_negative_acquisition(tone):
    rate=16000
    x=np.arange(rate*2)
    pcm=np.zeros(len(x)) if tone is None else .5*np.sin(2*np.pi*tone*x/rate)
    _,events=decode(pcm_bytes(pcm))
    assert not any(e["type"]=="image_start" for e in events)


def test_back_to_back_robot36():
    data=pcm_bytes(generate_robot36(sample_rate=16000,rows=240))
    _,events=decode(data+data)
    starts=[e for e in events if e["type"]=="image_start"]
    complete=[e for e in events if e["type"]=="image_complete"]
    assert len(starts)==len(complete)==2
    assert starts[0]["image_id"]!=starts[1]["image_id"]
