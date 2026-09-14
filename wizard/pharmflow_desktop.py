"""
PharmFlow - unified Windows desktop application.

Single shipped binary: ``PharmFlow.exe`` — 9-step wizard, phone setup, install, dashboard.
Optional: ``PharmFlow.exe --phone-setup`` opens Phones (step 4) only.

Build (from ``wizard/``)::

    py -3 -m PyInstaller PharmFlow.spec
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox

import webbrowser

# Frozen one-file: PyInstaller may ship wizard/*.py under _MEIPASS/wizard/
# (datas) and/or as top-level modules. Source runs: this file's directory.
_wizard_dir = Path(__file__).resolve().parent
_path_candidates = [_wizard_dir]
if getattr(sys, "frozen", False):
    _mei = Path(getattr(sys, "_MEIPASS", "") or "")
    if _mei.is_dir():
        _path_candidates.extend([_mei, _mei / "wizard"])
for _p in _path_candidates:
    _sd = str(_p)
    if _p.is_dir() and _sd not in sys.path:
        sys.path.insert(0, _sd)

try:
    from wizard_paths import automation_on_sys_path
except ImportError:  # frozen datas layout: wizard.wizard_paths
    from wizard.wizard_paths import automation_on_sys_path  # type: ignore[no-redef]

try:
    from pharmflow_version import build_label, instance_title
except ImportError:
    from wizard.pharmflow_version import build_label, instance_title  # type: ignore[no-redef]

# Theme + helpers (lightweight path before setup_wizard pulls full tree)
try:
    from wizard_theme import (
        ACCENT,
        BG,
        BG2,
        GREEN,
        T1,
        T2,
        T3,
        _style_scrollbars,
        accent_top_strip,
        style_primary_button,
        style_secondary_button,
        style_success_button,
        themed_vertical_scrollbar,
    )
except ImportError:
    from wizard.wizard_theme import (  # type: ignore[no-redef]
        ACCENT,
        BG,
        BG2,
        GREEN,
        T1,
        T2,
        T3,
        _style_scrollbars,
        accent_top_strip,
        style_primary_button,
        style_secondary_button,
        style_success_button,
        themed_vertical_scrollbar,
    )


def _center(win: tk.Tk | tk.Toplevel, w: int, h: int) -> None:
    win.update_idletasks()
    sw = win.winfo_screenwidth()
    sh = win.winfo_screenheight()
    x = max(0, (sw - w) // 2)
    y = max(0, (sh - h) // 2)
    win.geometry(f"{w}x{h}+{x}+{y}")


def _show_splash() -> None:
    """Short branded splash (no external image required)."""
    s = tk.Tk()
    s.overrideredirect(True)
    w, h = 580, 360
    _center(s, w, h)
    s.configure(bg="#05070d")
    fr = tk.Frame(s, bg="#05070d")
    fr.pack(fill="both", expand=True, padx=2, pady=2)
    tk.Frame(fr, bg=ACCENT, height=4).pack(fill="x")
    inner = tk.Frame(fr, bg="#0a0e18")
    inner.pack(fill="both", expand=True)
    tk.Label(
        inner,
        text="PharmFlow",
        font=("Segoe UI", 36, "bold"),
        bg="#0a0e18",
        fg=T1,
    ).pack(pady=(48, 8))
    tk.Label(
        inner,
        text="Virtual phones and a web dashboard",
        font=("Segoe UI", 13),
        bg="#0a0e18",
        fg=T2,
    ).pack()
    tk.Label(
        inner,
        text="Starting…",
        font=("Segoe UI", 11),
        bg="#0a0e18",
        fg=T3,
    ).pack(pady=(28, 0))
    s.after(1600, s.destroy)
    s.mainloop()


def _open_explorer_folder(path: str, *, parent: tk.Misc | None = None) -> None:
    p = Path(path)
    if not p.is_dir():
        messagebox.showwarning("Folder", f"Not found:\n{p}", parent=parent)
        return
    try:
        if sys.platform == "win32":
            os.startfile(str(p))  # type: ignore[attr-defined]
        else:
            subprocess.Popen(["xdg-open", str(p)])
    except OSError as e:
        messagebox.showerror("Folder", str(e), parent=parent)


def _kick_tor_warm_early() -> None:
    """Non-blocking: farm-default Tor host warm (see ``tor_manager.start_tor_warm_background``)."""
    if os.environ.get("PHARMFLOW_SKIP_TOR_WAIT", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    ):
        return
    try:
        automation_on_sys_path()
        import tor_manager  # noqa: WPS433

        tor_manager.start_tor_warm_background()
    except Exception:
        pass


def _try_open_dashboard(parent: tk.Misc | None = None) -> None:
    """Open Dashboard URL (server must already be running from Setup -> Launch)."""
    import threading

    # dashboard_base_url / probe live in setup_wizard — import late
    from setup_wizard import dashboard_base_url, probe_dashboard_listen_port

    def work() -> None:
        def show_error(title: str, message: str) -> None:
            def paint() -> None:
                messagebox.showerror(title, message, parent=parent)

            if parent is not None:
                try:
                    parent.after(0, paint)
                    return
                except tk.TclError:
                    pass
            paint()

        if not probe_dashboard_listen_port():
            show_error(
                "Dashboard",
                "Service is not running — start the service first.",
            )
            return
        url = f"{dashboard_base_url()}/"
        try:
            opened = bool(webbrowser.open(url))
        except OSError as e:
            show_error("Browser", str(e))
            return
        if not opened:
            show_error(
                "Dashboard",
                f"Dashboard is up at {url} but the browser did not open.",
            )

    threading.Thread(target=work, daemon=True).start()


def tor_pin_landed(result: dict | None) -> bool:
    """True only when the guest proxy write landed on a loopback exit."""
    if not isinstance(result, dict) or not result.get("http_proxy_applied"):
        return False
    proxy = str(result.get("http_proxy") or "").strip()
    if not proxy.startswith("127.0.0.1:") or proxy.endswith(":0"):
        return False
    try:
        return int(proxy.split(":", 1)[1]) > 0
    except (IndexError, ValueError):
        return False


def merge_tor_desktop_prefs(path: Path, serials: list[str]) -> None:
    """Record a real Tor pin without replacing the rest of desktop_prefs.json."""
    existing: dict = {}
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                existing = data
        except (OSError, json.JSONDecodeError):
            existing = {}
    existing["tor_proxy_configured"] = True
    if serials:
        existing["phone_serials"] = list(serials)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(existing, indent=2) + "\n", encoding="utf-8")


def run_main_window(*, initial_view: str | None = None) -> None:
    from setup_wizard import (
        PharmFlowWizard,
        _pharmflow_install_root,
        dashboard_base_url,
        state,
    )

    root = tk.Tk()
    _style_scrollbars(root)
    root.title(instance_title("Home"))
    root.geometry("1120x920")
    root.minsize(940, 760)
    root.configure(bg=BG, highlightthickness=0)
    accent_top_strip(root).pack(fill="x")

    # — Menus —
    menubar = tk.Menu(root)
    file_m = tk.Menu(menubar, tearoff=0)
    file_m.add_command(
        label="Open PharmFlow folder…",
        command=lambda: _open_folder_from_state(),
    )
    file_m.add_separator()

    def _quit_pharmflow() -> None:
        root.destroy()

    file_m.add_command(label="Exit", command=_quit_pharmflow)
    menubar.add_cascade(label="File", menu=file_m)

    view_m = tk.Menu(menubar, tearoff=0)
    view_m.add_command(label="Home", command=lambda: show_home())
    view_m.add_command(label="Setup", command=lambda: show_setup())
    view_m.add_separator()
    view_m.add_command(
        label="Open Dashboard in Browser",
        command=lambda: _try_open_dashboard(root),
    )
    menubar.add_cascade(label="View", menu=view_m)

    # — Tools: sequences + stealth (lazy imports; automation/ only when needed) —
    def _examples_dir() -> Path:
        return Path(_pharmflow_install_root()) / "automation" / "recordings" / "sequences"

    def _list_example_json_names() -> list[str]:
        d = _examples_dir()
        if not d.is_dir():
            return []
        return sorted(p.name for p in d.glob("*.json"))

    def _examples_open_folder() -> None:
        d = _examples_dir()
        if not d.is_dir():
            messagebox.showwarning(
                "Example sequences",
                f"Folder not found (complete Setup or clone repo with automation/):\n{d}",
                parent=root,
            )
            return
        _open_explorer_folder(str(d), parent=root)

    def _examples_copy_folder_path() -> None:
        d = _examples_dir()
        root.clipboard_clear()
        root.clipboard_append(str(d))
        root.update_idletasks()
        messagebox.showinfo(
            "Example sequences",
            "Examples folder path copied to clipboard.",
            parent=root,
        )

    def _examples_browse_dialog() -> None:
        names = _list_example_json_names()
        if not names:
            messagebox.showinfo(
                "Example sequences",
                "No .json files found under:\n" + str(_examples_dir()),
                parent=root,
            )
            return
        dlg = tk.Toplevel(root)
        dlg.title("Example sequences")
        dlg.configure(bg=BG)
        dlg.transient(root)
        dlg.grab_set()
        _center(dlg, 520, 400)
        tk.Label(
            dlg,
            text="Shipped examples (automation/recordings/sequences/)",
            font=("Segoe UI", 11, "bold"),
            bg=BG,
            fg=T1,
        ).pack(anchor="w", padx=12, pady=(12, 4))
        tk.Label(
            dlg,
            text="Double-click or select OK to copy the file path.",
            font=("Segoe UI", 10),
            bg=BG,
            fg=T2,
        ).pack(anchor="w", padx=12, pady=(0, 8))
        box_fr = tk.Frame(dlg, bg=BG)
        box_fr.pack(fill="both", expand=True, padx=12, pady=4)
        box = tk.Listbox(
            box_fr,
            font=("Consolas", 10),
            bg="#121722",
            fg=T1,
            selectbackground=ACCENT,
            height=14,
            highlightthickness=0,
        )
        box_sb = themed_vertical_scrollbar(box_fr, command=box.yview)
        box.configure(yscrollcommand=box_sb.set)
        box.pack(side="left", fill="both", expand=True)
        box_sb.pack(side="right", fill="y")
        for n in names:
            box.insert("end", n)

        def _listbox_wheel(e: tk.Event) -> None:
            if e.num == 4:
                box.yview_scroll(-1, "units")
            elif e.num == 5:
                box.yview_scroll(1, "units")
            else:
                d = getattr(e, "delta", 0) or 0
                if d:
                    box.yview_scroll(int(-1 * (d / 120)), "units")

        box.bind("<MouseWheel>", _listbox_wheel)
        box.bind("<Button-4>", _listbox_wheel)
        box.bind("<Button-5>", _listbox_wheel)

        def copy_selected() -> None:
            sel = box.curselection()
            if not sel:
                messagebox.showwarning("Example sequences", "Select a file.", parent=dlg)
                return
            name = box.get(sel[0])
            path = str(_examples_dir() / name)
            root.clipboard_clear()
            root.clipboard_append(path)
            root.update_idletasks()
            messagebox.showinfo("Example sequences", f"Copied path:\n{path}", parent=dlg)

        box.bind("<Double-Button-1>", lambda e: copy_selected())

        btns = tk.Frame(dlg, bg=BG)
        btns.pack(fill="x", padx=12, pady=12)
        tk.Button(
            btns,
            text="Copy path",
            font=("Segoe UI", 10),
            bg=BG,
            fg=T1,
            relief="flat",
            command=copy_selected,
        ).pack(side="right", padx=(8, 0))
        tk.Button(
            btns,
            text="Close",
            font=("Segoe UI", 10),
            bg=BG,
            fg=T2,
            relief="flat",
            command=dlg.destroy,
        ).pack(side="right")

    def _humanize_sequence_dialog() -> None:
        from sequence_humanize import humanize_sequence_file

        inp = filedialog.askopenfilename(
            parent=root,
            title="Select sequence JSON to humanize",
            filetypes=[("JSON sequence", "*.json"), ("All files", "*.*")],
        )
        if not inp:
            return
        inp_p = Path(inp)
        suggested = inp_p.parent / f"{inp_p.stem}_humanized.json"
        out = filedialog.asksaveasfilename(
            parent=root,
            title="Save humanized sequence",
            defaultextension=".json",
            initialfile=suggested.name,
            initialdir=str(inp_p.parent),
            filetypes=[("JSON sequence", "*.json"), ("All files", "*.*")],
        )
        if not out:
            return
        try:
            stats = humanize_sequence_file(inp_p, Path(out), seed=None)
            messagebox.showinfo(
                "Humanize sequence",
                f"Steps: {stats['steps']}\n\nSaved to:\n{stats['output']}",
                parent=root,
            )
        except Exception as e:
            messagebox.showerror("Humanize sequence", str(e), parent=root)

    def _collect_configured_serials() -> list[str]:
        serials: list[str] = []
        for p in state.get("phones") or []:
            if isinstance(p, dict) and p.get("serial"):
                serials.append(str(p["serial"]))
        if serials:
            return serials
        seen: set[str] = set()
        out: list[str] = []
        for g in state.get("groups") or []:
            pmap = g.get("phones") if isinstance(g, dict) else None
            if not isinstance(pmap, dict):
                continue
            for s in pmap.keys():
                if s not in seen:
                    seen.add(str(s))
                    out.append(str(s))
        return out

    def _setup_tor_all_phones() -> None:
        """
        Apply distinct Tor SOCKS + Android global HTTP proxy per configured phone.

        Mirrors dashboard ``/api/proxy/setup`` (see automation/tor_manager.py). Requires adb
        access to each device and a Tor binary under automation/tor/ or C:\\Tor\\tor.exe.
        Writes ``desktop_prefs.json`` with ``tor_proxy_configured`` (not browser fingerprint stealth).
        """

        # Snapshot phones on the UI thread — ``state`` must not be read from worker threads.
        serials_main = _collect_configured_serials()

        def work() -> None:
            serials: list[str] = list(serials_main)
            warnings: list[str] = []
            try:
                if not serials:
                    root.after(
                        0,
                        lambda: messagebox.showwarning(
                            "Tor proxy",
                            "No phones in Setup yet. Add phones in the wizard, or define "
                            "groups with phone serials.",
                            parent=root,
                        ),
                    )
                    return

                root_dir = _pharmflow_install_root()
                auto = root_dir / "automation"
                if not (auto / "dashboard.py").is_file():
                    root.after(
                        0,
                        lambda: messagebox.showerror(
                            "Tor proxy",
                            f"automation/ not found at:\n{auto}",
                            parent=root,
                        ),
                    )
                    return
                ap = str(auto)
                if ap not in sys.path:
                    sys.path.insert(0, ap)
                import tor_manager

                pre = tor_manager.tor_proxy_preflight()
                if not pre.get("ok"):
                    root.after(
                        0,
                        lambda msg=pre.get("error", "Tor unavailable"): messagebox.showerror(
                            "Tor proxy",
                            msg,
                            parent=root,
                        ),
                    )
                    return

                tor_manager.clear_tor_slots()
                pinned: list[str] = []
                for i, serial in enumerate(serials):
                    idx = tor_manager.phone_idx_from_adb_serial(serial)
                    tor_manager.register_tor_slot(serial, idx)
                    try:
                        tor_manager.start_tor_for_phone(idx)
                    except (FileNotFoundError, RuntimeError) as e:
                        warnings.append(f"{serial}: Tor start failed — {e}")
                        continue
                    w_socks = tor_manager.tor_wait_socks_seconds()
                    w_http = tor_manager.tor_wait_http_seconds()
                    if not tor_manager.wait_for_tor(idx, timeout=w_socks):
                        warnings.append(
                            f"{serial}: SOCKS not ready within {w_socks}s (tor.exe crashed — check logs)"
                        )
                        continue
                    if not tor_manager.wait_for_tor_http_tunnel(idx, timeout=w_http):
                        warnings.append(
                            f"{serial}: HTTP tunnel not ready within {w_http}s "
                            f"(tune PHARMFLOW_TOR_WAIT_HTTP / install standalone tor)"
                        )
                        continue
                    applied = tor_manager.apply_identity_adb(serial, idx)
                    if tor_pin_landed(applied):
                        pinned.append(serial)
                    else:
                        warnings.append(f"{serial}: guest proxy was not set to a loopback exit")

                snap_pinned = list(pinned)
                snap_requested = len(serials)
                snap_root = root_dir

                def apply_tor_on_main() -> None:
                    if not snap_pinned:
                        messagebox.showerror(
                            "Tor proxy",
                            "No phone got a loopback exit.\n\n" + "\n".join(warnings),
                            parent=root,
                        )
                        return
                    state["tor_proxy_desired"] = True
                    d = (state.get("pharmflow_dir") or "").strip()
                    rec_root = Path(d) if d else Path(snap_root)
                    prefs = rec_root / "automation" / "recordings" / "desktop_prefs.json"
                    try:
                        merge_tor_desktop_prefs(prefs, snap_pinned)
                    except OSError as e:
                        messagebox.showerror(
                            "Tor proxy",
                            f"Could not save preferences:\n{e}",
                            parent=root,
                        )
                        return
                    msg_lines = [
                        f"Pinned a loopback exit on {len(snap_pinned)} of {snap_requested} phone(s).",
                        "Saved the Tor flag into automation/recordings/desktop_prefs.json "
                        "without replacing the rest of that file.",
                        "",
                        "Note: this is Tor routing only — not browser fingerprint spoofing.",
                    ]
                    if warnings:
                        msg_lines.append("")
                        msg_lines.append("Warnings:")
                        msg_lines.extend(warnings)
                    messagebox.showinfo("Tor proxy", "\n".join(msg_lines), parent=root)

                root.after(0, apply_tor_on_main)
            except Exception as e:
                root.after(
                    0,
                    lambda err=e: messagebox.showerror("Tor proxy", str(err), parent=root),
                )
                return

        threading.Thread(target=work, daemon=True).start()

    tools_m = tk.Menu(menubar, tearoff=0)
    ex_m = tk.Menu(tools_m, tearoff=0)
    ex_m.add_command(label="Open examples folder", command=_examples_open_folder)
    ex_m.add_command(label="Browse examples…", command=_examples_browse_dialog)
    ex_m.add_command(label="Copy examples folder path", command=_examples_copy_folder_path)
    tools_m.add_cascade(label="Examples", menu=ex_m)
    tools_m.add_separator()
    tools_m.add_command(label="Humanize sequence…", command=_humanize_sequence_dialog)
    tools_m.add_command(label="Set up Tor on all phones…", command=_setup_tor_all_phones)

    # — Cloud Phones submenu —
    cloud_m = tk.Menu(tools_m, tearoff=0)

    def _cloud_connect():
        """Open dialog to connect to cloud phone instances."""
        from tkinter import simpledialog
        host = simpledialog.askstring(
            "Cloud Phones",
            "Enter cloud instance IP (e.g. 100.x.x.x):",
            parent=root,
        )
        if not host:
            return
        count = simpledialog.askinteger(
            "Cloud Phones",
            "Number of instances:",
            minvalue=1,
            parent=root,
        )
        if not count:
            return
        _run_cloud_cmd("connect", host, count)

    def _cloud_stealth():
        """Apply stealth protocols to cloud instances."""
        from tkinter import simpledialog
        host = simpledialog.askstring(
            "Cloud Stealth",
            "Enter cloud instance IP:",
            parent=root,
        )
        if not host:
            return
        count = simpledialog.askinteger(
            "Cloud Stealth",
            "Number of instances:",
            minvalue=1,
            parent=root,
        )
        if not count:
            return
        _run_cloud_cmd("stealth", host, count)

    def _cloud_tor():
        """Set up Tor proxy on cloud instances."""
        from tkinter import simpledialog
        host = simpledialog.askstring(
            "Cloud Tor",
            "Enter cloud instance IP:",
            parent=root,
        )
        if not host:
            return
        count = simpledialog.askinteger(
            "Cloud Tor",
            "Number of instances:",
            minvalue=1,
            parent=root,
        )
        if not count:
            return
        _run_cloud_cmd("tor", host, count, verify=True)

    def _cloud_full_setup():
        """Run full cloud phone setup (connect + stealth + tor)."""
        from tkinter import simpledialog
        host = simpledialog.askstring(
            "Cloud Full Setup",
            "Enter cloud instance IP (e.g. 100.x.x.x):",
            parent=root,
        )
        if not host:
            return
        count = simpledialog.askinteger(
            "Cloud Full Setup",
            "Number of instances:",
            minvalue=1,
            parent=root,
        )
        if not count:
            return
        _run_cloud_cmd("setup", host, count)

    def _cloud_status():
        """Show status of connected cloud instances."""
        from tkinter import simpledialog
        host = simpledialog.askstring(
            "Cloud Status",
            "Enter cloud instance IP (or leave blank for all):",
            parent=root,
        )
        if host is None:
            return
        _run_cloud_cmd("status", host or "", 0)

    def _run_cloud_cmd(command: str, host: str, count: int, *, verify: bool = False) -> None:
        """Run a cloud_phones CLI command in a background thread."""
        if getattr(sys, "frozen", False):
            cloud_cli = Path(sys._MEIPASS) / "cloud_phones" / "cloud_phones_cli.py"  # type: ignore[attr-defined]
        else:
            cloud_cli = Path(__file__).resolve().parent.parent / "cloud_phones" / "cloud_phones_cli.py"
        if not cloud_cli.exists():
            messagebox.showerror(
                "Cloud Phones",
                f"CloudPhones module not found:\n{cloud_cli}\n\n"
                "Please ensure cloud_phones/ folder exists.",
                parent=root,
            )
            return

        if getattr(sys, "frozen", False):
            cmd = [sys.executable, "--cloud-phones-cli", command]
        else:
            cmd = [sys.executable, str(cloud_cli), command]
        if host:
            cmd += ["--host", host]
        if count > 0:
            cmd += ["--count", str(count)]
        if verify:
            cmd.append("--verify")

        def _work():
            try:
                run_kwargs = {
                    "capture_output": True,
                    "text": True,
                    "timeout": 120,
                }
                if sys.platform == "win32":
                    run_kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
                result = subprocess.run(cmd, **run_kwargs)
                output = result.stdout + result.stderr
                root.after(0, lambda: _show_cloud_output(command, output))
            except subprocess.TimeoutExpired:
                root.after(0, lambda: messagebox.showwarning(
                    "Cloud Phones",
                    f"{command} command timed out after 120s",
                    parent=root,
                ))
            except Exception as e:
                root.after(0, lambda: messagebox.showerror(
                    "Cloud Phones",
                    f"Error: {e}",
                    parent=root,
                ))

        threading.Thread(target=_work, daemon=True).start()

    def _show_cloud_output(command: str, output: str) -> None:
        """Show cloud command output in a dialog."""
        win = tk.Toplevel(root)
        win.title(f"Cloud Phones — {command}")
        win.geometry("600x400")
        win.configure(bg="#0a0e18")

        tk.Label(
            win,
            text=f"Cloud Phones: {command}",
            font=("Segoe UI", 14, "bold"),
            bg="#0a0e18",
            fg=T1,
        ).pack(pady=(12, 6))

        txt = tk.Text(
            win,
            bg="#111827",
            fg="#e5e7eb",
            font=("Consolas", 11),
            wrap="word",
            relief="flat",
            padx=8,
            pady=8,
        )
        txt.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        txt.insert("1.0", output)
        txt.config(state="disabled")

        style_primary_button(
            tk.Button(win, text="Close", command=win.destroy)
        ).pack(pady=(0, 12))

    cloud_m.add_command(label="Connect to Cloud Instances…", command=_cloud_connect)
    cloud_m.add_command(label="Apply Stealth to Cloud…", command=_cloud_stealth)
    cloud_m.add_command(label="Set Up Tor on Cloud…", command=_cloud_tor)
    cloud_m.add_separator()
    cloud_m.add_command(label="Full Setup (Connect + Stealth + Tor)…", command=_cloud_full_setup)
    cloud_m.add_command(label="View Cloud Status…", command=_cloud_status)
    tools_m.add_cascade(label="☁ Cloud Phones", menu=cloud_m)

    menubar.add_cascade(label="Tools", menu=tools_m)

    help_m = tk.Menu(menubar, tearoff=0)
    help_m.add_command(
        label="About PharmFlow",
        command=lambda: messagebox.showinfo(
            "About",
            "PharmFlow runs virtual phones from your PC.\n\n"
            "Home = big buttons.\n"
            "Setup = step-by-step guide.\n"
            "Launch = start the helper, then open the dashboard.\n\n"
            "Cloud Phones: Tools menu for cloud Android instances.",
            parent=root,
        ),
    )
    root.config(menu=menubar)
    root.protocol("WM_DELETE_WINDOW", _quit_pharmflow)

    # Do not clear guest http_proxy or stop Tor when this window closes.
    # That drops farm traffic onto the host IP and kills the money exit.

    def _open_folder_from_state() -> None:
        d = (state.get("pharmflow_dir") or "").strip()
        if not d:
            d = str(_pharmflow_install_root())
        _open_explorer_folder(d, parent=root)

    def _go_wizard_view(view: str, wizard_page: int | None = None) -> None:
        """Stay in this window — embedded PharmFlowWizard (reliable Tk)."""
        show_setup()
        if wizard_page is not None and 0 <= wizard_page < len(wizard._pages):
            wizard._show(wizard_page)

    # — Body: swap Home vs Setup (no ttk.Notebook — consistent dark Tk look) —
    body = tk.Frame(root, bg=BG)
    body.pack(fill="both", expand=True)

    home_fr = tk.Frame(body, bg=BG)
    setup_fr = tk.Frame(body, bg=BG)

    def show_home() -> None:
        setup_fr.pack_forget()
        home_fr.pack(fill="both", expand=True)

    def show_setup() -> None:
        home_fr.pack_forget()
        setup_fr.pack(fill="both", expand=True)

    # — Home (simple numbered path) —
    hero = tk.Frame(home_fr, bg=BG)
    hero.pack(fill="both", expand=True, padx=48, pady=36)
    tk.Label(
        hero,
        text="PharmFlow",
        font=("Segoe UI", 28, "bold"),
        bg=BG,
        fg=T1,
        anchor="w",
    ).pack(fill="x", pady=(0, 4))
    tk.Label(
        hero,
        text="Nine-step setup: install tools, configure phones, run automation.",
        font=("Segoe UI", 16),
        bg=BG,
        fg=T2,
        justify="left",
        anchor="w",
    ).pack(fill="x", pady=(0, 20))

    row = tk.Frame(hero, bg=BG)
    row.pack(fill="x", pady=8)

    b_phone = tk.Button(
        row,
        text="  ★ Phone Setup — MuMu (Chromium on phones, hide emulator)  ",
        font=("Segoe UI", 14, "bold"),
        cursor="hand2",
        command=_launch_phone_setup_subprocess,
        padx=20,
        pady=12,
        bd=0,
    )
    style_success_button(b_phone)
    b_phone.pack(fill="x", pady=(0, 14))

    tk.Label(
        hero,
        text="MuMu farms: run Phone Setup (step 4 or green button), then continue with Test → Run.",
        font=("Segoe UI", 11),
        bg=BG,
        fg=T2,
        anchor="w",
    ).pack(fill="x", pady=(0, 10))

    row2 = tk.Frame(hero, bg=BG)
    row2.pack(fill="x", pady=4)

    _HOME_STEPS = [
        ("Start", "start", 0),
        ("Install", "install", 1),
        ("Android", "android", 2),
        ("Phone setup (MuMu)", "mumu-setup", None),
        ("Test site", "boot", 4),
        ("Steps", "steps", 5),
        ("Builder", "builder", 6),
        ("Teams", "teams", 7),
        ("Run", "go", 8),
    ]
    for i, (label, view, page) in enumerate(_HOME_STEPS):
        if view == "mumu-setup":
            cmd = _launch_phone_setup_subprocess
        else:
            cmd = lambda v=view, p=page: _go_wizard_view(v, p)
        btn = tk.Button(
            row2,
            text=f"  {i + 1}. {label}  ",
            font=("Segoe UI", 14, "bold"),
            cursor="hand2",
            command=cmd,
            padx=20,
            pady=10,
            bd=0,
        )
        if view == "mumu-setup":
            style_success_button(btn)
        elif view == "go":
            style_success_button(btn)
        elif view == "install":
            style_primary_button(btn)
        else:
            style_secondary_button(btn)
        btn.pack(fill="x", pady=(0, 6))

    b3 = tk.Button(
        row2,
        text="  Open control dashboard  ",
        font=("Segoe UI", 13),
        cursor="hand2",
        command=lambda: _try_open_dashboard(root),
        padx=24,
        pady=14,
        bd=0,
    )
    style_secondary_button(b3)
    b3.pack(fill="x", pady=(12, 0))

    avd_row = tk.Frame(hero, bg=BG)
    avd_row.pack(fill="x", pady=(14, 0))
    tk.Label(
        avd_row,
        text="Google AVD users (not MuMu):",
        font=("Segoe UI", 10),
        bg=BG,
        fg=T3,
        anchor="w",
    ).pack(side="left")
    b_avd = tk.Button(
        avd_row,
        text="Create AVD phone farm",
        font=("Segoe UI", 10),
        cursor="hand2",
        command=lambda: _go_wizard_view("phones", 3),
        padx=10,
        pady=4,
        bd=0,
    )
    style_secondary_button(b_avd)
    b_avd.pack(side="left", padx=(8, 0))

    hint = (
        "1 Start → 2 Install → 3 Android → 4 Phones (hide emulator) → 5 Test\n"
        "6 Steps → 7 Builder (optional) → 8 Teams → 9 Run"
    )
    tk.Label(
        hero,
        text=hint,
        font=("Segoe UI", 10),
        bg=BG,
        fg=T3,
        wraplength=880,
        justify="left",
        anchor="w",
    ).pack(fill="x", pady=(24, 0))

    # — Embedded wizard —
    def on_wizard_finish() -> None:
        show_home()
        messagebox.showinfo(
            "Wizard closed",
            "The setup pages were closed.\n\n"
            "Nothing was started from this button.\n"
            "Open Run and start the service if you want phones working.",
            parent=root,
        )

    wizard = PharmFlowWizard(setup_fr, on_finish=on_wizard_finish)
    wizard.pack(fill="both", expand=True)

    show_home()
    if initial_view in ("setup", "phones"):
        root.after(100, show_setup)
    root.after(500, _kick_tor_warm_early)
    root.mainloop()


def run_internal_tk_page(page_index: int, *, action: str | None = None) -> None:
    """Standalone Tk window for one wizard page (``--internal-tk-page``)."""
    import traceback

    from setup_wizard import BG, PharmFlowWizard, _persist_groups_config, _try_load_groups_config
    from wizard_theme import _style_scrollbars, accent_top_strip

    idx = max(0, min(int(page_index), 8))
    root = tk.Tk()
    root.title(instance_title("Wizard"))
    root.geometry("1120x920")
    root.minsize(940, 760)
    root.configure(bg=BG)
    _style_scrollbars(root)
    accent_top_strip(root).pack(fill="x")

    body = tk.Frame(root, bg=BG)
    body.pack(fill="both", expand=True)
    wiz = PharmFlowWizard(body)
    wiz.pack(fill="both", expand=True)
    _try_load_groups_config()
    wiz._show(idx)

    def run_action() -> None:
        try:
            page = wiz._pages[idx]
            if hasattr(page, "on_enter"):
                page.on_enter()
            act = (action or "").strip().lower()
            if act == "edit_sequence" and idx == 5 and hasattr(page, "_edit_sequence"):
                page._edit_sequence()
            elif act == "install_all" and hasattr(page, "_install_all"):
                page._install_all()
            elif act == "android_install" and hasattr(page, "_auto_install"):
                page._auto_install()
            elif act == "create_phones" and hasattr(page, "_create"):
                page._create()
            elif act == "start_server" and hasattr(page, "_start_server"):
                page._start_server()
            elif act == "start_server_and_open_dashboard" and hasattr(page, "_start_server"):
                page._start_server()
                if hasattr(page, "_open_dashboard_browser"):
                    root.after(400, lambda: page._open_dashboard_browser("/"))
            elif act == "run_groups" and hasattr(page, "_run_groups"):
                page._start_server()
                if hasattr(page, "_wait_dashboard_reachable"):
                    page._wait_dashboard_reachable(120)
                page._run_groups()
            elif act == "start_automation" and hasattr(page, "_start_automation_one_click"):
                page._start_server()
                if hasattr(page, "_wait_dashboard_reachable"):
                    page._wait_dashboard_reachable(120)
                page._start_automation_one_click()
            elif act == "add_group" and hasattr(page, "_add_group"):
                page._add_group()
                _persist_groups_config()
            elif act == "humanize" and hasattr(page, "_humanize_all_sequences"):
                page._humanize_all_sequences()
                _persist_groups_config()
        except Exception as exc:
            traceback.print_exc()
            messagebox.showerror("PharmFlow", f"Action failed:\n{exc}", parent=root)

    def on_close() -> None:
        try:
            _persist_groups_config()
        except Exception:
            pass
        root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)

    if action:
        root.after(450, run_action)

    root.deiconify()
    root.lift()
    try:
        root.update_idletasks()
    except tk.TclError:
        pass
    _mark_internal_tk_ready()

    root.mainloop()


def _mark_internal_tk_ready() -> None:
    """Tell the Control Panel the Tk window exists. Popen is not that proof."""
    path = os.environ.get("PHARMFLOW_TK_READY_FILE", "").strip()
    if not path:
        return
    try:
        Path(path).write_text("ready\n", encoding="utf-8")
    except OSError:
        pass


def _use_classic_tk_shell() -> bool:
    """Old Tk home — only when explicitly requested."""
    if os.environ.get("PHARMFLOW_TK", "").strip().lower() in ("1", "true", "yes", "on"):
        return True
    return "--tk" in sys.argv or "--classic" in sys.argv


def _launch_phone_setup_subprocess() -> None:
    """Open the phone-setup window. Do not hide it.

    CREATE_NO_WINDOW plus DETACHED_PROCESS sets SW_HIDE, so the operator
    clicks Phone Setup and nothing appears.
    """
    if getattr(sys, "frozen", False):
        cmd = [sys.executable, "--phone-setup"]
    else:
        entry = Path(__file__).resolve()
        py = Path(sys.executable)
        if py.name.lower() == "python.exe":
            pyw = py.with_name("pythonw.exe")
            if pyw.is_file():
                py = pyw
        cmd = [str(py), str(entry), "--phone-setup"]
    popen_kwargs: dict = {"close_fds": False}
    if sys.platform == "win32":
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 1  # SW_SHOWNORMAL
        popen_kwargs["startupinfo"] = si
    subprocess.Popen(cmd, **popen_kwargs)


def _combined_tool_path(rel: str) -> str:
    """Resolve a tools/*.py script inside the frozen bundle or the source tree."""
    if getattr(sys, "frozen", False):
        return str(Path(sys._MEIPASS) / rel)  # type: ignore[attr-defined]
    return str(Path(__file__).resolve().parent.parent / rel)


def _bootlog(msg: str) -> None:
    """Frozen-only marker log to locate where a windowed startup fails."""
    if not getattr(sys, "frozen", False):
        return
    try:
        import tempfile
        import traceback as _tb
        import time as _time

        with open(os.path.join(tempfile.gettempdir(), "pharmflow_boot.log"), "a", encoding="utf-8") as _f:
            _f.write(f"[{_time.strftime('%H:%M:%S')}] {msg}\n")
    except Exception:
        pass


def _in_cli_mode() -> bool:
    """True when argv routes to a CLI mode instead of the GUI window.

    ``--start-farm`` / ``--stop-farm`` must be included. A windowed EXE starts
    with ``sys.stdout is None``; if those flags are treated as GUI, the first
    ``_ensure_console`` swallows output to ``os.devnull`` and the farm CLI looks
    hung even when it is working.
    """
    return any(
        flag in sys.argv
        for flag in (
            "--version",
            "--agent",
            "--watchdog",
            "--cloud-phones-cli",
            "--cloud-agent",
            "--internal-tk-page",
            "--start-farm",
            "--stop-farm",
        )
    )


def _ensure_console() -> None:
    """Give the frozen windowed EXE a usable stdout.

    PyInstaller ``console=False`` builds start with ``sys.stdout is None`` and
    argparse ``--help``/``--version`` would crash on ``None.write``. In CLI
    mode we attach to the parent console so output + exit codes behave; in GUI
    mode we never attach (attaching a windowed GUI process to the parent console
    destabilises the app) and instead point stdout/stderr at ``os.devnull`` so
    stray prints can't crash the UI thread. Headless watchdog runs keep their
    own log redirects either way.
    """
    if sys.stdout is not None:
        return
    cli = _in_cli_mode()
    if cli and sys.platform == "win32":
        try:
            import ctypes

            kernel32 = ctypes.windll.kernel32
            ATTACH_PARENT_PROCESS = -1
            if kernel32.AttachConsole(ATTACH_PARENT_PROCESS):
                sys.stdout = open("CONOUT$", "w", encoding="utf-8", errors="replace")
                sys.stderr = open("CONOUT$", "w", encoding="utf-8", errors="replace")
                return
        except Exception:
            pass
    import os as _os

    sys.stdout = open(_os.devnull, "w", encoding="utf-8", errors="replace")
    if sys.stderr is None:
        sys.stderr = open(_os.devnull, "w", encoding="utf-8", errors="replace")


def _exec_tool_module(script: str, target: list[str]) -> int:
    """Execute a bundled tools/*.py in-process (frozen onefile world)."""
    import importlib.util

    _ensure_console()
    spec = importlib.util.spec_from_file_location("_pharmflow_combined_tool", script)
    if spec is None or spec.loader is None:
        print(f"Combined tool not loadable: {script}", file=sys.stderr)
        return 1
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception as exc:  # noqa: BLE001 - report and fail loudly
        print(f"Combined tool import failed ({script}): {exc}", file=sys.stderr)
        return 1
    if not callable(getattr(mod, "main", None)):
        return 0
    old_argv = list(sys.argv)
    sys.argv = [script, *target]
    try:
        rc = mod.main()
        return int(rc) if rc is not None else 0
    except SystemExit as exc:  # argparse --help/--version exits via SystemExit
        code = exc.code
        if code is None:
            return 0
        return int(code) if isinstance(code, int) else 1
    finally:
        sys.argv = old_argv


def run_combined_tool(flag: str, rel: str) -> int | None:
    """If ``flag`` is in argv, run the bundled tool and return its exit code;
    otherwise return None (not in combined mode).

    From source, the tool script is spawned with the current interpreter so the
    GUI stays windowed. Frozen, there is no interpreter to spawn a bare ``.py``
    with, so the bundled script (``_MEIPASS/tools/*.py``) is executed
    in-process instead — same module, same argparse behaviour."""
    if flag not in sys.argv:
        return None
    script = _combined_tool_path(rel)
    argv = list(sys.argv)
    i = argv.index(flag)
    target = [*argv[i + 1:]]
    if getattr(sys, "frozen", False):
        return _exec_tool_module(script, target)
    cmd = [sys.executable, script, *target]
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    try:
        proc = subprocess.run(cmd, creationflags=flags)
    except FileNotFoundError:
        print(f"Combined tool not found: {script}", file=sys.stderr)
        return 1
    return proc.returncode


def _farm_cli_mode() -> bool:
    """True when argv routes to the headless Start farm / Stop farm contract."""
    return "--start-farm" in sys.argv or "--stop-farm" in sys.argv


def _owner_pid_alive(pid: int) -> bool:
    if pid <= 0 or pid == os.getpid():
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _nested_start_farm_child() -> bool:
    """True when this process is a helper that re-exec'd PharmFlow.exe --start-farm.

    The owner sets PHARMFLOW_START_FARM_OWNER before spawning. A child that inherits
    it must exit immediately — entering run_farm_cli again hangs in a second loop
    and never returns the farm to the operator.
    """
    if "--start-farm" not in sys.argv:
        return False
    owner = (os.environ.get("PHARMFLOW_START_FARM_OWNER") or "").strip()
    if not owner:
        return False
    try:
        owner_pid = int(owner)
    except ValueError:
        return False
    return _owner_pid_alive(owner_pid)


def run_farm_cli() -> int:
    """Start or stop the unison money farm from the EXE itself.

    Mirrors the GUI Start farm button (``pharmflow_wizard_bridge.start_farm_from_app``)
    so the EXE — not a python recipe — owns the money path. ``--start-farm`` is
    long-running: it keeps the process alive while the farm runs and exits 0 when
    the farm stops (Ctrl-C / Stop farm / Stop-Process all work).
    """
    import time

    from wizard.farm_control import (
        farm_running as _fr,
        load_active_profile as _load_profile,
        start_farm as _sf,
        stop_farm as _stop,
    )

    _ensure_console()
    if "--stop-farm" in sys.argv:
        stopped = _stop()
        print("Farm stopped" if stopped else "Farm was not running")
        return 0
    if _fr():
        print("Farm already running — dashboard http://127.0.0.1:8091/")
        return 0
    ok = _sf(profile=_load_profile(None), hours=None, takeover=True)
    if not ok and _fr():
        # start_farm returns False when unison is already up. That is not a
        # failed arm — the stale-log path used to take this branch by mistake.
        print("Farm already running — dashboard http://127.0.0.1:8091/")
        return 0
    if not ok:
        print("Start farm refused (see farm log)", file=sys.stderr)
        return 1
    print("Farm started — dashboard http://127.0.0.1:8091/")
    try:
        while True:
            time.sleep(5)
            if not _fr():
                print("Farm stopped")
                return 0
    except KeyboardInterrupt:
        return 0
    finally:
        _bootlog("farm-cli: exit")


def main() -> None:
    _bootlog("main: start")
    if _nested_start_farm_child():
        _ensure_console()
        _bootlog("main: nested --start-farm ignored")
        print("Farm already running — nested --start-farm ignored")
        return
    if "--start-farm" in sys.argv:
        os.environ["PHARMFLOW_START_FARM_OWNER"] = str(os.getpid())
    _ensure_console()
    if "--version" in sys.argv:
        import pharmflow_version as ver
        print(ver.display_version())
        return
    _bootlog("main: version/combined checks done")

    # Combined-mode entrypoints: one PharmFlow.exe is the Control Panel,
    # the project agent, the cloud agent, and the watchdog.
    agent_mode = run_combined_tool("--agent", "tools/project_agent.py")
    if agent_mode is not None:
        raise SystemExit(agent_mode)
    cloud_agent_mode = run_combined_tool("--cloud-agent", "tools/cloud_agent.py")
    if cloud_agent_mode is not None:
        raise SystemExit(cloud_agent_mode)
    watchdog_mode = run_combined_tool("--watchdog", "tools/pharmflow_watchdog.py")
    if watchdog_mode is not None:
        raise SystemExit(watchdog_mode)

    if _farm_cli_mode():
        _bootlog("main: farm cli mode")
        raise SystemExit(run_farm_cli())

    if "--cloud-phones-cli" in sys.argv:
        from cloud_phones.cloud_phones_cli import main as cloud_main
        argv = list(sys.argv)
        i = argv.index("--cloud-phones-cli")
        sys.argv = [argv[0], *argv[i + 1:]]
        raise SystemExit(cloud_main())

    if "--internal-tk-page" in sys.argv:
        i = sys.argv.index("--internal-tk-page")
        idx = int(sys.argv[i + 1]) if i + 1 < len(sys.argv) else 0
        act = None
        if "--internal-tk-action" in sys.argv:
            j = sys.argv.index("--internal-tk-action")
            if j + 1 < len(sys.argv):
                act = sys.argv[j + 1]
        run_internal_tk_page(idx, action=act)
        return

    from phone_setup_entry import is_phone_setup_mode

    if is_phone_setup_mode():
        from phone_setup_entry import phone_setup_main

        phone_setup_main()
        return

    if _use_classic_tk_shell():
        _kick_tor_warm_early()
        run_main_window()
        return

    _bootlog("main: webview branch")
    _kick_tor_warm_early()
    _bootlog("main: tor warm done")
    try:
        from pharmflow_app_webview import run_pharmflow_app_or_fallback

        _bootlog("main: webview module imported")
        run_pharmflow_app_or_fallback()
        _bootlog("main: webview returned cleanly")
    except SystemExit:
        _bootlog("main: SystemExit from webview")
        raise
    except BaseException:
        import traceback as _tb

        _bootlog("main: webview EXCEPTION:\n" + _tb.format_exc())
        raise


if __name__ == "__main__":
    main()
