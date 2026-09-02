"""Hidden tk backend — reuses setup_wizard pages for WebView UI actions."""
from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from typing import Any, Callable

from setup_wizard import CPharmWizard
from wizard_theme import _style_scrollbars

# Mirrors CPharmWizard.PAGE_NAMES / PAGE_SUBTITLES (order matters).
# Nine steps in four parts — sidebar shows phase headers; ids are stable for code.
WIZARD_STEPS: list[dict[str, Any]] = [
    {
        "index": 0,
        "id": "start",
        "name": "Start",
        "phase": "Part 1 — Prepare this PC",
        "subtitle": "What you will do",
        "hint": "Read the roadmap, then work steps 1→9 in order.",
    },
    {
        "index": 1,
        "id": "install",
        "name": "Install",
        "phase": "Part 1 — Prepare this PC",
        "subtitle": "Java, Python, Tor, files",
        "hint": "Install everything this PC needs to run phones.",
    },
    {
        "index": 2,
        "id": "android",
        "name": "Android",
        "phase": "Part 1 — Prepare this PC",
        "subtitle": "MuMu or Google SDK",
        "hint": "MuMu on ARM PCs; SDK only if you use Google AVDs.",
    },
    {
        "index": 3,
        "id": "phones",
        "name": "Phones",
        "phase": "Part 2 — Make phones real",
        "subtitle": "Connect, hide emulator look",
        "hint": "Checklist + Set up my phones: Chromium, fingerprint, ad zones.",
    },
    {
        "index": 4,
        "id": "boot",
        "name": "Test",
        "phase": "Part 3 — Check & configure",
        "subtitle": "Open your site on phones",
        "hint": "Confirm the site and ads load before you automate.",
    },
    {
        "index": 5,
        "id": "steps",
        "name": "Steps",
        "phase": "Part 3 — Check & configure",
        "subtitle": "Default tap list",
        "hint": "Usually already set in Phones — edit only if needed.",
    },
    {
        "index": 6,
        "id": "builder",
        "name": "Builder",
        "phase": "Part 3 — Check & configure",
        "subtitle": "Custom sequences (optional)",
        "hint": "Skip if shipped defaults are fine.",
    },
    {
        "index": 7,
        "id": "teams",
        "name": "Groups",
        "phase": "Part 3 — Check & configure",
        "subtitle": "Assign phones to groups",
        "hint": "Assign playlists and runs per day.",
    },
    {
        "index": 8,
        "id": "go",
        "name": "Run",
        "phase": "Part 4 — Automate",
        "subtitle": "Start service + sequences",
        "hint": "Start service, then run all groups.",
    },
]

_STEP_ID_TO_INDEX = {s["id"]: s["index"] for s in WIZARD_STEPS}

_webview_window: Any = None
_webview_hide_depth = 0


def register_webview_window(window: Any) -> None:
    """Called from cpharm_app_webview so tk sub-windows can sit above WebView2."""
    global _webview_window
    _webview_window = window


def _webview_native_hwnd() -> int | None:
    if _webview_window is None:
        return None
    try:
        native = getattr(_webview_window, "native", None)
        if native is None:
            return None
        handle = getattr(native, "Handle", None)
        if handle is not None:
            if hasattr(handle, "ToInt32"):
                return int(handle.ToInt32())
            return int(handle)
        if isinstance(native, int):
            return native
    except Exception:
        pass
    return None


def _hide_webview_for_tk() -> None:
    global _webview_hide_depth
    _webview_hide_depth += 1
    if _webview_hide_depth != 1 or _webview_window is None:
        return
    if sys.platform == "win32":
        hwnd = _webview_native_hwnd()
        if hwnd:
            try:
                import ctypes

                ctypes.windll.user32.ShowWindow(hwnd, 0)
                return
            except Exception:
                pass
    for meth in ("hide", "minimize"):
        try:
            getattr(_webview_window, meth)()
            return
        except Exception:
            continue


def _restore_webview_from_tk() -> None:
    global _webview_hide_depth
    _webview_hide_depth = max(0, _webview_hide_depth - 1)
    if _webview_hide_depth != 0 or _webview_window is None:
        return
    if sys.platform == "win32":
        hwnd = _webview_native_hwnd()
        if hwnd:
            try:
                import ctypes

                ctypes.windll.user32.ShowWindow(hwnd, 5)
            except Exception:
                pass
    for meth in ("show", "restore"):
        try:
            getattr(_webview_window, meth)()
        except Exception:
            continue


_tk_root: tk.Tk | None = None
_wizard: Any = None
_ready = threading.Event()
_boot_error: str | None = None
_call_queue: queue.Queue = queue.Queue()
_log_callbacks: list[Callable[[str, str], None]] = []
_page_windows: dict[int, Any] = {}
_lift_pump_active = False


def _force_foreground_win(hwnd: int) -> None:
    if sys.platform != "win32" or not hwnd:
        return
    try:
        import ctypes

        user32 = ctypes.windll.user32
        SW_RESTORE = 9
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.keybd_event(0x12, 0, 0, 0)
        user32.keybd_event(0x12, 0, 2, 0)
        user32.SetForegroundWindow(hwnd)
    except Exception:
        pass


def _promote_tk_window(win: Any) -> None:
    try:
        win.deiconify()
        win.state("normal")
        win.lift()
        win.attributes("-topmost", True)
        win.update_idletasks()
        _force_foreground_win(int(win.winfo_id()))
        win.focus_force()
        win.after(800, lambda: win.attributes("-topmost", False))
        win.after(900, lambda: _force_foreground_win(int(win.winfo_id())))
    except Exception:
        pass


def _promote_all_toplevels() -> None:
    root = _tk_root
    if not root:
        return
    stack: list[Any] = [root]
    while stack:
        w = stack.pop()
        try:
            for c in w.winfo_children():
                stack.append(c)
                if c.winfo_class() == "Toplevel":
                    _promote_tk_window(c)
        except Exception:
            pass


def _minimize_webview() -> None:
    """Deprecated — minimizing WebView hid tk dialogs on Windows."""
    return


def _restore_webview() -> None:
    return


def _dialog_lift_pump(ticks: int = 0) -> None:
    global _lift_pump_active
    if not _tk_root:
        return
    if ticks == 0:
        _lift_pump_active = True
    if not _lift_pump_active or ticks > 120:
        _lift_pump_active = False
        return
    _promote_all_toplevels()
    _tk_root.after(100, lambda: _dialog_lift_pump(ticks + 1))


_dialog_parent: Any = None
_classic_wizard_windows: list[Any] = []


