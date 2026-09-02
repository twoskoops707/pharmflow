#!/usr/bin/env python3
"""Fail CI when shipped sequence matrices are incomplete."""
from __future__ import annotations

import json
import sys
from pathlib import Path

_AUTOMATION = Path(__file__).resolve().parent
if str(_AUTOMATION) not in sys.path:
    sys.path.insert(0, str(_AUTOMATION))

from dabflow_timer import CONCENTRATES, HEATERS, MATERIALS  # noqa: E402
from sequences_paths import resolve_sequences_dir  # noqa: E402

REPO_ROOT = _AUTOMATION.parent
HOME_COMBO_DIR = _AUTOMATION / "recordings" / "sequences"
RENAME_MAP_PATH = _AUTOMATION / "recordings" / "_sequence_rename_basename_map.json"


def _home_combo_paths() -> list[Path]:
    raw = json.loads(RENAME_MAP_PATH.read_text(encoding="utf-8"))
    out: list[Path] = []
    for old_key, new_base in raw.items():
        if not old_key.startswith("sequence_home_combo_v2_"):
            continue
        p = HOME_COMBO_DIR / new_base
        if p.is_file():
            out.append(p)
    return out

RESOLUTIONS = ("540x960", "720x1280", "900x1600", "1080x1920")
RESOLUTION_COUNT = len(RESOLUTIONS)
COMBO_COUNT = len(MATERIALS) * len(CONCENTRATES) * len(HEATERS)
# Shipped tree has combo-matrix basenames plus humanized gold (timer1x/timer2x) per combo.
MATRIX_FILES_PER_FLOW = COMBO_COUNT * 2
HALF_MATRIX_FILES_PER_FLOW = COMBO_COUNT
DABFLOW_MATRIX = MATRIX_FILES_PER_FLOW * RESOLUTION_COUNT * 2  # ad + no-ad
HALF_DABFLOW_MATRIX = HALF_MATRIX_FILES_PER_FLOW * RESOLUTION_COUNT * 2
DABFLOW_DEMOS = 2 * RESOLUTION_COUNT
DABFLOW_EARLY_EXIT = 7 * RESOLUTION_COUNT
MANTIS_HARDCODE_TESTS = 5 * RESOLUTION_COUNT
_DABFLOW_TOTALS = {
    DABFLOW_MATRIX + DABFLOW_DEMOS + DABFLOW_EARLY_EXIT + MANTIS_HARDCODE_TESTS,
    HALF_DABFLOW_MATRIX + DABFLOW_DEMOS + DABFLOW_EARLY_EXIT + MANTIS_HARDCODE_TESTS,
}
HOME_COMBO_TOTAL = 2 * 2 * 3 * 2 * 3 * 2 * 2 * 4  # entry×ad×footer×hero×bottom×timer×postad×branch


def _count_dabflow(root: Path) -> dict[str, int]:
    counts = {"matrix": 0, "demos": 0, "early_exit": 0, "mantis_hardcode": 0, "other": 0}
    for fp in root.rglob("dabflow*.json"):
        name = fp.name
        rel = fp.relative_to(root).as_posix()
        if "/mantis-hardcode/" in rel and name.startswith("dabflow__mantis_hardcode__"):
            counts["mantis_hardcode"] += 1
        elif "/early-exit/" in rel:
            counts["early_exit"] += 1
        elif name.startswith("dabflow__demo__"):
            counts["demos"] += 1
        elif name.startswith("dabflow__ad__") or name.startswith("dabflow__no_ads__"):
            counts["matrix"] += 1
        else:
            counts["other"] += 1
    return counts


