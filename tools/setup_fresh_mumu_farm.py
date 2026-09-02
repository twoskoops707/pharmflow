#!/usr/bin/env python3
"""
Dev CLI — operators use **CPharmMuMuSetup.exe → GO** (same logic in ``wizard/mumu_farm_ops.py``).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIZ = ROOT / "wizard"
AUTO = ROOT / "automation"
for p in (WIZ, AUTO):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import mumu_farm_ops as farm  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Configure MuMu phones for CPharm (dev — use CPharmMuMuSetup.exe in production)",
    )
    ap.add_argument("--count", type=int, default=3, help="Expected phone count (default 3)")
    ap.add_argument(
        "--fix-mumu-config",
        action="store_true",
        help="Patch MuMu setting.json Tablet → Phone (900×1600)",
    )
    ap.add_argument(
        "--wait-minutes",
        type=float,
        default=0,
        help="Poll adb until enough phones appear (default 0)",
    )
    ap.add_argument(
        "--no-fingerprint",
        action="store_true",
        help="Skip MuMu VM + browser fingerprint hardening",
    )
    ap.add_argument(
        "--extended-playlists",
        action="store_true",
        help="Use rotated ad-variant playlists (build_farm_playlists style)",
    )
    args = ap.parse_args()

    lines: list[str] = []

    def log(msg: str) -> None:
        line = msg if msg.endswith("\n") else msg + "\n"
        lines.append(line)
        sys.stdout.write(line)
        sys.stdout.flush()

    log("CPharm — set up MuMu phones (dev CLI)")
    log("Operators: run CPharmMuMuSetup.exe → GO instead of this script.")
    log("")

    if args.fix_mumu_config:
        n = farm.fix_mumu_tablet_profiles(log)
        log(f"Patched {n} VM profile(s). Cold-boot before continuing.")
    else:
        farm.log_vm_profile_summary(log)

    serials, summary = farm.run_farm_setup(
        log,
        serials=None,
        fix_tablet=not args.fix_mumu_config,
        patch_vms=not args.no_fingerprint,
        configure_browsers=True,
        count=args.count,
        wait_minutes=args.wait_minutes,
    )

    if not serials:
        log("")
        log("No phones found — boot MuMu, enable USB debugging, run CPharmMuMuSetup.exe → GO.")
        return 1

    rec = ROOT / "automation" / "recordings"
    gp = farm.write_groups_config_file(
        serials,
        rec / "groups_config.json",
        extended_ad=args.extended_playlists,
        note="No Google account required — browser-only getdabflow.app via open_url sequences.",
    )
    log(f"  Wrote {gp} ({len(serials)} phone(s))")
    prefs = farm.write_desktop_prefs_file(serials, rec / "desktop_prefs.json")
    log(f"  Wrote {prefs}")

    leaks = summary.get("leaks_total", 0)
    if summary.get("any_vm_patched"):
        log("Cold-boot each MuMu phone once, then run CPharmMuMuSetup.exe → GO again.")
    if leaks:
        log(f"Warning: {leaks} fingerprint leak(s) — cold-boot and GO again.")
        return 1
    log("")
    log("Done. Next: CPharm.exe → Install → Boot → Go.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
