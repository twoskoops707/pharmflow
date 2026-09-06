"""Step add dialog + full per-phone sequence editor (prior CPharm parity)."""

from __future__ import annotations

import copy
import json
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Callable

from automation.config import (
    AUTHOR_HEIGHT,
    AUTHOR_WIDTH,
    SHUFFLE_BOTH_SEPARATELY,
    SHUFFLE_COMBINED,
    SHUFFLE_NONE,
    SHUFFLE_SET_A,
    SHUFFLE_SET_B,
)
from automation.sequence_paths import discover_sequence_files
from wizard.wizard_paths import sequences_dir
from wizard.wizard_theme import (
    ACCENT,
    BG,
    BG2,
    BG3,
    BG4,
    FONT_CAPTION,
    FONT_SECTION,
    FS,
    GREEN,
    ON_ACCENT,
    RED,
    SP,
    T1,
    T2,
    T3,
    instruction_card,
    style_danger_button,
    style_primary_button,
    style_secondary_button,
    themed_vertical_scrollbar,
)

STEP_LABELS: dict[str, str] = {
    "open_url": "Open a website in the phone browser",
    "launch_app": "Open an installed app (Android package name)",
    "tap": "Tap the screen at a spot",
    "wait": "Wait N seconds",
    "swipe": "Swipe across the screen",
    "keyevent": "Press Back / Home / Enter",
    "key": "Press a keycode",
    "back": "Press Back",
    "close_app": "Force-stop an app",
    "clear_cookies": "Clear Chromium history, cookies, and site data",
    "rotate_identity": "Scramble browser session + rotate Tor (if enabled)",
    "ensure_fingerprint": "Verify browser headers before browse",
    "shell": "Run an adb shell command",
}


def step_action(step: dict[str, Any]) -> str:
    return str(step.get("action") or step.get("type") or "").strip()


def describe_step(step: dict[str, Any]) -> str:
    """One-line description for listboxes."""
    if not isinstance(step, dict):
        return str(step)
    action = step_action(step)
    params = step.get("params") if isinstance(step.get("params"), dict) else {}
    flat = {**{k: v for k, v in step.items() if k not in ("action", "type", "params", "description")}, **params}
    if action == "open_url":
        return f"open_url  {flat.get('url', '')}"
    if action == "launch_app":
        return f"launch_app  {flat.get('package', '')}"
    if action == "tap":
        return f"tap  ({flat.get('x', '?')}, {flat.get('y', '?')})"
    if action == "wait":
        return f"wait  {flat.get('seconds', '?')}s"
    if action == "swipe":
        return (
            f"swipe  ({flat.get('x1', flat.get('x_start', '?'))},{flat.get('y1', flat.get('y_start', '?'))})"
            f" → ({flat.get('x2', flat.get('x_end', '?'))},{flat.get('y2', flat.get('y_end', '?'))})"
        )
    if action in ("keyevent", "key"):
        return f"{action}  {flat.get('key', flat.get('code', flat.get('keycode', '')))}"
    if action == "shell":
        return f"shell  {flat.get('command', flat.get('cmd', ''))}"
    if action in ("close_app", "clear_cookies"):
        return f"{action}  {flat.get('package', '')}"
    desc = step.get("description") or ""
    return f"{action}  {desc}".strip()


def _safe_hits_per_day(raw: Any, default: int = 0) -> int:
    """Parse hits_per_day without crashing the editor on bad/float strings."""
    try:
        return max(0, int(float(raw)))
    except (TypeError, ValueError):
        return default


def normalize_step(step: dict[str, Any]) -> dict[str, Any]:
    """Normalize prior flat `type` steps into FamFlow `{action, params}`."""
    if not isinstance(step, dict):
        return {"action": "wait", "params": {"seconds": 1}}
    out = dict(step)
    action = step_action(out)
    if "action" not in out and "type" in out:
        out["action"] = out.pop("type")
        action = str(out["action"])
    if "params" not in out or not isinstance(out.get("params"), dict):
        params: dict[str, Any] = {}
        for key, val in list(out.items()):
            if key in ("action", "type", "description", "params"):
                continue
            params[key] = val
            out.pop(key, None)
        out["params"] = params
    out["action"] = action
    return out


