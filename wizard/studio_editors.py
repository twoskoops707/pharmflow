"""Studio Steps / Builder / Teams pages — prior PharmFlow capability level."""

from __future__ import annotations

import copy
import json
import random
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, simpledialog
from typing import Any, Callable

from automation.apk_tools import find_aapt_exe, package_from_apk
from automation.config import SHUFFLE_NONE
from wizard.dabflow_studio import build_dabflow_blueprint_card
from wizard.site_interview import build_site_interview_card
from wizard.sequence_humanize import humanize_steps
from wizard.step_dialogs import (
    AddStepDialog,
    PerPhoneSequenceEditor,
    describe_step,
    normalize_step,
)
from wizard.wizard_paths import load_config, save_config, sequences_dir
from wizard.wizard_theme import (
    ACCENT,
    BG,
    BG2,
    BG3,
    BG4,
    FONT_BODY,
    FONT_CAPTION,
    FONT_MONO,
    FONT_PAGE_TITLE,
    FONT_SECTION,
    FS,
    GREEN,
    RED,
    SP,
    T1,
    T2,
    T3,
    WORKING,
    instruction_card,
    style_danger_button,
    style_primary_button,
    style_secondary_button,
    themed_vertical_scrollbar,
)

DEFAULT_HITS = 720
# Action-type shortcuts only — no URLs, packages, or coordinates baked into the wizard.
QUICK_ACTION_TYPES = (
    "wait",
    "tap",
    "swipe",
    "back",
    "open_url",
    "launch_app",
    "rotate_identity",
)


def _safe_hits_display(raw: Any, default: int = DEFAULT_HITS) -> int:
    try:
        return max(0, int(float(raw)))
    except (TypeError, ValueError):
        return default


def _btn(parent: tk.Misc, text: str, cmd: Callable[[], None], *, primary: bool = False, danger: bool = False, state: str = "normal") -> tk.Button:
    b = tk.Button(parent, text=text, command=cmd, font=("Segoe UI", 10, "bold"), padx=10, pady=5, state=state)
    if danger:
        style_danger_button(b)
    elif primary:
        style_primary_button(b)
    else:
        style_secondary_button(b)
    if state == "disabled":
        b.configure(bg=BG4, fg=T3, activebackground=BG4, cursor="arrow")
    return b


def _grey_tip(parent: tk.Misc, text: str) -> None:
    tk.Label(parent, text=text, font=FONT_CAPTION, bg=BG2, fg=WORKING, anchor="w", wraplength=640, justify="left").pack(
        fill="x", pady=(2, 6)
    )


# ─── Steps (default sequence editor) ─────────────────────────────────────────


def build_steps_page(app: Any, parent: tk.Misc) -> None:
    """Automation default sequence — real add/edit/reorder, not a dead picker."""
    app._default_steps = list(getattr(app, "_default_steps", []) or [])
    if not app._default_steps:
        cfg_steps = []
        try:
            cfg_steps = load_config().get("default_steps") or []
        except Exception:
            pass
        app._default_steps = [normalize_step(s) for s in cfg_steps if isinstance(s, dict)]

    tk.Label(parent, text="Steps", font=FONT_PAGE_TITLE, bg=BG, fg=T1, anchor="w").pack(fill="x")
    tk.Label(
        parent,
        text="User-authored template only — add steps here or Load file…. Nothing is pre-filled by the wizard.",
        font=FONT_BODY,
        bg=BG,
        fg=T2,
        anchor="w",
        wraplength=720,
        justify="left",
    ).pack(fill="x", pady=(4, SP["md"]))

    card = instruction_card(parent)
    card.pack(fill="both", expand=True)

    ctrl = tk.Frame(card, bg=BG2)
    ctrl.pack(fill="x", pady=(0, SP["sm"]))
    for text, cmd in (
        ("+ Add Step", lambda: _steps_add(app)),
        ("Edit", lambda: _steps_edit(app)),
        ("Remove", lambda: _steps_remove(app)),
        ("Up", lambda: _steps_move(app, -1)),
        ("Down", lambda: _steps_move(app, 1)),
        ("Load file…", lambda: _steps_load(app)),
        ("Save as…", lambda: _steps_save(app)),
        ("Natural timing", lambda: _steps_humanize(app)),
        ("Open folder", app._open_sequences_folder),
    ):
        _btn(ctrl, text, cmd).pack(side="left", padx=(0, 4))

    app._steps_count_lbl = tk.Label(card, text="", font=FONT_CAPTION, bg=BG2, fg=T3, anchor="w")
    app._steps_count_lbl.pack(fill="x", pady=(0, 4))

    wrap = tk.Frame(card, bg=BG2)
    wrap.pack(fill="both", expand=True)
    app._steps_lb = tk.Listbox(
        wrap, font=FONT_MONO, bg=BG3, fg=T1, relief="flat", activestyle="none", selectbackground=ACCENT, height=16
    )
    sb = themed_vertical_scrollbar(wrap, command=app._steps_lb.yview)
    app._steps_lb.configure(yscrollcommand=sb.set)
    app._steps_lb.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    app._steps_lb.bind("<Double-Button-1>", lambda _e: _steps_edit(app))
    _steps_refresh(app)


