#!/usr/bin/env python3
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path

from sequence_normalize import load_sequence_steps_ui
from sequence_geometry import scale_point


ROOT = Path(__file__).resolve().parents[1]
SEQUENCE_DIR = ROOT / "automation" / "recordings" / "sequences"
RENAME_MAP_PATH = ROOT / "automation" / "recordings" / "_sequence_rename_basename_map.json"


def _combo_matrix_paths() -> list[Path]:
    """Paths for the former ``sequence_home_combo_v2_*.json`` matrix (event-chain names)."""
    raw = json.loads(RENAME_MAP_PATH.read_text(encoding="utf-8"))
    out: list[Path] = []
    for old_key, new_base in raw.items():
        if not old_key.startswith("sequence_home_combo_v2_"):
            continue
        p = SEQUENCE_DIR / new_base
        if p.is_file():
            out.append(p)
    return sorted(out, key=lambda x: x.name)


def _branch_from_name(name: str) -> str:
    token = "_branch-"
    if token not in name:
        return "unknown"
    return name.split(token, 1)[1].removesuffix(".json")


def main() -> int:
    files = _combo_matrix_paths()
    if not files:
        raise SystemExit(
            "FAILED: no home-combo matrix sequences (check "
            f"{RENAME_MAP_PATH.relative_to(ROOT)} for sequence_home_combo_v2_* keys)"
        )

    by_branch: dict[str, list[str]] = defaultdict(list)
    checked_steps = 0
    checked_coordinate_steps = 0
    failures: list[str] = []
    for path in files:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            steps, _meta = load_sequence_steps_ui(raw)
            if not isinstance(steps, list):
                failures.append(f"{path.name}: loader returned non-list steps")
                continue
            wrapped_steps, _wrapped_meta = load_sequence_steps_ui({"steps": steps, "label": "smoke"})
            if len(wrapped_steps) != len(steps):
                failures.append(f"{path.name}: wrapped loader changed step count")
                continue
            for idx, step in enumerate(steps):
                if not isinstance(step, dict):
                    continue
                checked_steps += 1
                stype = str(step.get("type", ""))
                if stype not in ("tap", "swipe"):
                    continue
                checked_coordinate_steps += 1
                bw = step.get("base_w")
                bh = step.get("base_h")
                if not isinstance(bw, int) or not isinstance(bh, int) or bw <= 0 or bh <= 0:
                    failures.append(
                        f"{path.name}: step {idx} ({stype}) missing valid base_w/base_h metadata"
                    )
                    continue
                # Validate compatibility with runtime wm-size scaling path.
                if stype == "tap":
                    sx, sy = scale_point(
                        int(step.get("x", 0)),
                        int(step.get("y", 0)),
                        1080,
                        1920,
                        bw,
                        bh,
                    )
                    if sx < 0 or sy < 0:
                        failures.append(
                            f"{path.name}: step {idx} ({stype}) failed wm-size scaling"
                        )
                else:
                    for xk, yk in (("x1", "y1"), ("x2", "y2")):
                        sx, sy = scale_point(
                            int(step.get(xk, 0)),
                            int(step.get(yk, 0)),
                            1080,
                            1920,
                            bw,
                            bh,
                        )
                        if sx < 0 or sy < 0:
                            failures.append(
                                f"{path.name}: step {idx} ({stype}) failed wm-size scaling for {xk}/{yk}"
                            )
            by_branch[_branch_from_name(path.name)].append(path.name)
        except Exception as exc:
            msg = str(exc)
            if "json array of steps" in msg.lower():
                failures.append(f"{path.name}: loader rejected with array-only message: {msg}")
            else:
                failures.append(f"{path.name}: {msg}")

    if failures:
        print(f"FAILED: {len(failures)} loader issue(s)")
        for issue in failures:
            print(f"- {issue}")
        return 1

    print(f"OK: loaded {len(files)} home-combo files via UI loader")
    print(f"CHECKED: {checked_steps} total steps")
    print(f"CHECKED: {checked_coordinate_steps} coordinate steps with baseline metadata")
    for branch in sorted(by_branch):
        names = sorted(by_branch[branch])
        print(f"BRANCH {branch}: {len(names)}")
        for name in names:
            print(f"  - {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
