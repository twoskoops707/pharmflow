"""Hidden tk backend — reuses setup_wizard pages for WebView UI actions."""
from __future__ import annotations

import copy
import json
import os
import platform
import psutil
import queue
import re
import subprocess
import sys
import threading
import time
import tkinter as tk
import urllib.request
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo
from typing import Any, Callable

from setup_wizard import PharmFlowWizard
from wizard_theme import _style_scrollbars

# Boot-order host gates (scaling plan): CPU/RAM headroom before each VM launch.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from automation import boot_gates as boot_gate  # noqa: E402
import docker_guard  # noqa: E402

# Mirrors PharmFlowWizard.PAGE_NAMES / PAGE_SUBTITLES (order matters).
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

# Deck has 10 steps (includes native "map"); PharmFlowWizard.PAGES has 9 Tk pages.
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
    """Map a deck step id/index to a PharmFlowWizard.PAGES index (or None if deck-only)."""
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
    """Called from pharmflow_app_webview so tk sub-windows can sit above WebView2."""
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
_boot_all_started_mono: float | None = None
_boot_all_thread: threading.Thread | None = None
_boot_all_cancel = threading.Event()
_boot_result_lock = threading.Lock()
_boot_all_result: dict[str, Any] = {"ok": True, "starting": False}
_cloud_result_lock = threading.Lock()
_cloud_result: dict[str, Any] = {"ok": True, "starting": False}
_cloud_thread: threading.Thread | None = None
_agent_run_lock = threading.Lock()
_agent_run_result: dict[str, Any] = {"ok": True, "starting": False}
_agent_run_thread: threading.Thread | None = None
_BOOT_LOCK_STALE_S = 600.0  # force-steal if boot worker hangs >10m (OPS_NOTES)
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
    """Open a visible wizard window in its own process. In-process Tcl dies under WebView2."""
    step_id = str(step_id or "steps").strip().lower()
    page_idx = _tk_page_index_for_step(step_id)
    if page_idx is None:
        return {"ok": True, "deck": step_id, "mode": "deck"}
    return _spawn_visible_wizard(int(page_idx), auto_action or "")

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
        from pharmflow_version import instance_title
        parent.title(instance_title("PharmFlow"))
    except Exception:
        parent.title("PharmFlow")
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
        return getattr(win, "_pharmflow_page", None)
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
    page_cls = sw.PharmFlowWizard.PAGES[page_index]
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
        setattr(win, "_pharmflow_page", page)
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
            root.title("PharmFlow backend")
            root.withdraw()
            host = tk.Frame(root)
            host.pack()
            wiz = PharmFlowWizard(host)
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
            _boot_error = f"PharmFlow backend failed to start: {exc}"
            _ready.set()

    threading.Thread(target=boot, name="pharmflow-tk-bridge", daemon=True).start()
    _ready.wait(timeout=120)
    if _boot_error:
        raise RuntimeError(_boot_error)
    if _wizard is None:
        raise RuntimeError("PharmFlow backend did not start in time — restart the app.")


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


def _run_direct(fn: Callable, *args, **kwargs) -> Any:
    """Run deck work on the caller thread. Never touch the Tk pump.

    The frozen EXE owns the process main thread with WebView2. Tcl/Tk created
    on a background thread dies with ``main thread is not in main loop``, and
    every later button then sits in ``_call_queue`` until the 600s timeout.
    State, disk, ADB, and localhost calls do not need a widget.
    """
    try:
        return fn(*args, **kwargs)
    except Exception as exc:  # noqa: BLE001 — surface to the WebView as an error dict
        return {"ok": False, "error": str(exc)[:500]}


_dashboard_proc: subprocess.Popen | None = None
_dashboard_thread: threading.Thread | None = None
_dashboard_lock = threading.Lock()
_service_start_lock = threading.Lock()
_service_start_result: dict[str, Any] = {"ok": True, "starting": False}
_groups_run_lock = threading.Lock()
_groups_run_result: dict[str, Any] = {"ok": True, "starting": False}


def _host_python_argv() -> tuple[list[str], str]:
    """Real CPython for dashboard.py. Empty argv means none was found.

    The frozen EXE is not an interpreter. Never return an unprobed ``python``
    name — Windows then opens the Store stub or fails, and the deck used to
    report the service as started anyway.
    """
    from farm_control import _is_frozen_app_exe, _resolve_helper_python
    from setup_wizard import _probe_python_cmd, _resolve_python_cmd, state

    # Frozen: do not ask setup_wizard to probe sys.executable. That is this EXE,
    # and its --version path still allocates a console before it prints.
    if not getattr(sys, "frozen", False):
        argv, disp = _resolve_python_cmd(state.get("python_cmd"))
        if argv and not _is_frozen_app_exe(str(argv[0])) and _probe_python_cmd(list(argv)):
            return list(argv), disp

    helper = _resolve_helper_python(requires="websockets")
    if helper and not _is_frozen_app_exe(helper) and _probe_python_cmd([helper]):
        state["python_cmd"] = helper
        state["python_cmd_argv"] = [helper]
        return [helper], helper
    return [], ""


def _pharmflow_dir() -> str:
    from setup_wizard import _pharmflow_install_root, state

    d = str(state.get("pharmflow_dir") or "").strip()
    if not d:
        d = str(_pharmflow_install_root())
        state["pharmflow_dir"] = d
    return d


def _dashboard_post(path: str, body: dict | None = None, timeout: float = 12) -> dict:
    """POST to the local dashboard. Same contract as LaunchPage._api, no widgets."""
    import urllib.error
    import urllib.request

    from setup_wizard import dashboard_base_url, probe_dashboard_listen_port

    payload = json.dumps(body or {}).encode()
    delay = 0.35
    last_err: Exception | None = None
    retried_probe = False
    for attempt in range(6):
        url = f"{dashboard_base_url()}{path}"
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 — loopback
                parsed = json.loads(r.read().decode())
            return parsed if isinstance(parsed, dict) else {"ok": True, "data": parsed}
        except urllib.error.HTTPError as e:
            try:
                raw = e.read().decode("utf-8", errors="replace")
                parsed = json.loads(raw)
                if isinstance(parsed, dict) and parsed.get("error"):
                    return parsed
            except Exception:
                pass
            return {"error": str(e)}
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as e:
            last_err = e
            err_s = str(e).lower()
            refused = "10061" in str(e) or "refused" in err_s or "actively refused" in err_s
            if refused and not retried_probe:
                retried_probe = True
                if probe_dashboard_listen_port():
                    continue
            if attempt < 5 and (refused or "timed out" in err_s):
                time.sleep(delay)
                delay = min(delay * 1.65, 2.8)
                continue
            if refused:
                return {"error": "The server is not running. On Go, tap Start service first."}
            return {"error": str(e)}
    if last_err and ("10061" in str(last_err) or "refused" in str(last_err).lower()):
        return {"error": "The server is not running. On Go, tap Start service first."}
    return {"error": str(last_err) if last_err else "Could not reach the server"}


def _python_imports_ok(py_argv: list[str], modules: str) -> bool:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    try:
        chk = subprocess.run(
            py_argv + ["-c", modules],
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=flags,
        )
        return chk.returncode == 0
    except Exception:
        return False


def _start_dashboard_inprocess() -> bool:
    """Run the control server inside this process when no CPython exists.

    A frozen PharmFlow.exe cannot ``Popen`` itself as ``python dashboard.py``.
    The module is already in the bundle, so the same ``main()`` the script
    runs under ``__main__`` runs on a daemon thread instead.
    """
    global _dashboard_thread
    if _dashboard_thread is not None and _dashboard_thread.is_alive():
        return True

    def _target() -> None:
        try:
            import asyncio

            from automation.dashboard import main as dashboard_main

            asyncio.run(dashboard_main())
        except Exception as exc:  # noqa: BLE001 — surfaced via the ready probe
            _emit_log("go", f"In-process dashboard failed: {exc}\n")

    _dashboard_thread = threading.Thread(
        target=_target,
        name="pharmflow-dashboard",
        daemon=True,
    )
    _dashboard_thread.start()
    _emit_log("go", "Control server started inside PharmFlow.exe (no host Python).\n")
    return True


def _start_dashboard_headless() -> dict:
    """Launch automation/dashboard.py. No Tk page, no messagebox, no self.after."""
    global _dashboard_proc
    from setup_wizard import (
        _DASHBOARD_SPAWN_FLAGS,
        _dashboard_ready_timeout_sec,
        clear_dashboard_listen_port_cache,
        probe_dashboard_listen_port,
    )

    proc: subprocess.Popen | None = None
    with _dashboard_lock:
        if probe_dashboard_listen_port():
            return {"ok": True, "started": True, "already_running": True, "ready": True}
        alive = _dashboard_proc is not None and _dashboard_proc.poll() is None
        thread_alive = _dashboard_thread is not None and _dashboard_thread.is_alive()
        if alive or thread_alive:
            proc = _dashboard_proc if alive else None
        else:
            root = _pharmflow_dir()
            dashboard = Path(root) / "automation" / "dashboard.py"
            if not dashboard.is_file():
                alt = Path(r"C:\PharmFlow") / "automation" / "dashboard.py"
                if alt.is_file():
                    dashboard = alt

            clear_dashboard_listen_port_cache()
            py_argv, py_disp = _host_python_argv()
            if not py_argv:
                if not _start_dashboard_inprocess():
                    return {
                        "ok": False,
                        "error": "No CPython found and the control server could not start inside PharmFlow.exe",
                    }
            else:
                if not dashboard.is_file():
                    return {"ok": False, "error": f"dashboard.py not found at {dashboard}"}
                _emit_log("go", f"Using Python: {py_disp}\n")
                dep_stmt = "import websockets, psutil"
                if not _python_imports_ok(py_argv, dep_stmt):
                    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
                    try:
                        pip = subprocess.run(
                            py_argv + ["-m", "pip", "install", "--quiet", "--user", "websockets>=12.0", "psutil>=5.9.0"],
                            capture_output=True,
                            text=True,
                            timeout=120,
                            creationflags=flags,
                        )
                    except OSError as exc:
                        return {"ok": False, "error": f"Cannot start dashboard: {exc}"}
                    if pip.returncode != 0 and not _python_imports_ok(py_argv, dep_stmt):
                        err = (pip.stderr or pip.stdout or "pip failed").strip()[-400:]
                        return {"ok": False, "error": f"Cannot start dashboard: {err}"}

                launch_cmd = py_argv + [str(dashboard)]
                _emit_log("go", f"Launch command: {' '.join(launch_cmd)}\n")
                flags = _DASHBOARD_SPAWN_FLAGS
                # CREATE_NO_WINDOW and DETACHED_PROCESS together are ignored by Windows
                # and a console flashes. Hide the console; do not detach.
                if sys.platform == "win32":
                    flags = int(getattr(subprocess, "CREATE_NO_WINDOW", 0))
                try:
                    proc = subprocess.Popen(
                        launch_cmd,
                        cwd=str(dashboard.parent),
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        creationflags=flags,
                    )
                except OSError as exc:
                    return {"ok": False, "error": f"Cannot start dashboard: {exc}"}
                _dashboard_proc = proc

    ready_sec = float(_dashboard_ready_timeout_sec())
    deadline = time.time() + ready_sec
    while time.time() < deadline:
        if proc is not None and proc.poll() is not None:
            return {"ok": False, "error": f"Dashboard exited immediately (code {proc.returncode})"}
        if proc is None and _dashboard_thread is not None and not _dashboard_thread.is_alive():
            return {"ok": False, "error": "In-process dashboard exited before it answered"}
        if probe_dashboard_listen_port():
            _emit_log("go", "Dashboard is up.\n")
            return {"ok": True, "started": True, "ready": True}
        time.sleep(0.45)
    return {"ok": False, "error": f"Dashboard did not answer /api/config within {int(ready_sec)}s"}


def _open_browser(url: str) -> bool:
    """Open a URL. False means the browser did not start — callers must not claim it did."""
    import webbrowser

    try:
        return bool(webbrowser.open(url))
    except Exception as exc:  # noqa: BLE001 — the button must see the failure
        _emit_log("go", f"Could not open browser for {url}: {exc}\n")
        return False


def _boot_then_continue() -> dict:
    """Start boot. An already-running boot is success, not a hard stop."""
    boot_res = boot_all_phones()
    if not isinstance(boot_res, dict):
        return {"ok": True, "boot": boot_res}
    if boot_res.get("ok") is not False:
        return boot_res
    err = str(boot_res.get("error") or "")
    if boot_res.get("already_booting") or "already in progress" in err.lower():
        _emit_log("boot", "Boot already running — continuing.\n")
        return {"ok": True, "already_booting": True, "boot": boot_res}
    return boot_res


def _spawn_visible_wizard(page_index: int, action: str) -> dict:
    """Tk-bound setup (install/SDK/create) runs in its own process main thread."""
    spawned = _spawn_wizard_page(page_index, action=action)
    if spawned.get("window_ready"):
        return {
            "ok": True,
            "started": True,
            "spawned": True,
            "window_ready": True,
            "page": page_index,
            "action": action,
            "message": spawned.get("message")
            or "Opened a wizard window — progress shows there, not in a hidden thread.",
        }
    if spawned.get("ok") and spawned.get("started"):
        return {
            "ok": True,
            "started": True,
            "spawned": True,
            "window_ready": False,
            "page": page_index,
            "action": action,
            "message": spawned.get("message")
            or "Wizard process started. The window is not up yet.",
        }
    return {
        "ok": False,
        "error": spawned.get("error") or "Could not open wizard window",
        "started": False,
        "window_ready": False,
    }


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
    """Deck already switched the view. Do not start a background Tk backend.

    Calling ``wizard()._show`` from here used to construct Tcl on a worker
    thread. When that mainloop died, every later button waited 600s.
    """
    deck_idx, err = _as_index(index, label="page index")
    if err or deck_idx is None:
        return {"ok": False, "error": err or "Invalid page index"}
    step = WIZARD_STEPS[deck_idx] if 0 <= deck_idx < len(WIZARD_STEPS) else {}
    return {
        "ok": True,
        "index": deck_idx,
        "id": step.get("id", "") if step else "",
        "tk": False,
    }


