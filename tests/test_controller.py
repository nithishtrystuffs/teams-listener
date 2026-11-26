import threading
from datetime import datetime
from pathlib import Path

import pytest

from teams_listener.audio.recorder import RecordingSummary
from teams_listener.config import Settings, load_settings, save_settings
from teams_listener.controller import Controller
from teams_listener.meeting import MeetingMeta, read_meta, write_meta

EVENTS = [{"t": 1.0, "type": "unmute", "detail": ""}]


class FakeRecorder:
    def __init__(self, folder, mic_name):
        self.folder, self.requested_mic = folder, mic_name
        self.muted = True
        self.mic_name = "Mic A"
        self.output_names = ["Speakers"]
        self.started = self.stopped = False
        self.lv = {"others": 0.2, "me": 0.1}

    def levels(self):
        return self.lv

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True
        return RecordingSummary(5.0, list(EVENTS), ["Speakers", "Mic A"])


class FakeQueue:
    def __init__(self, get_settings, on_progress, on_done, on_error, on_stage):
        self.on_progress, self.on_done, self.on_error, self.on_stage = on_progress, on_done, on_error, on_stage
        self.paused = False
        self.busy = False
        self.submitted = []
        self.shut = False

    def pause(self):
        self.paused = True

    def resume(self):
        self.paused = False

    def submit(self, folder):
        self.submitted.append(folder)

    def shutdown(self):
        self.shut = True


class FakeHotkeys:
    def __init__(self, hotkey, follow, on_toggle):
        self.on_toggle = on_toggle
        self.started = self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True


@pytest.fixture
def ctl(tmp_path):
    save_settings(Settings(output_dir=str(tmp_path / "out")), tmp_path / "s.json")
    events = []
    made = {}

    def rec_factory(folder, mic):
        made["rec"] = FakeRecorder(folder, mic)
        return made["rec"]

    def q_factory(*a):
        made["queue"] = FakeQueue(*a)
        return made["queue"]

    def hk_factory(*a):
        made["hk"] = FakeHotkeys(*a)
        return made["hk"]

    c = Controller(lambda n, d: events.append((n, d)), settings_path=tmp_path / "s.json",
                   recorder_factory=rec_factory, queue_factory=q_factory, hotkeys_factory=hk_factory,
                   mic_lister=lambda: ["Mic A", "Mic B"], clock=lambda: 100.0)
    c.events, c.made, c.out = events, made, tmp_path / "out"
    return c


def names(c):
    return [n for n, _ in c.events]


def test_start_writes_meta_pauses_queue_and_emits_state(ctl):
    st = ctl.start("Café sync — Q4")
    folder = Path(st["folder"])
    assert read_meta(folder).title == "Café sync — Q4"
    assert ctl.made["queue"].paused is True and ctl.made["rec"].started
    n, d = ctl.events[-1]
    assert n == "state" and d["recording"] is True and d["muted"] is True
    assert d["mic"] == "Mic A" and d["outputs"] == ["Speakers"] and d["nomic"] is False


def test_start_twice_raises(ctl):
    ctl.start("a")
    with pytest.raises(RuntimeError):
        ctl.start("b")


def test_start_failure_resumes_queue(ctl):
    def boom(f, m):
        raise OSError("boom")

    ctl._recorder_factory = boom
    with pytest.raises(OSError):
        ctl.start("x")
    assert ctl.made["queue"].paused is False and ctl.status()["recording"] is False


def test_stop_writes_end_events_and_submits(ctl):
    folder = Path(ctl.start("T")["folder"])
    res = ctl.stop()
    meta = read_meta(folder)
    assert res == {"folder": str(folder)}
    assert meta.end is not None and meta.events == EVENTS and meta.devices == ["Speakers", "Mic A"]
    q = ctl.made["queue"]
    assert q.submitted == [folder] and q.paused is False
    assert "meetings_changed" in names(ctl)
    assert ctl.status()["recording"] is False and ctl.status()["muted"] is True


def test_toggle_mute_from_any_thread_emits_state(ctl):
    ctl.start("T")
    t = threading.Thread(target=ctl.toggle_mute)
    t.start()
    t.join()
    assert ctl.made["rec"].muted is False
    n, d = ctl.events[-1]
    assert n == "state" and d["muted"] is False


def test_mute_when_idle_is_noop(ctl):
    before = len(ctl.events)
    assert ctl.toggle_mute()["recording"] is False
    assert ctl.set_muted(False)["muted"] is True
    assert len(ctl.events) == before


