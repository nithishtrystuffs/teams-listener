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


def test_unhashable_cmd_gets_error_and_loop_continues():
    inp = ('{"id":1,"cmd":["x"]}\n{"id":2,"cmd":{}}\n{"id":3,"cmd":"status"}\n')
    s, h, out = make(inp)
    s.serve()
    r = lines(out)
    assert [(m["id"], m["ok"]) for m in r] == [(1, False), (2, False), (3, True)]
    assert h["c"].shutdowns == 1


def test_invalid_utf8_stdin_survives(monkeypatch):
    monkeypatch.setattr(server, "_setup_logging", lambda: None)
    monkeypatch.setattr(sys, "stdout", sys.stdout)
    stdin = io.BytesIO(b'\xff\xfe garbage\n{"id":1,"cmd":"status"}\n')
    stdout = io.BytesIO()
    holder = {}

    def factory(emit):
        holder["c"] = FakeController(emit)
        return holder["c"]

    server.main(stdin=stdin, stdout=stdout, controller_factory=factory)
    r = [json.loads(x) for x in stdout.getvalue().decode("utf-8").splitlines()]
    assert len(r) == 2 and r[0]["ok"] is False and r[1]["ok"] is True
    assert holder["c"].shutdowns == 1


def test_eof_mid_stream_after_start_shuts_down_once():
    s, h, out = make('{"id":1,"cmd":"start","args":{"title":"t"}}\n')
    s.serve()
    assert h["c"].calls == [("start", "t")]
    assert h["c"].shutdowns == 1


_NATIVE_NOISE_SCRIPT = r'''
import os, sys
from teams_listener import server

server._setup_logging = lambda: None


class Noisy:
    def __init__(self, emit):
        self.emit = emit

    def status(self):
        os.write(1, b"native noise on fd 1\n")  # what a C library's printf would do
        print("python print noise")
        self.emit("state", {"seq": 1})
        return {"recording": False}

    def poll(self):
        pass

    def shutdown(self):
        os.write(1, b"noise at shutdown\n")


server.main(controller_factory=Noisy)
'''


def test_native_fd1_writes_do_not_corrupt_protocol():
    import subprocess
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent
    p = subprocess.run([sys.executable, "-c", _NATIVE_NOISE_SCRIPT], cwd=root,
                       input=b'{"id":1,"cmd":"status"}\n{"id":2,"cmd":"status"}\n',
                       capture_output=True, timeout=30)
    assert p.returncode == 0, p.stderr
    out = p.stdout.decode("utf-8").splitlines()
    msgs = [json.loads(x) for x in out]  # every stdout line is protocol JSON
    assert [m.get("id") for m in msgs if "id" in m] == [1, 2]
    assert b"native noise on fd 1" in p.stderr and b"python print noise" in p.stderr


def test_protocol_stdout_falls_back_to_devnull_when_fd2_is_invalid(monkeypatch):
    calls = []
    real_dup2 = server.os.dup2

    def fake_dup2(a, b):
        calls.append((a, b))
        if a == 2:
            raise OSError("bad fd 2")
        return real_dup2(a, b)

    saved = server.os.dup(1)
    try:
        monkeypatch.setattr(server.os, "dup2", fake_dup2)
        monkeypatch.setattr(server, "_point_std_handle_at_fd1", lambda: None)
        out = server._protocol_stdout()
        out.close()
        assert calls[0] == (2, 1) and calls[1][1] == 1  # second dup2: devnull onto fd 1
    finally:
        monkeypatch.undo()
        server.os.dup2(saved, 1)
        server.os.close(saved)


def test_shutdown_is_logged_so_a_clean_eof_stop_is_visible(caplog):
    import logging

    caplog.set_level(logging.INFO, logger="teams_listener.server")
    s, h, _ = make('{"id":1,"cmd":"status"}\n')
    s.serve()
    msgs = [r.getMessage() for r in caplog.records]
    assert "engine shutting down" in msgs and "engine shut down cleanly" in msgs
