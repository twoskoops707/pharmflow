"""Tests for automation/scheduler.py cron registration."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from automation.group_manager import GroupManager, PhoneGroup
from automation.scheduler import FarmScheduler


class SchedulerReloadTests(unittest.TestCase):
    def test_reload_schedules_registers_group_cron(self) -> None:
        farm = MagicMock()
        runner = MagicMock()
        groups = GroupManager.__new__(GroupManager)
        groups.groups = {
            "TeamA": PhoneGroup(
                name="TeamA",
                phones=["Phone-1"],
                schedule_cron="0 */6 * * *",
            )
        }
        groups.list_groups = lambda: [{"name": "TeamA", "schedule_cron": "0 */6 * * *"}]
        groups.get_group = lambda name: groups.groups.get(name)

        sched = FarmScheduler(farm, MagicMock(), groups)
        sched.runner = runner
        sched.start()

        with patch("automation.scheduler.run_group", return_value={"success": True}) as mock_run:
            n = sched.reload_schedules()
            self.assertEqual(n, 1)
            jobs = sched.list_jobs()
            self.assertEqual(len(jobs), 1)
            self.assertEqual(jobs[0]["id"], "group_cron_TeamA")

            # Execute the scheduled callable once (APScheduler stores it on the job)
            job = sched.scheduler.get_job("group_cron_TeamA")
            assert job is not None
            job.func()
            mock_run.assert_called_once()

        sched.stop()

    def test_reload_skips_empty_cron(self) -> None:
        farm = MagicMock()
        groups = GroupManager.__new__(GroupManager)
        groups.groups = {"TeamB": PhoneGroup(name="TeamB", phones=[], schedule_cron="")}
        groups.list_groups = lambda: [{"name": "TeamB"}]
        groups.get_group = lambda name: groups.groups.get(name)

        sched = FarmScheduler(farm, MagicMock(), groups)
        sched.start()
        self.assertEqual(sched.reload_schedules(), 0)
        self.assertEqual(sched.list_jobs(), [])
        sched.stop()


if __name__ == "__main__":
    unittest.main()
