#!/usr/bin/env python3
"""Clear all emulators, then run one Path2 + one Path3 side-by-side for visual check."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ["PHARMFLOW_ALLOW_SEQUENCE_RUNS"] = "1"
# Visual demo: scramble (direct) so creatives fill; farm Tor settings unchanged.
os.environ["PHARMFLOW_BROWSE_PROXY_MODE"] = "scramble"
os.environ["PHARMFLOW_REQUIRE_UNIQUE_EXIT_IP"] = "0"
os.environ["PHARMFLOW_SKIP_MANTIS_PATCH"] = "0"
os.environ["PHARMFLOW_DABFLOW_MANTIS_PATCH"] = "1"
os.environ["PHARMFLOW_EMULATOR_AD_MODE"] = "1"
os.environ["PHARMFLOW_EMULATOR_AD_FILL_WAIT"] = "6"
os.environ["PHARMFLOW_EMULATOR_AD_FALLBACK"] = "1"
os.environ["PHARMFLOW_FARM_ALLOW_ADS"] = "1"
os.environ["PHARMFLOW_AGE_GATE_WAIT"] = "4.0"
os.environ["PHARMFLOW_DABFLOW_LOAD_WAIT"] = "3.0"
os.environ["PHARMFLOW_START_DAB_VERIFY_WAIT"] = "4.0"

from automation.browser_adb import clear_chromium_all_data  # noqa: E402
from automation.config import BROWSER_CHROMIUM  # noqa: E402
from automation.sequence_runner import Sequence, SequenceRunner  # noqa: E402
from wizard.mumu_farm_ops import MuMuFarmOps  # noqa: E402

OUT = Path(r"C:\PharmFlow\logs\demo_path2_path3")
OUT.mkdir(parents=True, exist_ok=True)
ADB = os.environ.get("PHARMFLOW_ADB") or r"C:\PharmFlow\bundled\adb.exe"
SEQ_ROOT = ROOT / "automation" / "recordings" / "sequences" / "base" / "ceramic"
PATH2 = SEQ_ROOT / "ceramic_budder_butane_timer_halfway.json"
PATH3 = SEQ_ROOT / "ceramic_budder_butane_p3a_homead2_ad.json"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(OUT / "demo.log", encoding="utf-8"),
    ],
)
log = logging.getLogger("demo_p2_p3")


def _screencap(adb_bin: str, serial: str, local: Path) -> None:
    remote = "/sdcard/Download/pharmflow_demo.png"
    try:
        subprocess.run(
            [adb_bin, "-s", serial, "shell", "screencap", "-p", remote],
            check=False,
            capture_output=True,
            timeout=20,
        )
        local.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            [adb_bin, "-s", serial, "pull", remote, str(local)],
            check=False,
            capture_output=True,
            timeout=20,
        )
    except Exception as exc:
        log.warning("screencap failed %s: %s", serial, exc)


def clear_all(farm: MuMuFarmOps) -> None:
    farm.list_instances()
    farm.refresh_serials()
    for name, inst in sorted(farm.instances.items()):
        ser = getattr(inst, "adb_serial", None) or ""
        if not ser or not ser.startswith("10.0.2."):
            log.info("skip clear %s serial=%s", name, ser)
            continue
        if not farm.adb.wait_for_device(ser, timeout=8.0):
            log.warning("offline skip clear %s %s", name, ser)
            continue
        log.info("CLEAR %s %s", name, ser)
        farm.adb.shell(f"am force-stop {BROWSER_CHROMIUM}", serial=ser)
        ok = clear_chromium_all_data(farm.adb, ser)
        log.info("  pm clear ok=%s", ok)


def _run_one(
    farm: MuMuFarmOps,
    phone: str,
    path: Path,
    label: str,
    results: dict,
) -> None:
    inst = farm.get_phone(phone)
    ser = inst.adb_serial if inst else "?"
    log.info("START %s phone=%s serial=%s seq=%s", label, phone, ser, path.name)
    seq = Sequence.from_json(path)
    seq.phone = phone
    t0 = time.time()
    try:
        report = SequenceRunner(farm).run(seq)
    except Exception as exc:
        report = {"success": False, "error": str(exc), "steps": []}
        log.exception("%s crashed", label)
    elapsed = round(time.time() - t0, 1)
    ad_steps = [
        {
            "description": s.get("description"),
            "ok": s.get("ok"),
            "ad_fallback": s.get("ad_fallback"),
            "error": s.get("error"),
        }
        for s in report.get("steps", [])
        if "ad" in str(s.get("description", "")).lower()
        or s.get("ad_fallback") is not None
    ]
    summary = {
        "label": label,
        "phone": phone,
        "serial": ser,
        "seq": path.name,
        "success": report.get("success"),
        "error": report.get("error"),
        "failed_at": report.get("failed_at"),
        "elapsed_s": elapsed,
        "steps": len(report.get("steps", [])),
        "ad_steps": ad_steps,
    }
    results[label] = summary
    shot = OUT / f"{label}_{phone}_final.png"
    if inst and inst.adb_serial:
        _screencap(ADB, inst.adb_serial, shot)
        summary["screenshot"] = str(shot)
    log.info("DONE %s %s", label, json.dumps(summary, default=str))


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    if not PATH2.is_file() or not PATH3.is_file():
        log.error("missing sequences p2=%s p3=%s", PATH2.exists(), PATH3.exists())
        return 2

    farm = MuMuFarmOps()
    clear_all(farm)

    # Mid-run shots while sequences paint ads.
    stop_mid = threading.Event()

    def mid_shots() -> None:
        for delay, tag in ((55, "a"), (40, "b"), (45, "c")):
            if stop_mid.wait(delay):
                return
            for phone, label in (("vm0.gmadoa", "P2"), ("vm1.gmadoa", "P3")):
                inst = farm.get_phone(phone)
                if inst and inst.adb_serial:
                    _screencap(ADB, inst.adb_serial, OUT / f"{label}_{phone}_{tag}.png")
                    log.info("shot %s %s", label, tag)

    results: dict = {}
    mid = threading.Thread(target=mid_shots, daemon=True)
    mid.start()

    t2 = threading.Thread(
        target=_run_one,
        args=(farm, "vm0.gmadoa", PATH2, "P2", results),
        daemon=True,
    )
    t3 = threading.Thread(
        target=_run_one,
        args=(farm, "vm1.gmadoa", PATH3, "P3", results),
        daemon=True,
    )
    t2.start()
    t3.start()
    t2.join()
    t3.join()
    stop_mid.set()

    out_path = OUT / "results.json"
    out_path.write_text(json.dumps(results, indent=2), encoding="utf-8")
    log.info("WROTE %s", out_path)
    print(json.dumps(results, indent=2), flush=True)
    ok = all(r.get("success") for r in results.values()) if results else False
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
