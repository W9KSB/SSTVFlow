"""Development adapter only; the executable itself accepts raw PCM exclusively."""
import argparse
import base64
import json
from pathlib import Path
import time
import wave
from sstv_decoder.decoder import Decoder


def run(path, output, method="quadrature", noise_reduction=None):
    output.mkdir(parents=True,exist_ok=True)
    summaries = []
    latency = []
    starts = []
    with wave.open(str(path),"rb") as wav:
        if wav.getnchannels()!=1 or wav.getsampwidth()!=2:
            raise ValueError("adapter requires mono PCM16 WAV")
        rate = wav.getframerate()
        row_count = 0

        def emit(event):
            nonlocal row_count
            if event["type"] in ("image_complete","image_partial"):
                image = output / f"{path.stem}_{len(summaries)}_{method}.png"
                image.write_bytes(base64.b64decode(event.pop("png")))
                event["file"] = str(image)
                summaries.append(event)
            elif event["type"] == "image_start":
                starts.append(event)
            elif event["type"] == "row":
                row_count += 1
                latency.append((event["emitted_at_sample"]-event["row_audio_end_sample"])/rate)
        decoder = Decoder(rate,emit,method)
        if noise_reduction is not None:
            decoder.control({"command":"noise_reduction","strength":noise_reduction})
        begin = time.perf_counter()
        while data := wav.readframes(4096):
            decoder.feed(data)
        decoder.eof()
        elapsed = time.perf_counter()-begin
        report = dict(input=str(path),method=method, processing_seconds=elapsed,
                      audio_seconds=wav.getnframes()/rate, rows=row_count,
                      max_row_latency_seconds=max(latency,default=None),
                      mean_row_latency_seconds=sum(latency)/len(latency) if latency else None,
                      images=summaries)
        return report


if __name__ == "__main__":
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wav",type=Path)
    parser.add_argument("--output",type=Path,default=Path("artifacts"))
    parser.add_argument("--method",choices=("hilbert","quadrature","narrow"),default="quadrature")
    parser.add_argument("--noise-reduction",type=float,default=None)
    args=parser.parse_args()
    print(json.dumps(run(args.wav,args.output,args.method,args.noise_reduction),indent=2))
