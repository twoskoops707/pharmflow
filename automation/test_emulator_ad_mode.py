"""Unit tests for browse proxy / session scramble modes."""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from automation import emulator_ad_mode as eam


class BrowseProxyModeTests(unittest.TestCase):
    def tearDown(self) -> None:
        for key in (
            "PHARMFLOW_BROWSE_PROXY_MODE",
            "PHARMFLOW_EMULATOR_AD_MODE",
            "PHARMFLOW_EMULATOR_AD_RESTORE_TOR",
            "PHARMFLOW_AD_SESSION_SCRAMBLE",
        ):
            os.environ.pop(key, None)
        eam._paused.clear()

    def test_default_mode_from_prefs_is_scramble(self) -> None:
        with patch.object(eam, "browse_proxy_mode", return_value="scramble"):
            self.assertEqual(eam.browse_proxy_mode(), "scramble")

    def test_scramble_mode_enables_ad_mode_on_any_serial(self) -> None:
        os.environ["PHARMFLOW_BROWSE_PROXY_MODE"] = "scramble"
        self.assertTrue(eam.emulator_ad_mode_enabled("192.168.1.5:5555"))

    def test_scramble_does_not_restore_tor_by_default(self) -> None:
        os.environ["PHARMFLOW_BROWSE_PROXY_MODE"] = "scramble"
        self.assertFalse(eam.should_restore_tor_after_ads())

    def test_tor_mode_restores_tor_after_ads(self) -> None:
        os.environ["PHARMFLOW_BROWSE_PROXY_MODE"] = "tor"
        self.assertTrue(eam.should_restore_tor_after_ads())

    def test_session_scramble_on_for_scramble_mode(self) -> None:
        os.environ["PHARMFLOW_BROWSE_PROXY_MODE"] = "scramble"
        self.assertTrue(eam.session_scramble_enabled())

    @patch("automation.browse_proxy.pin_guest_proxy", return_value="127.0.0.1:8218")
    @patch("automation.browse_proxy.guest_proxy_healthy", return_value=True)
    def test_pause_is_ok_only_when_the_guest_exit_is_healthy(self, _healthy, pin) -> None:
        os.environ["PHARMFLOW_BROWSE_PROXY_MODE"] = "scramble"
        result = eam.pause_tor_for_ads(object(), "10.0.2.108:5555", 0)
        self.assertTrue(result.get("ok"))
        self.assertTrue(result.get("pinned"))
        pin.assert_called_once()

    @patch("automation.browse_proxy.pin_guest_proxy", return_value="")
    @patch("automation.browse_proxy.guest_proxy_healthy", return_value=False)
    def test_pause_does_not_claim_a_pin_when_the_exit_did_not_land(self, _healthy, _pin) -> None:
        os.environ["PHARMFLOW_BROWSE_PROXY_MODE"] = "scramble"
        result = eam.pause_tor_for_ads(object(), "10.0.2.108:5555", 0)
        self.assertFalse(result.get("ok"))
        self.assertFalse(result.get("pinned"))
        self.assertNotIn("10.0.2.108:5555", eam._paused)

    def test_ad_fill_wait_is_not_cut_at_60(self) -> None:
        os.environ["PHARMFLOW_EMULATOR_AD_FILL_WAIT"] = "90"
        try:
            self.assertEqual(eam.emulator_ad_fill_wait_sec(), 90.0)
        finally:
            os.environ.pop("PHARMFLOW_EMULATOR_AD_FILL_WAIT", None)


if __name__ == "__main__":
    unittest.main()