def navigate_wizard_step(step_id: str) -> dict:
    sid = str(step_id or "").strip().lower()
    idx = _STEP_ID_TO_INDEX.get(sid, 0)
    return navigate_wizard_page(idx)


def open_advanced_wizard() -> None:
    navigate_app_view("teams")


def navigate_app_view(view: str) -> None:
    from pharmflow_app_webview import emit_app_view

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
    # Do not run the full setup scan (it connects every guest and stalled the
    # deck). A marker file is not a live phone. One short adb devices is enough
    # to know whether Phones is done. A hung adb must not stall the buttons.
    try:
        import mumu_setup_core as msc
        import preflight_core as pc

        root = msc.data_root()
        setup_done = pc.mumu_setup_already_done(root)
        awaiting = bool(msc.setup_awaiting_cold_boot(root))
        live = False
        if setup_done and not awaiting:
            live = bool(pc.list_adb_phones(timeout=4))
        setup_ready = bool(setup_done and live and not awaiting)
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
    """Install checklist without constructing the Install page."""
    from pathlib import Path as _Path

    from setup_wizard import (
        _automation_bundle_missing,
        _pharmflow_install_root,
        _find_pharmflow_dashboard_root,
        _find_java_home,
        _probe_python_cmd,
        _resolve_python_cmd,
        run_cmd,
        state,
    )

    def _java() -> bool:
        if _find_java_home():
            return True
        ok, _out = run_cmd(["java", "-version"])
        return bool(ok)

    def _python() -> bool:
        py_argv, _disp = _resolve_python_cmd(state.get("python_cmd"))
        return bool(_probe_python_cmd(py_argv))

    def _packages() -> bool:
        py_argv, py_disp = _resolve_python_cmd(state.get("python_cmd"))
        if not _probe_python_cmd(py_argv):
            return False
        state["python_cmd"] = py_disp
        state["python_cmd_argv"] = list(py_argv)
        ok, _out = run_cmd(
            py_argv
            + [
                "-c",
                "import websockets, psutil, socks; from zoneinfo import ZoneInfo; ZoneInfo('UTC')",
            ]
        )
        return bool(ok)

    def _tor() -> bool:
        from pathlib import Path as _P

        candidates = []
        d = str(state.get("pharmflow_dir") or "")
        if d:
            candidates.append(_P(d) / "automation" / "tor" / "tor.exe")
        try:
            candidates.append(_pharmflow_install_root() / "automation" / "tor" / "tor.exe")
        except Exception:
            pass
        candidates.extend(
            [
                _P(r"C:\PharmFlow\automation\tor\tor.exe"),
                _P(r"C:\PharmFlow\bundled\tor.exe"),
                _P(r"C:\Tor\tor.exe"),
                _P(r"C:\Program Files\Tor\tor.exe"),
            ]
        )
        return any(p.is_file() for p in candidates)

    def _pharmflow() -> bool:
        d = str(state.get("pharmflow_dir") or "")
        candidates: list[_Path] = []
        if d:
            candidates.append(_Path(d).resolve())
        try:
            candidates.append(_pharmflow_install_root())
        except Exception:
            pass
        for p in candidates:
            if (p / "automation" / "dashboard.py").is_file() and not _automation_bundle_missing(p):
                state["pharmflow_dir"] = str(p)
                return True
            nested = _find_pharmflow_dashboard_root(p)
            if nested and not _automation_bundle_missing(nested):
                state["pharmflow_dir"] = str(nested)
                return True
        return False

    rows: list[dict] = []
    for key, label, fn in (
        ("java", "Java (helper)", _java),
        ("python", "Python (helper)", _python),
        ("packages", "Extra bits", _packages),
        ("tor", "Safe internet (Tor)", _tor),
        ("pharmflow", "PharmFlow files", _pharmflow),
    ):
        ok = False
        try:
            ok = bool(fn())
        except Exception:
            ok = False
        rows.append({"key": key, "label": label, "ok": ok})
    return rows


def run_install_all() -> dict:
    """Start the full install. Already-done is a file check; the worker is a
    visible wizard process whose main thread owns Tcl (in-process Tk cannot).
    """
    rows = scan_prereqs()
    if rows and all(r.get("ok") for r in rows):
        return {"ok": True, "started": False, "busy": False, "already_installed": True}
    return _spawn_visible_wizard(1, "install_all")


def get_android_status() -> dict:
    """SDK/ADB readiness. Selecting MuMu is not an installed Android SDK."""
    from pathlib import Path

    from setup_wizard import find_sdk, sdk_tool, state

    sdk = find_sdk() or ""
    stored = str(state.get("sdk_path") or "")
    if not sdk and stored and Path(stored, "platform-tools").is_dir():
        sdk = stored
    use_mumu = bool(state.get("use_mumu"))
    adb = ""
    try:
        adb = str(sdk_tool("adb") or "")
    except Exception:
        adb = ""
    if (not adb or not Path(adb).is_file()) and sdk:
        for name in ("adb.exe", "adb"):
            cand = Path(sdk) / "platform-tools" / name
            if cand.is_file():
                adb = str(cand)
                break
    adb_ok = bool(adb) and Path(adb).is_file()
    ready = adb_ok
    if adb_ok:
        status = "Ready"
        detail = adb
    elif sdk:
        status = "ADB missing"
        detail = str(sdk)
    elif use_mumu:
        status = "SDK not installed"
        detail = "MuMu is selected. Studio AVDs and USB phones still need the Android SDK."
    else:
        status = "Not installed"
        detail = ""
    return {
        "ok": True,
        "sdk_path": str(sdk) if sdk else "",
        "use_mumu": use_mumu,
        "ready": ready,
        "status": status,
        "detail": detail,
        "working": False,
    }


def run_android_install() -> dict:
    status = get_android_status()
    if status.get("ready") and status.get("sdk_path"):
        return {"ok": True, "started": False, "already_installed": True, "message": "Android SDK already found."}
    return _spawn_visible_wizard(2, "android_install")


def set_phone_farm_count(count: int) -> dict:
    from setup_wizard import state

    n = int(count)
    state["num_phones"] = n
    return {"ok": True, "count": n}


def run_create_phone_farm() -> dict:
    return _spawn_visible_wizard(3, "create_phones")


def run_test_url(url: str | None = None) -> dict:
    from site_prefs import load_target_site_url, save_target_site_url
    from setup_wizard import chrome_open_url, state

    _prepare_editor_state()
    phones = state.get("phones") or []
    if not phones:
        return {
            "ok": False,
            "error": (
                "No phones are answering ADB. Press Boot all phones, wait for the Android home, "
                "then Check again. A phone that is already open needs USB debugging ON."
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
    opened: list[dict] = []
    failed: list[dict] = []
    for phone in phones:
        if isinstance(phone, dict):
            serial = str(phone.get("serial") or "").strip()
            name = str(phone.get("name") or serial)
        else:
            serial = str(phone or "").strip()
            name = serial
        if not serial:
            failed.append({"name": name or "phone", "error": "missing serial"})
            continue
        try:
            ok, note = chrome_open_url(serial, test_url)
        except Exception as exc:
            failed.append({"serial": serial, "name": name, "error": str(exc)})
            _emit_log("boot", f"Could not open {test_url} on {name}: {exc}\n")
            continue
        if ok:
            opened.append({"serial": serial, "name": name, "note": note or ""})
            _emit_log("boot", f"Opened {test_url} on {name} ({serial}).\n")
        else:
            failed.append({"serial": serial, "name": name, "error": note or "Phone did not open a browser."})
            _emit_log("boot", f"Could not open {test_url} on {name}: {note or 'unknown'}\n")
    if not opened:
        first = failed[0]["error"] if failed else "Phone did not open a browser."
        return {
            "ok": False,
            "error": first if len(failed) <= 1 else f"Opened on 0 phone(s). Failed on {len(failed)}: {first}",
            "url": test_url,
            "opened": 0,
            "failed": len(failed),
            "failures": failed,
        }
    out = {
        "ok": not failed,
        "url": test_url,
        "opened": len(opened),
        "failed": len(failed),
        "serials": [row["serial"] for row in opened],
        "failures": failed,
        "note": opened[0].get("note") or "",
    }
    if failed:
        out["error"] = f"Opened on {len(opened)} phone(s). Failed on {len(failed)}."
    else:
        out["message"] = f"Opened on {len(opened)} phone(s)."
    return out


def get_site_settings() -> dict:
    from site_prefs import load_target_site_url, site_display_host

    u = load_target_site_url()
    return {"ok": True, "url": u, "host": site_display_host(u)}


def save_site_url(url: str) -> dict:
    from site_prefs import load_target_site_url, save_target_site_url, site_display_host

    requested = str(url or "").strip()
    if not requested:
        return {"ok": False, "error": "Enter a site URL first."}
    u = save_target_site_url(requested)
    stored = load_target_site_url()
    if not stored or stored != u:
        return {"ok": False, "error": "Site URL was not saved on disk."}
    return {"ok": True, "saved": True, "url": stored, "host": site_display_host(stored)}


_scan_lock = threading.Lock()
_scan_active = False
_scan_result: dict = {"ok": True, "starting": False}


def _set_scan_result(payload: dict) -> None:
    global _scan_result
    with _scan_lock:
        _scan_result = dict(payload)


def scan_site_status() -> dict:
    """Last site map. ``starting`` means the crawl is still running."""
    with _scan_lock:
        out = dict(_scan_result)
        active = _scan_active
    if out.get("starting") and not active:
        return {
            "ok": False,
            "starting": False,
            "error": "Site map stopped before it reported a result.",
        }
    return out


def last_completed_scan(url: str = "") -> dict | None:
    """Finished map for this URL, or None if missing, running, or failed."""
    from site_mapper import normalize_url

    target = normalize_url(url or "")
    if not target:
        return None
    status = scan_site_status()
    if status.get("starting") or not status.get("ok"):
        return None
    if normalize_url(str(status.get("start_url") or "")) != target:
        return None
    return status


def scan_site(url: str = "") -> dict:
    """Start a same-host crawl off the deck thread. Poll ``scan_site_status``."""
    global _scan_active

    from site_mapper import normalize_url, scan_site as _scan

    target = normalize_url(url or "")
    if not target:
        return {"ok": False, "error": "Enter a valid URL like https://example.com"}
    with _scan_lock:
        if _scan_active:
            return {
                "ok": True,
                "started": False,
                "busy": True,
                "starting": True,
                "message": "A site map is already running — wait for it to finish.",
            }
        _scan_active = True
    _set_scan_result(
        {
            "ok": True,
            "starting": True,
            "start_url": target,
            "message": "Scanning " + target,
        }
    )

    def _run() -> None:
        global _scan_active
        try:
            result = _scan(target)
            if not isinstance(result, dict):
                result = {"ok": False, "error": "Site map returned no result."}
            result = dict(result)
            result["starting"] = False
            _set_scan_result(result)
        except Exception as exc:  # noqa: BLE001 — surface as error dict
            _set_scan_result(
                {"ok": False, "starting": False, "error": str(exc)[:300], "start_url": target}
            )
        finally:
            with _scan_lock:
                if _scan_result.get("starting"):
                    _scan_result = {
                        "ok": False,
                        "starting": False,
                        "error": "Site map stopped before it reported a result.",
                        "start_url": target,
                    }
                _scan_active = False

    try:
        threading.Thread(target=_run, name="pharmflow-site-map", daemon=True).start()
    except Exception as exc:  # noqa: BLE001
        with _scan_lock:
            _scan_active = False
        msg = f"Site map did not start: {exc}"
        _set_scan_result({"ok": False, "starting": False, "error": msg})
        return {"ok": False, "started": False, "error": msg}
    return {
        "ok": True,
        "started": True,
        "starting": True,
        "message": "Scanning " + target,
    }


def apply_site_sequence(url: str = "") -> dict:
    """Scan a site, generate a starter sequence draft, save it, and make it
    the default sequence (the same state the Steps step reads)."""

    def commit(steps: list, path: str, draft: dict) -> dict:
        from setup_wizard import (
            _apply_default_steps_to_template_phones,
            _groups_have_assigned_phones,
            _persist_default_steps,
            _persist_groups_config,
            groups_config_path,
            state,
        )
        from wizard_paths import default_sequence_path

        before_groups, before_steps = _editor_snapshot()
        steps_path = default_sequence_path()
        groups_path = groups_config_path()
        prev_steps = _read_text(steps_path)
        need_groups = _groups_have_assigned_phones()
        prev_groups = _read_text(groups_path) if need_groups else None
        starter = Path(path)

        state["default_steps"] = list(steps)
        _apply_default_steps_to_template_phones()
        # Do not call the groups writer when no phones are assigned: that path
        # discovers ADB and can hang with zero devices.
        steps_written = _persist_default_steps()
        groups_written = _persist_groups_config() if need_groups else None
        steps_ok = bool(steps_written) and _disk_matches(
            steps_path, {"steps": list(state.get("default_steps") or [])}
        )
        groups_ok = (not need_groups) or (
            bool(groups_written) and _disk_groups_match(groups_path, list(state.get("groups") or []))
        )
        starter_ok = _disk_matches(starter, list(steps))
        if steps_ok and groups_ok and starter_ok:
            return {
                "ok": True,
                "saved": True,
                "steps": len(steps),
                "path": path,
                "note": draft["note"],
                "pages_mapped": draft["pages_mapped"],
            }
        _restore_text(steps_path, prev_steps)
        if need_groups:
            _restore_text(groups_path, prev_groups)
        try:
            starter.unlink()
        except OSError:
            pass
        state["groups"] = before_groups
        state["default_steps"] = before_steps
        return {"ok": False, "error": "Starter sequence was not saved on disk."}

    try:
        from site_mapper import build_starter_sequence, normalize_url, save_sequence
        from wizard_paths import app_data_root

        target = normalize_url(url or "")
        if not target:
            return {"ok": False, "error": "Enter a valid URL like https://example.com"}
        mapped = last_completed_scan(target)
        if not mapped:
            return {
                "ok": False,
                "error": (
                    "Scan the site first. The starter sequence is built from the "
                    "pages that were actually read, not a second silent crawl."
                ),
            }
        draft = build_starter_sequence(target, pages=list(mapped.get("pages") or []))
        steps = draft["steps"]
        host = target.split("//", 1)[-1].split("/", 1)[0]
        out_dir = app_data_root() / "sequences" / "site_scans"
        path = save_sequence(steps, host, output_dir=out_dir)
        return commit(steps, str(path), draft)
    except Exception as exc:  # noqa: BLE001 — surface as error dict
        return {"ok": False, "error": str(exc)[:300]}


def _earn_params(raw: dict | None) -> dict:
    body = raw if isinstance(raw, dict) else {}
    return {
        "phones": body.get("phones"),
        "visits_per_phone": body.get("visits_per_phone"),
        "target_usd": body.get("target_usd"),
        "ecpm": body.get("ecpm"),
        "impressions_per_visit": body.get("impressions_per_visit"),
        "path2_share": body.get("path2_share"),
        "ads_allowed": body.get("ads_allowed"),
        "visits_per_paid_action": body.get("visits_per_paid_action"),
        "awake_hours": body.get("awake_hours"),
    }


def get_earn_plan() -> dict:
    """Saved mix, or an empty form. Does not invent a phone count."""
    from automation.earn_plan import load_earn_plan

    plan = load_earn_plan()
    if not plan:
        return {"ok": True, "saved": False}
    return plan


def preview_earn_plan(params: dict | None = None) -> dict:
    from automation.earn_plan import compute_earn_plan

    return compute_earn_plan(_earn_params(params))


def save_earn_plan(params: dict | None = None) -> dict:
    from automation.earn_plan import save_earn_plan as _save

    return _save(_earn_params(params))


def _reload_persisted_wizard_state() -> None:
    from setup_wizard import _try_load_groups_config

    _try_load_groups_config()


def _prepare_editor_state() -> None:
    from setup_wizard import _pharmflow_install_root, list_adb_devices, state

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
    if not state.get("pharmflow_dir"):
        try:
            state["pharmflow_dir"] = str(_pharmflow_install_root())
        except Exception:
            pass


def _persist_editor_state() -> None:
    from setup_wizard import _persist_groups_config

    _persist_groups_config()


def _editor_snapshot() -> tuple[list, list]:
    from setup_wizard import state

    return (
        copy.deepcopy(list(state.get("groups") or [])),
        copy.deepcopy(list(state.get("default_steps") or [])),
    )


def _commit_editor_state(
    *,
    require_groups: bool,
    require_steps: bool,
    before_groups: list | None = None,
    before_steps: list | None = None,
) -> str | None:
    """Write editor state, then keep the change only if disk matches memory.

    ``_persist_groups_config`` returns None and skips the groups file when no
    phone is assigned.     Callers used to treat that as saved.
    """
    from setup_wizard import (
        _groups_have_assigned_phones,
        _persist_groups_config,
        groups_config_path,
        state,
    )
    from wizard_paths import default_sequence_path

    steps_path = default_sequence_path()
    groups_path = groups_config_path()
    prev_steps = _read_text(steps_path)
    prev_groups = _read_text(groups_path)
    _persist_groups_config()

    errors: list[str] = []
    if require_steps and not _disk_matches(steps_path, {"steps": list(state.get("default_steps") or [])}):
        errors.append("Sequence was not saved on disk.")
    if require_groups:
        if not _groups_have_assigned_phones():
            errors.append(
                "Group was not saved — no phones are assigned. Set up phones, then try again."
            )
        elif not _disk_groups_match(groups_path, list(state.get("groups") or [])):
            errors.append("Group was not saved on disk.")
    if not errors:
        return None
    _restore_text(steps_path, prev_steps)
    _restore_text(groups_path, prev_groups)
    if before_groups is not None:
        state["groups"] = before_groups
    if before_steps is not None:
        state["default_steps"] = before_steps
    if before_groups is None or before_steps is None:
        try:
            from setup_wizard import _try_load_groups_config

            _try_load_groups_config()
        except Exception:
            pass
        if before_groups is not None:
            state["groups"] = before_groups
        if before_steps is not None:
            state["default_steps"] = before_steps
    return " ".join(errors)


def _read_text(path) -> str | None:
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def _restore_text(path, text: str | None) -> None:
    try:
        if text is None:
            if path.is_file():
                path.unlink()
            return
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError:
        pass


def _disk_matches(path, expected) -> bool:
    import json

    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError, TypeError, ValueError):
        return False
    return stored == expected


def _disk_groups_match(path, expected: list) -> bool:
    import json

    try:
        stored = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeError, TypeError, ValueError):
        return False
    groups = stored.get("groups") if isinstance(stored, dict) else None
    return groups == expected


