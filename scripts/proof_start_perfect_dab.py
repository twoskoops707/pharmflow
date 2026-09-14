#!/usr/bin/env python3
"""One-phone live proof: Path1A sequence must start the real Perfect Dab timer."""

from __future__ import annotations

import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ["PHARMFLOW_ALLOW_SEQUENCE_RUNS"] = "1"
os.environ["PHARMFLOW_SKIP_MANTIS_PATCH"] = "1"
os.environ["PHARMFLOW_EMULATOR_AD_FILL_WAIT"] = "0"
os.environ.setdefault("PHARMFLOW_BROWSE_PROXY_MODE", "scramble")

from automation.sequence_runner import Sequence, SequenceRunner
from wizard.mumu_farm_ops import MuMuFarmOps

OUT = Path(r"C:\PharmFlow\logs\ad_map")
OUT.mkdir(parents=True, exist_ok=True)
ADB = os.environ.get("PHARMFLOW_ADB") or r"C:\PharmFlow\bundled\adb.exe"
SEQ = Path(
    r"C:\PharmFlow\automation\recordings\sequences\base\quartz\quartz_shatter_butane_p1a_complete.json"
)


def shot(farm, ser: str, tag: str) -> None:
    remote = f"/sdcard/Download/proof_{tag}.png"
    local = OUT / f"proof_{tag}.png"
    farm.adb.shell(f"screencap -p {remote}", serial=ser)
    subprocess.run([ADB, "-s", ser, "pull", remote, str(local)], check=False, capture_output=True)
    print(f"SHOT {tag} bytes={local.stat().st_size if local.exists() else 0}", flush=True)


def main() -> int:
    farm = MuMuFarmOps()
    farm.list_instances()
    phone = "vm0.gmadoa"
    inst = farm.get_phone(phone)
    ser = inst.adb_serial
    print("serial", ser, "seq", SEQ.name, flush=True)

    seq = Sequence.from_json(SEQ)
    seq.phone = phone
    runner = SequenceRunner(farm)

    # Run only through Start Perfect Dab (stop before long timer wait)
    cut = []
    for step in seq.steps:
        cut.append(step)
        if "Start Perfect Dab timer" in (step.description or ""):
            break
    seq.steps = cut
    print(f"Running {len(cut)} steps through Start Perfect Dab...", flush=True)
    report = runner.run(seq)
    print("runner_success", report.get("success"), "error", report.get("error"), flush=True)
    time.sleep(2.5)
    shot(farm, ser, "after_start")
    farm.adb.shell("uiautomator dump /sdcard/pharmflow_ui.xml", serial=ser)
    xml = farm.adb.shell("cat /sdcard/pharmflow_ui.xml", serial=ser).stdout or ""
    texts = " | ".join(re.findall(r'text="([^"]{1,80})"', xml))
    print("TEXTS_SNIP", texts[:500], flush=True)
    ok = ("HEAT YOUR BANGER" in texts.upper()) or ("PAUSE" in texts.upper()) or ("PERFECT AWAITS" in texts.upper())
    if not ok:
        # also accept countdown digit near timer
        ok = ("CURRENT SESSION" in texts.upper()) or ("Reset" in texts)
    print("TIMER_STARTED" if ok else "TIMER_NOT_STARTED", flush=True)
    return 0 if ok and report.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
