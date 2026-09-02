#!/usr/bin/env python3
"""Run one real sequence per browser and prove it reaches the DabFlow timer.

Firefox/Brave sequences used to open the browser and then sit there: Fenix held the
Terms-of-Use screen, and recorded Chromium coordinates missed because each browser
reserves different toolbar space. This runs an actual sequence through the
"Start Perfect Dab" tap and checks the timer is live.

    py -3 scripts/verify_browser_sequence.py --phone vm0.gmadoa --browser firefox
    py -3 scripts/verify_browser_sequence.py --phone vm0.gmadoa --browser all
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault("CPHARM_ALLOW_SEQUENCE_RUNS", "1")
os.environ.setdefault("CPHARM_SKIP_MANTIS_PATCH", "1")
os.environ["CPHARM_EMULATOR_AD_FILL_WAIT"] = "0"
# Fast demo: skip Tor/geo/IMEI isolation (minutes) — browser wipe still runs.
os.environ.setdefault("CPHARM_SKIP_SEQUENCE_ISOLATION", "1")
os.environ.setdefault("CPHARM_SKIP_FINGERPRINT", "1")

from automation.sequence_runner import Sequence, SequenceRunner
from automation.web_viewport import get_viewport
from wizard.mumu_farm_ops import MuMuFarmOps

OUT = Path(r"C:\CPharm\logs\browser_verify")
BROWSER_TAGS = ("chromium", "firefox", "brave", "duckduckgo")
TIMER_MARKERS = ("HEAT YOUR BANGER", "Pause", "PAUSE", "timer-display", "COOL DOWN")


def pick_sequence(root: Path, tag: str, rng: random.Random) -> Path | None:
    candidates = [p for p in root.rglob(f"*_p1a_{tag}_complete.json")]
    if not candidates:
        candidates = [p for p in root.rglob(f"*_{tag}_complete.json")]
    return rng.choice(candidates) if candidates else None


def run_one(farm: MuMuFarmOps, phone: str, seq_path: Path) -> dict:
    inst = farm.get_phone(phone)
    serial = inst.adb_serial
    seq = Sequence.from_json(seq_path)
    seq.phone = phone

    cut = None
    for i, step in enumerate(seq.steps):
        desc = step.description.lower()
        if desc.startswith("start perfect dab") or desc == "start perfect dab timer":
            cut = i + 1
            break
    if cut is not None:
        seq.steps = seq.steps[:cut]
    # Fast path: drop isolation preamble steps (clear/rotate/fingerprint) — wipe
    # already happens once in SequenceRunner when skip-isolation is on.
    skip_actions = {"rotate_identity", "ensure_fingerprint", "clear_cookies"}
    seq.steps = [s for s in seq.steps if s.action.value not in skip_actions]

    runner = SequenceRunner(farm)
    result = runner.run(seq)

    farm.adb.shell("uiautomator dump /sdcard/cpharm_verify.xml", serial=serial)
    xml = farm.adb.shell("cat /sdcard/cpharm_verify.xml", serial=serial).stdout or ""
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{seq_path.stem}.xml").write_text(xml, encoding="utf-8", errors="replace")
    farm.adb.shell(f"screencap -p /sdcard/{seq_path.stem}.png", serial=serial)
    farm.adb.run("pull", f"/sdcard/{seq_path.stem}.png", str(OUT / f"{seq_path.stem}.png"), serial=serial)

    vp = get_viewport(serial)
    failed_steps = [
        {
            "description": s.get("description"),
            "action": s.get("action"),
            "error": s.get("error"),
            "coords": s.get("coords"),
        }
        for s in result.get("steps", [])
        if s.get("ok") is False
    ]
    remapped = [s for s in result.get("steps", []) if "viewport_y" in s]
    return {
        "sequence": seq_path.stem,
        "preferred_browser": seq.preferred_browser,
        "serial": serial,
        "success": bool(result.get("success")),
        "error": result.get("error"),
        "failed_at": result.get("failed_at"),
        "steps_run": len(result.get("steps", [])),
        "failed_steps": failed_steps,
        "viewport": {"top": vp.top, "bottom": vp.bottom} if vp else None,
        "remapped_taps": len(remapped),
        "remap_example": remapped[0].get("viewport_y") if remapped else None,
        "dabflow_loaded": any(m in xml for m in ("age-gate", "DABFLOW", "nav-timer")),
        "timer_ok": any(m in xml for m in TIMER_MARKERS),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--phone", default="vm0.gmadoa")
    ap.add_argument("--browser", default="all", choices=(*BROWSER_TAGS, "all"))
    ap.add_argument(
        "--root",
        type=Path,
        default=Path(r"C:\CPharm\automation\recordings\sequences\base"),
    )
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()

    rng = random.Random(args.seed or None)
    tags = BROWSER_TAGS if args.browser == "all" else (args.browser,)

    farm = MuMuFarmOps()
    farm.list_instances()

    reports = []
    for tag in tags:
        seq_path = pick_sequence(args.root, tag, rng)
        if seq_path is None:
            print(f"{tag}: no sequence found under {args.root}", flush=True)
            reports.append({"sequence": None, "browser_tag": tag, "success": False, "error": "no sequence"})
            continue
        print(f"\n=== {tag}: {seq_path.stem} on {args.phone}", flush=True)
        report = run_one(farm, args.phone, seq_path)
        report["browser_tag"] = tag
        print(json.dumps(report, indent=2), flush=True)
        reports.append(report)

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "verify_summary.json").write_text(json.dumps(reports, indent=2), encoding="utf-8")
    print("\n==== SUMMARY ====", flush=True)
    for r in reports:
        print(
            f"{r.get('browser_tag'):9s} success={r.get('success')} "
            f"dabflow={r.get('dabflow_loaded')} timer={r.get('timer_ok')} "
            f"viewport={r.get('viewport')} remapped={r.get('remapped_taps')} "
            f"err={r.get('error')}",
            flush=True,
        )
    return 0 if all(r.get("timer_ok") for r in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
