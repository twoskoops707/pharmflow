"""Kill console-window flashing for ALL child processes (Windows).

Long-running keepers run under ``pythonw.exe`` (no console). Every ``adb.exe`` /
``tor.exe`` / ``curl.exe`` / ``taskkill`` / ``powershell`` they spawn therefore
allocates a brand-new console window that flashes and steals focus.

``install()`` monkeypatches ``subprocess.Popen.__init__`` — the single choke
point that ``run`` / ``check_output`` / ``check_call`` / ``call`` all funnel
through — so every child is created with ``CREATE_NO_WINDOW`` + a hidden
``STARTUPINFO``. Import this module and call ``install()`` at the very top of
every entry-point script (before any subprocess use).
"""

from __future__ import annotations

import subprocess
import sys

_CREATE_NO_WINDOW = 0x08000000
_CREATE_NEW_CONSOLE = 0x00000010
_DETACHED_PROCESS = 0x00000008
# Windows Console Host — CREATE_NO_WINDOW is ignored when Windows Terminal is
# the default terminal ("Let Windows decide" = all-zero GUIDs).
_CONHOST_GUID = "{B23D10C0-E52E-411E-9D5B-C09FDF709C7D}"
_installed = False


def pin_windows_console_host() -> None:
    """Force Console Host so CREATE_NO_WINDOW actually hides farm children."""
    if sys.platform != "win32":
        return
    try:
        import winreg

        key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, r"Console\%%Startup")
        try:
            winreg.SetValueEx(key, "DelegationConsole", 0, winreg.REG_SZ, _CONHOST_GUID)
            winreg.SetValueEx(key, "DelegationTerminal", 0, winreg.REG_SZ, _CONHOST_GUID)
        finally:
            winreg.CloseKey(key)
    except OSError:
        return


def install() -> None:
    """Idempotently patch subprocess so no child ever opens a console window."""
    global _installed
    if sys.platform != "win32":
        _installed = True
        return
    pin_windows_console_host()
    if _installed:
        return
    _installed = True

    _orig_init = subprocess.Popen.__init__

    def _patched_init(self, *args, **kwargs):  # type: ignore[no-untyped-def]
        cmd = args[0] if args else kwargs.get("args")
        parts = cmd if isinstance(cmd, (list, tuple)) else [cmd]
        cmd_s = " ".join(str(x) for x in parts if x is not None)
        # Wizard pages are GUI children. SW_HIDE + CREATE_NO_WINDOW parks them
        # off-screen (same WebView2 startup-show bug) so the operator sees nothing.
        if "--internal-tk-page" in cmd_s:
            flags = int(kwargs.get("creationflags", 0) or 0)
            flags &= ~(_CREATE_NO_WINDOW | _DETACHED_PROCESS | _CREATE_NEW_CONSOLE)
            kwargs["creationflags"] = flags
            si = kwargs.get("startupinfo")
            if si is None:
                si = subprocess.STARTUPINFO()
            try:
                si.dwFlags |= int(subprocess.STARTF_USESHOWWINDOW)
                si.wShowWindow = 1  # SW_SHOWNORMAL
                kwargs["startupinfo"] = si
            except Exception:
                pass
            return _orig_init(self, *args, **kwargs)
        flags = int(kwargs.get("creationflags", 0) or 0)
        # CREATE_NO_WINDOW cannot be combined with DETACHED_PROCESS or
        # CREATE_NEW_CONSOLE — Windows ignores both and a console flashes.
        # Drop the conflicting flags; keep CREATE_NO_WINDOW.
        flags &= ~(_DETACHED_PROCESS | _CREATE_NEW_CONSOLE)
        kwargs["creationflags"] = flags | _CREATE_NO_WINDOW
        si = kwargs.get("startupinfo")
        if si is None:
            si = subprocess.STARTUPINFO()
        try:
            si.dwFlags |= int(subprocess.STARTF_USESHOWWINDOW)
            si.wShowWindow = 0  # SW_HIDE
            kwargs["startupinfo"] = si
        except Exception:
            pass
        return _orig_init(self, *args, **kwargs)

    subprocess.Popen.__init__ = _patched_init  # type: ignore[assignment]


# Auto-install on import so a bare ``import automation.no_window`` is enough.
install()
