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
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from automation.farm_process_janitor import sweep_dead_processes  # noqa: E402

LOG_DIR = Path(os.environ.get("CPHARM_LOG_DIR", r"C:\CPharm\logs"))
HB = LOG_DIR / "clear_dead_procs_heartbeat.txt"


def _hb(msg: str) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        HB.write_text(
            f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}\n",
            encoding="utf-8",
        )
    except OSError:
        pass


def clear_dead() -> dict[str, int]:
    """Compatibility wrapper — remediator janitor is the real sweeper."""
    fixes = sweep_dead_processes()
    summary = {"killed": len(fixes), "kept_singletons": 0, "azure_sweep": 0, "fixes": len(fixes)}
    _hb(f"killed={len(fixes)} sample={','.join(fixes[:8])}")
    return summary


def main() -> int:
    if sys.platform != "win32":
        print("clear_dead_farm_procs is Windows-only", file=sys.stderr)
        return 2
    result = clear_dead()
    print(result, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
