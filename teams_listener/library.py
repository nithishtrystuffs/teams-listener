"""Read-only helpers over the meeting library, used by the desktop UI."""
from __future__ import annotations

import re
from pathlib import Path

from .meeting import read_meta
from .transcribe.pipeline import TRANSCRIPT_NAME

_LINE = re.compile(r"^\[(\d{2}):(\d{2}):(\d{2})\] \*\*(Others|Me):\*\* (.*)$", re.MULTILINE)


def parse_transcript(text: str) -> list[dict]:
    out = []
    for h, m, s, speaker, body in _LINE.findall(text):
        out.append({
            "t": float(int(h) * 3600 + int(m) * 60 + int(s)),
            "ts": f"{h}:{m}:{s}",
            "speaker": speaker,
            "text": body.strip(),
        })
    return out


def live_moments(events: list[dict], end_s: float) -> list[tuple[float, float]]:
    """Intervals where the mic was unmuted. Recordings start muted."""
    spans: list[tuple[float, float]] = []
    open_at: float | None = None
    for e in sorted(events, key=lambda e: e.get("t", 0)):
        kind = e.get("type")
        if kind == "unmute" and open_at is None:
            open_at = e["t"]
        elif kind == "mute" and open_at is not None:
            spans.append((open_at, e["t"]))
            open_at = None
    if open_at is not None:
        spans.append((open_at, end_s))
    return spans


def search_meetings(output_dir: Path, query: str) -> list[dict]:
    q = (query or "").strip().lower()
    output_dir = Path(output_dir)
    if not q or not output_dir.is_dir():
        return []
    results = []
    for d in sorted((p for p in output_dir.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True):
        t = d / TRANSCRIPT_NAME
        if not t.is_file():
            continue
        try:
            count = t.read_text(encoding="utf-8").lower().count(q)
        except OSError:
            continue
        if count > 0:
            results.append({"folder": str(d), "count": count})
    return results


def meeting_details(folder: Path) -> dict:
    folder = Path(folder)
    meta = read_meta(folder)
    t = folder / TRANSCRIPT_NAME
    has_transcript = t.is_file()
    lines = parse_transcript(t.read_text(encoding="utf-8")) if has_transcript else []
    duration = (meta.end - meta.start).total_seconds() if meta.end else None
    moments = live_moments(meta.events, duration if duration is not None else 0.0)
    others, me = folder / "others.flac", folder / "me.flac"
    audio = {"others": str(others), "me": str(me)} if others.is_file() and me.is_file() else None
    files = [p for p in (others, me) if p.is_file()]
    tracks = folder / "tracks"
    if tracks.is_dir():
        files += [p for p in tracks.rglob("*") if p.is_file()]
    return {
        "folder": str(folder),
        "title": meta.title,
        "start": meta.start.isoformat(),
        "end": meta.end.isoformat() if meta.end else None,
        "duration_s": duration,
        "model": meta.model,
        "devices": meta.devices,
        "lines": lines,
        "has_transcript": has_transcript,
        "live_s": sum(b - a for a, b in moments),
        "live_moments": [[a, b] for a, b in moments],
        "audio": audio,
        "audio_bytes": sum(p.stat().st_size for p in files),
    }


def resolve_meeting(output_dir: Path, folder: str) -> Path:
    root = Path(output_dir).resolve()
    p = (root / folder).resolve()
    if p.parent != root or not p.is_dir():
        raise ValueError(f"not a meeting folder: {folder}")
    return p
