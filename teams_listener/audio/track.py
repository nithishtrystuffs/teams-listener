"""Streaming resample to 16 kHz mono int16, and crash-safe raw track writing on a shared meeting clock."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import numpy as np
import soxr

SAMPLE_RATE = 16000
GAP_FILL_THRESHOLD = 3200  # 0.2 s in samples


class Resampler:
    """Float32 (n, ch) frames at src_rate -> int16 mono at 16 kHz. Stateful across calls."""

    def __init__(self, src_rate: int, channels: int):
        self.src_rate = src_rate
        self.channels = channels
        self._stream = None if src_rate == SAMPLE_RATE else soxr.ResampleStream(src_rate, SAMPLE_RATE, 1, dtype="float32")

    def process(self, frames: np.ndarray) -> np.ndarray:
        frames = np.asarray(frames, dtype=np.float32)
        mono = frames.mean(axis=1) if frames.ndim == 2 else frames
        if self._stream is not None:
            mono = self._stream.resample_chunk(np.ascontiguousarray(mono))
        return (np.clip(mono, -1.0, 1.0) * 32767.0).astype(np.int16)


class TrackWriter:
    """Appends int16 samples to tracks/<id>.pcm, placing them on the meeting clock.

    `arrival_time` is the clock time when the chunk's last sample was captured. Gaps longer than
    GAP_FILL_THRESHOLD between where the data says we are and where the clock says we are are
    filled with silence, so tracks stay aligned even if a device stops delivering frames.
    """

    def __init__(self, folder: Path, track_id: str, kind: Literal["others", "me"], device_name: str, clock_start: float):
        self.dir = Path(folder) / "tracks"
        self.track_id = track_id
        self.kind = kind
        self.device_name = device_name
        self.clock_start = clock_start
        self.offset_samples: int | None = None
        self.samples_written = 0
        self._f = None

    @property
    def pcm_path(self) -> Path:
        return self.dir / f"{self.track_id}.pcm"

    def write(self, samples: np.ndarray, arrival_time: float) -> None:
        samples = np.asarray(samples, dtype=np.int16)
        if len(samples) == 0:
            return
        end_expected = round((arrival_time - self.clock_start) * SAMPLE_RATE)
        if self.offset_samples is None:
            self.offset_samples = max(0, end_expected - len(samples))
            self.dir.mkdir(parents=True, exist_ok=True)
            (self.dir / f"{self.track_id}.json").write_text(
                json.dumps({"kind": self.kind, "device": self.device_name, "offset_samples": self.offset_samples}),
                encoding="utf-8",
            )
            self._f = open(self.pcm_path, "ab")
        else:
            end_actual = self.offset_samples + self.samples_written + len(samples)
            gap = end_expected - end_actual
            if gap > GAP_FILL_THRESHOLD:
                self._f.write(np.zeros(gap, np.int16).tobytes())
                self.samples_written += gap
        self._f.write(samples.tobytes())
        self._f.flush()
        self.samples_written += len(samples)

    def close(self) -> None:
        if self._f is not None:
            self._f.close()
            self._f = None
