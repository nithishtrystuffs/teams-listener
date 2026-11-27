"""UI-free orchestration: recording, mute, transcription queue, meetings library and settings.

Everything the UI shows comes from the events passed to `emit(name, data)`. The engine (this class) is the
single source of truth for recording/mute state. Public methods are thread-safe; `emit` is always called
without holding the internal lock.
"""
from __future__ import annotations

import dataclasses
import logging
import queue
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from .audio import devices
from .config import ALLOWED_MODELS, ALLOWED_THEMES, Settings, load_settings, save_settings
from .library import meeting_details, resolve_meeting, search_meetings
from .meeting import MeetingMeta, list_meetings, make_meeting_dir, read_meta, write_meta

log = logging.getLogger(__name__)
BAD_HOTKEY = "That shortcut isn't valid. Example: <ctrl>+<alt>+m"


def _default_recorder(folder: Path, mic_name: str | None):
    from .audio.recorder import Recorder

    return Recorder(folder, devices.list_output_loopbacks, devices.get_mic, mic_name)


def _default_queue(get_settings, on_progress, on_done, on_error, on_stage):
    from .transcribe.pipeline import TranscriptionQueue

    return TranscriptionQueue(None, get_settings, on_progress, on_done, on_error, on_stage)


def _default_hotkeys(hotkey: str, follow_teams: bool, on_toggle):
    from .hotkeys import MuteHotkeys

    return MuteHotkeys(hotkey, follow_teams, on_toggle)


