#!/usr/bin/env python3
"""
Dev CLI — download Chromium APK for sideload.

Operators: CPharmMuMuSetup.exe → GO auto-downloads when no browser is found.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIZ = ROOT / "wizard"
if str(WIZ) not in sys.path:
    sys.path.insert(0, str(WIZ))

import mumu_farm_ops as farm  # noqa: E402


def main() -> int:
    def log(msg: str) -> None:
        print(msg)

    print("Operators: CPharmMuMuSetup.exe → GO downloads Chromium automatically.")
    apk = farm.download_chromium_apk(log)
    if not apk or not apk.is_file():
        print("Download failed.", file=sys.stderr)
        return 1
    personal = ROOT / "user-downloads"
    personal.mkdir(parents=True, exist_ok=True)
    copy = personal / "ChromePublic.apk"
    if copy.resolve() != apk.resolve():
        shutil.copy2(apk, copy)
        log(f"Personal copy: {copy}")
    log("")
    log(f"Install: adb install -r \"{apk}\"")
    log("Package id: org.chromium.chrome")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
