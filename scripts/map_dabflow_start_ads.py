#!/usr/bin/env python3
"""Live-map Start Perfect Dab + home ad slots on vm0. Farm must stay stopped."""

from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

from automation.browser_adb import (
    clear_chromium_all_data,
    dismiss_chromium_fre,
    open_url,
    prepare_chromium,
    select_browser,
)
from automation.browse_proxy import prepare_browse_session
from wizard.mumu_farm_ops import MuMuFarmOps

OUT = Path(r"C:\PharmFlow\logs\ad_map")
OUT.mkdir(parents=True, exist_ok=True)
ADB = os.environ.get("PHARMFLOW_ADB") or r"C:\PharmFlow\bundled\adb.exe"


def shot(farm, ser: str, tag: str) -> Path:
    remote = f"/sdcard/Download/admap_{tag}.png"
    local = OUT / f"{tag}.png"
    farm.adb.shell(f"screencap -p {remote}", serial=ser)
    subprocess.run([ADB, "-s", ser, "pull", remote, str(local)], check=False, capture_output=True)
    print(f"SHOT {tag} bytes={local.stat().st_size if local.exists() else 0}", flush=True)
    return local


def ui_xml(farm, ser: str) -> str:
    farm.adb.shell("uiautomator dump /sdcard/pharmflow_ui.xml", serial=ser)
    return farm.adb.shell("cat /sdcard/pharmflow_ui.xml", serial=ser).stdout or ""


def find_bounds(xml: str, *needles: str) -> list[tuple[str, int, int, int, int, int, int]]:
    """Return (needle, x1,y1,x2,y2,cx,cy) for nodes whose text/id/desc matches."""
    hits: list[tuple[str, int, int, int, int, int, int]] = []
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
        if not m:
            continue
        x1, y1, x2, y2 = (int(m.group(i)) for i in range(1, 5))
        hits.append((matched, x1, y1, x2, y2, (x1 + x2) // 2, (y1 + y2) // 2))
    return hits


def main() -> None:
    farm = MuMuFarmOps()
    farm.list_instances()
    inst = farm.get_phone("vm0.gmadoa")
    ser = inst.adb_serial
    print("serial", ser, flush=True)

    prepare_browse_session(farm.adb, ser, inst.index)
    clear_chromium_all_data(farm.adb, ser)
    browser = select_browser(farm.adb, ser)
    prepare_chromium(farm.adb, ser, force=True)
    print("open", open_url(farm.adb, ser, "https://getdabflow.app", browser=browser), flush=True)
    time.sleep(4)
    dismiss_chromium_fre(farm.adb, ser)
    time.sleep(1.5)
    farm.adb.tap(380, 980, serial=ser)
    time.sleep(5)
    # quartz / shatter / butane
    farm.adb.tap(170, 825, serial=ser)
    time.sleep(2.0)
    farm.adb.tap(180, 480, serial=ser)
    time.sleep(2.5)
    farm.adb.tap(300, 900, serial=ser)
    time.sleep(1.5)
    shot(farm, ser, "10_before_scroll")

    start_hit = None
    for i in range(8):
        xml = ui_xml(farm, ser)
        hits = find_bounds(xml, "start-dab-btn", "START PERFECT DAB")
        print(f"scroll_pass={i} start_hits={hits}", flush=True)
        visible = [h for h in hits if h[4] > h[2] and h[3] > 100 and h[2] < 1450]
        if visible:
            # Prefer a hit with real height in the content area
            start_hit = max(visible, key=lambda h: (h[4] - h[2]) * (h[3] - h[1]))
            if start_hit[2] > 200 and start_hit[4] < 1500:
                break
        # Finger up = content moves up / reveal lower content
        farm.adb.swipe(450, 1150, 450, 550, 420, serial=ser)
        time.sleep(0.7)
        shot(farm, ser, f"11_scroll_{i}")

    xml = ui_xml(farm, ser)
    (OUT / "11_final.xml").write_text(xml, encoding="utf-8", errors="replace")
    hits = find_bounds(xml, "start-dab-btn", "START PERFECT DAB", "ad-slot", "adsbymantis")
    print("FINAL_HITS", hits, flush=True)
    shot(farm, ser, "12_ready_to_start")

    if not start_hit:
        # fallback: any non-zero start bounds
        cand = [h for h in hits if "start" in h[0].lower() and h[3] > h[1]]
        start_hit = cand[0] if cand else None

    if not start_hit:
        print("FAIL: could not locate Start Perfect Dab bounds", flush=True)
        return

    cx, cy = start_hit[5], start_hit[6]
    print(f"TAPPING_START {cx},{cy} bounds={start_hit[1:5]}", flush=True)
    farm.adb.tap(cx, cy, serial=ser)
    time.sleep(3.5)
    shot(farm, ser, "13_after_start")
    xml2 = ui_xml(farm, ser)
    (OUT / "13_after_start.xml").write_text(xml2, encoding="utf-8", errors="replace")
    texts = re.findall(r'text="([^"]{1,80})"', xml2)
    print("AFTER_START_TEXTS", [t for t in texts if t.strip()][:60], flush=True)

    # If timer running, wait a bit then continue to session notes / home ads later
    print("MAP_DONE", flush=True)


if __name__ == "__main__":
    main()
