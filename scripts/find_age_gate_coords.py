#!/usr/bin/env python3
"""Find working age-gate YES coordinates on live device."""

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


def shot(n: str) -> Path:
    remote = f"/sdcard/Download/{n}.png"
    local = OUT / f"{n}.png"
    sh("shell", "screencap", "-p", remote)
    sh("pull", remote, str(local))
    print(f"shot {n} {local.stat().st_size if local.is_file() else 0}", flush=True)
    return local


def dump_xml() -> str:
    sh("shell", "uiautomator", "dump", "/sdcard/pharmflow_age.xml")
    sh("pull", "/sdcard/pharmflow_age.xml", str(OUT / "age_probe.xml"))
    return (OUT / "age_probe.xml").read_text(encoding="utf-8", errors="replace")


def has_native_21_dialog(xml: str) -> bool:
    return "You must be 21" in xml and "positive_button" in xml


def dismiss_native_21() -> bool:
    xml = dump_xml()
    if not has_native_21_dialog(xml):
        return False
    # OK button center from earlier dump
    sh("shell", "input", "tap", "696", "972")
    time.sleep(1.0)
    return True


def url_bar(xml: str) -> str:
    m = re.search(r'resource-id="[^"]*url_bar[^"]*"[^>]*text="([^"]*)"', xml)
    if m:
        return m.group(1)
    m = re.search(r'text="([^"]*)"[^>]*resource-id="[^"]*url_bar[^"]*"', xml)
    return m.group(1) if m else ""


def main() -> None:
    print("=== fresh Chromium session ===", flush=True)
    sh("shell", "am", "force-stop", "org.chromium.chrome")
    time.sleep(1)
    sh(
        "shell",
        "am",
        "start",
        "-a",
        "android.intent.action.VIEW",
        "-d",
        "https://getdabflow.app",
        "-n",
        "org.chromium.chrome/com.google.android.apps.chrome.Main",
    )
    time.sleep(3.5)
    # Chromium Skip / Stay signed out
    sh("shell", "input", "tap", "450", "1127")
    time.sleep(2)
    shot("fresh_01_after_skip")
    # Site load
    time.sleep(6)
    for _ in range(3):
        if dismiss_native_21():
            print("dismissed native 21 dialog", flush=True)
        else:
            break
    shot("fresh_02_age_gate")
    xml = dump_xml()
    print(f"url={url_bar(xml)!r} native21={has_native_21_dialog(xml)}", flush=True)

    # Probe YES Y positions (HTML age gate — not in uiautomator)
    for y in (980, 1020, 1060, 1100, 1127, 1160, 1200, 1240, 1280, 1320, 1380):
        print(f"TAP YES candidate y={y}", flush=True)
        sh("shell", "input", "tap", "380", str(y))  # left side of modal = YES
        time.sleep(2.0)
        shot(f"fresh_yes_{y}")
        xml = dump_xml()
        if has_native_21_dialog(xml):
            print("  -> underage/native dialog (maybe hit No or blocked)", flush=True)
            dismiss_native_21()
            time.sleep(0.5)
            continue
        print(f"  -> url={url_bar(xml)!r}", flush=True)
        # Home screen usually loses the age-gate-only chrome dialog
        # Take another shot after short wait
        time.sleep(2)
        shot(f"fresh_yes_{y}_settle")
        # If screenshot got much larger / different, likely home
        break

    print("DONE — inspect fresh_yes_*.png", flush=True)


if __name__ == "__main__":
    main()
