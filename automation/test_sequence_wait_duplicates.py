from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

_automation_dir = Path(__file__).resolve().parent
if str(_automation_dir) not in sys.path:
    sys.path.insert(0, str(_automation_dir))

from sequence_normalize import merge_consecutive_waits, normalize_automation_steps, unwrap_sequence_document
from sequence_step_audit import find_consecutive_duplicate_violations
from sequences_paths import fixtures_sequences_dir, resolve_sequences_dir


def _sequence_dirs() -> list[Path]:
    dirs: list[Path] = []
    local = resolve_sequences_dir(create=False)
    if local.is_dir():
        dirs.append(local)
    fx = fixtures_sequences_dir()
    if fx.is_dir():
        dirs.append(fx)
    return dirs


class TestNoConsecutiveDuplicateCommands(unittest.TestCase):
    def test_sequence_files_have_no_consecutive_waits(self) -> None:
        files: list[Path] = []
        for seq_dir in _sequence_dirs():
            files.extend(
                sorted(p for p in seq_dir.rglob("*.json") if not p.name.startswith("_"))
            )
        self.assertTrue(files, "No sequence files under local PharmFlow/sequences or test fixtures")

        violations: list[str] = []
        for fp in files:
            payload = json.loads(fp.read_text(encoding="utf-8"))
            steps, _meta = unwrap_sequence_document(payload)
            violations.extend(
                find_consecutive_duplicate_violations(steps, label=str(fp))
            )

        self.assertFalse(
            violations,
            "Consecutive duplicate commands found:\n" + "\n".join(violations[:50]),
        )

    def test_merge_consecutive_waits_preserves_timer_complete(self) -> None:
        steps = [
            {"type": "wait", "seconds": 0.5},
            {"type": "wait", "seconds": 90.5, "checkpoint": "timer_complete"},
        ]
        merged = merge_consecutive_waits(steps)
        self.assertEqual(len(merged), 2)
        self.assertEqual(merged[0]["seconds"], 0.5)
        self.assertEqual(merged[1]["seconds"], 90.5)
        self.assertEqual(merged[1]["checkpoint"], "timer_complete")

    def test_normalize_collapses_duplicate_taps_keeps_higher_retries(self) -> None:
        steps = [
            {"type": "tap", "x": 100, "y": 200, "retries": 2},
            {"type": "tap", "x": 100, "y": 200, "retries": 5},
        ]
        out = normalize_automation_steps(steps)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["retries"], 5)

    def test_normalize_keeps_operator_wait_retries_and_swipe(self) -> None:
        steps = [
            {"type": "wait", "seconds": 900},
            {"type": "wait", "seconds": 200},
            {"type": "tap", "x": 10, "y": 20, "retries": 12, "jitter": 200, "pre_wait_ms": 15000},
            {"type": "swipe", "x1": 1, "y1": 2, "x2": 3, "y2": 4, "ms": 8000},
            {"type": "open_url", "url": "https://example.com", "post_wait_secs": 180},
        ]
        out = normalize_automation_steps(steps)
        waits = [s for s in out if s.get("type") == "wait"]
        self.assertEqual(len(waits), 1)
        self.assertEqual(waits[0]["seconds"], 1100)
        tap = next(s for s in out if s.get("type") == "tap")
        self.assertEqual(tap["retries"], 12)
        self.assertEqual(tap["jitter"], 200)
        self.assertEqual(tap["pre_wait_ms"], 15000)
        swipe = next(s for s in out if s.get("type") == "swipe")
        self.assertEqual(swipe["ms"], 8000)
        opened = next(s for s in out if s.get("type") == "open_url")
        self.assertEqual(opened["post_wait_secs"], 180)


if __name__ == "__main__":
    unittest.main()
