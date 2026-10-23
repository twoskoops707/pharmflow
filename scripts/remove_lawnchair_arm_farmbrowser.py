#!/usr/bin/env python3
"""Uninstall Lawnchair + install FarmBrowser on canonical farm phones."""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from automation.config import BROWSER_FARMBROWSER  # noqa: E402
from automation.farm_canonical_phones import CANONICAL_FARM_PHONES, canonical_names_sorted  # noqa: E402
from automation.farm_visit_caps import write_runtime_overrides  # noqa: E402

ADB = Path(r"C:\PharmFlow\bundled\adb.exe")
APK_SRC = Path(r"C:\PharmFlow\farmbrowser\app\build\outputs\apk\debug\app-debug.apk")
APK_CACHE = Path(r"C:\PharmFlow\apks\farmbrowser-debug.apk")
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)
LAWNCHAIR_PKGS = (
    "app.lawnchair",
    "ch.deletescape.lawnchair",
    "com.google.android.apps.nexuslauncher",
)
FB_ACTIVITY = "com.farmbrowser.stealth.browser.BrowserActivity"


def _adb(*args: str, serial: str = "", timeout: float = 25.0) -> str:
    cmd = [str(ADB)]
    if serial:
        cmd.extend(["-s", serial])
    cmd.extend(args)
    try:
        p = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=FLAGS,
        )
        return ((p.stdout or "") + (p.stderr or "")).strip()
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"ERR:{exc}"


def _connect_all() -> None:
    for ser in CANONICAL_FARM_PHONES.values():
        _adb("connect", ser, timeout=12.0)


def _online() -> set[str]:
    out = _adb("devices", timeout=10.0)
    on: set[str] = set()
    for line in out.splitlines()[1:]:
        parts = line.split()
        if len(parts) >= 2 and parts[1] == "device":
            on.add(parts[0])
    return on


def _uninstall_lawnchair(serial: str) -> list[str]:
    fixes: list[str] = []
    for pkg in LAWNCHAIR_PKGS:
        out = _adb("shell", "pm", "uninstall", "--user", "0", pkg, serial=serial, timeout=20.0)
        if "Success" in out or "DELETE_FAILED_INTERNAL_ERROR" not in out:
            fixes.append(f"uninstall {pkg} {serial} {out[:60]}")
        _adb("shell", "pm", "disable-user", "--user", "0", pkg, serial=serial, timeout=12.0)
        _adb("shell", "am", "force-stop", pkg, serial=serial, timeout=8.0)
    return fixes


def _install_farmbrowser(serial: str) -> str:
    apk = APK_CACHE if APK_CACHE.is_file() else APK_SRC
    if not apk.is_file():
        return f"MISSING_APK {apk}"
    out = _adb("install", "-r", "-g", str(apk), serial=serial, timeout=180.0)
    return out[:120]


def _arm_dabflow(serial: str) -> str:
    out = _adb(
        "shell",
        "am",
        "start",
        "-a",
        "android.intent.action.VIEW",
        "-d",
        "https://getdabflow.app/",
        "-n",
        f"{BROWSER_FARMBROWSER}/{FB_ACTIVITY}",
        serial=serial,
        timeout=15.0,
    )
    return out[:100]


def main() -> int:
    if APK_SRC.is_file() and not APK_CACHE.is_file():
        APK_CACHE.parent.mkdir(parents=True, exist_ok=True)
        APK_CACHE.write_bytes(APK_SRC.read_bytes())

    # NOTE: do NOT lock the browser allow-list to farmbrowser — no sequence
    # files are tagged farmbrowser, so that lock empties every pool and the
    # farm worker exits instantly (starving the farm). Allow the browsers that
    # actually have sequences and are installed on the phones.
    write_runtime_overrides(
        {
            "PHARMFLOW_FARM_BROWSERS": "chromium,firefox,brave",
            "PHARMFLOW_FARM_PATH3_BROWSERS": "chromium",
            "PHARMFLOW_FARM_CHROMIUM_ONLY": "0",
        }
    )

    _connect_all()
    time.sleep(2.0)
    online = _online()
    print(f"online={len(online)} canonical={len(CANONICAL_FARM_PHONES)}", flush=True)

    all_fixes: list[str] = []
    for fname in canonical_names_sorted():
        serial = CANONICAL_FARM_PHONES[fname]
        if serial not in online:
            print(f"SKIP_OFFLINE {fname} {serial}", flush=True)
            continue
        all_fixes.extend(_uninstall_lawnchair(serial))
        inst = _install_farmbrowser(serial)
        print(f"INSTALL {fname} {inst}", flush=True)
        arm = _arm_dabflow(serial)
        print(f"ARM {fname} {arm}", flush=True)

    lock = {
        "phones": dict(CANONICAL_FARM_PHONES),
        "tablet": {},
        "inject": {k: 8218 + int(k.split(".")[0][2:]) for k in CANONICAL_FARM_PHONES},
        "note": "farmbrowser_only_no_lawnchair",
    }
    log = Path(r"C:\PharmFlow\logs")
    (log / "ADB_SERIAL_MAP.lock.json").write_text(
        json.dumps(lock, indent=2) + "\n", encoding="utf-8"
    )
    (log / "FARM_RELOAD_FARM.flag").write_text("farmbrowser_only", encoding="utf-8")
    print(f"DONE fixes={len(all_fixes)}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
