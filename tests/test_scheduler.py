"""Tests for automation/scheduler.py (live quota scheduler)."""

from __future__ import annotations

import unittest

from automation.scheduler import _gen_today, _has_age_verification_marker


class SchedulerCoreTests(unittest.TestCase):
    def test_gen_today_spreads_hits_across_day(self) -> None:
        times = _gen_today(12)
        self.assertEqual(len(times), 12)
        # All fire-times fall within the next 24h and are unique.
        self.assertEqual(len(set(times)), 12)
        span = max(times) - min(times)
        self.assertGreater(span, 0)

    def test_gen_today_zero_hits(self) -> None:
        self.assertEqual(_gen_today(0), [])

    def test_age_verification_marker_detection(self) -> None:
        self.assertTrue(
            _has_age_verification_marker([{"type": "tap", "age_verification": True}])
        )
        self.assertTrue(
            _has_age_verification_marker([{"type": "wait", "age_gate": True}])
        )
        self.assertTrue(
            _has_age_verification_marker([{"type": "tap", "checkpoint": "age_gate"}])
        )
        self.assertFalse(_has_age_verification_marker([{"type": "tap"}, {"type": "wait"}]))
        self.assertFalse(_has_age_verification_marker(None))


if __name__ == "__main__":
    unittest.main()