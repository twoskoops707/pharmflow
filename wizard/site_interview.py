"""Site Interview — Q&A in the EXE that builds a SiteProfile for any website/APK."""

from __future__ import annotations

import json
import os
import subprocess
import threading
import tkinter as tk
from tkinter import messagebox
from typing import Any, Callable

from automation.site_profile import (
    AdClick,
    BrowsePath,
    CoreAction,
    FarmPrefs,
    GateTap,
    HumanizePrefs,
    SiteProfile,
    interview_defaults,
    list_profiles,
    save_profile,
)
from automation.dabflow_site_profile import ensure_dabflow_profile
from automation.site_sequence_gen import (
    build_sequence_variants,
    validate_sequence_variants,
    write_profile_sequences,
)
from wizard.site_llm import (
    apply_suggestions_to_interview_vars,
    get_llm_settings,
    llm_configured,
    save_llm_settings,
    suggest_profile_fields,
)
from wizard.wizard_paths import app_data_root, save_config, sequences_dir
from wizard.wizard_theme import (
    BG2,
    BG3,
    FONT_CAPTION,
    FONT_SECTION,
    SP,
    T1,
    T2,
    T3,
    instruction_card,
    style_primary_button,
    style_secondary_button,
)


def _btn(parent: tk.Misc, text: str, cmd: Callable[[], None], *, primary: bool = False) -> tk.Button:
    b = tk.Button(parent, text=text, command=cmd, font=("Segoe UI", 10, "bold"), padx=10, pady=5)
    if primary:
        style_primary_button(b)
    else:
        style_secondary_button(b)
    return b


def _entry(parent: tk.Misc, var: tk.StringVar, width: int = 48) -> tk.Entry:
    e = tk.Entry(parent, textvariable=var, bg=BG3, fg=T1, relief="flat", insertbackground=T1, width=width)
    e.pack(fill="x", pady=(2, 6), ipady=3)
    return e


def _labeled(parent: tk.Misc, text: str) -> None:
    tk.Label(parent, text=text, font=FONT_CAPTION, bg=BG2, fg=T3, anchor="w").pack(fill="x")


