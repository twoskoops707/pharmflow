#!/usr/bin/env python3
"""
Dev CLI — operators use **PharmFlow → Phones → Set up my phones** or Boot/Launch fingerprint buttons.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# ROOT first so `import automation.*` package imports resolve (dir-only inserts break).
for _p in (str(ROOT), str(ROOT / "wizard"), str(ROOT / "automation")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import mumu_farm_ops as farm  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Fix or audit MuMu fingerprint (dev CLI)")
    ap.add_argument("--serial", action="append", default=[], help="ADB serial (repeatable)")
    ap.add_argument("--apply", action="store_true", help="Patch MuMu VMs + browser disguise")
    ap.add_argument("--no-vm-patch", action="store_true", help="Skip MuMu setting.json")
    args = ap.parse_args()

    serials = args.serial or farm.order_farm_serials(farm.list_adb_serials())
    print("PharmFlow — phone fingerprint fix / audit (dev CLI)")
    print("Operators: PharmFlow → Phones → Set up my phones")
    print("=" * 50)

    if not serials:
        print("\nNo phones found. Boot MuMu and enable USB debugging.")
        return 1

    print(f"\nPhones found: {len(serials)}")
    for i, s in enumerate(serials):
        print(f"  {i + 1}. {s}")

    if args.apply:
        print("\nApplying fixes…\n")
        summary = farm.apply_fingerprint_all(
            serials,
            print,
            patch_vms=not args.no_vm_patch,
        )
        print("\n" + "=" * 50)
        if summary.get("any_vm_patched"):
            print("NEXT: fully STOP then START each MuMu phone (one time).")
        if summary.get("all_clean"):
            print("All phones look clean from here.")
            return 0
        print(f"Still {summary.get('leaks_total', 0)} leak(s) — cold-boot phones after VM patch.")
        return 1

    print("\nAudit only (no changes):\n")
    summary = farm.audit_fingerprint_all(serials, print)
    if summary.get("all_clean"):
        print("\nAll phones look OK.")
        return 0
    print(f"\n{summary.get('phones_with_leaks', 0)} phone(s) still leak.")
    print("Fix: PharmFlow → Phones → Set up my phones")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
