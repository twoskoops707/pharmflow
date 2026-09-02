"""Tests for Chromium FRE-complete seeding after pm clear."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from automation.browser_adb import (
    _FRE_BOOL_PREFS,
    _FRE_COMPLETE_PREFS_XML,
    _seed_fre_complete,
)


class BrowserAdbFreTests(unittest.TestCase):
    def test_seed_fre_xml_has_canonical_and_default_browser_keys(self) -> None:
        self.assertIn("first_run_flow", _FRE_COMPLETE_PREFS_XML)
        self.assertIn("first_run_flow_complete", _FRE_COMPLETE_PREFS_XML)
        self.assertIn('applink.chrome_default_browser" value="true"', _FRE_COMPLETE_PREFS_XML)
        self.assertTrue(_FRE_BOOL_PREFS["applink.chrome_default_browser"])
        self.assertTrue(_FRE_BOOL_PREFS["first_run_flow"])

    def test_seed_fre_complete_writes_prefs(self) -> None:
        adb = MagicMock()
        adb.shell.side_effect = [
            MagicMock(stdout="10052:10052", ok=True),  # stat owner
            MagicMock(ok=True),  # mkdir
            MagicMock(stdout="", ok=True),  # cat existing (empty → full XML write)
            MagicMock(ok=True),  # cp/chown after push
        ]
        adb.push.return_value = MagicMock(ok=True)
        with patch("automation.browser_adb.os.unlink"):
            ok = _seed_fre_complete(adb, "127.0.0.1:16384", "org.chromium.chrome")
        self.assertTrue(ok)
        adb.push.assert_called_once()
        self.assertIn("first_run_flow_complete", _FRE_COMPLETE_PREFS_XML)


if __name__ == "__main__":
    unittest.main()