def _store_name(path: Path) -> str:
    try:
        return path.resolve().relative_to(sequences_dir().resolve()).as_posix()
    except ValueError:
        return str(path.resolve())


class AddStepDialog(tk.Toplevel):
    """Type-driven Add Step dialog (prior CPharm parity)."""

    def __init__(self, parent: tk.Misc, *, initial: dict[str, Any] | None = None) -> None:
        super().__init__(parent)
        self.result: dict[str, Any] | None = None
        self.title("Add / Edit Step")
        self.configure(bg=BG)
        self.geometry("620x560")
        self.minsize(520, 460)
        self.transient(parent)
        self.grab_set()

        shell = tk.Frame(self, bg=BG)
        shell.pack(fill="both", expand=True, padx=SP["page"], pady=SP["page"])
        tk.Label(shell, text="What should the phone do?", font=("Segoe UI", 13, "bold"), bg=BG, fg=T1).pack(
            anchor="w", pady=(0, SP["md"])
        )

        type_frame = instruction_card(shell)
        type_frame.pack(fill="x", pady=(0, SP["md"]))
        tk.Label(type_frame, text="Action:", font=FS, bg=BG2, fg=T2, width=10, anchor="w").pack(side="left")
        init_action = step_action(initial) if initial else "open_url"
        if init_action not in STEP_LABELS:
            init_action = "open_url"
        self._type = tk.StringVar(value=init_action)
        combo = ttk.Combobox(
            type_frame,
            textvariable=self._type,
            values=list(STEP_LABELS.keys()),
            state="readonly",
            font=FS,
            width=28,
        )
        combo.pack(side="left")
        combo.bind("<<ComboboxSelected>>", lambda _e: self._update())

        self._desc = tk.Label(shell, text="", font=FS, bg=BG, fg=T2, wraplength=520, justify="left", anchor="w")
        self._desc.pack(fill="x", pady=(0, SP["sm"]))
        self._fields_frame = instruction_card(shell)
        self._fields_frame.pack(fill="both", expand=True, pady=(0, SP["md"]))
        self._fields: dict[str, tk.StringVar] = {}
        self._seed = normalize_step(initial) if initial else None
        self._update()

        btn_row = tk.Frame(shell, bg=BG)
        btn_row.pack(fill="x")
        ok = tk.Button(btn_row, text="OK", font=("Segoe UI", 11, "bold"), command=self._ok, padx=16, pady=6)
        style_primary_button(ok)
        ok.configure(bg=GREEN, activebackground=GREEN)
        ok.pack(side="left", padx=(0, 8))
        cancel = tk.Button(btn_row, text="Cancel", font=FS, command=self.destroy, padx=12, pady=6)
        style_secondary_button(cancel)
        cancel.pack(side="left")

    def _seed_val(self, key: str, default: Any = "") -> str:
        if not self._seed:
            return str(default)
        params = self._seed.get("params") or {}
        if key in params:
            return str(params[key])
        return str(self._seed.get(key, default))

    def _update(self) -> None:
        for w in self._fields_frame.winfo_children():
            w.destroy()
        self._fields.clear()
        t = self._type.get()
        self._desc.configure(text=STEP_LABELS.get(t, ""))

        def field(label: str, key: str, default: Any = "", width: int = 32) -> None:
            row = tk.Frame(self._fields_frame, bg=BG2)
            row.pack(fill="x", pady=3)
            tk.Label(row, text=label, font=FS, bg=BG2, fg=T2, width=18, anchor="w").pack(side="left")
            var = tk.StringVar(value=self._seed_val(key, default))
            tk.Entry(row, textvariable=var, font=("Consolas", 10), bg=BG, fg=T1, insertbackground=T1, relief="flat", width=width).pack(
                side="left", ipady=3
            )
            self._fields[key] = var

        def tip(text: str) -> None:
            tk.Label(self._fields_frame, text=text, font=FONT_CAPTION, bg=BG2, fg=T3, justify="left", wraplength=480, anchor="w").pack(
                fill="x", pady=1
            )

        if t == "open_url":
            field("Website URL:", "url", "", 36)
            field("After-open wait (sec):", "post_wait_secs", "", 8)
            tip("Enter the full URL yourself — nothing is pre-filled.")
        elif t == "launch_app":
            field("Package name:", "package", "", 36)
            field("After-open wait (sec):", "post_wait_secs", "", 8)
            tip("Enter the Android package (e.g. from Browse APK). Install the app first.")
        elif t == "tap":
            field("X:", "x", "")
            field("Y:", "y", "")
            field("Duration ms:", "duration_ms", "")
        elif t == "wait":
            field("Seconds:", "seconds", "")
        elif t == "swipe":
            field("Start X:", "x1", "")
            field("Start Y:", "y1", "")
            field("End X:", "x2", "")
            field("End Y:", "y2", "")
            field("Duration ms:", "duration_ms", "")
        elif t in ("keyevent", "key"):
            field("Key / code:", "key", "")
            tip("BACK, HOME, ENTER — or numeric keycode")
        elif t == "back":
            tip("Sends Android BACK keyevent.")
        elif t in ("close_app", "clear_cookies"):
            field("Package:", "package", "")
            tip("Leave blank to use the runtime default browser package at play time.")
        elif t == "shell":
            field("Command:", "command", "", 40)
        elif t == "rotate_identity":
            tip("Scrambles browser UA + android_id; rotates Tor when browse mode uses Tor.")
        elif t == "ensure_fingerprint":
            tip("Verify retail props before browse.")

    def _ok(self) -> None:
        t = self._type.get()
        params: dict[str, Any] = {}
        for key, var in self._fields.items():
            v = var.get().strip()
            if v == "":
                continue
            if key in ("seconds", "post_wait_secs", "duration_ms") or key.startswith(("x", "y")):
                try:
                    params[key] = float(v) if "." in v else int(v)
                    continue
                except ValueError:
                    pass
            params[key] = v
        # FamFlow runner prefers keycode int for keyevent
        if t in ("keyevent", "key") and "key" in params:
            key = str(params.pop("key")).upper()
            mapping = {"BACK": 4, "HOME": 3, "ENTER": 66, "APP_SWITCH": 187}
            params["code"] = mapping.get(key, key if str(key).isdigit() else 4)
            if isinstance(params["code"], str) and params["code"].isdigit():
                params["code"] = int(params["code"])
        self.result = {"action": t, "params": params}
        self.destroy()


