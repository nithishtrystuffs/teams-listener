"""Mix raw tracks into others.flac / me.flac, block by block (memory-safe for long meetings)."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf

from .track import SAMPLE_RATE


class NoAudioError(Exception):
    """The meeting has no recorded audio left (it was deleted), so it can't be transcribed again."""


@dataclass
class Track:
    kind: str
    device: str
    offset_samples: int
    path: Path
    length: int


def load_tracks(folder: Path) -> list[Track]:
    tracks: list[Track] = []
    tdir = Path(folder) / "tracks"
    if not tdir.is_dir():
        return tracks
    for pcm in sorted(tdir.glob("*.pcm")):
        side = pcm.with_suffix(".json")
        if not side.exists():
            continue
        try:
            meta = json.loads(side.read_text(encoding="utf-8"))
        except ValueError:
            continue
        length = pcm.stat().st_size // 2  # ignore a trailing odd byte from a crash mid-sample
        tracks.append(Track(meta["kind"], meta.get("device", ""), int(meta["offset_samples"]), pcm, length))
    return tracks


def mix_to_file(tracks: list[Track], total_samples: int, out_path: Path, block: int = SAMPLE_RATE * 60) -> None:
    maps = [(t, np.memmap(t.path, dtype=np.int16, mode="r", shape=(t.length,))) for t in tracks if t.length > 0]
    out_path = Path(out_path)
    tmp = out_path.with_name(out_path.name + ".tmp")
    try:
        with sf.SoundFile(tmp, "w", samplerate=SAMPLE_RATE, channels=1, subtype="PCM_16", format="FLAC") as f:
            for b0 in range(0, total_samples, block):
                b1 = min(b0 + block, total_samples)
                acc = np.zeros(b1 - b0, np.int32)
                for t, m in maps:
                    s0, s1 = max(b0, t.offset_samples), min(b1, t.offset_samples + t.length)
                    if s0 < s1:
                        acc[s0 - b0:s1 - b0] += m[s0 - t.offset_samples:s1 - t.offset_samples]
                f.write(np.clip(acc, -32768, 32767).astype(np.int16))
    finally:
        del maps
    tmp.replace(out_path)


def finalize_meeting(folder: Path) -> tuple[Path, Path]:
    folder = Path(folder)
    tracks = load_tracks(folder)
    others, me = folder / "others.flac", folder / "me.flac"
    if not tracks:
        if others.exists() and me.exists():
            return others, me  # raw tracks were removed; the mixed audio is all that's left
        if (folder / "transcript.md").exists():
            raise NoAudioError(f"No audio left for {folder.name} (it was deleted after transcription).")
    total = max((t.offset_samples + t.length for t in tracks), default=0) or SAMPLE_RATE
    mix_to_file([t for t in tracks if t.kind == "others"], total, others)
    mix_to_file([t for t in tracks if t.kind == "me"], total, me)
    return others, me
