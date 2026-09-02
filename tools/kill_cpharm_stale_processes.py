#!/usr/bin/env python3
"""
Close stale MuMu, adb, and CPharm processes (same logic as CPharmMuMuSetup startup).

Operators normally do not need this — CPharmMuMuSetup.exe runs it automatically.
Use when debugging stuck adb/MuMu/CPharm from a dev clone:

    python tools/kill_cpharm_stale_processes.py
    python tools/kill_cpharm_stale_processes.py --force-mumu
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_WIZ = _ROOT / "wizard"
if str(_WIZ) not in sys.path:
    sys.path.insert(0, str(_WIZ))

import setup_startup_cleanup as cleanup  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Close stale MuMu / adb / CPharm processes.")
    parser.add_argument(
        "--force-mumu",
        action="store_true",
        help="Also close MuMu even when setup was already completed once.",
    )
    parser.add_argument(
        "--first-time",
        action="store_true",
        help="Treat as first setup (close MuMu). Default: auto-detect from desktop_prefs.",
    )
    args = parser.parse_args()

    if args.force_mumu:
        os.environ["CPHARM_FORCE_STARTUP_CLEANUP"] = "1"

    first_time: bool | None = True if args.first_time else None
    if args.force_mumu:
        first_time = True

    def log(msg: str) -> None:
        print(msg)

    summary = cleanup.run_startup_cleanup(first_time=first_time, log=log)
    print("")
    print(cleanup.format_cleanup_log_line(summary))
    if summary.get("failed"):
        for line in summary["failed"]:
            print(f"  failed: {line}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
