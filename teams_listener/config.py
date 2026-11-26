"""User settings, stored as JSON in %APPDATA%\TeamsListener\settings.json."""
from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

ALLOWED_MODELS = ("small.en", "medium.en")
ALLOWED_THEMES = ("system", "light", "dark")
DEFAULT_SETTINGS_PATH = Path(os.environ.get("APPDATA", Path.home())) / "TeamsListener" / "settings.json"


@dataclass
class Settings:
    model: str = "small.en"
    model_path: str | None = None
    mic_device: str | None = None  # None = follow Windows default communications mic
    hotkey: str = "<ctrl>+<alt>+m"
    follow_teams_shortcut: bool = False
    delete_audio_after: bool = False
    output_dir: str = field(default_factory=lambda: str(Path.home() / "Documents" / "TeamsTranscripts"))
    theme: str = "system"  # system | light | dark


def load_settings(path: Path | None = None) -> Settings:
    path = Path(path or DEFAULT_SETTINGS_PATH)
    if not path.exists():
        return Settings()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("settings root is not an object")
    except (ValueError, OSError):
        try:
            path.replace(path.with_name(path.name + ".bak"))
        except OSError:
            pass
        return Settings()
    known = {f.name for f in fields(Settings)}
    s = Settings(**{k: v for k, v in raw.items() if k in known})
    if s.model not in ALLOWED_MODELS:
        s.model = Settings.model
    if s.theme not in ALLOWED_THEMES:
        s.theme = Settings.theme
    return s


def save_settings(s: Settings, path: Path | None = None) -> None:
    path = Path(path or DEFAULT_SETTINGS_PATH)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(s), indent=2), encoding="utf-8")
