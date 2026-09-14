#!/usr/bin/env python3
"""
Dev CLI — download Chromium APK for sideload.

Operators: PharmFlow phone setup auto-downloads when no browser is found.
"""
from __future__ import annotations

import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# ROOT must be on path: mumu_farm_ops imports automation.* as a package.
for _p in (str(ROOT), str(ROOT / "wizard"), str(ROOT / "automation")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import mumu_farm_ops as farm  # noqa: E402


def main() -> int:
    def log(msg: str) -> None:
        print(msg)

    print("Operators: PharmFlow phone setup downloads Chromium automatically.")
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
