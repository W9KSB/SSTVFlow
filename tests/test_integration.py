import base64
import io
import numpy as np
import pytest
from PIL import Image
from sstv_decoder.decoder import Decoder
from signals import generate_robot36, make_test_image
from pd_signals import generate_pd120, make_pd_test_image
from test_decoder import pcm_bytes, decode, final_rows


@pytest.mark.parametrize("rate",[16000,44100,48000])
def test_pd120_progressive_and_eof(rate):
    pcm=generate_pd120(sample_rate=rate,rows=8)
    decoder,events=decode(pcm_bytes(pcm),rate,eof=False)
    assert len(final_rows(events))>=7
    # The first row depends on first Y/Cr/Cb, not the following Y or full image.
    first=next(e for e in events if e["type"]=="row")
    first_required=.91+.020+.002080+3*.1216
    assert abs(first["row_audio_end_sample"]/rate-first_required)<.002
    assert first["emitted_at_sample"]/rate<first_required+.04
    assert not any(e["type"].startswith("image_p") for e in events)
    decoder.eof()
    assert events[-1]["output_row_count"]==8


def test_pd120_chunk_boundaries():
    data=pcm_bytes(generate_pd120(sample_rate=16000,rows=4))
    expected=final_rows(decode(data,chunk=len(data))[1])
    for size in (4096,137,2,1):
        assert final_rows(decode(data,chunk=size)[1])==expected


def test_pd120_offset_clock_and_missing_sync():
    data=pcm_bytes(generate_pd120(sample_rate=16000,rows=30,offset_hz=-65,
                                  timing_scale=.999,missed_sync_pairs=[3,4]))
    decoder,events=decode(data,eof=False)
    status=decoder.status()
    assert abs(status["frequency_offset_hz"]+65)<5
    assert abs(status["sample_clock_error_ppm"]+1000)<100
    assert any("timing_recovered" in e.get("quality_flags",[]) for e in events)
    decoder.eof()
    assert events[-1]["output_row_count"]==30


def test_pd120_without_vis():
    pcm=generate_pd120(sample_rate=16000,rows=20,include_header=False)
    _,events=decode(pcm_bytes(pcm))
    start=next(e for e in events if e["type"]=="image_start")
    assert start["mode"]=="PD120"
    assert not start["beginning_known"]
    assert len(final_rows(events))>=18


def test_mixed_partial_headers_separate_images():
    robot=pcm_bytes(generate_robot36(sample_rate=16000,rows=8))
    pd=pcm_bytes(generate_pd120(sample_rate=16000,rows=8))
    _,events=decode(robot+pd+robot+pd)
    starts=[e for e in events if e["type"]=="image_start"]
    finishes=[e for e in events if e["type"] in ("image_complete","image_partial")]
    assert [e["mode"] for e in starts]==["Robot36","PD120","Robot36","PD120"]
    assert len({e["image_id"] for e in starts})==len(finishes)==4


def test_clean_robot_detail_gate():
    source=make_test_image()
    _,events=decode(pcm_bytes(generate_robot36(source,sample_rate=16000)))
    complete=next(e for e in events if e["type"]=="image_complete")
    result=np.asarray(Image.open(io.BytesIO(base64.b64decode(complete["png"]))))
    mse=np.mean((result.astype(float)-np.asarray(source).astype(float))**2)
    assert 10*np.log10(255**2/mse)>28
    # A known fine checkerboard must retain substantial luma contrast.
    assert np.std(result[110:145,8:70].astype(float))>90


@pytest.mark.parametrize("mode",["Robot36","PD120"])
def test_noise_fading_drift_impulses_remain_recoverable(mode):
    generator=generate_robot36 if mode=="Robot36" else generate_pd120
    pcm=generator(sample_rate=16000,rows=30,noise_snr_db=24,
                  drift_hz_per_second=.5,fades=[(2,.2,.08)],impulses=[(3,2.0)])
    _,events=decode(pcm_bytes(pcm))
    assert len(final_rows(events))>=25
    assert events[-1]["type"]=="image_partial"


def test_white_pink_noise_and_random_tones_do_not_acquire():
    rate=16000
    rng=np.random.default_rng(4)
    white=rng.normal(0,.08,rate*3)
    pink=np.cumsum(white)
    pink=.1*pink/max(abs(pink))
    tones=np.concatenate([.2*np.sin(2*np.pi*f*np.arange(rate//5)/rate)
                          for f in rng.uniform(900,2600,20)])
    for pcm in (white,pink,tones):
        _,events=decode(pcm_bytes(pcm))
        assert not any(e["type"]=="image_start" for e in events)

