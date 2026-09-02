"""timer_complete waits must never be shortened by human variation or humanize."""

from __future__ import annotations

import random
import sys
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))
WIZARD_DIR = SCRIPT_DIR.parent / "wizard"
if str(WIZARD_DIR) not in sys.path:
    sys.path.insert(0, str(WIZARD_DIR))

import human_variation as hv  # noqa: E402
from dabflow_timer import all_combo_waits, timer_wait_seconds  # noqa: E402
from sequence_humanize import humanize_steps  # noqa: E402
from sequence_normalize import step_is_timer_complete_wait  # noqa: E402


class TimerCompleteWaitTests(unittest.TestCase):
    def test_step_helper(self):
        step = {"type": "wait", "seconds": 90.5, "checkpoint": "timer_complete"}
        self.assertTrue(step_is_timer_complete_wait(step))
        self.assertFalse(step_is_timer_complete_wait({"type": "wait", "seconds": 1}))

    def test_scaled_wait_seconds_never_shortens_timer_complete(self):
        base = timer_wait_seconds("ceramic", "distillate", "propane")
        rng = random.Random(0)
        for _ in range(200):
            got = hv.scaled_wait_seconds(base, rng, checkpoint="timer_complete")
            self.assertEqual(got, base)

    def test_scaled_wait_seconds_can_shorten_other_waits(self):
        rng = random.Random(1)
        got = hv.scaled_wait_seconds(1.0, rng, checkpoint="selections_done")
        self.assertLess(got, 1.0)

    def test_humanize_preserves_timer_complete_seconds(self):
        steps = [
            {"type": "wait", "seconds": 90.5, "checkpoint": "timer_complete"},
            {"type": "wait", "seconds": 0.5},
        ]
        out = humanize_steps(steps, random.Random(99))
        self.assertEqual(out[0]["seconds"], 90.5)
        self.assertNotEqual(out[1]["seconds"], 0.5)

    def test_all_combo_waits_are_distinct_per_formula(self):
        waits = [t.wait_seconds for *_, t in all_combo_waits()]
        self.assertEqual(len(waits), 60)
        self.assertGreater(len(set(waits)), 1)
        self.assertAlmostEqual(min(waits), 75.5)
        self.assertAlmostEqual(max(waits), 111.5)

    def test_ceramic_distillate_propane_demo_wait(self):
        self.assertEqual(timer_wait_seconds("ceramic", "distillate", "propane"), 90.5)


if __name__ == "__main__":
    unittest.main()
