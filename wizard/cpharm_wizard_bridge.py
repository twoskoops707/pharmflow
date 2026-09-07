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
        "id": "map",
        "name": "Site Map",
        "phase": "Part 3 — Check & configure",
        "subtitle": "Scan a site into steps",
        "hint": "Map any website's pages, forms and buttons, then generate a starter sequence draft.",
    },
    {
        "index": 6,
        "id": "steps",
        "name": "Steps",
        "phase": "Part 3 — Check & configure",
        "subtitle": "Default tap list",
        "hint": "Usually already set in Phones — edit only if needed.",
    },
    {
        "index": 7,
        "id": "builder",
        "name": "Builder",
        "phase": "Part 3 — Check & configure",
        "subtitle": "Custom sequences (optional)",
        "hint": "Skip if shipped defaults are fine.",
    },
    {
        "index": 8,
        "id": "teams",
        "name": "Groups",
        "phase": "Part 3 — Check & configure",
        "subtitle": "Assign phones to groups",
        "hint": "Assign playlists and runs per day.",
    },
    {
        "index": 9,
        "id": "go",
        "name": "Run",
        "phase": "Part 4 — Automate",
        "subtitle": "Start service + sequences",
        "hint": "Start service, then run all groups.",
    },
]

_STEP_ID_TO_INDEX = {s["id"]: s["index"] for s in WIZARD_STEPS}

# Deck has 10 steps (includes native "map"); CPharmWizard.PAGES has 9 Tk pages.
# Never use deck indices as PAGES indices — "map" shifts steps/builder/teams/go by +1.
_DECK_ID_TO_PAGE: dict[str, int | None] = {
    "start": 0,
    "install": 1,
    "android": 2,
    "phones": 3,
    "boot": 4,
    "map": None,  # deck-native Site Map — no Tk page
    "steps": 5,
    "builder": 6,
    "teams": 7,
    "go": 8,
}

_webview_window: Any = None
_webview_hide_depth = 0


def _tk_page_index_for_step(
    step_id: str | None = None, deck_index: int | None = None
) -> int | None:
    """Map a deck step id/index to a CPharmWizard.PAGES index (or None if deck-only)."""
    sid = str(step_id or "").strip().lower()
    if sid and sid in _DECK_ID_TO_PAGE:
        return _DECK_ID_TO_PAGE[sid]
    if deck_index is not None:
        try:
            di = int(deck_index)
        except (TypeError, ValueError):
            return 0
        if 0 <= di < len(WIZARD_STEPS):
            return _DECK_ID_TO_PAGE.get(str(WIZARD_STEPS[di].get("id") or ""))
    return 0


def _as_index(value: Any, *, label: str = "index") -> tuple[int | None, str | None]:
    try:
        return int(value), None
    except (TypeError, ValueError):
        return None, f"Invalid {label}: {value!r}"


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
_tk_thread_ident: int | None = None
_ready = threading.Event()
_boot_error: str | None = None
_call_queue: queue.Queue = queue.Queue()
_boot_all_lock = threading.Lock()
_farm_start_lock = threading.Lock()
_farm_starting = False
_farm_start_result: dict[str, Any] = {}
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
    page_idx = _tk_page_index_for_step(step_id)
    if page_idx is None:
        # Deck-only step (e.g. Site Map) — no classic Tk page to open.
        return {"ok": True, "deck": step_id, "mode": "deck"}
    idx = int(page_idx)

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
                return {"ok": False, "error": f"Could not reuse Wizard window: {exc}"}

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
        global _tk_root, _wizard, _boot_error, _tk_thread_ident
        try:
            _tk_thread_ident = threading.get_ident()
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
    """Run ``fn`` on the Tk bridge thread.

    Calling from the Tk thread itself runs ``fn`` inline (avoids deadlock when a
    pump callback re-enters). Cross-thread callers wait up to 600s; timeout
    returns ``{ok: False, error: ...}`` instead of raising ``queue.Empty``.
    """
    _ensure_tk_thread()
    if _tk_thread_ident is not None and threading.get_ident() == _tk_thread_ident:
        return fn(*args, **kwargs)
    done: queue.Queue = queue.Queue(maxsize=1)
    _call_queue.put((fn, args, kwargs, done))
    try:
        result = done.get(timeout=600)
    except queue.Empty:
        return {"ok": False, "error": "Timed out waiting for UI thread (600s)"}
    if isinstance(result, Exception):
        raise result
    return result


