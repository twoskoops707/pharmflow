"""Tests for automation/apk_tools.py."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from automation.apk_tools import install_apk_on_serials, package_from_apk


class ApkToolsTests(unittest.TestCase):
    def test_package_from_apk_missing_file(self) -> None:
        self.assertIsNone(package_from_apk(Path("does-not-exist.apk")))

    def test_package_from_apk_parses_aapt(self) -> None:
        with patch("automation.apk_tools.find_aapt_exe", return_value=Path("aapt.exe")):
            with patch("automation.apk_tools.subprocess.run") as run:
                run.return_value = MagicMock(
                    stdout="package: name='com.example.app' versionCode='1'\n",
                    returncode=0,
                )
                with patch.object(Path, "is_file", return_value=True):
                    pkg = package_from_apk(Path("fake.apk"))
        self.assertEqual(pkg, "com.example.app")

    def test_install_apk_on_serials(self) -> None:
        adb = MagicMock()
        adb.install.return_value = MagicMock(ok=True, stdout="Success")
        with patch.object(Path, "is_file", return_value=True):
            results = install_apk_on_serials(adb, Path("app.apk"), ["s1", "s2"])
        self.assertEqual(results, {"s1": True, "s2": True})
        self.assertEqual(adb.install.call_count, 2)


if __name__ == "__main__":
    unittest.main()
