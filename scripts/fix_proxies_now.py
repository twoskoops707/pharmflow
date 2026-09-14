#!/usr/bin/env python3
"""Emergency: restore guest http_proxy to inject ports on all farm phones."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("PHARMFLOW_MANTIS_INJECT_PROXY", "1")

from automation.browse_proxy import guest_proxy_healthy
from automation.farm_checkin import format_checkin, gather_checkin
from automation.mantis_inject_proxy import inject_enabled, phone_inject_port
from automation.tor_manager import phone_http_port
from wizard.mumu_farm_ops import MuMuFarmOps


def main() -> int:
    farm = MuMuFarmOps()
    farm.refresh_serials()
    phones = [
        (name, inst)
        for name, inst in list(getattr(farm, "instances", {}).items())
        if getattr(inst, "adb_serial", "")
    ]
    if not phones:
        print("No phones with an ADB serial. Nothing was repaired.")
        return 1
    results: list[str] = []
    repaired = 0
    for name, inst in phones:
        try:
            farm.setup_tor(name)
        except Exception as exc:
            print(name, "setup_tor fail", exc)
        idx = int(inst.index)
        port = phone_inject_port(idx) if inject_enabled() else phone_http_port(idx)
        ser = inst.adb_serial
        if port > 0:
            farm.adb.set_http_proxy("127.0.0.1", port, serial=ser)
        http = phone_http_port(idx)
        try:
            if http > 0:
                farm.adb.reverse(str(http), str(http), serial=ser)
            if port > 0:
                farm.adb.reverse(str(port), str(port), serial=ser)
        except Exception as exc:
            print(name, "reverse", exc)
        px = (
            farm.adb.shell("settings get global http_proxy", serial=ser, timeout=8).stdout or ""
        ).strip()
        ok = guest_proxy_healthy(px, idx)
        if ok:
            repaired += 1
        short = name.split(".")[0]
        line = f"{short} -> {px or 'none'}"
        print(line, "OK" if ok else "NOT REPAIRED")
        results.append(line)
    if repaired < 1:
        print(f"No phone got a loopback exit ({repaired} of {len(phones)}).")
        return 1
    fixes = [
        f"Proxy restored on {repaired} of {len(phones)} phone(s).",
        "; ".join(results),
    ]
    c = gather_checkin(fixes=fixes)
    print("---")
    print(format_checkin(c))
    print("proxy_bad", c.proxy_bad)
    print("(ntfy skipped — max 1/2h; use check-in for digest)")
    return 0 if repaired == len(phones) and not c.proxy_bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
