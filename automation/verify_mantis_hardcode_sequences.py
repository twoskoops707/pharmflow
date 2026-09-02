#!/usr/bin/env python3
"""Verify mantis-hardcode test sequences: open_url ad landing, no on-site ad tap, ≥30s dwell."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_AUTOMATION = Path(__file__).resolve().parent
if str(_AUTOMATION) not in sys.path:
    sys.path.insert(0, str(_AUTOMATION))

from sequence_normalize import unwrap_sequence_document  # noqa: E402
from sequences_paths import resolve_sequences_dir  # noqa: E402

AD_MIN = 30.0
HARDOCODE_DIR = "900x1600/ad/mantis-hardcode"
FORBIDDEN_AD_TAP_CHECKPOINTS = ("ad_glass", "ad_stats", "ad_settings", "ad_home", "ad_tapped")


def _find_checkpoint_step(steps: list, checkpoint: str) -> int | None:
    want = checkpoint.strip().lower()
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        if str(step.get("checkpoint", "")).strip().lower() == want:
            return i
    return None


def _ad_dwell_after_hardcode(steps: list, open_idx: int) -> float:
    total = 0.0
    for step in steps[open_idx + 1 :]:
        if not isinstance(step, dict):
            continue
        if step.get("type") in ("keyevent", "close_app"):
            break
        if step.get("type") == "wait":
            try:
                total += float(step.get("seconds", 0))
            except (TypeError, ValueError):
                pass
            if step.get("ad_read"):
                break
        elif step.get("type") != "swipe":
            break
    return total


def check_file(path: Path) -> list[str]:
    errs: list[str] = []
    data = json.loads(path.read_text(encoding="utf-8"))
    steps, meta = unwrap_sequence_document(data)
    if not isinstance(steps, list):
        return [f"{path.name}: steps not a list"]

    if meta.get("flow") != "mantis-hardcode" and not meta.get("mantis_hardcode"):
        errs.append(f"{path.name}: meta.flow must be mantis-hardcode")

    timer_done_idx = _find_checkpoint_step(steps, "timer_complete")
    if timer_done_idx is None:
        errs.append(f"{path.name}: missing timer_complete wait")
        return errs

    for cp in FORBIDDEN_AD_TAP_CHECKPOINTS:
        idx = _find_checkpoint_step(steps, cp)
        if idx is not None and steps[idx].get("type") == "tap":
            errs.append(f"{path.name}: must not tap on-site ad checkpoint {cp!r}")

    ad_cp = str(meta.get("mantis_ad_checkpoint") or "").strip()
    open_idx = _find_checkpoint_step(steps, ad_cp) if ad_cp else None
    if open_idx is None:
        for i, step in enumerate(steps):
            if isinstance(step, dict) and step.get("type") == "open_url" and step.get("mantis_hardcode"):
                open_idx = i
                ad_cp = str(step.get("checkpoint", ""))
                break
    if open_idx is None:
        errs.append(f"{path.name}: missing mantis_hardcode open_url step")
        return errs

    if open_idx <= timer_done_idx:
        errs.append(f"{path.name}: hardcode open_url must follow timer_complete")

    open_step = steps[open_idx]
    if open_step.get("type") != "open_url":
        errs.append(f"{path.name}: {ad_cp} is not open_url")
    if not open_step.get("ad_selected"):
        errs.append(f"{path.name}: hardcode open_url missing ad_selected")
    url = str(open_step.get("url") or "").strip()
    if not url.startswith("http"):
        errs.append(f"{path.name}: hardcode open_url missing http(s) url")

    dwell = _ad_dwell_after_hardcode(steps, open_idx)
    if round(dwell, 2) < AD_MIN:
        errs.append(f"{path.name}: ad dwell {dwell:.1f}s < {AD_MIN}s after hardcode open")

    return errs


def main() -> int:
    root = resolve_sequences_dir(create=False)
    sample_dir = root / HARDOCODE_DIR.replace("/", "/")
    if not sample_dir.is_dir():
        print(f"SKIP: no mantis-hardcode tests under {sample_dir}")
        return 0

    all_errs: list[str] = []
    checked = 0
    for fp in sorted(sample_dir.glob("dabflow__mantis_hardcode__*.json")):
        checked += 1
        all_errs.extend(check_file(fp))

    if checked == 0:
        print(f"SKIP: no dabflow__mantis_hardcode__*.json under {sample_dir}")
        return 0
    if all_errs:
        print("FAILED:")
        for e in all_errs:
            print(f"  - {e}")
        return 1
    print(
        f"OK: {checked} mantis-hardcode test sequence(s) — "
        f"open_url ad landing (no tap), dwell >={AD_MIN}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
