#!/usr/bin/env python3
"""Continue mapping: session notes Skip + home/tab ad slots after a running timer."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from wizard.mumu_farm_ops import MuMuFarmOps

OUT = Path(r"C:\PharmFlow\logs\ad_map")
OUT.mkdir(parents=True, exist_ok=True)
ADB = os.environ.get("PHARMFLOW_ADB") or r"C:\PharmFlow\bundled\adb.exe"


def shot(farm, ser: str, tag: str) -> None:
    remote = f"/sdcard/Download/admap_{tag}.png"
    local = OUT / f"{tag}.png"
    farm.adb.shell(f"screencap -p {remote}", serial=ser)
    subprocess.run([ADB, "-s", ser, "pull", remote, str(local)], check=False, capture_output=True)
    print(f"SHOT {tag} bytes={local.stat().st_size if local.exists() else 0}", flush=True)


def ui_xml(farm, ser: str) -> str:
    farm.adb.shell("uiautomator dump /sdcard/pharmflow_ui.xml", serial=ser)
    return farm.adb.shell("cat /sdcard/pharmflow_ui.xml", serial=ser).stdout or ""


def find_nodes(xml: str, *needles: str):
    hits = []
    for node in xml.split("<node "):
        low = node.lower()
        matched = None
        for n in needles:
            if n.lower() in low:
                matched = n
                break
        if not matched:
            continue
        m = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', node)
        rid = re.search(r'resource-id="([^"]*)"', node)
        txt = re.search(r'text="([^"]*)"', node)
        if not m:
            continue
        x1, y1, x2, y2 = (int(m.group(i)) for i in range(1, 5))
        if x2 <= x1 or y2 <= y1:
            continue
        hits.append(
            {
                "needle": matched,
                "id": rid.group(1) if rid else "",
                "text": (txt.group(1) if txt else "")[:60],
                "bounds": [x1, y1, x2, y2],
                "center": [(x1 + x2) // 2, (y1 + y2) // 2],
            }
        )
    return hits


def dump_ads(label: str, xml: str) -> None:
    ads = find_nodes(xml, "ad-slot", "adsbymantis", "Sponsored", "advertisement")
    print(f"ADS[{label}] count={len(ads)}", flush=True)
    for a in ads:
        print(f"  {a}", flush=True)
    (OUT / f"{label}_ads.txt").write_text("\n".join(str(a) for a in ads), encoding="utf-8")


def main() -> None:
    farm = MuMuFarmOps()
    farm.list_instances()
    ser = farm.get_phone("vm0.gmadoa").adb_serial
    print("serial", ser, flush=True)

    # Assume timer may already be running from prior map; if not, quick restart path
    xml = ui_xml(farm, ser)
    texts = " ".join(re.findall(r'text="([^"]*)"', xml)).upper()
    if "HEAT YOUR BANGER" not in texts and "PAUSE" not in texts:
        print("Timer not active — open flow + start", flush=True)
        from automation.browser_adb import (
            clear_chromium_all_data,
            dismiss_chromium_fre,
            open_url,
            prepare_chromium,
            select_browser,
        )
        from automation.browse_proxy import prepare_browse_session

        inst = farm.get_phone("vm0.gmadoa")
        prepare_browse_session(farm.adb, ser, inst.index)
        clear_chromium_all_data(farm.adb, ser)
        b = select_browser(farm.adb, ser)
        prepare_chromium(farm.adb, ser, force=True)
        open_url(farm.adb, ser, "https://getdabflow.app", browser=b)
        time.sleep(4)
        dismiss_chromium_fre(farm.adb, ser)
        time.sleep(1)
        farm.adb.tap(380, 980, serial=ser)
        time.sleep(4)
        farm.adb.tap(170, 825, serial=ser)
        time.sleep(1.5)
        farm.adb.tap(180, 480, serial=ser)
        time.sleep(2)
        farm.adb.tap(300, 900, serial=ser)
        time.sleep(1)
        farm.adb.swipe(450, 1150, 450, 550, 420, serial=ser)
        time.sleep(0.8)
        farm.adb.tap(449, 1281, serial=ser)
        time.sleep(2)

    shot(farm, ser, "20_timer_running")
    xml = ui_xml(farm, ser)
    dump_ads("20_timer", xml)
    # scroll timer page for more ads
    farm.adb.swipe(450, 1100, 450, 500, 450, serial=ser)
    time.sleep(1)
    shot(farm, ser, "21_timer_scrolled")
    dump_ads("21_timer_scrolled", ui_xml(farm, ser))

    # Wait for cool/session notes — heat was 20s in prior dump; wait ~90s total for notes
    print("Waiting for session notes / timer end (~95s)...", flush=True)
    time.sleep(95)
    shot(farm, ser, "22_after_timer_wait")
    xml = ui_xml(farm, ser)
    (OUT / "22_after_timer.xml").write_text(xml, encoding="utf-8", errors="replace")
    texts = re.findall(r'text="([^"]{1,80})"', xml)
    print("TEXTS", [t for t in texts if t.strip()][:80], flush=True)
    skips = find_nodes(xml, "Skip", "SKIP", "session", "notes", "Done", "Close")
    print("SKIP_CANDIDATES", skips, flush=True)

    # Try skip taps if present
    for s in skips:
        if "skip" in (s["text"] + s["id"] + s["needle"]).lower() and 200 < s["center"][1] < 1500:
            print("TAPPING_SKIP", s, flush=True)
            farm.adb.tap(s["center"][0], s["center"][1], serial=ser)
            time.sleep(2)
            break
    else:
        # provisional center tap
        print("No Skip node — provisional tap 450,1100", flush=True)
        farm.adb.tap(450, 1100, serial=ser)
        time.sleep(2)

    shot(farm, ser, "23_after_notes")
    xml = ui_xml(farm, ser)
    dump_ads("23_home_after_notes", xml)
    # scroll home for bottom ads
    for i in range(4):
        farm.adb.swipe(450, 1150, 450, 500, 450, serial=ser)
        time.sleep(0.9)
        shot(farm, ser, f"24_home_scroll_{i}")
        dump_ads(f"24_home_scroll_{i}", ui_xml(farm, ser))

    # Tab coords from nav — HOME TIMER STATS GLASS SETTINGS
    # Approximate from prior mapping; refine via dump
    xml = ui_xml(farm, ser)
    tabs = find_nodes(xml, "STATS", "GLASS", "SETTINGS", "TIMER", "HOME")
    print("TABS", tabs, flush=True)
    tab_centers = {}
    for t in tabs:
        key = t["text"].upper() or t["needle"].upper()
        if key in ("STATS", "GLASS", "SETTINGS", "TIMER", "HOME") and t["center"][1] > 1400:
            tab_centers[key] = t["center"]
    print("TAB_CENTERS", tab_centers, flush=True)

    for tab in ("STATS", "GLASS", "SETTINGS"):
        if tab not in tab_centers:
            continue
        x, y = tab_centers[tab]
        farm.adb.tap(x, y, serial=ser)
        time.sleep(2)
        shot(farm, ser, f"30_{tab.lower()}")
        dump_ads(f"30_{tab.lower()}", ui_xml(farm, ser))
        farm.adb.swipe(450, 1100, 450, 500, 450, serial=ser)
        time.sleep(1)
        shot(farm, ser, f"31_{tab.lower()}_scrolled")
        dump_ads(f"31_{tab.lower()}_scrolled", ui_xml(farm, ser))

    print("ADS_MAP_DONE", flush=True)


if __name__ == "__main__":
    main()