def _spawn_wizard_page(page_index: int, *, action: str | None = None) -> dict:
    """Open a wizard page in a SEPARATE process (reliable with the WebView shell).

    In-process Tk Toplevels created from the WebView process can render behind the
    WebView2 window on Windows and look like "nothing happened". A separate process
    gets its own top-level window that Windows always raises above the shell — the
    same pattern already proven by Phone Setup.
    """
    from wizard_tk_spawn import spawn_wizard_page as _spawn

    return _spawn(page_index, action=action)


def _spawn_with_visible_fallback(
    page_index: int,
    *,
    action: str | None = None,
    fallback: Callable[[], Any],
    success_augment: dict | None = None,
) -> dict:
    """Spawn a wizard page in a separate process and never hide a spawn failure.

    Returns the subprocess result when the spawn succeeds. If the spawn fails,
    runs ``fallback()`` (the in-process window) and returns its dict WITH an
    added ``error`` message carrying the original spawn failure, so the WebView
    shows a visible error banner instead of failing silently.
    """
    spawned = _spawn_wizard_page(page_index, action=action)
    if spawned.get("ok"):
        out = dict(spawned)
        if success_augment:
            out.update(success_augment)
        return out

    spawn_error = spawned.get("error") or "separate window launch failed"
    try:
        result = fallback() or {}
    except Exception as exc:
        result = {"ok": False, "error": f"in-process window also failed: {exc}"}
    if not isinstance(result, dict):
        result = {"ok": True, "detail": str(result)}
    result.setdefault("ok", True)
    existing = str(result.get("error") or "").strip()
    result["error"] = (existing + " " if existing else "") + f"Spawn failed: {spawn_error}"
    return result


def open_classic_wizard(step_id: str = "steps", *, auto_action: str | None = None) -> dict:
    """Open a visible editor window on the tk bridge thread (must not spawn a second Tk())."""
    step_id = str(step_id or "steps").strip().lower()
    idx = _STEP_ID_TO_INDEX.get(step_id, 0)

    def work() -> dict:
        from setup_wizard import BG, CPharmWizard
        from wizard_theme import _style_scrollbars

        existing = [w for w in _classic_wizard_windows if _window_exists(w)]
        _classic_wizard_windows[:] = existing
        if existing:
            win = existing[-1]
            try:
                host = win.winfo_children()[0] if win.winfo_children() else None
                wiz_host = host.winfo_children()[0] if host and host.winfo_children() else None
                if wiz_host and hasattr(wiz_host, "_show"):
                    wiz_host._show(idx)
                _show_tk_window(win)
                if wiz_host and auto_action == "edit_sequence" and idx == 5:
                    page = wiz_host._pages[5]
                    win.after(250, page._edit_sequence)
                elif wiz_host and auto_action == "add_group" and idx == 7:
                    win.after(250, lambda: wiz_host._pages[7]._add_group())
                elif wiz_host and auto_action == "humanize" and idx == 7:
                    win.after(250, lambda: wiz_host._pages[7]._humanize_all_sequences())
                elif wiz_host and auto_action == "start_server" and idx == 8:
                    win.after(250, lambda: wiz_host._pages[8]._start_server())
                elif wiz_host and auto_action == "run_groups" and idx == 8:
                    win.after(250, lambda: wiz_host._pages[8]._run_groups())
                elif wiz_host and auto_action == "start_automation" and idx == 8:
                    win.after(250, lambda: wiz_host._pages[8]._start_automation_one_click())
                return {"ok": True, "reused": True, "mode": "classic", "step": step_id}
            except Exception as exc:
                return {"ok": False, "error": f"Could not reuse {title} window: {exc}"}

        assert _tk_root is not None
        from cpharm_version import instance_title
        win = tk.Toplevel(_tk_dialog_parent())
        win.title(instance_title("Wizard"))
        win.geometry("1120x960")
        win.minsize(960, 780)
        win.config(bg=BG)
        _style_scrollbars(win)
        try:
            sw = win.winfo_screenwidth()
            sh = win.winfo_screenheight()
            win.geometry(f"1120x960+{max(0, (sw - 1120) // 2)}+{max(0, (sh - 960) // 2)}")
        except Exception:
            pass

        host = tk.Frame(win, bg=BG)
        host.pack(fill="both", expand=True)
        wiz = CPharmWizard(host)
        wiz.pack(fill="both", expand=True)
        wiz._show(idx)
        _classic_wizard_windows.append(win)

        def on_close() -> None:
            try:
                if win in _classic_wizard_windows:
                    _classic_wizard_windows.remove(win)
            except ValueError:
                pass
            try:
                win.destroy()
            except Exception:
                pass
            _restore_webview_from_tk()

        win.protocol("WM_DELETE_WINDOW", on_close)

        if auto_action == "edit_sequence" and idx == 5:

            def open_editor() -> None:
                try:
                    page = wiz._pages[5]
                    if hasattr(page, "on_enter"):
                        page.on_enter()
                    if hasattr(page, "_edit_sequence"):
                        page._edit_sequence()
                except Exception:
                    pass

            win.after(300, open_editor)
        elif auto_action == "add_group" and idx == 7:

            def add_group() -> None:
                try:
                    page = wiz._pages[7]
                    if hasattr(page, "on_enter"):
                        page.on_enter()
                    if hasattr(page, "_add_group"):
                        page._add_group()
                except Exception:
                    pass

            win.after(300, add_group)
        elif auto_action == "humanize" and idx == 7:

            def humanize() -> None:
                try:
                    page = wiz._pages[7]
                    if hasattr(page, "on_enter"):
                        page.on_enter()
                    if hasattr(page, "_humanize_all_sequences"):
                        page._humanize_all_sequences()
                except Exception:
                    pass

            win.after(300, humanize)
        elif auto_action == "start_server" and idx == 8:

            def start_srv() -> None:
                try:
                    page = wiz._pages[8]
                    if hasattr(page, "on_enter"):
                        page.on_enter()
                    if hasattr(page, "_start_server"):
                        page._start_server()
                except Exception:
                    pass

            win.after(300, start_srv)
        elif auto_action == "run_groups" and idx == 8:

            def run_grp() -> None:
                try:
                    page = wiz._pages[8]
                    if hasattr(page, "on_enter"):
                        page.on_enter()
                    if hasattr(page, "_run_groups"):
                        page._run_groups()
                except Exception:
                    pass

            win.after(300, run_grp)
        elif auto_action == "start_automation" and idx == 8:

            def start_auto() -> None:
                try:
                    page = wiz._pages[8]
                    if hasattr(page, "on_enter"):
                        page.on_enter()
                    if hasattr(page, "_start_automation_one_click"):
                        page._start_automation_one_click()
                except Exception:
                    pass

            win.after(300, start_auto)

        _show_tk_window(win)
        return {"ok": True, "mode": "classic", "step": step_id}

    return _run_on_tk(work)


