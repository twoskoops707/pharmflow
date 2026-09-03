"""UI helpers — custom icons, big buttons, friendly errors."""

from __future__ import annotations

import logging
import tkinter as tk
from pathlib import Path
from tkinter import scrolledtext
from typing import Callable

import customtkinter as ctk
from PIL import Image

from wizard.ui_theme import (
    ACCENT_BLUE,
    ACCENT_GREEN,
    ACCENT_ORANGE,
    ACCENT_RED,
    BG_CARD,
    BG_DARK,
    BUTTON_HEIGHT,
    BUTTON_WIDTH,
    FONT_BODY,
    FONT_BUTTON,
    FONT_SMALL,
    FONT_SUBTITLE,
    FONT_TITLE,
    ICON_SIZE,
    TEXT_MUTED,
    TEXT_PRIMARY,
)

from wizard.wizard_paths import bundle_root, is_frozen

logger = logging.getLogger(__name__)

ICONS_DIR = bundle_root() / "wizard" / "icons"
if is_frozen():
    # PyInstaller bundles icons under wizard/icons in MEIPASS
    _frozen_icons = bundle_root() / "wizard" / "icons"
    if _frozen_icons.is_dir():
        ICONS_DIR = _frozen_icons
    elif (bundle_root() / "icons").is_dir():
        ICONS_DIR = bundle_root() / "icons"
_icon_cache: dict[str, ctk.CTkImage] = {}


def icon_path(name: str) -> Path:
    """Return path to icon file (name without _icon suffix ok)."""
    if not name.endswith(".png"):
        name = f"{name}_icon.png" if not name.endswith("_icon") else f"{name}.png"
        if not name.endswith(".png"):
            name = f"{name}.png"
    # normalize: "phone" -> phone_icon.png
    if name == "phone.png":
        name = "phone_icon.png"
    p = ICONS_DIR / name
    if not p.is_file():
        # try adding _icon
        alt = ICONS_DIR / name.replace(".png", "_icon.png")
        if alt.is_file():
            return alt
    return p


def load_icon(name: str, size: int = ICON_SIZE) -> ctk.CTkImage | None:
    """Load a custom icon as CTkImage."""
    key = f"{name}:{size}"
    if key in _icon_cache:
        return _icon_cache[key]
    # Map short names
    mapping = {
        "phone": "phone_icon.png",
        "computer": "computer_icon.png",
        "network": "network_icon.png",
        "shield": "shield_icon.png",
        "download": "download_icon.png",
        "start": "start_icon.png",
        "stop": "stop_icon.png",
        "refresh": "refresh_icon.png",
        "settings": "settings_icon.png",
        "checkmark": "checkmark_icon.png",
        "warning": "warning_icon.png",
        "error": "error_icon.png",
        "app": "app_icon.png",
    }
    fname = mapping.get(name, name if name.endswith(".png") else f"{name}_icon.png")
    path = ICONS_DIR / fname
    if not path.is_file():
        logger.warning("Icon not found: %s", path)
        return None
    img = Image.open(path)
    ctk_img = ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))
    _icon_cache[key] = ctk_img
    return ctk_img


def friendly_error(exc: BaseException) -> str:
    """Convert technical exceptions to child-friendly messages."""
    msg = str(exc).lower()
    if "mumu" in msg or "not found" in msg:
        return "Oops! We could not find MuMu on your computer."
    if "adb" in msg:
        return "Oops! The phone connection did not work. Try starting the phone again."
    if "tor" in msg:
        return "Oops! The safe network (Tor) is not running yet."
    if "timeout" in msg:
        return "Oops! That took too long. Please try again."
    if "browser" in msg or "chrome" in msg:
        return "Oops! The web browser on the phone needs to be set up."
    return "Oops! Something didn't work. Please try again."


class BigButton(ctk.CTkButton):
    """Large labeled button with optional custom icon."""

    def __init__(
        self,
        master: tk.Misc,
        text: str,
        icon: str | None = None,
        command: Callable[[], None] | None = None,
        color: str = ACCENT_BLUE,
        **kwargs: object,
    ) -> None:
        img = load_icon(icon, 28) if icon else None
        super().__init__(
            master,
            text=text,
            image=img,
            compound="left",
            command=command,
            height=BUTTON_HEIGHT,
            width=BUTTON_WIDTH,
            font=FONT_BUTTON,
            fg_color=color,
            hover_color=_darken(color),
            corner_radius=12,
            **kwargs,  # type: ignore[arg-type]
        )


