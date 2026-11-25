from datetime import datetime

from teams_listener.meeting import MeetingMeta, make_meeting_dir, read_meta, slugify_title, write_meta


def test_slugify():
    assert slugify_title("Sprint: Review/Q4?") == "Sprint-Review-Q4"
    assert slugify_title("   ") == "meeting"
    assert len(slugify_title("x" * 200)) == 50


def test_make_meeting_dir_name_and_collision(tmp_path):
    t = datetime(2026, 11, 25, 14, 30)
    a = make_meeting_dir(tmp_path, t, "Standup")
    b = make_meeting_dir(tmp_path, t, "Standup")
    assert a.name == "2026-11-25_1430_Standup" and a.is_dir()
    assert b.name == "2026-11-25_1430_Standup-2"


def test_meta_roundtrip(tmp_path):
    m = MeetingMeta("T", datetime(2026, 11, 25, 14, 30), devices=["Speakers"],
                    events=[{"t": 1.5, "type": "unmute", "detail": ""}])
    write_meta(tmp_path, m)
    assert read_meta(tmp_path) == m


def test_meta_roundtrip_with_end_and_model(tmp_path):
    m = MeetingMeta("T", datetime(2026, 11, 25, 14, 30), end=datetime(2026, 11, 25, 15, 0), model="small.en")
    write_meta(tmp_path, m)
    assert read_meta(tmp_path) == m


def test_list_meetings_status_and_order(tmp_path):
    from teams_listener.meeting import list_meetings
    from tests.helpers import fake_meeting

    old = fake_meeting(tmp_path / "2026-11-24_0900_Old")
    (old / "transcript.md").write_text("x")
    fake_meeting(tmp_path / "2026-11-25_1430_Crashed")
    (tmp_path / "2026-11-25_1500_Empty").mkdir()  # no meta, no tracks: not a meeting
    (tmp_path / "notes.txt").write_text("x")
    got = [(m.folder.name, m.status, m.title) for m in list_meetings(tmp_path)]
    assert got == [("2026-11-25_1430_Crashed", "not transcribed", "Standup"),
                   ("2026-11-24_0900_Old", "transcribed", "Standup")]


def test_list_meetings_missing_dir(tmp_path):
    from teams_listener.meeting import list_meetings

    assert list_meetings(tmp_path / "nope") == []
