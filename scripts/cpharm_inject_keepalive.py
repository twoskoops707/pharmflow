#!/usr/bin/env python3
"""Hold lock-map inject listeners + slot Tor HTTP. EXE self-heal spawns this.

Fleet comes from ADB_SERIAL_MAP.lock.json (absolute inject 8218+idx, Tor HTTP
at the live base + roster slot). Hardcoded vm24-31 watched the wrong ports
after the fleet moved, so a "keepalive alive" process never restored money.
"""
from __future__ import annotations

import json
import os
import re
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
from automation.mantis_inject_proxy import ensure_inject_for_phone, start_inject_proxies
from automation.tor_manager import restore_tor_http_for_slots

LOG = Path(os.environ.get("CPHARM_LOGS") or os.environ.get("CPHARM_LOG_DIR") or r"C:\CPharm\logs")
ADB = Path(r"C:\CPharm\bundled\adb.exe")
if not ADB.is_file():
    ADB = Path(r"C:\Program Files\Netease\MuMuPlayerARM\shell\adb.exe")


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


def _load_targets() -> list[tuple[int, str, int]]:
    """(absolute_idx, serial, slot) from the live lock map. No phone-count cap."""
    path = LOG / "ADB_SERIAL_MAP.lock.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError, TypeError, ValueError):
        data = {}
    phones = {
        str(k): str(v).strip()
        for k, v in dict(data.get("phones") or {}).items()
        if str(v or "").strip() and not str(v).startswith("127.0.0.1:")
    }
    rows: list[tuple[int, str]] = []
    for name, ser in phones.items():
        m = re.match(r"^vm(\d+)\.gmadoa$", name, re.IGNORECASE)
        if not m:
            continue
        rows.append((int(m.group(1)), ser))
    rows.sort()
    targets = [(idx, ser, slot) for slot, (idx, ser) in enumerate(rows)]
    os.environ["CPHARM_INJECT_SLOT_MAP"] = json.dumps(
        {str(idx): slot for idx, _ser, slot in targets},
        separators=(",", ":"),
    )
    return targets


def arm() -> None:
    targets = _load_targets()
    if not targets:
        print("arm skip no lock-map phones", flush=True)
        return
    idxs = [idx for idx, _ser, _slot in targets]
    slots = [slot for _idx, _ser, slot in targets]
    start_inject_proxies(idxs)
    adb = AdbWrapper()
    for idx, ser, _slot in targets:
        try:
            info = ensure_inject_for_phone(adb, ser, idx, install_ca=True)
            if not info.get("ok"):
                print(
                    f"ensure_not_ok {ser} err={info.get('error')} ca={info.get('ca_installed')}",
                    flush=True,
                )
        except Exception as exc:
            print(f"ensure_err {ser} {exc}", flush=True)
    # When the farm lane is up, unison self-heal owns slot Tor. A keepalive
    # fleet is classified helper_tor and reaped on the next tick — starting
    # it here only kills the bootstrap. Farm-down: this process is an allowed
    # owner, so restore the dead HTTP tunnels here.
    farm_alive = False
    try:
        from automation.cpharm_unison_dedupe import pids_for_script

        farm_alive = bool(pids_for_script("run_farm_354.py"))
    except Exception:
        farm_alive = False
    if farm_alive:
        print("tor_restore skipped farm_owns_tor", flush=True)
    else:
        try:
            report = restore_tor_http_for_slots(slots)
            print(f"tor_restore {report}", flush=True)
        except Exception as exc:
            print(f"tor_restore_err {exc}", flush=True)
    for idx, ser, _slot in targets:
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
    up = sum(1 for idx, _ser, _slot in targets if _port_open(8218 + idx))
    print(f"arm inject_up={up}/{len(targets)} pid={os.getpid()}", flush=True)


def main() -> int:
    LOG.mkdir(parents=True, exist_ok=True)
    (LOG / "cpharm_inject_keepalive.pid").write_text(str(os.getpid()), encoding="utf-8")
    arm()
    while True:
        time.sleep(20)
        targets = _load_targets()
        dead = [8218 + idx for idx, _ser, _slot in targets if not _port_open(8218 + idx)]
        if dead or not targets:
            print(f"re-arm dead={dead}", flush=True)
            arm()
            continue
        for idx, ser, _slot in targets:
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
