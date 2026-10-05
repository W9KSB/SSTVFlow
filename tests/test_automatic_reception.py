"""Receive shifted, clock-mismatched audio without any configuration commands."""
import pytest
from signals import generate_robot36
from pd_signals import generate_pd120
from test_decoder import decode, pcm_bytes, final_rows


@pytest.mark.parametrize("mode,offset,scale",[
    ("Robot36",70,1.001),("PD120",-65,.999)])
@pytest.mark.parametrize("header",[True,False])
def test_automatic_mode_frequency_and_clock(mode,offset,scale,header):
    generator=generate_robot36 if mode=="Robot36" else generate_pd120
    pcm=generator(sample_rate=16000,rows=40,offset_hz=offset,
                  timing_scale=scale)
    if not header:
        pcm=pcm[round(.91*scale*16000):]
    decoder,events=decode(pcm_bytes(pcm),eof=False)
    start=next(e for e in events if e["type"]=="image_start")
    assert start["mode"]==mode
    assert start["beginning_known"]==header
    assert len(final_rows(events))>=36
    status=decoder.status()
    assert abs(status["frequency_offset_hz"]-offset)<5
    assert abs(status["sample_clock_error_ppm"]-(scale-1)*1e6)<150
    decoder.eof()