def _safe_run_on_tk(fn: Callable, *args, **kwargs) -> dict:
    """Like ``_run_on_tk`` but never raises — always returns a dict with ok/error."""
    try:
        result = _run_on_tk(fn, *args, **kwargs)
    except Exception as exc:  # noqa: BLE001 — surface to WebView as error dict
        return {"ok": False, "error": str(exc)[:500]}
    if isinstance(result, dict):
        return result
    return {"ok": True, "data": result}


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
        deck_idx, err = _as_index(index, label="page index")
        if err or deck_idx is None:
            return {"ok": False, "error": err or "Invalid page index"}
        step = WIZARD_STEPS[deck_idx] if 0 <= deck_idx < len(WIZARD_STEPS) else {}
        page_idx = _tk_page_index_for_step(step.get("id") if step else None, deck_idx)
        if page_idx is None:
            return {
                "ok": True,
                "index": deck_idx,
                "id": step.get("id", "") if step else "",
                "tk": False,
            }
        pages = wizard()._pages
        page_idx = max(0, min(int(page_idx), len(pages) - 1))
        wizard()._show(page_idx)
        return {
            "ok": True,
            "index": deck_idx,
            "id": step.get("id", "") if step else "",
            "page": page_idx,
        }

    return _safe_run_on_tk(work)


def navigate_wizard_step(step_id: str) -> dict:
    sid = str(step_id or "").strip().lower()
    idx = _STEP_ID_TO_INDEX.get(sid, 0)
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
    # Journey-state must NEVER run the full setup state scan (initial_state does
    # live adb discovery and took ~17s on this machine — stalling the deck before
    # the action buttons are even wired). Read the persisted setup marker file
    # instead: setup_already_done is a file check, ready follows from it here.
    try:
        import mumu_setup_core as msc
        import preflight_core as pc

        setup_done = pc.mumu_setup_already_done(msc.data_root())
        setup_ready = bool(setup_done)
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
                    "No phones found — start your emulator (MuMu, Docker redroid, AVD) or plug a real phone, "
                    "turn USB debugging ON, go to Step 4, click Check again, then Set up my phones."
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


def scan_site(url: str = "") -> dict:
    """Crawl a website and return its map (pages, forms, buttons, links)."""
    try:
        from site_mapper import scan_site as _scan

        return _scan(url or "")
    except Exception as exc:  # noqa: BLE001 — surface as error dict
        return {"ok": False, "error": str(exc)[:300]}


def apply_site_sequence(url: str = "") -> dict:
    """Scan a site, generate a starter sequence draft, save it, and make it
    the default sequence (the same state the Steps step reads)."""

    def commit(steps: list, path: str, draft: dict) -> dict:
        from setup_wizard import (
            _apply_default_steps_to_template_phones,
            _groups_have_assigned_phones,
            _persist_groups_config,
            state,
        )

        state["default_steps"] = steps
        _apply_default_steps_to_template_phones()
        # Persist to disk only when groups already have phones — otherwise
        # _persist_groups_config() triggers ADB discovery which can hang
        # with zero devices. The draft JSON is always saved regardless.
        if _groups_have_assigned_phones():
            _persist_groups_config()
        return {
            "ok": True,
            "steps": len(steps),
            "path": path,
            "note": draft["note"],
            "pages_mapped": draft["pages_mapped"],
        }

    try:
        from site_mapper import build_starter_sequence, normalize_url, save_sequence
        from wizard_paths import app_data_root

        target = normalize_url(url or "")
        if not target:
            return {"ok": False, "error": "Enter a valid URL like https://example.com"}
        draft = build_starter_sequence(target)
        steps = draft["steps"]
        host = target.split("//", 1)[-1].split("/", 1)[0]
        out_dir = app_data_root() / "sequences" / "site_scans"
        path = save_sequence(steps, host, output_dir=out_dir)
        return _run_on_tk(lambda: commit(steps, str(path), draft))
    except Exception as exc:  # noqa: BLE001 — surface as error dict
        return {"ok": False, "error": str(exc)[:300]}


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
        return {"ok": True, "count": len(steps), "has_steps": bool(steps)}

    return _safe_run_on_tk(work)


def _sync_default_steps_to_seq_page(steps: list) -> None:
    """Keep hidden Steps page in sync so load/save dialogs see the same list."""
    try:
        page = wizard()._pages[5]
        page._seq_steps.clear()
        page._seq_steps.extend(list(steps))
    except Exception:
        pass


def cursor_get_sequence() -> dict:
    """Deck-native: return default_steps for the in-webview sequence editor."""

    def work() -> dict:
        from setup_wizard import state

        _reload_persisted_wizard_state()
        steps = list(state.get("default_steps") or [])
        return {"ok": True, "steps": steps, "count": len(steps)}

    return _safe_run_on_tk(work)


def cursor_add_step(step: dict | None = None) -> dict:
    def work() -> dict:
        from setup_wizard import _apply_default_steps_to_template_phones, _normalize_sequence_steps, state

        _reload_persisted_wizard_state()
        raw = step if isinstance(step, dict) else {"type": "wait", "seconds": 2.0}
        normalized = _normalize_sequence_steps([raw])
        new_step = normalized[0] if normalized else dict(raw)
        steps = list(state.get("default_steps") or [])
        steps.append(new_step)
        state["default_steps"] = steps
        _apply_default_steps_to_template_phones()
        _sync_default_steps_to_seq_page(steps)
        _persist_editor_state()
        return {"ok": True, "count": len(steps), "steps": steps}

    return _safe_run_on_tk(work)


