"""DuckDuckGo Path1/2 support — activity, onboarding seed, viewport."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from automation.browser_adb import (
    DUCKDUCKGO_ACTIVITY,
    BrowserKind,
    browser_info_for_package,
)
from automation.browser_onboarding import (
    duckduckgo_onboarding_visible,
    seed_duckduckgo_onboarding_complete,
)
from automation.config import BROWSER_DUCKDUCKGO
from automation.dabflow_sequence_gen import PATH12_BROWSERS
from automation.web_viewport import (
    KNOWN_VIEWPORTS,
    AUTHOR_VIEWPORT,
    calibrate,
    clear_viewport,
    remap_y,
    set_viewport_for_package,
    viewport_from_dump,
)


class DuckDuckGoBrowserTests(unittest.TestCase):
    def test_browser_info_and_activity(self) -> None:
        info = browser_info_for_package(BROWSER_DUCKDUCKGO)
        assert info is not None
        self.assertEqual(info.kind, BrowserKind.DUCKDUCKGO)
        self.assertEqual(info.package, BROWSER_DUCKDUCKGO)
        self.assertEqual(info.activity, DUCKDUCKGO_ACTIVITY)
        self.assertIn("BrowserActivity", info.activity)

    def test_path12_browsers_by_default_farmbrowser(self) -> None:
        # Unison SSOT: Path1/2 default is FarmBrowser only; other browsers are
        # installable per-group via the wizard picker, not part of PATH12.
        tags = {t for t, _pkg, _label in PATH12_BROWSERS}
        self.assertEqual(tags, {"farmbrowser"})
        pkgs = {pkg for _t, pkg, _l in PATH12_BROWSERS}
        self.assertIn("com.farmbrowser.stealth.debug", pkgs)

    def test_onboarding_visible_welcome(self) -> None:
        xml = (
            '<node text="Welcome to DuckDuckGo!" '
            'resource-id="com.duckduckgo.mobile.android:id/welcomeTitle" />'
        )
        self.assertTrue(duckduckgo_onboarding_visible(xml))

    def test_onboarding_not_visible_when_age_gate_ready(self) -> None:
        xml = (
            '<node resource-id="com.duckduckgo.mobile.android:id/omnibarTextInput" '
            'text="getdabflow.app" />'
            '<node resource-id="age-gate" />'
            '<node resource-id="age-yes-btn" text="YES" />'
        )
        self.assertFalse(duckduckgo_onboarding_visible(xml))

    def test_onboarding_visible_widget_sheet_over_page(self) -> None:
        xml = (
            '<node resource-id="com.duckduckgo.mobile.android:id/omnibarTextInput" />'
            '<node text="Try our Home screen widget!" />'
            '<node resource-id="com.duckduckgo.mobile.android:id/'
            'homeScreenWidgetBottomSheetDialogGhostButton" text="Not Now" />'
        )
        self.assertTrue(duckduckgo_onboarding_visible(xml))

    def test_seed_writes_established_stage(self) -> None:
        adb = MagicMock()
        adb.shell.side_effect = [
            MagicMock(ok=True, stdout=""),  # force-stop
            MagicMock(ok=True, stdout="yes"),  # test -f app.db
            MagicMock(ok=True, stdout="1|ESTABLISHED"),  # sqlite upsert
            MagicMock(ok=True, stdout=""),  # privacy may call more shells
        ]
        with patch(
            "automation.browser_onboarding.apply_browser_privacy", return_value=True
        ) as privacy:
            ok = seed_duckduckgo_onboarding_complete(adb, "10.0.2.1:5555")
        self.assertTrue(ok)
        privacy.assert_called_once()
        sqlite_cmds = [
            c.args[0] for c in adb.shell.call_args_list if "sqlite3" in c.args[0]
        ]
        self.assertEqual(len(sqlite_cmds), 1)
        self.assertIn("INSERT OR REPLACE INTO userStage", sqlite_cmds[0])
        self.assertIn("ESTABLISHED", sqlite_cmds[0])
        self.assertIn("app.db", sqlite_cmds[0])

    def test_seed_bootstraps_db_when_missing(self) -> None:
        adb = MagicMock()
        # seed force-stop → missing db → launcher → poll found → force-stop →
        # ensure re-check → sqlite upsert
        adb.shell.side_effect = [
            MagicMock(ok=True, stdout=""),
            MagicMock(ok=True, stdout=""),  # missing
            MagicMock(ok=True, stdout="Starting:"),  # launcher
            MagicMock(ok=True, stdout="yes"),  # poll found
            MagicMock(ok=True, stdout=""),  # force-stop after bootstrap
            MagicMock(ok=True, stdout="yes"),  # ensure final exists check
            MagicMock(ok=True, stdout="1|ESTABLISHED"),
        ]
        with patch(
            "automation.browser_onboarding.apply_browser_privacy", return_value=True
        ):
            ok = seed_duckduckgo_onboarding_complete(adb, "10.0.2.1:5555")
        self.assertTrue(ok)
        started = [c.args[0] for c in adb.shell.call_args_list if "am start" in c.args[0]]
        self.assertTrue(any("Launcher" in s for s in started))

    def test_viewport_known_and_dump(self) -> None:
        self.assertEqual(KNOWN_VIEWPORTS[BROWSER_DUCKDUCKGO].top, 176)
        self.assertEqual(KNOWN_VIEWPORTS[BROWSER_DUCKDUCKGO].bottom, 1600)
        xml = (
            '<node resource-id="com.duckduckgo.mobile.android:id/webViewContainer" '
            'bounds="[0,176][900,1600]" />'
        )
        vp = viewport_from_dump(xml)
        assert vp is not None
        self.assertEqual(vp.top, 176)
        self.assertEqual(vp.bottom, 1600)

    def test_remap_uses_ddg_viewport(self) -> None:
        clear_viewport("serial-ddg")
        set_viewport_for_package("serial-ddg", BROWSER_DUCKDUCKGO)
        # Author y=160 (page top) → live top 176
        self.assertEqual(remap_y("serial-ddg", AUTHOR_VIEWPORT.top), 176)
        clear_viewport("serial-ddg")

    def test_calibrate_prefers_age_gate(self) -> None:
        clear_viewport("serial-ddg2")
        xml = (
            '<node resource-id="com.duckduckgo.mobile.android:id/webViewContainer" '
            'bounds="[0,176][900,1600]" />'
            '<node resource-id="age-gate" bounds="[0,176][900,1600]" />'
        )
        vp = calibrate("serial-ddg2", xml=xml, package=BROWSER_DUCKDUCKGO)
        self.assertEqual(vp.top, 176)
        clear_viewport("serial-ddg2")


if __name__ == "__main__":
    unittest.main()
