"""Process dedupe helpers — unison stack must never double-spawn lanes."""
from __future__ import annotations

from typing import Iterable


def pids_for_script(script_name: str) -> list[int]:
    try:
        import psutil
    except ImportError:
        return []
    found: list[int] = []
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmd = " ".join(str(x) for x in (proc.info.get("cmdline") or []))
            pid = int(proc.info.get("pid") or 0)
        except (TypeError, ValueError, psutil.Error):
            continue
        if script_name in cmd and "-c" not in cmd:
            found.append(pid)
    return sorted(found)


def dedupe_keep_newest(script_name: str) -> list[int]:
    """Kill duplicate workers; keep highest PID (newest)."""
    pids = pids_for_script(script_name)
    if len(pids) <= 1:
        return []
    killed: list[int] = []
    keep = pids[-1]
    try:
        import psutil

        for pid in pids[:-1]:
            try:
                psutil.Process(pid).terminate()
                killed.append(pid)
            except (psutil.Error, OSError):
                pass
    except ImportError:
        pass
    return killed


def any_running(script_names: Iterable[str]) -> bool:
    return any(pids_for_script(name) for name in script_names)