def _steps_refresh(app: Any) -> None:
    app._steps_lb.delete(0, tk.END)
    for i, step in enumerate(app._default_steps, 1):
        app._steps_lb.insert(tk.END, f"{i}. {describe_step(step)}")
    app._steps_count_lbl.configure(text=f"{len(app._default_steps)} step(s) in default template")


def _steps_add(app: Any) -> None:
    dlg = AddStepDialog(app)
    app.wait_window(dlg)
    if dlg.result:
        app._default_steps.append(normalize_step(dlg.result))
        _steps_persist(app)
        _steps_refresh(app)


def _steps_edit(app: Any) -> None:
    sel = app._steps_lb.curselection()
    if not sel:
        return
    idx = int(sel[0])
    dlg = AddStepDialog(app, initial=app._default_steps[idx])
    app.wait_window(dlg)
    if dlg.result:
        app._default_steps[idx] = normalize_step(dlg.result)
        _steps_persist(app)
        _steps_refresh(app)
        app._steps_lb.selection_set(idx)


def _steps_remove(app: Any) -> None:
    sel = app._steps_lb.curselection()
    if not sel:
        return
    del app._default_steps[int(sel[0])]
    _steps_persist(app)
    _steps_refresh(app)


def _steps_move(app: Any, delta: int) -> None:
    sel = app._steps_lb.curselection()
    if not sel:
        return
    i = int(sel[0])
    j = i + delta
    if j < 0 or j >= len(app._default_steps):
        return
    app._default_steps[i], app._default_steps[j] = app._default_steps[j], app._default_steps[i]
    _steps_persist(app)
    _steps_refresh(app)
    app._steps_lb.selection_set(j)


def _steps_load(app: Any) -> None:
    path = filedialog.askopenfilename(
        title="Load sequence",
        initialdir=str(sequences_dir()),
        filetypes=[("Sequence JSON", "*.json")],
    )
    if not path:
        return
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        messagebox.showerror("Load failed", str(exc), parent=app)
        return
    steps = data if isinstance(data, list) else data.get("steps")
    if not isinstance(steps, list):
        messagebox.showerror("Load failed", "No steps in file", parent=app)
        return
    app._default_steps = [normalize_step(s) for s in steps if isinstance(s, dict)]
    _steps_persist(app)
    _steps_refresh(app)
    app._log(f"Loaded {len(app._default_steps)} steps from {Path(path).name}", "ok")


def _steps_save(app: Any) -> None:
    path = filedialog.asksaveasfilename(
        title="Save sequence",
        initialdir=str(sequences_dir()),
        defaultextension=".json",
        filetypes=[("Sequence JSON", "*.json")],
    )
    if not path:
        return
    payload = {
        "name": Path(path).stem,
        "author_width": 900,
        "author_height": 1600,
        "steps": app._default_steps,
    }
    Path(path).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    app._log(f"Saved {Path(path).name}", "ok")


def _steps_persist(app: Any) -> None:
    try:
        save_config({"default_steps": app._default_steps})
    except Exception:
        pass


def _steps_humanize(app: Any) -> None:
    if not app._default_steps:
        app._log("No steps to humanize", "warn")
        return
    rng = random.Random()
    app._default_steps = humanize_steps(copy.deepcopy(app._default_steps), rng)
    _steps_persist(app)
    _steps_refresh(app)
    app._log("Natural timing applied to default template", "ok")


# ─── Builder ─────────────────────────────────────────────────────────────────


