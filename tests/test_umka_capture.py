"""Local UMKA fixture: automatic reception and grain regression, not ground truth."""
from pathlib import Path
import base64
import io
import wave
import numpy as np
import pytest
from PIL import Image
from scipy.ndimage import gaussian_filter
from sstv_decoder.decoder import Decoder


def test_umka_automatic_pixel_path_and_noise_reduction():
    root=Path(__file__).resolve().parents[1]
    audio=root/'corpus/user/umka/umka_left.wav'
    reference=root/'corpus/user/umka/baseline_initial.png'
    if not audio.exists() or not reference.exists():
        pytest.skip('local user-provided UMKA fixture unavailable')
    events=[]
    with wave.open(str(audio)) as wav:
        decoder=Decoder(wav.getframerate(),events.append)
        while data:=wav.readframes(4096):
            decoder.feed(data)
    result=next(e for e in events if e['type']=='image_partial')
    acquisition=next(e for e in events if e['type']=='acquisition')
    assert acquisition['acquisition_source']=='line_structure'
    assert acquisition['sample_position']/decoder.rate<.25
    assert result['mode']=='Robot36'
    assert result['decoded_row_count']==240
    assert result['missing_row_count']==0
    assert result['pixel_band']=='narrow'
    assert result['auto_noise_reduction']
    assert result['automatically_noise_reduced_channels']>0
    assert result['frequency_reference_source']=='raw_sync_fit'
    assert abs(result['frequency_offset_hz'])<5
    improved=np.asarray(Image.open(io.BytesIO(base64.b64decode(result['png'])))).astype(float)
    earlier=np.asarray(Image.open(reference)).astype(float)
    def grain(region):
        return np.mean(abs(np.diff(region,axis=1)))
    # Earlier acquisition recovers fourteen opening rows. Compare the same
    # audio/image region instead of measuring different physical rows.
    assert grain(improved[69:99,100:150])<grain(earlier[55:85,100:150])*.6
    rxsstv=root/'corpus/user/umka/reference_rxsstv.png'
    if rxsstv.exists():
        reference_luma=gaussian_filter(np.asarray(Image.open(rxsstv).convert('RGB')).astype(float)
                                      @np.array([.299,.587,.114]),1)
        actual_luma=gaussian_filter(improved@np.array([.299,.587,.114]),1)
        # Register the unknown-start receiver segments within a small window.
        # This is reference agreement, not original transmitter accuracy.
        mse=min(np.mean((reference_luma[40:200,20:300]
                         -actual_luma[40-dy:200-dy,20-dx:300-dx])**2)
                for dy in range(-6,7) for dx in range(-2,3))
        assert mse<16**2
    decoder.eof()
