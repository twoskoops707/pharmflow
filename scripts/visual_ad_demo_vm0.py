#!/usr/bin/env python3
"""Visual live demo on vm0 — watch MuMu while ads run."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ["PHARMFLOW_ALLOW_SEQUENCE_RUNS"] = "1"
os.environ.setdefault("PHARMFLOW_EMULATOR_AD_FILL_WAIT", "5")

from automation.browser_identity import apply_browser_session, build_chromium_command_line, profile_from_device
from automation.emulator_ad_mode import chromium_url_bar_text
from automation.sequence_runner import Sequence, SequenceRunner, SequenceStep, StepAction
from wizard.mumu_farm_ops import MuMuFarmOps

OUT = Path(r"C:\PharmFlow\logs\ad_proof")
OUT.mkdir(parents=True, exist_ok=True)


def main() -> int:
    farm = MuMuFarmOps()
    farm.list_instances()
    phone = "vm0.gmadoa"
    inst = farm.get_phone(phone)
    if not inst or not inst.adb_serial:
        print("ERROR: vm0 not connected")
        return 1
    serial = inst.adb_serial
    print(f"WATCH MUMU WINDOW: {phone} {serial}", flush=True)

    def shot(name: str) -> None:
        remote = f"/sdcard/Download/{name}.png"
        local = OUT / f"{name}.png"
        farm.adb.shell(f"screencap -p {remote}", serial=serial)
        farm.adb.run("pull", remote, str(local), serial=serial)
        size = local.stat().st_size if local.is_file() else 0
        print(f"SHOT {name} -> {local} ({size} bytes)", flush=True)

    prof = profile_from_device(farm.adb, serial)
    print("Writing chromium flags (CDP + remote-allow-origins)...", flush=True)
    apply_browser_session(farm.adb, serial, prof, phone_index=0)
    flags = build_chromium_command_line(prof)
    print(f"FLAGS has CDP={('--remote-debugging-port' in flags)} allow={('--remote-allow-origins' in flags)}", flush=True)
    if "--remote-allow-origins=*" not in flags:
        print("WARN: remote-allow-origins missing from flags builder", flush=True)

    seq = Sequence(
        name="visual_ad_demo",
        phone=phone,
        sequence_version=2,
        steps=[
            SequenceStep(StepAction.CLEAR_COOKIES, {}, "Clear Chromium"),
            SequenceStep(StepAction.ROTATE_IDENTITY, {}, "Scramble"),
            SequenceStep(StepAction.WAIT, {"seconds": 1.0}, "Settle"),
            SequenceStep(StepAction.ENSURE_FINGERPRINT, {}, "Verify headers"),
            SequenceStep(StepAction.OPEN_URL, {"url": "https://getdabflow.app"}, "Open DabFlow"),
            SequenceStep(StepAction.WAIT, {"seconds": 2.5}, "Settle after open (FRE handled in open_url)"),
            SequenceStep(
                StepAction.WAIT,
                {"seconds": {"min": 5.0, "max": 8.0}},
                "Wait for site load before age gate",
            ),
            SequenceStep(
                StepAction.TAP,
                {"x": {"base": 450, "tolerance": 5}, "y": {"base": 1380, "tolerance": 5}},
                "Age gate: Yes, I am 21+",
            ),
            SequenceStep(StepAction.WAIT, {"seconds": 2.0}, "Home settle"),
            SequenceStep(
                StepAction.WAIT,
                {"seconds": 20.0},
                "Wait for Mantis home ad fill — WATCH SCREEN",
            ),
            SequenceStep(
                StepAction.TAP,
                {"x": {"base": 450, "tolerance": 5}, "y": {"base": 1040, "tolerance": 5}},
                "Tap home ad banner (zone-one)",
            ),
            SequenceStep(StepAction.WAIT, {"seconds": 8.0}, "View ad landing — LOOK AT EMULATOR"),
        ],
    )
    print("=== STARTING VISUAL DEMO — LOOK AT vm0 NOW ===", flush=True)
    shot("visual_00_before")
    report = SequenceRunner(farm).run(seq)
    print(f"success={report.get('success')}", flush=True)
    for s in report.get("steps") or []:
        print(
            f"  {s.get('action')}: ok={s.get('ok')} "
            f"patch={s.get('mantis_patch')} fallback={s.get('ad_fallback')} "
            f"{(s.get('description') or '')[:55]}",
            flush=True,
        )
    shot("visual_99_final")
    print(f"URL BAR: {chromium_url_bar_text(farm.adb, serial)}", flush=True)
    print("DONE — browser left open on emulator for you to see", flush=True)
    return 0 if report.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
