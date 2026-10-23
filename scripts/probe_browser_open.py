#!/usr/bin/env python3
"""Probe a browser's open flow on one phone: clear, launch URL, dump UI + screenshot.

Diagnostic only — used to author per-browser onboarding/coordinate steps.

    py -3 scripts/probe_browser_open.py --serial 10.0.2.199:5555 --browser firefox
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from automation.adb_wrapper import AdbWrapper
from automation.browser_adb import browser_info_for_package
from automation.browser_apk_catalog import spec_for_tag
from automation.browser_onboarding import (
    dismiss_duckduckgo_onboarding,
    dismiss_firefox_onboarding,
    seed_duckduckgo_onboarding_complete,
    seed_firefox_onboarding_complete,
)

OUT_DIR = Path(r"C:\PharmFlow\logs\browser_probe")
_NODE_RE = re.compile(
    r'text="([^"]*)"[^>]*?resource-id="([^"]*)"[^>]*?class="([^"]*)"[^>]*?'
    r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"'
)


def dump_ui(adb: AdbWrapper, serial: str) -> str:
    adb.shell("uiautomator dump /sdcard/probe_ui.xml", serial=serial, timeout=20)
    return adb.shell("cat /sdcard/probe_ui.xml", serial=serial, timeout=15).stdout or ""


def summarize(xml: str) -> list[str]:
    rows: list[str] = []
    for text, rid, cls, x1, y1, x2, y2 in _NODE_RE.findall(xml):
        if not text and not rid:
            continue
        cx = (int(x1) + int(x2)) // 2
        cy = (int(y1) + int(y2)) // 2
        rows.append(f"  text={text!r} id={rid} cls={cls.split('.')[-1]} center=({cx},{cy})")
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--serial", required=True)
    ap.add_argument(
        "--browser",
        required=True,
        choices=("chromium", "firefox", "brave", "duckduckgo"),
    )
    ap.add_argument("--url", default="https://getdabflow.app")
    ap.add_argument("--waits", default="3,8,14", help="comma seconds to sample after launch")
    ap.add_argument("--no-clear", action="store_true")
    ap.add_argument("--seed", action="store_true", help="seed onboarding-complete prefs after clear")
    ap.add_argument("--walk", action="store_true", help="tap through onboarding after launch")
    ap.add_argument("--show-prefs", action="store_true", help="print shared_prefs after the run")
    args = ap.parse_args()

    spec = spec_for_tag(args.browser)
    if spec is None:
        print(f"unknown browser {args.browser}", file=sys.stderr)
        return 2
    info = browser_info_for_package(spec.package)
    if info is None:
        print(f"no BrowserInfo for {spec.package}", file=sys.stderr)
        return 2

    adb = AdbWrapper()
    serial = args.serial
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    pkgs = set(adb.pm_list_packages(serial=serial))
    print(f"installed={spec.package in pkgs} package={spec.package} activity={info.activity}")
    if spec.package not in pkgs:
        return 2

    adb.shell(f"am force-stop {spec.package}", serial=serial)
    if not args.no_clear:
        print("pm clear:", (adb.shell(f"pm clear {spec.package}", serial=serial).stdout or "").strip())
    if args.seed and args.browser == "firefox":
        print(f"seed prefs ok={seed_firefox_onboarding_complete(adb, serial, spec.package)}")
    if args.seed and args.browser == "duckduckgo":
        print(f"seed stage ok={seed_duckduckgo_onboarding_complete(adb, serial, spec.package)}")

    cmd = f'am start -a android.intent.action.VIEW -d "{args.url}" -n {info.activity}'
    res = adb.shell(cmd, serial=serial)
    print(f"launch ok={res.ok} out={(res.stdout or res.stderr or '').strip()[:300]}")
    if not res.ok:
        alt = adb.shell(
            f'am start -a android.intent.action.VIEW -d "{args.url}" -p {spec.package}',
            serial=serial,
        )
        print(f"fallback ok={alt.ok} out={(alt.stdout or alt.stderr or '').strip()[:300]}")

    if args.walk:
        time.sleep(3.0)
        if args.browser == "duckduckgo":
            walked = dismiss_duckduckgo_onboarding(adb, serial, dump_ui=dump_ui)
        else:
            walked = dismiss_firefox_onboarding(adb, serial, dump_ui=dump_ui)
        print(f"walked_onboarding={walked}")
        res2 = adb.shell(cmd, serial=serial)
        print(f"re-launch ok={res2.ok}")

    for raw in args.waits.split(","):
        secs = float(raw.strip() or 0)
        time.sleep(secs)
        xml = dump_ui(adb, serial)
        focus = adb.shell("dumpsys window | grep -E 'mCurrentFocus|mFocusedApp'", serial=serial)
        stamp = f"{args.browser}_t{int(secs)}"
        (OUT_DIR / f"{stamp}.xml").write_text(xml, encoding="utf-8", errors="replace")
        adb.shell(f"screencap -p /sdcard/{stamp}.png", serial=serial)
        adb.run("pull", f"/sdcard/{stamp}.png", str(OUT_DIR / f"{stamp}.png"), serial=serial)
        print(f"\n=== t+{secs}s focus={(focus.stdout or '').strip()[:200]}")
        rows = summarize(xml)
        print(f"    nodes={len(rows)} xml_len={len(xml)}")
        for row in rows[:35]:
            print(row)

    if args.show_prefs:
        listing = adb.shell(f"ls /data/data/{spec.package}/shared_prefs", serial=serial)
        print(f"\nshared_prefs: {(listing.stdout or '').strip()}")
        for name in (listing.stdout or "").split():
            body = adb.shell(f"cat /data/data/{spec.package}/shared_prefs/{name}", serial=serial)
            print(f"\n--- {name} ---\n{(body.stdout or '')[:4000]}")

    print(f"\nartifacts -> {OUT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