def build_builder_page(app: Any, parent: tk.Misc, *, is_arm: bool) -> None:
    """Website vs App gate + live step list with add/edit/quick tools."""
    app._builder_steps: list[dict[str, Any]] = list(getattr(app, "_builder_steps", []) or [])
    if not hasattr(app, "_builder_mode"):
        app._builder_mode = tk.StringVar(value="website")
    if not hasattr(app, "_humanize_on"):
        app._humanize_on = tk.BooleanVar(value=True)

    tk.Label(parent, text="Builder", font=FONT_PAGE_TITLE, bg=BG, fg=T1, anchor="w").pack(fill="x")
    tk.Label(
        parent,
        text=(
            "Virtual phone farm for any website or APK. Start with Site Interview "
            "(Q&A → humanized sequences), then optionally hand-author steps below. "
            "Legacy combinatorial catalogs for a prior campaign sit under Advanced."
        ),
        font=FONT_BODY,
        bg=BG,
        fg=T2,
        anchor="w",
    ).pack(fill="x", pady=(4, SP["md"]))

    build_site_interview_card(app, parent)

    gate = instruction_card(parent)
    gate.pack(fill="x", pady=(0, SP["sm"]))
    tk.Label(gate, text="Manual authoring (optional)", font=FONT_SECTION, bg=BG2, fg=T1, anchor="w").pack(fill="x")
    row = tk.Frame(gate, bg=BG2)
    row.pack(fill="x", pady=SP["sm"])
    _btn(row, "Website (URL)", lambda: _builder_pick(app, "website"), primary=True).pack(side="left", padx=(0, 8))
    _btn(row, "App (APK / package)", lambda: _builder_pick(app, "app")).pack(side="left")

    setup = instruction_card(parent)
    setup.pack(fill="x", pady=(0, SP["sm"]))
    app._builder_setup = setup

    app._builder_mode_host = tk.Frame(setup, bg=BG2)
    app._builder_mode_host.pack(fill="x")

    # Website fields
    app._builder_web = tk.Frame(app._builder_mode_host, bg=BG2)
    tk.Label(app._builder_web, text="Website URL", font=FONT_CAPTION, bg=BG2, fg=T3, anchor="w").pack(fill="x")
    app.builder_url = tk.Entry(app._builder_web, bg=BG3, fg=T1, relief="flat", insertbackground=T1)
    app.builder_url.pack(fill="x", pady=(2, 8), ipady=4)

    # App fields
    app._builder_app = tk.Frame(app._builder_mode_host, bg=BG2)
    tk.Label(app._builder_app, text="Package name", font=FONT_CAPTION, bg=BG2, fg=T3, anchor="w").pack(fill="x")
    pkg_row = tk.Frame(app._builder_app, bg=BG2)
    pkg_row.pack(fill="x", pady=(2, 4))
    app.builder_package = tk.Entry(pkg_row, bg=BG3, fg=T1, relief="flat", insertbackground=T1)
    app.builder_package.pack(side="left", fill="x", expand=True, ipady=4)
    aapt_ok = bool(find_aapt_exe())
    browse_state = "normal" if aapt_ok else "disabled"
    app._builder_apk_btn = _btn(pkg_row, "Browse APK…", lambda: _builder_browse_apk(app), state=browse_state)
    app._builder_apk_btn.pack(side="left", padx=(8, 0))
    tip_host = tk.Frame(app._builder_app, bg=BG2)
    tip_host.pack(fill="x")
    if is_arm and not aapt_ok:
        _grey_tip(tip_host, "aapt not found (common on ARM without full Android SDK). Enter the package name manually.")
    elif is_arm:
        _grey_tip(tip_host, "ARM: aapt may be slow under Prism — manual package entry is safest.")

    tk.Label(setup, text="Sequence name", font=FONT_CAPTION, bg=BG2, fg=T3, anchor="w").pack(fill="x")
    app.builder_name = tk.Entry(setup, bg=BG3, fg=T1, relief="flat", insertbackground=T1)
    app.builder_name.pack(fill="x", pady=(2, 8), ipady=4)

    # Seed / tools
    tools = instruction_card(parent)
    tools.pack(fill="x", pady=(0, SP["sm"]))
    tk.Label(tools, text="Author steps", font=FONT_SECTION, bg=BG2, fg=T1, anchor="w").pack(fill="x")
    tool_row = tk.Frame(tools, bg=BG2)
    tool_row.pack(fill="x", pady=SP["sm"])
    _btn(tool_row, "+ Add Step", lambda: _builder_add(app), primary=True).pack(side="left", padx=(0, 4))
    _btn(tool_row, "Edit", lambda: _builder_edit(app)).pack(side="left", padx=(0, 4))
    _btn(tool_row, "Remove", lambda: _builder_remove(app), danger=True).pack(side="left", padx=(0, 4))
    _btn(tool_row, "Up", lambda: _builder_move(app, -1)).pack(side="left", padx=(0, 4))
    _btn(tool_row, "Down", lambda: _builder_move(app, 1)).pack(side="left", padx=(0, 4))
    _btn(tool_row, "Add from gate", lambda: _builder_add_from_gate(app)).pack(side="left", padx=(0, 4))
    _btn(tool_row, "Load file…", lambda: _builder_load(app)).pack(side="left", padx=(0, 4))

    quick = tk.Frame(tools, bg=BG2)
    quick.pack(fill="x", pady=(0, SP["sm"]))
    tk.Label(quick, text="Add type:", font=FONT_CAPTION, bg=BG2, fg=T3).pack(side="left", padx=(0, 6))
    for action in QUICK_ACTION_TYPES:
        _btn(quick, action, lambda a=action: _builder_add_type(app, a)).pack(side="left", padx=2)

    wrap = tk.Frame(tools, bg=BG2)
    wrap.pack(fill="both", expand=True)
    app._builder_lb = tk.Listbox(
        wrap, font=FONT_MONO, bg=BG3, fg=T1, relief="flat", activestyle="none", selectbackground=ACCENT, height=12
    )
    bsb = themed_vertical_scrollbar(wrap, command=app._builder_lb.yview)
    app._builder_lb.configure(yscrollcommand=bsb.set)
    app._builder_lb.pack(side="left", fill="both", expand=True)
    bsb.pack(side="right", fill="y")
    app._builder_lb.bind("<Double-Button-1>", lambda _e: _builder_edit(app))

    foot = tk.Frame(parent, bg=BG)
    foot.pack(fill="x", pady=SP["md"])
    tk.Checkbutton(
        foot,
        text="Humanize timing metadata on save",
        variable=app._humanize_on,
        bg=BG,
        fg=T1,
        selectcolor=BG,
        activebackground=BG,
        font=FONT_CAPTION,
    ).pack(side="left")
    _btn(foot, "Save sequence", lambda: _builder_save(app), primary=True).pack(side="right")

    # Optional legacy combinatorial catalog (one past campaign) — not the product identity
    legacy = instruction_card(parent)
    legacy.pack(fill="x", pady=(0, SP["sm"]))
    tk.Label(
        legacy,
        text="Advanced — optional legacy combinatorial catalog",
        font=FONT_SECTION,
        bg=BG2,
        fg=T1,
        anchor="w",
    ).pack(fill="x")
    tk.Label(
        legacy,
        text=(
            "Only if you still have an old large catalog for a previous site campaign. "
            "New farms should use Site Interview above — the EXE is not tied to any one website."
        ),
        font=FONT_CAPTION,
        bg=BG2,
        fg=T3,
        anchor="w",
        wraplength=820,
        justify="left",
    ).pack(fill="x", pady=(2, 6))
    build_dabflow_blueprint_card(app, legacy)

    # Classic-only tools — always greyed on ARM so users don't break the farm
    adv = instruction_card(parent)
    adv.pack(fill="x", pady=(0, SP["sm"]))
    tk.Label(adv, text="Advanced (classic MuMu x64 only)", font=FONT_SECTION, bg=BG2, fg=T1, anchor="w").pack(fill="x")
    adv_row = tk.Frame(adv, bg=BG2)
    adv_row.pack(fill="x", pady=SP["sm"])
    _btn(
        adv_row,
        "Desktop recorder (not in build)",
        lambda: app._log("WebView recorder is not in this build — use Add Step", "warn"),
        state="disabled",
    ).pack(side="left", padx=(0, 6))
    classic_state = "disabled" if is_arm else "normal"
    _btn(
        adv_row,
        "Classic MuMu create API",
        lambda: _builder_classic_create(app),
        state=classic_state,
    ).pack(side="left", padx=(0, 6))
    if is_arm:
        _grey_tip(
            adv,
            "MuMu ARM: classic Manager create/launch CLI and the full desktop recorder are greyed out. "
            "Author steps here; manage VMs in MuMu Player ARM.",
        )

    _builder_pick(app, app._builder_mode.get())
    _builder_refresh(app)


