"""Tests for MuMu install detection and Chromium ABI downloads."""

from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock

_WIZ = Path(__file__).resolve().parent
if str(_WIZ) not in sys.path:
    sys.path.insert(0, str(_WIZ))

import browser_setup  # noqa: E402
import mumu_detect  # noqa: E402
import mumu_farm_ops as farm  # noqa: E402


class BrowserAbiTests(unittest.TestCase):
    def test_chromium_platform_arm64(self) -> None:
        self.assertEqual(browser_setup.chromium_platform_for_abi("arm64-v8a"), "Android_Arm64")
        self.assertEqual(browser_setup.chromium_platform_for_abi("armeabi-v7a"), "Android")

    def test_apk_native_abis_from_zip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            apk = Path(td) / "test.apk"
            with zipfile.ZipFile(apk, "w") as zf:
                zf.writestr("lib/arm64-v8a/libchrome.so", b"x")
            self.assertEqual(browser_setup.apk_native_abis(apk), {"arm64-v8a"})

    def test_is_abi_mismatch_error(self) -> None:
        self.assertTrue(
            browser_setup.is_abi_mismatch_error("Failure [INSTALL_FAILED_NO_MATCHING_ABIS]")
        )
        self.assertTrue(
            browser_setup.is_abi_mismatch_error("Failed to extract native libraries")
        )

    def test_chromium_apk_filename(self) -> None:
        self.assertEqual(
            browser_setup.chromium_apk_filename("arm64-v8a"),
            "ChromePublic-arm64-v8a.apk",
        )


class BrowserSetupInstallTests(unittest.TestCase):
    def test_install_chromium_apk_skips_when_already_installed(self) -> None:
        apk = Path("/tmp/ChromePublic.apk")
        with mock.patch.object(browser_setup, "pkg_installed", side_effect=lambda _s, pkg: pkg == "org.chromium.chrome"):
            with mock.patch.object(browser_setup, "install_apk") as mock_install:
                ok, pkg, msg = browser_setup.install_chromium_apk("10.0.2.15:5555", apk)
        self.assertTrue(ok)
        self.assertEqual(pkg, "org.chromium.chrome")
        mock_install.assert_not_called()

    def test_pick_browser_pkg_dabflow_prefers_chromium(self) -> None:
        with mock.patch.object(browser_setup, "pkg_installed") as pi:
            pi.side_effect = lambda _s, pkg: pkg in (
                browser_setup.CHROMIUM_PUBLIC_PKG,
                browser_setup.MUMU_BROWSER_PKG,
            )
            pkg = browser_setup.pick_browser_pkg("10.0.2.15:5555", dabflow=True)
        self.assertEqual(pkg, browser_setup.CHROMIUM_PUBLIC_PKG)

    def test_dabflow_ad_browser_installed(self) -> None:
        with mock.patch.object(browser_setup, "pkg_installed", side_effect=lambda _s, pkg: pkg == "org.chromium.chrome"):
            self.assertTrue(browser_setup.dabflow_ad_browser_installed("x"))
        with mock.patch.object(browser_setup, "pkg_installed", return_value=False):
            self.assertFalse(browser_setup.dabflow_ad_browser_installed("x"))

    def test_install_chromium_on_phones_uses_force_sideload_not_ensure_browser(self) -> None:
        serials = ["10.0.2.15:5555"]
        with tempfile.NamedTemporaryFile(suffix=".apk") as tmp:
            fake_apk = Path(tmp.name)
            with mock.patch.object(browser_setup, "resolve_chromium_apk", return_value=fake_apk):
                with mock.patch.object(browser_setup, "device_primary_abi", return_value="arm64-v8a"):
                    with mock.patch.object(
                        browser_setup,
                        "install_chromium_apk",
                        return_value=(True, "org.chromium.chrome", "Installed ChromePublic.apk (Chromium)"),
                    ) as mock_force:
                        with mock.patch.object(browser_setup, "ensure_browser") as mock_ensure:
                            with mock.patch.object(browser_setup, "warm_browser"):
                                summary = farm.install_chromium_on_phones(serials, lambda _m: None)
            self.assertTrue(summary["ok"])
            mock_force.assert_called_once()
            mock_ensure.assert_not_called()


class ChromiumResetTests(unittest.TestCase):
    def test_reset_skips_when_env_disabled(self) -> None:
        with mock.patch.dict("os.environ", {"CPHARM_SKIP_CHROMIUM_RESET": "1"}):
            with mock.patch.object(browser_setup, "pkg_installed", return_value=True):
                with mock.patch.object(browser_setup, "_adb") as mock_adb:
                    ok = browser_setup.reset_chromium_session("10.0.2.15:5555")
        self.assertFalse(ok)
        mock_adb.assert_not_called()

    def test_reset_pm_clears_chromium(self) -> None:
        with mock.patch.object(browser_setup, "pkg_installed", return_value=True):
            with mock.patch.object(browser_setup, "_adb", return_value="Success") as mock_adb:
                ok = browser_setup.reset_chromium_session("10.0.2.15:5555")
        self.assertTrue(ok)
        pm_clear = [
            c
            for c in mock_adb.call_args_list
            if len(c.args) >= 5 and c.args[1:4] == ("shell", "pm", "clear")
        ]
        self.assertEqual(len(pm_clear), 1)
        self.assertEqual(pm_clear[0].args[4], browser_setup.CHROMIUM_PUBLIC_PKG)


class MumuDetectTests(unittest.TestCase):
    def test_install_root_from_exe_shell_layout(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "MuMuPlayerARM"
            vms = root / "vms"
            shell = root / "shell"
            vms.mkdir(parents=True)
            exe = shell / "MuMuPlayer.exe"
            shell.mkdir()
            exe.write_text("", encoding="utf-8")
            # Resolve both sides: Windows %TEMP% may surface the 8.3 short name
            # (RUNNER~1) on CI while Path() keeps the long form (runneradmin) —
            # same directory, different strings, flaky assertEqual otherwise.
            self.assertEqual(mumu_detect.install_root_from_exe(exe).resolve(), root.resolve())

    def test_find_mumu_install_via_env_root(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td) / "Netease" / "MuMuPlayerARM"
            exe = root / "nemux-shell-winui.Manager.exe"
            root.mkdir(parents=True)
            exe.write_text("", encoding="utf-8")
            with mock.patch.object(mumu_detect, "IS_WIN", True):
                with mock.patch.dict("os.environ", {"CPHARM_MUMU_ROOT": str(root)}):
                    hit = mumu_detect.find_mumu_install()
            self.assertIsNotNone(hit)
            self.assertTrue(hit.name.lower().endswith(".exe"))


if __name__ == "__main__":
    unittest.main()
