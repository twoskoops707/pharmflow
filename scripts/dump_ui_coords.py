#!/usr/bin/env python3
"""Dump clickable nodes from current UI hierarchy."""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

SERIAL = sys.argv[1] if len(sys.argv) > 1 else "10.0.2.132:5555"
OUT = Path(r"C:\CPharm\logs\ad_proof\age_now.xml")


def adb(*args: str) -> str:
    r = subprocess.run(["adb", "-s", SERIAL, *args], capture_output=True, text=True, errors="replace")
    return (r.stdout or "") + (r.stderr or "")


def main() -> None:
    adb("shell", "uiautomator", "dump", "/sdcard/cpharm_age.xml")
    adb("pull", "/sdcard/cpharm_age.xml", str(OUT))
    xml = OUT.read_text(encoding="utf-8", errors="replace")
    print(f"xml bytes={len(xml)}")
    pat = re.compile(
        r'(?:text|content-desc)="([^"]*)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"'
        r'|bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*(?:text|content-desc)="([^"]*)"'
    )
    # Simpler: find all nodes with text and bounds
    for m in re.finditer(
        r'text="([^"]*)"[^>]*resource-id="([^"]*)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"',
        xml,
    ):
        text, rid, x1, y1, x2, y2 = m.groups()
        if not text.strip() and "ad" not in rid.lower():
            continue
        cx = (int(x1) + int(x2)) // 2
        cy = (int(y1) + int(y2)) // 2
        print(f"text={text[:50]!r:52} id={rid[-40:]:40} center=({cx},{cy})")

    print("--- all non-empty text ---")
    for m in re.finditer(r'text="([^"]+)"[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', xml):
        text, x1, y1, x2, y2 = m.groups()
        cx = (int(x1) + int(x2)) // 2
        cy = (int(y1) + int(y2)) // 2
        print(f"  {text[:70]!r:72} ({cx},{cy})")


if __name__ == "__main__":
    main()
