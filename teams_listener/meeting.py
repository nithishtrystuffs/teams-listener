"""Meeting folders and meta.json."""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

_INVALID = re.compile(r'[<>:"/\|?*]')
META_NAME = "meta.json"


def slugify_title(title: str) -> str:
    s = _INVALID.sub(" ", title or "")
    s = re.sub(r"\s+", "-", s.strip()).strip("-")[:50].strip("-")
    return s or "meeting"


def make_meeting_dir(output_dir: Path, start: datetime, title: str) -> Path:
    base = f"{start:%Y-%m-%d_%H%M}_{slugify_title(title)}"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    candidate, n = output_dir / base, 1
    while True:
        try:
            candidate.mkdir()
            return candidate
        except FileExistsError:
            n += 1
            candidate = output_dir / f"{base}-{n}"


@dataclass
class MeetingMeta:
    title: str
    start: datetime
    end: datetime | None = None
    model: str | None = None
    devices: list[str] = field(default_factory=list)
    events: list[dict] = field(default_factory=list)


def write_meta(folder: Path, meta: MeetingMeta) -> None:
    data = {
        "title": meta.title,
        "start": meta.start.isoformat(),
        "end": meta.end.isoformat() if meta.end else None,
        "model": meta.model,
        "devices": meta.devices,
        "events": meta.events,
    }
    tmp = Path(folder) / (META_NAME + ".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    tmp.replace(Path(folder) / META_NAME)


def read_meta(folder: Path) -> MeetingMeta:
    d = json.loads((Path(folder) / META_NAME).read_text(encoding="utf-8"))
    return MeetingMeta(
        title=d["title"],
        start=datetime.fromisoformat(d["start"]),
        end=datetime.fromisoformat(d["end"]) if d.get("end") else None,
        model=d.get("model"),
        devices=list(d.get("devices", [])),
        events=list(d.get("events", [])),
    )


@dataclass
class MeetingEntry:
    folder: Path
    title: str
    status: str  # "transcribed" | "not transcribed"


def list_meetings(output_dir: Path, limit: int | None = 50) -> list[MeetingEntry]:
    """Meeting folders, newest first (folder names start with YYYY-MM-DD_HHMM). limit=None: all of them."""
    output_dir = Path(output_dir)
    if not output_dir.is_dir():
        return []
    entries: list[MeetingEntry] = []
    for d in sorted((p for p in output_dir.iterdir() if p.is_dir()), key=lambda p: p.name, reverse=True):
        has_meta = (d / META_NAME).exists()
        if not has_meta and not (d / "tracks").is_dir():
            continue
        try:
            title = read_meta(d).title if has_meta else d.name
        except (ValueError, KeyError, OSError):
            title = d.name
        status = "transcribed" if (d / "transcript.md").exists() else "not transcribed"
        entries.append(MeetingEntry(d, title, status))
        if limit is not None and len(entries) >= limit:
            break
    return entries
