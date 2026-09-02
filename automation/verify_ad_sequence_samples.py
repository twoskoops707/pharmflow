#!/usr/bin/env python3
"""Spot-check ad-path sequences: full timer first, then tab → ad tap → ≥30s dwell."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_AUTOMATION = Path(__file__).resolve().parent
if str(_AUTOMATION) not in sys.path:
    sys.path.insert(0, str(_AUTOMATION))

from dabflow_layout import GLASS_AD_SLOT, SETTINGS_AD_SLOT, STATS_AD_SLOT  # noqa: E402
from sequence_normalize import unwrap_sequence_document  # noqa: E402
from sequences_paths import resolve_sequences_dir  # noqa: E402

AD_MIN = 30.0
AD_TAP_TOL = 90

POST_TIMER_AD_CHECKPOINTS = ("ad_glass", "ad_stats", "ad_settings", "ad_selected")
FORBIDDEN_PRE_TIMER_AD = ("ad_home", "ad_timer_video", "ad_timer_banner", "ad_timer_banner_lower")

_AD_SLOT_BY_CP = {
    "ad_glass": GLASS_AD_SLOT,
    "ad_stats": STATS_AD_SLOT,
    "ad_settings": SETTINGS_AD_SLOT,
}


def _find_checkpoint_tap(steps: list, checkpoint: str) -> int | None:
    want = checkpoint.strip().lower()
    for i, step in enumerate(steps):
        if not isinstance(step, dict) or step.get("type") != "tap":
            continue
        if str(step.get("checkpoint", "")).strip().lower() == want:
            return i
    return None


def _find_checkpoint_step(steps: list, checkpoint: str) -> int | None:
    want = checkpoint.strip().lower()
    for i, step in enumerate(steps):
        if not isinstance(step, dict):
            continue
        if str(step.get("checkpoint", "")).strip().lower() == want:
            return i
    return None


def _near_slot(step: dict, region) -> bool:
    if step.get("type") != "tap":
        return False
    try:
        x, y = float(step["x"]), float(step["y"])
    except (KeyError, TypeError, ValueError):
        return False
    return abs(x - region.cx) <= AD_TAP_TOL and abs(y - region.cy) <= AD_TAP_TOL


def _ad_dwell_after_tap(steps: list, ad_idx: int) -> float:
    total = 0.0
    for step in steps[ad_idx + 1 :]:
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
    steps, _ = unwrap_sequence_document(data)
    if not isinstance(steps, list):
        return [f"{path.name}: steps not a list"]

    timer_done_idx = _find_checkpoint_step(steps, "timer_complete")
    if timer_done_idx is None:
        errs.append(f"{path.name}: missing timer_complete wait before post-timer ad")
        return errs

    for cp in FORBIDDEN_PRE_TIMER_AD:
        idx = _find_checkpoint_tap(steps, cp)
        if idx is not None:
            errs.append(f"{path.name}: forbidden pre/post-timer-misplaced ad checkpoint {cp!r}")

    ad_cp = None
    ad_idx = None
    for cp in POST_TIMER_AD_CHECKPOINTS:
        idx = _find_checkpoint_tap(steps, cp)
        if idx is not None:
            ad_cp = cp
            ad_idx = idx
            break
    if ad_idx is None:
        errs.append(f"{path.name}: missing post-timer ad tap (one of {POST_TIMER_AD_CHECKPOINTS})")
        return errs

    if ad_idx <= timer_done_idx:
        errs.append(f"{path.name}: ad tap at index {ad_idx} must follow timer_complete at {timer_done_idx}")

    tap = steps[ad_idx]
    if not tap.get("ad_selected"):
        errs.append(f"{path.name}: {ad_cp} tap missing ad_selected marker")
    slot = _AD_SLOT_BY_CP.get(ad_cp or "")
    if slot and ad_cp != "ad_selected" and not _near_slot(tap, slot):
        errs.append(f"{path.name}: {ad_cp} tap not near expected ad slot")

    dwell = _ad_dwell_after_tap(steps, ad_idx)
    if round(dwell, 2) < AD_MIN:
        errs.append(f"{path.name}: ad dwell {dwell:.1f}s < {AD_MIN}s after {ad_cp}")

    return errs


def main() -> int:
    root = resolve_sequences_dir(create=False)
    all_errs: list[str] = []
    checked = 0
    sample_dir = root / "900x1600" / "ad"
    if not sample_dir.is_dir():
        print(f"SKIP: no ad sequences under {root}/900x1600/ad")
        return 0
    for fp in sorted(sample_dir.glob("dabflow*.json")):
        checked += 1
        all_errs.extend(check_file(fp))
    if checked == 0:
        print(f"SKIP: no dabflow sequences under {sample_dir}")
        return 0
    if all_errs:
        print("FAILED:")
        for e in all_errs:
            print(f"  - {e}")
        return 1
    print(
        f"OK: {checked} ad-path dabflow sequence(s) — "
        f"full timer_complete first, then tab ad tap + dwell >={AD_MIN}s"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
