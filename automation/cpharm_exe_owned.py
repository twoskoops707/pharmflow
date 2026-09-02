"""CPharm.exe ownership flags — helpers must not dual-spawn farm workers."""

from __future__ import annotations

import os
from pathlib import Path

EXE_OWNED_FLAG = Path(r"C:\CPharm\logs\CPHARM_EXE_OWNED.flag")


def exe_owns_farm() -> bool:
    """True when CPharm Start Farm owns the money path (EXE or its children)."""
    for key in ("CPHARM_EXE_OWNED_FARM", "CPHARM_FARM_IN_PROCESS"):
        if str(os.environ.get(key) or "").strip().lower() in ("1", "true", "yes", "on"):
            return True
    try:
        return EXE_OWNED_FLAG.is_file()
    except OSError:
        return False


def mark_exe_owned(*, in_process: bool = False) -> None:
    os.environ["CPHARM_EXE_OWNED_FARM"] = "1"
    if in_process:
        os.environ["CPHARM_FARM_IN_PROCESS"] = "1"
    try:
        EXE_OWNED_FLAG.parent.mkdir(parents=True, exist_ok=True)
        EXE_OWNED_FLAG.write_text(
            "owned_by=CPharm.exe\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def clear_exe_owned() -> None:
    os.environ.pop("CPHARM_EXE_OWNED_FARM", None)
    os.environ.pop("CPHARM_FARM_IN_PROCESS", None)
    try:
        EXE_OWNED_FLAG.unlink(missing_ok=True)
    except OSError:
        pass
