"""Generate custom PharmFlow UI icons — simple, consistent, child-readable."""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw

SIZE = 64
OUT = Path(__file__).resolve().parent.parent / "wizard" / "icons"
COLOR = "#6366F1"
ACCENT = "#22C55E"
WARN = "#F59E0B"
ERR = "#EF4444"
BG = (0, 0, 0, 0)


def _new() -> tuple[Image.Image, ImageDraw.ImageDraw]:
    img = Image.new("RGBA", (SIZE, SIZE), BG)
    return img, ImageDraw.Draw(img)


def _save(img: Image.Image, name: str) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    img.save(OUT / name)


def phone() -> None:
    img, d = _new()
    d.rounded_rectangle((18, 8, 46, 56), radius=6, outline=COLOR, width=3)
    d.ellipse((28, 48, 36, 52), fill=COLOR)
    _save(img, "phone_icon.png")


def computer() -> None:
    img, d = _new()
    d.rounded_rectangle((10, 12, 54, 40), radius=4, outline=COLOR, width=3)
    d.rectangle((26, 40, 38, 44), fill=COLOR)
    d.rectangle((16, 44, 48, 48), fill=COLOR)
    _save(img, "computer_icon.png")


def network() -> None:
    img, d = _new()
    d.ellipse((16, 16, 48, 48), outline=COLOR, width=3)
    d.line((8, 32, 56, 32), fill=COLOR, width=2)
    d.line((32, 8, 32, 56), fill=COLOR, width=2)
    d.ellipse((28, 28, 36, 36), fill=ACCENT)
    _save(img, "network_icon.png")


def shield() -> None:
    img, d = _new()
    d.polygon([(32, 8), (52, 18), (52, 38), (32, 56), (12, 38), (12, 18)], outline=COLOR, width=3)
    d.line((22, 32, 30, 40), fill=ACCENT, width=3)
    d.line((30, 40, 44, 24), fill=ACCENT, width=3)
    _save(img, "shield_icon.png")


def start_play() -> None:
    img, d = _new()
    d.polygon([(22, 16), (22, 48), (48, 32)], fill=ACCENT)
    _save(img, "start_icon.png")


def stop() -> None:
    img, d = _new()
    d.rounded_rectangle((20, 20, 44, 44), radius=3, fill=ERR)
    _save(img, "stop_icon.png")


def refresh() -> None:
    img, d = _new()
    d.arc((12, 12, 52, 52), start=45, end=315, fill=COLOR, width=3)
    d.polygon([(44, 10), (54, 18), (42, 22)], fill=COLOR)
    _save(img, "refresh_icon.png")


def download() -> None:
    img, d = _new()
    d.line((32, 12, 32, 40), fill=COLOR, width=3)
    d.polygon([(32, 44), (22, 32), (42, 32)], fill=COLOR)
    d.line((16, 52, 48, 52), fill=COLOR, width=3)
    _save(img, "download_icon.png")


def settings() -> None:
    img, d = _new()
    cx, cy, r = 32, 32, 10
    d.ellipse((cx - r, cy - r, cx + r, cy + r), outline=COLOR, width=3)
    for i in range(8):
        a = i * math.pi / 4
        x1 = cx + int(14 * math.cos(a))
        y1 = cy + int(14 * math.sin(a))
        x2 = cx + int(20 * math.cos(a))
        y2 = cy + int(20 * math.sin(a))
        d.line((x1, y1, x2, y2), fill=COLOR, width=3)
    _save(img, "settings_icon.png")


def checkmark() -> None:
    img, d = _new()
    d.line((14, 34, 28, 48), fill=ACCENT, width=4)
    d.line((28, 48, 50, 18), fill=ACCENT, width=4)
    _save(img, "checkmark_icon.png")


def warning() -> None:
    img, d = _new()
    d.polygon([(32, 10), (54, 50), (10, 50)], outline=WARN, width=3)
    d.line((32, 24, 32, 38), fill=WARN, width=3)
    d.ellipse((30, 42, 34, 46), fill=WARN)
    _save(img, "warning_icon.png")


def error() -> None:
    img, d = _new()
    d.ellipse((10, 10, 54, 54), outline=ERR, width=3)
    d.line((22, 22, 42, 42), fill=ERR, width=3)
    d.line((42, 22, 22, 42), fill=ERR, width=3)
    _save(img, "error_icon.png")


def app_icon() -> None:
    img, d = _new()
    d.rounded_rectangle((4, 4, 60, 60), radius=12, fill="#1E293B")
    d.rounded_rectangle((18, 8, 46, 56), radius=6, outline="#6366F1", width=3)
    d.ellipse((28, 48, 36, 52), fill="#22C55E")
    _save(img, "app_icon.png")
    # Multi-size ICO for Windows PyInstaller / Explorer
    sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    icons = [img.resize(size, Image.Resampling.LANCZOS) for size in sizes]
    icons[0].save(OUT / "app_icon.ico", format="ICO", sizes=[(s[0], s[1]) for s in sizes])


def add_icon() -> None:
    img, d = _new()
    d.line((32, 16, 32, 48), fill=COLOR, width=3)
    d.line((16, 32, 48, 32), fill=COLOR, width=3)
    _save(img, "add_icon.png")
    _save(img, "add.png")


def remove_icon() -> None:
    img, d = _new()
    d.line((16, 32, 48, 32), fill=ERR, width=3)
    _save(img, "remove_icon.png")
    _save(img, "remove.png")


def edit_icon() -> None:
    img, d = _new()
    d.polygon([(44, 12), (52, 20), (24, 48), (14, 50), (16, 40)], outline=COLOR, width=2)
    _save(img, "edit_icon.png")
    _save(img, "edit.png")


def eye_icon() -> None:
    img, d = _new()
    d.ellipse((12, 24, 52, 44), outline=COLOR, width=2)
    d.ellipse((28, 30, 36, 38), fill=COLOR)
    _save(img, "eye_icon.png")
    _save(img, "eye.png")


def eye_off_icon() -> None:
    img, d = _new()
    d.line((12, 20, 52, 48), fill=ERR, width=2)
    d.ellipse((12, 24, 52, 44), outline=COLOR, width=2)
    _save(img, "eye_off_icon.png")
    _save(img, "eye_off.png")


def _alias_icons() -> None:
    """Create short-name aliases (phone.png, play.png, etc.)."""
    aliases = {
        "phone_icon.png": "phone.png",
        "start_icon.png": "play.png",
        "checkmark_icon.png": "check.png",
        "computer_icon.png": "computer.png",
        "network_icon.png": "network.png",
        "shield_icon.png": "shield.png",
        "download_icon.png": "download.png",
        "stop_icon.png": "stop.png",
        "refresh_icon.png": "refresh.png",
        "settings_icon.png": "settings.png",
        "warning_icon.png": "warning.png",
        "error_icon.png": "error.png",
    }
    for src, dst in aliases.items():
        s = OUT / src
        d = OUT / dst
        if s.is_file() and not d.is_file():
            d.write_bytes(s.read_bytes())


def main() -> None:
    phone()
    computer()
    network()
    shield()
    start_play()
    stop()
    refresh()
    download()
    settings()
    checkmark()
    warning()
    error()
    app_icon()
    add_icon()
    remove_icon()
    edit_icon()
    eye_icon()
    eye_off_icon()
    _alias_icons()
    print(f"Generated icons in {OUT}")


if __name__ == "__main__":
    main()
