#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import time
from datetime import datetime
from pathlib import Path

ADB = r"C:\PharmFlow\bundled\adb.exe"
# All 6 MuMu guests — VM-index inject map.
PHONES = (
    ("vm0", "10.0.2.222:5555", 8218),
    ("vm1", "10.0.2.171:5555", 8219),
    ("vm2", "10.0.2.27:5555", 8220),
    ("vm3", "10.0.2.156:5555", 8221),
    ("vm4", "10.0.2.155:5555", 8222),
    ("vm5", "10.0.2.100:5555", 8223),
)


def sh(serial: str, *args: str, timeout: float = 12.0) -> str:
    try:
        p = subprocess.run(
            [ADB, "-s", serial, *args],
            capture_output=True,
            text=True,
            timeout=timeout,
            encoding="utf-8",
            errors="replace",
        )
        return ((p.stdout or "") + (p.stderr or "")).strip()
    except Exception as e:
        return f"ERR:{e}"


def main() -> None:
    for name, serial, port in PHONES:
        want = f"127.0.0.1:{port}"
        sh(serial, "shell", "settings", "put", "global", "http_proxy", want, timeout=6.0)
        if name != "vm5":
            sh(
                serial,
                "shell",
                "am",
                "start",
                "--activity-brought-to-front",
                "-n",
                "org.chromium.chrome/com.google.android.apps.chrome.Main",
                "-a",
                "android.intent.action.VIEW",
                "-d",
                "https://getdabflow.app/",
                timeout=15.0,
            )
            sh(serial, "shell", "input", "tap", "540", "1020", timeout=4.0)
            sh(serial, "shell", "input", "swipe", "540", "1450", "540", "350", "300", timeout=5.0)
        print(name, sh(serial, "shell", "settings", "get", "global", "http_proxy", timeout=5.0))

    # import watch once
    import sys

    sys.path.insert(0, r"C:\Users\jsmil\PharmFlow")
    from scripts.watch_bottom_ads import run_once

    payload = run_once(fix=True)
    print(
        "BOTTOM_ADS_VISIBLE=" + ("yes" if payload.get("bottom_ads_visible") else "NO"),
        f"ok={payload.get('bottom_ads_chromium_ok')}/{payload.get('bottom_ads_chromium_total')}",
        f"fg={payload.get('chromium_fg')}",
        flush=True,
    )
    lines = [
        f"FARM_HONEST_NOW ads {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        f"BOTTOM_ADS_VISIBLE={'yes' if payload.get('bottom_ads_visible') else 'NO'}",
        f"ok={payload.get('bottom_ads_chromium_ok')}/{payload.get('bottom_ads_chromium_total')} "
        f"chromium_fg={payload.get('chromium_fg')} actives={payload.get('actives')}",
        f"inject_listen=yes fixes={len(payload.get('auto_fixes') or [])}",
    ]
    for p in payload.get("phones") or []:
        lines.append(
            f"  {p.get('name')}: ads={p.get('adsbymantis')} fat={p.get('fat_bounds')} "
            f"proxy={p.get('proxy')} fg={p.get('fg')} ok={p.get('ok')} note={p.get('note')}"
        )
    Path(r"C:\PharmFlow\logs\FARM_HONEST_NOW.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines), flush=True)


if __name__ == "__main__":
    main()
