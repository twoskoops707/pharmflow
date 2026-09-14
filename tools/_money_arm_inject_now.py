"""One-shot: arm Tor+inject+pin for LIVE serial-map phones only. Money path."""
from __future__ import annotations

import json
import os
import socket
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("PHARMFLOW_TOR_PATH", r"C:\PharmFlow\automation\tor\tor.exe")

import automation.no_window  # noqa: E402,F401

from automation.adb_wrapper import AdbWrapper  # noqa: E402
from automation.browse_proxy import pin_guest_proxy  # noqa: E402
from automation.mantis_inject_proxy import ensure_inject_for_phone  # noqa: E402
from automation.tor_manager import ensure_tor_and_proxy_for_phone  # noqa: E402

LOG = Path(r"C:\PharmFlow\logs")


def _port_open(port: int) -> bool:
    try:
        s = socket.create_connection(("127.0.0.1", port), timeout=0.4)
        s.close()
        return True
    except OSError:
        return False


def main() -> int:
    pause = LOG / "PAUSE_BOTTOM_ADS_WATCH.flag"
    if pause.is_file():
        pause.unlink()
        print("cleared PAUSE_BOTTOM_ADS_WATCH.flag")

    lock_path = LOG / "ADB_SERIAL_MAP.lock.json"
    lock = json.loads(lock_path.read_text(encoding="utf-8-sig"))
    phones = {
        k: str(v).strip()
        for k, v in dict(lock.get("phones") or {}).items()
        if str(v).strip() and not str(v).startswith("127.0.0.1:")
    }
    inject = dict(lock.get("inject") or {})
    if not phones:
        print("ABORT: no live serials in ADB_SERIAL_MAP.lock.json")
        return 2

    names = sorted(phones, key=lambda n: int(n.split(".")[0][2:]))
    # Operator overrides must match live fleet (inputs win).
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
    print("overrides ->", ov["PHARMFLOW_FARM_PHONES"])

    # Persist lock as live-only (no empty ghosts).
    lock_out = {
        "phones": {n: phones[n] for n in names},
        "tablet": {},
        "inject": {
            n: int(inject.get(n) or (8218 + int(n.split(".")[0][2:])))
            for n in names
        },
        "note": "money_arm_live_only",
        "updated": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc
        ).isoformat(),
    }
    lock_path.write_text(json.dumps(lock_out, indent=2) + "\n", encoding="utf-8")
    sticky = LOG / "FARM_STICKY_7_PHONES.lock"
    sticky.write_text(
        json.dumps({"phones": lock_out["phones"], "updated": lock_out["updated"]}, indent=2)
        + "\n",
        encoding="utf-8",
    )

    adb = AdbWrapper()
    ok_n = 0
    for name in names:
        ser = phones[name]
        idx = int(name.split(".")[0][2:])
        port = int(lock_out["inject"][name])
        print(f"=== {name} {ser} idx={idx} inject={port}")
        try:
            tor = ensure_tor_and_proxy_for_phone(ser, idx)
            print("  tor ok=", tor.get("ok"), "http=", tor.get("http_port"), "err=", tor.get("error"))
        except Exception as exc:
            print("  tor_err", exc)
            continue
        try:
            info = ensure_inject_for_phone(adb, ser, idx, install_ca=True)
            print("  inject", info)
        except Exception as exc:
            print("  inject_err", exc)
            continue
        try:
            pin_guest_proxy(adb, ser, idx)
            print("  pinned idx=", idx, "port=", port)
            ok_n += 1
        except Exception as exc:
            print("  pin_err", exc)

    ports = sorted(lock_out["inject"].values())
    print("inject_listen", {p: _port_open(int(p)) for p in ports})
    print("tor_http", {8118 + (int(p) - 8218): _port_open(8118 + (int(p) - 8218)) for p in ports})
    print(f"DONE armed={ok_n}/{len(names)}")
    return 0 if ok_n == len(names) else 1


if __name__ == "__main__":
    raise SystemExit(main())
