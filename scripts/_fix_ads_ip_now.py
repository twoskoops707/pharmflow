#!/usr/bin/env python3
"""One-shot: remap live ADB serials, pin inject proxies, check IPs, start farm."""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = Path(r"C:\CPharm\logs")
sys.path.insert(0, str(ROOT))

from automation.adb_wrapper import AdbWrapper
from automation.browse_proxy import _read_guest_proxy, pin_guest_proxy
from automation.cpharm_exe_owned import mark_exe_owned
from automation.farm_visit_caps import reassert_sticky_caps, write_runtime_overrides
from wizard.farm_control import ensure_operator_stack, farm_running, start_farm

ADB = Path(r"C:\Users\jsmil\AppData\Local\Android\Sdk\platform-tools\adb.exe")
VMS_ROOT = Path(r"C:\Program Files\Netease\MuMuPlayerARM\vms")


def _adb_serials() -> set[str]:
    r = subprocess.run([str(ADB), "devices"], capture_output=True, text=True, timeout=15)
    return {ln.split()[0] for ln in r.stdout.splitlines() if "\tdevice" in ln}


def _build_live_map(serials: set[str]) -> dict[str, str]:
    live: dict[str, str] = {}
    for vm in sorted(VMS_ROOT.glob("vm*.gmadoa")):
        st = vm / "misc" / "state.json"
        if not st.is_file():
            continue
        try:
            data = json.loads(st.read_text(encoding="utf-8-sig"))
            host = str(data.get("AdbHost") or "").strip()
            port = int(data.get("AdbPort") or 5555)
            ser = f"{host}:{port}"
            if ser in serials:
                live[vm.name] = ser
        except Exception as exc:
            print(f"state_err {vm.name} {exc}", flush=True)

    if len(live) < len(serials):
        used = set(live.values())
        extra = sorted(serials - used)
        idx = 0
        for i in range(20):
            name = f"vm{i}.gmadoa"
            if name in live:
                continue
            if idx >= len(extra):
                break
            live[name] = extra[idx]
            idx += 1
    return live


def _guest_ip(adb: AdbWrapper, serial: str) -> str:
    cmd = (
        "curl -s --max-time 8 https://api.ipify.org 2>/dev/null "
        "|| wget -qO- --timeout=8 https://api.ipify.org 2>/dev/null"
    )
    try:
        return (adb.shell(cmd, serial=serial) or "").strip()[:60]
    except Exception as exc:
        return f"err:{exc}"


def main() -> int:
    for bad in ("farm_visit_caps_lock.json",):
        p = LOG / bad
        if p.is_dir():
            bak = LOG / f"{bad}.bak_dir"
            if bak.exists():
                import shutil

                shutil.rmtree(bak, ignore_errors=True)
            p.rename(bak)
            print(f"FIXED_DIR {bad}", flush=True)

    serials = _adb_serials()
    print(f"ADB_ONLINE {len(serials)} {sorted(serials)}", flush=True)
    if not serials:
        print("FAIL_NO_ADB", flush=True)
        return 3

    live = _build_live_map(serials)
    phones = sorted(live.keys(), key=lambda x: int(x.split(".")[0][2:]))
    ser_list = [live[p] for p in phones]
    n = len(phones)

    inject = {p: 8218 + int(p.split(".")[0][2:]) for p in phones}
    lock = {
        "phones": {p: live[p] for p in phones if p != "vm4.gmadoa"},
        "tablet": {"vm4.gmadoa": live["vm4.gmadoa"]} if "vm4.gmadoa" in live else {},
        "inject": inject,
        "note": "fix_ads_ip_now",
        "updated": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (LOG / "ADB_SERIAL_MAP.lock.json").write_text(json.dumps(lock, indent=2) + "\n", encoding="utf-8")
    print(f"WROTE_LOCK n={n} {phones}", flush=True)

    adb = AdbWrapper()
    for name, ser in zip(phones, ser_list):
        idx = int(name.split(".")[0][2:])
        try:
            pin_guest_proxy(adb, ser, idx)
            proxy = _read_guest_proxy(adb, ser)
            ip = _guest_ip(adb, ser)
            print(f"PIN {name} {ser} proxy={proxy} ip={ip}", flush=True)
        except Exception as exc:
            print(f"PIN_FAIL {name} {ser} {exc}", flush=True)

    write_runtime_overrides(
        {
            "CPHARM_FARM_PHONES": ",".join(phones),
            "CPHARM_ADB_SERIALS": ",".join(ser_list),
            "CPHARM_FARM_PHONE_COUNT": str(n),
            "CPHARM_FARM_EXPECT_PHONES": str(n),
            "CPHARM_FARM_STOP": "0",
            "CPHARM_TOR_PATH": r"C:\CPharm\bundled\tor.exe",
            "CPHARM_MANTIS_INJECT_PROXY": "1",
        }
    )
    print(f"reassert {reassert_sticky_caps()}", flush=True)

    mark_exe_owned(in_process=False)
    ensure_operator_stack(log=lambda m, l="ok": print(f"[{l}] {m}", flush=True))
    if farm_running():
        (LOG / "FARM_RELOAD_FARM.flag").write_text("ads_ip_fix", encoding="utf-8")
        print("FARM_RELOAD_FLAGGED", flush=True)
    else:
        ok = start_farm(hours=0.0, log=lambda m, l="ok": print(f"[{l}] {m}", flush=True), takeover=True)
        print(f"START_FARM {ok}", flush=True)

    time.sleep(10)
    try:
        import psutil

        pids = [
            p.info["pid"]
            for p in psutil.process_iter(["pid", "cmdline"])
            if p.info.get("cmdline") and any("run_farm_354" in str(x) for x in p.info["cmdline"])
        ]
        print(f"FARM_PIDS {pids}", flush=True)
    except Exception as exc:
        print(f"FARM_PID_CHECK {exc}", flush=True)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
