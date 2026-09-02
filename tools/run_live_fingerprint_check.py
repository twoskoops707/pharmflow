#!/usr/bin/env python3
"""
Dev CLI — live fingerprint audit/apply for one phone.

Operators: CPharmMuMuSetup.exe → GO (all phones) or CPharm → Re-apply hide emulator.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for sub in ("automation", "wizard"):
    p = ROOT / sub
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import mumu_farm_ops as farm  # noqa: E402
import setup_wizard as wiz  # noqa: E402


def _adb_ok(serial: str) -> bool:
    try:
        out = wiz.adb("shell", "echo", "ok", serial=serial, timeout=10).strip()
        return out == "ok"
    except Exception:
        return False


def main() -> int:
    ap = argparse.ArgumentParser(description="Live MuMu fingerprint audit/apply (dev CLI)")
    ap.add_argument("--serial", required=True, help="ADB serial (discover via adb devices)")
    ap.add_argument("--apply", action="store_true", help="Apply fingerprint fix")
    ap.add_argument("--index", type=int, default=0, help="Farm slot index (0=first phone)")
    args = ap.parse_args()
    serial = args.serial.strip()

    print(f"CPharm live fingerprint — {serial}")
    print("Operators: CPharmMuMuSetup.exe → GO")
    print("=" * 55)

    if not _adb_ok(serial):
        print("\nADB cannot talk to this phone.")
        print("Boot MuMu, enable USB debugging, then: adb connect", serial)
        return 1

    if args.apply:
        print("\nBefore fix:\n")
        farm.audit_one_serial(serial, print, farm_index=args.index)
        print("\nApplying fix…\n")
        farm.apply_one_serial(serial, print, farm_index=args.index, patch_vms=True)
        print("\nAfter fix:\n")

    result = farm.audit_one_serial(serial, print, farm_index=args.index)
    if result["clean"]:
        print("\nPASS — no obvious emulator leaks from this PC.")
        return 0
    print("\nStill leaking — cold-boot MuMu phone if VM settings were patched.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
