#!/usr/bin/env python3
"""Cursor agent ↔ FREEBUFF coordination — ntfy + shared handoff. NO emulator kills."""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = Path(r"C:\PharmFlow\logs")
sys.path.insert(0, str(ROOT))

from automation.adb_wrapper import AdbWrapper
from automation.browse_proxy import _read_guest_proxy, pin_guest_proxy
from automation.farm_checkin import format_checkin, gather_checkin, publish_ntfy
from automation.farm_visit_caps import write_runtime_overrides
from automation.mantis_inject_proxy import ensure_inject_for_phone, verify_reverse_tunnel

HANDOFF = LOG / "AGENT_COORD_CURSOR.json"
COORD_FLAG = LOG / "AGENT_COORD_FREEBUFF.flag"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fix_serial_map() -> dict[str, str]:
    """Remove stale tablet duplicate; keep live phones only."""
    lock_path = LOG / "ADB_SERIAL_MAP.lock.json"
    lock: dict = {}
    if lock_path.is_file():
        lock = json.loads(lock_path.read_text(encoding="utf-8-sig"))
    phones: dict[str, str] = dict(lock.get("phones") or {})
    tablet: dict[str, str] = dict(lock.get("tablet") or {})
    # vm4 lives in phones — drop ghost tablet entry pointing at offline IP
    if "vm4.gmadoa" in phones:
        tablet.pop("vm4.gmadoa", None)
    elif "vm4.gmadoa" in tablet:
        phones["vm4.gmadoa"] = tablet.pop("vm4.gmadoa")
    inject = {p: 8218 + int(p.split(".")[0][2:]) for p in phones}
    lock = {
        "phones": phones,
        "tablet": tablet,
        "inject": inject,
        "note": "cursor+freebuff coord no_emulator_kill",
        "updated": _utc(),
        "locked_at": _utc(),
    }
    lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    return phones


def _gentle_repin(phones: dict[str, str]) -> list[str]:
    adb = AdbWrapper()
    notes: list[str] = []
    for name, ser in sorted(phones.items(), key=lambda x: int(x[0].split(".")[0][2:])):
        idx = int(name.split(".")[0][2:])
        port = 8218 + idx
        try:
            adb.reverse(str(port), str(port), serial=ser)
            ensure_inject_for_phone(adb, ser, idx, install_ca=False)
            pin_guest_proxy(adb, ser, idx)
            ok = verify_reverse_tunnel(adb, ser, port)
            proxy = _read_guest_proxy(adb, ser)
            notes.append(f"{name} reverse={ok} proxy={proxy}")
        except Exception as exc:
            notes.append(f"{name} FAIL {exc}")
    return notes


def main() -> int:
    LOG.mkdir(parents=True, exist_ok=True)

    write_runtime_overrides(
        {
            "PHARMFLOW_TOR_PATH": r"C:\PharmFlow\bundled\tor.exe",
            "PHARMFLOW_FARM_STOP": "0",
        }
    )

    phones = _fix_serial_map()
    repin = _gentle_repin(phones)

    # Reload farm worker only — never touch MuMu/emulators
    (LOG / "FARM_RELOAD_FARM.flag").write_text("cursor+freebuff_coord", encoding="utf-8")
    (LOG / "SSP_FORCE_REFRESH.flag").write_text("coord_refresh", encoding="utf-8")
    COORD_FLAG.write_text(_utc(), encoding="utf-8")

    snap = gather_checkin(
        fixes=[
            "cursor: tor bundled OK",
            "cursor: serial map synced (no emulator kill)",
            "cursor: adb reverse repin",
            "cursor: FARM_RELOAD flagged for tor path",
            *repin[:6],
        ],
        note="Cursor↔FREEBUFF coord · emulators untouched",
    )
    body = format_checkin(snap)
    handoff = {
        "agent": "Cursor",
        "partner": "FREEBUFF",
        "ts": _utc(),
        "emulators": "DO_NOT_KILL",
        "dash": "http://127.0.0.1:8091/",
        "adb_n": snap.adb_online if hasattr(snap, "adb_online") else len(phones),
        "farm_up": snap.farm_up,
        "verdict": snap.verdict,
        "repin": repin,
        "next_for_freebuff": [
            "Watch SSP paying>0 (house-only was blocker)",
            "Do NOT restart/kill MuMu",
            "If isolation fails: verify PHARMFLOW_TOR_PATH in overrides",
            "Reply on twskoops with live numbers",
        ],
        "checkin": body,
    }
    HANDOFF.write_text(json.dumps(handoff, indent=2) + "\n", encoding="utf-8")

    title = f"[PharmFlow] Cursor+FREEBUFF {snap.verdict}"
    publish_ntfy(title, body, tags="clipboard,phone,white_check_mark", force=True)
    print("HANDOFF", HANDOFF, flush=True)
    print(body, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
