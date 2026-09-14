"""Launch a visible Tk wizard page in a separate process (reliable with WebView shell)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def spawn_wizard_page(page_index: int, *, action: str | None = None) -> dict:
    """Spawn ``PharmFlow.exe --internal-tk-page N [--internal-tk-action X]``.

    The child must be a visible GUI process. CREATE_NO_WINDOW / DETACHED_PROCESS
    set STARTUPINFO to SW_HIDE, which parks the window off-screen so the operator
    thinks the button did nothing. Console flash is avoided by launching pythonw
    (source) or the windowed EXE (frozen), not by hiding the window.
    """
    if getattr(sys, "frozen", False):
        exe = str(sys.executable)
        args = [exe, "--internal-tk-page", str(int(page_index))]
    else:
        entry = Path(__file__).resolve().parent / "cpharm_desktop.py"
        py = Path(sys.executable)
        if py.name.lower() == "python.exe":
            pyw = py.with_name("pythonw.exe")
            if pyw.is_file():
                py = pyw
        args = [str(py), str(entry), "--internal-tk-page", str(int(page_index))]
    if action:
        args.extend(["--internal-tk-action", str(action)])
    try:
        popen_kwargs: dict = {"close_fds": False}
        if sys.platform == "win32":
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 1  # SW_SHOWNORMAL
            popen_kwargs["startupinfo"] = si
        subprocess.Popen(args, **popen_kwargs)
        return {"ok": True, "spawned": True, "page": int(page_index), "action": action}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
