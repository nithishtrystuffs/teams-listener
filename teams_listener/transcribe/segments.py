"""Transcript segments: echo removal, merging, paragraph joining and Markdown rendering."""
from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import datetime
from difflib import SequenceMatcher
from typing import Literal

Speaker = Literal["Me", "Others"]


@dataclass(frozen=True)
class Segment:
    start: float
    end: float
    speaker: Speaker
    text: str


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^\w\s']", " ", text.lower())).strip()


def drop_echo(me: list[Segment], others: list[Segment], min_overlap: float = 0.5,
              min_similarity: float = 0.6) -> list[Segment]:
    """Drop Me segments that are the mic picking up remote speech from the speakers."""
    kept = []
    for m in me:
        dur = max(m.end - m.start, 1e-6)
        mt = _norm(m.text)
        echo = False
        for o in others:
            overlap = min(m.end, o.end) - max(m.start, o.start)
            if overlap / dur >= min_overlap and SequenceMatcher(None, mt, _norm(o.text)).ratio() >= min_similarity:
                echo = True
                break
        if not echo:
            kept.append(m)
    return kept


def merge(me: list[Segment], others: list[Segment]) -> list[Segment]:
    return sorted([*others, *me], key=lambda s: (s.start, 0 if s.speaker == "Others" else 1))


def join_paragraphs(segs: list[Segment], max_gap: float = 2.0) -> list[Segment]:
    out: list[Segment] = []
    for s in segs:
        if out and out[-1].speaker == s.speaker and s.start - out[-1].end < max_gap:
            prev = out[-1]
            out[-1] = replace(prev, end=max(prev.end, s.end), text=f"{prev.text} {s.text}")
        else:
            out.append(s)
    return out


def format_ts(seconds: float) -> str:
    s = int(seconds)
    return f"{s // 3600:02d}:{s % 3600 // 60:02d}:{s % 60:02d}"


def render_markdown(title: str, start: datetime, duration_s: float, segs: list[Segment]) -> str:
    minutes = max(1, round(duration_s / 60))
    head = f"# {title} — {start:%Y-%m-%d %H:%M} ({minutes} min)\n\n"
    if not segs:
        return head + "_No speech detected._\n"
    body = "\n\n".join(f"[{format_ts(s.start)}] **{s.speaker}:** {s.text}" for s in segs)
    return head + body + "\n"
