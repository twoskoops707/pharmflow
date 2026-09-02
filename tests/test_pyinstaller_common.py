"""Tests for wizard/pyinstaller_common.py shared build config."""

from __future__ import annotations

import unittest
from pathlib import Path

from wizard.pyinstaller_common import (
    APP_VERSION,
    ROOT,
    _existing_data_pairs,
    base_hiddenimports,
    icon_path,
    version_info_path,
)


class PyInstallerCommonTests(unittest.TestCase):
    def test_version_constant(self) -> None:
        self.assertEqual(APP_VERSION, "1.4.17")

    def test_hiddenimports_include_core_modules(self) -> None:
        hidden = base_hiddenimports()
        for mod in (
            "wizard.cpharm_desktop",
            "wizard.setup_desktop",
            "wizard.site_interview",
            "wizard.farm_control",
            "automation.dashboard",
            "automation.site_profile",
            "automation.site_sequence_gen",
            "automation.dabflow_site_profile",
            "automation.dabflow_mantis_client_patch",
            "automation.emulator_ad_mode",
            "automation.browse_proxy",
            "automation.browser_apk_catalog",
            "automation.browser_onboarding",
            "automation.browser_privacy",
            "automation.web_viewport",
            "automation.farm_pause",
            "automation.sequence_isolation",
            "scripts.keep_farm_alive",
            "scripts.watch_bottom_ads",
            "scripts.ntfy_farm_responder",
            "flask",
            "customtkinter",
            "apscheduler",
            "websockets",
            "scripts.farm_hourly_ntfy",
        ):
            self.assertIn(mod, hidden)

    def test_data_pairs_include_icons_and_sequences(self) -> None:
        pairs = dict(_existing_data_pairs())
        self.assertIn(str(ROOT / "wizard" / "icons"), pairs)
        self.assertIn(str(ROOT / "automation" / "recordings"), pairs)
        self.assertIn(str(ROOT / "scripts" / "run_farm_354.py"), pairs)
        self.assertIn(str(ROOT / "scripts" / "farm_hourly_ntfy.py"), pairs)
        self.assertIn(str(ROOT / "scripts" / "sideload_farm_browsers.py"), pairs)
        self.assertIn(str(ROOT / "scripts" / "keep_farm_alive.py"), pairs)
        self.assertIn(str(ROOT / "scripts" / "watch_bottom_ads.py"), pairs)
        self.assertIn(str(ROOT / "scripts" / "ntfy_farm_responder.py"), pairs)
        self.assertIn(str(ROOT / "automation" / "farm_pause.py"), pairs)
        self.assertIn(str(ROOT / "docs" / "multi_browser_sideload.md"), pairs)

    def test_version_info_files_exist(self) -> None:
        main_ver = version_info_path()
        setup_ver = version_info_path(setup=True)
        self.assertIsNotNone(main_ver)
        self.assertIsNotNone(setup_ver)
        self.assertTrue(str(main_ver).endswith("version_info.txt"))
        self.assertTrue(str(setup_ver).endswith("version_info_setup.txt"))

    def test_icon_path_prefers_ico_when_present(self) -> None:
        ico = ROOT / "wizard" / "icons" / "app_icon.ico"
        png = ROOT / "wizard" / "icons" / "app_icon.png"
        if ico.is_file():
            self.assertTrue(icon_path().endswith("app_icon.ico"))
        elif png.is_file():
            self.assertTrue(icon_path().endswith("app_icon.png"))

    def test_spec_file_exists(self) -> None:
        self.assertTrue((ROOT / "wizard" / "CPharm.spec").is_file())


if __name__ == "__main__":
    unittest.main()
