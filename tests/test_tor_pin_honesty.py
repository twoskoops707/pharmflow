"""A failed proxy write is not a pin, and the desktop Tor menu must not claim one."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import automation.tor_manager as tm  # noqa: E402
from wizard.pharmflow_desktop import merge_tor_desktop_prefs, tor_pin_landed  # noqa: E402


class TorPinHonestyTests(unittest.TestCase):
    def test_failed_settings_put_is_not_applied(self) -> None:
        failed = subprocess.CompletedProcess(args=["adb"], returncode=1, stdout="", stderr="no")
        with (
            patch.object(tm, "_use_gateway_proxy_mode", return_value=False),
            patch.object(tm, "_reverse_tcp_remove"),
            patch.object(tm, "_adb_reverse_tcp_pair_with_retries", return_value=True),
            patch.object(tm, "socks_port_for_phone_idx", return_value=9050),
            patch.object(tm, "_shell", return_value=failed) as shell,
        ):
            out = tm.apply_host_http_proxy_adb("10.0.2.20:5555", 20, 8138)
        self.assertFalse(out.get("http_proxy_applied"))
        self.assertIsNone(out.get("http_proxy"))
        shell.assert_called_once()

    def test_host_gateway_is_not_written(self) -> None:
        with (
            patch.object(tm, "_use_gateway_proxy_mode", return_value=True),
            patch.object(tm, "_tor_proxy_host_for_device", return_value="10.0.2.2"),
            patch.object(tm, "socks_port_for_phone_idx", return_value=9050),
            patch.object(tm, "_shell") as shell,
        ):
            out = tm.apply_host_http_proxy_adb("emulator-5554", 0, 8118)
        self.assertFalse(out.get("http_proxy_applied"))
        self.assertIsNone(out.get("http_proxy"))
        shell.assert_not_called()

    def test_loopback_pin_is_the_only_desktop_success(self) -> None:
        self.assertTrue(tor_pin_landed({"http_proxy_applied": True, "http_proxy": "127.0.0.1:8138"}))
        self.assertFalse(tor_pin_landed({"http_proxy_applied": False, "http_proxy": "127.0.0.1:8138"}))
        self.assertFalse(tor_pin_landed({"http_proxy_applied": True, "http_proxy": "10.0.2.2:8118"}))
        self.assertFalse(tor_pin_landed({"http_proxy_applied": True, "http_proxy": "127.0.0.1:0"}))

    def test_prefs_merge_keeps_the_setup_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "desktop_prefs.json"
            path.write_text(
                json.dumps({"mumu_setup_complete": True, "phone_serials": ["old"]}),
                encoding="utf-8",
            )
            merge_tor_desktop_prefs(path, ["10.0.2.20:5555"])
            stored = json.loads(path.read_text(encoding="utf-8"))
        self.assertTrue(stored.get("mumu_setup_complete"))
        self.assertTrue(stored.get("tor_proxy_configured"))
        self.assertEqual(stored.get("phone_serials"), ["10.0.2.20:5555"])

    def test_proxy_host_helper_never_names_this_pc(self) -> None:
        with patch.dict("os.environ", {"PHARMFLOW_TOR_PROXY_HOST": "192.168.1.10"}, clear=False):
            self.assertEqual(tm._tor_proxy_host_for_device("emulator-5554"), "127.0.0.1")
            self.assertEqual(tm._tor_proxy_host_for_device("10.0.2.20:5555"), "127.0.0.1")
        body = (ROOT / "automation" / "tor_manager.py").read_text(encoding="utf-8")
        helper = body.split("def _tor_proxy_host_for_device", 1)[1].split("\ndef ", 1)[0]
        self.assertNotIn('return "10.0.2.2"', helper)

    def test_legacy_flag_does_not_select_the_host_gateway(self) -> None:
        with patch.dict("os.environ", {"PHARMFLOW_PROXY_LEGACY_GATEWAY": "1"}, clear=False):
            self.assertFalse(tm._use_gateway_proxy_mode("10.0.2.120:5555"))
            self.assertFalse(tm._use_gateway_proxy_mode("emulator-5554"))
        setup = (ROOT / "automation" / "tor_manager.py").read_text(encoding="utf-8")
        body = setup.split("def _setup_reverse")[1].split("\n    def ")[0]
        self.assertNotIn('set_http_proxy("10.0.2.2"', body)

    def test_set_http_proxy_refuses_the_host_gateway(self) -> None:
        from automation.adb_wrapper import AdbWrapper

        adb = AdbWrapper()
        with patch.object(adb, "shell") as shell:
            refused = adb.set_http_proxy("10.0.2.2", 8118, serial="emulator-5554")
            zero = adb.set_http_proxy("127.0.0.1", 0, serial="emulator-5554")
        self.assertEqual(refused.returncode, 1)
        self.assertEqual(zero.returncode, 1)
        shell.assert_not_called()

    def test_billing_click_and_browse_refuse_a_missing_exit(self) -> None:
        runner = (ROOT / "automation" / "sequence_runner.py").read_text(encoding="utf-8")
        click = runner.split("Path3 click serial=", 1)[1].split("elif action == StepAction.WAIT:", 1)[0]
        refuse_at = click.find("Path3 click refused")
        open_at = click.find("maybe_fallback_ad_open_url")
        self.assertGreater(refuse_at, 0)
        self.assertGreater(open_at, refuse_at)
        browse = (ROOT / "automation" / "browser_farm.py").read_text(encoding="utf-8")
        body = browse.split("def browse_url", 1)[1].split("\ndef ", 1)[0]
        refuse = body.find("refusing browse")
        launch = body.find("ok = open_url(")
        self.assertGreater(refuse, 0)
        self.assertGreater(launch, refuse)
        self.assertIn("return False", body[refuse:launch])

    def test_tor_waits_are_not_cut_at_600(self) -> None:
        os.environ["PHARMFLOW_TOR_WAIT_SOCKS"] = "900"
        os.environ["PHARMFLOW_TOR_WAIT_HTTP"] = "900"
        os.environ["PHARMFLOW_TOR_WAIT_BOOTSTRAP"] = "900"
        try:
            self.assertEqual(tm.tor_wait_socks_seconds(), 900)
            self.assertEqual(tm.tor_wait_http_seconds(), 900)
            self.assertEqual(tm.tor_wait_bootstrap_seconds(), 900)
        finally:
            for key in (
                "PHARMFLOW_TOR_WAIT_SOCKS",
                "PHARMFLOW_TOR_WAIT_HTTP",
                "PHARMFLOW_TOR_WAIT_BOOTSTRAP",
            ):
                os.environ.pop(key, None)


if __name__ == "__main__":
    unittest.main()
