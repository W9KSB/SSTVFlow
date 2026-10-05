"""Host measurements, not an ARM64 deployment-performance claim."""
import argparse
import json
import platform
from pathlib import Path
import threading
import time
import psutil
from decode_wav import run


def benchmark(path,output):
    process=psutil.Process()
    stop=threading.Event()
    peaks={"rss":process.memory_info().rss,"cpu":0.0}
    process.cpu_percent()

    def monitor():
        while not stop.wait(.1):
            peaks["rss"]=max(peaks["rss"],process.memory_info().rss)
            peaks["cpu"]=max(peaks["cpu"],process.cpu_percent())
    watcher=threading.Thread(target=monitor)
    watcher.start()
    begin=time.perf_counter()
    cpu=time.process_time()
    try:
        report=run(path,output,"quadrature")
    finally:
        stop.set()
        watcher.join()
    elapsed=time.perf_counter()-begin
    cpu_seconds=time.process_time()-cpu
    return dict(report,host={"system":platform.system(),"machine":platform.machine(),"python":platform.python_version()},
                cpu_seconds=cpu_seconds,average_one_core_cpu_percent=cpu_seconds/elapsed*100,
                peak_one_core_cpu_percent=peaks["cpu"],peak_resident_bytes=peaks["rss"],
                cpu_seconds_per_audio_second=cpu_seconds/report["audio_seconds"],
                faster_than_realtime=report["audio_seconds"]/elapsed,
                note="Offline replay CPU saturates a core; CPU/audio predicts workload, not measured live ARM64 CPU.")


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("wav",type=Path)
    p.add_argument("--output",type=Path,default=Path("artifacts"))
    a=p.parse_args()
    print(json.dumps(benchmark(a.wav,a.output),indent=2))

