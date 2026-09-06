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

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore[assignment]

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


def _pid_is_this_watchdog(pid: int) -> bool:
    """True if *pid* is still this watchdog (avoids recycled-PID false positive).

    Without psutil: if the PID is alive, refuse a second instance (safer than
    spawning duplicates). With psutil: require farm_watchdog.py in cmdline.
    """
    if pid <= 0:
        return False
    if psutil is None:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False
    try:
        proc = psutil.Process(pid)
        if not proc.is_running():
            return False
        cmd = " ".join(str(x) for x in (proc.cmdline() or []))
        return "farm_watchdog.py" in cmd and "-c" not in cmd
    except Exception:
        return False


def main() -> int:
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    if PID_FILE.exists():
        try:
            old_pid = int(PID_FILE.read_text(encoding="utf-8").strip())
        except (ValueError, OSError):
            old_pid = 0
            try:
                PID_FILE.unlink(missing_ok=True)
            except OSError:
                pass
        else:
            if _pid_is_this_watchdog(old_pid):
                print("Another farm_watchdog is running. Exiting.", flush=True)
                return 0
            try:
                PID_FILE.unlink(missing_ok=True)
            except OSError:
                pass

    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")
    _log(f"farm_watchdog started pid={os.getpid()} interval={INTERVAL_S}s evidence_only=1")

    cycle = 0
    try:
        while True:
            cycle += 1
            try:
                report = investigate(apply=True)
                text = format_report(report)
            except Exception as exc:
                # Uncaught investigate() used to kill the process; supervisor
                # then respawned → crash/respawn loop and false-positive heat.
                _log(f"investigate soft-fail cycle={cycle}: {exc}")
                try:
                    MONITOR_FILE.write_text(
                        f"watchdog_error\ncycle={cycle}\nerror={exc}\n",
                        encoding="utf-8",
                    )
                except OSError:
                    pass
                time.sleep(max(15.0, INTERVAL_S))
                continue
            try:
                MONITOR_FILE.write_text(text + f"\n\ncycle={cycle}\n", encoding="utf-8")
            except OSError as exc:
                _log(f"monitor write failed: {exc}")
            if not isinstance(report, dict):
                _log(f"investigate non-dict report cycle={cycle}: {type(report).__name__}")
                time.sleep(max(15.0, INTERVAL_S))
                continue
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
        try:
            if PID_FILE.exists() and PID_FILE.read_text(encoding="utf-8").strip() == str(
                os.getpid()
            ):
                PID_FILE.unlink(missing_ok=True)
        except OSError:
            try:
                PID_FILE.unlink(missing_ok=True)
            except OSError:
                pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