def _darken(hex_color: str, factor: float = 0.85) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"#{int(r*factor):02x}{int(g*factor):02x}{int(b*factor):02x}"


class ScreenFrame(ctk.CTkFrame):
    """One wizard screen — title + content area."""

    def __init__(self, master: tk.Misc, title: str, subtitle: str = "") -> None:
        super().__init__(master, fg_color=BG_DARK)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        ctk.CTkLabel(self, text=title, font=FONT_TITLE, text_color=TEXT_PRIMARY).grid(
            row=0, column=0, pady=(40, 4), padx=40,
        )
        if subtitle:
            ctk.CTkLabel(self, text=subtitle, font=FONT_SUBTITLE, text_color=TEXT_MUTED).grid(
                row=1, column=0, pady=(0, 20), padx=40,
            )
        self.content = ctk.CTkFrame(self, fg_color="transparent")
        self.content.grid(row=2, column=0, sticky="nsew", padx=40, pady=10)
        self.content.columnconfigure(0, weight=1)

    def clear_content(self) -> None:
        for w in self.content.winfo_children():
            w.destroy()


class ProgressLog(ctk.CTkFrame):
    """Scrollable progress log for setup screen."""

    def __init__(self, master: tk.Misc, height: int = 200) -> None:
        super().__init__(master, fg_color=BG_CARD, corner_radius=12)
        self.text = scrolledtext.ScrolledText(
            self, height=height // 20, font=FONT_SMALL, bg=BG_CARD, fg=TEXT_PRIMARY,
            insertbackground=TEXT_PRIMARY, relief="flat", wrap="word",
        )
        self.text.pack(fill="both", expand=True, padx=8, pady=8)

    def append(self, msg: str) -> None:
        self.text.insert("end", msg + "\n")
        self.text.see("end")

    def clear(self) -> None:
        self.text.delete("1.0", "end")


class PhoneCard(ctk.CTkFrame):
    """One phone in the dashboard grid."""

    def __init__(self, master: tk.Misc, phone_name: str, running: bool, index: int) -> None:
        super().__init__(master, fg_color=BG_CARD, corner_radius=12, width=200, height=140)
        self.pack_propagate(False)
        icon = load_icon("phone", 40)
        ctk.CTkLabel(self, image=icon, text="").pack(pady=(16, 4))
        display = f"Phone {index + 1}" if phone_name.startswith("Phone") else phone_name
        ctk.CTkLabel(self, text=display, font=FONT_BODY, text_color=TEXT_PRIMARY).pack()
        status_color = ACCENT_GREEN if running else ACCENT_RED
        status_text = "Running" if running else "Stopped"
        ctk.CTkLabel(self, text=status_text, font=FONT_SMALL, text_color=status_color).pack(pady=4)


class ErrorScreen(ScreenFrame):
    """Friendly error screen with retry."""

    def __init__(
        self,
        master: tk.Misc,
        title: str,
        message: str,
        on_retry: Callable[[], None] | None = None,
        on_download: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master, title, message)
        icon = load_icon("error", 48)
        if icon:
            ctk.CTkLabel(self.content, image=icon, text="").pack(pady=20)
        btn_frame = ctk.CTkFrame(self.content, fg_color="transparent")
        btn_frame.pack(pady=20)
        if on_retry:
            BigButton(btn_frame, "TRY AGAIN", icon="refresh", command=on_retry).pack(pady=8)
        if on_download:
            BigButton(btn_frame, "DOWNLOAD MUMU", icon="download", command=on_download, color=ACCENT_ORANGE).pack(pady=8)


class WizardShell(ctk.CTk):
    """Base window for setup and main wizards."""

    def __init__(self, title: str = "PharmFlow Phone Farm") -> None:
        super().__init__()
        self.title(title)
        self.geometry("900x650")
        self.minsize(800, 600)
        self.configure(fg_color=BG_DARK)
        app_icon = load_icon("app", 32)
        if app_icon:
            try:
                self.iconphoto(True, app_icon._light_image)  # type: ignore[attr-defined]
            except Exception:
                pass
        self._screens: dict[str, ctk.CTkFrame] = {}
        self._container = ctk.CTkFrame(self, fg_color=BG_DARK)
        self._container.pack(fill="both", expand=True)

    def show_screen(self, name: str) -> None:
        for n, frame in self._screens.items():
            frame.pack_forget()
        if name in self._screens:
            self._screens[name].pack(fill="both", expand=True)

    def register_screen(self, name: str, frame: ctk.CTkFrame) -> None:
        self._screens[name] = frame
        frame.pack(fill="both", expand=True)
