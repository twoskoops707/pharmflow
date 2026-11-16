"""Start farm must refuse unless stealth AND funds checks both pass."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import farm_start_gate as gate  # noqa: E402


class FarmStartGateTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.logs = Path(self._td.name)

    def tearDown(self) -> None:
        self._td.cleanup()

    def test_refuses_without_phones(self) -> None:
        with (
            patch.object(gate, "_logs_dir", return_value=self.logs),
            patch.object(gate, "_desktop_prefs", return_value={"mask_emulator_fingerprint": True, "dabflow_mantis_patch": True}),
            patch.object(gate, "_discover_phones", return_value=[]),
            patch("wizard.site_prefs.load_target_site_url", return_value="https://getdabflow.app/"),
            patch.dict("os.environ", {"PHARMFLOW_MANTIS_BILLING_DIRECT": "0"}, clear=False),
        ):
            out = gate.evaluate_start_gate(serials=[], apply_stealth_defaults=False)
        self.assertFalse(out["ok"])
        self.assertFalse(out["stealth_ok"])
        self.assertIn("no phones", (out.get("error") or "").lower())

    def test_refuses_stealth_leaks(self) -> None:
        with (
            patch.object(gate, "_logs_dir", return_value=self.logs),
            patch.object(gate, "_desktop_prefs", return_value={"mask_emulator_fingerprint": True, "dabflow_mantis_patch": True}),
            patch.object(
                gate,
                "_stealth_audit",
                return_value={
                    "ok": False,
                    "phones": 1,
                    "phones_with_leaks": 1,
                    "leaks_total": 2,
                    "all_clean": False,
                },
            ),
            patch("wizard.site_prefs.load_target_site_url", return_value="https://getdabflow.app/"),
            patch.dict("os.environ", {"PHARMFLOW_MANTIS_BILLING_DIRECT": "0"}, clear=False),
        ):
            out = gate.evaluate_start_gate(serials=["10.0.2.2:5555"], apply_stealth_defaults=False)
        self.assertFalse(out["ok"])
        self.assertFalse(out["stealth_ok"])
        self.assertIn("stealth", (out.get("error") or "").lower())

    def test_refuses_when_money_health_explicit_fail(self) -> None:
        (self.logs / "FARM_MONEY_HEALTH.json").write_text(
            json.dumps({"money_ok": False, "payout_usd": 0, "impressions": 0, "clicks": 0}),
            encoding="utf-8",
        )
        with (
            patch.object(gate, "_logs_dir", return_value=self.logs),
            patch.object(gate, "_desktop_prefs", return_value={"mask_emulator_fingerprint": True, "dabflow_mantis_patch": True}),
            patch.object(
                gate,
                "_stealth_audit",
                return_value={
                    "ok": True,
                    "phones": 1,
                    "phones_with_leaks": 0,
                    "leaks_total": 0,
                    "all_clean": True,
                },
            ),
            patch("wizard.site_prefs.load_target_site_url", return_value="https://getdabflow.app/"),
            patch.dict("os.environ", {"PHARMFLOW_MANTIS_BILLING_DIRECT": "0"}, clear=False),
        ):
            out = gate.evaluate_start_gate(serials=["10.0.2.2:5555"], apply_stealth_defaults=False)
        self.assertFalse(out["ok"])
        self.assertTrue(out["stealth_ok"])
        self.assertFalse(out["funds_ok"])
        self.assertIn("money_ok", (out.get("error") or "").lower())

    def test_ok_when_stealth_clean_and_funds_generating(self) -> None:
        (self.logs / "mantis_today_state.json").write_text(
            json.dumps({"payout_usd": 1.25, "impressions": 40, "clicks": 2}),
            encoding="utf-8",
        )
        with (
            patch.object(gate, "_logs_dir", return_value=self.logs),
            patch.object(gate, "_desktop_prefs", return_value={"mask_emulator_fingerprint": True, "dabflow_mantis_patch": True}),
            patch.object(
                gate,
                "_stealth_audit",
                return_value={
                    "ok": True,
                    "phones": 2,
                    "phones_with_leaks": 0,
                    "leaks_total": 0,
                    "all_clean": True,
                },
            ),
            patch("wizard.site_prefs.load_target_site_url", return_value="https://getdabflow.app/"),
            patch.dict("os.environ", {"PHARMFLOW_MANTIS_BILLING_DIRECT": "0"}, clear=False),
        ):
            out = gate.evaluate_start_gate(
                serials=["10.0.2.2:5555", "10.0.2.3:5555"],
                apply_stealth_defaults=False,
            )
        self.assertTrue(out["ok"])
        self.assertTrue(out["stealth_ok"])
        self.assertTrue(out["funds_ok"])
        self.assertTrue(out["prefer_newest_build"])

    def test_refuses_stealth_gate_stop_file(self) -> None:
        (self.logs / "FARM_STEALTH_GATE_STOP.json").write_text("{}", encoding="utf-8")
        with patch.object(gate, "_logs_dir", return_value=self.logs):
            out = gate.evaluate_start_gate(serials=["10.0.2.2:5555"])
        self.assertFalse(out["ok"])
        self.assertIn("stealth gate stop", (out.get("error") or "").lower())

    def test_bridge_and_deck_expose_gate_and_attach(self) -> None:
        bridge = (ROOT / "wizard" / "pharmflow_wizard_bridge.py").read_text(encoding="utf-8")
        self.assertIn("def farm_start_gate_status(", bridge)
        self.assertIn("def dump_gate_status_fast(", bridge)
        self.assertIn("def attach_local_and_cloud_phones(", bridge)
        self.assertIn("farm_start_gate_status()", bridge)
        dump = bridge.split("def dump_gate_status_fast(")[1].split("\ndef ")[0]
        self.assertIn("dump_gate_status_fast", dump)
        self.assertNotIn("start_farm(", dump)
        self.assertNotIn("start_farm_from_app", dump)
        web = (ROOT / "wizard" / "pharmflow_app_webview.py").read_text(encoding="utf-8")
        self.assertIn("def farm_start_gate_status(", web)
        self.assertIn("def dump_gate_status_fast(", web)
        self.assertIn("def attach_local_and_cloud_phones(", web)
        html = (ROOT / "wizard" / "assets" / "pharmflow_app" / "index.html").read_text(encoding="utf-8")
        self.assertIn("btn-attach-phones", html)
        self.assertIn("farm-start-gate-status", html)
        self.assertIn('data-menu-action="options.gate_status"', html)
        js = (ROOT / "wizard" / "assets" / "pharmflow_app" / "app.js").read_text(encoding="utf-8")
        self.assertIn("attach_local_and_cloud_phones", js)
        self.assertIn("farm_start_gate_status", js)
        self.assertIn("dump_gate_status_fast", js)
        self.assertIn("menuDumpGateStatus", js)
        fc = (ROOT / "wizard" / "farm_control.py").read_text(encoding="utf-8")
        self.assertIn("farm_start_gate.evaluate_start_gate", fc)
        self.assertIn("prefer_newest_farm_builds", fc)

    def test_dump_gate_status_fast_writes_log_skip_audit(self) -> None:
        with (
            patch.object(gate, "_logs_dir", return_value=self.logs),
            patch.object(
                gate,
                "_desktop_prefs",
                return_value={"mask_emulator_fingerprint": True, "dabflow_mantis_patch": True},
            ),
            patch.object(
                gate,
                "_stealth_audit",
                side_effect=AssertionError("skip_audit must not call fingerprint audit"),
            ),
            patch("wizard.site_prefs.load_target_site_url", return_value="https://getdabflow.app/"),
            patch.dict("os.environ", {"PHARMFLOW_MANTIS_BILLING_DIRECT": "0"}, clear=False),
        ):
            out = gate.dump_gate_status_fast(
                serials=["10.0.2.2:5555"],
                skip_audit=True,
            )
        self.assertTrue(out.get("dumped"))
        self.assertEqual(out.get("start_farm"), "never")
        self.assertTrue(out.get("audit_skipped"))
        path = Path(out["path"])
        self.assertEqual(path.name, "gate-status-fast-last.txt")
        self.assertTrue(path.is_file())
        text = path.read_text(encoding="utf-8")
        self.assertIn("ADB=1", text)
        self.assertIn("STEALTH_OK=True (audit_skipped)", text)
        self.assertIn("FUNDS_OK=", text)
        self.assertIn("GATE_OK=", text)
        self.assertIn("MESSAGE=", text)
        self.assertIn("START_FARM=never", text)
        src = (ROOT / "tools" / "farm_start_gate.py").read_text(encoding="utf-8")
        dump_src = src.split("def dump_gate_status_fast(")[1].split("\ndef prefer_newest")[0]
        self.assertNotIn("start_farm(", dump_src)


class CloudAttachSurfaceTests(unittest.TestCase):
    def test_cloud_connect_exports_attach(self) -> None:
        import cloud_connect as cc

        self.assertTrue(callable(cc.attach_local_and_cloud_phones))


if __name__ == "__main__":
    unittest.main()