def _builder_pick(app: Any, mode: str) -> None:
    app._builder_mode.set(mode)
    app._builder_web.pack_forget()
    app._builder_app.pack_forget()
    # Keep name entry last: pack mode frame into the mode host only.
    if mode == "app":
        app._builder_app.pack(fill="x", in_=app._builder_mode_host)
    else:
        app._builder_web.pack(fill="x", in_=app._builder_mode_host)


def _builder_classic_create(app: Any) -> None:
    name = simpledialog.askstring("Create MuMu phone", "Instance name:", parent=app)
    if not name or not name.strip():
        return
    name = name.strip()
    farm = getattr(app, "farm", None)
    if farm is None:
        app._log("Phone farm not initialized — open Phones step first", "warn")
        return
    try:
        farm.create_phone(name)
        app._log(f"Created {name} via MuMu create API", "ok")
    except Exception as exc:
        app._log(f"MuMu create failed: {exc}", "warn")


def _builder_browse_apk(app: Any) -> None:
    path = filedialog.askopenfilename(title="Select APK", filetypes=[("Android APK", "*.apk")])
    if not path:
        return
    pkg = package_from_apk(path)
    if pkg:
        app.builder_package.delete(0, "end")
        app.builder_package.insert(0, pkg)
        app._log(f"Package from APK: {pkg}", "ok")
    else:
        app._log("Could not detect package — enter manually", "warn")