def test_hotkey_toggles_mute(ctl):
    ctl.start("T")
    ctl.events.clear()
    ctl.made["hk"].on_toggle()
    assert ctl.made["rec"].muted is False and ctl.made["hk"].started
    assert ctl.events[-1][0] == "state" and ctl.events[-1][1]["muted"] is False


def test_poll_emits_levels_and_state_on_mic_change(ctl):
    ctl.poll()
    assert "levels" not in names(ctl)
    ctl.start("T")
    ctl.events.clear()
    ctl.poll()
    assert ("levels", {"others": 0.2, "me": 0.1}) in ctl.events
    ctl.events.clear()
    ctl.made["rec"].mic_name = "Mic B"
    ctl.poll()
    assert names(ctl).count("state") == 1
    ctl.events.clear()
    ctl.poll()
    assert "state" not in names(ctl)


def test_list_meetings_marks_recording_and_transcribing(ctl):
    old = ctl.out / "2026-01-01_0900_old"
    old.mkdir(parents=True)
    write_meta(old, MeetingMeta("Old", datetime(2026, 1, 1, 9, 0), end=datetime(2026, 1, 1, 9, 30)))
    (old / "transcript.md").write_text("x")
    mid = ctl.out / "2026-01-02_0900_mid"
    mid.mkdir()
    write_meta(mid, MeetingMeta("Mid", datetime(2026, 1, 2, 9, 0)))
    queued = ctl.out / "2026-01-03_0900_q"
    queued.mkdir()
    write_meta(queued, MeetingMeta("Q", datetime(2026, 1, 3, 9, 0)))
    ctl.transcribe_again(queued.name)
    ctl.transcribe_again(mid.name)
    ctl.made["queue"].on_stage(mid, "transcribe")
    ctl.made["queue"].on_progress(mid, 0.4, 30.0)
    rec_folder = Path(ctl.start("Live")["folder"])
    items = {Path(i["folder"]).name: i for i in ctl.list_meetings()}
    assert items[rec_folder.name]["status"] == "recording"
    assert items[mid.name]["status"] == "transcribing" and items[mid.name]["progress"] == 0.4
    assert items[queued.name]["status"] == "queued" and items[queued.name]["progress"] is None
    assert items[old.name]["status"] == "transcribed"
    assert items[old.name]["duration_s"] == 1800.0 and items[old.name]["start"] == "2026-01-01T09:00:00"
    assert items[old.name]["title"] == "Old"


def test_get_meeting_rejects_outside_folder(ctl):
    ctl.out.mkdir(parents=True)
    with pytest.raises(ValueError):
        ctl.get_meeting("..")
    with pytest.raises(ValueError):
        ctl.get_meeting(str(ctl.out.parent))


def test_transcribe_again_refuses_recording_folder(ctl):
    folder = Path(ctl.start("T")["folder"])
    with pytest.raises(RuntimeError, match="still recording"):
        ctl.transcribe_again(folder.name)


def test_transcribe_again_writes_fallback_meta_and_submits(ctl):
    d = ctl.out / "2026-02-02_1000_raw"
    (d / "tracks").mkdir(parents=True)
    ctl.transcribe_again(d.name)
    assert read_meta(d).title == d.name
    assert ctl.made["queue"].submitted == [d]
    ctl.transcribe_again(d.name)  # already queued: ignored
    assert ctl.made["queue"].submitted == [d]


def test_progress_event_carries_stage(ctl):
    f = ctl.out / "m"
    ctl.made["queue"].on_stage(f, "model")
    assert ctl.events[-1] == ("progress", {"folder": str(f), "frac": 0.0, "eta_s": None, "stage": "model"})
    ctl.made["queue"].on_progress(f, 0.0, None)
    assert ctl.events[-1] == ("progress", {"folder": str(f), "frac": 0.0, "eta_s": None, "stage": "model"})
    ctl.made["queue"].on_progress(f, 0.5, 12.0)
    assert ctl.events[-1][1]["eta_s"] == 12.0 and ctl.events[-1][1]["frac"] == 0.5


def test_done_and_error_events(ctl):
    f = ctl.out / "m"
    ctl.made["queue"].on_done(f, f / "transcript.md")
    assert ("transcribed", {"folder": str(f)}) in ctl.events
    ctl.made["queue"].on_error(f, RuntimeError("bad"))
    assert ("error", {"folder": str(f), "message": "bad"}) in ctl.events
    assert names(ctl).count("meetings_changed") == 2


