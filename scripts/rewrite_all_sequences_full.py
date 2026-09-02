"""Rewrite all DabFlow sequences: splash, age gate, swipes, ads, identity text."""

from __future__ import annotations

import hashlib
import json
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from automation.dabflow_mapper import load_mapping
from automation.humanize import MIN_SCROLL_Y, scroll_swipe_params

CHROMIUM_SKIP_X = 450
CHROMIUM_SKIP_Y = 1127
AGE_GATE_X = 450
AGE_GATE_Y = 1380
HOME_AD = (450, 1040)
POST_TIMER_AD = (648, 1492)


def _seed(name: str) -> int:
    return int(hashlib.md5(name.encode("utf-8")).hexdigest()[:8], 16)


def _is_age_gate_step(step: dict[str, Any]) -> bool:
    desc = str(step.get("description", "")).lower()
    return step.get("action") == "tap" and ("age gate" in desc or "21+" in desc)


def _is_ad_tap_step(step: dict[str, Any]) -> bool:
    desc = str(step.get("description", "")).lower()
    return step.get("action") == "tap" and "ad" in desc and "banner" in desc


def _fix_swipe_params(params: dict[str, Any], seed: int) -> dict[str, Any]:
    out = dict(params)
    if "x1" not in out and "x" in out:
        out["x1"] = out.pop("x")
    if "y1" not in out and "y" in out:
        out["y1"] = out.pop("y")
    safe = scroll_swipe_params(seed, 10)
    for key in ("x1", "y1", "x2", "y2", "duration_ms"):
        if key not in out or not out[key]:
            out[key] = safe[key]
    y1 = out.get("y1")
    if isinstance(y1, dict) and int(y1.get("base", 0)) < MIN_SCROLL_Y:
        y1["base"] = max(MIN_SCROLL_Y, int(y1.get("base", MIN_SCROLL_Y)))
    elif isinstance(y1, int) and y1 < MIN_SCROLL_Y:
        out["y1"] = MIN_SCROLL_Y
    return out


def _fix_ad_tap(step: dict[str, Any], *, post_timer: bool) -> None:
    if not _is_ad_tap_step(step):
        return
    params = step.setdefault("params", {})
    x, y = (POST_TIMER_AD if post_timer else HOME_AD)
    params["x"] = {"base": x, "tolerance": 10}
    params["y"] = {"base": y, "tolerance": 10}
    if post_timer:
        step["description"] = "Tap post-timer ad banner"
    elif "home" not in step.get("description", "").lower():
        step["description"] = "Tap home ad banner (zone-one)"


