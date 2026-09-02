"""Custom styled widgets — gradients, scrollbars, modern buttons."""

from __future__ import annotations

import tkinter as tk
from tkinter import scrolledtext
from typing import Callable

import customtkinter as ctk

from wizard.gui.styles import (
    BG,
    BORDER,
    BUTTON_HEIGHT,
    BUTTON_WIDTH,
    ERROR,
    FONT_BODY,
    FONT_BUTTON,
    FONT_MONO,
    FONT_SMALL,
    FONT_SUBTITLE,
    FONT_TITLE,
    PRIMARY,
    PRIMARY_HOVER,
    SUCCESS,
    SURFACE,
    SURFACE_LIGHT,
    TEXT_PRIMARY,
    TEXT_SECONDARY,
    WARNING,
)


def load_icon(name: str, size: int = 32) -> ctk.CTkImage | None:
    from wizard.ui_helpers import load_icon as _load
    return _load(name, size)


class GradientButton(ctk.CTkButton):
    """Primary action button with indigo styling."""

    def __init__(
        self,
        master: tk.Misc,
        text: str,
        command: Callable[[], None] | None = None,
        icon: str | None = None,
        color: str = PRIMARY,
        width: int = BUTTON_WIDTH,
        **kwargs: object,
    ) -> None:
        img = load_icon(icon, 28) if icon else None
        super().__init__(
            master, text=text, image=img, compound="left", command=command,
            height=BUTTON_HEIGHT, width=width, font=FONT_BUTTON,
            fg_color=color, hover_color=PRIMARY_HOVER, corner_radius=10,
            **kwargs,  # type: ignore[arg-type]
        )


class ScrollPanel(ctk.CTkFrame):
    """Scrollable panel with visible scrollbar — 90% height usage."""

    def __init__(self, master: tk.Misc, height: int = 300, **kwargs: object) -> None:
        super().__init__(master, fg_color=SURFACE, corner_radius=10, **kwargs)  # type: ignore[call-arg]
        self.scroll = ctk.CTkScrollableFrame(self, fg_color=SURFACE, corner_radius=8, height=height)
        self.scroll.pack(fill="both", expand=True, padx=4, pady=4)

    @property
    def inner(self) -> ctk.CTkScrollableFrame:
        return self.scroll


class LogPanel(ctk.CTkFrame):
    """Text log with proper scrollbar (ScrolledText)."""

    def __init__(self, master: tk.Misc, height: int = 200) -> None:
        super().__init__(master, fg_color=SURFACE, corner_radius=10)
        self.text = scrolledtext.ScrolledText(
            self, height=max(8, height // 18), font=FONT_MONO,
            bg=SURFACE, fg=TEXT_PRIMARY, insertbackground=TEXT_PRIMARY,
            relief="flat", wrap="word", highlightthickness=1,
            highlightbackground=BORDER,
        )
        self.text.pack(fill="both", expand=True, padx=8, pady=8)

    def append(self, msg: str) -> None:
        self.text.insert("end", msg + "\n")
        self.text.see("end")

    def clear(self) -> None:
        self.text.delete("1.0", "end")


class TitleLabel(ctk.CTkLabel):
    def __init__(self, master: tk.Misc, text: str, subtitle: str = "") -> None:
        super().__init__(master, text=text, font=FONT_TITLE, text_color=TEXT_PRIMARY)
        self.subtitle_label: ctk.CTkLabel | None = None
        if subtitle:
            self.subtitle_label = ctk.CTkLabel(master, text=subtitle, font=FONT_SUBTITLE, text_color=TEXT_SECONDARY)


class StatusCard(ctk.CTkFrame):
    """Detection status card for dashboard."""

    def __init__(self, master: tk.Misc, title: str, ok: bool, detail: str = "") -> None:
        super().__init__(master, fg_color=SURFACE_LIGHT, corner_radius=10)
        color = SUCCESS if ok else ERROR
        icon_name = "checkmark" if ok else "error"
        img = load_icon(icon_name, 24)
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=12, pady=8)
        if img:
            ctk.CTkLabel(row, image=img, text="").pack(side="left", padx=(0, 8))
        ctk.CTkLabel(row, text=title, font=FONT_BODY, text_color=TEXT_PRIMARY).pack(side="left")
        ctk.CTkLabel(row, text="PASS" if ok else "FAIL", font=FONT_SMALL, text_color=color).pack(side="right")
        if detail:
            ctk.CTkLabel(self, text=detail, font=FONT_SMALL, text_color=TEXT_SECONDARY, wraplength=400, justify="left").pack(
                anchor="w", padx=12, pady=(0, 8),
            )


class PhoneCard(ctk.CTkFrame):
    """Dashboard phone card with status and actions."""

    def __init__(
        self,
        master: tk.Misc,
        name: str,
        index: int,
        running: bool,
        ip: str = "",
        on_details: Callable[[], None] | None = None,
        on_start: Callable[[], None] | None = None,
        on_stop: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(master, fg_color=SURFACE, corner_radius=12, width=220, height=160)
        self.pack_propagate(False)
        img = load_icon("phone", 36)
        if img:
            ctk.CTkLabel(self, image=img, text="").pack(pady=(12, 2))
        display = f"Phone {index + 1}" if name.startswith("Phone") else name
        ctk.CTkLabel(self, text=display, font=FONT_BODY, text_color=TEXT_PRIMARY).pack()
        status_c = SUCCESS if running else ERROR
        ctk.CTkLabel(self, text="Running" if running else "Stopped", font=FONT_SMALL, text_color=status_c).pack()
        if ip:
            ctk.CTkLabel(self, text=f"IP: {ip}", font=FONT_SMALL, text_color=TEXT_SECONDARY).pack()
        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(pady=6)
        if on_start:
            ctk.CTkButton(btns, text="Start", width=60, height=28, fg_color=SUCCESS, command=on_start).pack(side="left", padx=2)
        if on_stop:
            ctk.CTkButton(btns, text="Stop", width=60, height=28, fg_color=ERROR, command=on_stop).pack(side="left", padx=2)
        if on_details:
            ctk.CTkButton(btns, text="Details", width=60, height=28, command=on_details).pack(side="left", padx=2)
