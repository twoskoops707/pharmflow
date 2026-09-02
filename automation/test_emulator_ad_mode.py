"""Unit tests for browse proxy / session scramble modes."""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

import emulator_ad_mode as eam


class BrowseProxyModeTests(unittest.TestCase):
    def tearDown(self) -> None:
        for key in (
            "CPHARM_BROWSE_PROXY_MODE",
            "CPHARM_EMULATOR_AD_MODE",
            "CPHARM_EMULATOR_AD_RESTORE_TOR",
            "CPHARM_AD_SESSION_SCRAMBLE",
        ):
            os.environ.pop(key, None)

    def test_default_mode_from_prefs_is_scramble(self) -> None:
        with patch("browse_proxy.browse_proxy_mode", return_value="scramble"):
            self.assertEqual(eam.browse_proxy_mode(), "scramble")

    def test_scramble_mode_enables_ad_mode_on_any_serial(self) -> None:
        os.environ["CPHARM_BROWSE_PROXY_MODE"] = "scramble"
        self.assertTrue(eam.emulator_ad_mode_enabled("192.168.1.5:5555"))

    def test_scramble_does_not_restore_tor_by_default(self) -> None:
        os.environ["CPHARM_BROWSE_PROXY_MODE"] = "scramble"
        self.assertFalse(eam.should_restore_tor_after_ads())

    def test_tor_mode_restores_tor_after_ads(self) -> None:
        os.environ["CPHARM_BROWSE_PROXY_MODE"] = "tor"
        self.assertTrue(eam.should_restore_tor_after_ads())

    def test_session_scramble_on_for_scramble_mode(self) -> None:
        os.environ["CPHARM_BROWSE_PROXY_MODE"] = "scramble"
        self.assertTrue(eam.session_scramble_enabled())

    @patch("emulator_ad_mode.scramble_device_session")
    @patch("tor_manager.clear_all_proxies_on_devices")
    @patch("tor_manager.kick_default_browser_after_proxy_teardown")
    def test_pause_calls_scramble_in_scramble_mode(
        self,
        _kick,
        _clear,
        scramble,
    ) -> None:
        os.environ["CPHARM_BROWSE_PROXY_MODE"] = "scramble"
        scramble.return_value = {"ok": True}
        result = eam.pause_tor_for_ads("10.0.2.108:5555", 0)
        self.assertTrue(result.get("ok"))
        scramble.assert_called_once()


if __name__ == "__main__":
    unittest.main()