class PerPhoneSequenceEditor(tk.Toplevel):
    """Full per-phone editor: steps list + playlist file/folder (prior parity)."""

    def __init__(
        self,
        parent: tk.Misc,
        phone_name: str,
        phone_ent: dict[str, Any],
        *,
        on_save: Callable[[dict[str, Any]], None] | None = None,
        show_playlist: bool = True,
        phone_wm_size: tuple[int, int] | None = None,
    ) -> None:
        super().__init__(parent)
        self._ent = phone_ent
        self._on_save = on_save
        self._phone_name = phone_name
        self.title(f"Sequence — {phone_name}")
        self.configure(bg=BG)
        self.geometry("980x820")
        self.minsize(780, 640)
        self.transient(parent)
        self.grab_set()

        raw_steps = phone_ent.get("steps") if isinstance(phone_ent.get("steps"), list) else []
        self._draft: list[dict[str, Any]] = [normalize_step(s) for s in raw_steps if isinstance(s, dict)]
        self._playlist = [str(x).strip() for x in (phone_ent.get("sequence_playlist") or []) if str(x).strip()]
        self._playlist_b = [
            str(x).strip() for x in (phone_ent.get("sequence_playlist_secondary") or []) if str(x).strip()
        ]
        self._mode = tk.StringVar(value=str(phone_ent.get("sequence_playlist_mode") or "ordered"))
        self._shuffle = tk.StringVar(value=str(phone_ent.get("sequence_playlist_shuffle") or SHUFFLE_NONE))
        self._use_set_b = tk.BooleanVar(value=bool(self._playlist_b))
        self._hits = tk.StringVar(value=str(_safe_hits_per_day(phone_ent.get("hits_per_day"), 0)))
        self._dirty = False
        self._show_playlist = show_playlist
        self._phone_wm_size = phone_wm_size

        # Footer pinned to bottom so Save is always visible (playlist section was pushing it off-screen).
        foot = tk.Frame(self, bg=BG, highlightthickness=1, highlightbackground=BG4)
        foot.pack(side="bottom", fill="x", padx=SP["page"], pady=(0, SP["page"]))
        tk.Label(
            foot,
            text="Save writes steps + playlist to this phone in the team (not just a JSON file).",
            font=FONT_CAPTION,
            bg=BG,
            fg=T3,
            anchor="w",
        ).pack(fill="x", pady=(8, 4))
        btn_row = tk.Frame(foot, bg=BG)
        btn_row.pack(fill="x")
        cancel = tk.Button(btn_row, text="Cancel", command=self._cancel, font=FS, padx=12, pady=8)
        style_secondary_button(cancel)
        cancel.pack(side="left")
        save = tk.Button(
            btn_row,
            text="Save to phone",
            command=self._save,
            font=("Segoe UI", 11, "bold"),
            bg=GREEN,
            fg=ON_ACCENT,
            activebackground=GREEN,
            activeforeground=ON_ACCENT,
            padx=20,
            pady=8,
            relief="flat",
            cursor="hand2",
        )
        save.pack(side="right")
        self.bind("<Control-s>", lambda _e: self._save())
        self.protocol("WM_DELETE_WINDOW", self._cancel)

        outer = tk.Frame(self, bg=BG)
        outer.pack(fill="both", expand=True, padx=SP["page"], pady=(SP["page"], 0))
        scroll_host = tk.Frame(outer, bg=BG)
        scroll_host.pack(fill="both", expand=True)
        canvas = tk.Canvas(scroll_host, bg=BG, highlightthickness=0, bd=0)
        vsb = themed_vertical_scrollbar(scroll_host, command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        vsb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        body = tk.Frame(canvas, bg=BG)
        win = canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.bind("<Configure>", lambda e: canvas.itemconfig(win, width=e.width))

        intro = instruction_card(body)
        intro.pack(fill="x", pady=(0, SP["md"]))
        tk.Label(intro, text=f"Phone: {phone_name}", font=("Segoe UI", 13, "bold"), bg=BG2, fg=T1, anchor="w").pack(fill="x")
        tk.Label(
            intro,
            text="Edit steps for this phone. Add sequence files/folders as an optional playlist.",
            font=FONT_CAPTION,
            bg=BG2,
            fg=T3,
            anchor="w",
        ).pack(fill="x")

        prof_card = instruction_card(body)
        prof_card.pack(fill="x", pady=(0, SP["md"]))
        tk.Label(prof_card, text="Sequence screen-size profile", font=FONT_SECTION, bg=BG2, fg=T1, anchor="w").pack(fill="x")
        base_w = int(phone_ent.get("sequence_base_w") or AUTHOR_WIDTH)
        base_h = int(phone_ent.get("sequence_base_h") or AUTHOR_HEIGHT)
        self._base_w_var = tk.IntVar(value=base_w)
        self._base_h_var = tk.IntVar(value=base_h)
        self._profile_lbl = tk.Label(prof_card, text="", font=FS, bg=BG2, fg=T2, anchor="w")
        self._profile_lbl.pack(fill="x", pady=(0, SP["xs"]))
        prof_row = tk.Frame(prof_card, bg=BG2)
        prof_row.pack(fill="x")
        tk.Label(prof_row, text="base_w", font=FS, bg=BG2, fg=T3).pack(side="left")
        tk.Spinbox(
            prof_row, from_=240, to=5000, increment=1, textvariable=self._base_w_var,
            width=6, font=("Consolas", 10), bg=BG3, fg=T1, relief="flat",
        ).pack(side="left", padx=(6, 10))
        tk.Label(prof_row, text="base_h", font=FS, bg=BG2, fg=T3).pack(side="left")
        tk.Spinbox(
            prof_row, from_=240, to=8000, increment=1, textvariable=self._base_h_var,
            width=6, font=("Consolas", 10), bg=BG3, fg=T1, relief="flat",
        ).pack(side="left", padx=(6, 10))
        tk.Label(
            prof_row,
            text="(default 900×1600 — tap/swipe coords scale from this baseline)",
            font=FONT_CAPTION,
            bg=BG2,
            fg=T3,
        ).pack(side="left")
        self._base_w_var.trace_add("write", lambda *_: self._refresh_profile_status())
        self._base_h_var.trace_add("write", lambda *_: self._refresh_profile_status())
        self._refresh_profile_status()

        # Steps
        steps_card = instruction_card(body)
        steps_card.pack(fill="x", pady=(0, SP["md"]))
        tk.Label(steps_card, text="Steps", font=FONT_SECTION, bg=BG2, fg=T1, anchor="w").pack(fill="x")
        ctrl = tk.Frame(steps_card, bg=BG2)
        ctrl.pack(fill="x", pady=(SP["sm"], SP["sm"]))
        for text, cmd, danger in (
            ("+ Add Step", self._add_step, False),
            ("Edit", self._edit_step, False),
            ("Remove", self._remove_step, True),
            ("Up", self._up_step, False),
            ("Down", self._down_step, False),
            ("Load JSON…", self._load_json, False),
            ("Export JSON…", self._save_json, False),
        ):
            b = tk.Button(ctrl, text=text, command=cmd, font=FS, padx=8, pady=4)
            if danger:
                style_danger_button(b)
            else:
                style_secondary_button(b)
            b.pack(side="left", padx=(0, 4))

        list_wrap = tk.Frame(steps_card, bg=BG2)
        list_wrap.pack(fill="x")
        self._steps_lb = tk.Listbox(
            list_wrap, font=("Consolas", 10), bg=BG3, fg=T1, relief="flat", activestyle="none", selectbackground=ACCENT, height=8
        )
        sb = themed_vertical_scrollbar(list_wrap, command=self._steps_lb.yview)
        self._steps_lb.configure(yscrollcommand=sb.set)
        self._steps_lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self._steps_lb.bind("<Double-Button-1>", lambda _e: self._edit_step())

        if show_playlist:
            pl_card = instruction_card(body)
            pl_card.pack(fill="x", pady=(0, SP["md"]))
            tk.Label(pl_card, text="Saved sequence playlist (optional)", font=FONT_SECTION, bg=BG2, fg=T1, anchor="w").pack(
                fill="x"
            )
            pl_row = tk.Frame(pl_card, bg=BG2)
            pl_row.pack(fill="x", pady=(SP["sm"], 0))
            pl_list = tk.Frame(pl_row, bg=BG2)
            pl_list.pack(side="left", fill="x", expand=True)
            self._pl_lb = tk.Listbox(
                pl_list, font=("Consolas", 10), bg=BG3, fg=T1, relief="flat", activestyle="none", selectbackground=ACCENT, height=5
            )
            psb = themed_vertical_scrollbar(pl_list, command=self._pl_lb.yview)
            self._pl_lb.configure(yscrollcommand=psb.set)
            self._pl_lb.pack(side="left", fill="both", expand=True)
            psb.pack(side="right", fill="y")
            pl_btns = tk.Frame(pl_row, bg=BG2)
            pl_btns.pack(side="left", padx=(SP["md"], 0))
            for text, cmd in (
                ("Add file…", self._pl_add_file),
                ("Add folder…", self._pl_add_folder),
                ("Remove", self._pl_remove),
                ("Up", self._pl_up),
                ("Down", self._pl_down),
            ):
                b = tk.Button(pl_btns, text=text, command=cmd, font=FS, padx=8, pady=3)
                style_secondary_button(b)
                b.pack(fill="x", pady=(0, 4))

            mode_fr = tk.Frame(pl_card, bg=BG2)
            mode_fr.pack(fill="x", pady=(SP["md"], 0))
            for value, label in (
                ("ordered", "Ordered — next file each repeat"),
                ("random", "Random — pick one file per repeat"),
                ("series", "Series — run every file each repeat"),
            ):
                tk.Radiobutton(
                    mode_fr,
                    text=label,
                    variable=self._mode,
                    value=value,
                    bg=BG2,
                    fg=T1,
                    selectcolor=BG,
                    activebackground=BG2,
                    font=FS,
                    anchor="w",
                    command=self._mark_dirty,
                ).pack(fill="x")

            # Secondary playlist (Set B) + shuffle — prior CPharm parity
            set_b = tk.Frame(pl_card, bg=BG2)
            set_b.pack(fill="x", pady=(SP["md"], 0))
            tk.Checkbutton(
                set_b,
                text="Use secondary playlist (Set B)",
                variable=self._use_set_b,
                command=self._toggle_set_b,
                bg=BG2,
                fg=T1,
                selectcolor=BG,
                activebackground=BG2,
                font=FS,
                anchor="w",
            ).pack(fill="x")
            self._pl_b_host = tk.Frame(pl_card, bg=BG2)
            pl_b_row = tk.Frame(self._pl_b_host, bg=BG2)
            pl_b_row.pack(fill="x", pady=(SP["sm"], 0))
            pl_b_list = tk.Frame(pl_b_row, bg=BG2)
            pl_b_list.pack(side="left", fill="both", expand=True)
            self._pl_b_lb = tk.Listbox(
                pl_b_list,
                font=("Consolas", 10),
                bg=BG3,
                fg=T1,
                relief="flat",
                activestyle="none",
                selectbackground=ACCENT,
                height=4,
            )
            psb2 = themed_vertical_scrollbar(pl_b_list, command=self._pl_b_lb.yview)
            self._pl_b_lb.configure(yscrollcommand=psb2.set)
            self._pl_b_lb.pack(side="left", fill="both", expand=True)
            psb2.pack(side="right", fill="y")
            pl_b_btns = tk.Frame(pl_b_row, bg=BG2)
            pl_b_btns.pack(side="left", padx=(SP["md"], 0))
            for text, cmd in (
                ("Add file…", self._pl_b_add_file),
                ("Add folder…", self._pl_b_add_folder),
                ("Remove", self._pl_b_remove),
                ("Up", self._pl_b_up),
                ("Down", self._pl_b_down),
            ):
                b = tk.Button(pl_b_btns, text=text, command=cmd, font=FS, padx=8, pady=3)
                style_secondary_button(b)
                b.pack(fill="x", pady=(0, 4))

            sh_fr = tk.Frame(pl_card, bg=BG2)
            sh_fr.pack(fill="x", pady=(SP["sm"], 0))
            tk.Label(sh_fr, text="Shuffle", font=FS, bg=BG2, fg=T2).pack(side="left")
            shuffle_combo = ttk.Combobox(
                sh_fr,
                textvariable=self._shuffle,
                values=[
                    SHUFFLE_NONE,
                    SHUFFLE_SET_A,
                    SHUFFLE_SET_B,
                    SHUFFLE_BOTH_SEPARATELY,
                    SHUFFLE_COMBINED,
                ],
                state="readonly",
                width=22,
                font=FS,
            )
            shuffle_combo.pack(side="left", padx=8)
            shuffle_combo.bind("<<ComboboxSelected>>", lambda _e: self._mark_dirty())

            hits = tk.Frame(pl_card, bg=BG2)
            hits.pack(fill="x", pady=(SP["sm"], 0))
            tk.Label(hits, text="Hits / day (0 = use group repeat)", font=FS, bg=BG2, fg=T2).pack(side="left")
            tk.Entry(hits, textvariable=self._hits, width=8, bg=BG3, fg=T1, relief="flat", insertbackground=T1).pack(
                side="left", padx=8
            )

        self._refresh_profile_status()
        self._refresh_steps()
        if show_playlist:
            self._refresh_playlist()
            self._refresh_playlist_b()
            self._toggle_set_b()

    def _cancel(self) -> None:
        if self._dirty and not messagebox.askyesno(
            "Discard changes?",
            "You have unsaved edits for this phone. Close without saving?",
            parent=self,
        ):
            return
        self.destroy()

    def _toggle_set_b(self) -> None:
        self._mark_dirty()
        if not hasattr(self, "_pl_b_host"):
            return
        if self._use_set_b.get():
            self._pl_b_host.pack(fill="x", pady=(0, 0))
        else:
            self._pl_b_host.pack_forget()

    def _mark_dirty(self) -> None:
        self._dirty = True

    def _refresh_profile_status(self) -> None:
        try:
            bw = int(self._base_w_var.get())
            bh = int(self._base_h_var.get())
        except (tk.TclError, ValueError):
            bw, bh = AUTHOR_WIDTH, AUTHOR_HEIGHT
        text = f"Profile baseline: {bw}×{bh}"
        if self._phone_wm_size:
            rw, rh = self._phone_wm_size
            text += f" · device wm size {rw}×{rh}"
            if (rw, rh) != (bw, bh):
                text += " — coords will scale at runtime"
        self._profile_lbl.configure(text=text)

    def _refresh_steps(self) -> None:
        self._steps_lb.delete(0, tk.END)
        for i, step in enumerate(self._draft, 1):
            self._steps_lb.insert(tk.END, f"{i}. {describe_step(step)}")

    def _refresh_playlist(self) -> None:
        self._pl_lb.delete(0, tk.END)
        for name in self._playlist:
            self._pl_lb.insert(tk.END, name)

    def _refresh_playlist_b(self) -> None:
        if not hasattr(self, "_pl_b_lb"):
            return
        self._pl_b_lb.delete(0, tk.END)
        for name in self._playlist_b:
            self._pl_b_lb.insert(tk.END, name)

    def _selected_step(self) -> int | None:
        sel = self._steps_lb.curselection()
        return int(sel[0]) if sel else None

    def _add_step(self) -> None:
        dlg = AddStepDialog(self)
        self.wait_window(dlg)
        if dlg.result:
            self._draft.append(normalize_step(dlg.result))
            self._mark_dirty()
            self._refresh_steps()
            self._steps_lb.selection_set(tk.END)

    def _edit_step(self) -> None:
        idx = self._selected_step()
        if idx is None:
            return
        dlg = AddStepDialog(self, initial=self._draft[idx])
        self.wait_window(dlg)
        if dlg.result:
            self._draft[idx] = normalize_step(dlg.result)
            self._mark_dirty()
            self._refresh_steps()
            self._steps_lb.selection_set(idx)

    def _remove_step(self) -> None:
        idx = self._selected_step()
        if idx is None:
            return
        del self._draft[idx]
        self._mark_dirty()
        self._refresh_steps()

    def _up_step(self) -> None:
        idx = self._selected_step()
        if idx is None or idx == 0:
            return
        self._draft[idx - 1], self._draft[idx] = self._draft[idx], self._draft[idx - 1]
        self._mark_dirty()
        self._refresh_steps()
        self._steps_lb.selection_set(idx - 1)

    def _down_step(self) -> None:
        idx = self._selected_step()
        if idx is None or idx >= len(self._draft) - 1:
            return
        self._draft[idx + 1], self._draft[idx] = self._draft[idx], self._draft[idx + 1]
        self._mark_dirty()
        self._refresh_steps()
        self._steps_lb.selection_set(idx + 1)

    def _load_json(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="Load sequence JSON",
            initialdir=str(sequences_dir()),
            filetypes=[("Sequence JSON", "*.json"), ("All files", "*.*")],
        )
        if not path:
            return
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            messagebox.showerror("Load failed", str(exc), parent=self)
            return
        steps = data if isinstance(data, list) else data.get("steps")
        if not isinstance(steps, list):
            messagebox.showerror("Load failed", "No steps array in file", parent=self)
            return
        self._draft = [normalize_step(s) for s in steps if isinstance(s, dict)]
        self._mark_dirty()
        self._refresh_steps()

    def _save_json(self) -> None:
        path = filedialog.asksaveasfilename(
            parent=self,
            title="Save sequence JSON",
            initialdir=str(sequences_dir()),
            defaultextension=".json",
            filetypes=[("Sequence JSON", "*.json")],
        )
        if not path:
            return
        payload = {
            "name": Path(path).stem,
            "phone": self._phone_name,
            "author_width": AUTHOR_WIDTH,
            "author_height": AUTHOR_HEIGHT,
            "steps": self._draft,
        }
        try:
            payload["author_width"] = int(self._base_w_var.get())
            payload["author_height"] = int(self._base_h_var.get())
        except (tk.TclError, ValueError, TypeError):
            pass
        Path(path).write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        messagebox.showinfo("Saved", f"Wrote {path}", parent=self)

    def _pl_add_file(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="Select sequence JSON",
            initialdir=str(sequences_dir()),
            filetypes=[("Sequence JSON", "*.json")],
        )
        if not path:
            return
        name = _store_name(Path(path))
        if name not in self._playlist:
            self._playlist.append(name)
            self._mark_dirty()
            self._refresh_playlist()

    def _pl_add_folder(self) -> None:
        folder = filedialog.askdirectory(parent=self, title="Folder of sequences", initialdir=str(sequences_dir()))
        if not folder:
            return
        added = 0
        for path in discover_sequence_files(Path(folder), recursive=True):
            name = _store_name(path)
            if name not in self._playlist:
                self._playlist.append(name)
                added += 1
        self._mark_dirty()
        self._refresh_playlist()
        if added == 0:
            messagebox.showinfo("Playlist", "No new sequence files found.", parent=self)

    def _pl_remove(self) -> None:
        sel = list(self._pl_lb.curselection())
        for idx in reversed(sel):
            del self._playlist[idx]
        self._mark_dirty()
        self._refresh_playlist()

    def _pl_up(self) -> None:
        sel = self._pl_lb.curselection()
        if not sel or sel[0] == 0:
            return
        i = sel[0]
        self._playlist[i - 1], self._playlist[i] = self._playlist[i], self._playlist[i - 1]
        self._mark_dirty()
        self._refresh_playlist()
        self._pl_lb.selection_set(i - 1)

    def _pl_down(self) -> None:
        sel = self._pl_lb.curselection()
        if not sel or sel[0] >= len(self._playlist) - 1:
            return
        i = sel[0]
        self._playlist[i + 1], self._playlist[i] = self._playlist[i], self._playlist[i + 1]
        self._mark_dirty()
        self._refresh_playlist()
        self._pl_lb.selection_set(i + 1)

    def _pl_b_add_file(self) -> None:
        path = filedialog.askopenfilename(
            parent=self,
            title="Select sequence JSON (Set B)",
            initialdir=str(sequences_dir()),
            filetypes=[("Sequence JSON", "*.json")],
        )
        if not path:
            return
        name = _store_name(Path(path))
        if name not in self._playlist_b:
            self._playlist_b.append(name)
            self._mark_dirty()
            self._refresh_playlist_b()

    def _pl_b_add_folder(self) -> None:
        folder = filedialog.askdirectory(parent=self, title="Folder of sequences (Set B)", initialdir=str(sequences_dir()))
        if not folder:
            return
        for path in discover_sequence_files(Path(folder), recursive=True):
            name = _store_name(path)
            if name not in self._playlist_b:
                self._playlist_b.append(name)
        self._mark_dirty()
        self._refresh_playlist_b()

    def _pl_b_remove(self) -> None:
        sel = self._pl_b_lb.curselection()
        if not sel:
            return
        del self._playlist_b[int(sel[0])]
        self._mark_dirty()
        self._refresh_playlist_b()

    def _pl_b_up(self) -> None:
        sel = self._pl_b_lb.curselection()
        if not sel or sel[0] == 0:
            return
        i = int(sel[0])
        self._playlist_b[i - 1], self._playlist_b[i] = self._playlist_b[i], self._playlist_b[i - 1]
        self._mark_dirty()
        self._refresh_playlist_b()
        self._pl_b_lb.selection_set(i - 1)

    def _pl_b_down(self) -> None:
        sel = self._pl_b_lb.curselection()
        if not sel or sel[0] >= len(self._playlist_b) - 1:
            return
        i = int(sel[0])
        self._playlist_b[i + 1], self._playlist_b[i] = self._playlist_b[i], self._playlist_b[i + 1]
        self._mark_dirty()
        self._refresh_playlist_b()
        self._pl_b_lb.selection_set(i + 1)

    def _save(self) -> None:
        if not self._draft:
            if not messagebox.askyesno(
                "Save empty sequence?",
                "This phone will have zero steps. Save anyway?",
                parent=self,
            ):
                return
        try:
            hits = _safe_hits_per_day(self._hits.get().strip() or "0", 0)
        except Exception:
            hits = 0
        self._ent["steps"] = copy.deepcopy(self._draft)
        self._ent["sequence_playlist"] = list(self._playlist)
        self._ent["sequence_playlist_mode"] = self._mode.get()
        self._ent["sequence_playlist_shuffle"] = self._shuffle.get() or SHUFFLE_NONE
        self._ent["sequence_playlist_secondary"] = list(self._playlist_b) if self._use_set_b.get() else []
        self._ent["hits_per_day"] = max(0, hits)
        try:
            self._ent["sequence_base_w"] = int(self._base_w_var.get())
            self._ent["sequence_base_h"] = int(self._base_h_var.get())
        except (tk.TclError, ValueError):
            self._ent["sequence_base_w"] = AUTHOR_WIDTH
            self._ent["sequence_base_h"] = AUTHOR_HEIGHT
        self._ent["use_default_template"] = False
        self._ent["explicit_override"] = True
        self._dirty = False
        if callable(self._on_save):
            self._on_save(self._ent)
        self.destroy()
