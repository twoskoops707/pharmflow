"""Run one Path1A sequence via SequenceRunner through Start; capture timer proof."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("PHARMFLOW_ALLOW_SEQUENCE_RUNS", "1")
os.environ["PHARMFLOW_SKIP_MANTIS_PATCH"] = "1"
os.environ.setdefault("PHARMFLOW_BROWSE_PROXY_MODE", "scramble")
os.environ["PHARMFLOW_EMULATOR_AD_FILL_WAIT"] = "0"

from automation.sequence_runner import Sequence, SequenceRunner
from wizard.mumu_farm_ops import MuMuFarmOps

OUT = Path(r"C:\PharmFlow\logs\proof_fix")
ADB_BIN = os.environ.get("PHARMFLOW_ADB") or r"C:\PharmFlow\bundled\adb.exe"
SEQ = Path(
    r"C:\PharmFlow\automation\recordings\sequences\base\ceramic\ceramic_budder_butane_p1a_complete.json"
)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    farm = MuMuFarmOps()
    farm.list_instances()
    phone = "vm0.gmadoa"
    inst = farm.get_phone(phone)
    ser = inst.adb_serial
    print("serial", ser, "seq", SEQ.name, flush=True)

    seq = Sequence.from_json(SEQ)
    seq.phone = phone
    cut = None
    for i, step in enumerate(seq.steps):
        desc = step.description.lower()
        # Exact Start tap — do not match "Scroll to reveal Start Perfect Dab"
        if desc.startswith("start perfect dab") or desc == "start perfect dab timer":
            cut = i + 1
            break
    if cut is None:
        print("ERROR: no Start Perfect Dab tap step", flush=True)
        return 2
    seq.steps = seq.steps[:cut]
    print(f"running {len(seq.steps)} steps through Start", flush=True)
    print("last_steps", [s.description for s in seq.steps[-4:]], flush=True)

    runner = SequenceRunner(farm)
    result = runner.run(seq)
    print(
        "RUN_RESULT",
        json.dumps(
            {
                "success": result.get("success"),
                "error": result.get("error"),
                "failed_at": result.get("failed_at"),
            },
            indent=2,
        ),
        flush=True,
    )
    for sr in result.get("steps", []):
        desc = sr.get("description") or sr.get("action")
        if any(
            k in str(desc).lower()
            for k in ("fre", "age", "start perfect", "open_url", "material", "concentrate")
        ):
            print("STEP", desc, "ok=", sr.get("ok"), "err=", sr.get("error"), "extra=", {k: sr.get(k) for k in ("fre_dismiss", "start_dab", "coords") if k in sr}, flush=True)

    remote = "/sdcard/Download/proof_seq_after_start.png"
    local = OUT / "07_seq_runner_after_start.png"
    farm.adb.shell(f"screencap -p {remote}", serial=ser)
    subprocess.run([ADB_BIN, "-s", ser, "pull", remote, str(local)], check=False, capture_output=True)
    farm.adb.shell("uiautomator dump /sdcard/pharmflow_ui.xml", serial=ser)
    xml = farm.adb.shell("cat /sdcard/pharmflow_ui.xml", serial=ser).stdout or ""
    (OUT / "07_seq_runner_after_start.xml").write_text(xml, encoding="utf-8", errors="replace")
    timer_ok = any(t in xml for t in ("HEAT YOUR BANGER", "Pause", "PAUSE"))
    print(f"SHOT bytes={local.stat().st_size if local.exists() else 0} TIMER_OK={timer_ok}", flush=True)
    (OUT / "seq_runner_summary.json").write_text(
        json.dumps(
            {
                "success": result.get("success"),
                "error": result.get("error"),
                "timer_ok": timer_ok,
                "shot": str(local),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return 0 if timer_ok and result.get("success") else 1


if __name__ == "__main__":
    raise SystemExit(main())
