"""Unit tests for browse proxy / session scramble modes."""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from automation import emulator_ad_mode as eam


class BrowseProxyModeTests(unittest.TestCase):
    def tearDown(self) -> None:
        for key in (
            "CPHARM_BROWSE_PROXY_MODE",
            "CPHARM_EMULATOR_AD_MODE",
            "CPHARM_EMULATOR_AD_RESTORE_TOR",
            "CPHARM_AD_SESSION_SCRAMBLE",
        ):
            os.environ.pop(key, None)
        eam._paused.clear()

    def test_default_mode_from_prefs_is_scramble(self) -> None:
        with patch.object(eam, "browse_proxy_mode", return_value="scramble"):
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

    @patch("automation.browse_proxy.prepare_browse_session")
    def test_pause_calls_scramble_in_scramble_mode(self, prepare) -> None:
        os.environ["CPHARM_BROWSE_PROXY_MODE"] = "scramble"
        prepare.return_value = {"ok": True, "mode": "scramble"}
        result = eam.pause_tor_for_ads(object(), "10.0.2.108:5555", 0)
        self.assertTrue(result.get("ok"))
        prepare.assert_called_once()


if __name__ == "__main__":
    unittest.main()