def cursor_update_step(i: int, step: dict | None = None) -> dict:
    def work() -> dict:
        from setup_wizard import _apply_default_steps_to_template_phones, _normalize_sequence_steps, state

        _reload_persisted_wizard_state()
        steps = list(state.get("default_steps") or [])
        idx, err = _as_index(i, label="step index")
        if err or idx is None:
            return {"ok": False, "error": err or "Invalid step index"}
        if idx < 0 or idx >= len(steps):
            return {"ok": False, "error": f"Step index out of range: {idx}"}
        if not isinstance(step, dict):
            return {"ok": False, "error": "step must be an object"}
        normalized = _normalize_sequence_steps([step])
        steps[idx] = normalized[0] if normalized else dict(step)
        state["default_steps"] = steps
        _apply_default_steps_to_template_phones()
        _sync_default_steps_to_seq_page(steps)
        _persist_editor_state()
        return {"ok": True, "count": len(steps), "steps": steps}

    return _safe_run_on_tk(work)


def cursor_remove_step(i: int) -> dict:
    def work() -> dict:
        from setup_wizard import _apply_default_steps_to_template_phones, state

        _reload_persisted_wizard_state()
        steps = list(state.get("default_steps") or [])
        idx, err = _as_index(i, label="step index")
        if err or idx is None:
            return {"ok": False, "error": err or "Invalid step index"}
        if idx < 0 or idx >= len(steps):
            return {"ok": False, "error": f"Step index out of range: {idx}"}
        steps.pop(idx)
        state["default_steps"] = steps
        _apply_default_steps_to_template_phones()
        _sync_default_steps_to_seq_page(steps)
        _persist_editor_state()
        return {"ok": True, "count": len(steps), "steps": steps}

    return _safe_run_on_tk(work)


def cursor_move_step(i: int, dir: int = 1) -> dict:
    def work() -> dict:
        from setup_wizard import _apply_default_steps_to_template_phones, state

        _reload_persisted_wizard_state()
        steps = list(state.get("default_steps") or [])
        idx, err = _as_index(i, label="step index")
        if err or idx is None:
            return {"ok": False, "error": err or "Invalid step index"}
        delta, derr = _as_index(dir, label="dir")
        if derr or delta is None:
            return {"ok": False, "error": derr or "Invalid dir"}
        j = idx + delta
        if idx < 0 or idx >= len(steps):
            return {"ok": False, "error": f"Step index out of range: {idx}"}
        if j < 0 or j >= len(steps):
            return {"ok": False, "error": "Cannot move step further"}
        steps[idx], steps[j] = steps[j], steps[idx]
        state["default_steps"] = steps
        _apply_default_steps_to_template_phones()
        _sync_default_steps_to_seq_page(steps)
        _persist_editor_state()
        return {"ok": True, "count": len(steps), "steps": steps}

    return _safe_run_on_tk(work)


def cursor_add_group() -> dict:
    """Deck-native: append a group with the exact Tk GroupsPage shape."""

    def work() -> dict:
        from setup_wizard import (
            DEFAULT_HITS_PER_DAY,
            DEFAULT_SEQUENCE_BASE_H,
            DEFAULT_SEQUENCE_BASE_W,
            _normalize_all_groups,
            _profile_key,
            state,
        )

        _prepare_editor_state()
        _normalize_all_groups()
        n = len(state["groups"]) + 1
        default_steps = state.get("default_steps", [])
        phones_map: dict = {}
        for p in state.get("phones", []):
            if not isinstance(p, dict):
                continue
            ser = (p.get("serial") or "").strip()
            if not ser:
                continue
            phones_map[ser] = {
                "steps": list(default_steps),
                "hits_per_day": DEFAULT_HITS_PER_DAY,
                "use_default_template": True,
                "explicit_override": False,
                "sequence_base_w": DEFAULT_SEQUENCE_BASE_W,
                "sequence_base_h": DEFAULT_SEQUENCE_BASE_H,
                "sequence_profile_key": _profile_key(DEFAULT_SEQUENCE_BASE_W, DEFAULT_SEQUENCE_BASE_H),
                "sequence_playlist": [],
                "sequence_playlist_secondary": [],
                "sequence_playlist_mode": "series",
                "sequence_playlist_shuffle": "none",
            }
        state["groups"].append(
            {
                "name": f"Group {n}",
                "phones": phones_map,
                "stagger_secs": 30,
                "repeat": 1,
                "repeat_forever": False,
            }
        )
        _persist_editor_state()
        return {"ok": True, **_groups_detail_from_state()}

    return _safe_run_on_tk(work)


