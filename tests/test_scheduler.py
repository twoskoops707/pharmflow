"""Tests for automation/scheduler.py (live quota scheduler)."""

from __future__ import annotations

import unittest
from datetime import datetime
from zoneinfo import ZoneInfo

from automation.config import SCHED_ACTIVE_HOUR_END, SCHED_ACTIVE_HOUR_START
from automation.scheduler import (
    _ALLOWED_STEP_TYPES,
    _gen_today,
    _has_age_verification_marker,
    _hour_in_exit_daytime,
    plan_scheduler_start,
    timezone_for_exit_country,
)
from automation.tor_manager import country_from_control_reply


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

    def test_exit_daytime_times_stay_in_that_zone(self) -> None:
        times = _gen_today(8, spread="uniform", tz="Europe/Berlin")
        self.assertEqual(len(times), 8)
        zone = ZoneInfo("Europe/Berlin")
        hours = [datetime.fromtimestamp(t, zone).hour for t in times]
        self.assertTrue(hours)
        self.assertTrue(
            all(_hour_in_exit_daytime(hour, SCHED_ACTIVE_HOUR_START, SCHED_ACTIVE_HOUR_END) for hour in hours)
        )

    def test_unknown_zone_does_not_fall_back_to_host_clock(self) -> None:
        self.assertEqual(_gen_today(4, tz="Not/AZone"), [])

    def test_start_keeps_each_phones_steps_and_hits(self) -> None:
        plan = plan_scheduler_start({
            "serials": ["10.0.2.15:5555", "10.0.2.16:5555"],
            "steps": [{"type": "wait"}],
            "hits_per_day": 3,
            "steps_per_serial": {
                "10.0.2.15:5555": [{"type": "launch_app", "package": "com.example"}],
            },
            "hits_per_serial": {"10.0.2.16:5555": 9},
            "schedule_spread": "uniform",
            "schedule_tor_local": False,
        })
        self.assertNotIn("error", plan)
        by_serial = {job["serial"]: job for job in plan["jobs"]}
        self.assertEqual(by_serial["10.0.2.15:5555"]["steps"][0]["type"], "launch_app")
        self.assertEqual(by_serial["10.0.2.16:5555"]["hits"], 9)
        self.assertEqual(by_serial["10.0.2.16:5555"]["steps"][0]["type"], "wait")
        self.assertEqual(len(by_serial["10.0.2.16:5555"]["times"]), 9)

    def test_exit_country_option_does_not_place_host_times(self) -> None:
        plan = plan_scheduler_start({
            "serials": ["emulator-5554"],
            "steps": [{"type": "open_url"}],
            "hits_per_day": 4,
            "schedule_tor_local": True,
        })
        self.assertTrue(plan["tor_local"])
        self.assertEqual(plan["jobs"][0]["times"], [])
        self.assertIn("launch_app", _ALLOWED_STEP_TYPES)

    def test_exit_country_reply_and_timezone(self) -> None:
        self.assertEqual(
            country_from_control_reply("250-ip-to-country/1.2.3.4=de\r\n250 OK\r\n"),
            "DE",
        )
        self.assertEqual(country_from_control_reply("551 unknown"), "")
        self.assertEqual(timezone_for_exit_country("DE"), "Europe/Berlin")
        self.assertEqual(timezone_for_exit_country("??"), "")


if __name__ == "__main__":
    unittest.main()
