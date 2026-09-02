"""Portable code/data roots so CPharm.exe works without a FamFlow checkout.

Helpers spawned from the frozen EXE must not hardcode a developer PC path.
"""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

_WINDOWS_DATA = Path(r"C:\CPharm")


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"))


def code_root() -> Path:
    """Directory that contains ``automation/`` and ``scripts/``.

    Frozen EXE → PyInstaller MEIPASS. Dev / helper python → this repo.
    Override with ``CPHARM_CODE_ROOT`` on unusual layouts.
    """
    env = (os.environ.get("CPHARM_CODE_ROOT") or "").strip()
    if env:
        p = Path(env)
        if p.is_dir():
            return p
    if is_frozen():
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    here = Path(__file__).resolve()
    if here.parent.name == "automation":
        root = here.parent.parent
        if (root / "automation").is_dir():
            return root
    if here.parent.name == "scripts":
        return here.parent.parent
    return here.parent


def logs_dir() -> Path:
    env = (os.environ.get("CPHARM_LOGS") or os.environ.get("CPHARM_LOG_DIR") or "").strip()
    if env:
        p = Path(env)
        p.mkdir(parents=True, exist_ok=True)
        return p
    d = _WINDOWS_DATA / "logs" if os.name == "nt" else (code_root() / "logs")
    d.mkdir(parents=True, exist_ok=True)
    return d


def helper_python() -> str | None:
    """Interpreter for spawning scripts. Never CPharm.exe (it is a GUI)."""
    exe = Path(sys.executable)
    name = exe.name.lower()
    if "cpharm" in name or is_frozen():
        return _system_pythonw()
    if os.name == "nt" and name == "python.exe":
        pyw = exe.with_name("pythonw.exe")
        if pyw.is_file():
            return str(pyw)
    return str(exe) if exe.is_file() else _system_pythonw()


def _system_pythonw() -> str | None:
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    candidates = [
        local / "Python" / "pythoncore-3.14-64" / "pythonw.exe",
        local / "Python" / "pythoncore-3.13-64" / "pythonw.exe",
        local / "Python" / "pythoncore-3.12-64" / "pythonw.exe",
        local / "Programs" / "Python" / "Python314" / "pythonw.exe",
        local / "Programs" / "Python" / "Python313" / "pythonw.exe",
        local / "Programs" / "Python" / "Python312" / "pythonw.exe",
        local / "Programs" / "Python" / "Python311" / "pythonw.exe",
        Path(r"C:\Python314\pythonw.exe"),
        Path(r"C:\Python313\pythonw.exe"),
        Path(r"C:\Python312\pythonw.exe"),
        Path(r"C:\Python311\pythonw.exe"),
    ]
    for cand in candidates:
        if cand.is_file() and "cpharm" not in str(cand).lower():
            return str(cand)
    for name in ("pythonw", "python"):
        found = shutil.which(name)
        if found and "cpharm" not in found.lower():
            return found
    return None