def cursor_remove_group(i: int) -> dict:
    def work() -> dict:
        from setup_wizard import _normalize_all_groups, state

        _prepare_editor_state()
        _normalize_all_groups()
        groups = list(state.get("groups") or [])
        if len(groups) <= 1:
            return {"ok": False, "error": "Need at least one group.", **_groups_detail_from_state()}
        idx, err = _as_index(i, label="group index")
        if err or idx is None:
            return {"ok": False, "error": err or "Invalid group index", **_groups_detail_from_state()}
        if idx < 0 or idx >= len(groups):
            return {"ok": False, "error": f"Group index out of range: {idx}", **_groups_detail_from_state()}
        removed = groups.pop(idx)
        state["groups"] = groups
        _persist_editor_state()
        removed_name = (
            (removed.get("name") or "").strip()
            if isinstance(removed, dict)
            else ""
        ) or f"Group {idx + 1}"
        return {"ok": True, "removed": removed_name, **_groups_detail_from_state()}

    return _safe_run_on_tk(work)


def cursor_rename_group(i: int, name: str = "") -> dict:
    def work() -> dict:
        from setup_wizard import _normalize_all_groups, state

        _prepare_editor_state()
        _normalize_all_groups()
        groups = state.get("groups") or []
        idx, err = _as_index(i, label="group index")
        if err or idx is None:
            return {"ok": False, "error": err or "Invalid group index", **_groups_detail_from_state()}
        if idx < 0 or idx >= len(groups):
            return {"ok": False, "error": f"Group index out of range: {idx}", **_groups_detail_from_state()}
        g = groups[idx]
        if not isinstance(g, dict):
            return {"ok": False, "error": f"Group at {idx} is not an object", **_groups_detail_from_state()}
        new_name = (name or "").strip() or f"Group {idx + 1}"
        g["name"] = new_name
        _persist_editor_state()
        return {"ok": True, **_groups_detail_from_state()}

    return _safe_run_on_tk(work)


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
    """Legacy name — deck navigates to builder view; no Tk window."""
    return {"ok": True, "deck": "builder"}


def open_groups_manager() -> dict:
    """Legacy name — deck navigates to teams view; no Tk window."""
    return {"ok": True, "deck": "teams"}


def boot_all_phones() -> dict:
    """Boot every stopped MuMu ARM phone and wait for ADB — headless, no Tk.

    Uses the same proven helpers as the classic wizard's _boot_all
    (_find_mumu_manager → _mumu_get_instances → _mumu_launch → adb connect/echo
    wait), so the deck's Boot button drives the real launch path without opening
    any Tk window or page object. Runs in a daemon thread; per-phone progress
    streams to the deck's boot log via _emit_log("boot", …).
    """
    if not _boot_all_lock.acquire(blocking=False):
        return {"ok": False, "error": "Boot already in progress", "started": False}

    def work() -> None:
        import time as _time

        from setup_wizard import (
            _find_mumu_manager,
            _mumu_get_instances,
            _mumu_launch,
            adb,
        )

        def log(msg: str) -> None:
            _emit_log("boot", msg if msg.endswith("\n") else msg + "\n")

        try:
            mgr = _find_mumu_manager()
            if not mgr:
                log("MuMu manager tool not found — install MuMuPlayer ARM first.")
                _emit_log("boot", "BOOT FAILED: no manager\n")
                return
            instances = _mumu_get_instances(mgr, log_fn=log)
            if not instances:
                log("No MuMu instances found — open MuMu once so it creates its VMs.")
                _emit_log("boot", "BOOT FAILED: no instances\n")
                return
            booted: list[str] = []
            already: list[str] = []
            failed: list[str] = []
            for inst in instances:
                idx = inst["index"]
                name = inst["name"]
                serial = inst["adb_serial"]
                if inst.get("started"):
                    log(f"{name}: already running ({serial})")
                    already.append(name)
                    continue
                log(f"{name}: launching (instance {idx})…")
                try:
                    _mumu_launch(mgr, idx, log_fn=None)
                except Exception as exc:  # noqa: BLE001 — keep booting the rest
                    log(f"{name}: launch failed: {exc}")
                    failed.append(name)
                    continue
                _time.sleep(2)
                deadline = _time.time() + 180
                up = False
                while _time.time() < deadline:
                    _time.sleep(5)
                    adb("connect", serial, timeout=8)
                    check = adb("shell", "echo", "ok", serial=serial, timeout=8)
                    up = check.strip() == "ok"
                    if up:
                        break
                if up:
                    log(f"{name}: ADB up on {serial}")
                    booted.append(name)
                else:
                    log(f"{name}: no ADB answer after 180s — moving on")
                    failed.append(name)
            total = len(booted) + len(already)
            log(f"BOOT COMPLETE: {total} phone(s) up, {len(failed)} failed.")
        except Exception as exc:  # noqa: BLE001 — never silent-fail the boot worker
            log(f"BOOT FAILED: {exc}")
            _emit_log("boot", f"BOOT FAILED: {exc}\n")
        finally:
            try:
                _boot_all_lock.release()
            except RuntimeError:
                pass

    try:
        threading.Thread(target=work, daemon=True, name="boot-all-phones").start()
    except Exception as exc:  # noqa: BLE001
        try:
            _boot_all_lock.release()
        except RuntimeError:
            pass
        return {"ok": False, "error": f"Could not start boot thread: {exc}", "started": False}
    return {"ok": True, "started": True}