def test_shutdown_while_recording_saves_meta(ctl):
    folder = Path(ctl.start("T")["folder"])
    ctl.shutdown()
    meta = read_meta(folder)
    assert meta.end is not None and meta.events == EVENTS and meta.devices == ["Speakers", "Mic A"]
    assert ctl.made["rec"].stopped and ctl.made["hk"].stopped and ctl.made["queue"].shut


def test_settings_roundtrip_and_validation(ctl, tmp_path):
    d = ctl.get_settings()
    assert d["theme"] == "system"
    d.update(model="medium.en", theme="dark", bogus=1, hotkey="<ctrl>+<alt>+k")
    out = ctl.save_settings(d)
    assert out["model"] == "medium.en" and "bogus" not in out
    assert load_settings(tmp_path / "s.json").theme == "dark"
    assert "meetings_changed" in names(ctl)
    with pytest.raises(ValueError, match="isn't valid"):
        ctl.save_settings({"hotkey": "<<nope"})
    with pytest.raises(ValueError):
        ctl.save_settings({"model": "huge"})
    with pytest.raises(ValueError):
        ctl.save_settings({"theme": "pink"})
    assert load_settings(tmp_path / "s.json").hotkey == "<ctrl>+<alt>+k"


def test_list_mics(ctl):
    assert ctl.list_mics() == ["Mic A", "Mic B"]


def test_invalid_hotkey_at_construction_runs_without(tmp_path):
    save_settings(Settings(output_dir=str(tmp_path / "o"), hotkey="<<bad"), tmp_path / "s.json")

    def boom(*a):
        raise ValueError("bad")

    c = Controller(lambda n, d: None, settings_path=tmp_path / "s.json",
                   recorder_factory=lambda f, m: FakeRecorder(f, m),
                   queue_factory=lambda *a: FakeQueue(*a), hotkeys_factory=boom)
    assert c.status()["recording"] is False


def test_start_failure_after_pause_resumes_and_clears(ctl):
    def factory(folder, mic):
        r = FakeRecorder(folder, mic)

        def boom():
            raise OSError("no device")

        r.start = boom
        return r

    ctl._recorder_factory = factory
    with pytest.raises(OSError):
        ctl.start("x")
    assert ctl.made["queue"].paused is False
    assert ctl.status()["recording"] is False


def test_start_during_stop_tail_keeps_new_recording(ctl):
    gate, entered = threading.Event(), threading.Event()
    count = []

    def factory(folder, mic):
        r = FakeRecorder(folder, mic)
        ctl.made["rec"] = r
        count.append(r)
        if len(count) == 1:
            orig = r.stop

            def slow_stop():
                entered.set()
                gate.wait(5)
                return orig()

            r.stop = slow_stop
        return r

    ctl._recorder_factory = factory
    first = Path(ctl.start("one")["folder"])
    stopper = threading.Thread(target=ctl.stop)
    stopper.start()
    assert entered.wait(5)
    second = Path(ctl.start("two")["folder"])
    gate.set()
    stopper.join(5)
    st = ctl.status()
    assert st["recording"] and st["folder"] == str(second) and st["title"] == "two"
    assert read_meta(first).end is not None
    ctl.stop()
    assert read_meta(second).end is not None


def test_noncanonical_output_dir_identity(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    save_settings(Settings(output_dir=str(tmp_path / "x" / ".." / "out")), tmp_path / "s.json")
    made = {}

    def qf(*a):
        made["q"] = FakeQueue(*a)
        return made["q"]

    c = Controller(lambda n, d: None, settings_path=tmp_path / "s.json",
                   recorder_factory=lambda f, m: FakeRecorder(f, m), queue_factory=qf,
                   hotkeys_factory=lambda *a: FakeHotkeys(*a))
    folder = Path(c.start("T")["folder"])
    with pytest.raises(RuntimeError, match="still recording"):
        c.transcribe_again(folder.name)
    c.stop()
    c.transcribe_again(folder.name)
    assert made["q"].submitted == [folder]
    assert {i["status"] for i in c.list_meetings()} == {"queued"}


def test_last_state_matches_status_under_contention(ctl):
    ctl.start("T")
    ctl.events.clear()

    def hammer():
        for _ in range(200):
            ctl.toggle_mute()

    ts = [threading.Thread(target=hammer) for _ in range(2)]
    [x.start() for x in ts]
    [x.join() for x in ts]
    last = [d for n, d in ctl.events if n == "state"][-1]
    assert last["muted"] == ctl.status()["muted"]
