"""Read-only money path verification."""
from __future__ import annotations

import json
import socket
import subprocess
import sys
from pathlib import Path

import psutil

LOG = Path(r"C:\PharmFlow\logs")
LOCK = json.loads((LOG / "ADB_SERIAL_MAP.lock.json").read_text(encoding="utf-8-sig"))
phones = LOCK["phones"]
http_base = int(json.loads((LOG / "tor_port_bases.json").read_text()).get("http_base", 8268))
ADB = Path(r"C:\PharmFlow\bundled\adb.exe")
NW = int(getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0)


def port_open(port: int) -> bool:
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=0.35)
        s.close()
        return True
    except OSError:
        return False


def get_pids(marker: str) -> list[int]:
    out: list[int] = []
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmd = " ".join(str(x) for x in (proc.info.get("cmdline") or []))
            if marker in cmd:
                out.append(int(proc.info["pid"]))
        except (psutil.Error, TypeError, ValueError):
            pass
    return out


def main() -> int:
    inject_up = sum(1 for p in range(8242, 8250) if port_open(p))
    tor_up = sum(1 for i in range(24, 32) if port_open(http_base + i))
    bad_pins = 0
    for name, ser in phones.items():
        idx = int(name.split(".")[0][2:])
        want = f"127.0.0.1:{8218 + idx}"
        try:
            r = subprocess.run(
                [str(ADB), "-s", ser, "shell", "settings", "get", "global", "http_proxy"],
                capture_output=True,
                text=True,
                timeout=15,
                creationflags=NW,
            )
            cur = (r.stdout or "").strip().splitlines()[-1]
        except Exception as exc:
            cur = f"ERR:{exc}"
        if cur != want:
            bad_pins += 1
            print(f"BAD {name} want={want} got={cur}", flush=True)

    ka = get_pids("pharmflow_inject_keepalive.py")
    farm = get_pids("run_farm_354.py")
    roster = get_pids("run_mantis_inject_proxies.py")

    print(f"inject={inject_up}/8", flush=True)
    print(f"bad_pins={bad_pins}", flush=True)
    print(f"tor_http={tor_up}/8", flush=True)
    print(f"keepalive_pid={ka[0] if ka else 0}", flush=True)
    print(f"farm_pid={farm[0] if farm else 0}", flush=True)
    print(f"roster_inject_alive={roster}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