def get_automation_info() -> dict:
    def work() -> dict:
        from setup_wizard import state

        _reload_persisted_wizard_state()
        steps = list(state.get("default_steps") or [])
        return {"ok": True, "count": len(steps), "has_steps": bool(steps)}

    return _run_direct(work)


def _sync_default_steps_to_seq_page(steps: list) -> None:
    """Optional widget sync. Never starts Tcl — a dead pump used to freeze the EXE."""
    if _tk_root is None or _wizard is None or not _ready.is_set() or _boot_error:
        return
    try:
        page = _wizard._pages[5]
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

    return _run_direct(work)


def cursor_add_step(step: dict | None = None) -> dict:
    def work() -> dict:
        from setup_wizard import _apply_default_steps_to_template_phones, _normalize_sequence_steps, state

        _reload_persisted_wizard_state()
        raw = step if isinstance(step, dict) else {"type": "wait", "seconds": 2.0}
        normalized = _normalize_sequence_steps([raw])
        new_step = normalized[0] if normalized else dict(raw)
        before_groups, before_steps = _editor_snapshot()
        steps = list(state.get("default_steps") or [])
        steps.append(new_step)
        state["default_steps"] = steps
        _apply_default_steps_to_template_phones()
        _sync_default_steps_to_seq_page(steps)
        err = _commit_editor_state(
            require_groups=_groups_need_save(),
            require_steps=True,
            before_groups=before_groups,
            before_steps=before_steps,
        )
        steps = list(state.get("default_steps") or [])
        if err:
            return {"ok": False, "error": err, "count": len(steps), "steps": steps}
        return {"ok": True, "saved": True, "count": len(steps), "steps": steps}

    return _run_direct(work)


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
        before_groups, before_steps = _editor_snapshot()
        normalized = _normalize_sequence_steps([step])
        steps[idx] = normalized[0] if normalized else dict(step)
        state["default_steps"] = steps
        _apply_default_steps_to_template_phones()
        _sync_default_steps_to_seq_page(steps)
        err = _commit_editor_state(
            require_groups=_groups_need_save(),
            require_steps=True,
            before_groups=before_groups,
            before_steps=before_steps,
        )
        steps = list(state.get("default_steps") or [])
        if err:
            return {"ok": False, "error": err, "count": len(steps), "steps": steps}
        return {"ok": True, "saved": True, "count": len(steps), "steps": steps}

    return _run_direct(work)


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
        before_groups, before_steps = _editor_snapshot()
        steps.pop(idx)
        state["default_steps"] = steps
        _apply_default_steps_to_template_phones()
        _sync_default_steps_to_seq_page(steps)
        err = _commit_editor_state(
            require_groups=_groups_need_save(),
            require_steps=True,
            before_groups=before_groups,
            before_steps=before_steps,
        )
        steps = list(state.get("default_steps") or [])
        if err:
            return {"ok": False, "error": err, "count": len(steps), "steps": steps}
        return {"ok": True, "saved": True, "count": len(steps), "steps": steps}

    return _run_direct(work)


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
        before_groups, before_steps = _editor_snapshot()
        steps[idx], steps[j] = steps[j], steps[idx]
        state["default_steps"] = steps
        _apply_default_steps_to_template_phones()
        _sync_default_steps_to_seq_page(steps)
        err = _commit_editor_state(
            require_groups=_groups_need_save(),
            require_steps=True,
            before_groups=before_groups,
            before_steps=before_steps,
        )
        steps = list(state.get("default_steps") or [])
        if err:
            return {"ok": False, "error": err, "count": len(steps), "steps": steps}
        return {"ok": True, "saved": True, "count": len(steps), "steps": steps}

    return _run_direct(work)


def _groups_need_save() -> bool:
    from setup_wizard import _groups_have_assigned_phones

    return _groups_have_assigned_phones()


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
        before_groups, before_steps = _editor_snapshot()
        state["groups"].append(
            {
                "name": f"Group {n}",
                "phones": phones_map,
                "stagger_secs": 30,
                "repeat": 1,
                "repeat_forever": False,
            }
        )
        err = _commit_editor_state(
            require_groups=True,
            require_steps=False,
            before_groups=before_groups,
            before_steps=before_steps,
        )
        detail = _groups_detail_from_state()
        if err:
            return {"ok": False, "error": err, **detail}
        return {"ok": True, "saved": True, **detail}

    return _run_direct(work)


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
        before_groups, before_steps = _editor_snapshot()
        removed = groups.pop(idx)
        state["groups"] = groups
        err = _commit_editor_state(
            require_groups=True,
            require_steps=False,
            before_groups=before_groups,
            before_steps=before_steps,
        )
        detail = _groups_detail_from_state()
        if err:
            return {"ok": False, "error": err, **detail}
        removed_name = (
            (removed.get("name") or "").strip()
            if isinstance(removed, dict)
            else ""
        ) or f"Group {idx + 1}"
        return {"ok": True, "saved": True, "removed": removed_name, **detail}

    return _run_direct(work)


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
        before_groups, before_steps = _editor_snapshot()
        new_name = (name or "").strip() or f"Group {idx + 1}"
        g["name"] = new_name
        err = _commit_editor_state(
            require_groups=True,
            require_steps=False,
            before_groups=before_groups,
            before_steps=before_steps,
        )
        detail = _groups_detail_from_state()
        if err:
            return {"ok": False, "error": err, **detail}
        return {"ok": True, "saved": True, **detail}

    return _run_direct(work)


def run_edit_default_sequence() -> dict:
    """Open the sequence editor in its own process. The deck builder is the in-app editor."""
    return _spawn_visible_wizard(5, "edit_sequence")


def open_sequence_builder() -> dict:
    """Legacy name — deck navigates to builder view; no Tk window."""
    return {"ok": True, "deck": "builder"}


def open_groups_manager() -> dict:
    """Legacy name — deck navigates to teams view; no Tk window."""
    return {"ok": True, "deck": "teams"}


def _boot_serial_usable(serial: str) -> bool:
    """True when ``serial`` is a published guest endpoint, not an empty or localhost stub."""
    s = (serial or "").strip()
    if not s or ":" not in s:
        return False
    # MuMu ARM does not publish the classic 127.0.0.1:16xxx ports. Connecting
    # those (or calling adb with no -s) is the broken connector, not the guest.
    if s.startswith("127.0.0.1:"):
        return False
    return True


def _boot_serial_from_fleet(fleet: Any, name: str, idx: int) -> str:
    """state.json AdbHost:AdbPort for this VM. Empty when the guest has not published one."""
    if fleet is None:
        return ""
    try:
        names = fleet.canonical_names_sorted()
        serials = dict(zip(names, fleet.canonical_serials_sorted()))
    except Exception:
        return ""
    keys = [str(name or ""), f"vm{int(idx)}.gmadoa", f"vm{int(idx)}"]
    for key in keys:
        got = str(serials.get(key) or "").strip()
        if _boot_serial_usable(got):
            return got
    prefix = f"vm{int(idx)}."
    for vm_name, raw in serials.items():
        if str(vm_name).lower().startswith(prefix) and _boot_serial_usable(str(raw)):
            return str(raw).strip()
    return ""


def _set_boot_result(payload: dict) -> None:
    """Remember the boot worker result so the deck can poll it.

    The worker used to log BOOT FAILED and then exit. The button had already
    toasted that boot started, and nothing stored the failure.
    """
    global _boot_all_result
    with _boot_result_lock:
        _boot_all_result = dict(payload)


def boot_all_status() -> dict:
    """Last boot result. ``starting`` means the worker is still running."""
    with _boot_result_lock:
        out = dict(_boot_all_result)
    thr = _boot_all_thread
    if out.get("starting") and (thr is None or not thr.is_alive()):
        return {
            "ok": False,
            "starting": False,
            "error": "Boot stopped before it reported a result.",
        }
    return out


def _resolve_boot_serial(name: str, idx: int, current: str, fleet: Any) -> str:
    if _boot_serial_usable(current):
        return str(current).strip()
    return _boot_serial_from_fleet(fleet, name, idx)