def remove_group(index: int) -> dict:
    """Remove group ``index`` — same semantics as ``cursor_remove_group`` (keep ≥1)."""
    return cursor_remove_group(index)


def run_add_group() -> dict:
    """Compat wrapper — deck uses cursor_add_group (no Tk Groups window)."""
    return cursor_add_group()


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
        return {"ok": True, **_groups_detail_from_state()}

    return _safe_run_on_tk(work)


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
        return {"ok": True, "ready": ready, "server_running": running or ready}

    return _safe_run_on_tk(work)


def get_launch_summary() -> dict:
    def work() -> dict:
        page = _page(8)
        txt = ""
        try:
            txt = page._summary.get("1.0", "end").strip()
        except Exception:
            pass
        return {"ok": True, "summary": txt}

    return _safe_run_on_tk(work)


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

    return _safe_run_on_tk(work)


def get_browse_mode() -> dict:
    def work() -> dict:
        from wizard_paths import automation_on_sys_path

        automation_on_sys_path()
        import browse_proxy as bp

        m = bp.browse_proxy_mode()
        return {"ok": True, "mode": m, "label": bp.browse_proxy_mode_label(m)}

    return _safe_run_on_tk(work)


def start_server() -> dict:
    """Start the control server on the hidden Launch page — no Tk Run window."""

    def work() -> dict:
        try:
            page = launch_page()
            page.on_enter()
            if hasattr(page, "_start_server"):
                page._start_server()
            return {"ok": True, "started": True}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)[:500]}

    return _safe_run_on_tk(work)


def start_server_and_open_dashboard() -> dict:
    """Start service + open dashboard without spawning a visible Tk Run window."""

    def work() -> dict:
        try:
            page = launch_page()
            page.on_enter()
            if hasattr(page, "_start_server"):
                page._start_server()
            # _start_server is intentionally asynchronous; waiting here blocks the Tk
            # event loop and prevents the server thread's UI callbacks from running.
            opened = False
            if hasattr(page, "_open_dashboard_browser"):
                page.after(250, lambda: page._open_dashboard_browser("/"))
                opened = True
            out: dict[str, Any] = {"ok": True, "started": True, "dashboard_opened": opened}
            if not opened:
                out["message"] = "Server starting — click Open dashboard in a moment."
            return out
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)[:500]}

    return _safe_run_on_tk(work)


def run_all_groups() -> dict:
    """Boot phones (async), then start service + run groups on the Tk thread.

    No Tk Run window — progress streams to the deck go-log via LaunchPage wiring.
    Boot runs off-thread so it cannot deadlock the Tk pump; group start still
    goes through ``_safe_run_on_tk`` and returns ``{ok:false,error}`` on failure.
    """
    boot_res: dict | None = None
    boot_fn = globals().get("boot_all_phones")
    if callable(boot_fn):
        try:
            boot_res = boot_fn()
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"boot_all_phones failed: {exc}"}
        if isinstance(boot_res, dict) and boot_res.get("ok") is False:
            return {
                "ok": False,
                "error": boot_res.get("error") or "boot_all_phones failed",
                "boot": boot_res,
            }

    def work() -> dict:
        try:
            page = launch_page()
            page.on_enter()
            try:
                if hasattr(page, "_dashboard_config_reachable") and not page._dashboard_config_reachable():
                    if hasattr(page, "_start_server"):
                        page._start_server()
            except Exception as start_exc:  # noqa: BLE001 — try start anyway, keep error
                if hasattr(page, "_start_server"):
                    try:
                        page._start_server()
                    except Exception as exc2:  # noqa: BLE001
                        return {
                            "ok": False,
                            "error": f"start_server failed: {start_exc}; retry: {exc2}",
                            "boot": boot_res,
                        }
            if hasattr(page, "_run_groups"):
                page._run_groups()
            out: dict[str, Any] = {"ok": True, "started": True}
            if boot_res is not None:
                out["boot"] = boot_res
            return out
        except Exception as exc:  # noqa: BLE001
            err: dict[str, Any] = {"ok": False, "error": str(exc)[:500]}
            if boot_res is not None:
                err["boot"] = boot_res
            return err

    return _safe_run_on_tk(work)


