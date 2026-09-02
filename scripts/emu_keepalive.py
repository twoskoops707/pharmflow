#!/usr/bin/env python3
"""Reconnect ADB serials quietly — no console windows."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import automation.no_window  # noqa: E402,F401

LOG = Path(r"C:\CPharm\logs")
ADB = r"C:\CPharm\bundled\adb.exe"
if not Path(ADB).is_file():
    ADB = "adb"
INTERVAL_S = 45.0
_NOWIN = int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))


def _serials() -> list[str]:
    path = LOG / "farm_runtime_overrides.json"
    try:
        ov = json.loads(path.read_text(encoding="utf-8-sig"))
        return [s.strip() for s in str(ov.get("CPHARM_ADB_SERIALS") or "").split(",") if s.strip()]
    except Exception:
        return []


def main() -> int:
    while True:
        for ser in _serials():
            try:
                subprocess.run(
                    [ADB, "connect", ser],
                    capture_output=True,
                    timeout=8,
                    creationflags=_NOWIN,
                )
            except Exception:
                pass
        time.sleep(INTERVAL_S)


if __name__ == "__main__":
    raise SystemExit(main())
