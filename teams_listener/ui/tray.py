"""System-tray icon. Callbacks run on pystray's thread; the app marshals them to Tk."""
from __future__ import annotations

from typing import Callable

import pystray
from PIL import Image, ImageDraw

COLORS = {"idle": (128, 128, 128), "muted": (215, 38, 38), "live": (40, 170, 70)}


def make_icon_image(state: str) -> Image.Image:
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.ellipse((4, 4, 60, 60), fill=COLORS[state] + (255,))
    # simple mic glyph
    d.rounded_rectangle((25, 14, 39, 38), radius=7, fill=(255, 255, 255, 255))
    d.arc((19, 24, 45, 46), start=0, end=180, fill=(255, 255, 255, 255), width=3)
    d.line((32, 46, 32, 52), fill=(255, 255, 255, 255), width=3)
    return img


class Tray:
    def __init__(self, on_show: Callable, on_start_stop: Callable, on_mute: Callable, on_quit: Callable,
                 is_recording: Callable[[], bool], is_muted: Callable[[], bool]):
        menu = pystray.Menu(
            pystray.MenuItem("Show", lambda: on_show(), default=True),
            pystray.MenuItem(lambda item: "Stop recording" if is_recording() else "Start recording",
                             lambda: on_start_stop()),
            pystray.MenuItem(lambda item: "Unmute mic" if is_muted() else "Mute mic", lambda: on_mute(),
                             enabled=lambda item: is_recording()),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", lambda: on_quit()),
        )
        self._icon = pystray.Icon("teams_listener", make_icon_image("idle"), "Teams Listener — idle", menu)

    def start(self) -> None:
        self._icon.run_detached()
        self._running = True

    def set_state(self, state: str, tooltip: str) -> None:
        self._icon.icon = make_icon_image(state)
        self._icon.title = tooltip
        if getattr(self, "_running", False):
            self._icon.update_menu()

    def stop(self) -> None:
        self._icon.stop()
