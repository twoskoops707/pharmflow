"""Portable code/data roots so CPharm.exe works without a FamFlow checkout.

Helpers spawned from the frozen EXE must not hardcode a developer PC path.
"""

from __future__ import annotations

import os
import shutil
import subprocess
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
    """Interpreter for spawning scripts. Never CPharm.exe (it is a GUI).

    Stealth/farm helpers import the ``cryptography`` stack (TLS-inject CA,
    exit-IP guard, Tor repair). Native-ARM Windows Pythons have no
    cryptography wheel for 3.14, so spawning with ``sys.executable`` on an ARM
    box silently kills every fix child (``ModuleNotFoundError: cryptography``).
    Prefer a deps-complete interpreter: the current one when it works, else a
    system pythonw that can import the full stack.
    """
    exe = Path(sys.executable)
    name = exe.name.lower()
    if "cpharm" in name or is_frozen():
        return _deps_complete_pythonw() or _system_pythonw()
    if os.name == "nt" and name in ("python.exe", "pythonw.exe"):
        if _has_cryptography(exe):
            pyw = exe.with_name("pythonw.exe") if name == "python.exe" else exe
            if pyw.is_file():
                return str(pyw)
    # Current interpreter lacks deps (e.g. ARM64 python): find one that has them.
    found = _deps_complete_pythonw()
    if found:
        return found
    return str(exe) if exe.is_file() else _system_pythonw()


def _has_cryptography(py: Path) -> bool:
    """True when this interpreter can import the stealth CA stack."""
    try:
        r = subprocess.run(
            [str(py), "-c", "import cryptography"],
            capture_output=True,
            timeout=12,
            creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0),
        )
        return r.returncode == 0
    except Exception:
        return False


def _deps_complete_pythonw() -> str | None:
    for cand in _pythonw_candidates():
        if not cand.is_file() or "cpharm" in str(cand).lower():
            continue
        py = cand.with_name("python.exe")
        if py.is_file() and _has_cryptography(py):
            return str(cand)
    return None


def _pythonw_candidates() -> list[Path]:
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    return [
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


def _system_pythonw() -> str | None:
    for cand in _pythonw_candidates():
        if cand.is_file() and "cpharm" not in str(cand).lower():
            return str(cand)
    for name in ("pythonw", "python"):
        found = shutil.which(name)
        if found and "cpharm" not in found.lower():
            return found
    return None