def main() -> int:
    root = resolve_sequences_dir(create=False)
    if not root.is_dir():
        print(f"FAILED: sequences root missing: {root}")
        return 1

    summary_path = root / "_dabflow_matrix_summary.json"
    matrix_expected = DABFLOW_MATRIX
    per_flow_expected = MATRIX_FILES_PER_FLOW + 1  # matrix variants + demo ONE or TWO

    if summary_path.is_file():
        summary = json.loads(summary_path.read_text(encoding="utf-8"))
        summary_total = summary.get("total_json")
        if summary_total not in (DABFLOW_MATRIX, HALF_DABFLOW_MATRIX):
            print(
                f"FAILED: _dabflow_matrix_summary total_json={summary_total} "
                f"expected {DABFLOW_MATRIX} (or legacy half-matrix {HALF_DABFLOW_MATRIX})"
            )
            return 1
        # Do not force local files to match summary mode; validate against actual file counts below.

    dab = _count_dabflow(root)
    dab_total = sum(dab.values())
    errors: list[str] = []

    if dab["matrix"] == HALF_DABFLOW_MATRIX:
        matrix_expected = HALF_DABFLOW_MATRIX
        per_flow_expected = HALF_MATRIX_FILES_PER_FLOW + 1
    elif dab["matrix"] == DABFLOW_MATRIX:
        matrix_expected = DABFLOW_MATRIX
        per_flow_expected = MATRIX_FILES_PER_FLOW + 1

    if dab["matrix"] != matrix_expected:
        errors.append(f"dabflow matrix files: got {dab['matrix']}, want {matrix_expected}")
    if dab["demos"] != DABFLOW_DEMOS:
        errors.append(f"dabflow demos: got {dab['demos']}, want {DABFLOW_DEMOS}")
    if dab["early_exit"] != DABFLOW_EARLY_EXIT:
        errors.append(f"dabflow early-exit: got {dab['early_exit']}, want {DABFLOW_EARLY_EXIT}")
    if dab["mantis_hardcode"] != MANTIS_HARDCODE_TESTS:
        errors.append(
            f"dabflow mantis-hardcode tests: got {dab['mantis_hardcode']}, want {MANTIS_HARDCODE_TESTS}"
        )
    if dab["other"]:
        errors.append(f"unexpected dabflow files: {dab['other']}")

    for res in RESOLUTIONS:
        for flow in ("ad", "no-ad"):
            d = root / res / flow
            if not d.is_dir():
                errors.append(f"missing folder {res}/{flow}")
                continue
            n = len(list(d.glob("dabflow__*.json")))
            if n != per_flow_expected:
                errors.append(f"{res}/{flow}: got {n} dabflow JSON, want {per_flow_expected}")

        early_dir = root / res / "no-ad" / "early-exit"
        if not early_dir.is_dir():
            errors.append(f"missing {res}/no-ad/early-exit/")
        else:
            n_early = len(list(early_dir.glob("dabflow__early_exit__*.json")))
            if n_early != 7:
                errors.append(f"{res}/no-ad/early-exit: got {n_early}, want 7")

        hardcode_dir = root / res / "ad" / "mantis-hardcode"
        if not hardcode_dir.is_dir():
            errors.append(f"missing {res}/ad/mantis-hardcode/")
        else:
            n_mantis = len(list(hardcode_dir.glob("dabflow__mantis_hardcode__*.json")))
            if n_mantis != 5:
                errors.append(f"{res}/ad/mantis-hardcode: got {n_mantis}, want 5")

    home_count = len(_home_combo_paths())
    if home_count > 0 and home_count != HOME_COMBO_TOTAL:
        errors.append(f"home-combo sequences: got {home_count}, want {HOME_COMBO_TOTAL}")

    if errors:
        print("FAILED: sequence matrix count check")
        for err in errors:
            print(f"  - {err}")
        return 1

    grand = dab_total + home_count
    if dab_total not in _DABFLOW_TOTALS:
        errors.append(f"dabflow total: got {dab_total}, expected one of {sorted(_DABFLOW_TOTALS)}")
        print("FAILED: sequence matrix count check")
        for err in errors:
            print(f"  - {err}")
        return 1

    print(
        f"OK: dabflow={dab_total} ({matrix_expected} matrix + {DABFLOW_DEMOS} demos + "
        f"{DABFLOW_EARLY_EXIT} early-exit + {MANTIS_HARDCODE_TESTS} mantis-hardcode), "
        f"home-combo={home_count}, total={grand}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