def _collapse_pre_age_gate_waits(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One 5–10s wait after splash, before age gate tap."""
    age_idx = next((i for i, s in enumerate(steps) if _is_age_gate_step(s)), None)
    if age_idx is None:
        return steps

    out: list[dict[str, Any]] = []
    inserted_load_wait = False
    for i, step in enumerate(steps):
        if i >= age_idx:
            if not inserted_load_wait:
                out.append(
                    {
                        "action": "wait",
                        "params": {"seconds": {"min": 5.0, "max": 10.0}},
                        "description": "Wait for site load before age gate",
                    }
                )
                inserted_load_wait = True
            out.append(deepcopy(step))
            continue

        action = step.get("action")
        desc = str(step.get("description", "")).lower()

        if action == "wait" and not desc and i > 0:
            prev = steps[i - 1]
            if prev.get("action") == "tap" and "skip" in str(prev.get("description", "")).lower():
                continue
        if action == "wait" and "page load" in desc and "age gate" not in desc:
            continue
        if action == "wait" and "home screen" in desc and i < age_idx - 1:
            continue

        out.append(deepcopy(step))

        if action == "tap" and ("skip" in desc or "stay signed" in desc):
            if not inserted_load_wait:
                out.append(
                    {
                        "action": "wait",
                        "params": {"seconds": {"min": 5.0, "max": 10.0}},
                        "description": "Wait for site load before age gate",
                    }
                )
                inserted_load_wait = True

    if not inserted_load_wait:
        for i, s in enumerate(out):
            if _is_age_gate_step(s):
                out.insert(
                    i,
                    {
                        "action": "wait",
                        "params": {"seconds": {"min": 5.0, "max": 10.0}},
                        "description": "Wait for site load before age gate",
                    },
                )
                break
    return out


def _fix_identity_steps(steps: list[dict[str, Any]]) -> None:
    for step in steps:
        desc = str(step.get("description", ""))
        if step.get("action") == "rotate_identity" and "Tor circuit" in desc:
            step["description"] = "Scramble browser session + rotate identity"
        if step.get("action") == "wait" and "Tor to establish" in desc:
            step["description"] = "Wait after identity scramble"
            step["params"] = {"seconds": {"min": 1.2, "max": 2.0}}
        if step.get("action") == "ensure_fingerprint" and "VM fingerprint" in desc:
            step["description"] = "Verify browser headers before browse"


def rewrite_document(data: dict[str, Any], path: Path) -> dict[str, Any]:
    mapping = load_mapping()
    out = deepcopy(data)
    name = str(out.get("name") or path.stem)
    seed = _seed(name)
    steps: list[dict[str, Any]] = list(out.get("steps") or [])

    _fix_identity_steps(steps)

    new_steps: list[dict[str, Any]] = []
    seen_post_timer_ad = False
    for step in steps:
        step = deepcopy(step)
        if step.get("action") == "tap":
            params = step.setdefault("params", {})
            desc = str(step.get("description", "")).lower()
            if "skip" in desc or "stay signed" in desc:
                params["x"] = {"base": CHROMIUM_SKIP_X, "tolerance": 10}
                params["y"] = {"base": CHROMIUM_SKIP_Y, "tolerance": 10}
            if _is_age_gate_step(step):
                age = mapping.age_gate_consent()
                params["x"] = {"base": age.x, "tolerance": 10}
                params["y"] = {"base": age.y, "tolerance": 10}
            if _is_ad_tap_step(step):
                post_timer = "post-timer" in desc or (not seen_post_timer_ad and "1100" in json.dumps(params))
                if post_timer:
                    seen_post_timer_ad = True
                _fix_ad_tap(step, post_timer=post_timer)
        if step.get("action") == "swipe":
            step["params"] = _fix_swipe_params(step.get("params") or {}, seed)
        new_steps.append(step)

    new_steps = _collapse_pre_age_gate_waits(new_steps)
    out["steps"] = new_steps
    return out


def rewrite_file(path: Path, *, dry_run: bool = False) -> bool:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict) or "steps" not in data:
        return False
    new = rewrite_document(data, path)
    text = json.dumps(new, indent=2, ensure_ascii=False) + "\n"
    old = path.read_text(encoding="utf-8")
    if text == old:
        return False
    if not dry_run:
        path.write_text(text, encoding="utf-8", newline="\n")
    return True


def rewrite_tree(root: Path, *, dry_run: bool = False) -> int:
    count = 0
    for path in sorted(root.rglob("*.json")):
        if rewrite_file(path, dry_run=dry_run):
            count += 1
    return count


def main() -> None:
    dry = "--dry-run" in sys.argv
    args = [a for a in sys.argv[1:] if a != "--dry-run"]
    roots = [Path(a) for a in args] if args else [
        Path("automation/recordings/sequences"),
        Path(r"C:\CPharm\automation\recordings\sequences"),
    ]
    total = 0
    for root in roots:
        if not root.is_dir():
            print(f"skip missing: {root}")
            continue
        n = rewrite_tree(root, dry_run=dry)
        total += n
        print(f"{'Would rewrite' if dry else 'Rewrote'} {n} file(s) under {root}")
    print(f"total={'would be ' if dry else ''}{total}")


if __name__ == "__main__":
    main()
