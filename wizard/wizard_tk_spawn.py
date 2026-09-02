"""Launch a visible Tk wizard page in a separate process (reliable with WebView shell)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def spawn_wizard_page(page_index: int, *, action: str | None = None) -> dict:
    """Spawn ``CPharm.exe --internal-tk-page N [--internal-tk-action X]``.

    A separate process gets its own top-level window, so it always appears in
    front of the WebView shell instead of hiding behind it (the failure mode of
    in-process Tk Toplevels on Windows WebView2).
    """
    if getattr(sys, "frozen", False):
        exe = str(sys.executable)
        args = [exe, "--internal-tk-page", str(int(page_index))]
    else:
        entry = Path(__file__).resolve().parent / "cpharm_desktop.py"
        args = [str(sys.executable), str(entry), "--internal-tk-page", str(int(page_index))]
    if action:
        args.extend(["--internal-tk-action", str(action)])
    try:
        popen_kwargs = {"close_fds": False}
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = (
                getattr(subprocess, "CREATE_NO_WINDOW", 0)
                | getattr(subprocess, "DETACHED_PROCESS", 0)
            )
        subprocess.Popen(args, **popen_kwargs)
        return {"ok": True, "spawned": True, "page": int(page_index), "action": action}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
