"""Wall-clock proof of progressive output while a PCM pipe remains open."""

import json
import os
from pathlib import Path
import queue
import subprocess
import sys
import threading
import time

import numpy as np

from signals import generate_robot36


def test_realtime_pipe_progresses_and_pause_keeps_image_open():
    rate = 16000
    pcm = generate_robot36(sample_rate=rate, rows=24)
    data = np.rint(np.clip(pcm, -1, 32767 / 32768) * 32768).astype("<i2").tobytes()
    environment = os.environ.copy()
    source = str(Path(__file__).resolve().parents[1] / "src")
    environment["PYTHONPATH"] = source + os.pathsep + environment.get("PYTHONPATH", "")
    process = subprocess.Popen(
        [sys.executable, "-m", "sstv_decoder.cli", str(rate)],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        env=environment, bufsize=0,
    )
    received = queue.Queue()
    events = []
    errors = []

    def read_events():
        try:
            for line in process.stdout:
                received.put((time.perf_counter(), json.loads(line)))
        except Exception as exc:
            received.put((time.perf_counter(), {"type": "reader_error", "message": str(exc)}))

    def read_errors():
        errors.append(process.stderr.read().decode("utf-8", errors="replace"))

    stdout_reader = threading.Thread(target=read_events, daemon=True)
    stderr_reader = threading.Thread(target=read_errors, daemon=True)
    stdout_reader.start()
    stderr_reader.start()

    def drain():
        while True:
            try:
                events.append(received.get_nowait())
            except queue.Empty:
                return

    try:
        ready_at, ready = received.get(timeout=20)
        assert ready["type"] == "ready", ready
        events.append((ready_at, ready))
        started = time.perf_counter()
        chunk_samples = 320  # 20 ms; much smaller than the CLI's read request.
        pause_samples = round((0.91 + 12 * 0.15) * rate)
        paused = False
        pause_duration = 0.0
        pre_eof_row_count = 0
        for first in range(0, len(pcm), chunk_samples):
            deadline = started + first / rate + pause_duration
            time.sleep(max(0, deadline - time.perf_counter()))
            assert process.poll() is None, "decoder exited while PCM stdin was open"
            last = min(first + chunk_samples, len(pcm))
            payload = memoryview(data)[first * 2:last * 2]
            while payload:
                written = process.stdin.write(payload)
                assert written, "PCM pipe made no progress"
                payload = payload[written:]
            drain()
            if not paused and last >= pause_samples:
                # Give a queued block time to finish, then leave stdin open and
                # supply no audio. A scheduling pause is not signal loss/EOF.
                time.sleep(0.10)
                drain()
                rows_before_pause = [e for _, e in events if e["type"] == "row"]
                assert len(rows_before_pause) >= 8
                assert any(e["type"] == "image_start" for _, e in events)
                pause_started = time.perf_counter()
                time.sleep(0.25)
                pause_hold_seconds = time.perf_counter() - pause_started
                drain()
                assert not any(e["type"] in ("image_complete", "image_partial") for _, e in events)
                pause_duration = time.perf_counter() - (started + last / rate)
                paused = True
                pre_eof_row_count = len(rows_before_pause)
        time.sleep(0.12)
        drain()
        assert process.stdin and not process.stdin.closed
        assert len([e for _, e in events if e["type"] == "row"]) > pre_eof_row_count
        assert not any(e["type"] in ("image_complete", "image_partial") for _, e in events)
        before_eof = time.perf_counter()
        acquisition = next(at - started for at, event in events if event["type"] == "image_start")
        initial_rows = [(at, event) for at, event in events if event["type"] == "row" and event["row_index"] < 10]
        # End of a complete transmitted row, plus actual downstream processing.
        # Negative values are legitimate when the decoder publishes luminance
        # before that row's final chroma samples arrive.
        row_latencies = [at - started - (0.91 + (event["row_index"] + 1) * 0.15)
                         for at, event in initial_rows]
        assert acquisition < 1.5, acquisition
        assert len(row_latencies) >= 8
        assert max(row_latencies) < 0.5, row_latencies
        print("live_pipe " + json.dumps({
            "sample_rate": rate, "acquisition_seconds": round(acquisition, 4),
            "row_latency_median_seconds": round(float(np.median(row_latencies)), 4),
            "row_latency_max_seconds": round(max(row_latencies), 4),
            "rows_before_all_audio": pre_eof_row_count,
            "rows_before_eof": len([e for _, e in events if e["type"] == "row"]),
            "pause_seconds": round(pause_hold_seconds, 4),
            "stdin_open_seconds": round(before_eof - started, 4),
        }, sort_keys=True))
        process.stdin.close()
        assert process.wait(timeout=10) == 0
        stdout_reader.join(timeout=2)
        stderr_reader.join(timeout=2)
        drain()
        assert not any(e["type"] in ("error", "reader_error") for _, e in events), events
        partials = [e for _, e in events if e["type"] == "image_partial"]
        assert len(partials) == 1
        assert partials[0]["completion_reason"] == "eof"
        assert not "Traceback" in "".join(errors)
    finally:
        if process.stdin and not process.stdin.closed:
            process.stdin.close()
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
        stdout_reader.join(timeout=2)
        stderr_reader.join(timeout=2)
        process.stdout.close()
        process.stderr.close()