def _builder_add_from_gate(app: Any) -> None:
    """Append only the gate action the user typed — no rotate/wait template."""
    mode = app._builder_mode.get()
    if mode == "app":
        package = app.builder_package.get().strip()
        if not package:
            app._log("Enter package first", "warn")
            return
        step = {"action": "launch_app", "params": {"package": package}}
    else:
        url = app.builder_url.get().strip()
        if not url:
            app._log("Enter URL first", "warn")
            return
        step = {"action": "open_url", "params": {"url": url}}
    app._builder_steps.append(normalize_step(step))
    _builder_refresh(app)
    app._log("Added gate step", "ok")


def _builder_load(app: Any) -> None:
    path = filedialog.askopenfilename(
        title="Load sequence into builder",
        initialdir=str(sequences_dir()),
        filetypes=[("Sequence JSON", "*.json")],
    )
    if not path:
        return
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        messagebox.showerror("Load failed", str(exc), parent=app)
        return
    steps = data if isinstance(data, list) else data.get("steps")
    if not isinstance(steps, list):
        messagebox.showerror("Load failed", "No steps in file", parent=app)
        return
    app._builder_steps = [normalize_step(s) for s in steps if isinstance(s, dict)]
    if isinstance(data, dict) and data.get("name") and not app.builder_name.get().strip():
        app.builder_name.insert(0, str(data["name"]))
    _builder_refresh(app)
    app._log(f"Loaded {len(app._builder_steps)} steps from {Path(path).name}", "ok")


def _builder_refresh(app: Any) -> None:
    app._builder_lb.delete(0, tk.END)
    for i, step in enumerate(app._builder_steps, 1):
        app._builder_lb.insert(tk.END, f"{i}. {describe_step(step)}")


def _builder_add(app: Any) -> None:
    dlg = AddStepDialog(app)
    app.wait_window(dlg)
    if dlg.result:
        app._builder_steps.append(normalize_step(dlg.result))
        _builder_refresh(app)


def _builder_edit(app: Any) -> None:
    sel = app._builder_lb.curselection()
    if not sel:
        return
    idx = int(sel[0])
    dlg = AddStepDialog(app, initial=app._builder_steps[idx])
    app.wait_window(dlg)
    if dlg.result:
        app._builder_steps[idx] = normalize_step(dlg.result)
        _builder_refresh(app)
        app._builder_lb.selection_set(idx)


def _builder_remove(app: Any) -> None:
    sel = app._builder_lb.curselection()
    if not sel:
        return
    del app._builder_steps[int(sel[0])]
    _builder_refresh(app)


def _builder_move(app: Any, delta: int) -> None:
    sel = app._builder_lb.curselection()
    if not sel:
        return
    i = int(sel[0])
    j = i + delta
    if j < 0 or j >= len(app._builder_steps):
        return
    app._builder_steps[i], app._builder_steps[j] = app._builder_steps[j], app._builder_steps[i]
    _builder_refresh(app)
    app._builder_lb.selection_set(j)


def _builder_add_type(app: Any, action: str) -> None:
    """Open Add Step dialog for a type — fields start empty (no hardcoded params)."""
    dlg = AddStepDialog(app, initial={"action": action, "params": {}})
    app.wait_window(dlg)
    if dlg.result:
        app._builder_steps.append(normalize_step(dlg.result))
        _builder_refresh(app)


def _builder_save(app: Any) -> None:
    name = app.builder_name.get().strip()
    if not name:
        app._log("Sequence name required", "warn")
        return
    if not app._builder_steps:
        app._log("Add at least one step (Add Step, Add from gate, or Load file)", "warn")
        return
    payload: dict[str, Any] = {
        "name": name,
        "author_width": 900,
        "author_height": 1600,
        "steps": app._builder_steps,
    }
    if app._humanize_on.get():
        # Runner HumanizeConfig has no "enabled" flag — set real variation knobs.
        payload["humanize"] = {
            "timing_variation": 0.15,
            "coordinate_tolerance": 10,
            "random_actions": True,
        }
    else:
        payload["humanize"] = {
            "timing_variation": 0.0,
            "coordinate_tolerance": 0,
            "random_actions": False,
        }
    dest = sequences_dir() / f"{name}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    app._log(f"Saved sequence: {dest.name} ({len(app._builder_steps)} steps)", "ok")
    app.show_step("steps")


# ─── Teams (checkbox per phone) ──────────────────────────────────────────────


