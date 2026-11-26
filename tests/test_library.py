import pytest

from teams_listener.library import (
    live_moments, meeting_details, parse_transcript, resolve_meeting, search_meetings,
)
from tests.helpers import fake_meeting


def test_parse_transcript_lines():
    md = "# T — 2026-11-25 10:00 (47 min)\n\n[00:00:12] **Others:** Morning everyone.\n\n[00:01:05] **Me:** Nice — café works.\n"
    assert parse_transcript(md) == [
        {"t": 12.0, "ts": "00:00:12", "speaker": "Others", "text": "Morning everyone."},
        {"t": 65.0, "ts": "00:01:05", "speaker": "Me", "text": "Nice — café works."}]


def test_parse_transcript_empty_meeting():
    assert parse_transcript("# T — x (1 min)\n\n_No speech detected._\n") == []


def test_live_moments_pairs_and_open_end():
    ev = [{"t": 5, "type": "unmute"}, {"t": 9, "type": "mute"}, {"t": 20, "type": "unmute"}]
    assert live_moments(ev, 30.0) == [(5, 9), (20, 30.0)]


def test_search_counts_case_insensitive(tmp_path):
    a = tmp_path / "2026-11-25_1000_A"; a.mkdir()
    (a / "transcript.md").write_text("[00:00:01] **Others:** Deploy on Friday. deploy!", encoding="utf-8")
    (tmp_path / "2026-11-24_1000_B").mkdir()
    assert search_meetings(tmp_path, "DEPLOY") == [{"folder": str(a), "count": 2}]
    assert search_meetings(tmp_path, "  ") == []


def test_meeting_details_without_audio(tmp_path):
    f = fake_meeting(tmp_path / "2026-11-25_1430_Standup")
    d = meeting_details(f)
    assert d["title"] == "Standup" and d["audio"] is None and d["has_transcript"] is False and d["duration_s"] == 3.0


def test_resolve_meeting_rejects_escape(tmp_path):
    (tmp_path / "m").mkdir()
    assert resolve_meeting(tmp_path, str(tmp_path / "m")) == (tmp_path / "m").resolve()
    for bad in ["..", str(tmp_path.parent), str(tmp_path / "m" / ".." / ".."), "C:\Windows"]:
        with pytest.raises(ValueError): resolve_meeting(tmp_path, bad)


def test_meeting_details_endless_meeting_no_negative_live(tmp_path):
    from teams_listener.meeting import MeetingMeta, write_meta
    from datetime import datetime
    f = tmp_path / "2026-11-25_1430_X"; f.mkdir()
    write_meta(f, MeetingMeta("X", datetime(2026, 11, 25, 14, 30), events=[{"t": 5, "type": "unmute"}]))
    d = meeting_details(f)
    assert d["live_s"] >= 0 and all(b >= a for a, b in d["live_moments"])


def test_meeting_details_live_moments_with_end(tmp_path):
    from teams_listener.meeting import read_meta, write_meta
    f = fake_meeting(tmp_path / "2026-11-25_1430_Y", seconds=30)
    m = read_meta(f)
    m.events = [{"t": 5, "type": "unmute"}, {"t": 9, "type": "mute"}, {"t": 20, "type": "unmute"}]
    write_meta(f, m)
    d = meeting_details(f)
    assert d["live_moments"] == [[5, 9], [20, 30.0]] and d["live_s"] == 14.0


def test_search_survives_non_utf8_transcript(tmp_path):
    a = tmp_path / "2026-11-25_1000_A"; a.mkdir()
    (a / "transcript.md").write_bytes(b"deploy \xff\xfe deploy")
    b = tmp_path / "2026-11-24_1000_B"; b.mkdir()
    (b / "transcript.md").write_text("deploy", encoding="utf-8")
    assert search_meetings(tmp_path, "deploy") == [{"folder": str(b), "count": 1}]
