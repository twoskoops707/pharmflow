"""
CPharm UI tokens + Tk helpers (`wizard/setup_wizard.py`).

**Studio shell:** violet/slate palette + left sidebar rail (see ``CPharmWizard``) — not a “recolored
horizontal stepper.” Canvas vs cards: BG / BG2 / BG3; avoid loud yellow — WORKING / CALLOUT_* / WARN_FG.

PyInstaller one-file: bundle assets next to the frozen module, e.g. from ``wizard/``:
  ``--add-data "assets;assets"``
"""

from __future__ import annotations

import sys
import tkinter as tk
from pathlib import Path
from tkinter import ttk

_wizard_dir = Path(__file__).resolve().parent
_sd = str(_wizard_dir)
if _sd not in sys.path:
    sys.path.insert(0, _sd)

from wizard_paths import wizard_assets_dir

# --- Hierarchy (canvas → elevated cards) — cool violet/slate base ---
BG = "#0f1219"  # canvas — content pane & page background
BG2 = "#161c27"  # primary card / footer / top strip
BG3 = "#1e2633"  # nested / inset surfaces
BG4 = "#2a3445"  # hover / diagram tiles
BG_LOG_ROW = "#121820"  # code / mono strip

# Dedicated sidebar rail (left column shell — darker than canvas)
SHELL_SIDEBAR_BG = "#0b0f17"

# Footer dock (pair with ``style_*_button`` for hover states below)
FOOTER_BG = BG3  # bottom bar — inset from content canvas (BG); reads as “dock”

# Chrome & borders (Tk: simulate shadow with highlightbackground + flat relief)
BORDER = "#3a4659"
BORDER_STRONG = "#4f6078"
BORDER_FOCUS = "#7286a3"

# Accent — teal "Dark Signal desk" (FamFlow design system; matches the
# dashboard's --s:#14B8A6 signal. Plain, readable on dark; not purple.)
ACCENT = "#14B8A6"
ACCENT_DIM = "#0d9488"
ACCENT_GLOW = "#5eead4"
ACCENT_MUTED = "#0f766e"
ACCENT_SUBTLE = "#0b2e2a"  # soft fill behind accent-tinted areas

# Shell chrome lines (must follow ACCENT_* definitions — avoid NameError at import)
DIVIDER_ACCENT = ACCENT_MUTED  # 2px rule above footer / subtle chrome lines
SHELL_RAIL_ACCENT = ACCENT_DIM  # 2px strip between sidebar and main content

# Semantic fills (success / danger / emphasis)
GREEN = "#3ecfb0"
GREEN_ACTIVE = "#35b89c"
RED = "#e88888"
RED_ACTIVE = "#d07070"
PURPLE = "#9b9be0"
PURPLE_ACTIVE = "#8888cf"

# Text
T1 = "#eef2f8"
T2 = "#b8c5d6"
T3 = "#8697ab"
ON_ACCENT = "#0b0818"
BLACK = "#000000"

# States — replaces harsh yellow for “working” / attention (muted, readable on dark)
WORKING = "#7eb8d6"  # soft sky — in progress, busy
WARN_FG = "#d4a574"  # muted amber text only (no yellow panels)
WARN_BG = "#1c1814"
CALLOUT_BG = "#12101f"
CALLOUT_BORDER = ACCENT_MUTED
CALLOUT_STRIP = ACCENT  # left-edge accent for callout chrome

# Legacy alias: migrating code — prefer STATUS_PROGRESS / WORKING
YELLOW = WORKING

# Aliases for clearer setup_wizard usage (no harsh yellow in UI)
STATUS_PROGRESS = WORKING
STATUS_PENDING = "#8aa4b8"
WARNING = WARN_FG

# Text on callout panels (CALLOUT_BG)
CALLOUT_FG = T1
CALLOUT_MUTED = T2
CALLOUT_ACCENT_BAR = CALLOUT_STRIP

# MuMu / special surfaces
BG_MUMU = "#12181c"

