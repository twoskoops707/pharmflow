"""Tests for automation/tor_manager.py."""

from __future__ import annotations

import json
import os
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
        # Hermetic: slot resolution would otherwise read the HOST's live
        # ADB_SERIAL_MAP.lock.json (absolute vm indices map to dense slots).
        # Pin the identity slot map — the documented first-precedence input.
        with tempfile.TemporaryDirectory() as tmp:
            map_path = Path(tmp) / "ADB_SERIAL_MAP.lock.json"
            map_path.write_text(
                json.dumps({"phones": {"vm0.x": "10.0.2.1:5555", "vm1.x": "10.0.2.2:5555", "vm2.x": "10.0.2.3:5555"}}),
                encoding="utf-8",
            )
            with patch.dict(
                os.environ,
                {"CPHARM_LOGS": tmp, "PHARMFLOW_LOGS": tmp},
            ):
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
            with patch.dict("os.environ", {"PHARMFLOW_REQUIRE_UNIQUE_EXIT_IP": "1"}):
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


class TorWarmupHasNoPhoneCountCeilingTests(unittest.TestCase):
    """Repo rule: no hardcoded phone-count ceilings. High-index fleets (vm39+)
    must warm their own Tor lane, and the prewarm default follows the fleet."""

    def test_explicit_high_index_is_not_clamped_to_31(self) -> None:
        from automation import tor_manager as tm

        # Was silently remapped to 31 -> warmed the wrong (nonexistent) lane.
        self.assertEqual(tm._resolve_warm_phone_index(39), 39)
        self.assertEqual(tm._resolve_warm_phone_index(100), 100)

    def test_negative_index_is_still_guarded(self) -> None:
        from automation import tor_manager as tm

        self.assertEqual(tm._resolve_warm_phone_index(-5), 0)

    def test_env_warm_index_above_31_passes_through(self) -> None:
        from automation import tor_manager as tm

        with patch.dict(os.environ, {"PHARMFLOW_TOR_WARM_PHONE_INDEX": "44"}):
            self.assertEqual(tm._resolve_warm_phone_index(None), 44)

    def test_prewarm_env_above_31_passes_through(self) -> None:
        from automation import tor_manager as tm

        with patch.dict(os.environ, {"PHARMFLOW_TOR_PREWARM_MAX_IDX": "40"}):
            self.assertEqual(tm._tor_prewarm_max_idx(), 40)

    def test_prewarm_default_follows_live_fleet_size(self) -> None:
        from automation import tor_manager as tm

        env = {k: v for k, v in os.environ.items() if k != "PHARMFLOW_TOR_PREWARM_MAX_IDX"}
        with patch.dict(os.environ, env, clear=True):
            # A 40-phone fleet prewarms 40 lanes, not a fixed 8.
            with patch.object(tm, "live_fleet_indices", return_value=list(range(40, 80))):
                self.assertEqual(tm._tor_prewarm_max_idx(), 39)
            # A 3-phone fleet does not spin up 8 Tor processes it will never use.
            with patch.object(tm, "live_fleet_indices", return_value=[1, 2, 3]):
                self.assertEqual(tm._tor_prewarm_max_idx(), 2)
            # No discoverable roster: warm only lane 0; others start on demand.
            with patch.object(tm, "live_fleet_indices", return_value=[]):
                self.assertEqual(tm._tor_prewarm_max_idx(), 0)

    def test_bootstrap_background_does_not_reclamp_max_idx(self) -> None:
        """start_tor_host_bootstrap_background used to re-clamp to 31 after the
        resolver, which would silently undo an un-clamped max."""
        from automation import tor_manager as tm

        seen: list[int] = []

        class _FakeThread:
            def __init__(self, target=None, args=(), **_kw):
                seen.extend(args)

            def start(self) -> None:
                pass

            def is_alive(self) -> bool:
                return False

        with patch.object(tm, "_tor_skip_wait_env", return_value=False), \
                patch.object(tm, "tor_proxy_preflight", return_value={"ok": True}), \
                patch.object(tm.threading, "Thread", _FakeThread), \
                patch.object(tm, "_tor_prewarm_thread", None):
            tm.start_tor_host_bootstrap_background(max_phone_idx=57)
        self.assertEqual(seen, [57])

    def test_listening_lanes_walk_up_from_the_base_and_stop_at_the_first_gap(self) -> None:
        from automation import tor_manager as tm

        base = int(tm.HTTP_TUNNEL_BASE)
        up = {base, base + 1, base + 2, base + 4}  # base+3 is down: lanes are contiguous
        with patch.object(tm, "_tcp_open", side_effect=lambda p, timeout=0.4: p in up):
            self.assertEqual(tm.listening_tor_http_lane_ports(), [base, base + 1, base + 2])

    def test_listening_lanes_none_up_is_empty(self) -> None:
        from automation import tor_manager as tm

        with patch.object(tm, "_tcp_open", return_value=False):
            self.assertEqual(tm.listening_tor_http_lane_ports(), [])

    def test_listening_lanes_are_not_cut_at_eight(self) -> None:
        from automation import tor_manager as tm

        base = int(tm.HTTP_TUNNEL_BASE)
        up = set(range(base, base + 45))
        with patch.object(tm, "_tcp_open", side_effect=lambda p, timeout=0.4: p in up):
            self.assertEqual(len(tm.listening_tor_http_lane_ports()), 45)

    def test_listening_lanes_stop_at_the_end_of_the_port_space(self) -> None:
        from automation import tor_manager as tm

        with patch.object(tm, "HTTP_TUNNEL_BASE", 65533), patch.object(tm, "_tcp_open", return_value=True):
            self.assertEqual(tm.listening_tor_http_lane_ports(), [65533, 65534, 65535])


if __name__ == "__main__":
    unittest.main()
