"""Tests for browser_identity — UA from live getprop, not hardcoded models."""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from automation.browser_identity import (
    BrowserSessionProfile,
    DeviceIdentity,
    build_mobile_user_agent,
    profile_from_device,
    read_device_identity,
    verify_browser_headers,
    write_chromium_flags,
)


class BrowserIdentityTests(unittest.TestCase):
    def test_build_user_agent_uses_device_model(self) -> None:
        identity = DeviceIdentity(
            brand="OnePlus",
            manufacturer="OnePlus",
            model="CPH2449",
            android_release="13",
            build_id="TP1A.220905.001",
        )
        ua = build_mobile_user_agent(identity, "119.0.6045.163")
        self.assertIn("CPH2449", ua)
        self.assertIn("Android 13", ua)
        self.assertIn("Chrome/119.0.6045.163", ua)
        self.assertNotIn("SM-S918B", ua)
        self.assertNotIn("; wv", ua)
        self.assertNotIn("Version/4.0", ua)

    def test_read_device_identity_from_getprop(self) -> None:
        adb = MagicMock()
        adb.getprop.side_effect = lambda key, serial=None: {
            "ro.product.brand": "motorola",
            "ro.product.manufacturer": "motorola",
            "ro.product.model": "XT2343-3",
            "ro.build.version.release": "13",
            "ro.build.id": "T1SJ33.117-48-7",
            "ro.hardware": "qcom",
        }.get(key, "")

        identity = read_device_identity(adb, "10.0.2.149:5555")
        self.assertEqual(identity.model, "XT2343-3")
        self.assertEqual(identity.brand, "motorola")
        self.assertTrue(identity.is_usable())

    def test_profile_from_device_reads_chromium_version(self) -> None:
        adb = MagicMock()
        adb.getprop.side_effect = lambda key, serial=None: {
            "ro.product.brand": "samsung",
            "ro.product.manufacturer": "samsung",
            "ro.product.model": "SM-S918B",
            "ro.build.version.release": "14",
            "ro.build.id": "UP1A.231005.007",
        }.get(key, "")
        adb.shell.side_effect = lambda cmd, serial=None: MagicMock(
            stdout="    versionName=120.0.6099.144\n",
            ok=True,
        )

        profile = profile_from_device(adb, "serial")
        self.assertEqual(profile.model, "SM-S918B")
        self.assertIn("SM-S918B", profile.user_agent)
        self.assertIn("120.0.6099.144", profile.user_agent)
        self.assertEqual(profile.source, "getprop")

    def test_profile_from_retail_pool_rotates_model(self) -> None:
        from automation.browser_identity import profile_from_retail_pool

        adb = MagicMock()
        adb.shell.side_effect = lambda cmd, serial=None: MagicMock(
            stdout="    versionName=120.0.6099.144\n",
            ok=True,
        )
        p1 = profile_from_retail_pool(adb, "s1", avoid_model="")
        p2 = profile_from_retail_pool(adb, "s1", avoid_model=p1.model)
        self.assertEqual(p1.source, "retail_pool")
        self.assertTrue(p1.android_id)
        self.assertNotEqual(p1.model, p2.model)
        self.assertIn(p1.model, p1.user_agent)
        self.assertIn("120.0.6099.144", p1.user_agent)
        adb = MagicMock()
        identity = DeviceIdentity("google", "Google", "Pixel 7", "14", "AP2A.240805.005")
        profile = BrowserSessionProfile.from_device(identity, chrome_version="120.0.6099.144")
        adb.shell.return_value = MagicMock(
            stdout=(
                'chrome --disable-blink-features=AutomationControlled '
                f'--user-agent="{profile.user_agent}"'
            ),
            ok=True,
        )
        report = verify_browser_headers(adb, "s", profile)
        self.assertTrue(report.passed)
        self.assertTrue(report.chrome_flags_ok)


if __name__ == "__main__":
    unittest.main()