def build_teams_page(app: Any, parent: tk.Misc) -> None:
    """Groups with checkbox per live phone — no typing VM names."""
    tk.Label(parent, text="Teams", font=FONT_PAGE_TITLE, bg=BG, fg=T1, anchor="w").pack(fill="x")
    tk.Label(
        parent,
        text="Check phones into a group. Edit each phone’s steps/playlist. Exclusive membership (one group at a time).",
        font=FONT_BODY,
        bg=BG,
        fg=T2,
        anchor="w",
        wraplength=720,
        justify="left",
    ).pack(fill="x", pady=(4, SP["md"]))

    ctrl = tk.Frame(parent, bg=BG)
    ctrl.pack(fill="x", pady=(0, SP["sm"]))
    _btn(ctrl, "+ Add Group", lambda: _teams_add_group(app), primary=True).pack(side="left", padx=(0, 6))
    _btn(ctrl, "Natural timing — all phones", lambda: _teams_humanize(app)).pack(side="left", padx=(0, 6))
    _btn(ctrl, "Refresh", lambda: _teams_rebuild(app)).pack(side="left")
    app._teams_host = tk.Frame(parent, bg=BG)
    app._teams_host.pack(fill="both", expand=True)
    _teams_rebuild(app)


def _teams_rebuild(app: Any) -> None:
    for w in app._teams_host.winfo_children():
        w.destroy()
    live = list(app.farm.list_instances())
    groups = app.groups.list_groups()
    if not groups:
        tk.Label(app._teams_host, text="No teams yet — click + Add Group", font=FONT_BODY, bg=BG, fg=T3).pack(pady=20)
        return
    for g in groups:
        _teams_build_card(app, g, live)


def _teams_build_card(app: Any, g: dict[str, Any], live: list[Any]) -> None:
    name = g["name"]
    card = instruction_card(app._teams_host)
    card.pack(fill="x", pady=(0, SP["md"]))

    hdr = tk.Frame(card, bg=BG2)
    hdr.pack(fill="x")
    tk.Label(hdr, text=name, font=FONT_SECTION, bg=BG2, fg=T1, anchor="w").pack(side="left")
    rep = "forever" if g.get("repeat_forever") else str(g.get("repeat", 1))
    tk.Label(hdr, text=f"repeat {rep}", font=FONT_CAPTION, bg=BG2, fg=T3).pack(side="left", padx=12)
    _btn(hdr, "Run group", lambda n=name: app._run_group(n), primary=True).pack(side="right", padx=(4, 0))
    if len(app.groups.list_groups()) > 1:
        _btn(hdr, "Remove group", lambda n=name: _teams_remove_group(app, n), danger=True).pack(side="right")

    # Repeat / forever / stagger
    timing = tk.Frame(card, bg=BG2)
    timing.pack(fill="x", pady=(SP["sm"], SP["sm"]))
    tk.Label(timing, text="Repeat", font=FONT_CAPTION, bg=BG2, fg=T3).pack(side="left")
    rep_var = tk.StringVar(value=str(g.get("repeat", 1)))
    tk.Entry(timing, textvariable=rep_var, width=5, bg=BG3, fg=T1, relief="flat", insertbackground=T1).pack(side="left", padx=6)
    forever_var = tk.BooleanVar(value=bool(g.get("repeat_forever")))
    tk.Checkbutton(timing, text="Forever", variable=forever_var, bg=BG2, fg=T1, selectcolor=BG, activebackground=BG2, font=FONT_CAPTION).pack(
        side="left", padx=8
    )
    tk.Label(timing, text="Stagger secs", font=FONT_CAPTION, bg=BG2, fg=T3).pack(side="left")
    stagger_var = tk.StringVar(value=str(g.get("stagger_seconds", 0)))
    tk.Entry(timing, textvariable=stagger_var, width=5, bg=BG3, fg=T1, relief="flat", insertbackground=T1).pack(side="left", padx=6)

    def save_timing(_n=name, rv=rep_var, fv=forever_var, sv=stagger_var) -> None:
        try:
            repeat = max(1, int(rv.get() or "1"))
        except ValueError:
            repeat = 1
        try:
            stagger = max(0.0, float(sv.get() or "0"))
        except ValueError:
            stagger = 0.0
        app.groups.update_group(_n, repeat=repeat, repeat_forever=fv.get(), stagger_seconds=stagger)

    _btn(timing, "Save timing", save_timing).pack(side="left", padx=8)

    members = set(g.get("phones") or [])
    group_obj = app.groups.get_group(name)
    phone_entries = (group_obj.phone_entries if group_obj else {}) or {}

    if not live:
        tk.Label(card, text="No phones detected — boot VMs in MuMu Manager", font=FONT_BODY, bg=BG2, fg=RED).pack(anchor="w")
        return

    for inst in live:
        phone = inst.name
        row = tk.Frame(card, bg=BG3, padx=8, pady=5)
        row.pack(fill="x", pady=2)
        tk.Label(row, text=phone, font=FONT_MONO, bg=BG3, fg=T1, width=18, anchor="w").pack(side="left")
        ent = phone_entries.get(phone) if phone in members else None
        n_steps = len(ent.get("steps") or []) if isinstance(ent, dict) else 0
        n_pl = len(ent.get("sequence_playlist") or []) if isinstance(ent, dict) else 0
        src = "in group" if phone in members else "—"
        detail = f"{n_steps} steps · {n_pl} files · {src}" if phone in members else "not in group"
        tk.Label(row, text=detail, font=FONT_CAPTION, bg=BG3, fg=GREEN if phone in members else T3, width=28, anchor="w").pack(
            side="left", padx=6
        )

        hits_var = tk.StringVar(
            value=str(_safe_hits_display((ent or {}).get("hits_per_day"), DEFAULT_HITS))
            if phone in members
            else str(DEFAULT_HITS)
        )
        tk.Label(row, text="hits/day", font=FONT_CAPTION, bg=BG3, fg=T3).pack(side="left")
        tk.Entry(row, textvariable=hits_var, width=5, bg=BG2, fg=T1, relief="flat", insertbackground=T1).pack(side="left", padx=4)

        var = tk.BooleanVar(value=phone in members)

        def toggle(v=var, ph=phone, gn=name, hv=hits_var) -> None:
            _teams_toggle(app, gn, ph, v.get(), hv)

        def edit(ph=phone, gn=name) -> None:
            _teams_edit_phone(app, gn, ph)

        ed = _btn(row, "Edit", edit)
        ed.pack(side="left", padx=4)
        if phone not in members:
            ed.configure(state="disabled", bg=BG4, fg=T3, cursor="arrow")

        def remove_out(ph=phone, gn=name) -> None:
            var.set(False)
            _teams_toggle(app, gn, ph, False, hits_var)

        ou = _btn(row, "Out", remove_out)
        ou.pack(side="right", padx=(4, 0))
        if phone not in members:
            ou.configure(state="disabled", bg=BG4, fg=T3, cursor="arrow")

        tk.Checkbutton(
            row,
            text="",
            variable=var,
            command=toggle,
            bg=BG3,
            fg=T1,
            selectcolor=GREEN,
            activebackground=BG3,
        ).pack(side="right")

    # Clone first checked phone → all members (prior "Copy from Phone 1")
    members_list = [p for p in (g.get("phones") or []) if p]
    if len(members_list) > 1:
        clone_row = tk.Frame(card, bg=BG2)
        clone_row.pack(fill="x", pady=(8, 0))
        master = members_list[0]
        _btn(
            clone_row,
            f"Copy steps from {master} → all in group",
            lambda gn=name, m=master: _teams_clone_master(app, gn, m),
        ).pack(side="left")


