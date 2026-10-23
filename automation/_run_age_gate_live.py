#!/usr/bin/env python3
"""Run demo TWO through age gate only — verify loaded→age tap ≤ ~2–3s."""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "wizard"))
sys.path.insert(0, str(ROOT / "automation"))
os.environ["PHARMFLOW_HUMAN_VARIATION"] = "0"
os.environ.setdefault("PHARMFLOW_USE_SHELL_WM_FOCUS_CHEAT", "1")

import tor_manager  # noqa: E402
from sequence_normalize import normalize_automation_steps, unwrap_sequence_document  # noqa: E402
from setup_wizard import execute_steps  # noqa: E402


def main() -> int:
    serial = os.environ.get("PHARMFLOW_SERIAL", "10.0.2.108:5555")
    seq_path = Path(
        os.environ.get(
            "PHARMFLOW_SEQ",
            r"C:\PharmFlow\sequences\900x1600\ad\dabflow__demo__TWO.json",
        )
    )

    idx = tor_manager.phone_idx_from_adb_serial(serial)
    print(f"[age-gate] Tor setup serial={serial} idx={idx}", flush=True)
    tor_manager.repair_adb_reverse_for_proxy(serial, idx)
    tor = tor_manager.ensure_tor_and_proxy_for_phone(serial, idx)
    print(f"[age-gate] tor ok={tor.get('ok')}", flush=True)

    raw = json.loads(seq_path.read_text(encoding="utf-8-sig"))
    steps, _ = unwrap_sequence_document(raw)
    steps = normalize_automation_steps(steps)

    trim: list[dict] = []
    for s in steps:
        trim.append(s)
        if s.get("checkpoint") == "age_verification" or s.get("age_verification"):
            break

    t0 = time.monotonic()
    marks: list[tuple[float, str, str]] = []
    for i, s in enumerate(trim, 1):
        t = time.monotonic() - t0
        cp = str(s.get("checkpoint") or s.get("type") or "")
        print(f"  {t:5.1f}s step {i}/{len(trim)} {s.get('type')} {cp}", flush=True)
        marks.append((t, str(s.get("type")), cp))
        execute_steps([s], serial)

    loaded_t = next((t for t, _, cp in marks if cp == "loaded"), None)
    age_t = next((t for t, _, cp in marks if cp == "age_verification"), None)
    delta = (age_t - loaded_t) if loaded_t is not None and age_t is not None else None
    ok = delta is not None and delta <= 3.5

    out = Path(r"C:\PharmFlow\AGE_GATE_TIMING.txt")
    out.write_text(
        "\n".join(
            [
                f"result={'PASS' if ok else 'FAIL'}",
                f"serial={serial}",
                f"sequence={seq_path.name}",
                f"loaded_at_sec={loaded_t}",
                f"age_tap_at_sec={age_t}",
                f"loaded_to_age_sec={delta}",
                f"steps={len(trim)}",
                f"finished_at={datetime.now(timezone.utc).isoformat()}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"[age-gate] loaded->age = {delta:.2f}s ({'PASS' if ok else 'FAIL'})", flush=True)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
