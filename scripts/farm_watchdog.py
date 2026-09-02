#!/usr/bin/env python3
"""farm_watchdog.py — evidence-based farm monitor (no guesses).

Problems / errors / flat $ → read logs + JSON → fix. Never kill MuMu emulators.
"""
from __future__ import annotations

import os
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from automation.farm_watchdog_investigate import format_report, investigate

PID_FILE = Path(r"C:\CPharm\logs\farm_watchdog.pid")
LOG_FILE = Path(r"C:\CPharm\logs\farm_watchdog.log")
MONITOR_FILE = Path(r"C:\CPharm\logs\FARM_MONITOR_NOW.txt")
INTERVAL_S = float(os.environ.get("CPHARM_FARM_WATCHDOG_INTERVAL_S", "60"))


def _log(msg: str) -> None:
    line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    try:
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
    except OSError:
        pass
    print(line, flush=True)


def main() -> int:
    if PID_FILE.exists():
        try:
            old_pid = int(PID_FILE.read_text(encoding="utf-8").strip())
            os.kill(old_pid, 0)
            print("Another farm_watchdog is running. Exiting.")
            return 0
        except (ValueError, OSError, ProcessLookupError):
            PID_FILE.unlink(missing_ok=True)

    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    _log(f"farm_watchdog started pid={os.getpid()} interval={INTERVAL_S}s evidence_only=1")

    cycle = 0
    try:
        while True:
            cycle += 1
            report = investigate(apply=True)
            text = format_report(report)
            MONITOR_FILE.write_text(text + f"\n\ncycle={cycle}\n", encoding="utf-8")
            if report.get("problem_count"):
                _log(text.replace("\n", " | "))
            else:
                m = (report.get("evidence") or {}).get("mantis") or {}
                log_ev = (report.get("evidence") or {}).get("log") or {}
                _log(
                    f"OK cycle={cycle} ${m.get('payout_usd')} clk={m.get('clicks')} "
                    f"p3_ok={log_ev.get('p3_ok')} adb={(report.get('evidence') or {}).get('adb_live_n')}"
                )
            time.sleep(max(15.0, INTERVAL_S))
    except KeyboardInterrupt:
        _log("farm_watchdog stopped")
    finally:
        PID_FILE.unlink(missing_ok=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