# spacing scale (px)
SP = {"xs": 4, "sm": 8, "md": 12, "lg": 16, "xl": 24, "card": 14, "page": 20}


def instruction_card(
    parent: tk.Misc,
    *,
    bg: str = BG2,
    pad: int | None = None,
) -> tk.Frame:
    """Instruction or summary block: elevated card (``BG2`` + ``BORDER``) with theme padding."""
    p = SP["card"] if pad is None else pad
    return tk.Frame(
        parent,
        bg=bg,
        padx=p,
        pady=p,
        highlightthickness=1,
        highlightbackground=BORDER,
    )


def operator_callout(
    parent: tk.Misc,
    *,
    title: str = "",
    pad: int | None = None,
) -> tuple[tk.Frame, tk.Frame]:
    """Operator-facing callout: ``CALLOUT_*`` fill, left accent strip. Returns ``(outer, body)``."""
    p = SP["card"] if pad is None else pad
    outer = tk.Frame(
        parent,
        bg=CALLOUT_BG,
        highlightthickness=1,
        highlightbackground=CALLOUT_BORDER,
    )
    row = tk.Frame(outer, bg=CALLOUT_BG, padx=p, pady=p)
    row.pack(fill="both", expand=True)
    tk.Frame(row, bg=CALLOUT_ACCENT_BAR, width=3).pack(side="left", fill="y", padx=(0, SP["sm"]))
    body = tk.Frame(row, bg=CALLOUT_BG)
    body.pack(side="left", fill="both", expand=True)
    if title:
        tk.Label(
            body,
            text=title,
            font=FONT_SECTION,
            bg=CALLOUT_BG,
            fg=CALLOUT_FG,
            anchor="w",
        ).pack(fill="x")
    return outer, body


def callout_copy(
    parent: tk.Misc,
    text: str,
    *,
    wrap_container: tk.Misc | None = None,
    pady_top: int | None = None,
) -> tk.Label:
    """Body copy inside an ``operator_callout`` body — responsive wrap, no clipping."""
    top = SP["xs"] if pady_top is None else pady_top
    lbl = tk.Label(
        parent,
        text=text,
        font=FONT_BODY,
        bg=CALLOUT_BG,
        fg=CALLOUT_MUTED,
        anchor="w",
        justify="left",
    )
    lbl.pack(fill="x", pady=(top, 0))
    host = wrap_container if wrap_container is not None else parent
    bind_responsive_wraplength(lbl, host, pad=32, min_width=180)
    return lbl

# corner radius (px) — canvas cards / parity with web --rad
RADIUS = {"sm": 6, "md": 10, "lg": 14, "xl": 18}

# Typography scale (Segoe UI — Tk on Windows)
FONT_DISPLAY = ("Segoe UI", 22, "bold")  # hero / window identity
FONT_PAGE_TITLE = ("Segoe UI", 18, "bold")
FONT_SECTION = ("Segoe UI", 11, "bold")
FONT_BODY = ("Segoe UI", 11)
FONT_UI = ("Segoe UI", 12)
FONT_CAPTION = ("Segoe UI", 10)
FONT_EYEBROW = ("Segoe UI", 8, "bold")
FONT_MONO = ("Consolas", 11)

# Back-compat names used across setup_wizard
FONT_HERO = ("Segoe UI", 24, "bold")
FONT_H1 = FONT_PAGE_TITLE
FONT_H2 = FONT_SECTION
FONT_LEAD = ("Segoe UI", 12)
FH = FONT_PAGE_TITLE
FS = FONT_BODY
FB = FONT_UI
FG = ("Segoe UI", 13)
FM = FONT_MONO

CPharm_TSCROLL = "CPharm.Vertical.TScrollbar"

# Scroll architecture — bottom spacer prevents last controls sitting under scrollbar thumb.
SCROLL_BOTTOM_PAD = 56

