"""Packaging smoke test: record briefly and transcribe a wav, print one JSON line."""
import argparse
import json
import tempfile
import time
from pathlib import Path

from .audio.recorder import Recorder


def _recorded_seconds(folder: Path) -> dict[str, float]:
    totals = {"others": 0.0, "me": 0.0}
    for meta in (folder / "tracks").glob("*.json"):
        kind = json.loads(meta.read_text(encoding="utf-8")).get("kind")
        pcm = meta.with_suffix(".pcm")
        if kind in totals and pcm.exists():
            totals[kind] += pcm.stat().st_size / 2 / 16000
    return totals


def run_selftest(wav, record_seconds, engine, list_outputs, get_mic) -> dict:
    result = {"outputs": [d.name for d in list_outputs()], "mic": None,
              "recorded_s": {"others": 0.0, "me": 0.0}, "text": None}
    with tempfile.TemporaryDirectory() as tmp:
        rec = Recorder(Path(tmp), list_outputs, get_mic, None, poll_interval=0.05)
        rec.start()
        time.sleep(record_seconds)
        result["mic"] = rec.mic_name
        rec.stop()
        result["recorded_s"] = _recorded_seconds(Path(tmp))
    if wav is not None:
        segs = engine.transcribe(Path(wav), "Others", lambda f: None)
        result["text"] = " ".join(s.text.strip() for s in segs)
    return result


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--wav")
    ap.add_argument("--record-seconds", type=float, default=3.0)
    ap.add_argument("--model", default="small.en")
    args = ap.parse_args(argv)
    from .audio import devices
    from .transcribe.engine import WhisperEngine

    r = run_selftest(Path(args.wav) if args.wav else None, args.record_seconds, WhisperEngine(args.model),
                     devices.list_output_loopbacks, devices.get_mic)
    print(json.dumps(r), flush=True)
    return 0