def _window_exists(win: Any) -> bool:
    try:
        return bool(win.winfo_exists())
    except Exception:
        return False


def _tk_dialog_parent() -> Any:
    """On-screen host for modal dialogs (hidden/off-screen parents break Windows file pickers)."""
    global _dialog_parent
    _ensure_tk_thread()
    assert _tk_root is not None
    if _dialog_parent is not None:
        try:
            if _dialog_parent.winfo_exists():
                return _dialog_parent
        except tk.TclError:
            _dialog_parent = None
    parent = tk.Toplevel(_tk_root)
    try:
        from cpharm_version import instance_title
        parent.title(instance_title("CPharm"))
    except Exception:
        parent.title("CPharm")
    try:
        sw = parent.winfo_screenwidth()
        sh = parent.winfo_screenheight()
        parent.geometry(f"1x1+{max(0, sw - 2)}+{max(0, sh - 2)}")
    except Exception:
        parent.geometry("1x1+0+0")
    parent.deiconify()
    parent.update_idletasks()
    _dialog_parent = parent
    return parent


def _show_tk_window(win: Any) -> None:
    """Raise tk dialogs above WebView — do not hide/minimize WebView (breaks focus)."""
    _promote_tk_window(win)
    _dialog_lift_pump()


def _groups_detail_from_state() -> dict:
    from setup_wizard import state

    connected = {
        (p.get("serial") or "").strip()
        for p in (state.get("phones") or [])
        if isinstance(p, dict) and (p.get("serial") or "").strip()
    }
    groups_out: list[dict] = []
    for g in state.get("groups") or []:
        if not isinstance(g, dict):
            continue
        pmap = g.get("phones") or {}
        if not isinstance(pmap, dict):
            pmap = {}
        active = sum(1 for s in pmap if s in connected)
        groups_out.append(
            {
                "name": g.get("name") or "Group",
                "phone_count": active,
                "configured_count": len(pmap),
            }
        )
    return {
        "connected_phones": len(connected),
        "group_count": len(groups_out),
        "phone_count": sum(x["phone_count"] for x in groups_out),
        "groups": groups_out,
    }


def _window_page(win: Any) -> Any:
    try:
        return getattr(win, "_cpharm_page", None)
    except Exception:
        return None