class Controller:
    def __init__(self, emit: Callable[[str, dict], None], settings_path: Path | None = None,
                 recorder_factory=None, queue_factory=None, hotkeys_factory=None,
                 mic_lister=devices.list_mic_names, clock=time.monotonic):
        self._emit = emit
        self._settings_path = settings_path
        self._recorder_factory = recorder_factory or _default_recorder
        self._hotkeys_factory = hotkeys_factory or _default_hotkeys
        self._mic_lister = mic_lister
        self._clock = clock
        self._lock = threading.RLock()
        self._emit_lock = threading.Lock()  # orders `state` emits
        self._seq = 0  # bumped for every `state` emit (under _emit_lock); lets UIs drop stale replies
        self._hk_lock = threading.Lock()
        self.settings: Settings = load_settings(settings_path)

        self._recorder = None
        self._folder: Path | None = None
        self._meta: MeetingMeta | None = None
        self._title: str | None = None
        self._started_at = 0.0
        self._queued: set[Path] = set()
        self._progress: dict[Path, float] = {}
        self._stage: dict[Path, str] = {}
        self._last_devices: tuple | None = None
        self._hotkeys = None
        # The hotkey callback runs inside pynput's low-level keyboard hook, which must return at once
        # (Windows drops a slow hook silently). It only enqueues; this worker does the actual toggle.
        self._hk_requests: queue.Queue = queue.Queue()
        self._hk_worker = threading.Thread(target=self._hotkey_loop, name="hotkey-toggle", daemon=True)
        self._hk_worker.start()

        self._queue = (queue_factory or _default_queue)(
            lambda: self.settings, self._on_progress, self._on_done, self._on_error, self._on_stage)
        self._restart_hotkeys()

    # ---- status ------------------------------------------------------------
    def _status_locked(self) -> dict:
        rec = self._recorder
        if rec is None:
            return {"recording": False, "muted": True, "title": None, "folder": None, "elapsed_s": 0.0,
                    "mic": None, "outputs": [], "nomic": False}
        mic = rec.mic_name
        return {"recording": True, "muted": bool(rec.muted), "title": self._title,
                "folder": str(self._folder), "elapsed_s": max(0.0, self._clock() - self._started_at),
                "mic": mic, "outputs": list(rec.output_names), "nomic": mic is None}

    def status(self) -> dict:
        """Current status with the seq of the last emitted `state`. Taking _emit_lock first means no
        `state` emit is half-done, so the reply never carries a seq older than an event already sent.
        Never call this while holding _lock (lock order is _emit_lock, then _lock)."""
        with self._emit_lock:
            with self._lock:
                st = self._status_locked()
                st["seq"] = self._seq
                return st

    def _emit_state(self) -> dict:
        """Compute and emit `state` atomically w.r.t. other state emits, so the last one emitted is current.

        Also records the device snapshot so poll() doesn't repeat it."""
        with self._emit_lock:
            with self._lock:
                self._seq += 1
                st = self._status_locked()
                st["seq"] = self._seq
                self._last_devices = (st["mic"], tuple(st["outputs"])) if st["recording"] else None
            self._emit("state", st)
            return st

    # ---- recording ---------------------------------------------------------
    def _root(self) -> Path:
        return Path(self.settings.output_dir).resolve()

    def start(self, title: str = "Meeting") -> dict:
        with self._lock:
            if self._recorder is not None:
                raise RuntimeError("Already recording.")
            now = datetime.now()
            title = (title or "").strip() or "Meeting"
            folder = make_meeting_dir(self._root(), now, title)
            meta = MeetingMeta(title, now.replace(microsecond=0))
            write_meta(folder, meta)
            try:
                rec = self._recorder_factory(folder, self.settings.mic_device)
                self._queue.pause()  # no transcription while recording (keeps the Teams call smooth)
                rec.start()
            except Exception:
                log.exception("start failed")
                self._queue.resume()
                raise
            self._recorder, self._folder, self._meta, self._title = rec, folder, meta, title
            self._started_at = self._clock()
        self._emit("meetings_changed", {})
        return self._emit_state()

    def _finish_recording(self) -> Path | None:
        """Detach and stop the recorder, write meta. Returns the folder, or None when not recording."""
        with self._lock:
            rec, folder, meta = self._recorder, self._folder, self._meta
            if rec is None:
                return None
            self._recorder = self._folder = self._meta = self._title = None
        summary = rec.stop()
        meta.end = datetime.now().replace(microsecond=0)
        meta.devices = summary.devices
        meta.events = summary.events
        write_meta(folder, meta)
        return folder

    def stop(self) -> dict:
        try:
            folder = self._finish_recording()
        except Exception:
            # The recorder is already detached: the queue must resume and the UIs must see "not recording".
            try:
                self._emit_state()
            finally:
                self._queue.resume()
            raise
        if folder is None:
            return {"folder": None}
        self._emit_state()
        self._queue.resume()
        self._submit(folder)
        return {"folder": str(folder)}

    def set_muted(self, muted: bool) -> dict:
        with self._lock:
            idle = self._recorder is None
            if not idle:
                self._recorder.muted = bool(muted)
        return self.status() if idle else self._emit_state()

    def toggle_mute(self) -> dict:
        with self._lock:
            idle = self._recorder is None
            if not idle:
                self._recorder.muted = not self._recorder.muted
        return self.status() if idle else self._emit_state()

    def poll(self) -> None:
        """Call about every 100 ms."""
        with self._lock:
            rec = self._recorder
            if rec is None:
                return
            levels = dict(rec.levels())
            snapshot = (rec.mic_name, tuple(rec.output_names))
            changed = snapshot != self._last_devices
        self._emit("levels", {"others": levels["others"], "me": levels["me"]})
        if changed:
            self._emit_state()

    # ---- transcription -----------------------------------------------------
    def _submit(self, folder: Path) -> None:
        with self._lock:
            self._queued.add(folder)
        self._queue.submit(folder)
        self._emit("meetings_changed", {})

    def _progress_payload(self, folder: Path, frac: float, eta: float | None) -> dict:
        with self._lock:
            self._progress[folder] = frac
            self._queued.discard(folder)
            stage = self._stage.get(folder, "transcribe")
        return {"folder": str(folder), "frac": frac, "eta_s": eta, "stage": stage}

    def _on_stage(self, folder: Path, stage: str) -> None:
        with self._lock:
            self._stage[folder] = stage
        self._emit("progress", self._progress_payload(folder, 0.0, None))

    def _on_progress(self, folder: Path, frac: float, eta: float | None) -> None:
        self._emit("progress", self._progress_payload(folder, frac, eta))

    def _forget(self, folder: Path) -> None:
        with self._lock:
            self._queued.discard(folder)
            self._progress.pop(folder, None)
            self._stage.pop(folder, None)

    def _on_done(self, folder: Path, path: Path) -> None:
        self._forget(folder)
        self._emit("transcribed", {"folder": str(folder)})
        self._emit("meetings_changed", {})

    def _on_error(self, folder: Path, exc: Exception) -> None:
        self._forget(folder)
        log.error("transcription failed for %s: %r", folder, exc)
        self._emit("error", {"folder": str(folder), "message": str(exc)})
        self._emit("meetings_changed", {})

    def transcribe_again(self, folder: str) -> dict:
        f = resolve_meeting(self._root(), folder)
        with self._lock:
            if self._recorder is not None and f == self._folder:
                raise RuntimeError("This meeting is still recording.")
            if f in self._queued or f in self._progress:
                return {"folder": str(f)}
        if not (f / "meta.json").exists():
            write_meta(f, MeetingMeta(f.name, datetime.fromtimestamp(f.stat().st_ctime).replace(microsecond=0)))
        self._submit(f)
        return {"folder": str(f)}

    # ---- meetings ----------------------------------------------------------
    def list_meetings(self) -> list[dict]:
        entries = list_meetings(self._root(), limit=None)  # the sidebar and search need every meeting
        with self._lock:
            rec_folder = self._folder if self._recorder is not None else None
            rec_title = self._title
            queued, progress = set(self._queued), dict(self._progress)
        items = []
        for m in entries:
            status, prog = m.status, None
            if m.folder == rec_folder:
                status = "recording"
            elif m.folder in progress:
                status, prog = "transcribing", progress[m.folder]
            elif m.folder in queued:
                status = "queued"
            start, dur = None, None
            try:
                meta = read_meta(m.folder)
                start = meta.start.isoformat()
                dur = (meta.end - meta.start).total_seconds() if meta.end else None
            except (ValueError, KeyError, OSError):
                pass
            items.append({"folder": str(m.folder), "title": m.title, "start": start,
                          "duration_s": dur, "status": status, "progress": prog})
        if rec_folder is not None and not any(i["folder"] == str(rec_folder) for i in items):
            items.insert(0, {"folder": str(rec_folder), "title": rec_title, "start": None,
                             "duration_s": None, "status": "recording", "progress": None})
        return items

    def get_meeting(self, folder: str) -> dict:
        return meeting_details(resolve_meeting(self._root(), folder))

    def search(self, query: str) -> list[dict]:
        return search_meetings(self._root(), query)

    # ---- settings ----------------------------------------------------------
    def get_settings(self) -> dict:
        return dataclasses.asdict(self.settings)

    def list_mics(self) -> list[str]:
        return list(self._mic_lister())

    def _on_hotkey(self) -> None:
        """Called on pynput's hook thread: never block here."""
        self._hk_requests.put_nowait("toggle")

    def _hotkey_loop(self) -> None:
        while True:
            item = self._hk_requests.get()
            if item is None:
                return
            try:
                self.toggle_mute()
            except Exception:  # noqa: BLE001
                log.exception("hotkey mute toggle failed")

    def _stop_hotkeys(self) -> None:
        with self._hk_lock:
            hk, self._hotkeys = self._hotkeys, None
        if hk is not None:
            try:
                hk.stop()
            except Exception:  # noqa: BLE001
                log.exception("stopping hotkeys failed")

    def _restart_hotkeys(self) -> None:
        self._stop_hotkeys()
        s = self.settings
        try:
            hk = self._hotkeys_factory(s.hotkey, s.follow_teams_shortcut, self._on_hotkey)
            hk.start()
            with self._hk_lock:
                self._hotkeys = hk
        except ValueError:
            log.warning("invalid hotkey %r; running without hotkeys", s.hotkey)
        except Exception:  # noqa: BLE001 - a pynput failure must not crash-loop the engine
            log.warning("could not start hotkeys; running without hotkeys", exc_info=True)

    def save_settings(self, d: dict) -> dict:
        from pynput.keyboard import HotKey

        merged = dataclasses.asdict(self.settings)
        merged.update({k: v for k, v in d.items() if k in merged})
        hotkey = str(merged["hotkey"]).strip()
        try:
            HotKey.parse(hotkey)
        except ValueError:
            raise ValueError(BAD_HOTKEY) from None
        if merged["model"] not in ALLOWED_MODELS:
            raise ValueError(f"Unknown model: {merged['model']}")
        if merged["theme"] not in ALLOWED_THEMES:
            raise ValueError(f"Unknown theme: {merged['theme']}")
        new = Settings(
            model=merged["model"],
            model_path=(merged["model_path"] or "").strip() or None,
            mic_device=merged["mic_device"] or None,
            hotkey=hotkey,
            follow_teams_shortcut=bool(merged["follow_teams_shortcut"]),
            delete_audio_after=bool(merged["delete_audio_after"]),
            output_dir=(merged["output_dir"] or "").strip() or Settings().output_dir,
            theme=merged["theme"],
        )
        save_settings(new, self._settings_path)
        with self._lock:
            self.settings = new
        self._restart_hotkeys()
        self._emit("meetings_changed", {})
        return self.get_settings()

    # ---- lifecycle ---------------------------------------------------------
    def shutdown(self) -> None:
        try:
            self._finish_recording()
        finally:
            try:
                self._stop_hotkeys()
                self._hk_requests.put(None)
                self._hk_worker.join(timeout=2)
            finally:
                self._queue.shutdown()
