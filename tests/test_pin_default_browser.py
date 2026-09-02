"""Tests for pinning Chromium as Android ROLE_BROWSER."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from automation.browser_onboarding import pin_system_default_browser
from automation.config import BROWSER_CHROMIUM


class PinDefaultBrowserTests(unittest.TestCase):
    def test_pin_calls_role_holder_and_checks_resolve(self) -> None:
        adb = MagicMock()
        adb.shell.side_effect = [
            MagicMock(ok=True, stdout=""),
            MagicMock(
                ok=True,
                stdout=(
                    "priority=0 preferredOrder=0 match=0x208000 "
                    "specificIndex=-1 isDefault=true\n"
                    "org.chromium.chrome/com.google.android.apps.chrome.IntentDispatcher\n"
                ),
            ),
        ]
        ok = pin_system_default_browser(adb, "10.0.2.1:5555", BROWSER_CHROMIUM)
        self.assertTrue(ok)
        first = adb.shell.call_args_list[0][0][0]
        self.assertIn("add-role-holder", first)
        self.assertIn("android.app.role.BROWSER", first)
        self.assertIn(BROWSER_CHROMIUM, first)


if __name__ == "__main__":
    unittest.main()
