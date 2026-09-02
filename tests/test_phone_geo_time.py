"""Tests for awake-hour geo/timezone assignment."""

from __future__ import annotations

import unittest
from datetime import datetime, time, timezone

from automation.phone_geo_time import (
    GEO_CATALOG,
    local_in_window,
    locales_in_window,
    pick_locales_for_phones,
)


class PhoneGeoTimeTests(unittest.TestCase):
    def test_berlin_morning_utc(self) -> None:
        # 08:00 UTC in July → Berlin CEST (UTC+2) = 10:00 — inside 09:30–00:00
        now = datetime(2026, 7, 13, 8, 0, tzinfo=timezone.utc)
        self.assertTrue(local_in_window(now, "Europe/Berlin", time(9, 30), time(0, 0)))

    def test_la_night_excluded(self) -> None:
        # 08:00 UTC → America/Los_Angeles = 01:00 — outside window
        now = datetime(2026, 7, 13, 8, 0, tzinfo=timezone.utc)
        self.assertFalse(local_in_window(now, "America/Los_Angeles", time(9, 30), time(0, 0)))

    def test_eligible_pool_at_utc_morning(self) -> None:
        now = datetime(2026, 7, 13, 8, 17, tzinfo=timezone.utc)
        eligible = locales_in_window(now)
        self.assertGreaterEqual(len(eligible), 6)
        names = {e.tz for e in eligible}
        self.assertIn("Europe/Berlin", names)
        self.assertNotIn("America/Los_Angeles", names)  # US West still asleep
        self.assertTrue(all(e.tz != "America/Los_Angeles" for e in eligible))

    def test_us_paying_markets_preferred_during_us_day(self) -> None:
        # 18:40 UTC → 11:40 PDT — US geos dominate the window (12/18 in-window)
        # with a couple of awake non-US geos rounding out the 6 picks.
        now = datetime(2026, 8, 18, 18, 40, tzinfo=timezone.utc)
        picks = pick_locales_for_phones(6, now_utc=now)
        self.assertEqual(len(picks), 6)
        us = [p for p in picks if p.country == "USA"]
        self.assertGreaterEqual(len(us), 3)  # US majority, not exclusivity
        self.assertGreaterEqual(len({p.city for p in picks}), 4)

    def test_pick_six_distinct_when_possible(self) -> None:
        now = datetime(2026, 7, 13, 8, 17, tzinfo=timezone.utc)
        picks = pick_locales_for_phones(6, now_utc=now)
        self.assertEqual(len(picks), 6)
        # Prefer uniqueness
        self.assertGreaterEqual(len({p.tz for p in picks}), 4)


if __name__ == "__main__":
    unittest.main()
