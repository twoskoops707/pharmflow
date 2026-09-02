#!/usr/bin/env python3
"""
Dev CLI — write groups_config.json with rotated playlists.

Operators: CPharmMuMuSetup.exe → GO writes the same file automatically.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIZ = ROOT / "wizard"
if str(WIZ) not in sys.path:
    sys.path.insert(0, str(WIZ))

import mumu_farm_ops as farm  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description="Build farm groups (dev CLI)")
    ap.add_argument("--serial", action="append", default=[], dest="serials")
    ap.add_argument("--count", type=int, default=0)
    args = ap.parse_args()

    serials = list(args.serials)
    if not serials:
        serials = farm.order_farm_serials(farm.list_adb_serials())
    if args.count and len(serials) > args.count:
        serials = serials[: args.count]

    if not serials:
        print("No phones — boot MuMu first, or use CPharmMuMuSetup.exe → GO.")
        return 1

    out = ROOT / "automation" / "recordings" / "groups_config.json"
    farm.write_groups_config_file(
        serials,
        out,
        extended_ad=True,
        note="Ad-only playlists: demo TWO + combo variants; every run taps Mantis on Stats.",
    )
    print(f"Wrote {out} for {len(serials)} phone(s):")
    for i, s in enumerate(serials):
        entry = farm.phone_playlist_entry(i, extended_ad=True)
        print(f"  {i + 1}. {s} → {entry['sequence_playlist'][-1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
