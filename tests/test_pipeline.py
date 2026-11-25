import threading

import pytest

from teams_listener.config import Settings
from teams_listener.meeting import read_meta
from teams_listener.transcribe.pipeline import TranscriptionQueue, transcribe_meeting
from teams_listener.transcribe.segments import Segment
from tests.helpers import fake_meeting


def O(s, e, t):
    return Segment(s, e, "Others", t)


def M(s, e, t):
    return Segment(s, e, "Me", t)


class FakeEngine:
    def __init__(self, others=None, me=None):
        self.others = others if others is not None else [O(0, 2, "Hello.")]
        self.me = me if me is not None else []
        self.calls = []

    def transcribe(self, audio, speaker, on_progress):
        self.calls.append((audio.name, speaker))
        on_progress(0.5)
        on_progress(1.0)
        return list(self.others if speaker == "Others" else self.me)


class FailingEngine:
    def transcribe(self, audio, speaker, on_progress):
        raise RuntimeError("model exploded")


def test_pipeline_writes_transcript_and_keeps_audio(tmp_path):
    folder = fake_meeting(tmp_path)
    eng = FakeEngine(others=[O(0, 2, "Hello.")], me=[M(3, 4, "Hi."), M(0.1, 1.9, "hello")])
    p = transcribe_meeting(folder, eng, Settings(), lambda f: None)
    text = p.read_text(encoding="utf-8")
    assert text.startswith("# Standup — 2026-11-25 14:30 (1 min)")
    assert "**Others:** Hello." in text and "**Me:** Hi." in text and "hello\n" not in text
    assert (folder / "others.flac").exists() and read_meta(folder).model == "small.en"
    assert eng.calls == [("others.flac", "Others"), ("me.flac", "Me")]


def test_pipeline_progress_monotonic_to_one(tmp_path):
    seen = []
    transcribe_meeting(fake_meeting(tmp_path), FakeEngine(), Settings(), seen.append)
    assert seen == sorted(seen) and seen[-1] == 1.0 and seen[0] <= 0.5


def test_delete_audio_after(tmp_path):
    folder = fake_meeting(tmp_path)
    transcribe_meeting(folder, FakeEngine(), Settings(delete_audio_after=True), lambda f: None)
    assert (folder / "transcript.md").exists()
    assert not (folder / "others.flac").exists() and not (folder / "tracks").exists()


def test_engine_failure_keeps_audio(tmp_path):
    folder = fake_meeting(tmp_path)
    with pytest.raises(RuntimeError):
        transcribe_meeting(folder, FailingEngine(), Settings(delete_audio_after=True), lambda f: None)
    assert (folder / "tracks").exists() and not (folder / "transcript.md").exists()


def test_queue_runs_jobs_in_order(tmp_path):
    done = []
    ev = threading.Event()

    def on_done(f, p):
        done.append(f)
        if len(done) == 2:
            ev.set()

    q = TranscriptionQueue(lambda: FakeEngine(), Settings, lambda *a: None, on_done, lambda f, e: None)
    a, b = fake_meeting(tmp_path / "a"), fake_meeting(tmp_path / "b")
    q.submit(a)
    q.submit(b)
    assert ev.wait(10)
    assert done == [a, b]
    q.shutdown()


def test_queue_reports_errors_and_continues(tmp_path):
    errors, done = [], []
    ev = threading.Event()
    engines = iter([FailingEngine(), FakeEngine()])

    def factory():
        return next(engines)

    q = TranscriptionQueue(factory, Settings, lambda *a: None,
                           lambda f, p: (done.append(f), ev.set()), lambda f, e: errors.append((f, e)))
    q._engine_key = None
    a, b = fake_meeting(tmp_path / "a"), fake_meeting(tmp_path / "b")
    q.submit(a)
    q.submit(b)
    assert ev.wait(10)
    assert errors and errors[0][0] == a and done == [b]
    q.shutdown()
