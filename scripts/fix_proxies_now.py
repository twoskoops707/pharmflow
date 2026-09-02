#!/usr/bin/env python3
"""Emergency: restore guest http_proxy to inject ports on all farm phones."""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("CPHARM_MANTIS_INJECT_PROXY", "1")

from automation.farm_checkin import format_checkin, gather_checkin
from automation.tor_manager import phone_http_port
from wizard.mumu_farm_ops import MuMuFarmOps


def main() -> int:
    farm = MuMuFarmOps()
    farm.refresh_serials()
    phones = [
        "vm0.gmadoa",
        "vm1.gmadoa",
        "vm2.gmadoa",
        "vm3.gmadoa",
    ]
    results: list[str] = []
    for name in phones:
        inst = farm.get_phone(name)
        if not inst or not inst.adb_serial:
            results.append(f"{name}=MISSING")
            print(name, "MISSING")
            continue
        try:
            farm.setup_tor(name)
        except Exception as exc:
            print(name, "setup_tor fail", exc)
        inject = 8218 + int(inst.index)
        ser = inst.adb_serial
        farm.adb.shell(
            f"settings put global http_proxy 127.0.0.1:{inject}",
            serial=ser,
            timeout=8,
        )
        http = phone_http_port(inst.index)
        try:
            farm.adb.reverse(str(http), str(http), serial=ser)
            farm.adb.reverse(str(inject), str(inject), serial=ser)
        except Exception as exc:
            print(name, "reverse", exc)
        px = (
            farm.adb.shell("settings get global http_proxy", serial=ser, timeout=8).stdout or ""
        ).strip()
        ok = px == f"127.0.0.1:{inject}"
        short = name.split(".")[0]
        line = f"{short} -> {px}"
        print(line, "OK" if ok else "BAD expect", f"127.0.0.1:{inject}")
        results.append(line)

    fixes = [
        "Proxy restored: all phones -> inject 8218+ (cleared :0 after ad-fill)",
        "; ".join(results),
    ]
    c = gather_checkin(fixes=fixes)
    print("---")
    print(format_checkin(c))
    print("proxy_bad", c.proxy_bad)
    print("(ntfy skipped — max 1/2h; use check-in for digest)")
    return 0 if not c.proxy_bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