def build_site_interview_card(app: Any, parent: tk.Misc) -> None:
    """Primary Builder card: interview → profile → humanized sequences."""
    card = instruction_card(parent)
    card.pack(fill="x", pady=(0, SP["sm"]))
    tk.Label(
        card,
        text="Site Interview — any website or APK",
        font=FONT_SECTION,
        bg=BG2,
        fg=T1,
        anchor="w",
    ).pack(fill="x")
    tk.Label(
        card,
        text=(
            "CPharm is a virtual phone farm. Answer these questions for the site/app you want to farm. "
            "We save a Site Profile and generate humanized sequences. "
            "One brand (e.g. a previous campaign) is never what the EXE is — only a target you choose."
        ),
        font=FONT_CAPTION,
        bg=BG2,
        fg=T2,
        anchor="w",
        justify="left",
        wraplength=820,
    ).pack(fill="x", pady=(4, 8))

    if not hasattr(app, "_si_kind"):
        app._si_kind = tk.StringVar(value="website")
        app._si_name = tk.StringVar(value="")
        app._si_url = tk.StringVar(value="")
        app._si_package = tk.StringVar(value="")
        app._si_gate = tk.BooleanVar(value=True)
        app._si_gate_xy = tk.StringVar(value="380,980")
        app._si_core_xy = tk.StringVar(value="450,1200")
        app._si_core_scroll = tk.BooleanVar(value=True)
        app._si_browse = tk.BooleanVar(value=True)
        app._si_ads = tk.BooleanVar(value=True)
        app._si_ad_coords = tk.StringVar(value="450,1100")
        app._si_humanize = tk.StringVar(value="moderate")
        app._si_seqs_hr = tk.StringVar(value="15")
        app._si_phones = tk.StringVar(value="6")
        app._si_hours = tk.StringVar(value="6")
        app._si_ads_hr = tk.StringVar(value="1")
        app._si_start_spread = tk.StringVar(value="30")
        app._si_ntfy = tk.StringVar(value="twskoops")
    llm = get_llm_settings()
    if not hasattr(app, "_si_llm_key"):
        app._si_llm_key = tk.StringVar(value=llm.get("api_key") or "")
        app._si_llm_base = tk.StringVar(value=llm.get("base_url") or "")
        app._si_llm_model = tk.StringVar(value=llm.get("model") or "")
        app._si_llm_notes = tk.StringVar(value="")

    kind_row = tk.Frame(card, bg=BG2)
    kind_row.pack(fill="x", pady=(0, 4))
    tk.Label(kind_row, text="Target type", font=FONT_CAPTION, bg=BG2, fg=T3).pack(side="left")
    tk.Radiobutton(
        kind_row, text="Website", variable=app._si_kind, value="website", bg=BG2, fg=T1, selectcolor=BG2, activebackground=BG2
    ).pack(side="left", padx=8)
    tk.Radiobutton(
        kind_row, text="App (APK)", variable=app._si_kind, value="app", bg=BG2, fg=T1, selectcolor=BG2, activebackground=BG2
    ).pack(side="left")

    _labeled(card, "Display name")
    _entry(card, app._si_name)
    _labeled(card, "Website URL (if website)")
    _entry(card, app._si_url)
    _labeled(card, "Package name (if app)")
    _entry(card, app._si_package)

    tk.Checkbutton(
        card,
        text="Has an entry gate (age / cookies / continue)",
        variable=app._si_gate,
        bg=BG2,
        fg=T1,
        selectcolor=BG2,
        activebackground=BG2,
        font=FONT_CAPTION,
        anchor="w",
    ).pack(fill="x")
    _labeled(card, "Gate tap x,y (900×1600)")
    _entry(card, app._si_gate_xy, 20)

    _labeled(card, "Core success tap x,y (timer / CTA / submit)")
    _entry(card, app._si_core_xy, 20)
    tk.Checkbutton(
        card,
        text="Scroll into view before core tap",
        variable=app._si_core_scroll,
        bg=BG2,
        fg=T1,
        selectcolor=BG2,
        activebackground=BG2,
        font=FONT_CAPTION,
        anchor="w",
    ).pack(fill="x")
    tk.Checkbutton(
        card,
        text="Include browse-tab path variants",
        variable=app._si_browse,
        bg=BG2,
        fg=T1,
        selectcolor=BG2,
        activebackground=BG2,
        font=FONT_CAPTION,
        anchor="w",
    ).pack(fill="x")
    tk.Checkbutton(
        card,
        text="Include sponsored/ad click variants",
        variable=app._si_ads,
        bg=BG2,
        fg=T1,
        selectcolor=BG2,
        activebackground=BG2,
        font=FONT_CAPTION,
        anchor="w",
    ).pack(fill="x")
    _labeled(card, "Ad tap targets x,y (semicolon-separated; one distinct ad per target)")
    _entry(card, app._si_ad_coords)

    _labeled(card, "Humanize preset (conservative / moderate / aggressive)")
    _entry(card, app._si_humanize, 20)
    _labeled(card, "Farm: sequences per hour / phone")
    _entry(card, app._si_seqs_hr, 12)
    _labeled(card, "Farm: number of phones")
    _entry(card, app._si_phones, 12)
    _labeled(card, "Farm: hours")
    _entry(card, app._si_hours, 12)
    _labeled(card, "Farm: ad sequences per hour / phone")
    _entry(card, app._si_ads_hr, 12)
    _labeled(card, "Farm-start spread across phones (minutes)")
    _entry(card, app._si_start_spread, 12)
    _labeled(card, "ntfy topic (optional 2-hour reports)")
    _entry(card, app._si_ntfy, 24)

    tk.Label(
        card,
        text=(
            "Builder safeguards (always on): verified new exit IP + fresh browser identity, "
            "full browser-data wipe, fingerprint verification, unique sequences across phones, "
            "different per-sequence waits, randomized full-hour starts, and no concurrent/"
            "back-to-back reuse of the same ad."
        ),
        font=FONT_CAPTION,
        bg=BG2,
        fg=T2,
        anchor="w",
        justify="left",
        wraplength=820,
    ).pack(fill="x", pady=(8, 2))

    tk.Label(card, text="Optional AI assist (OpenAI-compatible)", font=FONT_SECTION, bg=BG2, fg=T1, anchor="w").pack(
        fill="x", pady=(10, 2)
    )
    tk.Label(
        card,
        text=(
            "Offline Q&A always works. If you paste an API key, AI can suggest field fills — "
            "you confirm before anything is applied. Never auto-starts the farm."
        ),
        font=FONT_CAPTION,
        bg=BG2,
        fg=T3,
        anchor="w",
        wraplength=820,
        justify="left",
    ).pack(fill="x", pady=(0, 4))
    _labeled(card, "API key (stored in C:\\CPharm config)")
    key_entry = tk.Entry(
        card,
        textvariable=app._si_llm_key,
        bg=BG3,
        fg=T1,
        relief="flat",
        insertbackground=T1,
        show="*",
        width=48,
    )
    key_entry.pack(fill="x", pady=(2, 6), ipady=3)
    _labeled(card, "Base URL (default https://api.openai.com/v1)")
    _entry(card, app._si_llm_base)
    _labeled(card, "Model (default gpt-4o-mini)")
    _entry(card, app._si_llm_model, 32)
    _labeled(card, "Notes for AI (optional)")
    _entry(card, app._si_llm_notes)

    row = tk.Frame(card, bg=BG2)
    row.pack(fill="x", pady=(8, 0))
    _btn(row, "Save profile + generate sequences", lambda: _interview_generate(app), primary=True).pack(
        side="left", padx=(0, 6)
    )
    _btn(row, "Validate logic", lambda: _interview_validate(app)).pack(side="left", padx=(0, 6))
    _btn(row, "Suggest with AI…", lambda: _interview_suggest_ai(app)).pack(side="left", padx=(0, 6))
    _btn(row, "Save AI settings", lambda: _save_ai_settings(app)).pack(side="left", padx=(0, 6))
    _btn(row, "Open sites folder", lambda: _open_sites(app)).pack(side="left")

    ensure_dabflow_profile(app_data_root())
    existing = list_profiles(app_data_root())
    tk.Label(
        card,
        text=f"Saved profiles: {', '.join(existing) if existing else '(none yet)'}",
        font=FONT_CAPTION,
        bg=BG2,
        fg=T3,
        anchor="w",
    ).pack(fill="x", pady=(8, 0))


