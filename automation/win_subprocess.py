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
    """Best-effort: hide any visible top-level window owned by ``pid`` (Windows)."""
    if sys.platform != "win32" or pid <= 0:
        return
    try:
        import ctypes

        user32 = ctypes.windll.user32
        pid_buf = ctypes.c_ulong()

        @ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)
        def _cb(hwnd, _lparam):  # type: ignore[misc]
            try:
                if not user32.IsWindowVisible(hwnd):
                    return True
                user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid_buf))
                if int(pid_buf.value) == int(pid):
                    user32.ShowWindow(hwnd, 0)
            except Exception:
                pass
            return True

        user32.EnumWindows(_cb, 0)
    except Exception:
        return


def hide_console_burst(pid: int, *, rounds: int = 20, delay_s: float = 0.05) -> None:
    """Hide console windows repeatedly right after spawn (covers AllocConsole races)."""
    import time

    for _ in range(max(1, rounds)):
        hide_console_for_pid(pid)
        # Also hide conhost children of this pid (blank flash often lives there).
        try:
            import psutil

            for child in psutil.Process(pid).children(recursive=False):
                if (child.name() or "").lower() in {"conhost.exe", "conhost"}:
                    hide_console_for_pid(child.pid)
        except Exception:
            pass
        time.sleep(delay_s)
