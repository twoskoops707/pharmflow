"""One-phone FRE → age → selections → Start Perfect Dab proof with screenshots."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from automation.browser_adb import (
    clear_chromium_all_data,
    dismiss_chromium_fre,
    open_url,
    prepare_chromium,
    select_browser,
)
from automation.browse_proxy import prepare_browse_session
from automation.dabflow_overlays import ensure_start_perfect_dab
from wizard.mumu_farm_ops import MuMuFarmOps

OUT = Path(r"C:\CPharm\logs\proof_fix")
ADB_BIN = os.environ.get("CPHARM_ADB") or r"C:\CPharm\bundled\adb.exe"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    farm = MuMuFarmOps()
    farm.list_instances()
    inst = farm.get_phone("vm0.gmadoa")
    ser = inst.adb_serial
    print("serial", ser, flush=True)

    def shot(tag: str) -> Path:
        remote = f"/sdcard/Download/proof_{tag}.png"
        local = OUT / f"{tag}.png"
        farm.adb.shell(f"screencap -p {remote}", serial=ser)
        subprocess.run(
            [ADB_BIN, "-s", ser, "pull", remote, str(local)],
            check=False,
            capture_output=True,
        )
        print(f"SHOT {tag} bytes={local.stat().st_size if local.exists() else 0}", flush=True)
        return local

    def dump(tag: str) -> str:
        farm.adb.shell("uiautomator dump /sdcard/cpharm_ui.xml", serial=ser)
        xml = farm.adb.shell("cat /sdcard/cpharm_ui.xml", serial=ser).stdout or ""
        (OUT / f"{tag}.xml").write_text(xml, encoding="utf-8", errors="replace")
        texts = re.findall(r'text="([^"]{2,80})"', xml)
        keys = (
            "start",
            "perfect",
            "dab",
            "skip",
            "yes",
            "21",
            "quartz",
            "heat",
            "pause",
            "stay",
            "google",
            "help",
            "manage",
            "ceramic",
            "budder",
        )
        interesting = [t for t in texts if any(k in t.lower() for k in keys)]
        print(f"DUMP {tag} interesting={interesting[:30]}", flush=True)
        return xml

    prepare_browse_session(farm.adb, ser, inst.index)
    clear_chromium_all_data(farm.adb, ser)
    browser = select_browser(farm.adb, ser)
    prepare_chromium(farm.adb, ser, force=True)

    farm.adb.shell(
        "monkey -p org.chromium.chrome -c android.intent.category.LAUNCHER 1",
        serial=ser,
    )
    time.sleep(2.0)
    shot("01_fre")
    xml = dump("01_fre")
    print("FRE visible", "fre_pager" in xml or "Stay signed out" in xml, flush=True)
    fre_ok = dismiss_chromium_fre(farm.adb, ser)
    print("FRE dismiss", fre_ok, flush=True)
    time.sleep(0.8)
    shot("02_after_fre")
    dump("02_after_fre")

    print("open", open_url(farm.adb, ser, "https://getdabflow.app", browser=browser), flush=True)
    time.sleep(2.5)
    shot("03_after_open")
    xml = dump("03_after_open")
    on_google = "google.com" in xml.lower() and "getdabflow" not in xml.lower()
    print("on_google", on_google, flush=True)

    farm.adb.tap(380, 980, serial=ser)
    time.sleep(1.5)
    shot("04_after_age")
    dump("04_after_age")

    farm.adb.tap(729, 825, serial=ser)
    time.sleep(0.6)
    farm.adb.tap(180, 720, serial=ser)
    time.sleep(0.7)
    farm.adb.tap(300, 900, serial=ser)
    time.sleep(0.5)
    shot("05_after_selections")
    dump("05_after_selections")

    report = ensure_start_perfect_dab(farm.adb, ser, fallback_xy=(449, 1281))
    print("START_REPORT", json.dumps(report), flush=True)
    shot("06_after_start")
    xml = dump("06_after_start")
    timer_ok = bool(report.get("timer_started")) or any(
        t in xml for t in ("HEAT YOUR BANGER", "Pause", "PAUSE")
    )
    print("TIMER_OK", timer_ok, flush=True)
    summary = {
        "fre_ok": fre_ok,
        "on_google_after_open": on_google,
        "start": report,
        "timer_ok": timer_ok,
    }
    (OUT / "proof_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("DONE", flush=True)
    return 0 if timer_ok and fre_ok and not on_google else 1


if __name__ == "__main__":
    raise SystemExit(main())
