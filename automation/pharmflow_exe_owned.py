"""PharmFlow.exe ownership flags — helpers must not dual-spawn farm workers."""

from __future__ import annotations

import os
from pathlib import Path

EXE_OWNED_FLAG = Path(r"C:\PharmFlow\logs\PHARMFLOW_EXE_OWNED.flag")


def exe_owns_farm() -> bool:
    """True when PharmFlow Start Farm owns the money path (EXE or its children)."""
    for key in ("PHARMFLOW_EXE_OWNED_FARM", "PHARMFLOW_FARM_IN_PROCESS"):
        if str(os.environ.get(key) or "").strip().lower() in ("1", "true", "yes", "on"):
            return True
    try:
        return EXE_OWNED_FLAG.is_file()
    except OSError:
        return False


def pharmflow_exe_alive() -> bool:
    """True when at least one PharmFlow.exe process is live on this box."""
    try:
        from automation.process_scan import pharmflow_exe_pids

        return bool(pharmflow_exe_pids())
    except Exception:
        return False


def mark_exe_owned(*, in_process: bool = False) -> None:
    os.environ["PHARMFLOW_EXE_OWNED_FARM"] = "1"
    if in_process:
        os.environ["PHARMFLOW_FARM_IN_PROCESS"] = "1"
    try:
        EXE_OWNED_FLAG.parent.mkdir(parents=True, exist_ok=True)
        EXE_OWNED_FLAG.write_text(
            "owned_by=PharmFlow.exe\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def clear_exe_owned() -> None:
    os.environ.pop("PHARMFLOW_EXE_OWNED_FARM", None)
    os.environ.pop("PHARMFLOW_FARM_IN_PROCESS", None)
    try:
        EXE_OWNED_FLAG.unlink(missing_ok=True)
    except OSError:
        pass


def reconcile_stale_exe_ownership(*, reap: bool = False) -> list[str]:
    """Clear sticky ownership when PharmFlow.exe is gone; optional one orphan reap.

    Crash / kill without ``stop_farm`` leaves ``PHARMFLOW_EXE_OWNED.flag`` set.
    External babysitters then exit (anti dual-spawn) and nothing reaps leftover
    python/tor. A durable janitor (not an orphan respawner) clears the flag and
    may run one ``reap_stale_processes`` pass.
    """
    notes: list[str] = []
    if not exe_owns_farm():
        return notes
    if pharmflow_exe_alive():
        return notes
    notes.append("stale_exe_owned")
    # Clear first so a nested reap → reconcile is a no-op (no recursion).
    clear_exe_owned()
    notes.append("cleared_stale_exe_owned")
    if reap:
        try:
            from automation.farm_exe_self_heal import reap_stale_processes

            notes.extend(reap_stale_processes(apply=True)[:24])
        except Exception as exc:  # noqa: BLE001
            notes.append(f"stale_reap_err:{type(exc).__name__}:{exc}")
    return notes
