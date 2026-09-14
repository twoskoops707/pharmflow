#!/usr/bin/env python3
"""Fix Tor stealing inject ports (8218+) — restore HTTPTunnel 8118+ + inject + repin.

Root cause: PharmFlow tor_manager auto-shifted HTTPTunnelPort onto 8218+,
so inject could not bind and phones hit raw Tor (no Mantis MITM).
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LOG = Path(r"C:\PharmFlow\logs")
sys.path.insert(0, str(ROOT))

import automation.no_window  # noqa: E402,F401  — CREATE_NO_WINDOW for taskkill/tor children
from automation.win_subprocess import hidden_run_kwargs  # noqa: E402

# Force correct bases BEFORE importing tor_manager / config
os.environ["PHARMFLOW_TOR_HTTP_BASE"] = "8118"
os.environ["PHARMFLOW_TOR_SOCKS_BASE"] = "9050"
os.environ["PHARMFLOW_TOR_CONTROL_BASE"] = "9151"
os.environ["PHARMFLOW_TOR_PATH"] = r"C:\PharmFlow\bundled\tor.exe"
if not Path(os.environ["PHARMFLOW_TOR_PATH"]).is_file():
    os.environ["PHARMFLOW_TOR_PATH"] = r"C:\PharmFlow\automation\tor\tor.exe"

from automation.adb_wrapper import AdbWrapper  # noqa: E402
from automation.browse_proxy import pin_guest_proxy  # noqa: E402
from automation.config import TOR_HTTP_TUNNEL_BASE  # noqa: E402
from automation.farm_visit_caps import write_runtime_overrides  # noqa: E402
from automation.mantis_inject_proxy import (  # noqa: E402
    ensure_inject_for_phone,
    start_inject_proxies,
    verify_reverse_tunnel,
)
from automation.tor_manager import TorManager, phone_http_port  # noqa: E402

ADB = Path(r"C:\PharmFlow\bundled\adb.exe")
PYW = Path(r"C:\Users\jsmil\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe")


def _kill_all_tor() -> int:
    n = 0
    try:
        import psutil
    except ImportError:
        subprocess.run(
            ["taskkill", "/F", "/IM", "tor.exe"],
            capture_output=True,
            **hidden_run_kwargs(),
        )
        return -1
    for proc in psutil.process_iter(["pid", "name"]):
        try:
            if (proc.info.get("name") or "").lower() == "tor.exe":
                proc.kill()
                n += 1
        except Exception:
            continue
    return n


def _kill_inject() -> int:
    n = 0
    try:
        import psutil
    except ImportError:
        return 0
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmd = " ".join(proc.info.get("cmdline") or [])
            if "run_mantis_inject_proxies" in cmd or "watch_proxy_inject" in cmd:
                proc.kill()
                n += 1
        except Exception:
            continue
    return n


def _probe_http(port: int, timeout: float = 25.0) -> str:
    proxy = f"http://127.0.0.1:{port}"
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({"http": proxy, "https": proxy})
    )
    with opener.open("http://ifconfig.me/ip", timeout=timeout) as resp:
        return (resp.read() or b"").decode("utf-8", errors="replace").strip()


def main() -> int:
    print(f"TOR_HTTP_BASE={TOR_HTTP_TUNNEL_BASE} (must be 8118)", flush=True)
    if int(TOR_HTTP_TUNNEL_BASE) != 8118:
        print("ABORT bad TOR_HTTP_TUNNEL_BASE", flush=True)
        return 2

    write_runtime_overrides(
        {
            "PHARMFLOW_TOR_HTTP_BASE": "8118",
            "PHARMFLOW_TOR_SOCKS_BASE": "9050",
            "PHARMFLOW_TOR_CONTROL_BASE": "9151",
            "PHARMFLOW_TOR_PATH": os.environ["PHARMFLOW_TOR_PATH"],
            "PHARMFLOW_MANTIS_INJECT_PROXY": "1",
            "PHARMFLOW_NEVER_SHARE_EXIT_IP": "1",
        }
    )

    killed_tor = _kill_all_tor()
    killed_inj = _kill_inject()
    print(f"killed tor={killed_tor} inject={killed_inj}", flush=True)
    time.sleep(2)

    lock_path = LOG / "ADB_SERIAL_MAP.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8-sig")) if lock_path.is_file() else {}
    phones = dict(lock.get("phones") or {})
    phones.update(lock.get("tablet") or {})
    if not phones:
        print("NO_PHONES_IN_LOCK", flush=True)
        return 3

    idxs = sorted({int(name.split(".")[0][2:]) for name in phones})
    print(f"phones={sorted(phones)} idxs={idxs}", flush=True)

    adb = AdbWrapper()
    tor = TorManager(adb)
    for name, ser in sorted(phones.items(), key=lambda x: int(x[0].split(".")[0][2:])):
        idx = int(name.split(".")[0][2:])
        try:
            inst = tor.start_phone_tor(idx, ser)
            print(
                f"TOR_UP {name} idx={idx} http={inst.http_port} socks={inst.socks_port}",
                flush=True,
            )
        except Exception as exc:
            print(f"TOR_FAIL {name} {exc}", flush=True)

    time.sleep(4)
    for idx in idxs:
        port = phone_http_port(idx)
        try:
            ip = _probe_http(port)
            print(f"EXIT_OK idx={idx} :{port} ip={ip}", flush=True)
        except Exception as exc:
            print(f"EXIT_FAIL idx={idx} :{port} {exc}", flush=True)

    # Inject on 8218+ (must be free now that Tor is on 8118+)
    start_inject_proxies(idxs)
    print(f"inject started for {idxs}", flush=True)

    subprocess.Popen(
        [str(PYW), "-u", str(ROOT / "scripts" / "run_mantis_inject_proxies.py"), "--phones", "14", "--no-install-ca"],
        **hidden_run_kwargs(),
    )

    for name, ser in sorted(phones.items(), key=lambda x: int(x[0].split(".")[0][2:])):
        idx = int(name.split(".")[0][2:])
        try:
            ensure_inject_for_phone(adb, ser, idx, install_ca=False)
            pin_guest_proxy(adb, ser, idx)
            ok = verify_reverse_tunnel(adb, ser, 8218 + idx)
            print(f"PIN_OK {name} inject={8218+idx} reverse={ok}", flush=True)
        except Exception as exc:
            print(f"PIN_FAIL {name} {exc}", flush=True)

    print("DONE_TOR_FIX", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
