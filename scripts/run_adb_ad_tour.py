#!/usr/bin/env python3
"""
Direct ADB runner — spoof identity + multi-tab Mantis ad tour.

No PharmFlow.exe / dashboard required. Uses MuMu ADB + PharmFlow automation modules.

  $env:PHARMFLOW_ALLOW_SEQUENCE_RUNS='1'
  py scripts/run_adb_ad_tour.py --phone vm0.gmadoa
  py scripts/run_adb_ad_tour.py --all-online
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("PHARMFLOW_ALLOW_SEQUENCE_RUNS", "1")
os.environ.setdefault("PHARMFLOW_EMULATOR_AD_FILL_WAIT", "4")

from automation.browser_farm import browse_url, clear_browser_before_sequence, scramble_for_sequence
from automation.dabflow_overlays import back_from_advertiser, bypass_splash_and_age_gate
from automation.emulator_ad_mode import chromium_url_bar_text, maybe_fallback_ad_open_url, still_on_dabflow
from automation.browser_adb import open_url as adb_open_url
from wizard.mumu_farm_ops import MuMuFarmOps

OUT = Path(r"C:\PharmFlow\logs\ad_proof")
OUT.mkdir(parents=True, exist_ok=True)

# Live-calibrated 900x1600 nav + ad taps
TABS = {
    "home": (90, 1555),
    "timer": (270, 1555),
    "stats": (449, 1555),
    "glass": (629, 1555),
    "settings": (809, 1555),
}
HOME_AD_SCROLL = (450, 1100, 450, 400, 700)
HOME_AD_TAP = (450, 500)
TAB_AD_SCROLL = (450, 1100, 450, 500, 650)
TAB_AD_TAP = (450, 700)


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def shot(farm: MuMuFarmOps, serial: str, name: str) -> Path:
    remote = f"/sdcard/Download/{name}.png"
    local = OUT / f"{name}.png"
    farm.adb.shell(f"screencap -p {remote}", serial=serial)
    farm.adb.run("pull", remote, str(local), serial=serial)
    print(f"  SHOT {name} ({local.stat().st_size if local.is_file() else 0}b)", flush=True)
    return local


def tap_ad_and_return(farm: MuMuFarmOps, serial: str, label: str, xy: tuple[int, int]) -> dict:
    x, y = xy
    print(f"  TAP AD [{label}] ({x},{y})", flush=True)
    farm.adb.tap(x, y, serial=serial)
    time.sleep(3.0)
    url = chromium_url_bar_text(farm.adb, serial)
    left = not still_on_dabflow(farm.adb, serial)
    fallback = False
    if not left:
        fallback = maybe_fallback_ad_open_url(
            farm.adb,
            serial,
            f"ad_{label}",
            open_url_fn=lambda s, u: adb_open_url(farm.adb, s, u),
        )
        time.sleep(2.5)
        url = chromium_url_bar_text(farm.adb, serial)
        left = not still_on_dabflow(farm.adb, serial)
    shot(farm, serial, f"tour_{label}_after_tap")
    print(f"  -> url={url[:70]!r} left_dabflow={left} fallback={fallback}", flush=True)
    if left or fallback:
        back_from_advertiser(farm.adb, serial)
        # Ensure we're on dabflow home-ish
        time.sleep(1.0)
        if "getdabflow" not in chromium_url_bar_text(farm.adb, serial).lower():
            browse_url(farm, farm._last_phone if hasattr(farm, "_last_phone") else "vm0.gmadoa", "https://getdabflow.app")
            time.sleep(2)
            bypass_splash_and_age_gate(farm.adb, serial)
    return {"label": label, "url": url, "left": left, "fallback": fallback}


def run_tour(farm: MuMuFarmOps, phone: str) -> dict:
    farm.list_instances()
    inst = farm.get_phone(phone)
    if not inst or not inst.adb_serial:
        return {"phone": phone, "success": False, "error": "phone not found"}
    serial = inst.adb_serial
    if not farm.adb.wait_for_device(serial, timeout=20.0):
        return {"phone": phone, "success": False, "error": f"offline {serial}"}

    print(f"\n=== AD TOUR {phone} serial={serial} ===", flush=True)
    print("SPOOF: clear cookies + scramble identity", flush=True)
    clear_browser_before_sequence(farm, phone)
    scramble_for_sequence(farm, phone)

    print("OPEN getdabflow.app", flush=True)
    ok = browse_url(farm, phone, "https://getdabflow.app")
    if not ok:
        return {"phone": phone, "success": False, "error": "open_url failed"}
    time.sleep(2.0)

    print("BYPASS splash + age gate", flush=True)
    bypass = bypass_splash_and_age_gate(farm.adb, serial)
    print(f"  bypass={bypass}", flush=True)
    shot(farm, serial, f"tour_{phone}_01_home")

    results: list[dict] = []

    # --- Home Mantis ads ---
    print("HOME: wait for Mantis fill + scroll + tap", flush=True)
    time.sleep(12.0)
    x1, y1, x2, y2, dur = HOME_AD_SCROLL
    farm.adb.swipe(x1, y1, x2, y2, dur, serial=serial)
    time.sleep(1.2)
    farm.adb.swipe(x1, y1, x2, y2, dur, serial=serial)
    time.sleep(1.0)
    shot(farm, serial, f"tour_{phone}_02_home_ads")
    results.append(tap_ad_and_return(farm, serial, "home", HOME_AD_TAP))

    # Ensure on home tab
    farm.adb.tap(*TABS["home"], serial=serial)
    time.sleep(1.0)

    # --- Other tabs: timer, stats, glass, settings ---
    for tab in ("timer", "stats", "glass", "settings"):
        print(f"TAB: {tab}", flush=True)
        farm.adb.tap(*TABS[tab], serial=serial)
        time.sleep(2.0)
        time.sleep(10.0)  # Mantis fill
        farm.adb.swipe(*TAB_AD_SCROLL[:4], TAB_AD_SCROLL[4], serial=serial)
        time.sleep(1.0)
        shot(farm, serial, f"tour_{phone}_tab_{tab}")
        results.append(tap_ad_and_return(farm, serial, tab, TAB_AD_TAP))
        # Return to dabflow if needed then continue
        farm.adb.tap(*TABS["home"], serial=serial)
        time.sleep(0.8)

    shot(farm, serial, f"tour_{phone}_99_done")
    summary = {
        "time": _utc(),
        "phone": phone,
        "serial": serial,
        "success": True,
        "bypass": bypass,
        "ads": results,
        "ads_left_site": sum(1 for r in results if r.get("left") or r.get("fallback")),
    }
    (OUT / f"tour_{phone}_report.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"DONE {phone}: {summary['ads_left_site']}/{len(results)} ad engagements", flush=True)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Direct ADB spoof + multi-tab ad tour")
    parser.add_argument("--phone", default="vm0.gmadoa")
    parser.add_argument("--all-online", action="store_true", help="Run on every connected phone")
    args = parser.parse_args()

    farm = MuMuFarmOps()
    farm.list_instances()
    phones: list[str] = []
    if args.all_online:
        for inst in farm.list_instances():
            st = farm.get_phone_status(inst.name)
            if st.get("connected"):
                phones.append(inst.name)
    else:
        phones = [args.phone]

    if not phones:
        print("ERROR: no online phones — start MuMu VMs / fix ADB")
        return 1

    print(f"Phones: {phones}")
    print("NOTE: PharmFlow.exe not required — this is pure ADB + Python automation")
    reports = [run_tour(farm, p) for p in phones]
    print(json.dumps(reports, indent=2))
    return 0 if all(r.get("success") for r in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
