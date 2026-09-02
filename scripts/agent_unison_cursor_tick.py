#!/usr/bin/env python3
"""Dual-agent unison tick — Cursor infra lane. Never kills emulators."""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = Path(r"C:\CPharm\logs")
sys.path.insert(0, str(ROOT))

from automation.adb_wrapper import AdbWrapper
from automation.agent_unison import claim_task, complete_task, heartbeat, set_status
from automation.browse_proxy import _read_guest_proxy, pin_guest_proxy
from automation.farm_checkin import format_checkin, gather_checkin, publish_ntfy
from automation.farm_visit_caps import write_runtime_overrides
from automation.mantis_inject_proxy import ensure_inject_for_phone, verify_reverse_tunnel

AGENT = "cursor"


def _fix_serial_map() -> dict[str, str]:
    lock_path = LOG / "ADB_SERIAL_MAP.lock.json"
    lock: dict = json.loads(lock_path.read_text(encoding="utf-8-sig")) if lock_path.is_file() else {}
    phones: dict[str, str] = dict(lock.get("phones") or {})
    tablet: dict[str, str] = dict(lock.get("tablet") or {})
    # Never use offline tablet ghost — vm4 must be single live serial
    if "vm4.gmadoa" in phones:
        tablet.pop("vm4.gmadoa", None)
    elif "vm4.gmadoa" in tablet and "vm4.gmadoa" not in phones:
        phones["vm4.gmadoa"] = tablet.pop("vm4.gmadoa")
    inject = {p: 8218 + int(p.split(".")[0][2:]) for p in phones}
    lock.update(
        {
            "phones": phones,
            "tablet": tablet,
            "inject": inject,
            "note": "unison_cursor_infra",
        }
    )
    lock_path.write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    return phones


def _repin_live(phones: dict[str, str]) -> list[str]:
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
            notes.append(f"{name}:{proxy}:rev={ok}")
        except Exception as exc:
            notes.append(f"{name}:FAIL:{exc}")
    return notes


def main() -> int:
    if not claim_task(AGENT, "infra_tick", ttl_s=120):
        print("SKIP infra_tick claimed by other agent", flush=True)
        return 0

    heartbeat(AGENT, task="infra_tick", note="no emulator kill")
    write_runtime_overrides(
        {
            "CPHARM_TOR_PATH": r"C:\CPharm\bundled\tor.exe",
            "CPHARM_FARM_STOP": "0",
        }
    )
    phones = _fix_serial_map()
    repin = _repin_live(phones)
    (LOG / "FARM_RELOAD_FARM.flag").write_text("unison_cursor", encoding="utf-8")

    snap = gather_checkin(fixes=repin, note="Cursor infra tick · emulators untouched")
    set_status(
        adb_n=snap.adb_online,
        farm_up=snap.farm_up,
        verdict=snap.verdict,
        proxies_ok=snap.proxies_ok,
        proxies_total=snap.proxies_total,
        repin=repin,
    )
    heartbeat(AGENT, task="infra_tick_done", extra={"repin_n": len(repin)})

    # Notify FREEBUFF lane on twskoops (force — coordination message)
    body = (
        "UNISON Cursor infra tick done\n"
        + format_checkin(snap)
        + "\n\nFREEBUFF lane: SSP/mantis/ntfy — read AGENT_UNISON.json"
    )
    publish_ntfy("[FamFlow] UNISON Cursor infra", body, force=True)
    complete_task(AGENT, "infra_tick", result="ok")
    print(body, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
