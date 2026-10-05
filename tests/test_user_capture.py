"""Local real satellite capture regression; fixtures are not redistributed."""
import base64
import io
from pathlib import Path
import wave
import numpy as np
import pytest
from PIL import Image
from sstv_decoder.decoder import Decoder


def test_user_entire_robot36_interval():
    root=Path(__file__).resolve().parents[1]
    path=root/"corpus/user/satellite_original.wav"
    baseline=root/"corpus/user/baseline_v1.png"
    if not path.exists() or not baseline.exists():
        pytest.skip("local satellite capture and received baseline are not redistributed")
    with wave.open(str(path)) as wav:
        assert wav.getnchannels()==1 and wav.getsampwidth()==2
        rate=wav.getframerate()
        wav.setpos(99*rate)
        data=wav.readframes(40*rate)
    events=[]
    decoder=Decoder(rate,events.append)
    for i in range(0,len(data),4093):
        decoder.feed(data[i:i+4093])
    # The authoritative full result must precede EOF.
    full=[e for e in events if e["type"]=="image_complete"]
    assert len(full)==1
    assert full[0]["mode"]=="Robot36"
    assert full[0]["decoded_row_count"]==full[0]["output_row_count"]==240
    assert full[0]["missing_row_count"]==0
    actual=np.asarray(Image.open(io.BytesIO(base64.b64decode(full[0]["png"])))).astype(float)
    reference=np.asarray(Image.open(baseline)).astype(float)
    assert actual.shape==reference.shape==(240,320,3)
    # Agreement with a received baseline is a geometry guard, not ground truth.
    # Chroma improvements are allowed; preserve the approved readable luminance.
    difference=(actual-reference)@np.array([.299,.587,.114])
    psnr=10*np.log10(255**2/max(np.mean(difference**2),1e-12))
    assert psnr>28
    decoder.eof()
