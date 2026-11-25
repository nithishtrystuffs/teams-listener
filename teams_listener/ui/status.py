"""What the mic button / tray should say. Kept free of Tk so it can be tested."""
from __future__ import annotations


def mic_display(recording: bool, muted: bool, mic_name: str | None) -> tuple[str, str]:
    """Returns (state, text); state is one of idle | nomic | muted | live."""
    if not recording:
        return "idle", "MIC: not recording"
    if mic_name is None:
        return "nomic", "⚠ NO MICROPHONE FOUND — recording Others only"
    if muted:
        return "muted", "🔇 MUTED — click or press shortcut to speak"
    return "live", f"🎙 LIVE — recording {mic_name}"
