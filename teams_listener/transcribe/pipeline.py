"""Meeting folder -> transcript.md, and a single-worker background queue."""
from __future__ import annotations

import queue
import shutil
import sys
import threading
import time
from pathlib import Path
from typing import Callable

import soundfile as sf

from ..audio.mixer import finalize_meeting
from ..config import Settings
from ..meeting import read_meta, write_meta
from .engine import Engine, WhisperEngine
from .segments import drop_echo, join_paragraphs, merge, render_markdown

TRANSCRIPT_NAME = "transcript.md"


def transcribe_meeting(folder: Path, engine: Engine, settings: Settings,
                       on_progress: Callable[[float], None]) -> Path:
    folder = Path(folder)
    others_path, me_path = finalize_meeting(folder)
    others = engine.transcribe(others_path, "Others", lambda f: on_progress(0.5 * f))
    me = engine.transcribe(me_path, "Me", lambda f: on_progress(0.5 + 0.5 * f))
    segs = join_paragraphs(merge(drop_echo(me, others), others))

    meta = read_meta(folder)
    if meta.end is not None:
        duration = (meta.end - meta.start).total_seconds()
    else:
        duration = sf.info(str(others_path)).duration
    out = folder / TRANSCRIPT_NAME
    tmp = folder / (TRANSCRIPT_NAME + ".tmp")
    tmp.write_text(render_markdown(meta.title, meta.start, duration, segs), encoding="utf-8")
    tmp.replace(out)
    meta.model = settings.model
    write_meta(folder, meta)

    if settings.delete_audio_after:
        for p in (others_path, me_path):
            p.unlink(missing_ok=True)
        shutil.rmtree(folder / "tracks", ignore_errors=True)
    on_progress(1.0)
    return out


def _lower_thread_priority() -> None:
    if sys.platform == "win32":
        try:
            import ctypes

            k32 = ctypes.windll.kernel32
            k32.SetThreadPriority(k32.GetCurrentThread(), -2)  # THREAD_PRIORITY_LOWEST
        except Exception:  # noqa: BLE001
            pass


class TranscriptionQueue:
    def __init__(
        self,
        engine_factory: Callable[[], Engine] | None,
        get_settings: Callable[[], Settings],
        on_progress: Callable[[Path, float, float | None], None],
        on_done: Callable[[Path, Path], None],
        on_error: Callable[[Path, Exception], None],
    ):
        self._factory = engine_factory
        self._get_settings = get_settings
        self._on_progress, self._on_done, self._on_error = on_progress, on_done, on_error
        self._q: queue.Queue[Path | None] = queue.Queue()
        self._engine: Engine | None = None
        self._engine_key: tuple | None = None
        self._busy = False
        self._thread = threading.Thread(target=self._run, name="transcribe", daemon=True)
        self._thread.start()

    @property
    def busy(self) -> bool:
        return self._busy or not self._q.empty()

    def submit(self, folder: Path) -> None:
        self._q.put(Path(folder))

    def shutdown(self) -> None:
        self._q.put(None)
        self._thread.join(timeout=5)

    def _engine_for(self, s: Settings) -> Engine:
        key = (s.model, s.model_path)
        if self._engine is None or key != self._engine_key:
            self._engine = self._factory() if self._factory else WhisperEngine(s.model, s.model_path)
            self._engine_key = key
        return self._engine

    def _run(self) -> None:
        _lower_thread_priority()
        while True:
            folder = self._q.get()
            if folder is None:
                return
            self._busy = True
            started = time.monotonic()

            def progress(frac: float, folder=folder) -> None:
                elapsed = time.monotonic() - started
                eta = elapsed / frac * (1 - frac) if frac > 0.02 else None
                self._on_progress(folder, frac, eta)

            try:
                s = self._get_settings()
                path = transcribe_meeting(folder, self._engine_for(s), s, progress)
            except Exception as e:  # noqa: BLE001 - reported to the UI; audio is kept
                self._engine = None  # don't reuse an engine that may be broken
                self._on_error(folder, e)
            else:
                self._on_done(folder, path)
            finally:
                self._busy = False