def _parse_xy(raw: str, default: tuple[int, int]) -> tuple[int, int]:
    try:
        parts = [p.strip() for p in str(raw).replace(" ", "").split(",")]
        return int(parts[0]), int(parts[1])
    except (IndexError, TypeError, ValueError):
        return default


def _parse_xy_list(raw: str, default: tuple[int, int]) -> list[tuple[int, int]]:
    targets: list[tuple[int, int]] = []
    for item in str(raw or "").split(";"):
        if not item.strip():
            continue
        xy = _parse_xy(item, (-1, -1))
        if 0 <= xy[0] <= 900 and 0 <= xy[1] <= 1600 and xy not in targets:
            targets.append(xy)
    return targets or [default]


def _profile_from_form(app: Any) -> SiteProfile:
    kind = app._si_kind.get().strip() or "website"
    name = app._si_name.get().strip() or ("website" if kind == "website" else "app")
    gx, gy = _parse_xy(app._si_gate_xy.get(), (380, 980))
    cx, cy = _parse_xy(app._si_core_xy.get(), (450, 1200))
    p = interview_defaults(
        kind=kind,
        name=name,
        url=app._si_url.get().strip(),
        package=app._si_package.get().strip(),
    )
    p.gates = [GateTap(label="entry_gate", x=gx, y=gy)] if app._si_gate.get() else []
    p.core = CoreAction(
        kind="scroll_then_tap" if app._si_core_scroll.get() else "tap",
        description="Core success action",
        x=cx,
        y=cy,
        scroll_before=bool(app._si_core_scroll.get()),
    )
    if not app._si_browse.get():
        p.browse_paths = []
    else:
        p.browse_paths = [
            BrowsePath(name="tab_a", x=180, y=1535),
            BrowsePath(name="tab_b", x=450, y=1535),
            BrowsePath(name="tab_c", x=720, y=1535),
        ]
    if not app._si_ads.get():
        p.ads = []
    else:
        ad_targets = _parse_xy_list(app._si_ad_coords.get(), (450, 1100))
        p.ads = [
            AdClick(name=f"sponsored_{idx}", x=x, y=y, max_per_hour=1)
            for idx, (x, y) in enumerate(ad_targets)
        ]
    preset = (app._si_humanize.get() or "moderate").strip().lower()
    if preset not in ("conservative", "moderate", "aggressive"):
        preset = "moderate"
    p.humanize = HumanizePrefs(preset=preset, concurrent_unique_sequences=True)
    try:
        seqs = int(float(app._si_seqs_hr.get() or "15"))
        phones = int(float(app._si_phones.get() or "6"))
        hours = float(app._si_hours.get() or "6")
        ads_hr = int(float(app._si_ads_hr.get() or "1"))
        start_spread = int(float(app._si_start_spread.get() or "30"))
    except ValueError:
        seqs, phones, hours, ads_hr, start_spread = 15, 6, 6.0, 1, 30
    p.farm = FarmPrefs(
        phone_count=max(1, min(10, phones)),
        seqs_per_hour=seqs,
        hours=hours,
        allow_ads=bool(app._si_ads.get()),
        ads_per_hour=max(0, ads_hr),
        ntfy_topic=(app._si_ntfy.get() or "").strip(),
        ntfy_hourly=True,
        ntfy_interval_s=7200,
        startup_spread_minutes=max(0, min(55, start_spread)),
    )
    return p


