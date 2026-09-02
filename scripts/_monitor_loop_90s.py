#!/usr/bin/env python3
"""Background monitor — calls farm_watchdog_investigate every 60s."""
from __future__ import annotations

import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PY = Path(r"C:\Users\jsmil\AppData\Local\Python\pythoncore-3.14-64\python.exe")
LOG = Path(r"C:\CPharm\logs\cursor_monitor_loop.log")
INTERVAL = 60
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)

sys.path.insert(0, str(ROOT))


def _log(msg: str) -> None:
    line = f"{datetime.now(timezone.utc).isoformat()} {msg}"
    print(line, flush=True)
    try:
        LOG.parent.mkdir(parents=True, exist_ok=True)
        with LOG.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass


def main() -> int:
    from automation.farm_watchdog_investigate import format_report, investigate

    _log("armed interval=60s evidence_investigate")
    while True:
        try:
            report = investigate(apply=True)
            _log(format_report(report).replace("\n", " | "))
        except Exception as exc:
            _log(f"tick_err:{exc}")
        time.sleep(INTERVAL)


if __name__ == "__main__":
    raise SystemExit(main())
