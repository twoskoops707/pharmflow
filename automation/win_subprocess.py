"""Subprocess helpers — hide console flash on Windows for ADB/Tor/tools."""

from __future__ import annotations

import subprocess
import sys
from typing import Any


def hidden_run_kwargs() -> dict[str, Any]:
    """Kwargs for ``subprocess.run`` / ``Popen`` that avoid a console window on Windows.

    Without ``CREATE_NO_WINDOW``, every ``adb.exe`` / ``tor.exe`` spawn flashes a
    terminal when the parent is a windowed GUI / ``pythonw`` (no console to inherit).
    That flash storm steals focus and makes the machine unusable.
    """
    if sys.platform != "win32":
        return {}
    # CREATE_NO_WINDOW is required for console-subsystem binaries (tor.exe, adb.exe).
    create_no_window = int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
    kwargs: dict[str, Any] = {"creationflags": create_no_window}
    startupinfo = subprocess.STARTUPINFO()
    startupinfo.dwFlags |= int(subprocess.STARTF_USESHOWWINDOW)
    startupinfo.wShowWindow = 0  # SW_HIDE
    kwargs["startupinfo"] = startupinfo
    return kwargs


def hide_console_for_pid(pid: int) -> None:
    """Best-effort: hide any top-level window owned by ``pid`` (Windows).

    Uses both ``ShowWindow(SW_HIDE)`` and ``ShowWindowAsync`` so Cascadia /
    PseudoConsole flashes that race the poller still get suppressed.
    """
    if sys.platform != "win32" or pid <= 0:
        return
    try:
        import ctypes

        user32 = ctypes.windll.user32
        pid_buf = ctypes.c_ulong()
        SW_HIDE = 0

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def _cb(hwnd, _lparam):  # type: ignore[misc]
            try:
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_buf))
                if int(pid_buf.value) != int(pid):
                    return True
                # Hide even if not yet marked visible — catches 1-frame pops.
                user32.ShowWindow(hwnd, SW_HIDE)
                try:
                    user32.ShowWindowAsync(hwnd, SW_HIDE)
                except Exception:
                    pass
            except Exception:
                pass
            return True

        user32.EnumWindows(_cb, 0)
    except Exception:
        return


def hide_console_burst(pid: int, *, rounds: int = 40, delay_s: float = 0.025) -> None:
    """Hide console windows repeatedly right after spawn (covers AllocConsole races)."""
    import time

    for _ in range(max(1, rounds)):
        hide_console_for_pid(pid)
        # Also hide conhost children of this pid (blank flash often lives there).
        try:
            import psutil

            for child in psutil.Process(pid).children(recursive=True):
                cname = (child.name() or "").lower()
                if cname in {"conhost.exe", "conhost", "openconsole.exe"}:
                    hide_console_for_pid(child.pid)
        except Exception:
            pass
        time.sleep(delay_s)