def _save_ai_settings(app: Any) -> None:
    save_llm_settings(
        api_key=app._si_llm_key.get(),
        base_url=app._si_llm_base.get(),
        model=app._si_llm_model.get(),
    )
    status = "configured" if llm_configured() else "cleared (no key)"
    app._log(f"AI settings saved — {status}", "ok")


def _interview_suggest_ai(app: Any) -> None:
    if getattr(app, "_si_busy", False):
        app._log("Site Interview busy…", "warn")
        return
    # Persist key from form before calling
    save_llm_settings(
        api_key=app._si_llm_key.get(),
        base_url=app._si_llm_base.get(),
        model=app._si_llm_model.get(),
    )
    if not llm_configured():
        messagebox.showwarning(
            "AI assist",
            "Paste an OpenAI-compatible API key first (or set CPHARM_LLM_API_KEY).\n"
            "Interview still works fully offline without AI.",
            parent=app,
        )
        return
    try:
        draft = _profile_from_form(app)
    except Exception as exc:
        app._log(f"Interview form error: {exc}", "err")
        return

    app._si_busy = True
    app._log("Asking AI for Site Interview suggestions…", "ok")
    notes = app._si_llm_notes.get()

    def work() -> None:
        try:
            suggestions = suggest_profile_fields(draft, extra_notes=notes)

            def on_ui() -> None:
                setattr(app, "_si_busy", False)
                rationale = str(suggestions.get("rationale") or "").strip()
                preview = json.dumps({k: v for k, v in suggestions.items() if k != "rationale"}, indent=2)
                msg = "Apply these AI suggestions to the form?\n\n"
                if rationale:
                    msg += f"{rationale}\n\n"
                msg += preview[:1800]
                if not messagebox.askyesno("Confirm AI suggestions", msg, parent=app):
                    app._log("AI suggestions discarded", "warn")
                    return
                applied = apply_suggestions_to_interview_vars(app, suggestions)
                app._log(f"Applied AI suggestions: {', '.join(applied) or '(none)'}", "ok")

            app.after(0, on_ui)
        except Exception as exc:
            app.after(
                0,
                lambda: (
                    app._log(f"AI suggest failed: {exc}", "err"),
                    setattr(app, "_si_busy", False),
                ),
            )

    threading.Thread(target=work, daemon=True).start()


