import json
from pathlib import Path

import numpy as np


def make_track(folder: Path, track_id: str, kind: str, offset: int, data: np.ndarray, device: str = "Dev") -> None:
    d = Path(folder) / "tracks"
    d.mkdir(parents=True, exist_ok=True)
    np.asarray(data, np.int16).tofile(d / f"{track_id}.pcm")
    (d / f"{track_id}.json").write_text(json.dumps({"kind": kind, "device": device, "offset_samples": offset}))


def fake_meeting(folder: Path, seconds: float = 3.0) -> Path:
    from datetime import datetime, timedelta

    from teams_listener.meeting import MeetingMeta, write_meta

    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    n = int(seconds * 16000)
    make_track(folder, "others-1", "others", 0, np.full(n, 100, np.int16))
    make_track(folder, "me-1", "me", 0, np.full(n, 50, np.int16))
    start = datetime(2026, 11, 25, 14, 30)
    write_meta(folder, MeetingMeta("Standup", start, end=start + timedelta(seconds=seconds)))
    return folder
