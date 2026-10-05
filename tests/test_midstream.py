"""Exact caller use case: play only two arbitrary middle seconds, without VIS."""
from pathlib import Path
import wave
import numpy as np
import pytest
from sstv_decoder.decoder import Decoder
from signals import generate_robot36
from pd_signals import generate_pd120
from test_decoder import pcm_bytes, decode, final_rows


@pytest.mark.parametrize("mode",["Robot36","PD120"])
@pytest.mark.parametrize("offset",[-150,0,150])
def test_two_second_generated_midstream(mode,offset):
    generator=generate_robot36 if mode=="Robot36" else generate_pd120
    rate=16000
    pcm=generator(sample_rate=rate,rows=40,offset_hz=offset)
    clip=pcm[round(3.137*rate):round(5.137*rate)]
    decoder,events=decode(pcm_bytes(clip),rate,eof=False)
    start=next(e for e in events if e["type"]=="image_start")
    assert start["mode"]==mode
    assert not start["beginning_known"]
    assert len(final_rows(events))>=(10 if mode=="Robot36" else 4)
    rows=[e for e in events if e["type"]=="row"]
    assert all(e["protocol_row_index"] is None for e in rows)
    decoder.eof()
    assert events[-1]["type"]=="image_partial"


@pytest.mark.parametrize("mode,relative",[
    ("Robot36","corpus/robot36/frame_13773866_1.wav"),
    ("PD120","corpus/pd120/frame_11086741_1.wav")])
@pytest.mark.parametrize("start_seconds",[5.137,12.371,21.013])
def test_two_second_real_midstream(mode,relative,start_seconds):
    path=Path(__file__).resolve().parents[1]/relative
    if not path.exists():
        pytest.skip("download the documented real corpus first")
    with wave.open(str(path)) as wav:
        rate=wav.getframerate()
        wav.setpos(round(start_seconds*rate))
        data=wav.readframes(2*rate)
    decoder,events=decode(data,rate,eof=False)
    starts=[e for e in events if e["type"]=="image_start"]
    assert len(starts)==1 and starts[0]["mode"]==mode
    assert not starts[0]["transmitter_row_numbering_known"]
    assert len(final_rows(events))>=(10 if mode=="Robot36" else 4)
    decoder.eof()
    assert events[-1]["type"]=="image_partial"