def _interview_validate(app: Any) -> None:
    """Show the same catalog audit enforced during generation."""
    try:
        profile = _profile_from_form(app)
        audit = validate_sequence_variants(build_sequence_variants(profile))
    except Exception as exc:
        messagebox.showerror("Builder logic validation", str(exc), parent=app)
        return
    details = (
        f"Sequences: {audit['sequence_count']}\n"
        f"Unique names/bodies: {audit['unique_names']}/{audit['unique_bodies']}\n"
        f"Different starting waits: {audit['unique_start_waits']}\n"
        f"Distinct ad targets: {audit['unique_ad_targets']}\n\n"
    )
    if audit["ok"]:
        details += (
            "PASS — identity rotation, fingerprint verification, browser wipe, "
            "humanized waits, unique bodies, and target launch/close are present."
        )
        messagebox.showinfo("Builder logic validation", details, parent=app)
    else:
        details += "FAIL\n" + "\n".join(str(err) for err in audit["errors"])
        messagebox.showerror("Builder logic validation", details, parent=app)


def _interview_generate(app: Any) -> None:
    if getattr(app, "_si_busy", False):
        app._log("Site Interview already generating…", "warn")
        return
    try:
        profile = _profile_from_form(app)
    except Exception as exc:
        app._log(f"Interview form error: {exc}", "err")
        return
    if profile.target_kind == "website" and not profile.url:
        messagebox.showwarning("Site Interview", "Enter a website URL.", parent=app)
        return
    if profile.target_kind == "app" and not profile.package:
        messagebox.showwarning("Site Interview", "Enter an app package name.", parent=app)
        return
    if not messagebox.askyesno(
        "Generate sequences",
        f"Save profile '{profile.slug}' and generate humanized sequences?\n\n"
        f"Output: {sequences_dir() / profile.slug}",
        parent=app,
    ):
        return

    app._si_busy = True
    app._log(f"Saving site profile '{profile.slug}' and generating sequences…", "ok")

    def work() -> None:
        try:
            path = save_profile(app_data_root(), profile)
            count = write_profile_sequences(profile, sequences_dir(), clean=True)
            audit = validate_sequence_variants(build_sequence_variants(profile))
            save_config({"active_site_slug": profile.slug})
            # Remember active site for farm prefs
            app.after(
                0,
                lambda: (
                    setattr(app, "_active_site_slug", profile.slug),
                    app._log(f"Profile saved → {path}", "ok"),
                    app._log(f"Generated {count} humanized sequences → {sequences_dir() / profile.slug}", "ok"),
                    app._log(
                        "Builder safeguards verified: "
                        f"{audit['unique_bodies']} unique bodies, "
                        f"{audit['unique_start_waits']} starting waits, "
                        f"{audit['unique_ad_targets']} ad targets",
                        "ok",
                    ),
                    setattr(app, "_si_busy", False),
                ),
            )
        except Exception as exc:
            app.after(
                0,
                lambda: (
                    app._log(f"Site Interview failed: {exc}", "err"),
                    setattr(app, "_si_busy", False),
                ),
            )

    threading.Thread(target=work, daemon=True).start()


def _open_sites(app: Any) -> None:
    path = app_data_root() / "sites"
    path.mkdir(parents=True, exist_ok=True)
    if os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
    else:
        subprocess.Popen(["xdg-open", str(path)])
