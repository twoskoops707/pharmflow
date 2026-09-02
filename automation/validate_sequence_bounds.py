#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from sequence_geometry import SEQUENCE_BASE_H, SEQUENCE_BASE_W
from sequence_normalize import unwrap_sequence_document


def _as_int(v: Any, default: int) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _check_bounds(path: Path, step: dict[str, Any], idx: int, errors: list[str]) -> None:
    stype = step.get("type")
    if stype not in ("tap", "swipe"):
        return
    bw = _as_int(step.get("base_w"), SEQUENCE_BASE_W)
    bh = _as_int(step.get("base_h"), SEQUENCE_BASE_H)
    if bw <= 0 or bh <= 0:
        errors.append(f"{path}: step {idx} invalid base_w/base_h ({bw},{bh})")
        return
    if stype == "tap":
        x = _as_int(step.get("x"), -1)
        y = _as_int(step.get("y"), -1)
        if x < 0 or y < 0 or x > bw or y > bh:
            errors.append(f"{path}: step {idx} tap out-of-bounds ({x},{y}) for {bw}x{bh}")
        return
    x1 = _as_int(step.get("x1"), -1)
    y1 = _as_int(step.get("y1"), -1)
    x2 = _as_int(step.get("x2"), -1)
    y2 = _as_int(step.get("y2"), -1)
    for label, x, y in (("start", x1, y1), ("end", x2, y2)):
        if x < 0 or y < 0 or x > bw or y > bh:
            errors.append(
                f"{path}: step {idx} swipe {label} out-of-bounds ({x},{y}) for {bw}x{bh}"
            )


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate tap/swipe coordinates are in bounds.")
    default_root = Path(__file__).resolve().parents[1] / "automation" / "recordings" / "sequences"
    parser.add_argument(
        "target",
        nargs="?",
        type=Path,
        default=default_root,
        help="Sequence file or directory (default: automation/recordings/sequences from repo root)",
    )
    args = parser.parse_args()

    root = Path(args.target).resolve()
    files = [root] if root.is_file() else sorted(root.rglob("*.json"))
    errors: list[str] = []
    checked = 0
    for f in files:
        if f.name.startswith("_"):
            continue
        try:
            payload = json.loads(f.read_text(encoding="utf-8"))
            steps, _meta = unwrap_sequence_document(payload)
        except Exception as exc:  # pragma: no cover
            errors.append(f"{f}: parse failure ({exc})")
            continue
        for idx, raw in enumerate(steps):
            if isinstance(raw, dict):
                _check_bounds(f, raw, idx, errors)
        checked += 1

    if errors:
        print(f"FAILED: {len(errors)} bounds issue(s)")
        for issue in errors:
            print(f"- {issue}")
        return 1
    print(f"OK: validated bounds for {checked} JSON file(s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
