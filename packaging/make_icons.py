"""Generate the Electron tray icons (desktop/assets/tray-<state>.png and @2x) from the v1 glyph."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from PIL import Image, ImageDraw

from teams_listener.ui.tray import COLORS, make_icon_image

OUT = Path(__file__).resolve().parent.parent / "desktop" / "assets"


def make_app_icon(size: int = 512) -> Image.Image:
    """Rounded-square blue->cyan gradient (like the in-app logo) with a white mic."""
    c1, c2 = (59, 130, 246), (34, 211, 238)
    grad = Image.new("RGBA", (size, size))
    px = grad.load()
    for y in range(size):
        for x in range(size):
            t = (x + y) / (2 * (size - 1))
            px[x, y] = tuple(round(a + (b - a) * t) for a, b in zip(c1, c2)) + (255,)
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=size * 0.22, fill=255)
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    img.paste(grad, (0, 0), mask)
    d = ImageDraw.Draw(img)
    u = size / 64
    white = (255, 255, 255, 255)
    d.rounded_rectangle((25 * u, 12 * u, 39 * u, 36 * u), radius=7 * u, fill=white)
    d.arc((18 * u, 22 * u, 46 * u, 46 * u), start=0, end=180, fill=white, width=round(3.2 * u))
    d.line((32 * u, 46 * u, 32 * u, 53 * u), fill=white, width=round(3.2 * u))
    d.line((25 * u, 53 * u, 39 * u, 53 * u), fill=white, width=round(3.2 * u))
    return img


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for state in COLORS:
        big = make_icon_image(state)
        big.resize((32, 32), 3).save(OUT / f"tray-{state}@2x.png")  # 3 = LANCZOS
        big.resize((16, 16), 3).save(OUT / f"tray-{state}.png")
    app = make_app_icon(512)
    app.save(OUT / "icon.png")
    app.save(OUT / "icon.ico", sizes=[(256, 256), (64, 64), (32, 32), (16, 16)])


if __name__ == "__main__":
    main()