def _redroid_rows() -> list[dict[str, Any]]:
    """Every redroid container docker knows. Ports are published host ports.

    Does not assume ``5555 + index``. Does not call docker when the engine is
    down — that CLI shim opens Docker Desktop.
    """
    if not docker_guard.engine_running():
        return []
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    try:
        proc = subprocess.run(
            [
                "docker",
                "ps",
                "-a",
                "--filter",
                "name=redroid-",
                "--format",
                "{{.Names}}|{{.Status}}|{{.Ports}}",
            ],
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=flags,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    if proc.returncode != 0:
        return []
    rows: list[dict[str, Any]] = []
    for line in (proc.stdout or "").splitlines():
        parts = line.split("|", 2)
        if len(parts) < 2:
            continue
        name = parts[0].strip()
        if not name.startswith("redroid-"):
            continue
        ports_raw = parts[2] if len(parts) > 2 else ""
        published = []
        seen: set[str] = set()
        for match in re.finditer(r"(?:0\.0\.0\.0|127\.0\.0\.1):(\d+)->", ports_raw):
            serial = f"127.0.0.1:{match.group(1)}"
            if serial in seen:
                continue
            seen.add(serial)
            published.append(serial)
        rows.append(
            {
                "name": name,
                "up": parts[1].strip().startswith("Up"),
                "ports": published,
            }
        )
    return rows


def _docker_start_named(name: str) -> tuple[int, str]:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    try:
        proc = subprocess.run(
            ["docker", "start", name],
            capture_output=True,
            text=True,
            timeout=120,
            creationflags=flags,
        )
    except subprocess.TimeoutExpired:
        return 1, f"docker start {name} timed out"
    except OSError as exc:
        return 1, str(exc)
    err = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return proc.returncode, err


def _wait_redroid_adb(ports: list[str], log: Callable[[str], None], name: str) -> bool:
    from setup_wizard import adb

    deadline = time.time() + 90
    while time.time() < deadline:
        if _boot_all_cancel.is_set():
            return False
        for serial in ports:
            adb("connect", serial, timeout=8)
            check = adb("shell", "echo", "ok", serial=serial, timeout=8)
            if check.strip() == "ok":
                log(f"{name}: ADB up on {serial}")
                return True
        time.sleep(4)
    return False


def _boot_stopped_redroid(log: Callable[[str], None]) -> dict[str, Any]:
    """Start every stopped redroid container and connect its published ADB port.

    Does not create containers, does not stop running ones, and does not guess
    a port from the container index.
    """
    rows = _redroid_rows()
    started: list[str] = []
    already: list[str] = []
    failed: list[str] = []
    if not rows:
        return {"found": 0, "started": started, "already": already, "failed": failed}
    for row in rows:
        if _boot_all_cancel.is_set():
            break
        name = str(row["name"])
        if row["up"]:
            ports = list(row["ports"])
            if ports and _wait_redroid_adb(ports, log, name):
                already.append(name)
            elif ports:
                failed.append(name)
                log(f"{name}: already running but no ADB on {', '.join(ports)}")
            else:
                failed.append(name)
                log(f"{name}: already running but docker published no ADB port")
            continue
        log(f"{name}: stopped — docker start")
        code, err = _docker_start_named(name)
        if code != 0:
            failed.append(name)
            log(f"{name}: docker start failed: {err}")
            continue
        fresh = next((item for item in _redroid_rows() if item["name"] == name), None)
        ports = list((fresh or {}).get("ports") or [])
        if not ports:
            failed.append(name)
            log(f"{name}: started but docker published no ADB port — not guessing 5555+index")
            continue
        if _wait_redroid_adb(ports, log, name):
            started.append(name)
        else:
            failed.append(name)
            log(f"{name}: started but no ADB answer on {', '.join(ports)}")
    return {"found": len(rows), "started": started, "already": already, "failed": failed}


def _running_avd_names() -> set[str]:
    """AVD names already launched (emulator -avd NAME)."""
    names: set[str] = set()
    for proc in psutil.process_iter(["cmdline"]):
        try:
            parts = [str(part) for part in (proc.info.get("cmdline") or [])]
        except (psutil.Error, TypeError, ValueError):
            continue
        if "-avd" not in parts:
            continue
        idx = parts.index("-avd")
        if idx + 1 < len(parts):
            names.add(parts[idx + 1])
    return names


def _avd_launch_argv(emu: str, name: str) -> list[str]:
    """Launch args for one Studio AVD. Never wipe the data disk."""
    host_arm64 = sys.platform == "win32" and "arm64" in (
        (platform.machine() or "") + os.environ.get("PROCESSOR_ARCHITECTURE", "")
    ).lower()
    flags = ["-gpu", "swiftshader_indirect", "-no-snapshot-save", "-no-boot-anim", "-no-audio"]
    if not host_arm64:
        flags = ["-accel", "auto", *flags]
    return [emu, "-avd", name, *flags]


def _launch_avd_process(emu: str, name: str) -> subprocess.Popen[Any]:
    """Start the emulator GUI. Hide the console, not the phone window."""
    argv = _avd_launch_argv(emu, name)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    return subprocess.Popen(  # noqa: S603
        subprocess.list2cmdline(argv),
        shell=True,
        creationflags=flags,
    )


def _emulator_serials() -> set[str]:
    from setup_wizard import adb

    raw = adb("devices", timeout=8)
    serials: set[str] = set()
    for line in raw.splitlines():
        if "\tdevice" not in line:
            continue
        serial = line.split()[0].strip()
        if serial.startswith("emulator-"):
            serials.add(serial)
    return serials


def _wait_new_emulator_serial(before: set[str], timeout_s: float = 120.0) -> str:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if _boot_all_cancel.is_set():
            return ""
        fresh = _emulator_serials() - before
        if fresh:
            return sorted(fresh)[0]
        time.sleep(3)
    return ""


def avd_name_from_emu_reply(text: str) -> str:
    """AVD name from ``adb emu avd name``. ``OK`` is the protocol trailer, not a name."""
    for line in str(text or "").splitlines():
        row = line.strip()
        if not row or row.upper() == "OK":
            continue
        return row
    return ""


def serial_for_running_avd(name: str, *, serials: list[str], emu_name) -> str:
    """Serial whose emulator console reports this AVD. Empty if none answers."""
    want = str(name or "").strip()
    if not want:
        return ""
    for serial in serials:
        try:
            raw = emu_name(serial)
        except Exception:
            continue
        if avd_name_from_emu_reply(raw) == want:
            return str(serial)
    return ""


def _boot_stopped_avds(log: Callable[[str], None]) -> dict[str, Any]:
    """Launch every Studio AVD that is not already answering ADB. No data wipe, no count."""
    from setup_wizard import adb, list_avds, sdk_tool, wait_for_boot

    names = [name for name in list_avds() if name]
    if not names:
        return {"found": 0, "started": [], "already": [], "failed": []}
    emu = sdk_tool("emulator")
    if not Path(emu).is_file():
        log("Studio AVDs exist but emulator.exe was not found — not launched.")
        return {"found": len(names), "started": [], "already": [], "failed": list(names)}
    running = _running_avd_names()
    started: list[str] = []
    already: list[str] = []
    failed: list[str] = []
    for name in names:
        if _boot_all_cancel.is_set():
            break
        if name in running:
            serial = serial_for_running_avd(
                name,
                serials=sorted(_emulator_serials()),
                emu_name=lambda serial: adb("emu", "avd", "name", serial=serial, timeout=8),
            )
            if serial and wait_for_boot(serial, timeout=120, log_fn=log):
                already.append(name)
                log(f"{name}: AVD already answering ADB on {serial}")
            else:
                failed.append(name)
                log(f"{name}: emulator process is up but no ADB answer — not counted as booted")
            continue
        if not boot_gate.wait_for_boot_headroom(
            label=name,
            log_fn=lambda msg, _name=name: log(f"{_name}: {msg}"),
        ):
            failed.append(name)
            log(f"{name}: skipped AVD launch — host lacked headroom")
            continue
        log(f"{name}: launching Android Studio AVD (data disk kept)…")
        before = _emulator_serials()
        try:
            _launch_avd_process(emu, name)
        except OSError as exc:
            failed.append(name)
            log(f"{name}: emulator launch failed: {exc}")
            continue
        serial = _wait_new_emulator_serial(before)
        if not serial:
            failed.append(name)
            log(f"{name}: emulator process started but no ADB serial yet")
            continue
        if wait_for_boot(serial, timeout=120, log_fn=log):
            started.append(name)
            log(f"{name}: ADB up on {serial}")
        else:
            failed.append(name)
            log(f"{name}: no boot_completed on {serial}")
    return {"found": len(names), "started": started, "already": already, "failed": failed}


def boot_all_phones() -> dict:
    """Boot every stopped MuMu phone, redroid container, and Studio AVD.

    Uses the same proven helpers as the classic wizard's _boot_all
    (_find_mumu_manager → _mumu_get_instances → _mumu_launch → adb connect/echo
    wait), so the deck's Boot button drives the real launch path without opening
    any Tk window or page object. Runs in a daemon thread; per-phone progress
    streams to the deck's boot log via _emit_log("boot", …).
    """
    global _boot_all_started_mono, _boot_all_thread

    def _try_acquire_boot_lock() -> tuple[bool, str]:
        """Acquire boot lock; force-steal if worker dead or hung > stale window."""
        global _boot_all_started_mono
        if _boot_all_lock.acquire(blocking=False):
            return True, ""
        thr = _boot_all_thread
        thr_dead = thr is None or not thr.is_alive()
        started = _boot_all_started_mono
        age = (time.monotonic() - started) if started is not None else None
        stale = age is not None and age >= _BOOT_LOCK_STALE_S
        if not (thr_dead or stale):
            return False, "already_running"
        # Cancel the hung worker (it checks this between phones) then steal.
        _boot_all_cancel.set()
        try:
            _boot_all_lock.release()
        except RuntimeError:
            pass
        if not _boot_all_lock.acquire(blocking=False):
            return False, "Boot already in progress"
        why = "dead_thread" if thr_dead else f"stale_{int(age or 0)}s"
        _emit_log("boot", f"BOOT LOCK stolen ({why}) — prior boot abandoned\n")
        return True, why

    got, steal_note = _try_acquire_boot_lock()
    if not got:
        # A live worker already owns the boot. That is not a failed click —
        # the deck was toasting "Boot failed" and Start automation aborted.
        if steal_note == "already_running":
            return {
                "ok": True,
                "started": False,
                "already_booting": True,
                "message": "Boot already running — progress continues in the boot log.",
            }
        return {"ok": False, "error": steal_note or "Boot already in progress", "started": False}

    _boot_all_cancel.clear()
    _boot_all_started_mono = time.monotonic()
    _set_boot_result(
        {
            "ok": True,
            "starting": True,
            "message": "Booting phones — watch the Test log.",
        }
    )

    def work() -> None:
        global _boot_all_started_mono
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
            instances: list[dict[str, Any]] = []
            mgr = None
            try:
                mgr = _find_mumu_manager()
                if mgr:
                    instances = _mumu_get_instances(mgr, log_fn=log) or []
            except Exception as exc:  # noqa: BLE001 — fall through to disk fleet
                log(f"MuMu manager discovery failed ({exc}) — using disk fleet instead.")
                mgr = None
            cli_fleet = None
            cli_launch = None
            if not instances:
                # This MuMuPlayerARM build ships NO CLI manager — the only
                # "Manager.exe" present is the GUI app
                # (nemux-shell-winui.Manager.exe), which must never be
                # executed (it opens the MuMu window). Enumerate the canonical
                # fleet from the vms\ folder instead and launch every instance
                # through the farm's proven shell launcher
                # (automation.mumu_shell_cli.launch_instance_index: auth-token
                # harvest from running shells + bare --VmIndex fallback), the
                # same mechanism that farmed vm10 successfully.
                try:
                    from automation import farm_canonical_phones as _fcp
                    from automation import mumu_shell_cli as _msc
                except Exception as exc:
                    msg = f"BOOT FAILED: no MuMu manager and fleet helpers unavailable: {exc}"
                    log(msg)
                    _set_boot_result({"ok": False, "starting": False, "error": msg})
                    return
                cli_fleet = _fcp
                cli_launch = _msc
                names = _fcp.canonical_names_sorted()
                serials = dict(zip(names, _fcp.canonical_serials_sorted()))
                for name in names:
                    if not name.lower().startswith("vm") or _fcp.is_banned_phone(name):
                        continue
                    idx = int(name[2:].split(".", 1)[0])
                    instances.append(
                        {
                            "index": idx,
                            "name": name,
                            "adb_serial": serials.get(name, ""),
                            "started": _msc.instance_shell_running(idx),
                        }
                    )
            if not instances:
                redroid = _boot_stopped_redroid(log)
                avds = _boot_stopped_avds(log)
                if not redroid["found"] and not avds["found"]:
                    msg = "No MuMu instances found — open MuMu once so it creates its VMs."
                    log(msg)
                    _set_boot_result({"ok": False, "starting": False, "error": msg})
                    return
                failed_extra = list(redroid["failed"]) + list(avds["failed"])
                up = bool(redroid["started"] or redroid["already"] or avds["started"] or avds["already"])
                summary = (
                    f"Boot finished: no MuMu instances, {len(redroid['started'])} redroid "
                    f"started, {len(redroid['already'])} redroid already up, "
                    f"{len(avds['started'])} AVD started, {len(avds['already'])} AVD already up, "
                    f"{len(failed_extra)} failed."
                )
                log(summary)
                payload = {
                    "ok": not failed_extra and up,
                    "starting": False,
                    "booted": len(redroid["started"]) + len(avds["started"]),
                    "failed": len(failed_extra),
                    "windowless": 0,
                    "reconnected": 0,
                    "redroid_started": len(redroid["started"]),
                    "redroid_failed": len(redroid["failed"]),
                    "avd_started": len(avds["started"]),
                    "avd_failed": len(avds["failed"]),
                }
                if payload["ok"]:
                    payload["message"] = summary
                else:
                    payload["error"] = summary
                _set_boot_result(payload)
                return
            # Serial overlay applies on the manager path too. Disk-fleet
            # fallback above is unchanged; this only fills empty/localhost
            # serials from state.json so adb is never called without -s.
            _fleet_mod = cli_fleet
            if _fleet_mod is None:
                try:
                    from automation import farm_canonical_phones as _fleet_mod
                except Exception as exc:
                    log(
                        f"disk-fleet serial overlay unavailable ({exc}) — "
                        "will not adb without a published guest serial"
                    )
                    _fleet_mod = None
            try:
                from automation import mumu_shell_cli as _player
            except Exception as exc:
                _player = cli_launch
                if _player is None:
                    log(f"player-show unavailable ({exc})")
            booted: list[str] = []
            already: list[str] = []
            reconnected: list[str] = []
            windowless: list[str] = []
            failed: list[str] = []
            for inst in instances:
                if _boot_all_cancel.is_set():
                    log("BOOT CANCELLED — lock stolen by a newer boot request")
                    break
                name = inst["name"]
                try:
                    idx = int(inst["index"])
                except (TypeError, ValueError, KeyError):
                    log(f"{name}: bad instance index {inst.get('index')!r}")
                    failed.append(name)
                    continue
                serial = _resolve_boot_serial(
                    name, idx, str(inst.get("adb_serial") or ""), _fleet_mod
                )

                def _shell_up(_idx: int = idx) -> bool:
                    if _player is None:
                        return False
                    try:
                        return bool(_player.instance_shell_running(_idx))
                    except Exception:
                        return False

                def _show_player(_idx: int = idx, _name: str = name) -> bool:
                    if _player is None:
                        return False
                    try:
                        if _player.player_window_visible(_idx):
                            return True
                        ok_show, note = _player.show_instance_player(_idx)
                        if note:
                            log(f"{_name}: {note}")
                        return bool(ok_show) or bool(_player.player_window_visible(_idx))
                    except Exception as exc:
                        log(f"{_name}: player show failed: {exc}")
                        return False

                if _shell_up():
                    # Live shell: show the player in place, then reconnect ADB.
                    # Do not spawn a second shell (that can replace the VM) and
                    # do not count a windowless process as a visible player.
                    visible = _show_player()
                    deadline = _time.time() + 45
                    up = False
                    reset = False
                    missing_serial_logged = False
                    while True:
                        if _boot_all_cancel.is_set():
                            break
                        if not _boot_serial_usable(serial):
                            serial = _resolve_boot_serial(name, idx, "", _fleet_mod)
                        if _boot_serial_usable(serial):
                            check = adb("shell", "echo", "ok", serial=serial, timeout=8)
                            if check.strip() == "ok":
                                up = True
                                break
                        if _time.time() >= deadline:
                            break
                        if not _boot_serial_usable(serial):
                            if not missing_serial_logged:
                                log(
                                    f"{name}: shell running, AdbHost not published — "
                                    "not calling adb without a serial"
                                )
                                missing_serial_logged = True
                        else:
                            if not reset:
                                log(
                                    f"{name}: ADB dead on running VM — "
                                    f"resetting transport ({serial})"
                                )
                                adb("disconnect", serial, timeout=8)
                                reset = True
                            adb("connect", serial, timeout=8)
                        _time.sleep(4)
                    if _boot_all_cancel.is_set():
                        break
                    if not visible:
                        visible = _show_player()
                    if up and visible:
                        log(
                            f"{name}: ADB verified up ({serial})"
                            + (" — reconnected" if reset else "")
                            + " (player visible)"
                        )
                        already.append(name)
                        if reset:
                            reconnected.append(name)
                        continue
                    if up and not visible:
                        log(
                            f"{name}: ADB up on {serial} but player window missing — "
                            "not a visible player (VM left running)"
                        )
                        windowless.append(name)
                        if reset:
                            reconnected.append(name)
                        continue
                    log(
                        f"{name}: running but no ADB after transport reset — "
                        "VM left running (HNS NIC attach may still be wedged)"
                    )
                    failed.append(name)
                    continue
                if inst.get("started") and not _shell_up():
                    log(f"{name}: marked started but shell is not running — launching")
                # Scaling-plan gate: never launch the next VM into a starved
                # host. Host-health gate only — no phone-count cap; if the
                # host can absorb another phone, the boot continues.
                if not boot_gate.wait_for_boot_headroom(
                    label=name,
                    log_fn=lambda m, _n=name: log(f"{_n}: {m}"),
                ):
                    log(f"{name}: skipped launch — host lacked headroom (gate timeout)")
                    failed.append(name)
                    continue
                log(f"{name}: launching (instance {idx})…")
                launch_ok = False
                try:
                    if cli_launch is not None:
                        launch_ok, note = cli_launch.launch_instance_index(idx, timeout=120.0)
                        log(f"{name}: {note}")
                    else:
                        launch_ok = bool(_mumu_launch(mgr, idx, log_fn=log))
                        log(f"{name}: launch returned {launch_ok}")
                except Exception as exc:  # noqa: BLE001 — keep booting the rest
                    log(f"{name}: launch failed: {exc}")
                    failed.append(name)
                    continue
                shell_after = _shell_up()
                if not launch_ok and not shell_after:
                    failed.append(name)
                    continue
                if not launch_ok and shell_after:
                    log(
                        f"{name}: shell running without a visible player — "
                        "reconnecting ADB; not a visible player until the window is up"
                    )
                _time.sleep(2)
                deadline = _time.time() + 180
                up = False
                target = serial if _boot_serial_usable(serial) else ""
                missing_serial_logged = False
                while _time.time() < deadline:
                    if _boot_all_cancel.is_set():
                        break
                    if not _boot_serial_usable(target):
                        # Guest publishes AdbHost only after the shell registers.
                        # Re-read state.json. Never adb -s "".
                        target = _resolve_boot_serial(name, idx, "", _fleet_mod)
                    if _boot_serial_usable(target):
                        adb("connect", target, timeout=8)
                        check = adb("shell", "echo", "ok", serial=target, timeout=8)
                        up = check.strip() == "ok"
                    elif not missing_serial_logged:
                        log(
                            f"{name}: waiting for AdbHost in state.json — "
                            "not calling adb without a serial"
                        )
                        missing_serial_logged = True
                    if up:
                        break
                    _time.sleep(5)
                if _boot_all_cancel.is_set():
                    break
                visible = _show_player()
                if up and visible:
                    log(f"{name}: ADB up on {target} (player visible)")
                    booted.append(name)
                elif up:
                    log(
                        f"{name}: ADB up on {target} but player window missing — "
                        "not a visible player (VM left running)"
                    )
                    windowless.append(name)
                else:
                    log(
                        f"{name}: no ADB answer after 180s — moving on "
                        "(HNS NIC attach may still be wedged; VM not killed)"
                    )
                    failed.append(name)
            redroid = _boot_stopped_redroid(log)
            avds = _boot_stopped_avds(log)
            failed.extend(redroid["failed"])
            failed.extend(avds["failed"])
            total = len(booted) + len(already)
            hns_note = ""
            if failed or windowless:
                hns_note = (
                    " Phones that never publish AdbHost still need an operator "
                    "HNS restart; VMs were left running."
                )
            summary = (
                f"Boot finished: {total} MuMu phone(s) up with a visible player, "
                f"{len(reconnected)} ADB reconnected, {len(windowless)} windowless "
                f"(not counted as a visible player), {len(redroid['started'])} redroid "
                f"started, {len(redroid['already'])} redroid already up, "
                f"{len(avds['started'])} AVD started, {len(avds['already'])} AVD already up, "
                f"{len(failed)} failed.{hns_note}"
            )
            log(summary)
            counts = {
                "booted": total + len(redroid["started"]) + len(avds["started"]),
                "failed": len(failed),
                "windowless": len(windowless),
                "reconnected": len(reconnected),
                "redroid_started": len(redroid["started"]),
                "redroid_failed": len(redroid["failed"]),
                "avd_started": len(avds["started"]),
                "avd_failed": len(avds["failed"]),
            }
            visible_up = bool(
                total
                or redroid["started"]
                or redroid["already"]
                or avds["started"]
                or avds["already"]
            )
            if _boot_all_cancel.is_set():
                _set_boot_result(
                    {
                        "ok": False,
                        "starting": False,
                        "error": "Boot cancelled — a newer boot took over.",
                        **counts,
                    }
                )
            elif failed or not visible_up:
                _set_boot_result(
                    {"ok": False, "starting": False, "error": summary, **counts}
                )
            else:
                _set_boot_result(
                    {"ok": True, "starting": False, "message": summary, **counts}
                )
        except Exception as exc:  # noqa: BLE001 — never silent-fail the boot worker
            msg = f"BOOT FAILED: {exc}"
            log(msg)
            _set_boot_result({"ok": False, "starting": False, "error": msg})
        finally:
            _boot_all_started_mono = None
            try:
                _boot_all_lock.release()
            except RuntimeError:
                pass

    try:
        _boot_all_thread = threading.Thread(
            target=work, daemon=True, name="boot-all-phones"
        )
        _boot_all_thread.start()
    except Exception as exc:  # noqa: BLE001
        _boot_all_started_mono = None
        try:
            _boot_all_lock.release()
        except RuntimeError:
            pass
        err = f"Could not start boot thread: {exc}"
        _set_boot_result({"ok": False, "starting": False, "error": err})
        return {"ok": False, "error": err, "started": False}
    out: dict[str, Any] = {"ok": True, "started": True}
    if steal_note:
        out["lock_stolen"] = steal_note
    return out


def remove_group(index: int) -> dict:
    """Remove group ``index`` — same semantics as ``cursor_remove_group`` (keep ≥1)."""
    return cursor_remove_group(index)


def run_add_group() -> dict:
    """Compat wrapper — deck uses cursor_add_group (no Tk Groups window)."""
    return cursor_add_group()


def run_humanize_all_sequences() -> dict:
    """Per-phone timing jitter. Same digest seed as GroupsPage, no widget rebuild."""
    import hashlib
    import random

    from sequence_humanize import humanize_steps
    from setup_wizard import state

    _prepare_editor_state()
    before_groups, before_steps = _editor_snapshot()
    n = 0
    for g in state.get("groups") or []:
        if not isinstance(g, dict):
            continue
        pmap = g.get("phones") or {}
        if not isinstance(pmap, dict):
            continue
        for serial, ent in pmap.items():
            if not isinstance(ent, dict):
                continue
            steps = ent.get("steps")
            if not isinstance(steps, list) or not steps:
                continue
            digest = hashlib.sha256(str(serial).encode("utf-8", errors="replace")).digest()[:8]
            seed = int.from_bytes(digest, "big")
            ent["steps"] = humanize_steps(steps, random.Random(seed))
            ent["explicit_override"] = True
            ent["use_default_template"] = False
            n += 1
    if n == 0:
        return {
            "ok": False,
            "error": "No phone sequences to change. Add steps on a phone first.",
            "count": 0,
        }
    err = _commit_editor_state(
        require_groups=True,
        require_steps=False,
        before_groups=before_groups,
        before_steps=before_steps,
    )
    if err:
        return {"ok": False, "error": err, "count": 0}
    msg = f"Applied natural timing tweaks on {n} phone sequence(s)."
    return {"ok": True, "saved": True, "message": msg, "count": n}


def _commit_default_steps(steps: list, path: str = "") -> dict:
    from setup_wizard import _apply_default_steps_to_template_phones, state

    before_groups, before_steps = _editor_snapshot()
    state["default_steps"] = list(steps)
    _apply_default_steps_to_template_phones()
    _sync_default_steps_to_seq_page(steps)
    err = _commit_editor_state(
        require_groups=_groups_need_save(),
        require_steps=True,
        before_groups=before_groups,
        before_steps=before_steps,
    )
    steps = list(state.get("default_steps") or [])
    if err:
        return {"ok": False, "error": err, "count": len(steps), "steps": steps}
    out = {"ok": True, "saved": True, "count": len(steps), "steps": steps}
    if path:
        out["path"] = path
    return out


def run_load_default_sequence() -> dict:
    from native_dialogs import ask_open_json_file

    path = ask_open_json_file(title="Load sequence", parent=None)
    if not path:
        return {"ok": False, "cancelled": True}
    return load_sequence_from_path(path)


def run_save_default_sequence() -> dict:
    from native_dialogs import ask_save_json_file
    from setup_wizard import state

    _reload_persisted_wizard_state()
    steps = list(state.get("default_steps") or [])
    if not steps:
        return {"ok": False, "error": "No steps to save — use Edit default sequence first."}
    path = ask_save_json_file(title="Save sequence", parent=None)
    if not path:
        return {"ok": False, "cancelled": True}
    return save_sequence_to_path(path)


def load_sequence_from_path(path: str) -> dict:
    from pathlib import Path

    from setup_wizard import SequenceJsonLoadError, _load_sequence_document_from_path, _normalize_sequence_steps

    if not str(path or "").strip():
        return {"ok": False, "error": "No sequence path"}
    try:
        data, _meta = _load_sequence_document_from_path(Path(path))
    except SequenceJsonLoadError as exc:
        return {"ok": False, "error": str(exc)}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    steps = _normalize_sequence_steps(data)
    if not steps:
        return {"ok": False, "error": "That file has no steps."}
    return _commit_default_steps(steps, str(path))


def save_sequence_to_path(path: str) -> dict:
    import json
    from pathlib import Path

    from setup_wizard import state

    if not str(path or "").strip():
        return {"ok": False, "error": "No sequence path"}
    _reload_persisted_wizard_state()
    steps = list(state.get("default_steps") or [])
    if not steps:
        return {"ok": False, "error": "No steps to save — use Edit default sequence first."}
    dest = Path(path)
    dest.write_text(json.dumps(steps, indent=2), encoding="utf-8")
    try:
        stored = json.loads(dest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"ok": False, "error": "Sequence was not saved on disk."}
    if stored != steps:
        return {"ok": False, "error": "Sequence was not saved on disk."}
    return _commit_default_steps(steps, str(path))


def get_groups_detail() -> dict:
    def work() -> dict:
        from setup_wizard import _normalize_all_groups

        _reload_persisted_wizard_state()
        _normalize_all_groups()
        return {"ok": True, **_groups_detail_from_state()}

    return _run_direct(work)


def get_groups_summary() -> dict:
    return get_groups_detail()


def is_dashboard_ready() -> dict:
    from setup_wizard import probe_dashboard_listen_port

    ready = bool(probe_dashboard_listen_port())
    proc = _dashboard_proc
    thread_alive = _dashboard_thread is not None and _dashboard_thread.is_alive()
    running = (proc is not None and proc.poll() is None) or thread_alive or ready
    with _service_start_lock:
        stored = dict(_service_start_result)
    if stored.get("starting"):
        return {"ok": True, "ready": ready, "starting": True, "server_running": running}
    if stored.get("ok") is False and stored.get("error"):
        return {
            "ok": False,
            "ready": False,
            "starting": False,
            "error": stored.get("error"),
            "server_running": running,
        }
    out = {"ok": True, "ready": ready, "starting": False, "server_running": running}
    # The start worker records whether the browser actually opened. Dropping
    # that field made the button open the dashboard a second time, or toast
    # "Service started" when the browser never opened.
    if "dashboard_opened" in stored:
        out["dashboard_opened"] = bool(stored.get("dashboard_opened"))
    return out


def get_launch_summary() -> dict:
    from setup_wizard import state

    _reload_persisted_wizard_state()
    groups = [g for g in (state.get("groups") or []) if isinstance(g, dict)]
    phones = 0
    for g in groups:
        pmap = g.get("phones") or {}
        if isinstance(pmap, dict):
            phones += len(pmap)
    steps = len(state.get("default_steps") or [])
    try:
        mode_info = get_browse_mode()
        mode = str(mode_info.get("label") or mode_info.get("mode") or "")
    except Exception:
        mode = ""
    lines = [
        f"Groups: {len(groups)}",
        f"Phones in groups: {phones}",
        f"Default steps: {steps}",
    ]
    if mode:
        lines.append(f"Browse mode: {mode}")
    lines.append("Start the service, then run all groups. Farm start is the money path.")
    return {"ok": True, "summary": "\n".join(lines)}


def save_browse_mode(mode: str) -> dict:
    def work() -> dict:
        import os

        from wizard_paths import automation_on_sys_path

        automation_on_sys_path()
        import browse_proxy as bp

        mode_l = (mode or "").strip().lower()
        if mode_l not in ("tor", "scramble", "direct", "upstream"):
            return {
                "ok": False,
                "error": "Browse mode must be tor, scramble, direct, or upstream.",
            }
        saved = bp.save_browse_prefs(browse_proxy_mode=mode_l)
        if not saved or saved.get("browse_proxy_mode") != mode_l:
            return {"ok": False, "error": "Browse mode was not saved — disk copy does not match."}
        os.environ["PHARMFLOW_BROWSE_PROXY_MODE"] = mode_l
        return {"ok": True, "saved": True, "mode": mode_l, "label": bp.browse_proxy_mode_label(mode_l)}

    return _run_direct(work)


def get_browse_mode() -> dict:
    def work() -> dict:
        from wizard_paths import automation_on_sys_path

        automation_on_sys_path()
        import browse_proxy as bp

        m = bp.browse_proxy_mode()
        return {"ok": True, "mode": m, "label": bp.browse_proxy_mode_label(m)}

    return _run_direct(work)


def _begin_service_start(*, open_browser: bool) -> dict:
    """Start the control server and remember the real result.

    The deck used to toast "Service started" the instant the thread was
    spawned. The worker owns the wait; callers poll ``is_dashboard_ready``.
    """
    with _service_start_lock:
        if _service_start_result.get("starting"):
            return {
                "ok": True,
                "starting": True,
                "message": "Service start already in progress — watch the Run log.",
            }
        _service_start_result.clear()
        _service_start_result.update(
            {"ok": True, "starting": True, "message": "Starting service — watch the Run log."}
        )

    def work() -> None:
        try:
            res = _start_dashboard_headless()
            if not res.get("ok"):
                err = str(res.get("error") or "Start service failed")
                _emit_log("go", f"Start service failed: {err}\n")
                with _service_start_lock:
                    _service_start_result.clear()
                    _service_start_result.update({"ok": False, "starting": False, "error": err})
                return
            if res.get("already_running"):
                _emit_log("go", "Dashboard already running.\n")
            opened = False
            if open_browser:
                from setup_wizard import dashboard_base_url

                url = dashboard_base_url().rstrip("/") + "/"
                opened = _open_browser(url)
                if opened:
                    _emit_log("go", f"Opened dashboard {url}\n")
                else:
                    _emit_log(
                        "go",
                        f"Dashboard is up at {url} but the browser did not open.\n",
                    )
            with _service_start_lock:
                _service_start_result.clear()
                _service_start_result.update(
                    {
                        "ok": True,
                        "starting": False,
                        "ready": True,
                        "started": True,
                        "already_running": bool(res.get("already_running")),
                        "dashboard_opened": opened,
                    }
                )
        except Exception as exc:  # noqa: BLE001 — the poll must see the failure
            err = f"Start service error: {exc}"
            _emit_log("go", f"{err}\n")
            with _service_start_lock:
                _service_start_result.clear()
                _service_start_result.update({"ok": False, "starting": False, "error": err})

    threading.Thread(target=work, name="pharmflow-dashboard", daemon=True).start()
    return {"ok": True, "starting": True, "message": "Starting service — watch the Run log."}


def start_server() -> dict:
    """Start the control server. No Tk Run window and no background Tcl pump."""
    return _begin_service_start(open_browser=False)


def start_server_and_open_dashboard() -> dict:
    """Start service, then open the dashboard in the browser once it answers."""
    return _begin_service_start(open_browser=True)


def _run_groups_on_dashboard() -> dict:
    from setup_wizard import state

    _persist_editor_state()
    started = _start_dashboard_headless()
    if not started.get("ok"):
        return started
    loaded = _dashboard_post("/api/groups/load", {})
    if loaded.get("error"):
        _emit_log("go", f"Load groups: {loaded['error']}\n")
    groups = state.get("groups") or []
    run_r = _dashboard_post("/api/groups/run", {"groups": groups}, timeout=120)
    if run_r.get("error"):
        _emit_log("go", f"Run groups failed: {run_r['error']}\n")
        return {"ok": False, "error": str(run_r["error"])}
    n = run_r.get("groups", len(groups))
    pt = run_r.get("phones_targeted")
    _emit_log("go", f"{n} group(s) running — {pt} phone(s) targeted.\n")
    return {"ok": True, "started": True, "groups": n, "phones_targeted": pt}


def _wait_for_boot_worker() -> None:
    """Groups must not be posted while Boot is still bringing phones up."""
    thr = _boot_all_thread
    if thr is None or not thr.is_alive() or thr is threading.current_thread():
        return
    _emit_log("go", "Waiting for boot to finish before running groups…\n")
    thr.join()


def _begin_groups_run(*, label: str) -> dict:
    """Boot, then run groups, and keep the real result for the deck to poll.

    Returning ``started: True`` before ``/api/groups/run`` answered made the
    deck toast success when the service was down or no phones were targeted.
    """
    boot_res = _boot_then_continue()
    if boot_res.get("ok") is False:
        return boot_res
    with _groups_run_lock:
        if _groups_run_result.get("starting"):
            return {
                "ok": True,
                "starting": True,
                "boot": boot_res,
                "message": "Groups are already starting — watch the Run log.",
            }
        _groups_run_result.clear()
        _groups_run_result.update(
            {"ok": True, "starting": True, "message": f"{label} is running — watch the Run log."}
        )

    def work() -> None:
        try:
            _emit_log("go", f"{label}: saving groups and starting service…\n")
            _wait_for_boot_worker()
            res = _run_groups_on_dashboard()
            if not res.get("ok"):
                err = str(res.get("error") or f"{label} failed")
                _emit_log("go", f"{label} failed: {err}\n")
                with _groups_run_lock:
                    _groups_run_result.clear()
                    _groups_run_result.update({"ok": False, "starting": False, "error": err})
                return
            targeted = res.get("phones_targeted")
            _emit_log(
                "go",
                f"{label} accepted — {targeted} phone(s) targeted. "
                "Sequences run on the service; this button does not wait for them to finish.\n",
            )
            with _groups_run_lock:
                done = {
                    "ok": True,
                    "starting": False,
                    "started": True,
                    "groups": res.get("groups"),
                    "phones_targeted": targeted,
                    "message": (
                        f"Groups accepted — {targeted} phone(s) targeted. "
                        "Watch the Run log for sequence progress."
                    ),
                }
                _groups_run_result.clear()
                _groups_run_result.update(done)
        except Exception as exc:  # noqa: BLE001 — the poll must see the failure
            err = f"{label} error: {exc}"
            _emit_log("go", f"{err}\n")
            with _groups_run_lock:
                _groups_run_result.clear()
                _groups_run_result.update({"ok": False, "starting": False, "error": err})

    threading.Thread(target=work, name="pharmflow-groups-run", daemon=True).start()
    return {
        "ok": True,
        "starting": True,
        "boot": boot_res,
        "message": f"{label} is running — watch the Run log.",
    }


def groups_run_status() -> dict:
    """Last Run-groups / Start-automation result. ``starting`` means still working."""
    with _groups_run_lock:
        return dict(_groups_run_result)


def run_all_groups() -> dict:
    """Boot phones, then start the service and run groups. Never waits on Tcl."""
    return _begin_groups_run(label="Run groups")


def start_automation_one_click() -> dict:
    """Boot, start the service, load groups, run them. An in-progress boot is not a failure."""
    return _begin_groups_run(label="Start automation")


def _exits_after_heal(serials: list[str]) -> tuple[list[str], list[str]]:
    """Split live serials by the guest proxy actually on the phone.

    Heal notes that omit ``repin_fail`` are not a pin. An empty, null, or
    ``:0`` proxy is this PC's path. Only a loopback exit counts.
    """
    from automation.browse_proxy import guest_proxy_healthy
    from setup_wizard import _wiz_read_guest_proxy

    pinned: list[str] = []
    missing: list[str] = []
    for serial in serials:
        try:
            cur = _wiz_read_guest_proxy(serial)
        except Exception:
            missing.append(serial)
            continue
        if "error:" in str(cur or "").lower() or not guest_proxy_healthy(str(cur or "")):
            missing.append(serial)
        else:
            pinned.append(serial)
    return pinned, missing


def fix_phone_internet() -> dict:
    """Re-pin live phones to their own inject/Tor exits.

    The button used to call ``wiz_clear_phone_proxies_best_effort``, which
    deletes ``global http_proxy``, drops Tor slots, and force-stops the
    browser. That sends traffic out the VM/host path (forbidden) and is why
    "Fix internet" killed the money exit. The EXE repair is the same heal the
    farm already owns: reconnect ADB, restore Tor/inject, re-pin guests.
    It does not reap farm lanes and it does not clear proxies to ``:0``.
    """
    from automation.farm_exe_self_heal import (
        adb_live_serials,
        connect_live_fleet,
        heal_inject_and_tor,
    )

    notes: list[str] = []
    try:
        notes.extend(connect_live_fleet() or [])
    except Exception as exc:  # noqa: BLE001
        notes.append(f"connect_failed:{exc}")
    try:
        live = list(adb_live_serials() or [])
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": f"ADB check failed: {exc}", "n": 0}
    if not live:
        return {
            "ok": False,
            "error": "No live phones — start a phone, then try again.",
            "n": 0,
            "fixes": notes,
        }
    try:
        notes.extend(heal_inject_and_tor(live=live) or [])
    except Exception as exc:  # noqa: BLE001
        _emit_log("boot", f"Fix internet failed: {exc}\n")
        return {"ok": False, "error": str(exc), "n": len(live)}
    for line in notes:
        _emit_log("boot", f"Fix internet: {line}\n")
    pinned, missing = _exits_after_heal(live)
    out: dict[str, Any] = {
        "ok": bool(pinned) and not missing,
        "n": len(pinned),
        "fixes": notes,
    }
    if missing or not pinned:
        sample = missing[0] if missing else "no phone"
        out["error"] = (
            f"Exit still missing on {len(missing) or len(live)} phone(s) ({sample}). "
            "A live ADB serial is not a loopback exit."
        )
        out["unpinned"] = missing
        return out
    out["message"] = f"Re-pinned {len(pinned)} phone(s) onto their own exits."
    return out


def open_dashboard() -> dict:
    from setup_wizard import dashboard_base_url, probe_dashboard_listen_port

    if not probe_dashboard_listen_port():
        return {
            "ok": False,
            "error": "Service is not running — use Go → Start service + open control dashboard first.",
        }
    url = dashboard_base_url().rstrip("/") + "/"
    if not _open_browser(url):
        return {
            "ok": False,
            "opened": False,
            "error": f"Dashboard is up at {url} but the browser did not open.",
            "dashboard": url,
        }
    return {"ok": True, "opened": True, "dashboard": url}


def open_farm_dashboard() -> dict:
    """Open the live farm dashboard (127.0.0.1:8091) only.

    The Home and Groups buttons are labeled as the operator dashboard. Opening
    the wizard control server on another port and returning opened=True made
    that label a lie. If :8091 is down, say so. Do not substitute the control
    dashboard.
    """
    import urllib.request

    farm_dash = "http://127.0.0.1:8091/"
    try:
        with urllib.request.urlopen(farm_dash, timeout=2.5):  # noqa: S310 — loopback
            if not _open_browser(farm_dash):
                return {
                    "ok": False,
                    "opened": False,
                    "error": f"Farm dashboard is up at {farm_dash} but the browser did not open.",
                    "dashboard": farm_dash,
                }
            return {"ok": True, "opened": True, "dashboard": farm_dash}
    except Exception:
        return {
            "ok": False,
            "opened": False,
            "error": (
                "Farm dashboard is not up at http://127.0.0.1:8091/ — start the farm first. "
                "This button does not open the control dashboard."
            ),
            "dashboard": farm_dash,
        }


def get_farm_health() -> dict:
    """Session-quality telemetry for the deck's Health view.

    Dump-timeout and fallback stats come from the farm log. ``farm_alive``
    does not. A log touched in the last two minutes is not a running farm —
    the Home button already treats that as a lie. LIVE means a worker process,
    including an external python farm that PharmFlow did not start.
    """
    try:
        from automation.farm_health import snapshot

        out = snapshot()
    except Exception as exc:  # noqa: BLE001 — the view must never crash
        return {"ok": False, "error": str(exc)}
    if not isinstance(out, dict):
        return {"ok": False, "error": "Farm health returned nothing."}
    try:
        from wizard.farm_control import (
            external_python_farm_running,
            farm_process_alive,
        )

        alive = bool(farm_process_alive() or external_python_farm_running())
    except Exception:  # noqa: BLE001 — the card must not guess from the log
        alive = False
    out["farm_alive"] = alive
    return out


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


def _set_cloud_result(payload: dict) -> None:
    global _cloud_result
    with _cloud_result_lock:
        _cloud_result = dict(payload)


def cloud_command_status() -> dict:
    """Last cloud-phone command. ``starting`` means the process is still running."""
    with _cloud_result_lock:
        out = dict(_cloud_result)
    thr = _cloud_thread
    if out.get("starting") and (thr is None or not thr.is_alive()):
        return {
            "ok": False,
            "starting": False,
            "error": "Cloud command stopped before it reported a result.",
        }
    return out


def run_cloud_phone_command(command: str, host: str = "", count: int = 0, *, verify: bool = False) -> dict:
    """Run a cloud_phones CLI command in a hidden background process.

    Output streams into the Step 9 log. The exit code is stored for
    ``cloud_command_status`` so the button does not treat a failed process
    as still running.
    """
    global _cloud_thread
    with _cloud_result_lock:
        if _cloud_result.get("starting"):
            return {
                "ok": True,
                "starting": True,
                "already_running": True,
                "command": command,
                "message": "A cloud command is already running — watch the Run log.",
            }

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
    except OSError as exc:
        err = f"Cloud {command} could not start: {exc}"
        _set_cloud_result({"ok": False, "starting": False, "error": err, "command": command})
        return {"ok": False, "error": err, "command": command}

    _set_cloud_result(
        {
            "ok": True,
            "starting": True,
            "command": command,
            "message": f"Cloud {command} started — watch the Run log.",
        }
    )

    def work() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            _emit_log("go", line)
        proc.wait()
        code = proc.returncode
        _emit_log("go", f"\n[cloud {command}] finished (exit {code})\n")
        if code == 0:
            _set_cloud_result(
                {
                    "ok": True,
                    "starting": False,
                    "command": command,
                    "exit_code": code,
                    "message": f"Cloud {command} finished (exit 0).",
                }
            )
        else:
            _set_cloud_result(
                {
                    "ok": False,
                    "starting": False,
                    "command": command,
                    "exit_code": code,
                    "error": f"Cloud {command} failed (exit {code}).",
                }
            )

    _cloud_thread = threading.Thread(target=work, daemon=True, name="pharmflow-cloud-cmd")
    _cloud_thread.start()
    return {
        "ok": True,
        "starting": True,
        "command": command,
        "message": f"Cloud {command} started — watch the Run log.",
    }


def cloud_phone_setup(host: str, count: int = 0) -> dict:
    """Full cloud setup: connect + stealth + Tor on the instances the operator asked for."""
    host = str(host or "").strip()
    if not host:
        return {"ok": False, "error": "Cloud setup needs an instance IP."}
    try:
        n = int(count)
    except (TypeError, ValueError):
        return {"ok": False, "error": "Cloud setup needs an instance count."}
    if n < 1:
        return {"ok": False, "error": "Cloud setup needs an instance count."}
    return run_cloud_phone_command("setup", host, n)


def cloud_phone_status(host: str = "") -> dict:
    """List connected cloud instances (hidden window)."""
    return run_cloud_phone_command("status", host, 0)


def _watchdog_script_path() -> str:
    if getattr(sys, "frozen", False):
        return str(Path(sys._MEIPASS) / "tools" / "pharmflow_watchdog.py")  # type: ignore[attr-defined]
    return str(Path(__file__).resolve().parent.parent / "tools" / "pharmflow_watchdog.py")


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
        "base": os.environ.get("PHARMFLOW_CLOUD_AGENT_BASE", "https://api.openai.com/v1"),
        "model": os.environ.get("PHARMFLOW_CLOUD_AGENT_MODEL", "gpt-4o"),
        "api_key": "",
        "configured": False,
    }
    raw_key = os.environ.get("PHARMFLOW_CLOUD_AGENT_KEY", "")
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
    existing: dict = {}
    if cfg_path.is_file():
        try:
            loaded = json.loads(cfg_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {
                "ok": False,
                "error": "Agent settings file is corrupt. It was not replaced.",
            }
        if not isinstance(loaded, dict):
            return {
                "ok": False,
                "error": "Agent settings file is not a settings object. It was not replaced.",
            }
        existing = loaded
    if base and base.strip():
        existing["base"] = base.strip().rstrip("/")
    if model and model.strip():
        existing["model"] = model.strip()
    if api_key and api_key.strip():
        existing["api_key"] = api_key.strip()
    payload = json.dumps(existing, indent=2)
    try:
        cfg_path.write_text(payload, encoding="utf-8")
        stored = json.loads(cfg_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return {"ok": False, "error": str(exc) or "Agent settings were not saved on disk."}
    if not isinstance(stored, dict) or stored.get("base") != existing.get("base") or stored.get("model") != existing.get("model"):
        return {"ok": False, "error": "Agent settings were not saved on disk."}
    if api_key and api_key.strip() and stored.get("api_key") != api_key.strip():
        return {"ok": False, "error": "Agent settings were not saved on disk."}
    return {
        "ok": True,
        "saved": True,
        "configured": bool(existing.get("api_key") or os.environ.get("PHARMFLOW_CLOUD_AGENT_KEY")),
    }


def _tool_argv(flag: str, rel: str, extra: list[str]) -> list[str]:
    """Argv that runs a bundled tool from source or from the frozen EXE.

    PharmFlow.exe is not CPython. Passing it a ``.py`` path opens another
    Control Panel. Frozen, the same binary routes ``--watchdog`` / ``--agent``
    / ``--cloud-agent`` in-process. From source, a real interpreter runs the script.
    """
    if getattr(sys, "frozen", False):
        return [str(sys.executable), flag, *extra]
    script = Path(__file__).resolve().parent.parent / rel
    py, _disp = _host_python_argv()
    if not py:
        py = [sys.executable]
    return [*py, str(script), *extra]


def _set_agent_run_result(payload: dict) -> None:
    global _agent_run_result
    with _agent_run_lock:
        _agent_run_result = dict(payload)


def cloud_agent_status() -> dict:
    """Last cloud-agent run. ``starting`` means the process is still running."""
    with _agent_run_lock:
        out = dict(_agent_run_result)
    thr = _agent_run_thread
    if out.get("starting") and (thr is None or not thr.is_alive()):
        return {
            "ok": False,
            "starting": False,
            "error": "Cloud agent stopped before it reported a result.",
        }
    return out


def run_cloud_agent(goal: str, *, apply: bool = False, base: str = "", model: str = "", max_steps: int | None = None) -> dict:
    """Run the LLM cloud agent in a hidden process, streaming output to the Step 9 log."""
    global _agent_run_thread
    if not getattr(sys, "frozen", False) and not Path(_agent_script_path()).is_file():
        _emit_log("go", f"[cloud agent] not found: {_agent_script_path()}\n")
        return {"ok": False, "error": "cloud agent module missing in this build"}
    with _agent_run_lock:
        if _agent_run_result.get("starting"):
            return {
                "ok": True,
                "starting": True,
                "already_running": True,
                "message": "Cloud agent is already running — watch the Run log.",
            }

    extra: list[str] = []
    if apply:
        extra.append("--apply")
    if base and base.strip():
        extra += ["--base", base.strip()]
    if model and model.strip():
        extra += ["--model", model.strip()]
    if max_steps is not None:
        extra += ["--max-steps", str(max(1, int(max_steps)))]
    extra.append(str(goal))
    cmd = _tool_argv("--cloud-agent", "tools/cloud_agent.py", extra)
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            creationflags=flags,
        )
    except OSError as exc:
        err = f"Cloud agent could not start: {exc}"
        _emit_log("go", f"[cloud agent] {err}\n")
        _set_agent_run_result({"ok": False, "starting": False, "error": err})
        return {"ok": False, "error": err}
    _set_agent_run_result(
        {
            "ok": True,
            "starting": True,
            "message": "Cloud agent started — watch the Run log.",
        }
    )

    def work() -> None:
        _emit_log("go", "\n── Cloud agent started ──\n")
        assert proc.stdout is not None
        for line in proc.stdout:
            _emit_log("go", line)
        proc.wait()
        code = proc.returncode
        if code == 0:
            _emit_log("go", f"\n── Cloud agent finished (exit {code}) ──\n")
            _set_agent_run_result(
                {
                    "ok": True,
                    "starting": False,
                    "exit_code": code,
                    "message": "Cloud agent finished.",
                }
            )
        elif code == 4:
            _emit_log("go", f"\n── Cloud agent stopped at its step limit (exit {code}) ──\n")
            _set_agent_run_result(
                {
                    "ok": False,
                    "starting": False,
                    "exit_code": code,
                    "error": "Cloud agent stopped at its step limit. It did not finish the goal.",
                }
            )
        else:
            _emit_log("go", f"\n── Cloud agent failed (exit {code}) ──\n")
            _set_agent_run_result(
                {
                    "ok": False,
                    "starting": False,
                    "exit_code": code,
                    "error": f"Cloud agent failed (exit {code}).",
                }
            )

    _agent_run_thread = threading.Thread(target=work, daemon=True, name="pharmflow-cloud-agent")
    _agent_run_thread.start()
    return {"ok": True, "starting": True, "message": "Cloud agent started — watch the Run log."}


def agent_status() -> dict:
    """Report live farm, ADB, and dashboard state. Does not reap or scan a fixed Docker port range.

    The old button spawned this EXE as if it were Python and scanned a fixed
    localhost port range. That either opened a second Control Panel or
    checked ports that are not this MuMu farm.
    """
    notes: list[str] = []
    status = _operator_status()
    listed = _status_farm_process_alive(status)
    try:
        from wizard.farm_control import (
            external_python_farm_running,
            farm_process_alive,
        )

        local = bool(farm_process_alive() or external_python_farm_running())
    except Exception as exc:  # noqa: BLE001
        local = False
        notes.append(f"farm check failed: {exc}")
    proc = local if listed is None else bool(listed or local)
    live: list[str] = []
    try:
        from automation.farm_exe_self_heal import adb_live_serials

        live = [str(s) for s in (adb_live_serials() or [])]
    except Exception as exc:  # noqa: BLE001
        notes.append(f"adb check failed: {exc}")
    dash = False
    try:
        from setup_wizard import probe_dashboard_listen_port

        dash = bool(probe_dashboard_listen_port())
    except Exception as exc:  # noqa: BLE001
        notes.append(f"control service check failed: {exc}")
    farm_dash = False
    try:
        import urllib.request

        with urllib.request.urlopen("http://127.0.0.1:8091/", timeout=1.5):  # noqa: S310
            farm_dash = True
    except Exception:
        farm_dash = False
    farm_up = bool(proc)
    lines = [
        "\n[agent] status",
        f"  Farm: {'running' if farm_up else 'down'}",
        f"  ADB live: {len(live)}",
        f"  Control service: {'up' if dash else 'down'}",
        f"  Farm dashboard: {'up' if farm_dash else 'down'}",
    ]
    if live:
        lines.append("  Phones: " + ", ".join(live))
    lines.extend(f"  {n}" for n in notes)
    _emit_log("go", "\n".join(lines) + "\n")
    message = (
        f"Farm {'running' if farm_up else 'down'} — {len(live)} phone(s) on ADB. "
        f"Control {'up' if dash else 'down'}. Farm dashboard {'up' if farm_dash else 'down'}."
    )
    out = {
        "ok": not notes,
        "running": farm_up,
        "adb": len(live),
        "dashboard": bool(farm_dash or dash),
        "message": message,
    }
    if notes:
        out["error"] = "; ".join(notes)[:500]
    return out


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
    from wizard.farm_control import (
        external_python_farm_running as _ex,
        farm_process_alive as _alive,
        load_active_profile,
        operator_dashboard_listening,
        start_farm as _sf,
    )

    global _farm_start_result, _farm_starting
    with _farm_start_lock:
        if _farm_starting:
            return {
                "ok": True,
                "starting": True,
                "message": "Farm startup is already in progress — watch the Run log.",
            }
        if _alive():
            if operator_dashboard_listening():
                return {
                    "ok": True,
                    "started": True,
                    "running": True,
                    "dashboard_ready": True,
                    "message": "Farm worker is already running. Operator dashboard is answering.",
                    "dashboard": "http://127.0.0.1:8091/",
                }
            _farm_starting = True
            _farm_start_result = {
                "ok": True,
                "starting": True,
                "running": False,
                "dashboard_ready": False,
                "message": "Farm worker is already running. Bringing the operator dashboard up.",
            }

            def dash_log(msg: str, level: str = "ok") -> None:
                _ = level
                _emit_log("go", "[farm] " + str(msg).rstrip() + "\n")

            def bring_dash() -> None:
                global _farm_start_result, _farm_starting
                from wizard.farm_control import open_operator_dashboard

                try:
                    up = bool(open_operator_dashboard(log=dash_log, open_browser=False))
                except Exception as exc:  # noqa: BLE001 — surface in Run log
                    up = False
                    _emit_log("go", f"[farm] Operator dashboard did not come up: {exc}\n")
                with _farm_start_lock:
                    _farm_starting = False
                    if up:
                        _farm_start_result = {
                            "ok": True,
                            "starting": False,
                            "running": True,
                            "dashboard_ready": True,
                            "message": "Farm worker is running. Operator dashboard is answering.",
                        }
                    else:
                        _farm_start_result = {
                            "ok": True,
                            "starting": False,
                            "running": True,
                            "dashboard_ready": False,
                            "message": (
                                "Farm worker is running. Operator dashboard is not answering "
                                "on http://127.0.0.1:8091/."
                            ),
                        }

            threading.Thread(target=bring_dash, name="pharmflow-farm-dash", daemon=True).start()
            return dict(_farm_start_result)
        # External python money path is already up. Start farm must not kill it
        # with takeover=True just because PharmFlow.exe did not own the PID.
        if _ex():
            dash_up = operator_dashboard_listening()
            message = (
                "Python farm is already running. Open the dashboard. "
                "Start farm does not take over that money path from this button."
            )
            _emit_log("go", "[farm] " + message + "\n")
            _farm_start_result = {
                "ok": False,
                "starting": False,
                "running": True,
                "external": True,
                "dashboard_ready": dash_up,
                "error": message,
                "message": message,
                "dashboard": "http://127.0.0.1:8091/",
            }
            return dict(_farm_start_result)
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
            # start_farm returns False for both "already running" and "failed
            # to arm". A fresh log is not a live process — do not promote a
            # failed arm into success.
            if not ok and _alive():
                ok = True
                _emit_log("go", "[farm] Farm is already running — not a failed start.\n")
            if ok:
                _emit_log("go", "[farm] Farm worker is up — watch the Run log and dashboard.\n")
                with _farm_start_lock:
                    _farm_start_result = {
                        "ok": True,
                        "starting": False,
                        "running": True,
                        "message": "Farm worker is up — watch the Run log and dashboard.",
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

    threading.Thread(target=work, name="pharmflow-farm-start", daemon=True).start()
    return {
        "ok": True,
        "starting": True,
        "message": "Farm startup started — watch the Run log for each lane.",
        "dashboard": "http://127.0.0.1:8091/",
    }


def stop_farm_from_app() -> dict:
    """Stop the unison money farm started by :func:`start_farm_from_app`.

    A fresh log is not a worker. If no worker process is alive, the button
    has nothing to stop. If a worker is still alive after the stop attempt,
    the button must not say the farm stopped. An external python farm that
    PharmFlow did not start is still a live money path — do not claim it is
    already stopped, and do not kill it from this button.
    """
    from wizard.farm_control import (
        external_python_farm_running as _ex,
        farm_process_alive as _alive,
        stop_farm as _stop,
    )

    global _farm_start_result
    try:
        if not _alive():
            if _ex():
                message = (
                    "Python farm is running outside this EXE. "
                    "Stop farm does not kill that money path from this button."
                )
                with _farm_start_lock:
                    _farm_start_result = {
                        "ok": False,
                        "starting": False,
                        "running": True,
                        "external": True,
                        "error": message,
                    }
                return {
                    "ok": False,
                    "stopped": False,
                    "running": True,
                    "external": True,
                    "error": message,
                }
            with _farm_start_lock:
                _farm_start_result = {
                    "ok": True,
                    "starting": False,
                    "running": False,
                    "message": "Farm is already stopped.",
                }
            return {
                "ok": True,
                "stopped": False,
                "running": False,
                "message": "Farm is already stopped.",
            }
        stopped = _stop()
        still = bool(_alive() or _ex())
        if still or not stopped:
            message = "Farm stop did not complete — a worker process is still running."
            with _farm_start_lock:
                _farm_start_result = {
                    "ok": False,
                    "starting": False,
                    "running": True,
                    "error": message,
                }
            return {"ok": False, "stopped": False, "running": True, "error": message}
        with _farm_start_lock:
            _farm_start_result = {
                "ok": True,
                "starting": False,
                "running": False,
                "message": "Farm stopped.",
            }
        return {"ok": True, "stopped": True, "running": False, "message": "Farm stopped."}
    except Exception as exc:  # noqa: BLE001
        with _farm_start_lock:
            _farm_start_result = {
                "ok": False,
                "starting": False,
                "running": True,
                "error": f"stop_farm error: {exc}",
            }
        return {"ok": False, "error": f"stop_farm error: {exc}", "running": True}


def test_phone_status() -> dict:
    """Last test-phone spin-up. ``starting`` means the worker is still running."""
    from wizard.farm_control import test_phone_status as _status

    return _status()


def spin_up_test_phone_from_app() -> dict:
    """User-clicked ONLY: bring up one phone (Docker redroid or MuMu VM) for testing."""
    from wizard.farm_control import spin_up_test_phone as _spin

    def _phone_log(msg: str, level: str = "ok") -> None:
        _emit_log("boot", f"[test phone] {msg}\n")

    try:
        return _spin(log=_phone_log)
    except Exception as exc:  # noqa: BLE001 — surface to UI
        return {"ok": False, "error": f"spin_up_test_phone error: {exc}"}


def _adb_phone_kind(serial: str, *, mumu_serials: set[str], redroid_ports: set[int]) -> str:
    """Label one live serial. A 10.0.2.x guest is MuMu only when state.json published it."""
    serial = str(serial or "").strip()
    if serial in mumu_serials:
        return "MuMu"
    if serial.startswith("emulator-"):
        return "AVD"
    if serial.startswith("127.0.0.1:"):
        try:
            port = int(serial.rsplit(":", 1)[1])
        except (ValueError, IndexError):
            port = -1
        if port in redroid_ports:
            return "redroid"
        return "emu/TCP"
    if ":" in serial:
        return "emu/TCP"
    return "USB"


def _mumu_guest_serials(mapped: dict) -> set[str]:
    """Serials MuMu published for its VMs. Not every device on the ADB bus."""
    out: set[str] = set()
    for raw in (mapped or {}).values():
        serial = str(raw or "").strip()
        if serial.startswith("10.0.2.") or serial.startswith("127.0.0.1:"):
            out.add(serial)
    return out


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

    # Docker engine + redroid containers. Do not invoke docker when the
    # engine is down — the Windows CLI shim opens Docker Desktop.
    redroid_ports: set[int] = set()
    if docker_guard.engine_running():
        # The engine is up even when no redroid containers exist. An empty
        # `docker ps` is not "start Docker Desktop".
        out["docker"] = True
        code, text = _cli(
            [
                "docker",
                "ps",
                "-a",
                "--filter",
                "name=redroid-",
                "--format",
                "{{.Names}}|{{.Status}}|{{.Ports}}",
            ]
        )
        if code == 0 and text:
            for line in text.splitlines():
                parts = line.split("|", 2)
                name = (parts[0] if parts else "").strip()
                if not name:
                    continue
                status = parts[1] if len(parts) > 1 else ""
                ports_raw = parts[2] if len(parts) > 2 else ""
                out["redroid"]["total"] += 1
                status_l = (status or "").lower()
                if status_l and not status_l.startswith(("exited", "created", "dead")):
                    out["redroid"]["up"] += 1
                for match in re.finditer(r"(?:0\.0\.0\.0|127\.0\.0\.1):(\d+)->", ports_raw):
                    redroid_ports.add(int(match.group(1)))

    # MuMu instances (offline + online) — tolerant; MuMu may not be installed.
    mumu_serials: set[str] = set()
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
                mumu_serials = _mumu_guest_serials(farm.refresh_serials() or {})
            except Exception:
                mumu_serials = set()

    # ADB inventory. A failed listing is not "zero phones."
    devices: list[Any] = []
    adb_error = ""
    try:
        from automation.adb_wrapper import AdbWrapper

        devices = list(AdbWrapper().devices_detailed() or [])
    except Exception as exc:  # noqa: BLE001 — the page must see the failure
        devices = []
        adb_error = str(exc)

    phones: list[dict[str, Any]] = []
    for d in devices:
        serial = str(getattr(d, "serial", "") or "")
        if not serial:
            continue
        online = bool(getattr(d, "online", False))
        kind = _adb_phone_kind(serial, mumu_serials=mumu_serials, redroid_ports=redroid_ports)
        if online:
            if kind == "MuMu":
                out["mumu"]["online"] += 1
            elif kind == "AVD":
                out["avd_online"] += 1
            elif kind == "USB":
                out["usb_online"] += 1
            elif kind == "emu/TCP":
                out["tcp_online"] += 1
        phones.append({"serial": serial, "kind": kind, "online": online})
    out["phones"] = phones
    out["phones_online"] = sum(1 for p in phones if p["online"])
    if adb_error:
        out["ok"] = False
        out["error"] = f"ADB inventory failed: {adb_error}"
    return out


def farm_status_from_app() -> dict:
    """Lightweight farm status for the Run page. Never waits on Tcl."""
    from wizard.farm_control import external_python_farm_running as _ex
    from wizard.farm_control import farm_process_alive as _alive

    try:
        owned = bool(_alive())
        external = bool(_ex())
        # External run_farm_354 is a live money path. Reporting running=False
        # while external=True made Home show Start farm and invited a takeover.
        running = owned or external
        with _farm_start_lock:
            result = dict(_farm_start_result)
            starting = bool(_farm_starting)
        # A fresh farm_354.log is not a running farm. Do not erase a recorded
        # start failure just because the last session wrote the log recently.
        if result.get("ok") is False and not starting and not running:
            result["running"] = False
            result["starting"] = False
        elif running:
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
        from wizard.farm_control import operator_dashboard_listening

        result["dashboard_ready"] = operator_dashboard_listening()
        return result
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "error": str(exc), "running": False, "starting": False}


def _hud_money_from_mantis(raw: dict, *, source: str) -> dict[str, Any] | None:
    """Map a Mantis-today object. None means the payload is not usable.

    A payload with no date, or a date that is not Pacific today, is not
    today's money. The operator dash file path already drops a stale file.
    This guard is the same rule for a dash JSON body.
    """
    if not isinstance(raw, dict):
        return None
    today = datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()
    if str(raw.get("date") or "") != today:
        return None
    if raw.get("impressions") is None and raw.get("clicks") is None and raw.get("payout_usd") is None:
        return None
    try:
        payout = round(float(raw.get("payout_usd") or 0.0), 2)
        clicks = max(0, int(raw.get("clicks") or 0))
        impressions = max(0, int(raw.get("impressions") or 0))
        ecpm = float(raw.get("ecpm") or 0.0)
    except (TypeError, ValueError):
        return None
    return {
        "revenue_today_usd": payout,
        "clicks": clicks,
        "impressions": impressions,
        "ecpm": ecpm,
        "as_of": str(raw.get("updated") or raw.get("date") or ""),
        "money_source": source,
    }


def _operator_status() -> dict[str, Any] | None:
    """Live operator dash payload. The HUD must match :8091, not a relative log."""
    try:
        with urllib.request.urlopen("http://127.0.0.1:8091/api/status", timeout=2.5) as resp:  # noqa: S310
            raw = json.loads(resp.read().decode("utf-8", errors="replace"))
    except Exception:
        return None
    return raw if isinstance(raw, dict) and raw.get("ok") is not False else None


def _mantis_today_file() -> dict[str, Any] | None:
    """Same Pacific-day guard the operator dash uses.

    Prefer PHARMFLOW_LOG_DIR when set. Otherwise read the freshest
    mantis_today_state.json under C:\\PharmFlow\\logs or the pre-branding
    C:\\CPharm\\logs root so a live farm writing the legacy path does not
    make the HUD show blank money when the dash is briefly down.
    """
    today = datetime.now(ZoneInfo("America/Los_Angeles")).date().isoformat()
    roots: list[Path] = []
    forced = os.environ.get("PHARMFLOW_LOG_DIR") or os.environ.get("PHARMFLOW_LOGS")
    if forced:
        roots.append(Path(forced))
    else:
        roots.append(Path(r"C:\PharmFlow\logs"))
        legacy = Path(r"C:\CPharm\logs")
        if legacy.resolve() != roots[0].resolve():
            roots.append(legacy)
    candidates: list[Path] = []
    for root in roots:
        path = root / "mantis_today_state.json"
        if path.is_file():
            candidates.append(path)
    if not candidates:
        return None
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for path in candidates:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            continue
        if not isinstance(raw, dict) or str(raw.get("date") or "") != today:
            continue
        money = _hud_money_from_mantis(raw, source="mantis_today_state")
        if money is not None:
            return money
    return None


_FARM_WORKER_NEEDLES = ("run_farm_354", "run_farm_cycles", "pharmflow_unison_supervisor")


def _status_farm_process_alive(status: dict | None) -> bool | None:
    """Whether the operator dash process list names a farm worker.

    None means the payload has no process list, so the caller must not guess.
    PharmFlow.exe plus a fresh progress file is not a worker. That bool is
    ``farm_alive`` on the dash, and the Home button used it to skip Start farm.
    """
    if not isinstance(status, dict):
        return None
    if "processes" not in status and "farm_owner" not in status:
        return None
    rows = status.get("processes") or []
    if isinstance(rows, list):
        for row in rows:
            if not isinstance(row, dict):
                continue
            cmd = str(row.get("cmd") or "")
            if any(needle in cmd for needle in _FARM_WORKER_NEEDLES):
                return True
    owner = str(status.get("farm_owner") or "")
    if owner.startswith("python"):
        return True
    return False


def get_farm_hud() -> dict:
    """Compact live telemetry for the wizard HUD strip (phones / income / state).

    Money comes from the operator dashboard (``/api/status``) or, if that
    process is down, from ``C:\\PharmFlow\\logs\\mantis_today_state.json``. A
    relative ``logs/`` FACT scrape used to report $0 from the frozen EXE
    while the dashboard already had today's numbers.
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
        "money_ok": False,
        "dashboard": "http://127.0.0.1:8091/",
    }

    money: dict[str, Any] | None = None
    status = _operator_status()
    if status:
        mantis = status.get("mantis_today")
        if isinstance(mantis, dict):
            money = _hud_money_from_mantis(mantis, source="operator_status")
        rows = status.get("phone_rows")
        if isinstance(rows, list):
            live = [
                row
                for row in rows
                if isinstance(row, dict) and str(row.get("serial") or "").strip()
            ]
            if live:
                out["phones_online"] = len(live)
    proc = _status_farm_process_alive(status)
    external = False
    try:
        from wizard.farm_control import external_python_farm_running as _ex
        from wizard.farm_control import farm_process_alive as _alive

        external = bool(_ex())
        if proc is None:
            proc = bool(_alive() or external)
        elif not proc and external:
            proc = True
    except Exception:  # noqa: BLE001 — HUD is best-effort
        if proc is None:
            proc = False
    out["running"] = bool(proc)
    out["external"] = bool(external)
    out["farm"] = "run" if out["running"] else "off"
    if money is None:
        money = _mantis_today_file()
    if money:
        out.update(money)
        out["money_ok"] = True

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
        # Bundled adb returning 0 must not wipe a live serial count from the dash.
        if n:
            out["phones_online"] = n
    except Exception:  # noqa: BLE001
        pass

    return out
