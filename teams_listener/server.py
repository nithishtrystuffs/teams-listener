"""JSON-lines engine server: one request/reply/event per line over stdin/stdout."""
import io
import json
import logging
import os
import sys
import threading
from typing import Callable, TextIO

from .logsetup import setup_logging as _setup_logging

log = logging.getLogger(__name__)

COMMANDS = frozenset({
    "status", "start", "stop", "set_muted", "toggle_mute", "list_meetings", "get_meeting",
    "search", "transcribe_again", "get_settings", "save_settings", "list_mics", "quit",
})


class Server:
    def __init__(self, controller_factory: Callable, inp: TextIO, out: TextIO,
                 poll_interval: float = 0.1):
        self.inp = inp
        self.out = out
        self.poll_interval = poll_interval
        self._wlock = threading.Lock()
        self._closed = False
        self._stop = threading.Event()
        self.controller = controller_factory(self._emit)

    # ---- output ------------------------------------------------------------
    def _write(self, obj: dict) -> None:
        """Never raises: emit runs on hotkey/worker threads."""
        try:
            line = json.dumps(obj, ensure_ascii=False, default=str)
            with self._wlock:
                if self._closed:
                    return
                try:
                    self.out.write(line + "\n")
                    self.out.flush()
                except Exception:
                    self._closed = True
                    raise
        except Exception:
            log.exception("failed to write to protocol stream")

    def _emit(self, name: str, data: dict) -> None:
        self._write({"event": name, "data": data})

    # ---- requests ----------------------------------------------------------
    def handle(self, line: str) -> dict | None:
        try:
            req = json.loads(line)
            if not isinstance(req, dict):
                raise ValueError("not an object")
        except ValueError:
            return {"id": None, "ok": False, "error": "bad request"}
        rid = req.get("id")
        cmd = req.get("cmd")
        if not isinstance(cmd, str) or cmd not in COMMANDS:
            return {"id": rid, "ok": False, "error": f"unknown command: {cmd}"}
        args = req.get("args") or {}
        try:
            if cmd == "quit":
                self._stop.set()
                result = None
            elif cmd == "save_settings":
                result = self.controller.save_settings(args)
            else:
                result = getattr(self.controller, cmd)(**args)
            return {"id": rid, "ok": True, "result": result}
        except Exception as e:
            log.exception("command %s failed", cmd)
            return {"id": rid, "ok": False, "error": str(e)}

    def _poll_loop(self) -> None:
        while not self._stop.wait(self.poll_interval):
            try:
                self.controller.poll()
            except Exception:
                log.exception("poll failed")

    def serve(self) -> None:
        poller = threading.Thread(target=self._poll_loop, name="poll", daemon=True)
        poller.start()
        try:
            for line in self.inp:
                if not line.strip():
                    continue
                reply = self.handle(line)
                if reply is not None:
                    self._write(reply)
                if self._stop.is_set():
                    break
        finally:
            self._stop.set()
            poller.join(timeout=5)
            self.controller.shutdown()


def _point_std_handle_at_fd1() -> None:
    """Windows: native code that writes via GetStdHandle(STD_OUTPUT_HANDLE) must follow fd 1 too."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        import msvcrt

        ctypes.windll.kernel32.SetStdHandle(-11, msvcrt.get_osfhandle(1))  # STD_OUTPUT_HANDLE
    except Exception:  # noqa: BLE001
        log.warning("could not repoint the Win32 stdout handle", exc_info=True)


def _protocol_stdout():
    """Take the real stdout (fd 1) for the protocol and point fd 1 at stderr (or devnull when fd 2 is
    unusable), so writes to fd 1 from native code can't corrupt the protocol stream."""
    if sys.stdout is not None:
        try:
            sys.stdout.flush()
        except Exception:  # noqa: BLE001
            pass
    fd = os.dup(1)
    try:
        os.dup2(2, 1)
    except OSError:
        null = os.open(os.devnull, os.O_WRONLY)
        try:
            os.dup2(null, 1)
        finally:
            os.close(null)
    _point_std_handle_at_fd1()
    return os.fdopen(fd, "wb", buffering=0)


def main(stdin=None, stdout=None, controller_factory=None) -> None:
    """stdin/stdout are binary streams (default: the process's real ones)."""
    _setup_logging()
    raw_in = stdin if stdin is not None else sys.stdin.buffer
    if stdout is not None:
        raw_out = stdout
    else:
        try:
            raw_out = _protocol_stdout()
        except OSError:
            log.warning("could not move the protocol off fd 1", exc_info=True)
            raw_out = sys.stdout.buffer
    inp = io.TextIOWrapper(raw_in, encoding="utf-8", errors="replace")
    out = io.TextIOWrapper(raw_out, encoding="utf-8", newline="\n")
    # Stray prints must not corrupt the protocol stream.
    sys.stdout = sys.stderr if sys.stderr is not None else open(os.devnull, "w")
    log.info("server started (frozen=%s)", getattr(sys, "frozen", False))
    if controller_factory is None:
        from .controller import Controller as controller_factory
    Server(controller_factory, inp, out).serve()
