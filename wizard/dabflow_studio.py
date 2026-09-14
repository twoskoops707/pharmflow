"""DabFlow sequence-building rationale + regenerate helpers for the Studio EXE."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import messagebox
from typing import Any, Callable

from automation.config import REQUIRED_SEQUENCE_VERSION
from automation.dabflow_mapper import load_mapping
from automation.dabflow_sequence_gen import write_catalog, write_presets, write_sequences
from wizard.wizard_paths import automation_dir, bundle_root, desktop_prefs_file, sequences_dir
from wizard.wizard_theme import (
    BG2,
    BG3,
    FONT_CAPTION,
    FONT_MONO,
    FONT_SECTION,
    SP,
    T1,
    T2,
    T3,
    instruction_card,
    style_primary_button,
    style_secondary_button,
)

# Farm cadence defaults (UI + desktop_prefs) — do not auto-start the farm.
DEFAULT_FARM_PATHS = "1,2,3"
DEFAULT_FARM_GAP_MIN_S = 30.0
DEFAULT_FARM_GAP_MAX_S = 45.0
DEFAULT_PATH3_PER_HOUR = 2
DEFAULT_FARM_ALLOW_ADS = True
DEFAULT_FARM_HOURS = 6.0

RATIONALE_LINES = (
    "Full combinatorial catalog: 3 materials × 10 concentrates (incl. hash_rosin) × 2 heaters "
    "× Path1 A–D × Path2 × Path3 A–D with ad-slot fan-out → {count} sequences (every combo). "
    "Required sequence_version ≥ {version} (stale v2 files are refused).",
    "Path1 (after full timer + session notes Skip): A close as-is; B one browse tab + scroll; "
    "C two tabs; D all three tab orders (stats/glass/settings — not home/timer for browse). "
    "Names: p1a_complete, p1b_<tab>_complete, p1c_*, p1d_*.",
    "Path2: halfway exit after 50–80s (p2_halfway).",
    "Path3: same A–D shapes plus exactly one ad click. Path3A = home Sponsored/Mantis ads after "
    "notes (p3a_homeadN_ad); B/C/D = ad on one visited tab × ad-slot ordinal.",
    "Live coords (900×1600): Start Perfect Dab is below the fold — scroll into view, then tap "
    "~({start_x},{start_y}) (#start-dab-btn). Blind tap without scroll fails. "
    "Session notes Skip ~({skip_x},{skip_y}). Age Yes ~({age_x},{age_y}). Nav y≈{nav_y}. "
    "Chromium FRE Skip only when splash visible.",
    "Humanization: per-sequence wait ranges, scroll start/stop variance (scroll_swipe_params / seeds), "
    "coordinate jitter. Regenerate stamps sequence_version={version}.",
    "Farm cadence (scripts/run_farm_354.py): Path1/2 gap {gap_min}–{gap_max}s; "
    "Path3 ≤{p3}/hour/phone; default --hours {hours}. Prefs set PHARMFLOW_FARM_* env vars only — "
    "this card does not start the farm.",
)


def expected_combination_count() -> int:
    return load_mapping().combination_count()


def sequences_output_root() -> Path:
    """Durable sequences root — matches regenerate_base_sequences (frozen vs dev)."""
    if getattr(sys, "frozen", False):
        durable = automation_dir() / "recordings" / "sequences"
        durable.mkdir(parents=True, exist_ok=True)
        return durable
    return sequences_dir()


def count_base_sequences(root: Path | None = None) -> int:
    base = (root or sequences_output_root()) / "base"
    if not base.is_dir():
        return 0
    return sum(1 for p in base.rglob("*.json") if "smoke" not in p.parts)


def _rationale_format_kwargs() -> dict[str, Any]:
    mapping = load_mapping()
    start = mapping.timer_start()
    skip = mapping.session_notes_skip()
    age = mapping.age_gate_consent()
    nav_y = mapping.tab_point("home").y
    return {
        "count": mapping.combination_count(),
        "version": REQUIRED_SEQUENCE_VERSION,
        "start_x": start.x,
        "start_y": start.y,
        "skip_x": skip.x,
        "skip_y": skip.y,
        "age_x": age.x,
        "age_y": age.y,
        "nav_y": nav_y,
        "p3": DEFAULT_PATH3_PER_HOUR,
        "gap_min": int(DEFAULT_FARM_GAP_MIN_S),
        "gap_max": int(DEFAULT_FARM_GAP_MAX_S),
        "hours": int(DEFAULT_FARM_HOURS),
    }


def rationale_text() -> str:
    kw = _rationale_format_kwargs()
    return "\n\n".join(line.format(**kw) for line in RATIONALE_LINES)


def farm_prefs_defaults() -> dict[str, Any]:
    return {
        "paths": DEFAULT_FARM_PATHS,
        "gap_min_s": DEFAULT_FARM_GAP_MIN_S,
        "gap_max_s": DEFAULT_FARM_GAP_MAX_S,
        "path3_per_hour": DEFAULT_PATH3_PER_HOUR,
        "allow_ads": DEFAULT_FARM_ALLOW_ADS,
        "hours": DEFAULT_FARM_HOURS,
    }


def load_farm_prefs() -> dict[str, Any]:
    defaults = farm_prefs_defaults()
    try:
        path = desktop_prefs_file()
        if not path.is_file():
            return defaults
        data = json.loads(path.read_text(encoding="utf-8"))
        farm = data.get("farm") if isinstance(data, dict) else None
        if not isinstance(farm, dict):
            return defaults
        out = dict(defaults)
        if farm.get("paths"):
            out["paths"] = str(farm["paths"]).strip()
        if farm.get("gap_min_s") is not None:
            out["gap_min_s"] = float(farm["gap_min_s"])
        if farm.get("gap_max_s") is not None:
            out["gap_max_s"] = float(farm["gap_max_s"])
        if farm.get("path3_per_hour") is not None:
            out["path3_per_hour"] = int(farm["path3_per_hour"])
        if "allow_ads" in farm:
            out["allow_ads"] = bool(farm["allow_ads"])
        if farm.get("hours") is not None:
            out["hours"] = float(farm["hours"])
        return out
    except Exception:
        return defaults


def save_farm_prefs(prefs: dict[str, Any]) -> None:
    path = desktop_prefs_file()
    existing: dict[str, Any] = {}
    if path.is_file():
        try:
            existing = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            existing = {}
    merged = farm_prefs_defaults()
    merged.update({k: prefs[k] for k in farm_prefs_defaults() if k in prefs})
    existing["farm"] = merged
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")


def apply_farm_prefs_to_environ(prefs: dict[str, Any] | None = None) -> None:
    """Set env vars for farm runners — does not start the farm."""
    p = prefs or load_farm_prefs()
    os.environ["PHARMFLOW_FARM_PATHS"] = str(p.get("paths") or DEFAULT_FARM_PATHS)
    allow = p.get("allow_ads", DEFAULT_FARM_ALLOW_ADS)
    os.environ["PHARMFLOW_FARM_ALLOW_ADS"] = "1" if allow else "0"
    os.environ["PHARMFLOW_FARM_GAP_MIN"] = str(p.get("gap_min_s", DEFAULT_FARM_GAP_MIN_S))
    os.environ["PHARMFLOW_FARM_GAP_MAX"] = str(p.get("gap_max_s", DEFAULT_FARM_GAP_MAX_S))
    os.environ["PHARMFLOW_FARM_PATH3_PER_HOUR"] = str(p.get("path3_per_hour", DEFAULT_PATH3_PER_HOUR))
    os.environ["PHARMFLOW_FARM_HOURS"] = str(p.get("hours", DEFAULT_FARM_HOURS))


def regenerate_base_sequences(*, preset: str = "moderate") -> tuple[int, Path]:
    """Write full combinatorial base sequences under sequences_output_root()/base."""
    root = sequences_output_root()
    out_dir = root / "base"
    count = write_sequences(out_dir, preset=preset, base_only=True, clean=True)
    write_catalog(root / "sequence_catalog.md")
    presets = bundle_root() / "automation" / "presets"
    if not presets.is_dir():
        presets = root.parent.parent / "presets"
    try:
        write_presets(presets)
    except OSError:
        pass
    return count, out_dir


def _btn(parent: tk.Misc, text: str, cmd: Callable[[], None], *, primary: bool = False) -> tk.Button:
    b = tk.Button(parent, text=text, command=cmd, font=("Segoe UI", 10, "bold"), padx=10, pady=5)
    if primary:
        style_primary_button(b)
    else:
        style_secondary_button(b)
    return b


def build_dabflow_blueprint_card(app: Any, parent: tk.Misc) -> None:
    """Docs + regenerate controls for DabFlow blueprint sequences."""
    expected = expected_combination_count()
    on_disk = count_base_sequences()

    card = instruction_card(parent)
    card.pack(fill="x", pady=(0, SP["sm"]))
    tk.Label(card, text="Optional legacy combinatorial catalog", font=FONT_SECTION, bg=BG2, fg=T1, anchor="w").pack(
        fill="x"
    )
    status = tk.Label(
        card,
        text=(
            f"Catalog: {on_disk} on disk / {expected} expected · "
            f"REQUIRED_SEQUENCE_VERSION={REQUIRED_SEQUENCE_VERSION}"
        ),
        font=FONT_MONO,
        bg=BG2,
        fg=T2,
        anchor="w",
    )
    status.pack(fill="x", pady=(4, 6))
    app._dabflow_status_label = status

    tk.Label(
        card,
        text=rationale_text(),
        font=FONT_CAPTION,
        bg=BG2,
        fg=T3,
        anchor="w",
        justify="left",
        wraplength=820,
    ).pack(fill="x", pady=(0, 8))

    row = tk.Frame(card, bg=BG2)
    row.pack(fill="x")
    _btn(row, "Regenerate all sequences", lambda: _regen_clicked(app), primary=True).pack(
        side="left", padx=(0, 6)
    )
    _btn(row, "Open sequences folder", lambda: app._open_sequences_folder()).pack(side="left", padx=(0, 6))
    _btn(row, "Open catalog.md", lambda: _open_catalog(app)).pack(side="left")


def _refresh_status(app: Any) -> None:
    label = getattr(app, "_dabflow_status_label", None)
    if label is None:
        return
    expected = expected_combination_count()
    on_disk = count_base_sequences()
    label.configure(
        text=(
            f"Catalog: {on_disk} on disk / {expected} expected · "
            f"REQUIRED_SEQUENCE_VERSION={REQUIRED_SEQUENCE_VERSION}"
        )
    )


def _regen_clicked(app: Any) -> None:
    if getattr(app, "_dabflow_regen_busy", False):
        app._log("Regenerate already running…", "warn")
        return
    expected = expected_combination_count()
    out_root = sequences_output_root() / "base"
    if not messagebox.askyesno(
        "Regenerate legacy catalog",
        f"Rewrite legacy combinatorial base sequences under:\n{out_root}\n\n"
        f"Expected count: {expected}\nPrefer Site Interview for new sites. Continue?",
        parent=app,
    ):
        return

    app._dabflow_regen_busy = True
    app._log(f"Regenerating {expected} legacy catalog sequences…", "ok")

    def work() -> None:
        try:
            count, out_dir = regenerate_base_sequences()
            app.after(
                0,
                lambda c=count, d=out_dir: (
                    app._log(f"Generated {c} sequences → {d}", "ok"),
                    _refresh_status(app),
                    setattr(app, "_dabflow_regen_busy", False),
                ),
            )
        except Exception as exc:
            err_msg = str(exc)
            app.after(
                0,
                lambda msg=err_msg: (
                    app._log(f"Regenerate failed: {msg}", "err"),
                    setattr(app, "_dabflow_regen_busy", False),
                ),
            )

    threading.Thread(target=work, daemon=True).start()


def _open_catalog(app: Any) -> None:
    path = sequences_output_root() / "sequence_catalog.md"
    if not path.is_file():
        alt = sequences_dir() / "sequence_catalog.md"
        path = alt if alt.is_file() else path
    if not path.is_file():
        alt = bundle_root() / "automation" / "recordings" / "sequences" / "sequence_catalog.md"
        path = alt if alt.is_file() else path
    if not path.is_file():
        app._log("sequence_catalog.md not found — regenerate first", "warn")
        return
    if os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(path)])


def build_farm_cadence_card(app: Any, parent: tk.Misc) -> None:
    """Farm path/gap/Path3 defaults — saves prefs only; never starts the farm."""
    prefs = load_farm_prefs()
    if not hasattr(app, "_farm_paths_var"):
        app._farm_paths_var = tk.StringVar(value=str(prefs["paths"]))
        app._farm_gap_min_var = tk.StringVar(value=str(prefs["gap_min_s"]))
        app._farm_gap_max_var = tk.StringVar(value=str(prefs["gap_max_s"]))
        app._farm_path3_var = tk.StringVar(value=str(prefs["path3_per_hour"]))
        app._farm_allow_ads_var = tk.BooleanVar(value=bool(prefs["allow_ads"]))
        app._farm_hours_var = tk.StringVar(value=str(prefs["hours"]))

    card = instruction_card(parent)
    card.pack(fill="x", pady=SP["sm"])
    tk.Label(card, text="Farm cadence (defaults — does not start farm)", font=FONT_SECTION, bg=BG2, fg=T1, anchor="w").pack(
        fill="x"
    )
    tk.Label(
        card,
        text=(
            f"Path1/2 gap {int(DEFAULT_FARM_GAP_MIN_S)}–{int(DEFAULT_FARM_GAP_MAX_S)}s; "
            f"Path3 ≤{DEFAULT_PATH3_PER_HOUR}/hour/phone; default duration "
            f"{int(DEFAULT_FARM_HOURS)}h (PHARMFLOW_FARM_HOURS / --hours). "
            "Saved to desktop_prefs and env for scripts/run_farm_354.py — does not start farm."
        ),
        font=FONT_CAPTION,
        bg=BG2,
        fg=T3,
        anchor="w",
        wraplength=800,
        justify="left",
    ).pack(fill="x", pady=(2, 8))

    grid = tk.Frame(card, bg=BG2)
    grid.pack(fill="x")

    def _row(label: str, var: tk.Variable, width: int = 12) -> None:
        r = tk.Frame(grid, bg=BG2)
        r.pack(fill="x", pady=2)
        tk.Label(r, text=label, font=FONT_CAPTION, bg=BG2, fg=T3, width=22, anchor="w").pack(side="left")
        tk.Entry(r, textvariable=var, bg=BG3, fg=T1, relief="flat", insertbackground=T1, width=width).pack(
            side="left", ipady=3
        )

    _row("Paths (PHARMFLOW_FARM_PATHS)", app._farm_paths_var, 16)
    _row("Gap min seconds", app._farm_gap_min_var)
    _row("Gap max seconds", app._farm_gap_max_var)
    _row("Path3 per hour / phone", app._farm_path3_var)
    _row("Duration hours (--hours)", app._farm_hours_var)
    tk.Checkbutton(
        grid,
        text="Allow Path3 ads (PHARMFLOW_FARM_ALLOW_ADS)",
        variable=app._farm_allow_ads_var,
        bg=BG2,
        fg=T1,
        selectcolor=BG2,
        activebackground=BG2,
        font=FONT_CAPTION,
        anchor="w",
    ).pack(fill="x", pady=(4, 6))

    _btn(card, "Save farm defaults", lambda: _save_farm_clicked(app), primary=True).pack(anchor="w")


def _save_farm_clicked(app: Any) -> None:
    try:
        prefs = {
            "paths": app._farm_paths_var.get().strip() or DEFAULT_FARM_PATHS,
            "gap_min_s": float(app._farm_gap_min_var.get()),
            "gap_max_s": float(app._farm_gap_max_var.get()),
            "path3_per_hour": int(float(app._farm_path3_var.get())),
            "allow_ads": bool(app._farm_allow_ads_var.get()),
            "hours": float(app._farm_hours_var.get()),
        }
    except ValueError:
        app._log("Farm defaults: enter numeric gap / Path3 / hours values", "warn")
        return
    save_farm_prefs(prefs)
    apply_farm_prefs_to_environ(prefs)
    app._log(
        f"Saved farm defaults: paths={prefs['paths']} gap={prefs['gap_min_s']}-{prefs['gap_max_s']}s "
        f"path3={prefs['path3_per_hour']}/hr hours={prefs['hours']} "
        f"ads={'on' if prefs['allow_ads'] else 'off'} (farm not started)",
        "ok",
    )
