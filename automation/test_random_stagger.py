#!/usr/bin/env python3
"""Verify group / playlist timing helpers produce varied delays in expected ranges."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_AUTOMATION_DIR = Path(__file__).resolve().parent
if str(_AUTOMATION_DIR) not in sys.path:
    sys.path.insert(0, str(_AUTOMATION_DIR))

import human_variation as hv  # noqa: E402


class RandomStaggerTests(unittest.TestCase):
    def test_sequence_start_gap_in_range(self) -> None:
        rng = hv.rng_for_run("phone-a", 1)
        samples = [hv.sequence_start_gap_seconds(rng) for _ in range(40)]
        self.assertTrue(all(hv.SEQUENCE_START_GAP_MIN <= s <= hv.SEQUENCE_START_GAP_MAX for s in samples))
        self.assertGreater(len(set(round(s, 3) for s in samples)), 1)

    def test_playlist_cycle_pause_in_range(self) -> None:
        rng = hv.rng_for_run("phone-b", 2)
        samples = [hv.playlist_cycle_pause_seconds(rng) for _ in range(40)]
        self.assertTrue(all(hv.PLAYLIST_CYCLE_PAUSE_MIN <= s <= hv.PLAYLIST_CYCLE_PAUSE_MAX for s in samples))
        self.assertGreater(len(set(round(s, 3) for s in samples)), 1)

    def test_group_stagger_jitter_not_constant(self) -> None:
        group = {"stagger_secs": 30, "human_stagger": True}
        rng = hv.rng_for_run("phone-c", 3)
        lo = 30 * (1.0 - hv.GROUP_STAGGER_JITTER_FRAC)
        hi = 30 * (1.0 + hv.GROUP_STAGGER_JITTER_FRAC)
        samples = [hv.group_stagger_seconds(group, rng) for _ in range(40)]
        self.assertTrue(all(lo <= s <= hi for s in samples))
        self.assertGreater(len(set(round(s, 2) for s in samples)), 1)

    def test_group_stagger_min_max(self) -> None:
        group = {"stagger_secs": 99, "stagger_min": 5, "stagger_max": 12}
        rng = hv.rng_for_run("phone-d", 4)
        samples = [hv.group_stagger_seconds(group, rng) for _ in range(40)]
        self.assertTrue(all(5.0 <= s <= 12.0 for s in samples))

    def test_group_stagger_fixed_when_human_stagger_off(self) -> None:
        group = {"stagger_secs": 30, "human_stagger": False}
        rng = hv.rng_for_run("phone-e", 5)
        samples = [hv.group_stagger_seconds(group, rng) for _ in range(5)]
        self.assertEqual(samples, [30.0, 30.0, 30.0, 30.0, 30.0])


if __name__ == "__main__":
    unittest.main()
