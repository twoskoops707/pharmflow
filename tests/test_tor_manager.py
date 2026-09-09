"""Tests for automation/tor_manager.py."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from automation.tor_manager import (
    TorManager,
    _parse_public_ip,
    guest_proxy_endpoint,
    parse_http_tunnel_port,
    phone_control_port,
    phone_http_port,
    remember_exit_ip,
    verify_http_tunnel_enabled,
    write_torrc,
)


class TorManagerTests(unittest.TestCase):
    def test_phone_http_ports_increment_per_index(self) -> None:
        # Base is env-configured and auto-evades ports already claimed by other
        # processes (a live farm's Tor holds 8118+ on the dev box), so assert
        # the relative contract against the module's resolved base.
        from automation import tor_manager as tm

        base = int(tm.HTTP_TUNNEL_BASE)
        self.assertEqual(phone_http_port(0), base)
        self.assertEqual(phone_http_port(1), base + 1)
        self.assertEqual(phone_http_port(2), base + 2)
        self.assertEqual(guest_proxy_endpoint(1), f"127.0.0.1:{base + 1}")

    def test_write_torrc_enables_http_tunnel_port(self) -> None:
        from automation import tor_manager as tm

        expected = int(tm.HTTP_TUNNEL_BASE)
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cfg = write_torrc(0, data_root=root)
            self.assertTrue(verify_http_tunnel_enabled(cfg, expected_port=expected))
            text = cfg.read_text(encoding="utf-8")
            self.assertIn(f"HTTPTunnelPort {expected}", text)
            self.assertIn(f"ControlPort 127.0.0.1:{phone_control_port(0)}", text)

    def test_parse_public_ip(self) -> None:
        self.assertEqual(_parse_public_ip("1.2.3.4\n"), "1.2.3.4")
        self.assertEqual(_parse_public_ip("127.0.0.1"), "")
        self.assertEqual(_parse_public_ip("not an ip"), "")

    def test_rotate_until_unique_retries_on_same_ip(self) -> None:
        adb = MagicMock()
        mgr = TorManager(adb=adb)
        mgr.start_phone_tor = MagicMock(return_value=None)  # type: ignore[method-assign]
        mgr.rotate_identity = MagicMock(return_value=True)  # type: ignore[method-assign]
        # before known as 1.1.1.1; first two fetches still 1.1.1.1; third changes
        ips = ["1.1.1.1", "1.1.1.1", "9.9.9.9"]
        mgr.fetch_exit_ip = MagicMock(side_effect=ips)  # type: ignore[method-assign]
        with (
            patch("automation.tor_manager._persist_exit_ips"),
            patch("automation.tor_manager._load_exit_ips"),
        ):
            remember_exit_ip(0, "1.1.1.1")
            with patch.dict("os.environ", {"CPHARM_REQUIRE_UNIQUE_EXIT_IP": "1"}):
                result = mgr.rotate_until_unique_ip(
                    0, "serial", max_retries=5, avoid_other_phones=False
                )
        self.assertTrue(result.ok)
        self.assertTrue(result.changed)
        self.assertEqual(result.before, "1.1.1.1")
        self.assertEqual(result.after, "9.9.9.9")
        self.assertEqual(result.retries, 3)
        self.assertEqual(result.log_line(), "IP before=1.1.1.1 after=9.9.9.9 changed=yes retries=3")

    def test_rotate_rejects_other_phone_in_use_ip(self) -> None:
        adb = MagicMock()
        mgr = TorManager(adb=adb)
        mgr.start_phone_tor = MagicMock(return_value=None)  # type: ignore[method-assign]
        mgr.rotate_identity = MagicMock(return_value=True)  # type: ignore[method-assign]
        # Phone 1 holds 2.2.2.2; phone 0 must skip it and take 3.3.3.3.
        ips = ["2.2.2.2", "3.3.3.3"]
        mgr.fetch_exit_ip = MagicMock(side_effect=ips)  # type: ignore[method-assign]
        with (
            patch("automation.tor_manager._persist_exit_ips"),
            patch("automation.tor_manager._load_exit_ips"),
        ):
            remember_exit_ip(0, "1.1.1.1")
            remember_exit_ip(1, "2.2.2.2")
            result = mgr.rotate_until_unique_ip(
                0, "serial", max_retries=5, avoid_other_phones=True
            )
        self.assertTrue(result.ok)
        self.assertTrue(result.changed)
        self.assertEqual(result.after, "3.3.3.3")
        self.assertTrue(result.avoided_collision)
        self.assertGreaterEqual(result.retries, 2)

    def test_parse_http_tunnel_port(self) -> None:
        torrc = "# comment\nHTTPTunnelPort 8120\nSocksPort 9052\n"
        self.assertEqual(parse_http_tunnel_port(torrc), 8120)

    def test_verify_phone_tor_reports_failures(self) -> None:
        adb = MagicMock()
        adb.run.return_value = MagicMock(stdout="", stderr="", returncode=0)
        mgr = TorManager(adb=adb)
        with (
            patch.object(mgr, "_control_alive", return_value=False),
            patch.object(mgr, "_http_tunnel_alive", return_value=False),
        ):
            status = mgr.verify_phone_tor(0, adb_serial="127.0.0.1:16384")
        self.assertFalse(status.ok)
        self.assertIn("tor process not running", status.failures)

    def test_setup_reverse_sets_guest_proxy(self) -> None:
        adb = MagicMock()
        adb.reverse.return_value = MagicMock(ok=True)
        adb.set_http_proxy.return_value = MagicMock(ok=True)
        mgr = TorManager(adb=adb)
        mgr._setup_reverse("127.0.0.1:16384", 8118)
        adb.reverse.assert_called_once_with("8118", "8118", serial="127.0.0.1:16384")
        adb.set_http_proxy.assert_called_once_with("127.0.0.1", 8118, serial="127.0.0.1:16384")


if __name__ == "__main__":
    unittest.main()
