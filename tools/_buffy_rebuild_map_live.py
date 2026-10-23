#!/usr/bin/env python3
"""Rebuild ADB_SERIAL_MAP.lock.json + overrides from LIVE MuMu ARM VM state.

Precedent: scripts/_restore_7_phone_map.py — but serials are READ from each
vm*.gmadoa/misc/state.json (AdbHost/AdbPort) instead of hardcoded, because VMs
re-IP on reboot. Never shrinks to ghosts: only VMs that state.json lists and
adb can reach are written. Inject port convention: 8218 + vm_index.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import time
from pathlib import Path

LOG = Path(r"C:\PharmFlow\logs")
_ADB_CANDIDATES = [
    Path(r"C:\PharmFlow\bundled\adb.exe"),
    Path(r"C:\Program Files\platform-tools\adb.exe"),
]
ADB = next((p for p in _ADB_CANDIDATES if p.is_file()), None) or shutil.which("adb")
VMS = Path(r"C:\Program Files\Netease\MuMuPlayerARM\vms")
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)


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


def _adb_online(serial: str) -> bool:
    try:
        r = subprocess.run(
            [str(ADB), "-s", serial, "shell", "echo", "ok"],
            capture_output=True,
            timeout=8,
            creationflags=FLAGS,
        )
        return r.returncode == 0 and b"ok" in r.stdout
    except Exception:
        return False


def main() -> int:
    _connect_all()
    phones: dict[str, str] = {}
    for vm in sorted(VMS.glob("vm*.gmadoa")):
        st = vm / "misc" / "state.json"
        if not st.is_file():
            continue
        try:
            d = json.loads(st.read_text(encoding="utf-8-sig"))
            host = str(d.get("AdbHost") or "").strip()
            port = int(d.get("AdbPort") or 5555)
        except Exception:
            continue
        if not host:
            continue
        serial = f"{host}:{port}"
        if _adb_online(serial):
            phones[vm.name] = serial
        else:
            print(f"skip offline {vm.name} {serial}")

    # Two VMs claiming one serial means a stale state.json — first claim wins,
    # the later VM is reported and skipped (no ghost/dup serials in the lock).
    seen: dict[str, str] = {}
    for name in sorted(phones, key=lambda n: int(n.split(".")[0][2:])):
        ser = phones[name]
        if ser in seen:
            print(f"DUP serial {ser}: {name} duplicates {seen[ser]} (stale state.json) — skipped")
            del phones[name]
        else:
            seen[ser] = name

    if not phones:
        print("ABORT: no live phones found in MuMu vms dir")
        return 2

    inject = {k: 8218 + int(k.split(".")[0][2:]) for k in phones}
    lock = {
        "phones": dict(phones),
        "tablet": {},
        "inject": inject,
        "note": "buffy_live_rebuild",
        "updated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    LOG.mkdir(parents=True, exist_ok=True)
    (LOG / "ADB_SERIAL_MAP.lock.json").write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    (LOG / "FARM_STICKY_7_PHONES.lock").write_text(
        json.dumps({"phones": dict(phones), "updated": lock["updated"]}, indent=2) + "\n",
        encoding="utf-8",
    )

    names = sorted(phones, key=lambda n: int(n.split(".")[0][2:]))
    ov_path = LOG / "farm_runtime_overrides.json"
    ov: dict = {}
    if ov_path.is_file():
        try:
            raw = json.loads(ov_path.read_text(encoding="utf-8-sig"))
            if isinstance(raw, dict):
                ov = raw
        except (OSError, json.JSONDecodeError):
            ov = {}
    ov["PHARMFLOW_FARM_PHONES"] = ",".join(names)
    ov["PHARMFLOW_ADB_SERIALS"] = ",".join(phones[n] for n in names)
    ov["PHARMFLOW_FARM_PHONE_COUNT"] = str(len(names))
    ov["PHARMFLOW_FARM_EXPECT_PHONES"] = str(len(names))
    ov_path.write_text(json.dumps(ov, indent=2) + "\n", encoding="utf-8")

    for n in names:
        print(f"{n} -> {phones[n]} inject={inject[n]}")
    print(f"wrote lock for {len(names)} phones")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