def _teams_toggle(app: Any, group_name: str, phone: str, checked: bool, hits_var: tk.StringVar) -> None:
    # Exclusive membership across groups
    for g in app.groups.list_groups():
        if g["name"] == group_name:
            continue
        if phone in (g.get("phones") or []):
            others = [p for p in g["phones"] if p != phone]
            app.groups.update_group(g["name"], phones=others)
    group = app.groups.get_group(group_name)
    if not group:
        return
    phones = list(group.phones)
    if checked:
        if phone not in phones:
            phones.append(phone)
        app.groups.update_group(group_name, phones=phones)
        ent = group.ensure_phone_entry(phone)
        try:
            ent["hits_per_day"] = max(0, int(hits_var.get() or DEFAULT_HITS))
        except ValueError:
            ent["hits_per_day"] = DEFAULT_HITS
        # Only copy user template if they authored one — never invent steps.
        template = list(getattr(app, "_default_steps", []) or [])
        if not ent.get("steps") and template:
            ent["steps"] = copy.deepcopy(template)
            ent["use_default_template"] = True
        elif not ent.get("steps"):
            ent["steps"] = []
            ent["use_default_template"] = False
        app.groups.save()
    else:
        phones = [p for p in phones if p != phone]
        app.groups.update_group(group_name, phones=phones)
    _teams_rebuild(app)


def _teams_edit_phone(app: Any, group_name: str, phone: str) -> None:
    group = app.groups.get_group(group_name)
    if not group:
        return
    if phone not in group.phones:
        app._log(f"Check {phone} into the group first", "warn")
        return
    ent = group.ensure_phone_entry(phone)

    def on_save(updated: dict[str, Any]) -> None:
        group.phone_entries[phone] = updated
        app.groups.save()
        app._log(f"Saved {len(updated.get('steps') or [])} step(s) for {phone}", "ok")
        _teams_rebuild(app)

    wm_size: tuple[int, int] | None = None
    if hasattr(app, "farm") and app.farm:
        try:
            wm_size = app.farm.get_runtime_resolution(phone)
        except (KeyError, OSError, RuntimeError):
            wm_size = None
    dlg = PerPhoneSequenceEditor(
        app, phone, ent, on_save=on_save, show_playlist=True, phone_wm_size=wm_size,
    )
    app.wait_window(dlg)


