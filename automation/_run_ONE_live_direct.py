#!/usr/bin/env python3
"""Run dabflow__demo__ONE.json on MuMu via execute_steps - no wizard GUI."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from pathlib import Path

PHARMFLOW = Path(r"C:\Users\jsmil\PharmFlow")
ROOT = Path(__file__).resolve().parent.parent
SEQ = PHARMFLOW / "sequences/900x1600/no-ad/dabflow__demo__ONE.json"
OUT = PHARMFLOW / "FULL_FLOW_LIVE.txt"

sys.path.insert(0, str(ROOT / "wizard"))
sys.path.insert(0, str(ROOT / "automation"))
os.environ["PHARMFLOW_HUMAN_VARIATION"] = "0"
os.environ["PHARMFLOW_SKIP_TOR_WAIT"] = "1"
os.environ.setdefault("PHARMFLOW_USE_SHELL_WM_FOCUS_CHEAT", "1")

import tor_manager
from adb_paths import adb_executable
from sequence_normalize import normalize_automation_steps, unwrap_sequence_document
from setup_wizard import execute_steps

adb = adb_executable()


def kill_other_pharmflow_python() -> None:
    """Stop stray PharmFlow automation processes so ADB/Tor are not contended."""
    if os.name != "nt":
        return
    me = os.getpid()
    ps = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            (
                "Get-CimInstance Win32_Process -Filter \"Name='python.exe' OR Name='pythonw.exe'\" "
                "| Where-Object { $_.ProcessId -ne "
                + str(me)
                + " -and $_.CommandLine -match 'pharmflow|PharmFlow|setup_wizard|dabflow' } "
                "| ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }"
            ),
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )
    if ps.returncode != 0 and ps.stderr:
        print(ps.stderr.strip(), flush=True)


def repair_proxy(serial: str) -> None:
    idx = tor_manager.phone_idx_from_adb_serial(serial)
    port = tor_manager.http_proxy_port_for_phone_idx(idx)
    print(f"[pharmflow] proxy repair serial={serial} phone_idx={idx} port={port}", flush=True)
    tor_manager.repair_adb_reverse_for_proxy(serial, idx)
    tor_manager.ensure_tor_and_proxy_for_phone(serial, idx)


def pick_serial() -> str:
    out = subprocess.run([adb, "devices"], capture_output=True, text=True, timeout=30).stdout or ""
    devices = [ln.split("\t", 1)[0] for ln in out.splitlines() if ln.strip().endswith("\tdevice")]
    for pref in ("10.0.2.69:5555", "10.0.2.179:5555"):
        if pref in devices:
            return pref
    return devices[0] if devices else ""


def main() -> int:
    t0 = time.monotonic()
    started_at = datetime.now(timezone.utc).isoformat()
    overall = "FAIL"
    kill_other_pharmflow_python()
    serial = pick_serial()

    if not serial:
        OUT.write_text(
            f"result=FAIL\nreason=no_adb_device\nstarted_at={started_at}\n"
            f"finished_at={datetime.now(timezone.utc).isoformat()}\nwall_sec=0\n",
            encoding="utf-8",
        )
        print("NO ADB DEVICE")
        return 1

    if not SEQ.is_file():
        OUT.write_text(
            f"result=FAIL\nreason=sequence_missing\ndevice={serial}\nstarted_at={started_at}\n"
            f"finished_at={datetime.now(timezone.utc).isoformat()}\nwall_sec=0\n",
            encoding="utf-8",
        )
        return 1

    print(f"adb devices:\n{subprocess.run([adb, 'devices'], capture_output=True, text=True, timeout=30).stdout or ''}", flush=True)
    repair_proxy(serial)

    raw = json.loads(SEQ.read_text(encoding="utf-8-sig"))
    steps, _ = unwrap_sequence_document(raw)
    steps = normalize_automation_steps(steps)
    timer_wait = next((float(s["seconds"]) for s in steps if s.get("checkpoint") == "timer_complete"), 0.0)

    fail_reason = ""
    try:
        for i, step in enumerate(steps):
            t = step.get("type", "")
            cp = step.get("checkpoint") or ""
            el = time.monotonic() - t0
            print(f"{el:7.1f}s step {i + 1}/{len(steps)} {t} {cp}", flush=True)
            if t == "wait" and cp == "timer_complete":
                print(f"  >>> TIMER WAIT {timer_wait}s START", flush=True)
            if execute_steps([step], serial) is False:
                raise RuntimeError(f"step {i + 1} {t} did not land")
            if t == "wait" and cp == "timer_complete":
                print(f"  >>> TIMER WAIT END wall={time.monotonic() - t0 - el:.1f}s", flush=True)
        overall = "PASS"
    except Exception as exc:
        overall = "FAIL"
        fail_reason = f"{type(exc).__name__}: {exc}"
        print(traceback.format_exc(), flush=True)

    finished_at = datetime.now(timezone.utc).isoformat()
    elapsed = round(time.monotonic() - t0, 2)
    close_n = sum(1 for s in steps if s.get("type") == "close_app")
    open_n = sum(1 for s in steps if s.get("type") == "open_url")
    OUT.write_text(
        "\n".join(
            [
                f"result={overall}",
                f"device={serial}",
                f"started_at={started_at}",
                f"finished_at={finished_at}",
                f"wall_sec={elapsed}",
                f"steps={len(steps)}",
                f"open_url={open_n}",
                f"close_app={close_n}",
                f"timer_wait_sec={timer_wait}",
                *( [f"fail_reason={fail_reason}"] if fail_reason else [] ),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"DONE {overall} elapsed={elapsed}s steps={len(steps)} -> {OUT}", flush=True)
    return 0 if overall == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