def start_automation_one_click() -> dict:
    """One-click automation on the hidden Launch page — no Tk Run window."""
    boot_fn = globals().get("boot_all_phones")
    if callable(boot_fn):
        try:
            boot_res = boot_fn()
            if isinstance(boot_res, dict) and boot_res.get("ok") is False:
                return {
                    "ok": False,
                    "error": boot_res.get("error") or "boot_all_phones failed",
                    "boot": boot_res,
                }
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": f"boot_all_phones failed: {exc}"}

    def work() -> dict:
        try:
            page = launch_page()
            page.on_enter()
            if hasattr(page, "_start_automation_one_click"):
                page._start_automation_one_click()
            return {"ok": True, "started": True}
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc)[:500]}

    return _safe_run_on_tk(work)


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


def open_farm_dashboard() -> dict:
    """Open the live farm dashboard (127.0.0.1:8091) when it is up.

    The farm dash is the operator screen the HUD/help text already point at.
    It runs independently of the wizard control server, so the deck buttons
    must not gate on that 8080 service. Falls back to the wizard page open
    when the farm dash is unreachable.
    """
    import urllib.request
    import webbrowser

    FARM_DASH = "http://127.0.0.1:8091/"

    def _reachable(url: str) -> bool:
        try:
            with urllib.request.urlopen(url, timeout=2.5):  # noqa: S310 — loopback
                return True
        except Exception:
            return False

    def work() -> dict:
        if _reachable(FARM_DASH):
            webbrowser.open(FARM_DASH)
            return {"ok": True, "opened": True, "dashboard": FARM_DASH}
        page = launch_page()
        if bool(page._dashboard_config_reachable()):
            page._open_dashboard_browser("/")
            return {"ok": True, "opened": True}
        return {
            "ok": False,
            "error": "Dashboard is not up yet — press Start service (Run step), or start the farm first.",
            "dashboard": FARM_DASH,
        }

    return _run_on_tk(work)


def get_farm_health() -> dict:
    """Session-quality telemetry for the deck's Health view.

    Pure reader: dump-timeout / fallback-tap / paying-fill stats derived from
    the live farm log and SSP hunter state. Never touches farm state.
    """
    try:
        from automation.farm_health import snapshot

        return snapshot()
    except Exception as exc:  # noqa: BLE001 — the view must never crash
        return {"ok": False, "error": str(exc)}


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


def farm_start_in_progress() -> bool:
    return _farm_starting


def start_farm_from_app(profile_slug: str = "", hours: float = 0) -> dict:
    """Acknowledge farm startup immediately and stream the real result to Run.

    Farm helper startup can take long enough to make a synchronous WebView call
    look dead. The worker owns the blocking startup; the API returns a truthful
    ``starting`` response immediately and emits each progress/error line through
    the existing Run log callback.
    """
    from wizard.farm_control import farm_running as _fr, load_active_profile, start_farm as _sf

    global _farm_start_result, _farm_starting
    with _farm_start_lock:
        if _farm_starting:
            return {
                "ok": True,
                "starting": True,
                "message": "Farm startup is already in progress — watch the Run log.",
            }
        if _fr():
            return {
                "ok": True,
                "started": True,
                "running": True,
                "message": "Farm is already running.",
                "dashboard": "http://127.0.0.1:8091/",
            }
        _farm_starting = True
        _farm_start_result = {
            "ok": True,
            "starting": True,
            "running": False,
            "message": "Farm startup started — watch the Run log for each lane.",
        }

    def log(msg: str, level: str = "ok") -> None:
        prefix = "[farm] "
        _emit_log("go", prefix + str(msg).rstrip() + "\n")

    def work() -> None:
        global _farm_start_result, _farm_starting
        try:
            _emit_log("go", "[farm] Starting farm stack — checking profile and helper lanes…\n")
            profile = load_active_profile(profile_slug or None)
            ok = _sf(profile=profile, hours=hours or None, log=log, takeover=True)
            if ok:
                _emit_log("go", "[farm] Farm startup complete — unison, watchdog, and dashboard are live.\n")
                with _farm_start_lock:
                    _farm_start_result = {
                        "ok": True,
                        "starting": False,
                        "running": True,
                        "message": "Farm startup complete — unison, watchdog, and dashboard are live.",
                    }
            else:
                message = "Farm startup failed — see the preceding Run log lines."
                _emit_log("go", "[farm] " + message + "\n")
                with _farm_start_lock:
                    _farm_start_result = {
                        "ok": False,
                        "starting": False,
                        "running": False,
                        "error": message,
                    }
        except Exception as exc:  # noqa: BLE001 — surface to visible Run log
            message = f"Start farm error: {exc}"
            _emit_log("go", f"[farm] {message}\n")
            with _farm_start_lock:
                _farm_start_result = {
                    "ok": False,
                    "starting": False,
                    "running": False,
                    "error": message,
                }
        finally:
            with _farm_start_lock:
                _farm_starting = False

    threading.Thread(target=work, name="cpharm-farm-start", daemon=True).start()
    return {
        "ok": True,
        "starting": True,
        "message": "Farm startup started — watch the Run log for each lane.",
        "dashboard": "http://127.0.0.1:8091/",
    }


