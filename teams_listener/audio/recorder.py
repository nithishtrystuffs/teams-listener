"""Records every active output (loopback) device plus the mic onto one meeting clock."""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from .devices import AudioDevice, AudioReader, DeviceGone
from .track import Resampler, TrackWriter


@dataclass
class Active:
    track_id: str
    device: AudioDevice
    reader: AudioReader
    writer: TrackWriter
    resampler: Resampler
    is_mic: bool


@dataclass
class RecordingSummary:
    duration_s: float
    events: list[dict]
    devices: list[str]


class Recorder:
    def __init__(
        self,
        folder: Path,
        list_outputs: Callable[[], list[AudioDevice]],
        get_mic: Callable[[str | None], AudioDevice | None],
        mic_name: str | None,
        poll_interval: float = 1.0,
        clock: Callable[[], float] = time.perf_counter,
    ):
        self.folder = Path(folder)
        self._list_outputs = list_outputs
        self._get_mic = get_mic
        self._mic_name = mic_name
        self.poll_interval = poll_interval
        self.clock = clock
        self.clock_start = clock()
        self.events: list[dict] = []
        self._lock = threading.RLock()
        self._active: dict[str, Active] = {}
        self._mic: Active | None = None
        self._muted = True
        self._levels = {"others": {}, "me": 0.0}
        self._counters = {"others": 0, "me": 0}
        self._devices_seen: list[str] = []
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._started = False

    # ---- public -------------------------------------------------------
    @property
    def muted(self) -> bool:
        return self._muted

    @muted.setter
    def muted(self, value: bool) -> None:
        value = bool(value)
        with self._lock:
            if value != self._muted:
                self._muted = value
                self._event("mute" if value else "unmute", "")

    @property
    def mic_name(self) -> str | None:
        """Name of the mic currently recorded, or None when there is no mic."""
        act = self._mic
        return act.device.name if act is not None else None

    def levels(self) -> dict[str, float]:
        with self._lock:
            others = max(self._levels["others"].values(), default=0.0)
            return {"others": others, "me": self._levels["me"]}

    def start(self) -> None:
        self.clock_start = self.clock()
        self._started = True
        self._open_mic()
        self._spawn(self._mic_loop, "mic")
        self._spawn(self._poll_loop, "poll")

    def stop(self) -> RecordingSummary:
        self._stop.set()
        for t in self._threads:
            t.join(timeout=3.0)
        with self._lock:
            for act in list(self._active.values()):
                self._close(act)
            self._active.clear()
            if self._mic is not None:
                self._close(self._mic)
                self._mic = None
        return RecordingSummary(self.clock() - self.clock_start, list(self.events), list(self._devices_seen))

    # ---- internals (tested directly) ----------------------------------
    def _event(self, type_: str, detail: str) -> None:
        self.events.append({"t": round(self.clock() - self.clock_start, 3), "type": type_, "detail": detail})

    def _spawn(self, target, name, *args) -> None:
        t = threading.Thread(target=target, args=args, name=f"rec-{name}", daemon=True)
        self._threads.append(t)
        t.start()

    def _open(self, dev: AudioDevice, kind: str) -> Active | None:
        try:
            reader = dev.open()
        except DeviceGone:
            return None
        with self._lock:
            self._counters[kind] += 1
            track_id = f"{kind}-{self._counters[kind]}"
            if dev.name not in self._devices_seen:
                self._devices_seen.append(dev.name)
        writer = TrackWriter(self.folder, track_id, kind, dev.name, self.clock_start)
        return Active(track_id, dev, reader, writer, Resampler(reader.samplerate, reader.channels), kind == "me")

    def _close(self, act: Active) -> None:
        try:
            act.reader.close()
        finally:
            act.writer.close()

    def _open_mic(self, fallback: bool = False) -> Active | None:
        dev = self._get_mic(None if fallback else self._mic_name)
        act = self._open(dev, "me") if dev is not None else None
        with self._lock:
            self._mic = act
        if fallback and act is not None:
            self._event("mic_switched", dev.name)
        return act

    def _poll_once(self, start_threads: bool = True) -> None:
        for dev in self._list_outputs():
            with self._lock:
                if dev.id in self._active:
                    continue
            act = self._open(dev, "others")
            if act is None:
                continue
            with self._lock:
                self._active[dev.id] = act
            self._event("device_added", dev.name)
            if start_threads:
                self._spawn(self._device_loop, act.track_id, act)
        if self._mic is None and self._started and not self._stop.is_set():
            # The poller is the only place a missing/lost mic is (re)opened, so it can't be opened twice.
            self._open_mic(fallback=True)

    def _pump_once(self, act: Active) -> bool:
        try:
            frames = act.reader.read()
        except DeviceGone:
            self._close(act)
            with self._lock:
                if act.is_mic:
                    self._levels["me"] = 0.0
                    self._mic = None
                else:
                    self._active.pop(act.device.id, None)
                    self._levels["others"].pop(act.track_id, None)
            self._event("device_removed", act.device.name)
            return False
        samples = act.resampler.process(frames)
        rms = float(np.sqrt(np.mean(np.square(frames)))) if len(frames) else 0.0
        if act.is_mic and self._muted:
            samples = np.zeros_like(samples)
            rms = 0.0
        act.writer.write(samples, self.clock())
        with self._lock:
            if act.is_mic:
                self._levels["me"] = min(rms, 1.0)
            else:
                self._levels["others"][act.track_id] = min(rms, 1.0)
        return True

    # ---- thread loops -------------------------------------------------
    def _device_loop(self, act: Active) -> None:
        while not self._stop.is_set() and self._pump_once(act):
            pass

    def _mic_loop(self) -> None:
        while not self._stop.is_set():
            act = self._mic
            if act is None:
                self._stop.wait(0.1)
                continue
            self._pump_once(act)

    def _poll_loop(self) -> None:
        while not self._stop.is_set():
            self._poll_once()
            self._stop.wait(self.poll_interval)
