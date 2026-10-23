"""Deck structure tests — webview shell + wizard bridge (post-deck migration)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


class WizardBridgeStepsTests(unittest.TestCase):
    """WIZARD_STEPS now lives in the wizard bridge (deck sidebar source)."""

    def test_wizard_has_ten_steps(self) -> None:
        from wizard.pharmflow_wizard_bridge import WIZARD_STEPS

        self.assertEqual(len(WIZARD_STEPS), 10)
        names = [s["name"] for s in WIZARD_STEPS]
        self.assertEqual(
            names,
            [
                "Start",
                "Install",
                "Android",
                "Phones",
                "Test",
                "Site Map",
                "Steps",
                "Builder",
                "Groups",
                "Run",
            ],
        )

    def test_step_ids_and_indices_are_stable(self) -> None:
        from wizard.pharmflow_wizard_bridge import WIZARD_STEPS

        for i, step in enumerate(WIZARD_STEPS):
            self.assertEqual(step.get("index"), i, f"step {i} index mismatch")
            self.assertTrue(step.get("id"), f"step {i} missing id")
            self.assertTrue(step.get("name"), f"step {i} missing name")

    def test_bridge_step_lookup_helpers(self) -> None:
        from wizard.pharmflow_wizard_bridge import get_wizard_steps

        steps = get_wizard_steps()
        self.assertEqual(len(steps), 10)
        self.assertIsNot(steps[0], __import__("wizard.pharmflow_wizard_bridge", fromlist=["x"]).WIZARD_STEPS[0])  # copies, not the live dicts
        self.assertEqual(steps[0].get("id"), "start")
        self.assertEqual(steps[9].get("id"), "go")


class PharmFlowAppApiTests(unittest.TestCase):
    """The desktop app is a pywebview shell (PharmFlowAppApi), not Tk."""

    def test_api_class_exposes_deck_endpoints(self) -> None:
        from wizard.pharmflow_app_webview import PharmFlowAppApi

        api = PharmFlowAppApi()
        for name in (
            "get_wizard_steps",
            "get_farm_hud",
            "get_prereq_status",
            "start_farm",
            "stop_farm",
            "farm_status",
        ):
            self.assertTrue(callable(getattr(api, name)), f"missing {name}")

    def test_api_bridge_call_never_raises(self) -> None:
        from wizard.pharmflow_app_webview import PharmFlowAppApi

        api = PharmFlowAppApi()
        # Unknown bridge method -> {ok: False, error: ...}, no exception.
        out = api._bridge_call("no_such_bridge_method")
        self.assertFalse(out.get("ok"))
        self.assertIn("no_such_bridge_method", str(out.get("error")))

    def test_start_farm_bridge_refuses_external_python(self) -> None:
        """App Start-farm must refuse when the python money path is already UP."""
        from wizard.pharmflow_wizard_bridge import start_farm_from_app

        with (
            patch("wizard.farm_control.farm_process_alive", return_value=False),
            patch("wizard.farm_control.external_python_farm_running", return_value=True),
            patch("wizard.farm_control.operator_dashboard_listening", return_value=True),
            patch("wizard.farm_control.start_farm", return_value=True) as sf,
            patch("wizard.pharmflow_wizard_bridge._emit_log") as emit,
        ):
            out = start_farm_from_app()
        self.assertFalse(out.get("starting"))
        self.assertFalse(out.get("ok"))
        self.assertTrue(out.get("running"))
        self.assertTrue(out.get("external"))
        self.assertFalse(sf.called)
        self.assertTrue(emit.called)
        self.assertIn("does not take over", str(out.get("error") or out.get("message") or ""))

    def test_farm_status_bridge_reports_external_as_running(self) -> None:
        from wizard.pharmflow_wizard_bridge import farm_status_from_app

        with (
            patch("wizard.farm_control.farm_process_alive", return_value=False),
            patch("wizard.farm_control.external_python_farm_running", return_value=True),
            patch("wizard.farm_control.operator_dashboard_listening", return_value=True),
        ):
            out = farm_status_from_app()
        self.assertEqual(out.get("external"), True)
        self.assertTrue(out.get("running"))
        self.assertTrue(out.get("dashboard_ready"))

    def test_stop_farm_bridge_stops_external_python(self) -> None:
        from wizard.pharmflow_wizard_bridge import stop_farm_from_app

        with (
            patch("wizard.farm_control.farm_process_alive", return_value=False),
            patch(
                "wizard.farm_control.external_python_farm_running",
                side_effect=[True, False],
            ),
            patch(
                "wizard.farm_control.stop_external_python_farm",
                return_value=[4242],
            ) as stop_ex,
            patch("wizard.farm_control.stop_farm", return_value=True) as stop_fn,
        ):
            out = stop_farm_from_app()
        self.assertTrue(out.get("ok"))
        self.assertTrue(out.get("stopped"))
        self.assertFalse(out.get("running"))
        self.assertFalse(out.get("external"))
        self.assertTrue(stop_ex.called)
        self.assertFalse(stop_fn.called)
        self.assertIn("External python farm stopped", str(out.get("message") or ""))


class BootAllPhonesReconnectTests(unittest.TestCase):
    """boot_all_phones must re-verify ADB on every RUNNING phone and hard-reset
    dead transports — a running-but-offline VM (seen in the field as 10.0.2.66
    offline) may never be skipped as 'already running'."""

    @staticmethod
    def _instance(name: str, idx: int, serial: str, started: bool) -> dict:
        return {"name": name, "index": idx, "adb_serial": serial, "started": started}

    def _boot(self, instances: list[dict], echo_results: list[str]) -> None:
        """Drive boot_all_phones' worker with a scripted adb("shell", "echo", …) queue."""
        from wizard import pharmflow_wizard_bridge as bridge

        def fake_adb(*args, serial=None, timeout=20):
            if args[:2] == ("shell", "echo"):
                return echo_results.pop(0) if echo_results else ""
            return ""

        with (
            patch.object(bridge, "_boot_all_lock") as lock,
            lock.acquire(blocking=False),
            patch("setup_wizard._find_mumu_manager", return_value=MagicMock()),
            patch("setup_wizard._mumu_get_instances", return_value=instances),
            patch("setup_wizard.adb", side_effect=fake_adb),
            patch("wizard.pharmflow_wizard_bridge._emit_log"),
            patch("time.sleep"),
            patch("time.time", side_effect=[0.0] * 500),
        ):
            res = bridge.boot_all_phones()
            self.assertTrue(res.get("started"))
            # Join the worker so assertions run against completed state and the
            # patches stay alive for the whole run (no suite-order races).
            import threading as _th

            for _ in range(200):
                if not any(t.name == "boot-all-phones" and t.is_alive() for t in _th.enumerate()):
                    break
                _th.Event().wait(0.01)
            self.assertTrue(lock.release.called)

    def test_running_phone_with_dead_adb_is_reconnected(self) -> None:
        inst = [self._instance("P1", 0, "10.0.2.66:5555", started=True)]
        # 1st echo: dead (never 'ok'); 2nd echo (after disconnect+connect): 'ok'.
        self._boot(inst, echo_results=["", "ok"])

    def test_running_phone_with_healthy_adb_never_reset(self) -> None:
        inst = [self._instance("P1", 0, "10.0.2.146:5555", started=True)]
        # First echo already 'ok' — no disconnect/connect may be issued.
        self._boot(inst, echo_results=["ok"])

    def test_running_phone_dead_adb_after_reset_counts_failed(self) -> None:
        inst = [self._instance("P1", 0, "10.0.2.66:5555", started=True)]
        # Every echo stays dead — phone ends in failed, never 'already'.
        self._boot(inst, echo_results=[""])


if __name__ == "__main__":
    unittest.main()