def stop_farm_from_app() -> dict:
    """Stop the unison money farm started by :func:`start_farm_from_app`."""
    from wizard.farm_control import farm_running as _fr, stop_farm as _stop

    def work() -> dict:
        global _farm_start_result
        try:
            if not _fr():
                with _farm_start_lock:
                    _farm_start_result = {
                        "ok": True,
                        "starting": False,
                        "running": False,
                        "message": "Farm is already stopped.",
                    }
                return {"ok": True, "stopped": False, "running": False, "message": "Farm is already stopped."}
            stopped = _stop()
            with _farm_start_lock:
                _farm_start_result = {
                    "ok": bool(stopped),
                    "starting": False,
                    "running": False,
                    "message": "Farm stopped." if stopped else "Farm stop did not complete.",
                }
            return {"ok": bool(stopped), "stopped": bool(stopped), "running": False}
        except Exception as exc:  # noqa: BLE001
            with _farm_start_lock:
                _farm_start_result = {
                    "ok": False,
                    "starting": False,
                    "running": False,
                    "error": f"stop_farm error: {exc}",
                }
            return {"ok": False, "error": f"stop_farm error: {exc}", "running": False}

    return _run_on_tk(work)


def spin_up_test_phone_from_app() -> dict:
    """User-clicked ONLY: bring up one phone (Docker redroid or MuMu VM) for testing.

    Delegates to wizard.farm_control.spin_up_test_phone, which never runs
    automatically and returns immediately (the boot continues in a background
    thread). Every progress line is streamed to the deck's "boot" log so the
    operator sees the phone come up live instead of a silent dead-end.
    """
    from wizard.farm_control import spin_up_test_phone as _spin

    def _phone_log(msg: str, level: str = "ok") -> None:
        _emit_log("boot", f"[test phone] {msg}\n")

    def work() -> dict:
        try:
            return _spin(log=_phone_log)
        except Exception as exc:  # noqa: BLE001 — surface to UI
            return {"ok": False, "error": f"spin_up_test_phone error: {exc}"}

    return _run_on_tk(work)


def get_machine_capabilities() -> dict:
    """Live machine + emulator inventory for the Android step (ARM64-aware).

    Bounded, best-effort scan: CPU architecture, Docker engine and redroid
    containers, MuMu instances, Studio AVDs and real USB phones — everything
    ADB answers right now. Never raises; a broken piece just reads as empty.
    """
    import platform
    import subprocess

    CREATE_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0

    def _cli(args: list[str], timeout: float = 7.0) -> tuple[int, str]:
        try:
            proc = subprocess.run(
                args,
                capture_output=True,
                text=True,
                timeout=timeout,
                creationflags=CREATE_NO_WINDOW,
            )
            return proc.returncode, (proc.stdout or "").strip()
        except Exception:
            return -1, ""

    out: dict[str, Any] = {
        "ok": True,
        "arch": "x64",
        "arch_label": "x64 (Intel/AMD)",
        "docker": False,
        "redroid": {"up": 0, "total": 0},
        "mumu": {"instances": 0, "online": 0},
        "avd_online": 0,
        "usb_online": 0,
        "tcp_online": 0,
        "phones_online": 0,
        "phones": [],
    }

    mach = (platform.machine() or "").upper()
    if "ARM" in mach or "AARCH" in mach:
        out["arch"] = "arm64"
        out["arch_label"] = "ARM64 (Snapdragon)"

    # Docker engine + redroid containers.
    redroid_names: list[str] = []
    code, text = _cli(
        [
            "docker",
            "ps",
            "-a",
            "--filter",
            "name=redroid-",
            "--format",
            "{{.Names}}|{{.Status}}",
        ]
    )
    if code == 0 and text:
        out["docker"] = True
        for line in text.splitlines():
            name, _, status = line.partition("|")
            name = (name or "").strip()
            if not name:
                continue
            redroid_names.append(name)
            out["redroid"]["total"] += 1
            status_l = (status or "").lower()
            if status_l and not status_l.startswith(("exited", "created", "dead")):
                out["redroid"]["up"] += 1

    # MuMu instances (offline + online) — tolerant; MuMu may not be installed.
    mumu_live: list[str] = []
    try:
        from wizard.mumu_farm_ops import MuMuFarmOps
    except Exception:  # noqa: BLE001
        try:
            from mumu_farm_ops import MuMuFarmOps  # type: ignore[no-redef]
        except Exception:  # noqa: BLE001
            MuMuFarmOps = None  # type: ignore[assignment]
    if MuMuFarmOps is not None:
        try:
            farm = MuMuFarmOps()
        except Exception:
            farm = None
        if farm is not None:
            try:
                out["mumu"]["instances"] = len(list(farm.list_instances() or []))
            except Exception:
                pass
            try:
                mumu_live = [
                    str(d.serial)
                    for d in farm.enumerate_adb_devices()
                    if getattr(d, "online", False)
                ]
            except Exception:
                mumu_live = []
    out["mumu"]["online"] = len(mumu_live)

    # ADB inventory.
    devices: list[Any] = []
    try:
        from automation.adb_wrapper import AdbWrapper

        devices = list(AdbWrapper().devices_detailed() or [])
    except Exception:
        devices = []

    redroid_ports = {5555 + idx for idx in range(len(redroid_names))}
    phones: list[dict[str, Any]] = []
    for d in devices:
        serial = str(getattr(d, "serial", "") or "")
        if not serial:
            continue
        online = bool(getattr(d, "online", False))
        kind = "phone"
        if serial.startswith("emulator-"):
            kind = "AVD"
        elif serial.startswith("127.0.0.1:"):
            try:
                port = int(serial.rsplit(":", 1)[1])
            except (ValueError, IndexError):
                port = -1
            if port in redroid_ports:
                kind = "redroid"
            elif serial.startswith("127.0.0.1:16"):
                kind = "MuMu"
            else:
                kind = "emu/TCP"
        elif ":" in serial:
            kind = "emu/TCP"
        else:
            kind = "USB"
        if online:
            if kind == "AVD":
                out["avd_online"] += 1
            elif kind == "USB":
                out["usb_online"] += 1
            elif kind == "emu/TCP":
                out["tcp_online"] += 1
        phones.append({"serial": serial, "kind": kind, "online": online})
    out["phones"] = phones
    out["phones_online"] = sum(1 for p in phones if p["online"])
    return out


