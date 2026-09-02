"""Tests for automation/dashboard.py Flask API."""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

import automation.dashboard as dashboard


class DashboardApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.mock_farm = MagicMock()
        self.mock_farm.is_ready = True
        self.mock_farm.instances = {}
        self.mock_farm.detect.return_value = {"mumu": True}
        self.mock_farm.tor.detect.return_value = {"selected_exists": True, "install_kind": "system"}
        self.mock_farm.list_instances.return_value = None
        self.mock_farm.get_phone_status.return_value = {
            "name": "phone-a",
            "running": False,
            "connected": False,
            "adb_serial": "127.0.0.1:16384",
            "resolution": "900x1600",
        }

        self.mock_runner = MagicMock()
        self.mock_runner.run.return_value = {"success": True, "steps": []}

        self.mock_groups = MagicMock()
        self.mock_groups.list_groups.return_value = []

        self.mock_scheduler = MagicMock()
        self.mock_scheduler.scheduler.running = True
        self.mock_scheduler.get_job_log.return_value = []

        dashboard.farm = self.mock_farm
        dashboard.runner = self.mock_runner
        dashboard.groups = self.mock_groups
        dashboard.scheduler = self.mock_scheduler
        dashboard._activity_log.clear()

        self.client = dashboard.app.test_client()

    def test_index_serves_ui(self) -> None:
        resp = self.client.get("/")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"CPharm", resp.data)
        self.assertIn(b"/api/phones", resp.data)
        self.assertIn(b"Pick file", resp.data)

    def test_api_phones_get(self) -> None:
        inst = MagicMock()
        inst.name = "phone-a"
        self.mock_farm.instances = {"phone-a": inst}
        with patch.object(dashboard, "_enrich_phone_status", side_effect=lambda s: s):
            resp = self.client.get("/api/phones")
        self.assertEqual(resp.status_code, 200)
        data = resp.get_json()
        self.assertIsInstance(data, list)
        self.assertEqual(data[0]["name"], "phone-a")

    def test_api_sequences_list(self) -> None:
        with patch("automation.dashboard.list_sequence_ids", return_value=["dabflow/complete"]):
            resp = self.client.get("/api/sequences")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.get_json(), ["dabflow/complete"])

    def test_api_sequences_run(self) -> None:
        with (
            patch.dict(os.environ, {"CPHARM_ALLOW_SEQUENCE_RUNS": "1"}),
            patch("automation.dashboard.resolve_sequence_path", return_value=MagicMock()),
            patch("automation.dashboard.Sequence") as seq_cls,
            patch("automation.dashboard._start_job", return_value="job123") as start_job,
        ):
            seq_cls.from_json.return_value = MagicMock(phone="")
            resp = self.client.post(
                "/api/sequences/run",
                json={"sequence": "dabflow/complete", "phone": "phone-a"},
            )
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertTrue(body["ok"])
        self.assertEqual(body["job_id"], "job123")
        start_job.assert_called_once()

    def test_api_tor_detection(self) -> None:
        with patch.object(dashboard, "_phone_tor_status", return_value={"name": "phone-a", "ok": True}):
            inst = MagicMock()
            inst.name = "phone-a"
            self.mock_farm.instances = {"phone-a": inst}
            resp = self.client.get("/api/tor")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertIn("detection", body)
        self.assertEqual(len(body["phones"]), 1)

    def test_api_tor_rotate(self) -> None:
        inst = MagicMock(index=0, adb_serial="127.0.0.1:16384")
        self.mock_farm.get_phone.return_value = inst
        self.mock_farm.tor.rotate_identity.return_value = True
        with patch.object(dashboard, "_phone_tor_status", return_value={"name": "phone-a", "ok": True}):
            resp = self.client.post("/api/tor/phone-a/rotate")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.get_json()["ok"])

    def test_api_logs(self) -> None:
        dashboard._log_event("test event", "info")
        resp = self.client.get("/api/logs?limit=10")
        self.assertEqual(resp.status_code, 200)
        body = resp.get_json()
        self.assertEqual(body["entries"][0]["message"], "test event")


if __name__ == "__main__":
    unittest.main()
