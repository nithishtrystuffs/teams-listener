import io
import json
import sys
import threading

from teams_listener import server
from teams_listener.server import Server


class FakeController:
    def __init__(self, emit):
        self.emit = emit
        self.calls = []
        self.shutdowns = 0
        self.polls = 0

    def status(self):
        return {"recording": False}

    def start(self, title="Meeting"):
        self.calls.append(("start", title))
        return {"title": title}

    def save_settings(self, d):
        self.calls.append(("save_settings", d))
        return d

    def get_settings(self):
        from pathlib import Path
        return {"p": Path("x")}

    def stop(self):
        raise RuntimeError("boom")

    def poll(self):
        self.polls += 1

    def shutdown(self):
        self.shutdowns += 1


def make(inp="", out=None):
    holder = {}

    def factory(emit):
        holder["c"] = FakeController(emit)
        return holder["c"]

    out = out or io.StringIO()
    return Server(factory, io.StringIO(inp), out), holder, out


def lines(out):
    return [json.loads(x) for x in out.getvalue().splitlines()]


def test_reply_matches_id():
    s, _, _ = make()
    assert s.handle('{"id":7,"cmd":"status"}') == {"id": 7, "ok": True, "result": {"recording": False}}


def test_args_and_save_settings_and_path_default():
    s, h, out = make()
    s.handle('{"id":1,"cmd":"start","args":{"title":"x"}}')
    s.handle('{"id":2,"cmd":"save_settings","args":{"a":1}}')
    assert h["c"].calls == [("start", "x"), ("save_settings", {"a": 1})]
    s._write(s.handle('{"id":3,"cmd":"get_settings"}'))
    assert lines(out)[0]["result"] == {"p": "x"}


def test_unknown_command_and_bad_json():
    s, _, _ = make()
    assert s.handle('{"id":1,"cmd":"nope"}') == {"id": 1, "ok": False, "error": "unknown command: nope"}
    assert s.handle("{not json") == {"id": None, "ok": False, "error": "bad request"}
    assert s.handle("[1]") == {"id": None, "ok": False, "error": "bad request"}


def test_exception_becomes_error_reply():
    s, _, _ = make()
    assert s.handle('{"id":2,"cmd":"stop"}') == {"id": 2, "ok": False, "error": "boom"}


def test_events_are_written_as_lines():
    s, h, out = make()
    t = threading.Thread(target=lambda: h["c"].emit("state", {"recording": True}))
    t.start()
    t.join()
    assert lines(out) == [{"event": "state", "data": {"recording": True}}]


def test_eof_shuts_down_controller_once():
    s, h, out = make('{"id":1,"cmd":"status"}\n')
    s.serve()
    assert h["c"].shutdowns == 1
    assert lines(out)[0]["ok"] is True


def test_quit_replies_then_shuts_down():
    s, h, out = make('{"id":1,"cmd":"quit"}\n{"id":2,"cmd":"status"}\n')
    s.serve()
    assert [m["id"] for m in lines(out)] == [1]
    assert h["c"].shutdowns == 1


def test_poll_thread_runs():
    s, h, _ = make('{"id":1,"cmd":"status"}\n')
    s.poll_interval = 0.01
    s.inp = _SlowInput()
    s.serve()
    assert h["c"].polls >= 1


class _SlowInput:
    def __iter__(self):
        import time
        time.sleep(0.2)
        return iter(())


def test_write_never_raises_after_closed_stream():
    out = io.StringIO()
    s, _, _ = make(out=out)
    out.close()
    s._write({"a": 1})
    s._write({"a": 2})  # dropped silently


def test_utf8_title_round_trip():
    title = "Café sync — Q4"
    req = json.dumps({"id": 1, "cmd": "start", "args": {"title": title}}, ensure_ascii=False) + "\n"
    inp = io.TextIOWrapper(io.BytesIO(req.encode("utf-8")), encoding="utf-8")
    holder = {}

    def factory(emit):
        holder["c"] = FakeController(emit)
        return holder["c"]

    Server(factory, inp, io.StringIO()).serve()
    assert holder["c"].calls == [("start", title)]


def test_main_redirects_stray_prints(monkeypatch):
    class Noisy(FakeController):
        def status(self):
            print("noise")
            return {"recording": False}

    stdin = io.BytesIO(b'{"id":1,"cmd":"status"}\n')
    stdout = io.BytesIO()
    monkeypatch.setattr(server, "_setup_logging", lambda: None, raising=False)
    monkeypatch.setattr(sys, "stdout", sys.stdout)  # restored by monkeypatch
    server.main(stdin=stdin, stdout=stdout, controller_factory=Noisy)
    data = stdout.getvalue().decode("utf-8")
    assert "noise" not in data
    assert json.loads(data.splitlines()[0])["ok"] is True