def _fit_subwindow(win: Any, width: int, height: int) -> None:
    try:
        sw = int(win.winfo_screenwidth())
        sh = int(win.winfo_screenheight())
        w = max(980, min(int(width), sw - 90))
        h = max(760, min(int(height), sh - 90))
        x = max(0, (sw - w) // 2)
        y = max(0, (sh - h) // 2)
        win.geometry(f"{w}x{h}+{x}+{y}")
        win.minsize(900, 680)
    except Exception:
        win.geometry(f"{width}x{height}")
        win.minsize(820, 620)


def _open_wizard_page_window(
    page_index: int,
    title: str,
    *,
    width: int = 1020,
    height: int = 880,
    on_open: Callable[[Any], None] | None = None,
) -> dict:
    import setup_wizard as sw

    _prepare_editor_state()
    page_cls = sw.CPharmWizard.PAGES[page_index]
    existing = _page_windows.get(page_index)
    if existing is not None:
        try:
            if existing.winfo_exists():
                page = _window_page(existing)
                if page is not None and hasattr(page, "on_enter"):
                    page.on_enter()
                if on_open is not None and page is not None:
                    try:
                        on_open(page)
                    except Exception as exc:
                        return {"ok": False, "error": f"{title} action failed: {exc}"}
                _show_tk_window(existing)
                return {"ok": True, "reused": True}
        except Exception:
            _page_windows.pop(page_index, None)

    win = tk.Toplevel(_tk_dialog_parent())
    win.title(title)
    _style_scrollbars(win)
    _fit_subwindow(win, width, height)
    try:
        win.configure(bg="#0f1320")
    except Exception:
        pass

    def on_close() -> None:
        _page_windows.pop(page_index, None)
        try:
            _persist_editor_state()
        except Exception:
            pass
        try:
            win.destroy()
        except Exception:
            pass

    win.protocol("WM_DELETE_WINDOW", on_close)
    page = page_cls(win)
    page.pack(fill="both", expand=True)
    if hasattr(page, "on_enter"):
        page.on_enter()
    if on_open is not None:
        try:
            on_open(page)
        except Exception as exc:
            try:
                win.destroy()
            except Exception:
                pass
            _restore_webview_from_tk()
            return {"ok": False, "error": f"{title} action failed: {exc}"}
    try:
        setattr(win, "_cpharm_page", page)
    except Exception:
        pass
    _page_windows[page_index] = win
    _show_tk_window(win)
    return {"ok": True}


def register_log_callback(fn: Callable[[str, str], None]) -> None:
    """``fn(channel, message)`` — channel matches step id or ``install`` / ``run``."""
    if fn not in _log_callbacks:
        _log_callbacks.append(fn)


def _emit_log(channel: str, text: str) -> None:
    """Always emit on the tk thread — install/setup run in worker threads."""

    def dispatch() -> None:
        for fn in list(_log_callbacks):
            try:
                fn(channel, text)
            except Exception:
                pass

    root = _tk_root
    if root is not None:
        try:
            root.after(0, dispatch)
            return
        except Exception:
            pass
    dispatch()


def _schedule_on_tk(fn: Callable[[], None]) -> None:
    root = _tk_root
    if root is not None:
        try:
            root.after(0, fn)
            return
        except Exception:
            pass
    fn()


def _ensure_tk_thread() -> None:
    global _boot_error
    if _ready.is_set():
        if _boot_error:
            raise RuntimeError(_boot_error)
        return

    def boot() -> None:
        global _tk_root, _wizard, _boot_error
        try:
            root = tk.Tk()
            root.title("CPharm backend")
            root.withdraw()
            host = tk.Frame(root)
            host.pack()
            wiz = CPharmWizard(host)
            _tk_root = root
            _wizard = wiz
            _wire_install_log(wiz._pages[1])
            _wire_boot_log(wiz._pages[4])
            _wire_launch_log(wiz._pages[8])
            try:
                from site_prefs import apply_site_url_to_boot_page

                apply_site_url_to_boot_page(wiz._pages[4])
            except Exception:
                pass

            def pump_queue() -> None:
                try:
                    while True:
                        fn, args, kwargs, done = _call_queue.get_nowait()
                        try:
                            result = fn(*args, **kwargs)
                            if done is not None:
                                done.put(result)
                        except Exception as exc:
                            if done is not None:
                                done.put(exc)
                except queue.Empty:
                    pass
                root.after(50, pump_queue)

            pump_queue()
            _ready.set()
            root.mainloop()
        except Exception as exc:
            _boot_error = f"CPharm backend failed to start: {exc}"
            _ready.set()

    threading.Thread(target=boot, name="cpharm-tk-bridge", daemon=True).start()
    _ready.wait(timeout=120)
    if _boot_error:
        raise RuntimeError(_boot_error)
    if _wizard is None:
        raise RuntimeError("CPharm backend did not start in time — restart the app.")


def _wire_install_log(page: Any) -> None:
    orig = page._log

    def patched(text: str) -> None:
        line = text if text.endswith("\n") else text + "\n"

        def on_tk() -> None:
            orig(text)
            _emit_log("install", line)

        _schedule_on_tk(on_tk)

    page._log = patched  # type: ignore[method-assign]


def _wire_boot_log(page: Any) -> None:
    orig = page._log_write

    def patched(text: str) -> None:
        line = text if text.endswith("\n") else text + "\n"

        def on_tk() -> None:
            orig(text)
            _emit_log("boot", line)

        _schedule_on_tk(on_tk)

    page._log_write = patched  # type: ignore[method-assign]


def _wire_launch_log(page: Any) -> None:
    orig = page._log_write

    def patched(text: str) -> None:
        line = text if text.endswith("\n") else text + "\n"

        def on_tk() -> None:
            orig(text)
            _emit_log("go", line)

        _schedule_on_tk(on_tk)

    page._log_write = patched  # type: ignore[method-assign]


def _run_on_tk(fn: Callable, *args, **kwargs) -> Any:
    _ensure_tk_thread()
    done: queue.Queue = queue.Queue(maxsize=1)
    _call_queue.put((fn, args, kwargs, done))
    result = done.get(timeout=600)
    if isinstance(result, Exception):
        raise result
    return result


def _run_async_on_tk(fn: Callable, *args, **kwargs) -> None:
    _ensure_tk_thread()
    _call_queue.put((fn, args, kwargs, None))


def wizard() -> Any:
    _ensure_tk_thread()
    assert _wizard is not None
    return _wizard


def _page(index: int) -> Any:
    idx = max(0, min(int(index), len(wizard()._pages) - 1))
    wizard()._show(idx)
    return wizard()._pages[idx]


def install_page() -> Any:
    return wizard()._pages[1]


def launch_page() -> Any:
    return wizard()._pages[8]


def get_wizard_steps() -> list[dict]:
    return [dict(s) for s in WIZARD_STEPS]


def navigate_wizard_page(index: int) -> dict:
    def work() -> dict:
        idx = max(0, min(int(index), len(wizard()._pages) - 1))
        wizard()._show(idx)
        step = WIZARD_STEPS[idx] if idx < len(WIZARD_STEPS) else {}
        return {"ok": True, "index": idx, "id": step.get("id", "")}

    return _run_on_tk(work)


def navigate_wizard_step(step_id: str) -> dict:
    idx = _STEP_ID_TO_INDEX.get(str(step_id or "").strip().lower(), 0)
    return navigate_wizard_page(idx)


def open_advanced_wizard() -> None:
    navigate_app_view("teams")


def navigate_app_view(view: str) -> None:
    from cpharm_app_webview import emit_app_view

    emit_app_view(view)


def navigate_dragon_view(view: str) -> None:
    """Deprecated alias."""
    navigate_app_view(view)


def navigate_wizard_chapter(index: int) -> None:
    step = WIZARD_STEPS[int(index)] if 0 <= int(index) < len(WIZARD_STEPS) else WIZARD_STEPS[0]
    navigate_app_view(step["id"])


def get_dragon_scroll() -> list[dict]:
    return get_wizard_steps()


def get_journey_state() -> dict:
    install_ready = False
    setup_ready = False
    groups_ok = False
    steps_ok = False
    try:
        rows = scan_prereqs()
        install_ready = bool(rows) and all(r.get("ok") for r in rows)
    except Exception:
        pass
    try:
        from mumu_setup_webview import MuMuSetupApi

        api = MuMuSetupApi(skip_launch_cpharm=True)
        st = api.get_state()
        checklist = st.get("checklist") or []
        setup_ready = bool(st.get("ready")) or bool(st.get("setup_already_done"))
    except Exception:
        pass
    try:
        _reload_persisted_wizard_state()
        from setup_wizard import state

        steps_ok = bool(state.get("default_steps"))
        groups = state.get("groups") or []
        if not steps_ok:
            for g in groups:
                if not isinstance(g, dict):
                    continue
                phones = g.get("phones") or {}
                if not isinstance(phones, dict):
                    continue
                for pdata in phones.values():
                    if not isinstance(pdata, dict):
                        continue
                    if pdata.get("steps") or pdata.get("sequence_playlist"):
                        steps_ok = True
                        break
                if steps_ok:
                    break
        groups_ok = bool(groups) and any(
            isinstance(g, dict)
            and isinstance(g.get("phones"), dict)
            and bool(g["phones"])
            for g in groups
        )
    except Exception:
        pass

    steps_out = []
    for s in WIZARD_STEPS:
        sid = s["id"]
        complete = False
        if sid == "start":
            complete = True
        elif sid == "install":
            complete = install_ready
        elif sid == "android":
            try:
                from setup_wizard import find_sdk

                complete = bool(find_sdk())
            except Exception:
                complete = False
        elif sid == "phones":
            complete = setup_ready
        elif sid == "boot":
            complete = False
        elif sid == "steps":
            complete = steps_ok
        elif sid == "teams":
            complete = groups_ok and steps_ok
        elif sid == "builder":
            complete = False
        elif sid == "go":
            complete = False
        steps_out.append(
            {
                "id": sid,
                "index": s["index"],
                "label": s["name"],
                "complete": complete,
                "order": s["index"] + 1,
            }
        )

    recommended = "start"
    if install_ready:
        recommended = "phones" if not setup_ready else ("teams" if not groups_ok else "go")
    else:
        recommended = "install"

    return {"steps": steps_out, "recommended_view": recommended}


def scan_prereqs() -> list[dict]:
    def work() -> list[dict]:
        page = install_page()
        rows = []
        checks = [
            ("java", "Java (helper)", page._check_java),
            ("python", "Python (helper)", page._check_python),
            ("packages", "Extra bits", page._check_packages),
            ("tor", "Safe internet (Tor)", page._check_tor),
            ("cpharm", "CPharm files", page._check_cpharm),
        ]
        for key, label, fn in checks:
            ok = False
            try:
                ok = bool(fn())
            except Exception:
                ok = False
            rows.append({"key": key, "label": label, "ok": ok})
        return rows

    return _run_on_tk(work)


def run_install_all() -> dict:
    """Start the full install; tell the WebView whether anything needed doing.

    Runs synchronously through the TK queue so ``already_installed`` / ``busy``
    are truthful when the button handler reads them (the old async enqueue
    returned before ``work`` ran, so the UI always saw the defaults).
    """

    def work() -> dict:
        page = install_page()
        if getattr(page, "_working", False):
            return {"ok": True, "started": False, "busy": True,
                    "already_installed": False}
        try:
            already = bool(page._check_all())
        except Exception:
            already = False
        page._install_all()
        return {"ok": True, "started": True, "busy": False,
                "already_installed": already}

    return _run_on_tk(work)


def get_android_status() -> dict:
    def work() -> dict:
        from setup_wizard import find_sdk, state

        page = _page(2)
        sdk = find_sdk() or state.get("sdk_path") or ""
        use_mumu = bool(state.get("use_mumu"))
        status = getattr(page, "_status_lbl", None)
        detail = getattr(page, "_detail_lbl", None)
        return {
            "sdk_path": str(sdk) if sdk else "",
            "use_mumu": use_mumu,
            "ready": bool(sdk) or use_mumu,
            "status": status.cget("text") if status else "",
            "detail": detail.cget("text") if detail else "",
            "working": bool(getattr(page, "_working", False)),
        }

    return _run_on_tk(work)


def run_android_install() -> dict:
    def work() -> None:
        page = _page(2)
        page._auto_install()

    _run_async_on_tk(work)
    return {"ok": True, "started": True}


def set_phone_farm_count(count: int) -> dict:
    def work() -> dict:
        page = _page(3)
        n = int(count)
        if hasattr(page, "_pick_count"):
            page._pick_count(n)
        return {"ok": True, "count": n}

    return _run_on_tk(work)


def run_create_phone_farm() -> dict:
    def work() -> None:
        page = _page(3)
        page._create()

    _run_async_on_tk(work)
    return {"ok": True, "started": True}


def run_boot_all() -> dict:
    def work() -> None:
        _prepare_editor_state()
        page = _page(4)
        page._boot_all()

    _run_async_on_tk(work)
    return {"ok": True, "started": True}


def run_stop_all_phones() -> dict:
    def work() -> None:
        _prepare_editor_state()
        page = _page(4)
        page._stop_all()

    _run_async_on_tk(work)
    return {"ok": True, "started": True}


def run_test_url(url: str | None = None) -> dict:
    def work() -> dict:
        from site_prefs import apply_site_url_to_boot_page, load_target_site_url, save_target_site_url

        _prepare_editor_state()
        from setup_wizard import state

        phones = state.get("phones") or []
        if not phones:
            return {
                "ok": False,
                "error": (
                    "No phones found — start MuMu, turn USB debugging ON, go to Step 4, "
                    "click Check again, then Set up my phones."
                ),
            }
        test_url = (url or "").strip() or load_target_site_url()
        if not test_url:
            return {
                "ok": False,
                "error": "Enter your site URL in Step 5, click Save, then try again.",
            }
        if url and url.strip():
            save_target_site_url(url.strip())
        page = _page(4)
        apply_site_url_to_boot_page(page)
        if hasattr(page, "_test_url_var"):
            page._test_url_var.set(test_url)
        serial = phones[0].get("serial") if isinstance(phones[0], dict) else str(phones[0])
        name = phones[0].get("name", serial) if isinstance(phones[0], dict) else serial
        try:
            from setup_wizard import chrome_open_url

            ok, note = chrome_open_url(serial, test_url)
        except Exception as exc:
            return {"ok": False, "error": str(exc), "serial": serial, "url": test_url}
        if ok:
            page._log_write(f"Opened {test_url} on {name} ({serial}).\n")
            return {"ok": True, "url": test_url, "serial": serial, "note": note or ""}
        page._log_write(f"Could not open {test_url} on {name}: {note or 'unknown'}\n")
        return {
            "ok": False,
            "error": note or "Phone did not open a browser.",
            "url": test_url,
            "serial": serial,
        }

    return _run_on_tk(work)


def get_site_settings() -> dict:
    def work() -> dict:
        from site_prefs import load_target_site_url, site_display_host

        u = load_target_site_url()
        return {"url": u, "host": site_display_host(u)}

    return _run_on_tk(work)


def save_site_url(url: str) -> dict:
    def work() -> dict:
        from site_prefs import apply_site_url_to_boot_page, save_target_site_url, site_display_host

        u = save_target_site_url(url)
        apply_site_url_to_boot_page(wizard()._pages[4])
        return {"ok": True, "url": u, "host": site_display_host(u)}

    return _run_on_tk(work)


def _reload_persisted_wizard_state() -> None:
    from setup_wizard import _try_load_groups_config

    _try_load_groups_config()


def _prepare_editor_state() -> None:
    from setup_wizard import _cpharm_install_root, list_adb_devices, state

    import preflight_core as preflight

    _reload_persisted_wizard_state()
    try:
        phones_quick = preflight.list_adb_phones()
        if not phones_quick:
            preflight.discover_adb_phones(connect_mumu=True)
            phones_quick = preflight.list_adb_phones()
        phones = list_adb_devices()
        if not phones and phones_quick:
            phones = list(phones_quick)
        if not phones:
            persisted = [
                p
                for p in (state.get("phones") or [])
                if isinstance(p, dict) and (p.get("serial") or "").strip()
            ]
            if persisted:
                preflight.discover_adb_phones(connect_mumu=True)
                phones = list_adb_devices() or persisted
    except Exception:
        phones = []
    state["phones"] = list(phones)
    if not state.get("cpharm_dir"):
        try:
            state["cpharm_dir"] = str(_cpharm_install_root())
        except Exception:
            pass


def _persist_editor_state() -> None:
    from setup_wizard import _persist_groups_config

    _persist_groups_config()


def get_automation_info() -> dict:
    def work() -> dict:
        from setup_wizard import state

        _reload_persisted_wizard_state()
        steps = list(state.get("default_steps") or [])
        return {"count": len(steps), "has_steps": bool(steps)}

    return _run_on_tk(work)


def run_edit_default_sequence() -> dict:
    def work() -> dict:
        from setup_wizard import PerPhoneSequenceEditor, _apply_default_steps_to_template_phones, state

        _reload_persisted_wizard_state()
        parent = _tk_dialog_parent()
        page = wizard()._pages[5]
        page.on_enter()
        dlg = PerPhoneSequenceEditor(
            parent,
            serial="default",
            phone_name="Default sequence (template for group assignments)",
            steps_list=page._seq_steps,
        )
        dlg.transient(parent)
        dlg.protocol("WM_DELETE_WINDOW", dlg.destroy)
        _show_tk_window(dlg)
        # The dialog is modal, but wait on the dialog itself. Waiting on the
        # hidden 1x1 parent can leave the WebView callback blocked forever.
        dlg.grab_set()
        dlg.wait_window()
        n = len(page._seq_steps)
        state["default_steps"] = list(page._seq_steps)
        _apply_default_steps_to_template_phones()
        _persist_editor_state()
        return {"ok": True, "count": n}

    return _spawn_with_visible_fallback(5, action="edit_sequence", fallback=lambda: _run_on_tk(work))


def open_sequence_builder() -> dict:
    def work() -> dict:
        return _open_wizard_page_window(6, "CPharm — Builder", width=1220, height=980)

    return _spawn_with_visible_fallback(6, fallback=lambda: _run_on_tk(work))


def open_groups_manager() -> dict:
    def work() -> dict:
        return _open_wizard_page_window(7, "CPharm — Groups", width=1240, height=1000)

    return _spawn_with_visible_fallback(7, fallback=lambda: _run_on_tk(work))


def run_add_group() -> dict:
    def work() -> dict:
        _prepare_editor_state()
        page = _page(7)
        page.on_enter()
        page._add_group()
        _persist_editor_state()
        return _groups_detail_from_state()

    detail = _run_on_tk(work)
    if isinstance(detail, dict):
        return {"ok": True, **detail}
    return {"ok": True}


def run_humanize_all_sequences() -> dict:
    def work() -> dict:
        _prepare_editor_state()
        page = _page(7)
        page.on_enter()
        page._humanize_all_sequences()
        _persist_editor_state()
        msg = ""
        try:
            msg = str(page._grp_status.cget("text") or "").strip()
        except Exception:
            pass
        if not msg:
            msg = "Natural timing applied."
        return {"ok": True, "message": msg}

    return _run_on_tk(work)


def run_load_default_sequence() -> dict:
    def work() -> dict:
        from pathlib import Path

        from native_dialogs import ask_open_json_file
        from setup_wizard import (
            SequenceJsonLoadError,
            _apply_default_steps_to_template_phones,
            _load_sequence_document_from_path,
            _normalize_sequence_steps,
            state,
        )

        _prepare_editor_state()
        page = wizard()._pages[5]
        page.on_enter()
        parent = _tk_dialog_parent()
        path = ask_open_json_file(title="Load sequence", parent=parent)
        if not path:
            return {"ok": False, "cancelled": True}
        try:
            data, _meta = _load_sequence_document_from_path(Path(path))
        except SequenceJsonLoadError as exc:
            return {"ok": False, "error": str(exc)}
        data = _normalize_sequence_steps(data)
        page._seq_steps.clear()
        page._seq_steps.extend(data)
        state["default_steps"] = list(page._seq_steps)
        _apply_default_steps_to_template_phones()
        from setup_wizard import _persist_groups_config

        _persist_groups_config()
        return {"ok": True, "count": len(page._seq_steps), "path": path}

    return _run_on_tk(work)


def run_save_default_sequence() -> dict:
    def work() -> dict:
        import json
        from pathlib import Path

        from native_dialogs import ask_save_json_file
        from setup_wizard import state

        _prepare_editor_state()
        page = wizard()._pages[5]
        page.on_enter()
        if not page._seq_steps:
            return {"ok": False, "error": "No steps to save — use Edit default sequence first."}
        parent = _tk_dialog_parent()
        path = ask_save_json_file(title="Save sequence", parent=parent)
        if not path:
            return {"ok": False, "cancelled": True}
        Path(path).write_text(json.dumps(page._seq_steps, indent=2), encoding="utf-8")
        state["default_steps"] = list(page._seq_steps)
        from setup_wizard import _persist_groups_config

        _persist_groups_config()
        return {"ok": True, "path": path}

    return _run_on_tk(work)


def load_sequence_from_path(path: str) -> dict:
    def work() -> dict:
        from pathlib import Path

        from setup_wizard import (
            SequenceJsonLoadError,
            _apply_default_steps_to_template_phones,
            _load_sequence_document_from_path,
            _normalize_sequence_steps,
            state,
        )

        _prepare_editor_state()
        page = wizard()._pages[5]
        page.on_enter()
        try:
            data, _meta = _load_sequence_document_from_path(Path(path))
        except SequenceJsonLoadError as exc:
            return {"ok": False, "error": str(exc)}
        data = _normalize_sequence_steps(data)
        page._seq_steps.clear()
        page._seq_steps.extend(data)
        state["default_steps"] = list(page._seq_steps)
        _apply_default_steps_to_template_phones()
        from setup_wizard import _persist_groups_config

        _persist_groups_config()
        return {"ok": True, "count": len(page._seq_steps), "path": path}

    return _run_on_tk(work)


def save_sequence_to_path(path: str) -> dict:
    def work() -> dict:
        import json
        from pathlib import Path

        from setup_wizard import state

        _prepare_editor_state()
        page = wizard()._pages[5]
        page.on_enter()
        if not page._seq_steps:
            return {"ok": False, "error": "No steps to save — use Edit default sequence first."}
        Path(path).write_text(json.dumps(page._seq_steps, indent=2), encoding="utf-8")
        state["default_steps"] = list(page._seq_steps)
        from setup_wizard import _persist_groups_config

        _persist_groups_config()
        return {"ok": True, "path": path}

    return _run_on_tk(work)


def get_groups_detail() -> dict:
    def work() -> dict:
        from setup_wizard import _normalize_all_groups

        _reload_persisted_wizard_state()
        _normalize_all_groups()
        return _groups_detail_from_state()

    return _run_on_tk(work)


def get_groups_summary() -> dict:
    return get_groups_detail()


def is_dashboard_ready() -> dict:
    def work() -> dict:
        page = launch_page()
        ready = bool(page._dashboard_config_reachable())
        running = False
        try:
            proc = getattr(page, "_server_proc", None)
            running = proc is not None and proc.poll() is None
        except Exception:
            running = ready
        return {"ready": ready, "server_running": running or ready}

    return _run_on_tk(work)


def get_launch_summary() -> dict:
    def work() -> dict:
        page = _page(8)
        txt = ""
        try:
            txt = page._summary.get("1.0", "end").strip()
        except Exception:
            pass
        return {"summary": txt}

    return _run_on_tk(work)


def save_browse_mode(mode: str) -> dict:
    def work() -> dict:
        import os

        from wizard_paths import automation_on_sys_path

        automation_on_sys_path()
        import browse_proxy as bp

        mode_l = (mode or "scramble").strip().lower()
        bp.save_browse_prefs(browse_proxy_mode=mode_l)
        os.environ["CPHARM_BROWSE_PROXY_MODE"] = mode_l
        return {"ok": True, "mode": mode_l, "label": bp.browse_proxy_mode_label(mode_l)}

    return _run_on_tk(work)


def get_browse_mode() -> dict:
    def work() -> dict:
        from wizard_paths import automation_on_sys_path

        automation_on_sys_path()
        import browse_proxy as bp

        m = bp.browse_proxy_mode()
        return {"mode": m, "label": bp.browse_proxy_mode_label(m)}

    return _run_on_tk(work)


def start_server() -> dict:
    def work() -> dict:
        result = _open_wizard_page_window(8, "CPharm — Run", width=1240, height=1000)
        page = _window_page(_page_windows.get(8)) or launch_page()
        page.on_enter()
        if hasattr(page, "_start_server"):
            page._start_server()
        if isinstance(result, dict):
            result["started"] = True
            return result
        return {"ok": True, "started": True}

    return _spawn_with_visible_fallback(
        8, action="start_server", success_augment={"started": True}, fallback=lambda: _run_on_tk(work)
    )


def start_server_and_open_dashboard() -> dict:
    def work() -> dict:
        result = _open_wizard_page_window(8, "CPharm — Run", width=1240, height=1000)
        page = _window_page(_page_windows.get(8)) or launch_page()
        page.on_enter()
        if hasattr(page, "_start_server"):
            page._start_server()
        # _start_server is intentionally asynchronous; waiting here blocks the Tk
        # event loop and prevents the server thread's UI callbacks from running.
        # Open the browser from the page once the normal readiness poll succeeds.
        opened = False
        if hasattr(page, "_open_dashboard_browser"):
            page.after(250, lambda: page._open_dashboard_browser("/"))
            opened = True
        out = dict(result) if isinstance(result, dict) else {"ok": True}
        out["dashboard_opened"] = opened
        if not opened:
            out["message"] = "Server starting — click Open dashboard in a moment."
        return out

    return _spawn_with_visible_fallback(
        8,
        action="start_server_and_open_dashboard",
        success_augment={"started": True, "dashboard_opened": True},
        fallback=lambda: _run_on_tk(work),
    )


def run_all_groups() -> dict:
    def work() -> dict:
        result = _open_wizard_page_window(8, "CPharm — Run", width=1240, height=1000)
        page = _window_page(_page_windows.get(8)) or launch_page()
        page.on_enter()
        if hasattr(page, "_run_groups"):
            page._run_groups()
        if isinstance(result, dict):
            result["started"] = True
            return result
        return {"ok": True, "started": True}

    return _spawn_with_visible_fallback(
        8, action="run_groups", success_augment={"started": True}, fallback=lambda: _run_on_tk(work)
    )


def start_automation_one_click() -> dict:
    def work() -> dict:
        result = _open_wizard_page_window(8, "CPharm — Run", width=1240, height=1000)
        page = _window_page(_page_windows.get(8)) or launch_page()
        page.on_enter()
        if hasattr(page, "_start_automation_one_click"):
            page._start_automation_one_click()
        if isinstance(result, dict):
            result["started"] = True
            return result
        return {"ok": True, "started": True}

    return _spawn_with_visible_fallback(
        8, action="start_automation", success_augment={"started": True}, fallback=lambda: _run_on_tk(work)
    )


def fix_phone_internet() -> dict:
    def work() -> dict:
        from setup_wizard import wiz_clear_phone_proxies_best_effort

        n = wiz_clear_phone_proxies_best_effort(stop_tor_host=False)
        return {"ok": True, "n": n}

    return _run_on_tk(work)


def open_dashboard() -> dict:
    def work() -> dict:
        page = launch_page()
        ready = bool(page._dashboard_config_reachable())
        running = False
        try:
            proc = getattr(page, "_server_proc", None)
            running = proc is not None and proc.poll() is None
        except Exception:
            running = ready
        if not ready and not running:
            return {
                "ok": False,
                "error": "Service is not running — use Step 9 → Start service + open dashboard first.",
            }
        page._open_dashboard_browser("/")
        return {"ok": True}

    return _run_on_tk(work)


# ── Cloud phones + agent (visible from Step 9 → Extra tools) ──


def _cloud_cli_argv(command: str, host: str = "", count: int = 0, *, verify: bool = False) -> list[str]:
    """Build argv that runs cloud_phones_cli in the frozen EXE or from source."""
    if getattr(sys, "frozen", False):
        cmd = [str(sys.executable), "--cloud-phones-cli", command]
    else:
        cloud_cli = Path(__file__).resolve().parent.parent / "cloud_phones" / "cloud_phones_cli.py"
        cmd = [str(sys.executable), str(cloud_cli), command]
    if host:
        cmd += ["--host", host]
    if count > 0:
        cmd += ["--count", str(count)]
    if verify:
        cmd.append("--verify")
    return cmd


def run_cloud_phone_command(command: str, host: str = "", count: int = 0, *, verify: bool = False) -> dict:
    """Run a cloud_phones CLI command in a hidden background process.

    Output streams into the Step 9 log so the operator can watch progress.
    """

    def work() -> None:
        cmd = _cloud_cli_argv(command, host, count, verify=verify)
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                creationflags=flags,
            )
        except Exception as exc:
            _emit_log("go", f"[cloud {command}] could not start: {exc}\n")
            return
        assert proc.stdout is not None
        for line in proc.stdout:
            _emit_log("go", line)
        proc.wait()
        _emit_log("go", f"\n[cloud {command}] finished (exit {proc.returncode})\n")

    threading.Thread(target=work, daemon=True).start()
    return {"ok": True, "started": True, "command": command}


def cloud_phone_setup(host: str, count: int = 8) -> dict:
    """Full cloud setup: connect + stealth + Tor on N instances (hidden window)."""
    return run_cloud_phone_command("setup", host, int(count or 8))


def cloud_phone_status(host: str = "") -> dict:
    """List connected cloud instances (hidden window)."""
    return run_cloud_phone_command("status", host, 0)


def _watchdog_script_path() -> str:
    if getattr(sys, "frozen", False):
        return str(Path(sys._MEIPASS) / "tools" / "cpharm_watchdog.py")  # type: ignore[attr-defined]
    return str(Path(__file__).resolve().parent.parent / "tools" / "cpharm_watchdog.py")


def _agent_script_path() -> str:
    """Resolve tools/cloud_agent.py in a frozen EXE or from source."""
    if getattr(sys, "frozen", False):
        return str(Path(sys._MEIPASS) / "tools" / "cloud_agent.py")  # type: ignore[attr-defined]
    return str(Path(__file__).resolve().parent.parent / "tools" / "cloud_agent.py")


def _agent_config_path() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent / "cloud_agent.json"
    return Path(__file__).resolve().parent.parent / "cloud_agent.json"


def cloud_agent_config() -> dict:
    """Return current cloud-agent config WITHOUT exposing the API key (masked)."""
    import os

    cfg_path = _agent_config_path()
    cfg: dict = {
        "base": os.environ.get("CPHARM_CLOUD_AGENT_BASE", "https://api.openai.com/v1"),
        "model": os.environ.get("CPHARM_CLOUD_AGENT_MODEL", "gpt-4o"),
        "api_key": "",
        "configured": False,
    }
    raw_key = os.environ.get("CPHARM_CLOUD_AGENT_KEY", "")
    if cfg_path.is_file():
        try:
            data = json.loads(cfg_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
        if isinstance(data.get("base"), str) and data["base"].strip():
            cfg["base"] = data["base"].strip()
        if isinstance(data.get("model"), str) and data["model"].strip():
            cfg["model"] = data["model"].strip()
        if isinstance(data.get("api_key"), str) and data["api_key"].strip():
            raw_key = data["api_key"].strip()
    cfg["configured"] = bool(raw_key)
    cfg["api_key"] = (raw_key[:4] + "…" if len(raw_key) > 6 else "") if raw_key else ""
    return cfg


def save_cloud_agent_config(base: str = "", model: str = "", api_key: str = "") -> dict:
    """Persist cloud-agent config to <root>/cloud_agent.json (key stored on disk)."""
    cfg_path = _agent_config_path()
    existing = {}
    if cfg_path.is_file():
        try:
            existing = json.loads(cfg_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            existing = {}
        if not isinstance(existing, dict):
            existing = {}
    if base and base.strip():
        existing["base"] = base.strip().rstrip("/")
    if model and model.strip():
        existing["model"] = model.strip()
    if api_key and api_key.strip():
        existing["api_key"] = api_key.strip()
    try:
        cfg_path.write_text(json.dumps(existing, indent=2), encoding="utf-8")
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    return {"ok": True, "configured": bool(existing.get("api_key") or os.environ.get("CPHARM_CLOUD_AGENT_KEY"))}


def run_cloud_agent(goal: str, *, apply: bool = False, base: str = "", model: str = "", max_steps: int = 12) -> dict:
    """Run the LLM cloud agent in a hidden process, streaming output to the Step 9 log."""
    agent = _agent_script_path()
    if not Path(agent).is_file():
        _emit_log("go", f"[cloud agent] not found: {agent}\n")
        return {"ok": False, "error": "cloud agent module missing in this build"}

    def work() -> None:
        import os

        cmd = [str(sys.executable), agent]
        if apply:
            cmd.append("--apply")
        if base and base.strip():
            cmd += ["--base", base.strip()]
        if model and model.strip():
            cmd += ["--model", model.strip()]
        cmd += ["--max-steps", str(max(1, int(max_steps)))]
        cmd += [str(goal)]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        env = dict(os.environ)
        _emit_log("go", "\n── Cloud agent started ──\n")
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
                creationflags=flags,
            )
        except Exception as exc:
            _emit_log("go", f"[cloud agent] could not start: {exc}\n")
            return
        assert proc.stdout is not None
        for line in proc.stdout:
            _emit_log("go", line)
        proc.wait()
        _emit_log("go", f"\n── Cloud agent finished (exit {proc.returncode}) ──\n")

    threading.Thread(target=work, daemon=True).start()
    return {"ok": True, "started": True}


def agent_status() -> dict:
    """Run the packaged watchdog once (dry-run) and stream a summary to Step 9 log."""

    def work() -> None:
        wd = _watchdog_script_path()
        if not Path(wd).is_file():
            _emit_log("go", f"[agent] watchdog not found: {wd}\n")
            return
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
        try:
            result = subprocess.run(
                [str(sys.executable), wd, "--host", "127.0.0.1", "--count", "4"],
                capture_output=True,
                text=True,
                timeout=120,
                creationflags=flags,
            )
        except Exception as exc:
            _emit_log("go", f"[agent] watchdog check failed: {exc}\n")
            return
        out = (result.stdout or "").strip()
        try:
            data = json.loads(out)
        except Exception:
            data = {"raw": out[-2000:]}
        docker = data.get("docker") or {}
        adb_rows = data.get("adb") or []
        connected = [r for r in adb_rows if r.get("adb") == "connected"]
        unreachable = [r for r in adb_rows if r.get("adb") == "unreachable"]
        lines = [
            "\n[agent] watchdog status",
            f"  Docker/emulators: {'OK' if docker.get('ok') else docker.get('error', 'unknown')}",
            f"  ADB devices checked: {len(adb_rows)}",
            f"  Connected: {len(connected)}   Unreachable: {len(unreachable)}",
        ]
        if data.get("docker_repair"):
            lines.append(f"  Docker repair: {data['docker_repair'].get('status', 'n/a')}")
        _emit_log("go", "\n".join(lines) + "\n")

    threading.Thread(target=work, daemon=True).start()
    return {"ok": True, "started": True}


# ── Farm start/stop (unison money stack) — added in pharmflow merge ──


def start_farm_from_app(profile_slug: str = "", hours: float = 0) -> dict:
    """Start the unison money farm (run_farm_354 + stealth + watchdog) from the app.

    Delegates to wizard.farm_control.start_farm so the EXE owns the same
    money path the operator dash (:8091) reports on.
    """
    from wizard.farm_control import farm_running as _fr, load_active_profile, start_farm as _sf

    def work() -> dict:
        try:
            if _fr():
                return {"ok": False, "error": "Farm already running", "running": True}
            profile = load_active_profile(profile_slug or None)
            ok = _sf(profile=profile, hours=hours or None, takeover=True)
            if ok:
                return {"ok": True, "started": True, "dashboard": "http://127.0.0.1:8091/"}
            return {"ok": False, "error": "Start farm refused (see farm log)"}
        except Exception as exc:  # noqa: BLE001 — surface to UI
            return {"ok": False, "error": f"start_farm error: {exc}"}

    return _run_on_tk(work)


def stop_farm_from_app() -> dict:
    """Stop the unison money farm started by :func:`start_farm_from_app`."""
    from wizard.farm_control import farm_running as _fr, stop_farm as _stop

    def work() -> dict:
        try:
            if not _fr():
                return {"ok": False, "error": "Farm is not running"}
            stopped = _stop()
            return {"ok": bool(stopped), "stopped": bool(stopped)}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"stop_farm error: {exc}"}

    return _run_on_tk(work)


def farm_status_from_app() -> dict:
    """Lightweight farm status for the Run page."""
    from wizard.farm_control import farm_running as _fr, external_python_farm_running as _ex

    def work() -> dict:
        try:
            return {
                "ok": True,
                "running": bool(_fr()),
                "external": bool(_ex()),
                "dashboard": "http://127.0.0.1:8091/",
            }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)}

    return _run_on_tk(work)
