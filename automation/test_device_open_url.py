"""Tests for explicit browser component handling in device_open_url.

The previous heuristic used ``"chrome" in component.lower()`` which fired on
unrelated packages whose activity name happens to contain the substring
(e.g. ``com.foo.chromecast/.Activity``). Sequences targeting a non-Chrome
browser via an explicit component would then silently get the Chrome-only
``--ez create_new_tab true`` extra appended, which Chromium-derivative
browsers may interpret differently or ignore. These tests pin the new
exact-or-prefix matching on the package portion of the component.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_AUTOMATION_DIR = Path(__file__).resolve().parent
if str(_AUTOMATION_DIR) not in sys.path:
    sys.path.insert(0, str(_AUTOMATION_DIR))

from device_open_url import (  # noqa: E402
    _component_is_chrome,
    am_start_view_url_argv,
)


class ComponentIsChromeTests(unittest.TestCase):
    def test_known_chrome_package_matches(self):
        self.assertTrue(
            _component_is_chrome("com.android.chrome/com.google.android.apps.chrome.Main")
        )
        self.assertTrue(_component_is_chrome("com.chrome.beta/.MainActivity"))
        self.assertTrue(_component_is_chrome("com.chrome.dev/.Foo"))

    def test_internal_chrome_subpackage_matches(self):
        self.assertTrue(
            _component_is_chrome("com.google.android.apps.chrome.dogfood/.Main")
        )

    def test_non_chrome_package_with_chrome_substring_does_not_match(self):
        self.assertFalse(_component_is_chrome("com.foo.chromecast/.Activity"))
        self.assertFalse(_component_is_chrome("com.example.chrome_helper/.Main"))
        self.assertFalse(_component_is_chrome("com.brave.browser/.MainActivity"))
        self.assertFalse(_component_is_chrome("org.mozilla.firefox/.App"))

    def test_blank_or_malformed_component_does_not_match(self):
        self.assertFalse(_component_is_chrome(""))
        self.assertFalse(_component_is_chrome("com.android.chrome"))
        self.assertFalse(_component_is_chrome("/.Activity"))
        self.assertFalse(_component_is_chrome("   "))


class AmStartArgvTests(unittest.TestCase):
    def test_default_no_component_uses_view_intent(self):
        argv = am_start_view_url_argv("https://example.com")
        self.assertEqual(
            argv,
            [
                "shell",
                "am",
                "start",
                "-a",
                "android.intent.action.VIEW",
                "-d",
                "https://example.com",
            ],
        )

    def test_chrome_component_appends_create_new_tab_extra(self):
        argv = am_start_view_url_argv(
            "https://example.com",
            browser_component="com.android.chrome/com.google.android.apps.chrome.Main",
        )
        self.assertIn("--ez", argv)
        self.assertIn("create_new_tab", argv)
        self.assertIn("true", argv)

    def test_chromecast_component_does_not_append_chrome_extra(self):
        argv = am_start_view_url_argv(
            "https://example.com",
            browser_component="com.foo.chromecast/.Activity",
        )
        self.assertNotIn("create_new_tab", argv)

    def test_explicit_new_tab_true_overrides_for_non_chrome(self):
        argv = am_start_view_url_argv(
            "https://example.com",
            browser_component="org.mozilla.firefox/.App",
            new_tab=True,
        )
        self.assertIn("create_new_tab", argv)

    def test_explicit_new_tab_false_overrides_for_chrome(self):
        argv = am_start_view_url_argv(
            "https://example.com",
            browser_component="com.android.chrome/com.google.android.apps.chrome.Main",
            new_tab=False,
        )
        self.assertNotIn("create_new_tab", argv)

    def test_package_only_uses_dash_p(self):
        argv = am_start_view_url_argv(
            "https://example.com", package="com.example.browser"
        )
        self.assertIn("-p", argv)
        self.assertIn("com.example.browser", argv)
        self.assertNotIn("-n", argv)


if __name__ == "__main__":
    unittest.main()
