#!/usr/bin/env python3
"""Hold absolute inject 24..31 + hard-pin guests. EXE self-heal spawns this."""
from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import automation.no_window  # noqa: F401

from automation.adb_wrapper import AdbWrapper
from automation.mantis_inject_proxy import start_inject_proxies
from automation import tor_manager

LOG = Path(r"C:\CPharm\logs")
ADB = Path(r"C:\CPharm\bundled\adb.exe")
if not ADB.is_file():
    ADB = Path(r"C:\Program Files\Netease\MuMuPlayerARM\shell\adb.exe")

SERIALS = {
    24: "10.0.2.30:5555",
    25: "10.0.2.188:5555",
    26: "10.0.2.240:5555",
    27: "10.0.2.43:5555",
    28: "10.0.2.172:5555",
    29: "10.0.2.189:5555",
    30: "10.0.2.170:5555",
    31: "10.0.2.148:5555",
}


def _adb(args: list[str], timeout: float = 12.0) -> None:
    subprocess.run(
        [str(ADB), *args],
        capture_output=True,
        timeout=timeout,
        creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0),
    )


def _port_open(port: int) -> bool:
    try:
        c = socket.create_connection(("127.0.0.1", port), 0.35)
        c.close()
        return True
    except OSError:
        return False


def _install_ca_best_effort() -> None:
    if str(os.environ.get("CPHARM_INJECT_INSTALL_CA", "1")).strip().lower() in (
        "0",
        "false",
        "no",
        "off",
    ):
        return
    try:
        from automation.mantis_inject_ca import install_ca_on_device
    except Exception:
        return
    adb = AdbWrapper()
    for ser in SERIALS.values():
        try:
            install_ca_on_device(adb, ser)
        except Exception:
            pass


def arm() -> None:
    idxs = list(range(24, 32))
    start_inject_proxies(idxs)
    _install_ca_best_effort()
    # When farm lane owns Tor, do NOT spawn a second Tor fleet (process storm).
    farm_alive = False
    try:
        from automation.cpharm_unison_dedupe import pids_for_script

        farm_alive = bool(pids_for_script("run_farm_354.py"))
    except Exception:
        farm_alive = False
    if not farm_alive:
        for idx in idxs:
            try:
                tor_manager.start_tor_for_phone(idx)
            except Exception:
                pass
    else:
        # Farm owns Tor, but if listeners died, re-warm so money path doesn't stall.
        dead_tor = [i for i in idxs if not _port_open(8268 + i) and not _port_open(8118 + i)]
        for idx in dead_tor:
            try:
                tor_manager.start_tor_for_phone(idx)
            except Exception:
                pass
    for idx, ser in SERIALS.items():
        port = 8218 + idx
        try:
            _adb(["-s", ser, "reverse", f"tcp:{port}", f"tcp:{port}"])
            _adb(
                [
                    "-s",
                    ser,
                    "shell",
                    "settings",
                    "put",
                    "global",
                    "http_proxy",
                    f"127.0.0.1:{port}",
                ]
            )
        except Exception:
            pass
    up = sum(1 for p in range(8242, 8250) if _port_open(p))
    print(f"arm inject_up={up}/8 pid={os.getpid()} farm_alive={int(farm_alive)}", flush=True)


def main() -> int:
    LOG.mkdir(parents=True, exist_ok=True)
    (LOG / "cpharm_inject_keepalive.pid").write_text(str(os.getpid()), encoding="utf-8")
    arm()
    while True:
        time.sleep(20)
        dead = [p for p in range(8242, 8250) if not _port_open(p)]
        if dead:
            print(f"re-arm dead={dead}", flush=True)
            arm()
        else:
            # re-assert pins that drift to 8218-8221
            for idx, ser in SERIALS.items():
                port = 8218 + idx
                try:
                    r = subprocess.run(
                        [str(ADB), "-s", ser, "shell", "settings", "get", "global", "http_proxy"],
                        capture_output=True,
                        text=True,
                        timeout=8,
                        creationflags=int(getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0),
                    )
                    cur = (r.stdout or "").strip().splitlines()[-1] if r.stdout else ""
                    want = f"127.0.0.1:{port}"
                    if cur != want:
                        print(f"re-pin {ser} {cur} -> {want}", flush=True)
                        _adb(["-s", ser, "reverse", f"tcp:{port}", f"tcp:{port}"])
                        _adb(
                            [
                                "-s",
                                ser,
                                "shell",
                                "settings",
                                "put",
                                "global",
                                "http_proxy",
                                want,
                            ]
                        )
                except Exception:
                    pass


if __name__ == "__main__":
    raise SystemExit(main())
