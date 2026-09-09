"""Deck structure tests — webview shell + wizard bridge (post-deck migration)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch


class WizardBridgeStepsTests(unittest.TestCase):
    """WIZARD_STEPS now lives in the wizard bridge (deck sidebar source)."""

    def test_wizard_has_ten_steps(self) -> None:
        from wizard.cpharm_wizard_bridge import WIZARD_STEPS

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
        from wizard.cpharm_wizard_bridge import WIZARD_STEPS

        for i, step in enumerate(WIZARD_STEPS):
            self.assertEqual(step.get("index"), i, f"step {i} index mismatch")
            self.assertTrue(step.get("id"), f"step {i} missing id")
            self.assertTrue(step.get("name"), f"step {i} missing name")

    def test_bridge_step_lookup_helpers(self) -> None:
        from wizard.cpharm_wizard_bridge import get_wizard_steps

        steps = get_wizard_steps()
        self.assertEqual(len(steps), 10)
        self.assertIsNot(steps[0], __import__("wizard.cpharm_wizard_bridge", fromlist=["x"]).WIZARD_STEPS[0])  # copies, not the live dicts
        self.assertEqual(steps[0].get("id"), "start")
        self.assertEqual(steps[9].get("id"), "go")


class CPharmAppApiTests(unittest.TestCase):
    """The desktop app is a pywebview shell (CPharmAppApi), not Tk."""

    def test_api_class_exposes_deck_endpoints(self) -> None:
        from wizard.cpharm_app_webview import CPharmAppApi

        api = CPharmAppApi()
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
        from wizard.cpharm_app_webview import CPharmAppApi

        api = CPharmAppApi()
        # Unknown bridge method -> {ok: False, error: ...}, no exception.
        out = api._bridge_call("no_such_bridge_method")
        self.assertFalse(out.get("ok"))
        self.assertIn("no_such_bridge_method", str(out.get("error")))

    def test_start_farm_bridge_refuses_external_python(self) -> None:
        """App Start-farm must surface refuse when the python money path is UP."""
        from wizard.cpharm_wizard_bridge import start_farm_from_app

        with (
            patch("wizard.farm_control.farm_running", return_value=False),
            patch("wizard.farm_control.external_python_farm_running", return_value=True),
            patch("wizard.farm_control.start_farm", return_value=False) as sf,
            patch("wizard.cpharm_wizard_bridge._emit_log") as emit,
            patch("wizard.cpharm_wizard_bridge._farm_start_result", {}),
        ):
            out = start_farm_from_app()
        # Background worker refuses synchronously and streams the refusal.
        self.assertTrue(out.get("starting") or out.get("ok") is False)
        self.assertFalse(sf.called or (not sf.called and out.get("started")))
        self.assertTrue(emit.called or out.get("message"))

    def test_farm_status_bridge_reports_refuse_state(self) -> None:
        from wizard.cpharm_wizard_bridge import farm_status_from_app

        with (
            patch("wizard.farm_control.farm_running", return_value=False),
            patch("wizard.farm_control.external_python_farm_running", return_value=True),
        ):
            out = farm_status_from_app()
        self.assertEqual(out.get("external"), True)


if __name__ == "__main__":
    unittest.main()
