#!/usr/bin/env python3
"""Start a FamFlow helper with no console window (Windows)."""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    if len(sys.argv) < 2:
        print("usage: start_hidden.py <script> [args...]", file=sys.stderr)
        return 2
    script = sys.argv[1]
    args = sys.argv[2:]
    py = sys.executable
    # Prefer console-less interpreter for long-running helpers.
    if sys.platform == "win32":
        cand = Path(py).with_name("pythonw.exe")
        if cand.is_file():
            py = str(cand)
    cmd = [py, "-u", str(ROOT / script), *args]
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT) + os.pathsep + env.get("PYTHONPATH", "")
    creation = 0
    kwargs: dict = {}
    if sys.platform == "win32":
        creation = int(getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
        si = subprocess.STARTUPINFO()
        si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        si.wShowWindow = 0
        kwargs["startupinfo"] = si
        kwargs["creationflags"] = creation
    subprocess.Popen(
        cmd,
        cwd=str(ROOT),
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        **kwargs,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
