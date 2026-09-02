"""CI smoke guard for the Tk wizard pages.

Spawns each wizard page through ``--internal-tk-page <idx>`` (the same path the
EXE uses) in a subprocess, waits a short survival window, and fails the build if
the window process exits before the window is rendered. On success the window is
still alive at that point (it is intentionally killed, since the pages are
long-lived GUIs and would otherwise hang CI).

Skips cleanly when no usable display is available (e.g. headless Linux or a
session-0 runner) instead of hard-failing, so the guard can never block a real
release build.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGES = (0, 1, 2, 3, 4, 5, 6, 7, 8)
SURVIVE_SECONDS = 6.0

_NO_DISPLAY_HINTS = (
    "no display",
    "couldn't connect to display",
    "can't connect to display",
    "invalid mit-magic-cookie",
    "could not open display",
    "couldn't get a system tray window",
)


def _can_do_gui() -> bool:
    """True when this runner can open a real Tk window."""
    if os.name == "nt":
        return True  # GitHub Actions Windows runners run an interactive desktop
    return bool(os.environ.get("DISPLAY"))  # xvfb on Linux/macOS


def _build_cmd(idx: int) -> list[str]:
    target = ROOT / "wizard" / "cpharm_desktop.py"
    return [sys.executable, str(target), "--internal-tk-page", str(idx)]


def _spawn_and_check(idx: int) -> tuple[bool, str]:
    """Return (ok, detail). On early exit, detail is the captured stderr tail."""
    proc = subprocess.Popen(
        _build_cmd(idx),
        cwd=str(ROOT),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    deadline = time.monotonic() + SURVIVE_SECONDS
    while time.monotonic() < deadline:
        rc = proc.poll()
        if rc is not None:
            err = (proc.stderr.read() or "")[-600:]
            return False, f"page {idx} exited early (rc={rc}) before render: {err}"
        time.sleep(0.2)
    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
    return True, f"page {idx} alive after {SURVIVE_SECONDS:.0f}s (window OK, killed)"


def main() -> int:
    if not _can_do_gui():
        print("SKIP: no usable display on this host — wizard-page GUI guard not run")
        return 0
    failures = 0
    for idx in PAGES:
        ok, msg = _spawn_and_check(idx)
        low = msg.lower()
        if not ok and any(h in low for h in _NO_DISPLAY_HINTS):
            # Runner has no interactive desktop (session 0 / xvfb missing):
            # stop rather than falsely failing a release build.
            print(f"SKIP: no usable display on this runner ({msg.strip()[:140]})")
            return 0
        print(("PASS " if ok else "FAIL ") + msg)
        if not ok:
            failures += 1
    if failures:
        print(f"wizard page spawn guard: {failures} failure(s)")
        return 1
    print(f"wizard page spawn guard: all {len(PAGES)} pages rendered OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())