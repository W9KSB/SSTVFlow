"""Reproduce locally retained RF recordings from their provenance manifests."""
import hashlib
import json
from pathlib import Path
import urllib.request
import soundfile as sf


def fetch(directory):
    manifest=json.loads((directory/"manifest.json").read_text())
    # Inspect the manifest, because historical API field names vary by event.
    for recording in manifest["recordings"]:
        original=directory/recording["audio_file"]
        url=recording.get("source_audio_url") or recording.get("archive_url")
        if not url or not url.startswith("https://"):
            raise ValueError("manifest must supply a verified HTTPS recording URL")
        if not original.exists():
            with urllib.request.urlopen(url,timeout=120) as response,original.open("wb") as out:
                while block:=response.read(1<<20):
                    out.write(block)
        digest=hashlib.sha256(original.read_bytes()).hexdigest()
        if digest!=recording["audio_sha256"]:
            raise ValueError(f"recording hash mismatch: {original.name}")
        pcm,rate=sf.read(original,dtype="float32",always_2d=True)
        mono=pcm.mean(axis=1)
        for crop in recording.get("frame_crops",[]):
            first=round(crop["source_start_seconds"]*rate)
            last=round(crop["source_end_seconds"]*rate)
            sf.write(directory/crop["file"],mono[first:last],rate,subtype="PCM_16")
        print(original.name)


if __name__=="__main__":
    import argparse
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("directory",type=Path)
    fetch(p.parse_args().directory)

