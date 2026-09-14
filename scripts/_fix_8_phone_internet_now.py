#!/usr/bin/env python3
"""Map live 8 MuMu phones + fix internet (tor 8118+ / inject 8218+ / repin)."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = Path(r"C:\PharmFlow\logs")
sys.path.insert(0, str(ROOT))

os.environ["PHARMFLOW_TOR_HTTP_BASE"] = "8118"
os.environ["PHARMFLOW_TOR_SOCKS_BASE"] = "9050"
os.environ["PHARMFLOW_TOR_CONTROL_BASE"] = "9151"
os.environ["PHARMFLOW_TOR_PATH"] = r"C:\PharmFlow\bundled\tor.exe"

from automation.adb_wrapper import AdbWrapper
from automation.browse_proxy import pin_guest_proxy, _read_guest_proxy
from automation.mantis_inject_proxy import ensure_inject_for_phone, start_inject_proxies, verify_reverse_tunnel
from automation.tor_manager import TorManager

VMS = Path(r"C:\Program Files\Netease\MuMuPlayerARM\vms")
ADB = Path(r"C:\PharmFlow\bundled\adb.exe")
PYW = Path(r"C:\Users\jsmil\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe")
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# Live ADB right now (from MuMu state.json scan)
PHONES = {
    "vm0.gmadoa": "10.0.2.187:5555",
    "vm1.gmadoa": "10.0.2.57:5555",
    "vm5.gmadoa": "10.0.2.198:5555",
    "vm7.gmadoa": "10.0.2.130:5555",
    "vm9.gmadoa": "10.0.2.119:5555",
    "vm10.gmadoa": "10.0.2.110:5555",
    "vm12.gmadoa": "10.0.2.203:5555",
    "vm13.gmadoa": "10.0.2.225:5555",
}


def main() -> int:
    names = sorted(PHONES.keys(), key=lambda x: int(x.split(".")[0][2:]))
    serials = [PHONES[n] for n in names]
    n = len(names)
    inject = {name: 8218 + int(name.split(".")[0][2:]) for name in names}

    lock = {
        "phones": dict(PHONES),
        "tablet": {},
        "inject": inject,
        "note": "live_8_internet_fix",
        "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    LOG.mkdir(parents=True, exist_ok=True)
    (LOG / "ADB_SERIAL_MAP.lock.json").write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")

    ov_path = LOG / "farm_runtime_overrides.json"
    ov: dict = {}
    if ov_path.is_file():
        ov = json.loads(ov_path.read_text(encoding="utf-8-sig"))
    ov.update(
        {
            "PHARMFLOW_FARM_PHONES": ",".join(names),
            "PHARMFLOW_ADB_SERIALS": ",".join(serials),
            "PHARMFLOW_FARM_PHONE_COUNT": str(n),
            "PHARMFLOW_FARM_EXPECT_PHONES": str(n),
            "PHARMFLOW_TABLET_FARM": "1",
            "PHARMFLOW_FARM_BAN_SERIALS": "10.0.2.216,127.0.0.1:16544,10.0.2.108",
            "PHARMFLOW_REQUIRE_FARM_BROWSERS": "0",
            "PHARMFLOW_FAST_STICKY_BOOT": "1",
            "PHARMFLOW_FARM_UNIQUE_SEQ": "1",
            "PHARMFLOW_SKIP_SEQUENCE_ISOLATION": "0",
            "PHARMFLOW_NEVER_SHARE_EXIT_IP": "1",
            "PHARMFLOW_MANTIS_INJECT_PROXY": "1",
            "PHARMFLOW_TOR_HTTP_BASE": "8118",
            "PHARMFLOW_TOR_PATH": r"C:\PharmFlow\bundled\tor.exe",
            "PHARMFLOW_FARM_STOP": "0",
            "PHARMFLOW_SKIP_BOOT_GEO": "1",
            "PHARMFLOW_PREFER_PAYING": "1",
            "PHARMFLOW_SSP_PREFER_PAYING": "1",
        }
    )
    ov_path.write_text(json.dumps(ov, indent=2) + "\n", encoding="utf-8")
    print(f"MAP {n} phones", flush=True)

    # Tor per phone index
    tor = TorManager()
    adb = AdbWrapper()
    for name, ser in PHONES.items():
        idx = int(name.split(".")[0][2:])
        try:
            tor.start_phone_tor(idx, ser)
            print(f"tor ok phone={idx}", flush=True)
        except Exception as exc:
            print(f"tor FAIL phone={idx} {exc}", flush=True)

    # Inject listener (indices 0-13 covers all)
    try:
        import psutil

        for proc in psutil.process_iter(["pid", "cmdline"]):
            cmd = " ".join(proc.info.get("cmdline") or [])
            if "run_mantis_inject_proxies" in cmd:
                proc.kill()
    except Exception:
        pass
    time.sleep(1)
    start_inject_proxies(phone_indices=[int(n.split(".")[0][2:]) for n in names])
    print("inject started", flush=True)
    time.sleep(3)

    for name, ser in PHONES.items():
        idx = int(name.split(".")[0][2:])
        port = 8218 + idx
        try:
            adb.reverse(str(port), str(port), serial=ser)
            ensure_inject_for_phone(adb, ser, idx, install_ca=False)
            pin_guest_proxy(adb, ser, idx)
            ok = verify_reverse_tunnel(adb, ser, port)
            proxy = _read_guest_proxy(adb, ser)
            adb.shell("svc wifi enable", serial=ser)
            print(f"OK {name} {ser} proxy={proxy} rev={ok}", flush=True)
        except Exception as exc:
            print(f"FAIL {name} {exc}", flush=True)

    # Clear stale locks, reload farm
    prog = LOG / "farm_354_progress.json"
    if prog.is_file():
        d = json.loads(prog.read_text(encoding="utf-8-sig"))
        d["active_sequences"] = []
        d["active_keys"] = []
        prog.write_text(json.dumps(d, indent=2) + "\n", encoding="utf-8")

    (LOG / "PAUSE_BOTTOM_ADS_WATCH.flag").write_text("internet_fix_8", encoding="utf-8")

    try:
        import psutil

        for proc in psutil.process_iter(["pid", "cmdline"]):
            cmd = " ".join(proc.info.get("cmdline") or [])
            if "watch_bottom_ads" in cmd or "farm_fail_review" in cmd:
                proc.kill()
    except Exception:
        pass

    print("DONE_8", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
