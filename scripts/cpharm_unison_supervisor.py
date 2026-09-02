#!/usr/bin/env python3
"""CPharm unison supervisor — four lanes, one stack.

Lane 1: run_farm_354.py              — sequences / Path3 / money worker
Lane 2: cpharm_stealth_guard.py      — tor, inject, ADB, GPU, dash
Lane 3: farm_watchdog.py             — evidence monitor + FARM_MONITOR_NOW
Lane 4: agent_unison_freebuff_loop.py — SSP paying, flat-$, path3 OK (FREEBUFF)

CPharm.exe Start Farm spawns THIS script (not ensure_farm / remediator soup).
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = Path(r"C:\CPharm\logs")
PID_FILE = LOG / "cpharm_unison_supervisor.pid"
STATE_FILE = LOG / "cpharm_unison_state.json"
sys.path.insert(0, str(ROOT))

import automation.no_window  # noqa: F401

from automation.cpharm_farm_config import (  # noqa: E402
    apply_farm_env,
    purge_legacy_override_files,
    reset_runtime,
)

from automation.cpharm_unison_dedupe import dedupe_keep_newest, pids_for_script  # noqa: E402

LANES: tuple[tuple[str, str], ...] = (
    ("farm", "run_farm_354.py"),
    ("stealth", "cpharm_stealth_guard.py"),
    ("watchdog", "farm_watchdog.py"),
    ("freebuff", "agent_unison_freebuff_loop.py"),
)
INTERVAL_S = float(os.environ.get("CPHARM_UNISON_INTERVAL_S", "45"))
FLAGS = 0x08000000  # CREATE_NO_WINDOW


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _pyw() -> str:
    pyw = sys.executable.replace("python.exe", "pythonw.exe")
    return pyw if Path(pyw).is_file() else sys.executable


def _lane_pids() -> dict[str, list[int]]:
    out: dict[str, list[int]] = {name: [] for name, _ in LANES}
    try:
        import psutil
    except ImportError:
        return out
    needles = {name: script for name, script in LANES}
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmd = " ".join(str(x) for x in (proc.info.get("cmdline") or []))
            pid = int(proc.info.get("pid") or 0)
        except (TypeError, ValueError, psutil.Error):
            continue
        for name, script in needles.items():
            if script in cmd and "-c" not in cmd:
                out[name].append(pid)
    return out


def _spawn_lane(name: str, script: str) -> int | None:
    path = ROOT / "scripts" / script
    if not path.is_file():
        return None
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    env["CPHARM_EXE_OWNED_FARM"] = "1"
    apply_farm_env(env)
    proc = subprocess.Popen(
        [_pyw(), "-u", str(path)],
        cwd=str(ROOT),
        env=env,
        creationflags=FLAGS,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=True,
    )
    return proc.pid


def _ensure_lanes() -> list[str]:
    notes: list[str] = []
    for _name, script in LANES:
        extras = dedupe_keep_newest(script)
        for pid in extras:
            notes.append(f"dedupe_{script}:{pid}")
    pids = _lane_pids()
    for name, script in LANES:
        if pids.get(name):
            continue
        pid = _spawn_lane(name, script)
        if pid:
            notes.append(f"spawn_{name}={pid}")
        else:
            notes.append(f"missing_{name}")
    return notes


def _ensure_freebuff_queue() -> list[str]:
    """Refresh FREEBUFF task queue on AGENT_UNISON.json (idempotent)."""
    notes: list[str] = []
    assign = ROOT / "scripts" / "agent_unison_assign_freebuff.py"
    if not assign.is_file():
        return notes
    try:
        env = os.environ.copy()
        env["PYTHONPATH"] = str(ROOT)
        proc = subprocess.run(
            [_pyw(), "-u", str(assign)],
            cwd=str(ROOT),
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            creationflags=FLAGS,
        )
        if proc.returncode == 0:
            notes.append("freebuff_queue_assigned")
        else:
            notes.append(f"freebuff_assign_rc={proc.returncode}")
    except (OSError, subprocess.TimeoutExpired) as exc:
        notes.append(f"freebuff_assign_err:{exc}")
    return notes


def _kill_legacy_stack() -> list[str]:
    """Retire competing babysit scripts — unison owns the stack now."""
    killed: list[str] = []
    retire = (
        "ensure_farm_24x7.py",
        "keep_farm_alive.py",
        "farm_remediate_loop.py",
        # FREEBUFF lane 4 owns agent_unison_freebuff_loop; do not kill it here.
        # watch_bottom_ads / ssp_paying_hunter may be spawned by money remediate.
    )
    try:
        import psutil

        for proc in psutil.process_iter(["pid", "cmdline"]):
            cmd = " ".join(str(x) for x in (proc.info.get("cmdline") or []))
            for needle in retire:
                if needle in cmd:
                    try:
                        proc.terminate()
                        killed.append(f"{needle}:{proc.info['pid']}")
                    except (psutil.Error, TypeError):
                        pass
    except ImportError:
        pass
    return killed


def main() -> int:
    LOG.mkdir(parents=True, exist_ok=True)
    if PID_FILE.is_file():
        try:
            old = int(PID_FILE.read_text(encoding="utf-8").strip())
            os.kill(old, 0)
            print("cpharm_unison_supervisor already running", flush=True)
            return 0
        except (OSError, ValueError, ProcessLookupError):
            PID_FILE.unlink(missing_ok=True)
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    reset_runtime(note="unison_start")
    removed = purge_legacy_override_files()
    apply_farm_env()
    boot_notes = _ensure_freebuff_queue()
    print(
        f"cpharm_unison_supervisor pid={os.getpid()} "
        f"purged={removed} lanes={[n for n, _ in LANES]} "
        f"{' '.join(boot_notes)}",
        flush=True,
    )
    try:
        while True:
            notes = _kill_legacy_stack() + _ensure_lanes()
            if notes:
                STATE_FILE.write_text(
                    __import__("json").dumps(
                        {"ts": _utc(), "notes": notes, "pids": _lane_pids()},
                        indent=2,
                    )
                    + "\n",
                    encoding="utf-8",
                )
                print(f"{_utc()} {' '.join(notes[:10])}", flush=True)
            time.sleep(max(20.0, INTERVAL_S))
    except KeyboardInterrupt:
        pass
    finally:
        PID_FILE.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
