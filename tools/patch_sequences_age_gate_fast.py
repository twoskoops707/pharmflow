#!/usr/bin/env python3
"""Patch every shipped sequence: MuMu age coords + fast timing (≤~3s to Yes tap)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "automation"))

from dabflow_layout import (  # noqa: E402
    AGE_GATE_OPEN_POST_WAIT_MAX_SEC,
    AGE_GATE_POST_TAP_WAIT_SEC,
    AGE_GATE_PRE_WAIT_MAX_MS,
    AGE_YES,
    AGE_YES_MUMU,
    age_gate_tap_page_coords,
)

CX, CY = age_gate_tap_page_coords()
BASE_W, BASE_H = 900, 1600
PRE_SITE_WAIT_MAX_SEC = 0.25
AGE_JITTER_MAX = 6

STATS = {"files": 0, "updates": 0, "age_steps": 0, "skipped": 0}


def _is_age_step(step: dict) -> bool:
    if step.get("type") != "tap":
        return False
    if step.get("age_verification") is True or step.get("age_gate") is True:
        return True
    cp = str(step.get("checkpoint", "")).strip().lower()
    if cp in ("age_verification", "age_gate"):
        return True
    try:
        x, y = int(step.get("x", 0)), int(step.get("y", 0))
        bw = int(step.get("base_w") or BASE_W)
        bh = int(step.get("base_h") or BASE_H)
    except (TypeError, ValueError):
        return False
    # Playwright Yes @ 900×1600 or scaled equivalent
    if bw == BASE_W and bh == BASE_H and x == AGE_YES.cx and y == AGE_YES.cy:
        return True
    if bw == BASE_W and bh == BASE_H and abs(x - AGE_YES_MUMU.cx) <= 8 and abs(y - AGE_YES_MUMU.cy) <= 8:
        return True
    # Scaled Playwright coords from other baseline sizes
    sx = round(AGE_YES.cx * bw / BASE_W)
    sy = round(AGE_YES.cy * bh / BASE_H)
    if abs(x - sx) <= 3 and abs(y - sy) <= 3:
        return True
    return False


def _touch(step: dict, key: str, val) -> bool:
    if step.get(key) == val:
        return False
    step[key] = val
    return True


def _patch_age_step(step: dict) -> int:
    n = 0
    STATS["age_steps"] += 1
    if _touch(step, "x", CX):
        n += 1
    if _touch(step, "y", CY):
        n += 1
    if _touch(step, "base_w", BASE_W):
        n += 1
    if _touch(step, "base_h", BASE_H):
        n += 1
    if _touch(step, "age_verification", True):
        n += 1
    if _touch(step, "checkpoint", "age_verification"):
        n += 1
    if _touch(step, "phase", "pre_site_fast"):
        n += 1
    pre = float(step.get("pre_wait_ms") or 0)
    cap_pre = min(pre, AGE_GATE_PRE_WAIT_MAX_MS) if pre else 80.0
    if _touch(step, "pre_wait_ms", cap_pre):
        n += 1
    retries = int(step.get("retries") or 0)
    if retries < 5 and _touch(step, "retries", 5):
        n += 1
    jitter = int(step.get("jitter") or 0)
    if jitter > AGE_JITTER_MAX and _touch(step, "jitter", AGE_JITTER_MAX):
        n += 1
    return n


def patch_steps(steps: list) -> int:
    n = 0
    seen_age = False
    before_first_age = True

    for step in steps:
        if not isinstance(step, dict):
            before_first_age = False
            continue

        t = step.get("type")

        if t == "open_url" and "getdabflow.app" in str(step.get("url", "")).lower():
            if before_first_age or not seen_age:
                pws = step.get("post_wait_secs")
                try:
                    old = float(pws) if pws not in (None, "") else 0.0
                except (TypeError, ValueError):
                    old = 0.0
                cap = (
                    min(old, AGE_GATE_OPEN_POST_WAIT_MAX_SEC)
                    if old
                    else AGE_GATE_OPEN_POST_WAIT_MAX_SEC
                )
                if _touch(step, "post_wait_secs", cap):
                    n += 1
                if _touch(step, "phase", "pre_site_fast"):
                    n += 1

        if t == "wait" and before_first_age:
            phase = str(step.get("phase") or "").lower()
            if phase in ("pre_site_fast", "") or not seen_age:
                try:
                    secs = float(step.get("seconds") or 0)
                except (TypeError, ValueError):
                    secs = 0.0
                if secs > PRE_SITE_WAIT_MAX_SEC and _touch(
                    step, "seconds", round(PRE_SITE_WAIT_MAX_SEC, 3)
                ):
                    n += 1
                if phase == "" and _touch(step, "phase", "pre_site_fast"):
                    n += 1

        if _is_age_step(step):
            n += _patch_age_step(step)
            seen_age = True
            before_first_age = False
            continue

        if t == "wait" and seen_age:
            try:
                secs = float(step.get("seconds") or 0)
            except (TypeError, ValueError):
                secs = 0.0
            cap = min(secs, AGE_GATE_POST_TAP_WAIT_SEC) if secs else AGE_GATE_POST_TAP_WAIT_SEC
            if _touch(step, "seconds", round(cap, 3)):
                n += 1
            seen_age = False
            continue

        if t not in ("wait", "open_url") or str(step.get("phase", "")).lower() not in (
            "pre_site_fast",
            "",
        ):
            if not before_first_age:
                seen_age = False

    return n


def patch_file(path: Path) -> int:
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        STATS["skipped"] += 1
        return 0
    steps = data.get("steps") if isinstance(data, dict) else data
    if not isinstance(steps, list):
        STATS["skipped"] += 1
        return 0
    n = patch_steps(steps)
    if n:
        STATS["files"] += 1
        STATS["updates"] += n
        path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return n


def sequence_roots() -> list[Path]:
    roots: list[Path] = []
    seen: set[str] = set()
    candidates = [
        ROOT / "sequences",
        ROOT.parent / "sequences",
        Path.home() / "PharmFlow" / "sequences",
        ROOT / "automation" / "recordings" / "sequences",
    ]
    for p in candidates:
        try:
            key = str(p.resolve())
        except OSError:
            continue
        if p.is_dir() and key not in seen:
            seen.add(key)
            roots.append(p)
    return roots


def main() -> int:
    total = 0
    for root in sequence_roots():
        for path in sorted(root.rglob("*.json")):
            if path.name.startswith("_"):
                continue
            total += 1
            patch_file(path)

    print(
        f"Scanned {total} sequences | patched {STATS['files']} files | "
        f"{STATS['updates']} field updates | {STATS['age_steps']} age steps | "
        f"skipped {STATS['skipped']} | MuMu tap=({CX},{CY}) @ {BASE_W}x{BASE_H}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
