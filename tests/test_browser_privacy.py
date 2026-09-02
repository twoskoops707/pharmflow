"""Tests for browser privacy hardening (prefs merge + Chromium flags)."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from automation.browser_identity import BrowserSessionProfile, build_chromium_command_line
from automation.browser_privacy import (
    CHROMIUM_PRIVACY_FLAGS,
    FIREFOX_PRIVACY_BOOL_PREFS,
    PRIVACY_NOT_GUARANTEED,
    append_privacy_flags,
    apply_browser_privacy,
    merge_boolean_prefs_xml,
    privacy_limitations_summary,
)
from automation.config import (
    BROWSER_BRAVE,
    BROWSER_CHROMIUM,
    BROWSER_DUCKDUCKGO,
    BROWSER_FIREFOX,
)


class BrowserPrivacyMergeTests(unittest.TestCase):
    def test_merge_into_empty_creates_map(self) -> None:
        xml = merge_boolean_prefs_xml("", {"metrics_reporting_enabled": False})
        self.assertIn("<map>", xml)
        self.assertIn('name="metrics_reporting_enabled" value="false"', xml)

    def test_merge_preserves_existing_fre_keys(self) -> None:
        existing = (
            '<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n'
            "<map>\n"
            '<boolean name="first_run_flow_complete" value="true" />\n'
            "</map>\n"
        )
        xml = merge_boolean_prefs_xml(existing, {"metrics_reporting_enabled": False})
        self.assertIn('name="first_run_flow_complete" value="true"', xml)
        self.assertIn('name="metrics_reporting_enabled" value="false"', xml)

    def test_merge_updates_existing_boolean(self) -> None:
        existing = (
            "<map>\n"
            '<boolean name="pref_key_telemetry" value="true" />\n'
            "</map>\n"
        )
        xml = merge_boolean_prefs_xml(existing, {"pref_key_telemetry": False})
        self.assertIn('name="pref_key_telemetry" value="false"', xml)
        self.assertNotIn('value="true"', xml)


class BrowserPrivacyFlagsTests(unittest.TestCase):
    def test_append_privacy_flags_adds_once(self) -> None:
        once = append_privacy_flags("chrome --no-first-run")
        for flag in CHROMIUM_PRIVACY_FLAGS:
            self.assertIn(flag.split("=", 1)[0], once)
        twice = append_privacy_flags(once)
        self.assertEqual(once, twice)

    def test_build_chromium_command_line_includes_privacy(self) -> None:
        profile = BrowserSessionProfile(
            key="test",
            brand="samsung",
            model="SM-S918B",
            user_agent="Mozilla/5.0 test",
        )
        line = build_chromium_command_line(profile)
        self.assertIn("--disable-breakpad", line)
        self.assertIn("--metrics-recording-only", line)
        self.assertIn("--user-agent=", line)
        # Must not use networking kill-switches that break page loads.
        self.assertNotIn("--disable-background-networking", line)


class BrowserPrivacyApplyTests(unittest.TestCase):
    def test_apply_chromium_merges_prefs(self) -> None:
        adb = MagicMock()
        existing = (
            '<?xml version="1.0" encoding="utf-8" standalone="yes" ?>\n'
            "<map>\n"
            '<boolean name="first_run_flow_complete" value="true" />\n'
            "</map>\n"
        )
        adb.shell.side_effect = [
            MagicMock(stdout=existing, ok=True),  # cat
            MagicMock(stdout="10052:10052", ok=True),  # stat
            MagicMock(ok=True),  # mkdir
            MagicMock(ok=True),  # write
            MagicMock(ok=True),  # chown
            MagicMock(ok=True),  # chmod
            MagicMock(ok=True),  # restorecon
        ]
        ok = apply_browser_privacy(adb, "127.0.0.1:16384", BROWSER_CHROMIUM)
        self.assertTrue(ok)
        write_cmd = adb.shell.call_args_list[3][0][0]
        self.assertIn("base64 -d", write_cmd)
        self.assertIn(
            f"/data/data/{BROWSER_CHROMIUM}/shared_prefs/{BROWSER_CHROMIUM}_preferences.xml",
            write_cmd,
        )

    def test_apply_firefox_and_brave_and_ddg_dispatch(self) -> None:
        for pkg in (BROWSER_FIREFOX, BROWSER_BRAVE, BROWSER_DUCKDUCKGO):
            adb = MagicMock()
            adb.shell.side_effect = [
                MagicMock(stdout="", ok=True),
                MagicMock(stdout="1000:1000", ok=True),
                MagicMock(ok=True),
                MagicMock(ok=True),
                MagicMock(ok=True),
                MagicMock(ok=True),
                MagicMock(ok=True),
            ]
            self.assertTrue(apply_browser_privacy(adb, "serial", pkg), pkg)

    def test_apply_unknown_package_noop(self) -> None:
        adb = MagicMock()
        self.assertFalse(apply_browser_privacy(adb, "serial", "com.example.other"))
        adb.shell.assert_not_called()

    def test_firefox_pref_keys_cover_telemetry(self) -> None:
        self.assertFalse(FIREFOX_PRIVACY_BOOL_PREFS["pref_key_telemetry"])
        self.assertFalse(FIREFOX_PRIVACY_BOOL_PREFS["pref_key_experimentation_enabled"])

    def test_limitations_documented(self) -> None:
        summary = privacy_limitations_summary()
        self.assertIn("Not guaranteed", summary)
        self.assertTrue(any("exfiltration" in item.lower() for item in PRIVACY_NOT_GUARANTEED))


if __name__ == "__main__":
    unittest.main()
