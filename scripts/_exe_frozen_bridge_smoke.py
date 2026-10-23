"""Invoke PharmFlow.next.exe --deck-self-test (frozen bridge honesty)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

NEXT = Path(r"C:\PharmFlow\PharmFlow.next.exe")


def main() -> int:
    if not NEXT.is_file():
        print("FAIL missing", NEXT)
        return 1
    proc = subprocess.run(
        [str(NEXT), "--deck-self-test"],
        capture_output=True,
        text=True,
        timeout=180,
        errors="replace",
    )
    print(proc.stdout or "")
    if proc.stderr:
        print(proc.stderr, file=sys.stderr)
    return int(proc.returncode or 0)


if __name__ == "__main__":
    raise SystemExit(main())