# Scrollbars: ``themed_vertical_scrollbar`` uses ``ttk.Scrollbar`` + ``_style_scrollbars`` (clam).
# ``tk.Scrollbar`` ``troughcolor`` can still paint a light/native track on some Windows Tk builds.
SCROLL_TROUGH = BG
SCROLL_THUMB = ACCENT_MUTED
SCROLL_THUMB_HOVER = ACCENT
SCROLL_THUMB_ACTIVE = ACCENT_DIM

# Nested canvases (dialogs / panes) — ``register_nested_scroll_canvas`` avoids double-scroll with shell.
_nested_scroll_registry: dict[int, set[int]] = {}

# Keyed by (asset basename, id(winfo_toplevel)) so each Tk interpreter gets its own
# PhotoImage; reusing one cache entry across destroyed roots breaks unittest order (TclError).
_icon_cache: dict[tuple[str, int], tk.PhotoImage] = {}


def themed_vertical_scrollbar(parent: tk.Misc, *, command) -> ttk.Scrollbar:
    """Vertical scrollbar using clam + ``CPharm_TSCROLL`` (reliable dark trough on Windows)."""
    _style_scrollbars(parent.winfo_toplevel())
    return ttk.Scrollbar(
        parent,
        orient="vertical",
        command=command,
        style=CPharm_TSCROLL,
        takefocus=False,
    )


def bind_responsive_wraplength(
    label: tk.Label,
    container: tk.Misc,
    *,
    pad: int = 48,
    min_width: int = 200,
) -> None:
    """Keep ``wraplength`` in sync with container width so long operator copy never clips."""

    def _sync(_event: tk.Event | None = None) -> None:
        try:
            w = int(container.winfo_width())
        except (tk.TclError, ValueError):
            return
        if w > 1:
            label.configure(wraplength=max(min_width, w - pad))

    container.bind("<Configure>", _sync, add="+")
    label.after_idle(_sync)


def assets_dir() -> Path:
    """Directory containing ``*.png`` icons (development or PyInstaller extract)."""
    return wizard_assets_dir()


def load_icon(name: str, master: tk.Misc) -> tk.PhotoImage | None:
    """
    Load ``assets/{name}.png`` as ``PhotoImage``. Returns None if missing.
    Safe to call repeatedly; images are cached per Tk toplevel (not only per process).
    """
    base = name if name.endswith(".png") else f"{name}.png"
    try:
        root = master.winfo_toplevel()
    except tk.TclError:
        return None
    key = (base, id(root))
    if key in _icon_cache:
        return _icon_cache[key]
    path = assets_dir() / base
    if not path.is_file():
        return None
    try:
        img = tk.PhotoImage(master=master, file=str(path))
    except tk.TclError:
        return None
    _icon_cache[key] = img
    return img


def style_success_button(w: tk.Button) -> None:
    """Green primary — matches CPharmMuMuSetup GO button."""
    w.configure(
        bg=GREEN,
        fg=ON_ACCENT,
        activebackground=GREEN_ACTIVE,
        activeforeground=ON_ACCENT,
        relief="flat",
        bd=0,
        highlightthickness=1,
        highlightbackground=BORDER,
        highlightcolor=GREEN,
        cursor="hand2",
    )


def accent_top_strip(parent: tk.Misc, *, height: int = 3) -> tk.Frame:
    """Violet accent rule (setup exe / studio chrome parity)."""
    return tk.Frame(parent, bg=ACCENT, height=height)


def mumu_setup_callout(parent: tk.Misc) -> tk.Frame:
    """MuMu users: Phone Setup is the first tab in CPharm."""
    outer, body = operator_callout(parent, title="MuMu users — do this first")
    callout_copy(
        body,
        "1. In CPharm, open the Phone Setup tab (same glass UI as this guide).\n"
        "2. Follow the checklist → click GO.\n"
        "3. Cold-boot MuMu phones if GO asks, then GO again.\n"
        "4. Use Install and Go & Run tabs, or Advanced wizard for teams/builder.",
        wrap_container=outer,
    )
    return outer


