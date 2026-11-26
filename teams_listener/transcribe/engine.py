"""faster-whisper on CPU, English only."""
from __future__ import annotations

from pathlib import Path
from typing import Callable, Protocol

from .segments import Segment, Speaker


class Engine(Protocol):
    def transcribe(self, audio: Path, speaker: Speaker, on_progress: Callable[[float], None]) -> list[Segment]: ...


class WhisperEngine:
    def __init__(self, model: str, model_path: str | None = None, cpu_threads: int = 4):
        self.model_name = model
        self.model_path = model_path
        self.cpu_threads = cpu_threads
        self._model = None

    def _load(self):
        if self._model is None:
            from faster_whisper import WhisperModel

            self._model = WhisperModel(self.model_path or self.model_name, device="cpu", compute_type="int8",
                                       cpu_threads=self.cpu_threads)
        return self._model

    def needs_download(self) -> bool:
        """True if the model isn't cached locally yet (first use will download it). Never raises."""
        if self.model_path:
            return False
        try:
            from faster_whisper.utils import download_model

            download_model(self.model_name, local_files_only=True)
            return False
        except Exception:  # noqa: BLE001 - any failure means "not available locally"
            return True

    def transcribe(self, audio: Path, speaker: Speaker, on_progress: Callable[[float], None]) -> list[Segment]:
        segments, info = self._load().transcribe(str(audio), language="en", vad_filter=True, beam_size=5)
        out: list[Segment] = []
        duration = info.duration or 0.0
        for seg in segments:
            text = seg.text.strip()
            if text:
                out.append(Segment(float(seg.start), float(seg.end), speaker, text))
            if duration > 0:
                on_progress(min(seg.end / duration, 1.0))
        on_progress(1.0)
        return out