def farm_status_from_app() -> dict:
    """Lightweight farm status for the Run page."""
    from wizard.farm_control import farm_running as _fr, external_python_farm_running as _ex

    def work() -> dict:
        try:
            running = bool(_fr())
            external = bool(_ex())
            with _farm_start_lock:
                result = dict(_farm_start_result)
                starting = bool(_farm_starting)
            if running or external:
                result.update({"ok": True, "running": True, "starting": False})
            elif starting:
                result.setdefault("ok", True)
                result["running"] = False
                result["starting"] = True
            else:
                result.setdefault("ok", True)
                result.setdefault("running", False)
                result.setdefault("starting", False)
            result["external"] = external
            result["dashboard"] = "http://127.0.0.1:8091/"
            return result
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "error": str(exc), "running": False, "starting": False}

    return _run_on_tk(work)


def get_farm_hud() -> dict:
    """Compact live telemetry for the wizard HUD strip (phones / income / state).

    Runs on the caller's thread (never the tk loop) so a 15s HUD poll can
    never freeze the GUI, and never raises: the HUD must stay live even when
    the farm is down or ADB is wedged.
    """
    out: dict[str, Any] = {
        "ok": True,
        "farm": "off",
        "running": False,
        "external": False,
        "phones_online": 0,
        "revenue_today_usd": 0.0,
        "clicks": 0,
        "impressions": 0,
        "ecpm": 0.0,
        "as_of": "",
        "dashboard": "http://127.0.0.1:8091/",
    }

    try:
        from wizard.farm_control import external_python_farm_running as _ex
        from wizard.farm_control import farm_running as _fr

        out["running"] = bool(_fr())
        out["external"] = bool(_ex())
        out["farm"] = "run" if (out["running"] or out["external"]) else "off"
    except Exception:  # noqa: BLE001 — HUD is best-effort
        pass

    try:
        from automation.scorecard_api import _live_farm_facts

        facts = _live_farm_facts() or {}
        out["revenue_today_usd"] = round(float(facts.get("payout_usd") or 0.0), 2)
        out["clicks"] = int(facts.get("clicks") or 0)
        out["impressions"] = int(facts.get("impressions") or 0)
        out["ecpm"] = float(facts.get("ecpm") or 0.0)
        out["as_of"] = str(facts.get("source") or "")
    except Exception:  # noqa: BLE001
        pass

    try:
        from wizard.wizard_paths import bundled_adb_path

        exe = str(bundled_adb_path())
        r = subprocess.run(
            [exe, "devices"],
            capture_output=True,
            text=True,
            timeout=6,
            errors="replace",
        )
        n = 0
        for line in (r.stdout or "").splitlines()[1:]:
            parts = line.split()
            if len(parts) >= 2 and parts[1] == "device":
                n += 1
        out["phones_online"] = n
    except Exception:  # noqa: BLE001
        pass

    return out
