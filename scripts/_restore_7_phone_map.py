#!/usr/bin/env python3
"""Restore sticky 7-phone map — never shrink on ADB blips."""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

LOG = Path(r"C:\PharmFlow\logs")
ADB = Path(r"C:\PharmFlow\bundled\adb.exe")
VMS = Path(r"C:\Program Files\Netease\MuMuPlayerARM\vms")
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)

PHONES = {
    "vm0.gmadoa": "10.0.2.187:5555",
    "vm3.gmadoa": "10.0.2.132:5555",
    "vm4.gmadoa": "10.0.2.51:5555",
    "vm5.gmadoa": "10.0.2.198:5555",
    "vm7.gmadoa": "10.0.2.130:5555",
    "vm12.gmadoa": "10.0.2.203:5555",
    "vm13.gmadoa": "10.0.2.225:5555",
}


def _connect_all() -> None:
    for vm in sorted(VMS.glob("vm*.gmadoa")):
        st = vm / "misc" / "state.json"
        if not st.is_file():
            continue
        try:
            d = json.loads(st.read_text(encoding="utf-8-sig"))
            host = str(d.get("AdbHost") or "").strip()
            port = int(d.get("AdbPort") or 5555)
            if host:
                subprocess.run(
                    [str(ADB), "connect", f"{host}:{port}"],
                    capture_output=True,
                    timeout=10,
                    creationflags=FLAGS,
                )
        except Exception:
            pass
    time.sleep(2)


def main() -> int:
    _connect_all()
    inject = {k: 8218 + int(k.split(".")[0][2:]) for k in PHONES}
    lock = {
        "phones": dict(PHONES),
        "tablet": {},
        "inject": inject,
        "note": "restore_7_sticky",
        "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    LOG.mkdir(parents=True, exist_ok=True)
    (LOG / "ADB_SERIAL_MAP.lock.json").write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")

    ov_path = LOG / "farm_runtime_overrides.json"
    ov: dict = {}
    if ov_path.is_file():
        ov = json.loads(ov_path.read_text(encoding="utf-8-sig"))
    names = sorted(PHONES.keys(), key=lambda x: int(x.split(".")[0][2:]))
    ov.update(
        {
            "PHARMFLOW_FARM_PHONES": ",".join(names),
            "PHARMFLOW_ADB_SERIALS": ",".join(PHONES[n] for n in names),
            "PHARMFLOW_FARM_PHONE_COUNT": "7",
            "PHARMFLOW_FARM_EXPECT_PHONES": "7",
            "PHARMFLOW_FARM_UNIQUE_SEQ": "1",
            "PHARMFLOW_SKIP_SEQUENCE_ISOLATION": "0",
            "PHARMFLOW_NEVER_SHARE_EXIT_IP": "1",
            "PHARMFLOW_TABLET_FARM": "1",
            "PHARMFLOW_TABLET_PHONE": "",
            "PHARMFLOW_TABLET_SERIAL": "",
        }
    )
    ov_path.write_text(json.dumps(ov, indent=2) + "\n", encoding="utf-8")
    sticky = {
        "phones": dict(PHONES),
        "note": "sticky_7_all_farm_including_vm4",
        "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    (LOG / "FARM_STICKY_7_PHONES.lock").write_text(json.dumps(sticky, indent=2) + "\n", encoding="utf-8")
    (LOG / "FARM_RELOAD_FARM.flag").write_text("restore_7_phones", encoding="utf-8")
    (LOG / "PAUSE_BOTTOM_ADS_WATCH.flag").write_text("cursor_monitor", encoding="utf-8")
    print("RESTORED", len(PHONES), "phones", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
