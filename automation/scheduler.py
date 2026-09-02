"""Task scheduler for automated sequence runs."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from automation.group_manager import GroupManager
from automation.group_runner import run_group
from automation.sequence_paths import resolve_sequence_path
from automation.sequence_runner import Sequence, SequenceRunner
from wizard.mumu_farm_ops import MuMuFarmOps

logger = logging.getLogger(__name__)


class FarmScheduler:
    """Schedule automated sequence runs per phone or group."""

    def __init__(
        self,
        farm: MuMuFarmOps,
        sequences_dir: Path,
        group_manager: GroupManager | None = None,
    ) -> None:
        self.farm = farm
        self.sequences_dir = sequences_dir
        self.groups = group_manager or GroupManager()
        self.runner = SequenceRunner(farm)
        self.scheduler = BackgroundScheduler()
        self._job_log: list[dict[str, Any]] = []
        self._on_complete: Callable[[dict[str, Any]], None] | None = None

    def set_on_complete(self, callback: Callable[[dict[str, Any]], None]) -> None:
        self._on_complete = callback

    def start(self) -> None:
        if not self.scheduler.running:
            self.scheduler.start()
            logger.info("Scheduler started")

    def stop(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            logger.info("Scheduler stopped")

    def schedule_sequence(
        self,
        job_id: str,
        sequence_name: str,
        phone: str,
        cron: str | None = None,
        interval_seconds: int | None = None,
    ) -> str:
        """Schedule a sequence by cron expression or interval."""
        seq_path = resolve_sequence_path(self.sequences_dir, sequence_name)
        if not seq_path.is_file():
            raise FileNotFoundError(f"Sequence not found: {sequence_name}")

        def _run() -> None:
            seq = Sequence.from_json(seq_path)
            seq.phone = phone
            report = self.runner.run(seq)
            entry = {"job_id": job_id, "time": datetime.now(timezone.utc).isoformat(), "report": report}
            self._job_log.append(entry)
            logger.info("Scheduled run %s: success=%s", job_id, report.get("success"))
            if self._on_complete:
                self._on_complete(entry)

        if cron:
            trigger = CronTrigger.from_crontab(cron)
        elif interval_seconds:
            trigger = IntervalTrigger(seconds=interval_seconds)
        else:
            raise ValueError("Provide cron or interval_seconds")

        self.scheduler.add_job(_run, trigger=trigger, id=job_id, replace_existing=True)
        return job_id

    def schedule_group(self, group_name: str) -> list[str]:
        """Schedule all phones in a group using group's cron and sequence."""
        group = self.groups.get_group(group_name)
        if not group:
            raise KeyError(f"Group not found: {group_name}")
        job_ids: list[str] = []
        for phone in group.phones:
            if not group.sequence:
                continue
            job_id = f"group_{group_name}_{phone}"
            cron = group.schedule_cron or "0 */6 * * *"
            self.schedule_sequence(job_id, group.sequence, phone, cron=cron)
            job_ids.append(job_id)
        return job_ids

    def reload_schedules(self) -> int:
        """Register cron jobs for every group with a non-empty ``schedule_cron``."""
        prefix = "group_cron_"
        for job in list(self.scheduler.get_jobs()):
            if job.id.startswith(prefix):
                self.remove_job(job.id)

        scheduled = 0
        for summary in self.groups.list_groups():
            group = self.groups.get_group(summary["name"])
            if not group:
                continue
            cron = (group.schedule_cron or "").strip()
            if not cron:
                continue
            group_name = group.name
            job_id = f"{prefix}{group_name}"

            def _run(gn: str = group_name, jid: str = job_id) -> None:
                report = run_group(self.farm, self.groups, self.runner, gn)
                entry = {
                    "job_id": jid,
                    "time": datetime.now(timezone.utc).isoformat(),
                    "report": report,
                }
                self._job_log.append(entry)
                logger.info(
                    "Scheduled group %s: success=%s iterations=%s",
                    gn,
                    report.get("success"),
                    report.get("iterations"),
                )
                if self._on_complete:
                    self._on_complete(entry)

            try:
                trigger = CronTrigger.from_crontab(cron)
            except ValueError as exc:
                logger.warning("Invalid cron %r for group %s: %s", cron, group_name, exc)
                continue
            self.scheduler.add_job(_run, trigger=trigger, id=job_id, replace_existing=True)
            scheduled += 1
            logger.info("Scheduled group %s with cron %r", group_name, cron)
        return scheduled

    def remove_job(self, job_id: str) -> None:
        try:
            self.scheduler.remove_job(job_id)
        except Exception as exc:
            logger.warning("Failed to remove job %s: %s", job_id, exc)

    def list_jobs(self) -> list[dict[str, Any]]:
        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "next_run": str(job.next_run_time) if job.next_run_time else None,
                "trigger": str(job.trigger),
            })
        return jobs

    def get_job_log(self, limit: int = 50) -> list[dict[str, Any]]:
        return self._job_log[-limit:]
