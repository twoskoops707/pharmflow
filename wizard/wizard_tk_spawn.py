"""Launch a visible Tk wizard page in a separate process (reliable with WebView shell)."""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
import uuid
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
        entry = Path(__file__).resolve().parent / "pharmflow_desktop.py"
        py = Path(sys.executable)
        if py.name.lower() == "python.exe":
            pyw = py.with_name("pythonw.exe")
            if pyw.is_file():
                py = pyw
        args = [str(py), str(entry), "--internal-tk-page", str(int(page_index))]
    if action:
        args.extend(["--internal-tk-action", str(action)])
    token = uuid.uuid4().hex
    ready_path = Path(tempfile.gettempdir()) / f"pharmflow_tk_ready_{token}.txt"
    err_path = Path(tempfile.gettempdir()) / f"pharmflow_tk_err_{token}.log"
    env = os.environ.copy()
    env["PHARMFLOW_TK_READY_FILE"] = str(ready_path)
    err_handle = None
    try:
        err_handle = open(err_path, "w", encoding="utf-8")
        popen_kwargs: dict = {
            "close_fds": False,
            "env": env,
            "stdout": err_handle,
            "stderr": subprocess.STDOUT,
        }
        if sys.platform == "win32":
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 1  # SW_SHOWNORMAL
            popen_kwargs["startupinfo"] = si
        proc = subprocess.Popen(args, **popen_kwargs)
    except Exception as exc:
        return {"ok": False, "error": str(exc), "window_ready": False, "started": False}
    finally:
        if err_handle is not None:
            err_handle.close()
    return confirm_spawned_window(
        proc,
        ready_path,
        err_path,
        page=int(page_index),
        action=action,
    )


def confirm_spawned_window(
    proc: subprocess.Popen,
    ready_path: Path,
    err_path: Path,
    *,
    page: int = 0,
    action: str | None = None,
    timeout: float = 15.0,
) -> dict:
    """Opened means the child mapped a Tk window, not that Popen returned.

    A child that dies before writing the ready file did not open a window.
    A child still importing is not an open window either.
    """
    deadline = time.time() + max(0.2, float(timeout))
    while time.time() < deadline:
        if ready_path.is_file():
            return {
                "ok": True,
                "spawned": True,
                "started": True,
                "window_ready": True,
                "page": page,
                "action": action,
                "message": "Opened a wizard window — progress shows there, not in a hidden thread.",
            }
        code = proc.poll()
        if code is not None:
            return {
                "ok": False,
                "spawned": True,
                "started": False,
                "window_ready": False,
                "page": page,
                "action": action,
                "error": _wizard_exit_error(code, err_path),
            }
        time.sleep(0.2)
    if proc.poll() is not None:
        return {
            "ok": False,
            "spawned": True,
            "started": False,
            "window_ready": False,
            "page": page,
            "action": action,
            "error": _wizard_exit_error(proc.returncode, err_path),
        }
    return {
        "ok": True,
        "spawned": True,
        "started": True,
        "window_ready": False,
        "page": page,
        "action": action,
        "message": "Wizard process started. The window is not up yet.",
    }


def _wizard_exit_error(code: int | None, err_path: Path) -> str:
    tail = ""
    try:
        text = err_path.read_text(encoding="utf-8", errors="replace").strip()
        if text:
            tail = text[-400:]
    except OSError:
        tail = ""
    base = f"Wizard window exited before it opened (exit {code})."
    return f"{base} {tail}".strip()
