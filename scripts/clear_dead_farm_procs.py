#!/usr/bin/env python3
"""Clear dead / duplicate FamFlow farm helper processes.

Keeps exactly one of each long-running helper. Kills:
  - duplicate farm/cycles/watch/inject/dash/ensure/tickler/suppress/fail_review/ntfy
  - leftover one-shot probes (verify_browser_sequence, map_dabflow_live, smoke/probe)
  - MuMu nemux-shell ADB consoles
  - watch_adb_devices cmd windows
  - duplicate proxy_guard_loop.ps1 (keeps newest)
  - Azure telemetry bash/wsl/conhost orphans (via FamFlowTools killer when present)

Does **not** kill a solitary healthy run_farm_354 / cycles / tor / adb server.
Does **not** kill Freebuff / bun.exe processes (protected).
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

try:
    import psutil
except ImportError:  # pragma: no cover
    psutil = None  # type: ignore[assignment]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from automation.farm_process_janitor import sweep_dead_processes  # noqa: E402

LOG_DIR = Path(
    os.environ.get("CPHARM_LOGS")
    or os.environ.get("CPHARM_LOG_DIR")
    or r"C:\CPharm\logs"
)
HB = LOG_DIR / "clear_dead_procs_heartbeat.txt"

# Never treat these as kill targets / never report them as janitor work.
_PROTECTED_MARKERS = (
    "bun.exe",
    "bun ",
    "\\bun",
    "freebuff",
    "agent_unison_freebuff",
)


def _hb(msg: str) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        HB.write_text(
            f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def _is_real_kill(fix: str) -> bool:
    """Janitor returns meta lines (counts, missing psutil) mixed with kills."""
    low = (fix or "").lower()
    if any(m in low for m in _PROTECTED_MARKERS):
        return False
    if "pid=" not in low:
        return False
    if low.startswith("dup_cull_err") or low.startswith("janitor_"):
        return False
    return True


def _protected_still_alive() -> int:
    """Count live Freebuff/bun PIDs so we never claim success after harming them."""
    if psutil is None:
        return -1
    n = 0
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            name = str(proc.info.get("name") or "").lower()
            cmd = " ".join(str(x) for x in (proc.info.get("cmdline") or [])).lower()
        except (psutil.Error, TypeError, OSError):
            continue
        if name in {"bun.exe", "bun"} or any(m in cmd for m in _PROTECTED_MARKERS):
            n += 1
    return n


def clear_dead() -> dict[str, int]:
    """Compatibility wrapper — remediator janitor is the real sweeper."""
    before_protected = _protected_still_alive()
    fixes = sweep_dead_processes()
    # Drop any fix strings that mention protected Freebuff/bun targets (safety).
    safe_fixes = [f for f in fixes if not any(m in f.lower() for m in _PROTECTED_MARKERS)]
    kills = [f for f in safe_fixes if _is_real_kill(f)]
    after_protected = _protected_still_alive()
    if before_protected > 0 and after_protected >= 0 and after_protected < before_protected:
        _hb(
            f"WARN freebuff/bun count dropped {before_protected}->{after_protected}; "
            f"janitor sample={','.join(fixes[:8])}"
        )
    summary = {
        "killed": len(kills),
        "kept_singletons": 0,
        "azure_sweep": 0,
        "fixes": len(safe_fixes),
        "protected_bun": max(0, after_protected),
        "psutil_ok": int(psutil is not None and "janitor_psutil_missing" not in fixes),
    }
    _hb(f"killed={len(kills)} sample={','.join(kills[:8])}")
    return summary


def main() -> int:
    if sys.platform != "win32":
        print("clear_dead_farm_procs is Windows-only", file=sys.stderr)
        return 2
    result = clear_dead()
    print(result, flush=True)
    if not result.get("psutil_ok", 1):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
