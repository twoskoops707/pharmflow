"""Tests for automation.browser_apk_catalog (no network required)."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from automation.browser_apk_catalog import (
    BROWSER_APK_SPECS,
    BROWSER_BRAVE,
    BROWSER_CHROMIUM,
    BROWSER_DUCKDUCKGO,
    BROWSER_FARMBROWSER,
    BROWSER_FIREFOX,
    BROWSER_OPERA,
    apk_path_for,
    catalog_markdown,
    default_apk_cache_dir,
    spec_for_package,
    spec_for_tag,
)


class BrowserApkCatalogTests(unittest.TestCase):
    def test_specs_cover_path12_browsers(self) -> None:
        # Catalog ships 6 browsers: the original four plus Opera and the
        # embedded FarmBrowser (commit 9360b32 embeds its APK in the EXE).
        packages = {s.package for s in BROWSER_APK_SPECS}
        self.assertEqual(
            packages,
            {
                BROWSER_CHROMIUM,
                BROWSER_FIREFOX,
                BROWSER_BRAVE,
                BROWSER_DUCKDUCKGO,
                BROWSER_OPERA,
                BROWSER_FARMBROWSER,
            },
        )
        # Every path12 browser must be bundled offline (no Play Store reliance).
        for s in BROWSER_APK_SPECS:
            self.assertTrue(s.path12, f"{s.package} lost path12")
        chromium = spec_for_package(BROWSER_CHROMIUM)
        assert chromium is not None
        self.assertTrue(chromium.path3)
        self.assertTrue(chromium.path12)
        firefox = spec_for_tag("firefox")
        assert firefox is not None
        self.assertFalse(firefox.path3)
        ddg = spec_for_tag("duckduckgo")
        assert ddg is not None
        self.assertEqual(ddg.package, BROWSER_DUCKDUCKGO)
        self.assertTrue(ddg.path12)
        self.assertFalse(ddg.path3)
        self.assertEqual(apk_path_for(ddg, cache_dir=Path(r"C:\tmp\apks")).name, "duckduckgo-android.apk")

    def test_catalog_mentions_duckduckgo(self) -> None:
        md = catalog_markdown().lower()
        self.assertIn("duckduckgo", md)
        self.assertIn("com.duckduckgo.mobile.android", md)

    def test_catalog_mentions_no_play_store(self) -> None:
        md = catalog_markdown().lower()
        self.assertIn("google play store", md)
        self.assertIn("none required", md)
        self.assertIn("sideload_farm_browsers.py", md)
        self.assertIn("credentials", md)

    def test_apk_path_uses_cache(self) -> None:
        spec = spec_for_tag("brave")
        assert spec is not None
        p = apk_path_for(spec, cache_dir=Path(r"C:\tmp\apks"))
        self.assertEqual(p.name, "brave-android-arm64.apk")
        self.assertEqual(p.parent, Path(r"C:\tmp\apks"))

    def test_default_cache_respects_env(self) -> None:
        with patch.dict("os.environ", {"CPHARM_APK_CACHE": r"D:\farm\apks"}):
            self.assertEqual(default_apk_cache_dir(), Path(r"D:\farm\apks"))

    def test_ensure_summary_flags(self) -> None:
        from automation.browser_apk_catalog import ensure_farm_browsers_on_serials

        adb = MagicMock()
        fake_apk = Path(r"C:\CPharm\apks\ChromePublic-arm64.apk")
        with (
            patch(
                "automation.browser_apk_catalog.download_all_path12_apks",
                return_value={BROWSER_CHROMIUM: fake_apk},
            ),
            patch(
                "automation.browser_apk_catalog.install_apks_on_serials",
                return_value={BROWSER_CHROMIUM: {"10.0.2.1:5555": True}},
            ),
        ):
            summary = ensure_farm_browsers_on_serials(adb, ["10.0.2.1:5555"])
        self.assertFalse(summary["play_store"])
        self.assertFalse(summary["credentials_required"])
        self.assertTrue(summary["ok"])


if __name__ == "__main__":
    unittest.main()