def style_primary_button(w: tk.Button) -> None:
    """Accent-filled primary action.

    Hover recipe (consistent Studio chrome): fill ACCENT → active ACCENT_DIM;
    secondary: BG3 → BG4 + BORDER; ghost: BG2 → BG3 on FOOTER_BG/BG2 bars;
    keep highlightborder BORDER unless keyboard focus (ACCENT_GLOW via highlightcolor).
    """
    w.configure(
        bg=ACCENT,
        fg=ON_ACCENT,
        activebackground=ACCENT_DIM,
        activeforeground=ON_ACCENT,
        relief="flat",
        bd=0,
        highlightthickness=1,
        highlightbackground=BORDER,
        highlightcolor=ACCENT_GLOW,
        cursor="hand2",
    )


def style_secondary_button(w: tk.Button) -> None:
    """Muted surface — outline via border highlight."""
    w.configure(
        bg=BG3,
        fg=T1,
        activebackground=BG4,
        activeforeground=T1,
        relief="flat",
        bd=0,
        highlightthickness=1,
        highlightbackground=BORDER,
        cursor="hand2",
    )


def style_ghost_button(w: tk.Button) -> None:
    """Low-emphasis control (e.g. Cancel) — blends with header/footer bar (BG2)."""
    w.configure(
        bg=BG2,
        fg=T2,
        activebackground=BG3,
        activeforeground=T1,
        relief="flat",
        bd=0,
        highlightthickness=0,
        cursor="hand2",
    )


def style_danger_button(w: tk.Button) -> None:
    w.configure(
        bg=RED,
        fg=ON_ACCENT,
        activebackground=RED_ACTIVE,
        activeforeground=ON_ACCENT,
        relief="flat",
        bd=0,
        highlightthickness=1,
        highlightbackground=BORDER,
        highlightcolor=RED_ACTIVE,
        cursor="hand2",
    )


def draw_round_rect(
    canvas: tk.Canvas,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    r: float,
    **kwargs,
) -> None:
    """Rounded rectangle using arcs + rectangles (Tk has no native radius)."""
    if x2 < x1:
        x1, x2 = x2, x1
    if y2 < y1:
        y1, y2 = y2, y1
    tags = kwargs.pop("tags", ())
    fill = kwargs.pop("fill", "")
    outline = kwargs.pop("outline", "")
    width = int(kwargs.pop("width", 1))
    r = min(float(r), (x2 - x1) / 2, (y2 - y1) / 2)
    if r <= 0:
        canvas.create_rectangle(x1, y1, x2, y2, fill=fill, outline=outline, width=width, tags=tags)
        return
    d = 2 * r
    if fill:
        canvas.create_rectangle(x1 + r, y1, x2 - r, y2, fill=fill, outline="", tags=tags)
        canvas.create_rectangle(x1, y1 + r, x2, y2 - r, fill=fill, outline="", tags=tags)
        canvas.create_arc(x1, y1, x1 + d, y1 + d, start=90, extent=90, fill=fill, outline="", tags=tags)
        canvas.create_arc(x2 - d, y1, x2, y1 + d, start=0, extent=90, fill=fill, outline="", tags=tags)
        canvas.create_arc(x2 - d, y2 - d, x2, y2, start=270, extent=90, fill=fill, outline="", tags=tags)
        canvas.create_arc(x1, y2 - d, x1 + d, y2, start=180, extent=90, fill=fill, outline="", tags=tags)
    if outline:
        canvas.create_line(x1 + r, y1, x2 - r, y1, fill=outline, width=width, tags=tags)
        canvas.create_line(x1 + r, y2, x2 - r, y2, fill=outline, width=width, tags=tags)
        canvas.create_line(x1, y1 + r, x1, y2 - r, fill=outline, width=width, tags=tags)
        canvas.create_line(x2, y1 + r, x2, y2 - r, fill=outline, width=width, tags=tags)
        canvas.create_arc(
            x1, y1, x1 + d, y1 + d, start=90, extent=90,
            style="arc", outline=outline, width=width, tags=tags,
        )
        canvas.create_arc(
            x2 - d, y1, x2, y1 + d, start=0, extent=90,
            style="arc", outline=outline, width=width, tags=tags,
        )
        canvas.create_arc(
            x2 - d, y2 - d, x2, y2, start=270, extent=90,
            style="arc", outline=outline, width=width, tags=tags,
        )
        canvas.create_arc(
            x1, y2 - d, x1 + d, y2, start=180, extent=90,
            style="arc", outline=outline, width=width, tags=tags,
        )


