from datetime import datetime

from teams_listener.transcribe.segments import Segment, drop_echo, format_ts, join_paragraphs, merge, render_markdown


def O(s, e, t):
    return Segment(s, e, "Others", t)


def M(s, e, t):
    return Segment(s, e, "Me", t)


def test_drop_echo_removes_matching_overlap():
    assert drop_echo([M(1.1, 3.9, "let's get started.")], [O(1.0, 4.0, "Let's get started")]) == []


def test_drop_echo_keeps_real_speech():
    me = [M(1.0, 4.0, "Yes I can hear you")]
    assert drop_echo(me, [O(1.0, 4.0, "Let's get started")]) == me


def test_drop_echo_keeps_same_words_at_different_time():
    me = [M(10.0, 12.0, "Let's get started")]
    assert drop_echo(me, [O(1.0, 4.0, "Let's get started")]) == me


def test_merge_and_join():
    segs = join_paragraphs(merge([M(5.0, 6.0, "Hi.")], [O(0.0, 2.0, "Hello."), O(3.0, 4.0, "Welcome.")]))
    assert segs == [O(0.0, 4.0, "Hello. Welcome."), M(5.0, 6.0, "Hi.")]


def test_merge_tie_others_first():
    assert [s.speaker for s in merge([M(1, 2, "a")], [O(1, 2, "b")])] == ["Others", "Me"]


def test_join_respects_gap():
    assert len(join_paragraphs([O(0, 1, "a"), O(3.5, 4, "b")])) == 2


def test_format_ts():
    assert format_ts(0) == "00:00:00" and format_ts(3725.9) == "01:02:05"


def test_render():
    md = render_markdown("Standup", datetime(2026, 11, 25, 14, 30), 52 * 60 + 10,
                         [O(5, 9, "Morning everyone."), M(19, 21, "Hi.")])
    assert md.startswith("# Standup — 2026-11-25 14:30 (52 min)\n")
    assert "[00:00:05] **Others:** Morning everyone.\n\n[00:00:19] **Me:** Hi." in md


def test_render_empty():
    md = render_markdown("X", datetime(2026, 11, 25, 9, 0), 3, [])
    assert "(1 min)" in md and "_No speech detected._" in md
