"""One-shot inject CA + reverse + proxy pin for money phones."""
from __future__ import annotations

import json
import socket
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import automation.no_window  # noqa: F401

from automation.adb_wrapper import AdbWrapper
from automation.mantis_inject_ca import (
    android_cacert_hash,
    ensure_ca_files,
    install_ca_on_device,
)
from cryptography import x509

LOG = Path(r"C:\PharmFlow\logs")
LOCK = json.loads((LOG / "ADB_SERIAL_MAP.lock.json").read_text(encoding="utf-8-sig"))
phones = LOCK["phones"]
ADB = Path(r"C:\PharmFlow\bundled\adb.exe")
NW = int(getattr(subprocess, "CREATE_NO_WINDOW", 0) or 0)


def port_open(port: int) -> bool:
    try:
        s = socket.create_connection(("127.0.0.1", port), 0.35)
        s.close()
        return True
    except OSError:
        return False


def main() -> int:
    adb = AdbWrapper()
    ensure_ca_files()
    cert = x509.load_pem_x509_certificate(
        Path(r"C:\PharmFlow\certs\mantis_inject\ca.cert.pem").read_bytes()
    )
    remote_name = f"{android_cacert_hash(cert)}.0"
    ca_ok = 0
    bad_pins = 0
    for name, ser in sorted(phones.items()):
        idx = int(name.split(".")[0][2:])
        port = 8218 + idx
        if port < 8242 or port > 8249:
            continue
        install_ca_on_device(adb, ser)
        verify = adb.shell(
            f"test -f /system/etc/security/cacerts/{remote_name} && echo PRESENT "
            f"|| test -f /apex/com.android.conscrypt/cacerts/{remote_name} && echo PRESENT",
            serial=ser,
            timeout=12,
        )
        if "PRESENT" in (verify.stdout or ""):
            ca_ok += 1
        subprocess.run(
            [str(ADB), "-s", ser, "reverse", f"tcp:{port}", f"tcp:{port}"],
            capture_output=True,
            timeout=15,
            creationflags=NW,
        )
        subprocess.run(
            [
                str(ADB),
                "-s",
                ser,
                "shell",
                "settings",
                "put",
                "global",
                "http_proxy",
                f"127.0.0.1:{port}",
            ],
            capture_output=True,
            timeout=15,
            creationflags=NW,
        )
        r = subprocess.run(
            [str(ADB), "-s", ser, "shell", "settings", "get", "global", "http_proxy"],
            capture_output=True,
            text=True,
            timeout=15,
            creationflags=NW,
        )
        cur = (r.stdout or "").strip().splitlines()[-1]
        want = f"127.0.0.1:{port}"
        if cur != want:
            bad_pins += 1
            print(f"BAD {name} want={want} got={cur}", flush=True)
        else:
            print(f"OK {name} port={port}", flush=True)
    inject_up = sum(1 for p in range(8242, 8250) if port_open(p))
    print(f"inject={inject_up}/8", flush=True)
    print(f"bad_pins={bad_pins}", flush=True)
    print(f"ca_ok={ca_ok}/8", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