def _style_scrollbars(root: tk.Misc) -> None:
    """Themed ttk scrollbars: wide thumb, flat rail, no arrows — readable on dark UI."""
    try:
        style = ttk.Style(root)
    except tk.TclError:
        return
    # Windows "vista"/native themes often ignore custom scrollbar colors; clam honors them.
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass

    v_layout = [
        (
            "Vertical.Scrollbar.trough",
            {
                "sticky": "ns",
                "children": [
                    (
                        "Vertical.Scrollbar.thumb",
                        {"expand": "1", "sticky": "nswe"},
                    )
                ],
            },
        )
    ]
    h_layout = [
        (
            "Horizontal.Scrollbar.trough",
            {
                "sticky": "ew",
                "children": [
                    (
                        "Horizontal.Scrollbar.thumb",
                        {"expand": "1", "sticky": "nswe"},
                    )
                ],
            },
        )
    ]

    # Dark trough + green/blue thumb (parity with web dashboard / ``themed_vertical_scrollbar``).
    sc_trough = SCROLL_TROUGH
    sc_thumb = SCROLL_THUMB
    sc_thumb_hi = SCROLL_THUMB_HOVER
    sc_thumb_press = SCROLL_THUMB_ACTIVE

    def _apply_vertical(name: str) -> None:
        try:
            style.layout(name, v_layout)
        except tk.TclError:
            pass
        style.configure(
            name,
            background=sc_thumb,
            troughcolor=sc_trough,
            bordercolor=sc_trough,
            lightcolor=sc_thumb,
            darkcolor=sc_thumb,
            arrowcolor=T3,
            arrowsize=0,
            borderwidth=0,
            relief="flat",
            width=7,
            gripcount=0,
        )
        style.map(
            name,
            background=[
                ("pressed !disabled", sc_thumb_press),
                ("active !disabled", sc_thumb_hi),
                ("disabled", BG3),
            ],
            troughcolor=[
                ("readonly", sc_trough),
                ("disabled", BG2),
            ],
            lightcolor=[
                ("pressed !disabled", sc_thumb_press),
                ("active !disabled", sc_thumb_hi),
            ],
            darkcolor=[
                ("pressed !disabled", sc_thumb_press),
                ("active !disabled", sc_thumb_hi),
            ],
        )

    def _apply_horizontal(name: str) -> None:
        try:
            style.layout(name, h_layout)
        except tk.TclError:
            pass
        style.configure(
            name,
            background=sc_thumb,
            troughcolor=sc_trough,
            bordercolor=sc_trough,
            lightcolor=sc_thumb,
            darkcolor=sc_thumb,
            arrowcolor=T3,
            arrowsize=0,
            borderwidth=0,
            relief="flat",
            width=7,
            gripcount=0,
        )
        style.map(
            name,
            background=[
                ("pressed !disabled", sc_thumb_press),
                ("active !disabled", sc_thumb_hi),
                ("disabled", BG3),
            ],
            troughcolor=[
                ("readonly", sc_trough),
                ("disabled", BG2),
            ],
            lightcolor=[
                ("pressed !disabled", sc_thumb_press),
                ("active !disabled", sc_thumb_hi),
            ],
            darkcolor=[
                ("pressed !disabled", sc_thumb_press),
                ("active !disabled", sc_thumb_hi),
            ],
        )

    # Custom class + default ttk names so unstylized scrollbars still match the dark theme.
    _apply_vertical(CPharm_TSCROLL)
    _apply_vertical("Vertical.TScrollbar")
    _apply_horizontal("Horizontal.TScrollbar")

    # clam theme defaults are light — keep combobox + progress bars on the dark stack.
    try:
        style.configure(
            "TCombobox",
            fieldbackground=BG3,
            background=BG3,
            foreground=T1,
            arrowcolor=T2,
            bordercolor=BORDER,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", BG3)],
            background=[("readonly", BG3)],
        )
    except tk.TclError:
        pass
    try:
        style.configure(
            "Horizontal.TProgressbar",
            background=GREEN,
            troughcolor=BG3,
            borderwidth=0,
            lightcolor=GREEN,
            darkcolor=GREEN,
        )
        style.configure(
            "Vertical.TProgressbar",
            background=GREEN,
            troughcolor=BG3,
            borderwidth=0,
            lightcolor=GREEN,
            darkcolor=GREEN,
        )
    except tk.TclError:
        pass


