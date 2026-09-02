"""Verify sequence matrices are snowflakes — not identical timing clones."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

_automation_dir = Path(__file__).resolve().parent
if str(_automation_dir) not in sys.path:
    sys.path.insert(0, str(_automation_dir))

from dabflow_timer import CONCENTRATES, HEATERS, MATERIALS  # noqa: E402
from sequence_normalize import unwrap_sequence_document  # noqa: E402
from sequences_paths import resolve_sequences_dir  # noqa: E402


def _micro_wait_fingerprint(steps: list[dict]) -> tuple[float, ...]:
    """Fingerprint of non-timer micro-waits (excludes timer_complete / heat waits)."""
    out: list[float] = []
    for step in steps:
        if step.get("type") != "wait":
            continue
        cp = step.get("checkpoint") or ""
        if cp in ("timer_complete", "timer_heat_complete"):
            continue
        secs = float(step.get("seconds", 0.0))
        if secs >= 30.0:
            continue
        out.append(round(secs, 3))
    return tuple(out)


class TestSequenceSnowflakeHumanization(unittest.TestCase):
    def test_dabflow_combo_differs_across_resolutions(self) -> None:
        root = resolve_sequences_dir(create=False)
        mat, conc, heat = "ceramic", "distillate", "propane"
        fname = f"dabflow__ad__mat-{mat}__conc-{conc}__heat-{heat}.json"
        fps = [
            root / res / "ad" / fname
            for res in ("540x960", "720x1280", "900x1600", "1080x1920")
        ]
        if not all(p.is_file() for p in fps):
            self.skipTest("dabflow ad sample missing — run generate_dabflow_gold_matrix.py")

        prints = []
        for fp in fps:
            payload = json.loads(fp.read_text(encoding="utf-8"))
            steps, _ = unwrap_sequence_document(payload)
            prints.append(_micro_wait_fingerprint(steps))

        self.assertGreater(len(set(prints)), 1, "all resolutions share identical micro-wait fingerprint")

    def test_dabflow_matrix_not_all_identical(self) -> None:
        root = resolve_sequences_dir(create=False)
        sample: list[tuple[float, ...]] = []
        for mat in MATERIALS[:2]:
            for conc in CONCENTRATES[:2]:
                for heat in HEATERS[:2]:
                    fp = root / "900x1600" / "no-ad" / (
                        f"dabflow__no_ads__mat-{mat}__conc-{conc}__heat-{heat}.json"
                    )
                    if not fp.is_file():
                        continue
                    payload = json.loads(fp.read_text(encoding="utf-8"))
                    steps, _ = unwrap_sequence_document(payload)
                    sample.append(_micro_wait_fingerprint(steps))
        self.assertGreaterEqual(len(sample), 4)
        self.assertGreater(len(set(sample)), 1, "sampled dabflow files all identical")

    def test_home_combo_sequences_differ(self) -> None:
        seq_dir = _automation_dir / "recordings" / "sequences"
        files = sorted(seq_dir.glob("*.json"))[:12]
        if len(files) < 4:
            self.skipTest("home combo sequences not generated yet")
        prints = []
        for fp in files:
            steps = json.loads(fp.read_text(encoding="utf-8"))
            if isinstance(steps, dict):
                steps, _ = unwrap_sequence_document(steps)
            prints.append(_micro_wait_fingerprint(steps))
        self.assertGreater(len(set(prints)), 1, "home combo sample files all identical")


if __name__ == "__main__":
    unittest.main()
