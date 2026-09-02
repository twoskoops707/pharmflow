"""Verify Chromium APK is present and installed on every live MuMu phone."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from automation.browser_adb import discover_browsers, is_chromium_available
from automation.config import BROWSER_CHROMIUM
from wizard.browser_setup import chrome_apk_path, download_chrome_public_apk, ensure_browser_via_adb
from wizard.mumu_farm_ops import MuMuFarmOps


def main() -> int:
    apk = chrome_apk_path()
    print(f"apk_path={apk}")
    print(f"apk_exists={apk.is_file()} size={apk.stat().st_size if apk.is_file() else 0}")
    if not apk.is_file() or apk.stat().st_size < 1_000_000:
        print("Downloading Chromium APK…")
        got = download_chrome_public_apk()
        print(f"download_result={got}")
        apk = chrome_apk_path()
        if not apk.is_file() or apk.stat().st_size < 1_000_000:
            print("FAIL: Chromium APK missing after download")
            return 2

    farm = MuMuFarmOps()
    insts = farm.list_instances()
    print(f"phones={[(i.name, i.adb_serial, i.running) for i in insts]}")
    if not insts:
        print("FAIL: no phones / VMs found")
        return 2

    results: list[dict] = []
    for inst in insts:
        serial = inst.adb_serial
        print(f"--- {inst.name} {serial}")
        if not serial:
            results.append({"phone": inst.name, "installed": False, "error": "no serial"})
            continue
        farm.connect_adb(inst.name)
        before = is_chromium_available(farm.adb, serial)
        pkgs_before = [b.package for b in discover_browsers(farm.adb, serial)]
        print(f"before chromium={before} browsers={pkgs_before}")
        info = ensure_browser_via_adb(farm.adb, serial)
        after = is_chromium_available(farm.adb, serial)
        pkgs_after = [b.package for b in discover_browsers(farm.adb, serial)]
        pm = farm.adb.shell(f"pm path {BROWSER_CHROMIUM}", serial=serial)
        stock = farm.adb.shell("pm path com.android.chrome", serial=serial)
        print(f"ensure={info}")
        print(f"after chromium={after} browsers={pkgs_after}")
        print(f"pm_chromium={(pm.stdout or pm.stderr or '').strip()}")
        print(f"pm_chrome={(stock.stdout or stock.stderr or '').strip()}")
        results.append(
            {
                "phone": inst.name,
                "serial": serial,
                "installed": bool(info.get("installed") and after),
                "package": info.get("package"),
                "pm_path": (pm.stdout or "").strip(),
                "error": info.get("error"),
            }
        )

    ok = sum(1 for r in results if r.get("installed"))
    print(f"SUMMARY {ok}/{len(results)}")
    for r in results:
        print(f"RESULT {r}")
    return 0 if ok == len(results) and results else 1


if __name__ == "__main__":
    raise SystemExit(main())
