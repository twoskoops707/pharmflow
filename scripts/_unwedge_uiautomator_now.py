#!/usr/bin/env python3
"""Clear wedged uiautomator / hung ADB shells causing mass tap/swipe FAILs.

Does NOT kill MuMu. Does NOT adb kill-server.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from automation.adb_wrapper import AdbWrapper
from automation.farm_money_monitor import cull_hung_adb

ADB = Path(r"C:\PharmFlow\bundled\adb.exe")
FLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _run(cmd: list[str], timeout: float = 12) -> tuple[int, str]:
    try:
        r = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            creationflags=FLAGS,
        )
        return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()
    except Exception as exc:
        return 1, str(exc)


def _kill_dump_fighters() -> list[str]:
    """Stop helpers that compete with farm for uiautomator dumps."""
    fixes: list[str] = []
    try:
        import psutil
    except ImportError:
        return fixes
    for proc in psutil.process_iter(["pid", "cmdline"]):
        try:
            cmd = " ".join(proc.info.get("cmdline") or [])
            if "watch_bottom_ads" in cmd or "farm_fail_review" in cmd:
                pid = int(proc.info["pid"])
                proc.kill()
                fixes.append(f"killed pid={pid} {'watch' if 'watch_bottom' in cmd else 'fail_review'}")
        except Exception:
            continue
    return fixes


def main() -> int:
    print("cull", cull_hung_adb(max_kill=40, min_age_s=25), flush=True)
    print("fighters", _kill_dump_fighters(), flush=True)

    _, out = _run([str(ADB), "devices"], timeout=20)
    live = [ln.split()[0] for ln in out.splitlines() if "\tdevice" in ln]
    print(f"LIVE {len(live)} {live}", flush=True)
    if not live:
        return 3

    adb = AdbWrapper()
    for ser in live:
        _run([str(ADB), "-s", ser, "shell", "pkill", "-f", "uiautomator"], timeout=8)
        _run(
            [
                str(ADB),
                "-s",
                ser,
                "shell",
                "rm",
                "-f",
                "/sdcard/pharmflow_ui.xml",
                "/sdcard/pharmflow_overlay.xml",
                "/sdcard/pharmflow_ad_pick.xml",
            ],
            timeout=8,
        )
        t0 = time.time()
        code, ping = _run([str(ADB), "-s", ser, "shell", "echo", "ping"], timeout=8)
        print(f"ADB {ser} code={code} {(time.time() - t0):.2f}s {ping!r}", flush=True)
        try:
            adb.shell(
                "am start -a android.intent.action.VIEW -d https://getdabflow.app "
                "-n org.chromium.chrome/com.google.android.apps.chrome.Main",
                serial=ser,
            )
        except Exception as exc:
            print(f"chrome_fail {ser} {exc}", flush=True)

    # Flag farm to keep going — do not full restart (would re-wedge on isolation storm)
    Path(r"C:\PharmFlow\logs").mkdir(parents=True, exist_ok=True)
    print("DONE_UNWEDGE", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
