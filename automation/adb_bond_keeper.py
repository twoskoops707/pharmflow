"""Always-on ADB bond keeper (supervisor lane).

Holds / repairs / starts the adb bond between the EXE and its emulators.

Why this exists
---------------
Emulators registered via ``adb connect`` silently fall off the adb server
when the server restarts or a TCP registration times out — even though the
guest Android is healthy. The farm's per-cycle logic only heals a phone it
still knows about, so a dropped phone could sit off adb forever. This lane
runs independently, every few seconds:

  * START   — ``adb connect`` every known serial that is missing from
              ``adb devices``.
  * REPAIR  — if ``adb devices`` comes back empty while known serials exist,
              start-server (never kill-server) and reconnect the whole fleet.
  * HOLD    — otherwise report the bond is healthy.

It never touches VMs, never raises, and is safe to run alongside the farm
lane (adb connect is idempotent).
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import automation.no_window  # noqa: E402,F401  — hide adb consoles under pythonw

from automation.farm_phone_discover import (  # noqa: E402
    ADB,
    _adb_online_serials,
    _known_candidate_serials,
)
from automation.win_subprocess import hidden_run_kwargs  # noqa: E402

LOG = Path(os.environ.get("PHARMFLOW_LOGS") or r"C:\PharmFlow\logs")
INTERVAL_S = float(os.environ.get("PHARMFLOW_ADB_KEEPER_INTERVAL_S", "8") or "8")
REPAIR_AFTER_CONSECUTIVE = 2


def _log(line: str) -> None:
    ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
    msg = f"[{ts}] {line}"
    print(msg, flush=True)
    try:
        LOG.mkdir(parents=True, exist_ok=True)
        with (LOG / "adb_bond_keeper.log").open("a", encoding="utf-8") as fh:
            fh.write(msg + "\n")
    except OSError:
        pass


def _run_adb(args: list[str], timeout: float) -> str:
    try:
        p = subprocess.run(
            [ADB] + args,
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
            **hidden_run_kwargs(),
        )
        return (p.stdout or "") + (p.stderr or "")
    except Exception as exc:  # noqa: BLE001 — keeper is best-effort
        return f"ERR {exc}"


def _repair_server() -> set[str]:
    """Dead server: start it, then reconnect every known serial.

    ``adb kill-server`` drops every live phone. An empty devices list is not
    proof the server is wedged. start-server brings a dead daemon up and
    leaves an already-running daemon alone.
    """
    _log("BOND REPAIR: adb listing empty — start-server + reconnect every known serial (no kill-server)")
    _run_adb(["start-server"], timeout=20.0)
    time.sleep(1.0)
    return _reconnect_missing(set())


def _reconnect_missing(online: set[str]) -> set[str]:
    missing = [s for s in _known_candidate_serials() if s and s not in online]
    for serial in missing:
        out = _run_adb(["connect", serial], timeout=4.0)
        if "connected" in out.lower() or "already connected" in out.lower():
            _log(f"BOND START: {serial} reattached")
        else:
            _log(f"BOND START: {serial} connect failed ({out.strip()[:60]})")
    return _adb_online_serials(timeout=8.0)


def _main() -> None:
    _log(f"adb bond keeper up (interval={INTERVAL_S}s, adb={ADB})")
    bad = 0
    last_hold = 0.0
    while True:
        started = time.monotonic()
        try:
            online = _adb_online_serials(timeout=8.0)
            known = _known_candidate_serials()
            if known and not online:
                bad += 1
            else:
                bad = 0
            if bad >= REPAIR_AFTER_CONSECUTIVE and known:
                online = _repair_server()
                bad = 0
            else:
                online = _reconnect_missing(online)
            if time.monotonic() - last_hold >= 60.0:
                _log(
                    f"BOND HOLD: {len(online)}/{len(known) or '?'} known serials on adb"
                )
                last_hold = time.monotonic()
        except Exception as exc:  # noqa: BLE001 — never die
            _log(f"BOND ERROR: {exc}")
        elapsed = time.monotonic() - started
        time.sleep(max(0.5, INTERVAL_S - elapsed))


if __name__ == "__main__":
    _main()