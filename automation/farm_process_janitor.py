"""PharmFlow janitor — reap hung ADB consoles, orphan conhost, leaked bash/wsl, dup helpers.

Called every remediator tick. Does not kill PharmFlow.exe, the farm worker, dash,
MuMu phone shells, or Tor.
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from automation.process_scan import SINGLETON_HELPERS, cull_duplicates_keep_newest

LOG = Path(os.environ.get("PHARMFLOW_LOGS") or r"C:\PharmFlow\logs")
HB = LOG / "farm_process_janitor_heartbeat.txt"

_KEEP_CONHOST_PARENTS = {
    "tor.exe",
    "nemux-shell-winui.exe",
    "nemux-shell-winui.manager.exe",
    "pharmflow.exe",
    "cursor.exe",
    "node.exe",
}

_LEAK_CMD_MARKERS = (
    "track-telemetry",
    "sg-python.sh",
    "kill-azure-telemetry.ps1",
)

_FLASH_CMD_MARKERS = (
    "nemux-shell-winui",
    "watch_adb_devices",
    "platform-tools",
    r"c:\pharmflow\bundled\adb",
)

_HUNG_ONESHOT = (
    "kill_azure_telemetry.py",
    "kill-azure-telemetry.ps1",
)

_ADB_DUMP_MARKERS = (
    "uiautomator",
    "dumpsys window",
    "dumpsys activity activities",
    "dump /sdcard",
)

_MAX_ADB = 12
_MAX_BASH_WSL = 6
_ADB_DUMP_MAX_AGE_S = 25.0
_ONESHOT_MAX_AGE_S = 120.0
_ADB_CONHOST_MAX_AGE_S = 45.0


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def cmdline_of(proc_info: dict[str, Any]) -> str:
    return " ".join(str(x) for x in (proc_info.get("cmdline") or []))


def should_kill_leak_shell(name: str, cmd: str) -> bool:
    n = (name or "").lower()
    low = (cmd or "").lower()
    if n not in {"bash.exe", "bash", "wsl.exe", "wsl", "wslhost.exe", "cmd.exe", "cmd", "powershell.exe"}:
        return False
    return any(m in low for m in _LEAK_CMD_MARKERS)


def should_kill_flash_cmd(name: str, cmd: str) -> bool:
    n = (name or "").lower()
    low = (cmd or "").lower()
    if n not in {"cmd.exe", "cmd"}:
        return False
    return any(m in low for m in _FLASH_CMD_MARKERS)


def should_kill_hung_adb(name: str, cmd: str, age_s: float) -> bool:
    if (name or "").lower() not in {"adb.exe", "adb"}:
        return False
    if "fork-server" in (cmd or "") or "start-server" in (cmd or ""):
        return False
    if age_s < _ADB_DUMP_MAX_AGE_S:
        return False
    low = (cmd or "").lower()
    if " shell" in low or any(m in low for m in _ADB_DUMP_MARKERS):
        return True
    return False


def should_kill_hung_oneshot(name: str, cmd: str, age_s: float) -> bool:
    if "python" not in (name or "").lower() and "powershell" not in (name or "").lower():
        return False
    if age_s < _ONESHOT_MAX_AGE_S:
        return False
    low = (cmd or "").lower()
    return any(m in low for m in _HUNG_ONESHOT)


def should_kill_orphan_conhost(name: str, parent_alive: bool) -> bool:
    return (name or "").lower() == "conhost.exe" and not parent_alive


def should_kill_adb_conhost(name: str, parent_name: str, age_s: float) -> bool:
    if (name or "").lower() != "conhost.exe":
        return False
    if (parent_name or "").lower() not in {"adb.exe", "adb"}:
        return False
    return age_s >= _ADB_CONHOST_MAX_AGE_S


def _hb(msg: str) -> None:
    try:
        LOG.mkdir(parents=True, exist_ok=True)
        HB.write_text(f"{_utc()} {msg}\n", encoding="utf-8")
    except OSError:
        pass


def _kill(proc: Any, reason: str, fixes: list[str]) -> None:
    try:
        pid = int(proc.pid)
        proc.kill()
        fixes.append(f"{reason} pid={pid}")
    except Exception:
        pass


def sweep_dead_processes() -> list[str]:
    """One pass: dups, hung ADB, flash cmd, leak bash/wsl, orphan/adb conhost."""
    fixes: list[str] = []
    try:
        import psutil
    except ImportError:
        return ["janitor_psutil_missing"]

    now = time.time()
    alive = set()
    try:
        alive = {int(p.pid) for p in psutil.process_iter(["pid"])}
    except Exception:
        alive = set()

    adb_procs: list[Any] = []
    bash_wsl: list[Any] = []

    for proc in psutil.process_iter(["pid", "name", "cmdline", "create_time", "ppid"]):
        try:
            info = proc.info
            name = str(info.get("name") or "")
            cmd = cmdline_of(info)
            age = now - float(info.get("create_time") or now)
            nlow = name.lower()
            ppid = int(info.get("ppid") or 0)
            parent_alive = ppid in alive
            parent_name = ""
            if parent_alive:
                try:
                    parent_name = psutil.Process(ppid).name()
                except (psutil.Error, OSError):
                    parent_alive = False
                    parent_name = ""

            if nlow in {"adb.exe", "adb"}:
                adb_procs.append(proc)
            if nlow in {"bash.exe", "bash", "wsl.exe", "wsl", "wslhost.exe"}:
                bash_wsl.append(proc)

            if should_kill_leak_shell(name, cmd):
                _kill(proc, "kill_leak_shell", fixes)
                continue
            if should_kill_flash_cmd(name, cmd):
                _kill(proc, "kill_flash_cmd", fixes)
                continue
            if should_kill_hung_adb(name, cmd, age):
                _kill(proc, "kill_hung_adb", fixes)
                continue
            if should_kill_hung_oneshot(name, cmd, age):
                _kill(proc, "kill_hung_oneshot", fixes)
                continue
            if should_kill_orphan_conhost(name, parent_alive):
                _kill(proc, "kill_orphan_conhost", fixes)
                continue
            if should_kill_adb_conhost(name, parent_name, age):
                _kill(proc, "kill_adb_conhost", fixes)
                continue
            if nlow == "conhost.exe" and (parent_name or "").lower() in _KEEP_CONHOST_PARENTS:
                continue
        except (psutil.Error, TypeError, ValueError, OSError):
            continue

    if len(adb_procs) > _MAX_ADB:
        for p in adb_procs:
            cmd = ""
            try:
                cmd = " ".join(str(x) for x in (p.cmdline() or []))
            except (psutil.Error, OSError):
                cmd = ""
            if "fork-server" in cmd:
                continue
            _kill(p, "cull_excess_adb", fixes)
        fixes.append(f"cull_excess_adb n={len(adb_procs)}")

    if len(bash_wsl) > _MAX_BASH_WSL:
        for p in bash_wsl:
            _kill(p, "cull_excess_bash_wsl", fixes)
        fixes.append(f"cull_excess_bash_wsl n={len(bash_wsl)}")

    try:
        fixes.extend(cull_duplicates_keep_newest(SINGLETON_HELPERS + ("run_farm_354.py",)))
    except Exception as exc:
        fixes.append(f"dup_cull_err:{exc}")

    _hb(f"fixes={len(fixes)} " + ",".join(fixes[:12]))
    return fixes
