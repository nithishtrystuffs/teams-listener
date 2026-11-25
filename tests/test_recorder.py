import numpy as np
import pytest

from teams_listener.audio.devices import DeviceGone
from teams_listener.audio.recorder import Recorder


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


class FakeReader:
    samplerate = 48000
    channels = 2

    def __init__(self, dev):
        self.dev = dev

    def read(self):
        if self.dev.blocks <= 0:
            raise DeviceGone(self.dev.name)
        self.dev.blocks -= 1
        if getattr(self.dev, "delay", 0):
            import time
            time.sleep(self.dev.delay)
        self.dev.clock.t += 0.1
        return np.full((4800, 2), 0.5, np.float32)

    def close(self):
        pass


class FakeDevice:
    clock = None

    def __init__(self, id, name, blocks):
        self.id, self.name, self.blocks = id, name, blocks

    def open(self):
        return FakeReader(self)


def make_recorder(tmp_path, outs, mic="default", default_mic=None, no_mic=False):
    clock = FakeClock()
    if mic == "default":
        mic = FakeDevice("m", "Mic", 99)
    default_mic = default_mic or mic
    for d in [*outs, mic, default_mic]:
        if d is not None:
            d.clock = clock

    def list_outputs():
        for d in outs:
            d.clock = clock
        return list(outs)

    def get_mic(name):
        if no_mic:
            return None
        return mic if (mic is not None and name == mic.name) else default_mic

    r = Recorder(tmp_path, list_outputs, get_mic, mic.name if mic else None, clock=clock)
    r.clock_start = 0.0
    return r


def pcm(tmp_path, track_id):
    return np.fromfile(tmp_path / f"tracks/{track_id}.pcm", np.int16)


def test_poll_adds_new_devices_once(tmp_path):
    outs = [FakeDevice("a", "Speakers", 5)]
    r = make_recorder(tmp_path, outs)
    r._poll_once(start_threads=False)
    r._poll_once(start_threads=False)
    assert [e["type"] for e in r.events].count("device_added") == 1
    outs.append(FakeDevice("b", "Headset", 5))
    r._poll_once(start_threads=False)
    assert {a.track_id for a in r._active.values()} == {"others-1", "others-2"}


def test_starts_muted_and_writes_silence(tmp_path):
    r = make_recorder(tmp_path, [])
    act = r._open_mic()
    assert r.muted is True
    r._pump_once(act)
    r._pump_once(act)
    act.writer.close()
    data = pcm(tmp_path, "me-1")
    assert len(data) > 0 and not data.any()


def test_unmuted_mic_writes_audio_and_logs_event(tmp_path):
    r = make_recorder(tmp_path, [])
    act = r._open_mic()
    r.muted = False
    r._pump_once(act)
    act.writer.close()
    assert pcm(tmp_path, "me-1").any()
    assert r.events[-1]["type"] == "unmute"


def test_others_never_muted(tmp_path):
    r = make_recorder(tmp_path, [FakeDevice("a", "Speakers", 3)])
    r._poll_once(start_threads=False)
    act = r._active["a"]
    r._pump_once(act)
    act.writer.close()
    assert r.muted is True and pcm(tmp_path, "others-1").any()


def test_device_gone_closes_track_and_logs(tmp_path):
    r = make_recorder(tmp_path, [FakeDevice("a", "BT Headphones", 1)])
    r._poll_once(start_threads=False)
    act = r._active["a"]
    assert r._pump_once(act) is True and r._pump_once(act) is False
    assert r.events[-1]["type"] == "device_removed" and r.events[-1]["detail"] == "BT Headphones"
    assert "a" not in r._active


def test_mic_gone_falls_back_to_default(tmp_path):
    r = make_recorder(tmp_path, [], mic=FakeDevice("m", "BT Mic", 1), default_mic=FakeDevice("d", "Laptop Mic", 99))
    r._started = True
    act = r._open_mic()
    r._pump_once(act)
    assert r._pump_once(act) is False
    r._poll_once(start_threads=False)  # the poller reopens the lost mic
    assert any(e["type"] == "mic_switched" and e["detail"] == "Laptop Mic" for e in r.events)
    assert r._mic is not None and r._mic.track_id == "me-2"
    r._pump_once(r._mic)
    assert (tmp_path / "tracks/me-2.json").exists()


def test_no_mic_records_others_only(tmp_path):
    r = make_recorder(tmp_path, [FakeDevice("a", "Speakers", 2)], no_mic=True)
    assert r._open_mic() is None
    r._poll_once(start_threads=False)
    r._pump_once(r._active["a"])
    r._active["a"].writer.close()
    assert pcm(tmp_path, "others-1").any()


def test_levels_report_others_and_me(tmp_path):
    r = make_recorder(tmp_path, [FakeDevice("a", "Speakers", 3)])
    r._poll_once(start_threads=False)
    r._pump_once(r._active["a"])
    lv = r.levels()
    assert lv["others"] == pytest.approx(0.5, abs=0.01) and lv["me"] == 0.0


def test_threaded_start_stop_summary(tmp_path):
    import time
    outs = [FakeDevice("a", "Speakers", 10**9)]
    clock_real = time.perf_counter
    r = Recorder(tmp_path, lambda: list(outs), lambda n: None, None, poll_interval=0.05, clock=clock_real)
    for d in outs:
        d.clock = type("C", (), {"t": 0.0})()
        d.delay = 0.01
    r.start()
    time.sleep(0.3)
    summary = r.stop()
    assert summary.duration_s > 0.2 and "Speakers" in summary.devices
    assert (tmp_path / "tracks/others-1.pcm").exists()


def test_mic_name_reports_current_mic_or_none(tmp_path):
    r = make_recorder(tmp_path, [])
    assert r.mic_name is None
    r._open_mic()
    assert r.mic_name == "Mic"
    r2 = make_recorder(tmp_path / "x", [], no_mic=True)
    r2._open_mic()
    assert r2.mic_name is None


def test_mic_loss_reopened_only_by_poller(tmp_path):
    r = make_recorder(tmp_path, [], mic=FakeDevice("m", "BT Mic", 1), default_mic=FakeDevice("d", "Laptop Mic", 99))
    r._started = True
    act = r._open_mic()
    r._pump_once(act)
    assert r._pump_once(act) is False
    assert r._mic is None  # the mic thread must not reopen it itself
    r._poll_once(start_threads=False)
    assert r._mic is not None and r._mic.track_id == "me-2"
    r._poll_once(start_threads=False)
    assert r._mic.track_id == "me-2" and r._counters["me"] == 2  # no second open
