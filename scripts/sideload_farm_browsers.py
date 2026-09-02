#!/usr/bin/env python3
"""Download + sideload farm browsers (Chromium / Firefox / Brave) — no Play Store.

Usage::

    py -3 scripts/sideload_farm_browsers.py --download-only
    py -3 scripts/sideload_farm_browsers.py --install
    py -3 scripts/sideload_farm_browsers.py --force --install

APKs land in C:\\CPharm\\apks\\ (override with CPHARM_APK_CACHE).
No Google account / Play Store credentials are used or required.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from automation.adb_wrapper import AdbWrapper
from automation.browser_apk_catalog import (
    BROWSER_APK_SPECS,
    catalog_markdown,
    default_apk_cache_dir,
    download_all_path12_apks,
    ensure_farm_browsers_on_serials,
)


def _live_serials(adb: AdbWrapper) -> list[str]:
    return [s for s, state in adb.devices() if state == "device"]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sideload Path1/2 farm browsers without Google Play Store"
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=None,
        help=f"APK cache (default: {default_apk_cache_dir()})",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download even when cached APKs exist",
    )
    parser.add_argument(
        "--download-only",
        action="store_true",
        help="Only download APKs; do not install",
    )
    parser.add_argument(
        "--install",
        action="store_true",
        help="Install cached/downloaded APKs onto all online ADB devices",
    )
    parser.add_argument(
        "--print-catalog",
        action="store_true",
        help="Print the operator catalog markdown and exit",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit machine-readable JSON summary",
    )
    args = parser.parse_args()

    if args.print_catalog:
        print(catalog_markdown(), end="")
        return 0

    do_install = bool(args.install)
    do_download = bool(args.download_only) or do_install or not (args.download_only or args.install)

    def progress(msg: str) -> None:
        if not args.json:
            print(msg, flush=True)

    cache = args.cache_dir or default_apk_cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    progress(f"APK cache: {cache}")
    progress("Note: no Play Store / no Google credentials — public vendor mirrors only.")

    if do_install:
        adb = AdbWrapper()
        serials = _live_serials(adb)
        if not serials:
            print("ERROR: no online ADB devices", file=sys.stderr)
            return 2
        progress(f"Devices: {serials}")
        result = ensure_farm_browsers_on_serials(
            adb,
            serials,
            cache_dir=cache,
            force_download=args.force,
            progress_cb=progress,
        )
        if args.json:
            print(json.dumps(result, indent=2))
        else:
            print(result.get("note", ""))
            for serial, pkgs in (result.get("per_phone") or {}).items():
                print(f"{serial}: {pkgs}")
            print(f"ok={result.get('ok')}")
        return 0 if result.get("ok") else 1

    # Download-only (default when --install not passed).
    if do_download:
        apks = download_all_path12_apks(
            cache_dir=cache, force=args.force, progress_cb=progress
        )
        summary = {
            "cache": str(cache),
            "apks": {pkg: str(p) for pkg, p in apks.items()},
            "specs": [
                {
                    "tag": s.tag,
                    "package": s.package,
                    "path12": s.path12,
                    "path3": s.path3,
                }
                for s in BROWSER_APK_SPECS
            ],
            "credentials_required": False,
            "play_store": False,
        }
        if args.json:
            print(json.dumps(summary, indent=2))
        else:
            for pkg, path in apks.items():
                print(f"OK {pkg} -> {path} ({path.stat().st_size} bytes)")
            print("Tip: pass --install to sideload onto online phones.")
        return 0 if apks else 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
