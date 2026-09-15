"""Farm health must read the session log, not whichever farm_*.log was touched last."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from automation.farm_health import newest_farm_log, snapshot


class FarmHealthSnapshotTests(unittest.TestCase):
    def test_session_log_wins_over_a_newer_monitor_log(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            session = root / "farm_354.log"
            session.write_text("2026-09-14 01:00:00,000 INFO [vm0] step 1\n", encoding="utf-8")
            monitor = root / "farm_money_monitor.log"
            monitor.write_text("newer\n", encoding="utf-8")
            os.utime(session, (1_000_000, 1_000_000))
            os.utime(monitor, (2_000_000, 2_000_000))
            old_dir = os.environ.get("PHARMFLOW_LOG_DIR")
            old_logs = os.environ.get("PHARMFLOW_LOGS")
            os.environ["PHARMFLOW_LOG_DIR"] = str(root)
            os.environ.pop("PHARMFLOW_LOGS", None)
            try:
                picked = newest_farm_log()
            finally:
                if old_dir is None:
                    os.environ.pop("PHARMFLOW_LOG_DIR", None)
                else:
                    os.environ["PHARMFLOW_LOG_DIR"] = old_dir
                if old_logs is None:
                    os.environ.pop("PHARMFLOW_LOGS", None)
                else:
                    os.environ["PHARMFLOW_LOGS"] = old_logs
            self.assertEqual(Path(picked or ""), session)

    def test_missing_session_log_is_not_a_clean_farm(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "farm_money_monitor.log").write_text("no steps\n", encoding="utf-8")
            old_dir = os.environ.get("PHARMFLOW_LOG_DIR")
            old_logs = os.environ.get("PHARMFLOW_LOGS")
            os.environ.pop("PHARMFLOW_LOG_DIR", None)
            os.environ["PHARMFLOW_LOGS"] = str(root)
            try:
                out = snapshot()
            finally:
                if old_dir is None:
                    os.environ.pop("PHARMFLOW_LOG_DIR", None)
                else:
                    os.environ["PHARMFLOW_LOG_DIR"] = old_dir
                if old_logs is None:
                    os.environ.pop("PHARMFLOW_LOGS", None)
                else:
                    os.environ["PHARMFLOW_LOGS"] = old_logs
            self.assertFalse(out["ok"])
            self.assertEqual(out["phones"], [])
            self.assertIn("farm_354.log", out.get("error") or "")

    def test_payout_from_another_day_is_not_current(self) -> None:
        import json
        import time

        from automation.farm_health import payout_latest

        with TemporaryDirectory() as tmp:
            watch = Path(tmp) / "freebuff_payout_watch.json"
            watch.write_text(
                json.dumps([{"ts": 1, "payout_usd": 77, "clicks": 4, "impressions": 9}]),
                encoding="utf-8",
            )
            old = os.environ.get("PHARMFLOW_LOG_DIR")
            os.environ["PHARMFLOW_LOG_DIR"] = tmp
            try:
                stale = payout_latest()
                watch.write_text(
                    json.dumps(
                        [{
                            "ts": time.time(),
                            "payout_usd": 3.5,
                            "clicks": 1,
                            "impressions": 20,
                        }]
                    ),
                    encoding="utf-8",
                )
                fresh = payout_latest()
            finally:
                if old is None:
                    os.environ.pop("PHARMFLOW_LOG_DIR", None)
                else:
                    os.environ["PHARMFLOW_LOG_DIR"] = old
        self.assertIsNone(stale["payout_usd"])
        self.assertEqual(fresh["payout_usd"], 3.5)

    def test_fresh_log_is_not_a_live_farm(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "farm_354.log").write_text("step\n", encoding="utf-8")
            old = os.environ.get("PHARMFLOW_LOG_DIR")
            os.environ["PHARMFLOW_LOG_DIR"] = str(root)
            try:
                out = snapshot()
            finally:
                if old is None:
                    os.environ.pop("PHARMFLOW_LOG_DIR", None)
                else:
                    os.environ["PHARMFLOW_LOG_DIR"] = old
        self.assertTrue(out["ok"])
        self.assertTrue(out["log_fresh"])
        self.assertFalse(out["farm_alive"])

    def test_payout_prefers_freshest_legacy_root_when_env_unset(self) -> None:
        import json
        import time
        from unittest.mock import patch

        from automation import farm_health as fh
        from automation.farm_health import payout_latest

        with TemporaryDirectory() as tmp:
            base = Path(tmp)
            pharm = base / "PharmFlow" / "logs"
            cpharm = base / "CPharm" / "logs"
            pharm.mkdir(parents=True)
            cpharm.mkdir(parents=True)
            older = [{"ts": time.time(), "payout_usd": 1.0, "clicks": 1, "impressions": 10}]
            newer = [{"ts": time.time(), "payout_usd": 9.5, "clicks": 2, "impressions": 20}]
            (pharm / "freebuff_payout_watch.json").write_text(json.dumps(older), encoding="utf-8")
            (cpharm / "freebuff_payout_watch.json").write_text(json.dumps(newer), encoding="utf-8")
            os.utime(pharm / "freebuff_payout_watch.json", (1_700_000_000, 1_700_000_000))
            os.utime(cpharm / "freebuff_payout_watch.json", (1_800_000_000, 1_800_000_000))
            with patch.object(fh, "_log_roots", return_value=[str(pharm), str(cpharm)]):
                out = payout_latest()
        self.assertEqual(out["payout_usd"], 9.5)


if __name__ == "__main__":
    unittest.main()