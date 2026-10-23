#!/usr/bin/env python3
"""Nudge the mouse + hold wake locks so the farm host stays active.

Prevents screensaver / display sleep / system idle sleep while the farm runs.
Runs forever; start via scripts/start_hidden.py (no console).
"""
from __future__ import annotations

import ctypes
import os
import sys
import time
from datetime import datetime
from pathlib import Path

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002

HEARTBEAT = Path(os.environ.get("PHARMFLOW_MOUSE_TICKLE_HB", r"C:\PharmFlow\logs\mouse_tickler_heartbeat.txt"))
INTERVAL_S = float(os.environ.get("PHARMFLOW_MOUSE_TICKLE_INTERVAL", "45"))
DELTA = int(os.environ.get("PHARMFLOW_MOUSE_TICKLE_DELTA", "1"))


class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


def _hold_awake() -> None:
    ctypes.windll.kernel32.SetThreadExecutionState(
        ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
    )


def _nudge_mouse() -> tuple[int, int]:
    pt = POINT()
    ctypes.windll.user32.GetCursorPos(ctypes.byref(pt))
    x, y = int(pt.x), int(pt.y)
    ctypes.windll.user32.SetCursorPos(x + DELTA, y + DELTA)
    time.sleep(0.05)
    ctypes.windll.user32.SetCursorPos(x, y)
    return x, y


def _write_hb(n: int, x: int, y: int) -> None:
    try:
        HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
        HEARTBEAT.write_text(
            f"{datetime.now():%Y-%m-%d %H:%M:%S} ticks={n} interval={INTERVAL_S:g} pos={x},{y}\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def main() -> int:
    if sys.platform != "win32":
        print("mouse_tickler.py is Windows-only", file=sys.stderr)
        return 2
    n = 0
    while True:
        _hold_awake()
        try:
            x, y = _nudge_mouse()
        except Exception:
            x = y = -1
        n += 1
        _write_hb(n, x, y)
        time.sleep(max(5.0, INTERVAL_S))


if __name__ == "__main__":
    raise SystemExit(main())
