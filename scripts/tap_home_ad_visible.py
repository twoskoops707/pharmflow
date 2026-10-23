#!/usr/bin/env python3
"""Scroll DabFlow home until ad-slot-1 is tappable, then tap and screenshot."""

from __future__ import annotations

import re
import subprocess
import time
from pathlib import Path

S = "10.0.2.132:5555"
OUT = Path(r"C:\PharmFlow\logs\ad_proof")
OUT.mkdir(parents=True, exist_ok=True)


def sh(*a: str) -> str:
    r = subprocess.run(["adb", "-s", S, *a], capture_output=True, text=True, errors="replace")
    return (r.stdout or "") + (r.stderr or "")


def shot(n: str) -> None:
    remote = f"/sdcard/Download/{n}.png"
    local = OUT / f"{n}.png"
    sh("shell", "screencap", "-p", remote)
    sh("pull", remote, str(local))
    print(f"shot {n} {local.stat().st_size if local.is_file() else 0}", flush=True)


def dump() -> str:
    sh("shell", "uiautomator", "dump", "/sdcard/pharmflow_age.xml")
    sh("pull", "/sdcard/pharmflow_age.xml", str(OUT / "age_probe.xml"))
    return (OUT / "age_probe.xml").read_text(encoding="utf-8", errors="replace")


def find_ad(xml: str) -> tuple[int, int, tuple[int, int, int, int]] | None:
    for pat in (
        r'resource-id="ad-slot-1"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
        r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*resource-id="ad-slot-1"',
    ):
        m = re.search(pat, xml)
        if m:
            x1, y1, x2, y2 = map(int, m.groups())
            return (x1 + x2) // 2, (y1 + y2) // 2, (x1, y1, x2, y2)
    return None


def url_bar(xml: str) -> str:
    m = re.search(r'resource-id="[^"]*url_bar[^"]*"[^>]*text="([^"]*)"', xml)
    return m.group(1) if m else ""


def main() -> None:
    print("=== reveal + tap home Mantis ad ===", flush=True)
    ad = None
    for i in range(4):
        sh("shell", "input", "swipe", "450", "1100", "450", "450", "650")
        time.sleep(1.3)
        xml = dump()
        ad = find_ad(xml)
        print(f"scroll {i} ad={ad}", flush=True)
        shot(f"ad_reveal_{i}")
        if ad and 200 < ad[1] < 1450:
            print("AD VISIBLE ABOVE NAV", ad, flush=True)
            break

    xml = dump()
    ad = find_ad(xml)
    print("final ad", ad, flush=True)
    shot("ad_visible_now")
    if not ad:
        print("FAIL: ad-slot-1 not found", flush=True)
        return
    x, y, bounds = ad
    # Prefer tapping slightly above nav if slot overlaps
    tap_y = min(y, 1420)
    print(f"TAPPING AD ({x},{tap_y}) bounds={bounds}", flush=True)
    sh("shell", "input", "tap", str(x), str(tap_y))
    time.sleep(4.5)
    shot("ad_tapped_result")
    xml = dump()
    print(f"URL={url_bar(xml)!r}", flush=True)
    print("LOOK AT MUMU — should show advertiser or stay on dabflow", flush=True)


if __name__ == "__main__":
    main()
