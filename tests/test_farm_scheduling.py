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


class DailyBudgetAssumesNoFleetSizeTests(unittest.TestCase):
    """The daily budget state must not invent a fleet: rows are created on demand
    for whatever phone indexes actually record visits (repo rule: no hardcoded
    phone-count ceilings; cf. test_up_without_count_does_not_invent_eight)."""

    def _with_budget_file(self, payload: dict | None):
        import json as _json
        import tempfile as _tf

        tmp = _tf.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = Path(tmp.name) / "farm_daily_budget_state.json"
        if payload is not None:
            path.write_text(_json.dumps(payload), encoding="utf-8")
        patcher = unittest.mock.patch.object(farm, "_daily_budget_path", return_value=path)
        patcher.start()
        self.addCleanup(patcher.stop)
        return path

    @staticmethod
    def _today() -> str:
        from datetime import datetime

        return datetime.now().astimezone().date().isoformat()

    def test_new_day_starts_with_no_invented_rows(self) -> None:
        self._with_budget_file({"date": "1999-01-01", "phones": {"0": {"visits": 5, "ads": 2}}})
        state = farm._load_daily_budget()
        self.assertEqual(state["date"], self._today())
        self.assertEqual(state["phones"], {})  # was 8 seeded rows (range(8))

    def test_high_index_phone_records_and_survives_reload(self) -> None:
        self._with_budget_file({"date": "1999-01-01", "phones": {}})
        row = farm._record_phone_visit(39, path3=True)
        self.assertEqual(row, {"visits": 1, "ads": 1})
        farm._record_phone_visit(39, path3=False)
        reloaded = farm._load_daily_budget()["phones"]
        self.assertEqual(reloaded["39"], {"visits": 2, "ads": 1})

    def test_same_day_carries_over_exactly_the_recorded_phones(self) -> None:
        self._with_budget_file(
            {
                "date": self._today(),
                "phones": {"3": {"visits": 4, "ads": 1}, "41": {"visits": 9, "ads": 3}},
            }
        )
        phones = farm._load_daily_budget()["phones"]
        # Exactly what was recorded -- no dense 0..max fill for phones that don't exist.
        self.assertEqual(set(phones), {"3", "41"})
        self.assertEqual(phones["41"], {"visits": 9, "ads": 3})

    def test_junk_and_malformed_rows_are_tolerated(self) -> None:
        self._with_budget_file(
            {
                "date": self._today(),
                "phones": {"abc": {"visits": 1}, "7": "not-a-row", "8": {"visits": -3, "ads": 2}},
            }
        )
        phones = farm._load_daily_budget()["phones"]
        self.assertNotIn("abc", phones)
        self.assertEqual(phones["7"], {"visits": 0, "ads": 0})
        self.assertEqual(phones["8"], {"visits": 0, "ads": 2})  # negatives clamp to 0

    def test_missing_row_reads_as_empty_not_an_error(self) -> None:
        self._with_budget_file(None)
        state = farm._load_daily_budget()
        self.assertEqual(farm._phone_budget_row(state, 57), {"visits": 0, "ads": 0})

    def test_loader_source_has_no_fixed_fleet_literals(self) -> None:
        import inspect

        src = inspect.getsource(farm._load_daily_budget)
        self.assertNotIn("range(8)", src)
        self.assertNotIn("max_idx = 5", src)


if __name__ == "__main__":
    unittest.main()
