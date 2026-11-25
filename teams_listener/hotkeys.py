"""Global mute hotkeys (listen-only: keys still reach Teams)."""
from __future__ import annotations

from typing import Callable

from pynput import keyboard

TEAMS_SHORTCUT = "<ctrl>+<shift>+m"


def build_hotkey_map(hotkey: str, follow_teams: bool, on_toggle: Callable[[], None]) -> dict[str, Callable]:
    keyboard.HotKey.parse(hotkey)  # raises ValueError on a bad hotkey string
    m = {hotkey: on_toggle}
    if follow_teams and hotkey != TEAMS_SHORTCUT:
        m[TEAMS_SHORTCUT] = on_toggle
    return m


class MuteHotkeys:
    """`on_toggle` runs on pynput's thread; the UI must marshal it to its own thread."""

    def __init__(self, hotkey: str, follow_teams: bool, on_toggle: Callable[[], None]):
        self._map = build_hotkey_map(hotkey, follow_teams, on_toggle)
        self._listener: keyboard.GlobalHotKeys | None = None

    def start(self) -> None:
        self._listener = keyboard.GlobalHotKeys(self._map)
        self._listener.start()

    def stop(self) -> None:
        if self._listener is not None:
            self._listener.stop()
            self._listener = None
