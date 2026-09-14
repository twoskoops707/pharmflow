"""Tests for full-hour farm pacing and pronounced startup staggering."""

from __future__ import annotations

import os
import random
import tempfile
import unittest
import unittest.mock
from pathlib import Path

from automation.site_profile import interview_defaults
from automation.site_sequence_gen import write_profile_sequences
from scripts import run_farm_354 as farm


class FarmSchedulingTests(unittest.TestCase):
    def test_slots_span_hour_without_front_loading(self) -> None:
        slots = farm._schedule_hour_seq_slots(
            random.Random(42),
            phone_idx=2,
            minute_now=0,
            second_now=0.0,
        )
        # Randomized spacing/jitter may drop 1 near the lead cutoff.
        self.assertGreaterEqual(len(slots), farm.SEQS_PER_HOUR - 2)
        self.assertGreater(slots[-1] - slots[0], 2500.0)
        self.assertGreaterEqual(min(slots), farm.SLOT_MIN_LEAD_S)
        self.assertTrue(all(a < b for a, b in zip(slots, slots[1:])))

    def test_mid_hour_restart_drops_backlog_and_keeps_lead(self) -> None:
        slots = farm._schedule_hour_seq_slots(
            random.Random(7),
            phone_idx=1,
            minute_now=31,
            second_now=20.0,
        )
        cutoff = 31 * 60 + 20 + farm.SLOT_MIN_LEAD_S
        self.assertTrue(slots)
        self.assertTrue(all(slot >= cutoff for slot in slots))

    def test_startup_delays_are_random_with_min_gap(self) -> None:
        delays = farm._random_phone_start_delays(4, random.Random(42))
        self.assertEqual(len(delays), 4)
        self.assertTrue(all(0.0 <= d <= farm.START_STAGGER_WINDOW_S + 1.0 for d in delays))
        # Same seed should reshuffle assignment but gaps on the sorted timeline hold.
        ordered = sorted(delays)
        for a, b in zip(ordered, ordered[1:]):
            self.assertGreaterEqual(b - a, farm.START_STAGGER_MIN_GAP_S * 0.5)
        # Not the old fixed vm0→vm3 band order (0, 300, 600, 900).
        self.assertNotEqual(delays, sorted(delays))

    def test_nonad_draw_without_replacement_then_resets(self) -> None:
        pools = {
            "ad": [],
            "complete": [Path(f"seq_{i}_complete.json") for i in range(5)],
            "halfway": [],
        }
        used: set[str] = set()
        rng = random.Random(1)
        original = farm._preflight
        farm._preflight = lambda *a, **k: None  # type: ignore[assignment]
        try:
            picked = []
            for _ in range(5):
                cand = farm._pick(
                    pools,
                    want_ads=False,
                    rng=rng,
                    active_keys=set(),
                    used_stems=used,
                    last_ad=[None],
                    recent=[],
                    recent_ad_keys=[],
                    recent_combos=[],
                    recent_stems=[],
                )
                self.assertIsNotNone(cand)
                assert cand is not None
                used.add(cand.stem)
                picked.append(cand.stem)
            self.assertEqual(len(set(picked)), 5, "no repeats until pool exhausts")
            # Sixth pick: pool exhausted -> pass resets and a stem is reusable.
            cand = farm._pick(
                pools,
                want_ads=False,
                rng=rng,
                active_keys=set(),
                used_stems=used,
                last_ad=[None],
                recent=[],
                recent_ad_keys=[],
                recent_combos=[],
                recent_stems=[],
            )
            self.assertIsNotNone(cand)
            self.assertLess(len(used), 5, "used ledger reset on new pass")
        finally:
            farm._preflight = original  # type: ignore[assignment]

    def test_ad_pick_never_back_to_back(self) -> None:
        os.environ["PHARMFLOW_FARM_ALLOW_ADS"] = "1"
        os.environ["PHARMFLOW_FARM_PATHS"] = "1,2,3"
        pools = {
            "ad": [Path("home_homead1_ad.json"), Path("home_homead2_ad.json")],
            "complete": [],
            "halfway": [],
        }
        rng = random.Random(3)
        original = farm._preflight
        farm._preflight = lambda *a, **k: None  # type: ignore[assignment]
        try:
            for _ in range(12):
                cand = farm._pick(
                    pools,
                    want_ads=True,
                    rng=rng,
                    active_keys=set(),
                    used_stems=set(),
                    last_ad=["home_homead1_ad"],
                    recent=[],
                    recent_ad_keys=[],
                    recent_combos=[],
                    recent_stems=[],
                )
                self.assertIsNotNone(cand)
                assert cand is not None
                self.assertNotEqual(cand.stem, "home_homead1_ad")
        finally:
            farm._preflight = original  # type: ignore[assignment]

    def test_generic_site_sequences_pass_non_dabflow_preflight(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            profile = interview_defaults(
                kind="website",
                name="Example",
                url="https://example.com",
            )
            write_profile_sequences(profile, root, clean=True)
            files = list((root / profile.slug).glob("*.json"))
            sequence_files = [path for path in files if path.name != "_generated.json"]
            self.assertTrue(sequence_files)
            self.assertTrue(all(farm._preflight(path, strict=True) is None for path in sequence_files))

    def test_saved_earn_plan_overrides_visit_caps_and_a_missing_file_does_not(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            env = {
                "PHARMFLOW_LOGS": str(root),
                "PHARMFLOW_FARM_DAILY_VISITS": "11",
                "PHARMFLOW_FARM_DAILY_ADS": "1",
                "PHARMFLOW_FARM_ALLOW_ADS": "0",
                "PHARMFLOW_FARM_PATHS": "1,2",
            }
            with unittest.mock.patch.dict(os.environ, env, clear=False):
                self.assertEqual(farm._phone_visits_cap(0), 11)
                self.assertFalse(farm._ads_allowed())
                from automation.earn_plan import save_earn_plan

                saved = save_earn_plan(
                    {
                        "phones": 2,
                        "visits_per_phone": 40,
                        "ads_allowed": True,
                        "visits_per_paid_action": 20,
                        "path2_share": 0.25,
                        "spread_seed": 9,
                    },
                    root / "earn_plan.json",
                )
                self.assertTrue(saved["saved"])
                self.assertEqual(sum(saved["visits_by_phone"]), 80)
                self.assertNotEqual(saved["visits_by_phone"][0], saved["visits_by_phone"][1])
                self.assertEqual(farm._phone_visits_cap(0), saved["visits_by_phone"][0])
                self.assertEqual(farm._phone_visits_cap(1), saved["visits_by_phone"][1])
                self.assertEqual(farm._phone_ads_cap(0), saved["path3_by_phone"][0])
                self.assertTrue(farm._ads_allowed())
                self.assertEqual(farm._farm_paths(), {"1", "2", "3"})
                self.assertEqual(farm._halfway_share(), 0.25)
                self.assertEqual(farm._path3_per_hour(0), saved["path3_by_phone"][0])
                self.assertEqual(farm._path3_per_hour(1), saved["path3_by_phone"][1])
                # Extra live phones still get a count around the mean, not a shrink.
                self.assertGreater(farm._phone_visits_cap(5), 0)


if __name__ == "__main__":
    unittest.main()
