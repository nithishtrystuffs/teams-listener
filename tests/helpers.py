import json
from pathlib import Path

import numpy as np


def make_track(folder: Path, track_id: str, kind: str, offset: int, data: np.ndarray, device: str = "Dev") -> None:
    d = Path(folder) / "tracks"
    d.mkdir(parents=True, exist_ok=True)
    np.asarray(data, np.int16).tofile(d / f"{track_id}.pcm")
    (d / f"{track_id}.json").write_text(json.dumps({"kind": kind, "device": device, "offset_samples": offset}))
