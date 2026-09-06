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

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore[assignment]

# Never kill Freebuff / Codebuff agent hosts (bun desktop + related).
_FREEBUFF_MARKERS = (
    "freebuff",
    "codebuff",
    "@codebuff/freebuff-desktop",
    "codebufffreebuff-desktop",
    "codebuff/freebuff",
)


def _freebuff_protected_pids() -> set[int]:
    """PIDs for Freebuff bun / @codebuff freebuff-desktop — must never be killed."""
    if psutil is None:
        return set()
    protected: set[int] = set()
    try:
        for proc in psutil.process_iter(["pid", "name", "cmdline", "exe"]):
            try:
                pid = int(proc.info.get("pid") or 0)
                if pid <= 0:
                    continue
                name = (proc.info.get("name") or "").lower()
                exe = (proc.info.get("exe") or "").lower()
                cmd_parts = proc.info.get("cmdline") or []
                cmd = " ".join(str(x) for x in cmd_parts).lower()
                blob = f"{name} {exe} {cmd}"
                is_bun = name in ("bun.exe", "bun") or name.endswith("bun.exe") or "/bun" in exe.replace("\\", "/")
                if any(m in blob for m in _FREEBUFF_MARKERS) or (
                    is_bun and ("codebuff" in blob or "freebuff" in blob)
                ):
                    protected.add(pid)
            except (psutil.Error, TypeError, ValueError):
                continue
    except (psutil.Error, OSError):
        return protected
    return protected


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

    # Expand protected set so Freebuff bun / freebuff-desktop survive cleanup.
    freebuff_pids = _freebuff_protected_pids()
    _orig_protected = cleanup._protected_pids

    def _protected_with_freebuff(my_pid: int) -> set[int]:
        return _orig_protected(my_pid) | freebuff_pids

    cleanup._protected_pids = _protected_with_freebuff  # type: ignore[assignment]
    try:
        summary = cleanup.run_startup_cleanup(first_time=first_time, log=log)
    finally:
        cleanup._protected_pids = _orig_protected  # type: ignore[assignment]

    if freebuff_pids:
        log(f"  protected Freebuff/codebuff pids: {sorted(freebuff_pids)}")

    print("")
    print(cleanup.format_cleanup_log_line(summary))
    if summary.get("failed"):
        for line in summary["failed"]:
            print(f"  failed: {line}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