def canvas_embed_set_width(canvas: tk.Canvas, window_item_id: int, event: tk.Event) -> None:
    """Resize a ``Canvas.create_window`` child to match the canvas width.

    Skips zero/negative widths from transient Configure events (minimize, rapid resize)
    that can confuse Tk geometry or clip embedded frames.
    """
    try:
        w = int(event.width)
    except (tk.TclError, ValueError, TypeError):
        return
    if w <= 0:
        return
    try:
        canvas.itemconfigure(window_item_id, width=w)
    except tk.TclError:
        return


def canvas_set_scrollregion_from_bbox_all(canvas: tk.Canvas) -> None:
    """Apply ``scrollregion`` from ``bbox("all")`` only when the bbox is non-empty."""
    try:
        box = canvas.bbox("all")
    except tk.TclError:
        return
    if not box:
        return
    try:
        canvas.configure(scrollregion=box)
    except tk.TclError:
        return


def canvas_schedule_scrollregion_refresh(canvas: tk.Misc) -> None:
    """``after_idle`` scrollregion sync — safe to call after dynamic layout changes."""
    try:
        canvas.after_idle(lambda c=canvas: canvas_set_scrollregion_from_bbox_all(c))
    except tk.TclError:
        pass


def scroll_bottom_spacer(parent: tk.Misc, *, height: int | None = None) -> tk.Frame:
    """Trailing spacer so the last row clears the scrollbar / window edge when scrolled to end."""
    h = SCROLL_BOTTOM_PAD if height is None else height
    return tk.Frame(parent, bg=parent.cget("bg") if hasattr(parent, "cget") else BG, height=h)


def register_nested_scroll_canvas(canvas: tk.Canvas) -> None:
    """Mark a canvas as nested (playlist pane, dialog body, etc.) for mousewheel routing."""
    try:
        root_id = id(canvas.winfo_toplevel())
    except tk.TclError:
        return
    _nested_scroll_registry.setdefault(root_id, set()).add(id(canvas))


def nested_scroll_canvas_at_widget(widget: tk.Misc, *, exclude: tk.Canvas | None = None) -> tk.Canvas | None:
    """Return the nearest ancestor ``Canvas`` registered as nested, or None."""
    try:
        root_id = id(widget.winfo_toplevel())
    except tk.TclError:
        return None
    registered = _nested_scroll_registry.get(root_id)
    if not registered:
        return None
    w: tk.Misc | None = widget
    while w is not None:
        if isinstance(w, tk.Canvas) and id(w) in registered and w is not exclude:
            return w
        try:
            w = w.master
        except tk.TclError:
            break
    return None


