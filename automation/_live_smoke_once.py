"""One-off live smoke: run_sequence_step per device (not committed)."""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

os.environ["CPHARM_HUMAN_VARIATION"] = "0"

SCRIPT_DIR = Path(__file__).resolve().parent
os.chdir(SCRIPT_DIR)
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from sequence_normalize import normalize_automation_steps
from dashboard import run_sequence_step

BASE = SCRIPT_DIR / "recordings" / "sequences"
JOBS = [
    ("10.0.2.104:5555", BASE / "close_chrome__open_getdabflow_app__w10s__tap_consent_strip__tap_age_modal__tap_landing_hero__hd2a57d.json", "ads — close_chrome__open_getdabflow_app__w10s__tap_consent_strip__tap_age_modal__tap_landing_hero__hd2a57d.json"),
    ("10.0.2.253:5555", BASE / "close_chrome__open_getdabflow_app__w10s__tap_consent_strip__tap_age_modal__tap_landing_hero__hdd71d4.json", "no-ads — close_chrome__open_getdabflow_app__w10s__tap_consent_strip__tap_age_modal__tap_landing_hero__hdd71d4.json"),
    (
        "10.0.2.66:5555",
        BASE / "open_getdabflow__combo_landing_short__rotate_wait_fullreset.json",
        "home/combo — open_getdabflow__combo_landing_short__rotate_wait_fullreset.json",
    ),
]


def _run_one(serial, path, label):
    t0 = time.time()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
        steps = raw if isinstance(raw, list) else raw.get("steps", [])
        if not isinstance(steps, list):
            raise TypeError("steps must be a list")
        steps = normalize_automation_steps(steps)
        for step in steps:
            run_sequence_step(serial, step)
        dt = time.time() - t0
        return {
            "label": label,
            "serial": serial,
            "file": str(path.relative_to(SCRIPT_DIR)),
            "exit_code": 0,
            "steps": len(steps),
            "seconds": round(dt, 2),
            "error": None,
        }
    except Exception:
        dt = time.time() - t0
        return {
            "label": label,
            "serial": serial,
            "file": str(path.relative_to(SCRIPT_DIR)),
            "exit_code": 1,
            "steps": None,
            "seconds": round(dt, 2),
            "error": traceback.format_exc(),
        }


def main():
    results = []
    with ThreadPoolExecutor(max_workers=3) as pool:
        futs = [pool.submit(_run_one, s, p, lbl) for s, p, lbl in JOBS]
        for fut in as_completed(futs):
            results.append(fut.result())
    order = {s: i for i, s in enumerate(j[0] for j in JOBS)}
    results.sort(key=lambda r: order.get(r["serial"], 99))
    for r in results:
        print(json.dumps(r, indent=2))
    bad = sum(1 for r in results if r.get("exit_code") != 0)
    return 1 if bad else 0


if __name__ == "__main__":
    raise SystemExit(main())