def _teams_add_group(app: Any) -> None:
    # Simple name dialog
    dlg = tk.Toplevel(app)
    dlg.title("New group")
    dlg.configure(bg=BG)
    dlg.geometry("360x140")
    dlg.transient(app)
    dlg.grab_set()
    tk.Label(dlg, text="Group name", font=FS, bg=BG, fg=T1).pack(anchor="w", padx=16, pady=(16, 4))
    var = tk.StringVar(value=f"Group {len(app.groups.list_groups()) + 1}")
    tk.Entry(dlg, textvariable=var, bg=BG3, fg=T1, relief="flat", insertbackground=T1).pack(fill="x", padx=16, ipady=4)

    def ok() -> None:
        name = var.get().strip()
        if not name:
            return
        if app.groups.get_group(name):
            messagebox.showwarning("Exists", "Group already exists", parent=dlg)
            return
        live = [i.name for i in app.farm.list_instances()]
        # Exclusive: clear these phones from other groups first
        for other in app.groups.list_groups():
            remaining = [p for p in (other.get("phones") or []) if p not in live]
            if remaining != list(other.get("phones") or []):
                app.groups.update_group(other["name"], phones=remaining)
        app.groups.create_group(name, live)  # start with all phones checked
        for ph in live:
            ent = app.groups.phone_entry(name, ph)
            template = list(getattr(app, "_default_steps", []) or [])
            if template:
                ent["steps"] = copy.deepcopy(template)
                ent["use_default_template"] = True
            else:
                ent["steps"] = []
                ent["use_default_template"] = False
            ent["hits_per_day"] = DEFAULT_HITS
        app.groups.save()
        dlg.destroy()
        _teams_rebuild(app)

    _btn(dlg, "Create", ok, primary=True).pack(pady=12)
    app.wait_window(dlg)


def _teams_remove_group(app: Any, name: str) -> None:
    if not messagebox.askyesno("Remove group", f"Delete group {name}?", parent=app):
        return
    app.groups.delete_group(name)
    _teams_rebuild(app)


def _teams_clone_master(app: Any, group_name: str, master: str) -> None:
    group = app.groups.get_group(group_name)
    if not group:
        return
    src = group.ensure_phone_entry(master)
    src_steps = copy.deepcopy(src.get("steps") or [])
    src_pl = copy.deepcopy(src.get("sequence_playlist") or [])
    src_pl_b = copy.deepcopy(src.get("sequence_playlist_secondary") or [])
    src_mode = src.get("sequence_playlist_mode")
    src_shuffle = src.get("sequence_playlist_shuffle")
    for phone in list(group.phones):
        if phone == master:
            continue
        ent = group.ensure_phone_entry(phone)
        ent["steps"] = copy.deepcopy(src_steps)
        ent["sequence_playlist"] = copy.deepcopy(src_pl)
        ent["sequence_playlist_secondary"] = copy.deepcopy(src_pl_b)
        ent["sequence_playlist_mode"] = src_mode or "ordered"
        ent["sequence_playlist_shuffle"] = src_shuffle or SHUFFLE_NONE
        if "sequence_base_w" in src:
            ent["sequence_base_w"] = src.get("sequence_base_w")
        if "sequence_base_h" in src:
            ent["sequence_base_h"] = src.get("sequence_base_h")
        if "hits_per_day" in src:
            ent["hits_per_day"] = src.get("hits_per_day")
        ent["use_default_template"] = False
        ent["explicit_override"] = True
    app.groups.save()
    app._log(f"Copied {master} steps to {len(group.phones) - 1} phone(s) in {group_name}", "ok")
    _teams_rebuild(app)


def _teams_humanize(app: Any) -> None:
    changed = 0
    for g in app.groups.list_groups():
        group = app.groups.get_group(g["name"])
        if not group:
            continue
        for phone in group.phones:
            ent = group.ensure_phone_entry(phone)
            steps = ent.get("steps") or []
            if not steps:
                continue
            rng = random.Random(hash(phone) & 0xFFFFFFFF)
            ent["steps"] = humanize_steps(copy.deepcopy(steps), rng)
            ent["use_default_template"] = False
            changed += 1
        app.groups.save()
    app._log(f"Humanized timing on {changed} phone sequence(s)", "ok")
    _teams_rebuild(app)
