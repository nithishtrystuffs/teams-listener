"""Generate the Electron tray icons (desktop/assets/tray-<state>.png and @2x) from the v1 glyph."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from teams_listener.ui.tray import COLORS, make_icon_image

OUT = Path(__file__).resolve().parent.parent / "desktop" / "assets"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for state in COLORS:
        big = make_icon_image(state)
        big.resize((32, 32), 3).save(OUT / f"tray-{state}@2x.png")  # 3 = LANCZOS
        big.resize((16, 16), 3).save(OUT / f"tray-{state}.png")


if __name__ == "__main__":
    main()
