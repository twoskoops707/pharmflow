"""
Close stale MuMu, adb, and CPharm processes before CPharmMuMuSetup opens.

Runs automatically when **CPharmMuMuSetup.exe** starts (before the UI). On the
**first setup** (``mumu_setup_complete`` not yet set), also closes MuMu so you
start from a clean slate. After setup is done, re-opening setup only clears
duplicate CPharm / adb / setup instances — not running MuMu phones.

Skip: ``CPHARM_SKIP_STARTUP_CLEANUP=1``
Force MuMu kill even after setup: ``CPHARM_FORCE_STARTUP_CLEANUP=1``

Dev CLI: ``python tools/kill_cpharm_stale_processes.py``
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

LogFn = Callable[[str], None]

# MuMu / Netease emulator host processes (Windows MuMuPlayer ARM + legacy builds).
MUMU_PROCESS_BASENAMES = frozenset(
    {
        "mumuplayer.exe",
        "mumunxmain.exe",
        "mumunxdevice.exe",
        "mumumanager.exe",
        "nemux-shell-winui.manager.exe",
        "nemuplayer.exe",
        "nemuheadless.exe",
        "nemusvc.exe",
        "nemuservice.exe",
        "mumuvmm.exe",
        "mumuvmmsvc.exe",
    }
)

CPHARM_EXE_BASENAMES = frozenset(
    {
        "cpharmmumusetup.exe",
        "cpharm.exe",
    }
)

CPHARM_PY_CMDLINE_MARKERS = (
    "cpharm_desktop",
    "cpharm_mumu_setup",
    "setup_wizard",
    "dashboard.py",
    "mumu_setup_webview",
)

ADB_BASENAMES = frozenset({"adb.exe", "adb"})

_SUBPROC_FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


def _noop_log(_msg: str) -> None:
    pass


def _skip_cleanup() -> bool:
    return os.environ.get("CPHARM_SKIP_STARTUP_CLEANUP", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _force_mumu_kill() -> bool:
    return os.environ.get("CPHARM_FORCE_STARTUP_CLEANUP", "").strip().lower() in (
        "1",
        "true",
        "yes",
    )


def _data_root_for_marker() -> Path:
    from wizard_paths import cpharm_default_install_root, cpharm_install_root, has_automation_dashboard

    try:
        root = cpharm_install_root()
    except Exception:
        root = cpharm_default_install_root()
    if has_automation_dashboard(root):
        return root
    home = Path.home() / "CPharm"
    if has_automation_dashboard(home):
        return home
    return root


def is_first_setup_open() -> bool:
    import preflight_core as preflight

    return not preflight.mumu_setup_already_done(_data_root_for_marker())


def _protected_pids(my_pid: int) -> set[int]:
    protected = {my_pid}
    try:
        import psutil

        proc = psutil.Process(my_pid)
        for child in proc.children(recursive=True):
            protected.add(child.pid)
    except Exception:
        pass
    return protected


def _adb_kill_server(log: LogFn) -> None:
    exe: str | None = None
    try:
        from adb_paths import adb_executable

        exe = adb_executable()
    except Exception:
        pass
    if not exe or not Path(exe).is_file():
        return
    try:
        subprocess.run(
            [exe, "kill-server"],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=_SUBPROC_FLAGS,
        )
        log("  adb kill-server")
    except (OSError, subprocess.TimeoutExpired):
        pass


def _basename(name: str) -> str:
    return Path(name).name.lower()


def _exe_path_lower(proc) -> str:
    try:
        return (proc.exe() or "").lower()
    except Exception:
        return ""


def _cmdline_text(proc) -> str:
    try:
        parts = proc.cmdline()
        return " ".join(parts).lower() if parts else ""
    except Exception:
        return ""


def _is_mumu_process(proc) -> bool:
    try:
        base = _basename(proc.name())
    except Exception:
        return False
    if base in MUMU_PROCESS_BASENAMES:
        return True
    exe = _exe_path_lower(proc)
    if not exe:
        return False
    if "mumuplayer" in exe or "mumunx" in exe:
        return True
    if "netease" in exe and ("mumu" in exe or "nemu" in exe):
        return True
    return False


def _is_phone_setup_process(proc) -> bool:
    cmd = _cmdline_text(proc)
    return "--phone-setup" in cmd or "phone_setup_entry" in cmd


def _is_cpharm_exe_process(proc) -> bool:
    try:
        return _basename(proc.name()) in CPHARM_EXE_BASENAMES
    except Exception:
        return False


def _is_cpharm_python_process(proc) -> bool:
    try:
        base = _basename(proc.name())
    except Exception:
        return False
    if base not in ("python.exe", "pythonw.exe", "python3.exe"):
        return False
    cmd = _cmdline_text(proc)
    return any(m in cmd for m in CPHARM_PY_CMDLINE_MARKERS)


def _is_adb_process(proc) -> bool:
    try:
        return _basename(proc.name()) in ADB_BASENAMES
    except Exception:
        return False


def _terminate_process(proc, log: LogFn) -> tuple[bool, str]:
    label = "unknown"
    try:
        label = proc.name()
        pid = proc.pid
    except Exception as exc:
        return False, str(exc)
    try:
        proc.terminate()
    except Exception as exc:
        return False, f"{label} (pid {pid}): {exc}"
    try:
        proc.wait(timeout=4)
        log(f"  stopped {label} (pid {pid})")
        return True, f"{label}:{pid}"
    except Exception:
        try:
            proc.kill()
            proc.wait(timeout=3)
            log(f"  killed {label} (pid {pid})")
            return True, f"{label}:{pid}"
        except Exception as exc:
            return False, f"{label} (pid {pid}): {exc}"


def run_startup_cleanup(
    *,
    first_time: bool | None = None,
    log: LogFn | None = None,
    my_pid: int | None = None,
) -> dict:
    """
    Close stale processes. Returns ``{ok, first_time, killed, failed, skipped}``.

    ``first_time`` defaults to :func:`is_first_setup_open` unless overridden.
    """
    log = log or _noop_log
    if _skip_cleanup():
        log("Startup cleanup skipped (CPHARM_SKIP_STARTUP_CLEANUP).")
        return {"ok": True, "first_time": False, "killed": [], "failed": [], "skipped": ["env"]}

    if sys.platform != "win32":
        log("Startup cleanup: Windows only — skipped on this OS.")
        return {"ok": True, "first_time": False, "killed": [], "failed": [], "skipped": ["platform"]}

    if first_time is None:
        first_time = is_first_setup_open()
    if _force_mumu_kill():
        first_time = True

    my_pid = my_pid if my_pid is not None else os.getpid()
    protected = _protected_pids(my_pid)

    killed: list[str] = []
    failed: list[str] = []
    skipped: list[str] = []

    log("")
    if first_time:
        log("First-time setup — closing previous MuMu, adb, and CPharm processes…")
    else:
        log("Closing stale CPharm / adb / setup processes (MuMu left running)…")

    _adb_kill_server(log)
    time.sleep(0.4)

    try:
        import psutil
    except ImportError:
        log("  psutil not available — adb kill-server only.")
        return {
            "ok": True,
            "first_time": first_time,
            "killed": killed,
            "failed": failed,
            "skipped": ["psutil"],
        }

    targets: list[tuple[object, str]] = []
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            pid = proc.pid
        except Exception:
            continue
        if pid in protected:
            skipped.append(f"protected:{pid}")
            continue
        try:
            if _is_cpharm_exe_process(proc):
                if pid == my_pid:
                    continue
                if _is_phone_setup_process(proc):
                    skipped.append(f"phone-setup:{pid}")
                    continue
                targets.append((proc, "cpharm"))
            elif _is_cpharm_python_process(proc):
                if _is_phone_setup_process(proc):
                    skipped.append(f"phone-setup:{pid}")
                    continue
                targets.append((proc, "cpharm_py"))
            elif first_time and _is_adb_process(proc):
                targets.append((proc, "adb"))
            elif first_time and _is_mumu_process(proc):
                targets.append((proc, "mumu"))
        except Exception:
            continue

    # Children before parents where possible — sort by create time descending.
    def _sort_key(item):
        proc, _kind = item
        try:
            return proc.create_time()
        except Exception:
            return 0.0

    targets.sort(key=_sort_key, reverse=True)

    for proc, kind in targets:
        ok, detail = _terminate_process(proc, log)
        if ok:
            killed.append(f"{kind}:{detail}")
        else:
            failed.append(detail)

    if not killed and not failed:
        log("  nothing to close.")
    elif killed:
        log(f"  closed {len(killed)} process(es).")
    if failed:
        log(f"  {len(failed)} process(es) could not be closed (may need Admin).")

    return {
        "ok": not failed,
        "first_time": first_time,
        "killed": killed,
        "failed": failed,
        "skipped": skipped,
    }


def run_setup_startup_cleanup(log: LogFn | None = None) -> dict:
    """Entry used by CPharmMuMuSetup.exe ``main()``."""
    return run_startup_cleanup(log=log)


def format_cleanup_log_line(summary: dict) -> str:
    if summary.get("skipped") == ["env"]:
        return ""
    killed = summary.get("killed") or []
    if not killed:
        return "Startup cleanup: no stale processes found."
    return f"Startup cleanup: closed {len(killed)} stale process(es)."
