#!/usr/bin/env python3
"""Pause farm until a wall time. Keeps operator dash (:8091) running.

  py -u scripts/farm_pause_until.py --midnight
  py -u scripts/farm_pause_until.py --until "2026-08-14T00:00:00-07:00"
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

LOG = Path(r"C:\PharmFlow\logs")

# Farm workers to stop; dash + midnight watch stay up.
_KILL_NEEDLES = (
    "run_farm_354.py",
    "run_farm_cycles.py",
    "farm_remediate_loop.py",
    "keep_farm_alive.py",
    "watch_bottom_ads.py",
    "run_mantis_inject_proxies.py",
    "farm_fail_review.py",
    "mantis_autopilot.py",
    "farm_hourly_ntfy.py",
    "ntfy_farm_responder.py",
    "ntfy_agent_wake.py",
)


def _kill_farm_workers() -> list[int]:
    killed: list[int] = []
    try:
        import psutil
    except ImportError:
        return killed
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmd = " ".join(proc.info.get("cmdline") or [])
            if any(n in cmd for n in _KILL_NEEDLES):
                proc.kill()
                killed.append(int(proc.info["pid"]))
        except (psutil.Error, OSError, TypeError, ValueError):
            continue
    return killed


def _write_honest_paused(until: str) -> None:
    text = (
        f"FARM PAUSED until {until}\n"
        f"DASH stays up http://127.0.0.1:8091/\n"
        f"Midnight watch will restart farm with saved snapshot.\n"
    )
    try:
        (LOG / "FARM_HONEST_NOW.txt").write_text(text, encoding="utf-8")
    except OSError:
        pass


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--midnight", action="store_true", help="Pause until next local midnight")
    ap.add_argument("--until", type=str, default="", help="ISO datetime to resume")
    ap.add_argument("--tz", type=str, default="America/Los_Angeles")
    args = ap.parse_args()

    from automation.farm_pause import capture_snapshot, pause_until, pause_until_local_midnight

    if args.midnight:
        payload = pause_until_local_midnight(args.tz)
    elif args.until:
        when = datetime.fromisoformat(args.until.replace("Z", "+00:00"))
        payload = pause_until(when, reason=f"paused until {args.until}")
    else:
        payload = pause_until_local_midnight(args.tz)

    snap = capture_snapshot(note="pre-pause snapshot")
    killed = _kill_farm_workers()
    _write_honest_paused(str(payload.get("until")))

    # Start midnight/resume watcher (single instance).
    pyw = sys.executable.replace("python.exe", "pythonw.exe")
    if not Path(pyw).is_file():
        pyw = sys.executable
    watch = ROOT / "scripts" / "farm_midnight_watch.py"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT)
    subprocess.Popen(
        [pyw, "-u", str(watch)],
        cwd=str(ROOT),
        env=env,
        creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0) or 0x08000000,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    time.sleep(1.0)

    out = {
        "pause": payload,
        "killed_pids": killed,
        "phones_in_snapshot": len(snap.get("phones") or []),
        "watch_script": str(watch),
    }
    (LOG / "_farm_pause_last.json").write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(out, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
