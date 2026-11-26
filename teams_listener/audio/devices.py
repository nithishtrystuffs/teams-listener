"""Real audio devices via `soundcard` (WASAPI). Verified manually; the Recorder is tested with fakes."""
from __future__ import annotations

import sys
import warnings
from typing import Protocol

import numpy as np

BLOCK_FRAMES = 4800
CAPTURE_RATE = 48000


class DeviceGone(Exception):
    """The device disappeared or failed; its track should be closed."""


class AudioReader(Protocol):
    samplerate: int
    channels: int

    def read(self) -> np.ndarray: ...  # float32 (n, ch); blocks ~100 ms; raises DeviceGone

    def close(self) -> None: ...


class AudioDevice(Protocol):
    id: str
    name: str

    def open(self) -> AudioReader: ...


def _silence_soundcard_warnings() -> None:
    try:
        from soundcard.mediafoundation import SoundcardRuntimeWarning

        warnings.simplefilter("ignore", SoundcardRuntimeWarning)
    except ImportError:  # pragma: no cover
        pass


class _ScReader:
    def __init__(self, sc_mic):
        _silence_soundcard_warnings()
        self.samplerate = CAPTURE_RATE
        try:
            self._ctx = sc_mic.recorder(samplerate=CAPTURE_RATE, blocksize=BLOCK_FRAMES)
            self._rec = self._ctx.__enter__()
        except Exception as e:  # noqa: BLE001 - any WASAPI/COM failure means the device is unusable
            raise DeviceGone(str(e)) from e
        self.channels = getattr(sc_mic, "channels", 2)

    def read(self) -> np.ndarray:
        try:
            data = self._rec.record(numframes=BLOCK_FRAMES)
        except Exception as e:  # noqa: BLE001
            raise DeviceGone(str(e)) from e
        return np.asarray(data, dtype=np.float32)

    def close(self) -> None:
        try:
            self._ctx.__exit__(None, None, None)
        except Exception:  # noqa: BLE001 - device may already be gone
            pass


class ScDevice:
    def __init__(self, sc_mic):
        self._mic = sc_mic
        self.id = sc_mic.id
        self.name = sc_mic.name

    def open(self) -> AudioReader:
        return _ScReader(self._mic)


def list_output_loopbacks() -> list[AudioDevice]:
    import soundcard as sc

    _silence_soundcard_warnings()
    try:
        return [ScDevice(m) for m in sc.all_microphones(include_loopback=True) if m.isloopback]
    except Exception:  # noqa: BLE001
        return []


def list_mic_names() -> list[str]:
    import soundcard as sc

    try:
        return [m.name for m in sc.all_microphones(include_loopback=False)]
    except Exception:  # noqa: BLE001
        return []


def _default_communications_capture_id() -> str | None:
    try:
        # soundcard initialises COM as multithreaded (MTA); comtypes would try STA on import and fail
        # with "Cannot change thread mode after it is set". COINIT_MULTITHREADED = 0.
        if not hasattr(sys, "coinit_flags"):
            sys.coinit_flags = 0
        import comtypes
        from pycaw.api.mmdeviceapi import IMMDeviceEnumerator
        from pycaw.constants import CLSID_MMDeviceEnumerator, EDataFlow, ERole

        try:
            comtypes.CoInitializeEx(0)  # COINIT_MULTITHREADED for this thread (no-op if already MTA)
        except OSError:
            pass
        enum = comtypes.CoCreateInstance(CLSID_MMDeviceEnumerator, IMMDeviceEnumerator, comtypes.CLSCTX_INPROC_SERVER)
        dev = enum.GetDefaultAudioEndpoint(EDataFlow.eCapture.value, ERole.eCommunications.value)
        return dev.GetId()
    except Exception:  # noqa: BLE001 - no capture device, or COM unavailable
        return None


def get_mic(name: str | None) -> AudioDevice | None:
    """Named mic, else the default communications mic, else the default mic, else None (no mic at all)."""
    import soundcard as sc

    try:
        mics = sc.all_microphones(include_loopback=False)
    except Exception:  # noqa: BLE001
        return None
    if not mics:
        return None
    if name:
        for m in mics:
            if m.name == name:
                return ScDevice(m)
    comm_id = _default_communications_capture_id()
    if comm_id:
        for m in mics:
            if m.id == comm_id:
                return ScDevice(m)
    try:
        return ScDevice(sc.default_microphone())
    except Exception:  # noqa: BLE001
        return ScDevice(mics[0])
