#!/usr/bin/env python3
"""Humanize every shipped sequence — unique timing per file + de-crowd waits."""
from __future__ import annotations

import hashlib
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "wizard"))
sys.path.insert(0, str(ROOT / "automation"))

from dabflow_layout import (  # noqa: E402
    AGE_GATE_OPEN_POST_WAIT_MAX_SEC,
    AGE_GATE_PRE_WAIT_MAX_MS,
    AGE_GATE_POST_TAP_WAIT_SEC,
    age_gate_tap_page_coords,
)
from sequence_humanize import humanize_steps  # noqa: E402
from sequence_normalize import normalize_automation_steps, unwrap_sequence_document  # noqa: E402

CX, CY = age_gate_tap_page_coords()
FILES = 0
UPDATES = 0


def _is_age_step(step: dict) -> bool:
    return bool(
        step.get("age_verification") is True
        or step.get("age_gate") is True
        or str(step.get("checkpoint", "")).strip().lower() in ("age_verification", "age_gate")
    )


def _patch_age_in_steps(steps: list) -> None:
    prev_age = False
    for step in steps:
        if not isinstance(step, dict):
            prev_age = False
            continue
        if step.get("type") == "open_url" and "getdabflow.app" in str(step.get("url", "")).lower():
            phase = str(step.get("phase") or "").lower()
            if phase in ("pre_site_fast", "") or str(step.get("checkpoint", "")).lower() in ("loaded", ""):
                pws = step.get("post_wait_secs")
                try:
                    old = float(pws) if pws not in (None, "") else 0.0
                except (TypeError, ValueError):
                    old = 0.0
                step["post_wait_secs"] = (
                    min(old, AGE_GATE_OPEN_POST_WAIT_MAX_SEC) if old else AGE_GATE_OPEN_POST_WAIT_MAX_SEC
                )
        if step.get("type") == "tap" and _is_age_step(step):
            step["x"], step["y"] = CX, CY
            step["base_w"], step["base_h"] = 900, 1600
            step["phase"] = "pre_site_fast"
            pre = float(step.get("pre_wait_ms") or 0)
            step["pre_wait_ms"] = min(pre, AGE_GATE_PRE_WAIT_MAX_MS) if pre else 80.0
            step["retries"] = max(int(step.get("retries") or 0), 5)
            step["jitter"] = min(int(step.get("jitter") or 0), 6)
            prev_age = True
            continue
        if step.get("type") == "wait" and prev_age:
            try:
                secs = float(step.get("seconds") or 0)
            except (TypeError, ValueError):
                secs = 0.0
            step["seconds"] = round(
                min(secs, AGE_GATE_POST_TAP_WAIT_SEC) if secs else AGE_GATE_POST_TAP_WAIT_SEC,
                3,
            )
            prev_age = False
            continue
        prev_age = False


def _roots() -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []
    for p in (ROOT / "sequences", ROOT.parent / "sequences", Path.home() / "PharmFlow" / "sequences"):
        try:
            key = str(p.resolve())
        except OSError:
            continue
        if p.is_dir() and key not in seen:
            seen.add(key)
            out.append(p)
    return out


def process_file(path: Path) -> bool:
    global FILES, UPDATES
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return False
    steps, meta = unwrap_sequence_document(data)
    if not isinstance(steps, list) or not steps:
        return False

    seed = int(hashlib.sha256(str(path).encode("utf-8")).hexdigest()[:8], 16)
    rng = random.Random(seed)
    human = humanize_steps(steps, rng)
    _patch_age_in_steps(human)
    normalized = normalize_automation_steps(human)

    if isinstance(data, list):
        new_data: object = normalized
    else:
        new_data = dict(data)
        new_data["steps"] = normalized
        if meta is not None and isinstance(new_data.get("meta"), dict):
            m = dict(new_data["meta"])
            m["humanize_seed"] = seed
            new_data["meta"] = m

    text = json.dumps(new_data, indent=2, ensure_ascii=False) + "\n"
    if text != path.read_text(encoding="utf-8"):
        path.write_text(text, encoding="utf-8")
        FILES += 1
        UPDATES += 1
        return True
    return False


def main() -> int:
    total = 0
    for root in _roots():
        for path in sorted(root.rglob("*.json")):
            if path.name.startswith("_"):
                continue
            if "dabflow" not in path.name:
                continue
            total += 1
            process_file(path)
    print(f"Humanized {FILES}/{total} dabflow sequences (unique seed per file, waits merged).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