def bind_canvas_mousewheel(
    host: tk.Misc,
    canvas: tk.Canvas,
    *,
    primary: tk.Canvas | None = None,
) -> None:
    """Scroll ``canvas`` on wheel; route to nested registered canvases when pointer is over them."""

    def _scroll_target(event: tk.Event) -> tk.Canvas:
        nested = nested_scroll_canvas_at_widget(event.widget, exclude=primary)
        return nested if nested is not None else canvas

    def _wheel_linux(event: tk.Event) -> str:
        target = _scroll_target(event)
        if event.num == 4:
            target.yview_scroll(-1, "units")
        elif event.num == 5:
            target.yview_scroll(1, "units")
        return "break"

    def _wheel_win(event: tk.Event) -> str:
        d = getattr(event, "delta", 0) or 0
        if d == 0:
            return "break"
        scaled = -d / 120.0
        n = int(round(scaled))
        if n == 0:
            n = 1 if scaled > 0 else -1
        _scroll_target(event).yview_scroll(n, "units")
        return "break"

    for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
        host.bind(seq, _wheel_linux if "Button" in seq else _wheel_win, add="+")
    canvas.bind("<Enter>", lambda _e: canvas.focus_set(), add="+")


def create_vertical_scroll_area(
    parent: tk.Misc,
    *,
    bg: str | None = None,
    pad_x: int = 0,
    pad_y: int = 0,
    bottom_pad: bool = True,
) -> tuple[tk.Canvas, tk.Frame, ttk.Scrollbar]:
    """Canvas + inner frame + themed scrollbar. Inner gets optional bottom spacer."""
    fill = bg if bg is not None else BG
    host = tk.Frame(parent, bg=fill)
    if pad_x or pad_y:
        host.pack(fill="both", expand=True, padx=pad_x, pady=pad_y)
    else:
        host.pack(fill="both", expand=True)
    canvas = tk.Canvas(host, bg=fill, highlightthickness=0)
    vsb = themed_vertical_scrollbar(host, command=canvas.yview)
    canvas.configure(yscrollcommand=vsb.set)
    vsb.pack(side="right", fill="y")
    canvas.pack(side="left", fill="both", expand=True)
    inner = tk.Frame(canvas, bg=fill)
    win_id = canvas.create_window((0, 0), window=inner, anchor="nw")

    def _on_inner_configure(_event: tk.Event | None = None) -> None:
        canvas_set_scrollregion_from_bbox_all(canvas)

    inner.bind("<Configure>", _on_inner_configure, add="+")
    canvas.bind(
        "<Configure>",
        lambda e, c=canvas, w=win_id: canvas_embed_set_width(c, w, e),
        add="+",
    )
    register_nested_scroll_canvas(canvas)
    bind_canvas_mousewheel(host, canvas, primary=canvas)
    if bottom_pad:
        scroll_bottom_spacer(inner).pack(fill="x")
    return canvas, inner, vsb


def _readonly_log_key(event: tk.Event) -> str | None:
    """Block typing/edits; allow Ctrl+A/C, navigation, and selection."""
    ks = event.keysym
    if ks in (
        "Shift_L", "Shift_R", "Control_L", "Control_R",
        "Alt_L", "Alt_R", "Meta_L", "Meta_R", "Caps_Lock", "Num_Lock",
    ):
        return
    if event.state & 0x0004:
        kl = ks.lower()
        if kl in ("a", "c"):
            return
        return "break"
    if ks in (
        "Left", "Right", "Up", "Down", "Home", "End",
        "Prior", "Next", "Tab",
    ):
        return
    if ks.startswith("KP_") and ks in (
        "KP_Left", "KP_Right", "KP_Up", "KP_Down",
        "KP_Prior", "KP_Next", "KP_Home", "KP_End",
    ):
        return
    return "break"


def _attach_readonly_log_text(w: tk.Text) -> None:
    """Read-only log/status Text: selectable and Ctrl+A/C work; no typing or paste."""
    w.configure(state="normal", cursor="arrow")
    w.bind("<Key>", _readonly_log_key)
    w.bind("<<Paste>>", lambda e: "break")
    w.bind("<Control-v>", lambda e: "break")
    w.bind("<Control-V>", lambda e: "break")
    w.bind("<Control-x>", lambda e: "break")
    w.bind("<Control-X>", lambda e: "break")
