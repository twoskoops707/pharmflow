from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

_AUTOMATION_DIR = Path(__file__).resolve().parent
if str(_AUTOMATION_DIR) not in sys.path:
    sys.path.insert(0, str(_AUTOMATION_DIR))

import browser_adb  # noqa: E402
import dashboard  # noqa: E402
import generate_dabflow_gold_matrix as gold_matrix  # noqa: E402
import tor_manager  # noqa: E402
from device_open_url import am_start_view_url_argv  # noqa: E402


class BrowserPackageOrderingTests(unittest.TestCase):
    def test_packages_for_view_url_attempts_keeps_oem_first_and_adds_mumu_browser(self):
        installed = {
            "com.sec.android.app.sbrowser",
            "com.mumudroid.browser",
            "com.android.chrome",
        }
        with (
            mock.patch.object(browser_adb, "default_view_package", return_value="com.sec.android.app.sbrowser"),
            mock.patch.object(
                browser_adb,
                "_installed_browser_candidates",
                return_value=["com.android.chrome"],
            ),
            mock.patch.object(browser_adb, "package_installed", side_effect=lambda _serial, pkg: pkg in installed),
        ):
            pkgs = browser_adb.packages_for_view_url_attempts("serial-1", "")

        self.assertEqual(pkgs[:3], ["com.sec.android.app.sbrowser", "com.mumudroid.browser", "com.android.chrome"])

    def test_packages_defers_chrome_default_to_last(self):
        installed = {
            "com.android.chrome",
            "com.mumudroid.browser",
        }
        with (
            mock.patch.object(browser_adb, "default_view_package", return_value="com.android.chrome"),
            mock.patch.object(browser_adb, "_installed_browser_candidates", return_value=[]),
            mock.patch.object(browser_adb, "package_installed", side_effect=lambda _serial, pkg: pkg in installed),
        ):
            pkgs = browser_adb.packages_for_view_url_attempts("127.0.0.1:16384", "")
        self.assertEqual(pkgs[0], "com.mumudroid.browser")
        self.assertEqual(pkgs[-1], "com.android.chrome")

    def test_packages_detects_nemu_style_browser_name(self):
        installed = {"com.vendor.nemu.browser"}
        with (
            mock.patch.object(browser_adb, "default_view_package", return_value=None),
            mock.patch.object(
                browser_adb,
                "_installed_browser_candidates",
                return_value=["com.vendor.nemu.browser"],
            ),
            mock.patch.object(browser_adb, "package_installed", side_effect=lambda _serial, pkg: pkg in installed),
        ):
            pkgs = browser_adb.packages_for_view_url_attempts("serial-1", "")
        self.assertIn("com.vendor.nemu.browser", pkgs)


class OpenUrlNavigationRetryTests(unittest.TestCase):
    def test_navigation_retry_uses_generic_view_only_for_net_errors_when_enabled(self):
        first = dashboard.AdbResult(
            argv=("adb", "-s", "serial-1", "shell", "am", "start"),
            returncode=0,
            stdout="",
            stderr="Warning: browser showed net::ERR_CONNECTION_RESET",
        )
        second = dashboard.AdbResult(
            argv=("adb", "-s", "serial-1", *am_start_view_url_argv("https://getdabflow.app")),
            returncode=0,
            stdout="Starting: Intent",
            stderr="",
        )
        calls: list[tuple[str, ...]] = []

        def fake_adb(_serial: str, *argv, **_kwargs):
            calls.append(tuple(argv))
            return second

        with (
            mock.patch.dict(os.environ, {"PHARMFLOW_OPEN_URL_NAV_RETRY": "1"}),
            mock.patch.object(dashboard, "_adb", side_effect=fake_adb),
        ):
            result = dashboard._retry_open_url_action_view_for_browser_net_error(
                "serial-1", "https://getdabflow.app", first
            )

        self.assertIs(result, second)
        self.assertEqual(calls, [tuple(am_start_view_url_argv("https://getdabflow.app"))])

    def test_navigation_retry_is_enabled_by_default(self):
        first = dashboard.AdbResult(
            argv=(),
            returncode=0,
            stdout="",
            stderr="net::ERR_CONNECTION_RESET",
        )
        second = dashboard.AdbResult(
            argv=("adb", "-s", "serial-1", *am_start_view_url_argv("https://getdabflow.app")),
            returncode=0,
            stdout="Starting: Intent",
            stderr="",
        )
        calls: list[tuple[str, ...]] = []

        def fake_adb(_serial: str, *argv, **_kwargs):
            calls.append(tuple(argv))
            return second

        with (
            mock.patch.dict(os.environ, {"PHARMFLOW_OPEN_URL_NAV_RETRY_BACKOFF_SEC": "0"}, clear=True),
            mock.patch.object(dashboard, "_adb", side_effect=fake_adb),
        ):
            result = dashboard._retry_open_url_action_view_for_browser_net_error(
                "serial-1", "https://getdabflow.app", first
            )

        self.assertIs(result, second)
        self.assertEqual(calls, [tuple(am_start_view_url_argv("https://getdabflow.app"))])

    def test_navigation_retry_disabled_when_env_zero(self):
        first = dashboard.AdbResult(
            argv=(),
            returncode=0,
            stdout="",
            stderr="net::ERR_CONNECTION_RESET",
        )
        with (
            mock.patch.dict(os.environ, {"PHARMFLOW_OPEN_URL_NAV_RETRY": "0"}),
            mock.patch.object(dashboard, "_adb") as adb_mock,
        ):
            result = dashboard._retry_open_url_action_view_for_browser_net_error(
                "serial-1", "https://getdabflow.app", first
            )

        self.assertIs(result, first)
        adb_mock.assert_not_called()


class TorWarmDoubleWaitTests(unittest.TestCase):
    """Regression for the open_url double-wait: when a warm worker has just exited without
    setting the host-ready event, the synchronous ``ensure_tor_and_proxy_for_phone`` should
    use a short retry budget (<= 15s) instead of waiting another full
    ``PHARMFLOW_TOR_WAIT_SOCKS`` + ``PHARMFLOW_TOR_WAIT_HTTP`` window (8+ minutes blocked browser).
    """

    def setUp(self) -> None:
        with tor_manager._tor_warm_last_exit_lock:
            tor_manager._tor_warm_last_exit_ts.clear()
        with tor_manager._tor_host_ready_lock:
            tor_manager._tor_host_ready_events.clear()

    def test_recent_warm_attempt_short_circuits_ensure_wait(self):
        tor_manager._record_warm_attempt_exit(0)
        self.assertTrue(tor_manager._recent_warm_attempt(0, window_sec=60.0))

        called_timeouts: list[int] = []

        def fake_wait_for_tor(idx: int, timeout: int = 30) -> bool:
            called_timeouts.append(int(timeout))
            return False

        def fake_wait_for_http(idx: int, timeout: int = 30) -> bool:
            called_timeouts.append(int(timeout))
            return False

        with (
            mock.patch.object(tor_manager, "start_tor_for_phone", return_value=9050),
            mock.patch.object(tor_manager, "wait_for_tor", side_effect=fake_wait_for_tor),
            mock.patch.object(tor_manager, "wait_for_tor_http_tunnel", side_effect=fake_wait_for_http),
            mock.patch.object(tor_manager, "tor_wait_socks_seconds", return_value=240),
            mock.patch.object(tor_manager, "tor_wait_http_seconds", return_value=240),
            mock.patch.object(tor_manager, "apply_identity_adb", return_value={}),
        ):
            result = tor_manager.ensure_tor_and_proxy_for_phone("serial-1", 0)

        self.assertFalse(result.get("ok"))
        # Short retry budget — never the full 240s when a warm worker just exited.
        self.assertTrue(all(t <= 15 for t in called_timeouts), f"saw timeouts={called_timeouts}")
        self.assertIn("recent prewarm", result.get("error", ""))

    def test_recent_warm_bootstrap_uses_full_bootstrap_budget_not_13s(self):
        """After a failed warm, port waits stay short but bootstrap must not cap at ws_eff-2 (~13s)."""
        tor_manager._record_warm_attempt_exit(0)
        bootstrap_timeouts: list[int] = []

        def fake_bootstrap(idx: int, timeout: int = 120) -> bool:
            bootstrap_timeouts.append(int(timeout))
            return False

        with (
            mock.patch.object(tor_manager, "start_tor_for_phone", return_value=9050),
            mock.patch.object(tor_manager, "wait_for_tor", return_value=True),
            mock.patch.object(tor_manager, "wait_for_tor_bootstrap", side_effect=fake_bootstrap),
            mock.patch.object(tor_manager, "wait_for_tor_http_tunnel", return_value=True),
            mock.patch.object(tor_manager, "tor_wait_socks_seconds", return_value=240),
            mock.patch.object(tor_manager, "tor_wait_http_seconds", return_value=240),
            mock.patch.object(tor_manager, "tor_wait_bootstrap_seconds", return_value=120),
            mock.patch.object(tor_manager, "_shell"),
            mock.patch.object(tor_manager, "apply_identity_adb") as apply_mock,
        ):
            with tor_manager._tor_host_ready_lock:
                tor_manager._tor_host_ready_events.clear()
            result = tor_manager.ensure_tor_and_proxy_for_phone("127.0.0.1:16384", 0)

        self.assertFalse(result.get("ok"))
        self.assertEqual(bootstrap_timeouts, [120])
        self.assertNotIn("13s", result.get("error", ""))
        self.assertIn("PHARMFLOW_TOR_WAIT_BOOTSTRAP", result.get("error", ""))
        apply_mock.assert_not_called()

    def test_bootstrap_response_parser_accepts_common_tor_formats(self):
        self.assertTrue(tor_manager._tor_control_bootstrap_response_done("250-status/bootstrap-phase\nPROGRESS=100"))
        self.assertTrue(tor_manager._tor_control_bootstrap_response_done("250-status/bootstrap-phase\nTAG=done"))
        self.assertTrue(tor_manager._tor_control_bootstrap_response_done("250 OK\nBootstrapped 100% (done): Done"))
        self.assertFalse(tor_manager._tor_control_bootstrap_response_done("250-status/bootstrap-phase\nPROGRESS=50"))

    def test_bootstrap_log_tail_detects_bootstrapped_100(self):
        with tempfile.TemporaryDirectory() as td:
            data = Path(td) / "data_0"
            data.mkdir()
            (data / "tor.log").write_text(
                "May 17 12:00:00.000 [notice] Bootstrapped 100% (done): Done\n",
                encoding="utf-8",
            )
            with mock.patch.object(tor_manager, "TOR_DIR", Path(td)):
                self.assertTrue(tor_manager._bootstrap_indicated_in_tor_log(0))

    def test_no_recent_warm_uses_full_wait_budget(self):
        called_timeouts: list[int] = []

        def fake_wait_for_tor(idx: int, timeout: int = 30) -> bool:
            called_timeouts.append(int(timeout))
            return False

        def fake_wait_for_http(idx: int, timeout: int = 30) -> bool:
            called_timeouts.append(int(timeout))
            return False

        with (
            mock.patch.object(tor_manager, "start_tor_for_phone", return_value=9050),
            mock.patch.object(tor_manager, "wait_for_tor", side_effect=fake_wait_for_tor),
            mock.patch.object(tor_manager, "wait_for_tor_http_tunnel", side_effect=fake_wait_for_http),
            mock.patch.object(tor_manager, "tor_wait_socks_seconds", return_value=240),
            mock.patch.object(tor_manager, "tor_wait_http_seconds", return_value=240),
            mock.patch.object(tor_manager, "apply_identity_adb", return_value={}),
        ):
            result = tor_manager.ensure_tor_and_proxy_for_phone("serial-2", 1)

        self.assertFalse(result.get("ok"))
        # No prewarm recorded for idx=1 → full budget honored.
        self.assertEqual(called_timeouts[0], 240)


class EmulatorProxyRoutingTests(unittest.TestCase):
    def test_serial_looks_like_emulator_includes_mumu_nat_serial(self):
        self.assertTrue(tor_manager._serial_looks_like_emulator("10.0.2.66:5555"))
        self.assertTrue(tor_manager._serial_looks_like_emulator("10.0.2.253:5555"))

    def test_mumu_guest_bridge_serial_uses_reverse_not_gateway(self):
        self.assertTrue(tor_manager._adb_serial_is_mumu_guest_bridge("10.0.2.120:5555"))
        self.assertFalse(tor_manager._use_gateway_proxy_mode("10.0.2.120:5555"))
        self.assertFalse(tor_manager._adb_serial_is_mumu_guest_bridge("10.0.2.2:5555"))
        with mock.patch.dict(os.environ, {"PHARMFLOW_PROXY_LEGACY_GATEWAY": "1"}, clear=False):
            self.assertFalse(tor_manager._use_gateway_proxy_mode("10.0.2.120:5555"))
            self.assertFalse(tor_manager._use_gateway_proxy_mode("emulator-5554"))

    def test_apply_identity_uses_reverse_for_mumu_guest_bridge(self):
        shell_calls: list[tuple] = []
        reverse_calls: list[tuple] = []

        def fake_shell(serial: str, *args: str, timeout: int = 15):
            shell_calls.append((serial, args))
            return mock.Mock(returncode=0, stdout="", stderr="")

        def fake_reverse(*_a, **_k):
            reverse_calls.append(_a)
            return True

        with (
            mock.patch.object(tor_manager, "http_proxy_port_for_phone_idx", return_value=8118),
            mock.patch.object(tor_manager, "socks_port_for_phone_idx", return_value=9050),
            mock.patch.object(tor_manager, "_adb_reverse_tcp_pair_with_retries", side_effect=fake_reverse),
            mock.patch.object(tor_manager, "_reverse_tcp_remove"),
            mock.patch.object(tor_manager, "_shell", side_effect=fake_shell),
            mock.patch.object(tor_manager, "browser_pkg_for_clear", return_value=None),
        ):
            result = tor_manager.apply_identity_adb("10.0.2.120:5555", 0)

        self.assertEqual(result.get("proxy_mode"), "adb_reverse")
        self.assertEqual(result.get("http_proxy"), "127.0.0.1:8118")
        self.assertTrue(result.get("http_proxy_applied"))
        self.assertEqual(len(reverse_calls), 1, "MuMu guest bridge must use adb reverse")
        self.assertTrue(
            any(args == ("settings", "put", "global", "http_proxy", "127.0.0.1:8118") for _s, args in shell_calls),
            shell_calls,
        )


class ApplyIdentityStaleProxyTests(unittest.TestCase):
    """When ``adb reverse`` fails, the guest proxy is left in place. Deleting it is host-IP egress."""

    def test_apply_identity_does_not_clear_http_proxy_when_reverse_fails(self):
        shell_calls: list[tuple] = []

        def fake_shell(serial: str, *args: str, timeout: int = 15):
            shell_calls.append((serial, args))
            return mock.Mock(returncode=0, stdout="", stderr="")

        with (
            mock.patch.object(tor_manager, "http_proxy_port_for_phone_idx", return_value=8118),
            mock.patch.object(tor_manager, "socks_port_for_phone_idx", return_value=9050),
            mock.patch.object(tor_manager, "_tor_proxy_host_for_device", return_value="127.0.0.1"),
            mock.patch.object(tor_manager, "_use_gateway_proxy_mode", return_value=False),
            mock.patch.object(tor_manager, "_adb_reverse_tcp_pair_with_retries", return_value=False),
            mock.patch.object(tor_manager, "_reverse_tcp_remove"),
            mock.patch.object(tor_manager, "_shell", side_effect=fake_shell),
        ):
            result = tor_manager.apply_identity_adb("127.0.0.1:16384", 0)

        self.assertFalse(result.get("http_proxy_applied"))
        self.assertFalse(result.get("adb_reverse_ok"))
        self.assertFalse(
            any(args[:4] == ("settings", "delete", "global", "http_proxy") for _s, args in shell_calls),
            f"must not delete http_proxy when reverse fails, got {shell_calls}",
        )
        self.assertFalse(
            any(
                len(args) >= 5
                and args[:4] == ("settings", "put", "global", "http_proxy")
                and str(args[4]).endswith(":0")
                for _s, args in shell_calls
            ),
            shell_calls,
        )


class EnsureTorReverseFailureTests(unittest.TestCase):
    """``ensure_tor_and_proxy_for_phone`` must surface failed ``adb reverse`` (not leave browser broken)."""

    def test_ensure_tor_fails_when_adb_reverse_not_ok(self):
        with (
            mock.patch.object(tor_manager, "start_tor_for_phone", return_value=9050),
            mock.patch.object(tor_manager, "wait_for_tor", return_value=True),
            mock.patch.object(tor_manager, "wait_for_tor_http_tunnel", return_value=True),
            mock.patch.object(
                tor_manager,
                "apply_identity_adb",
                return_value={"proxy_mode": "adb_reverse", "adb_reverse_ok": False},
            ),
        ):
            r = tor_manager.ensure_tor_and_proxy_for_phone("dev-1", 0)
        self.assertFalse(r.get("ok"))
        self.assertIn("adb reverse", r.get("error", ""))


class PhoneIdxFromAdbSerialTests(unittest.TestCase):
    def test_avd_emulator_serials(self):
        self.assertEqual(tor_manager.phone_idx_from_adb_serial("emulator-5554"), 0)
        self.assertEqual(tor_manager.phone_idx_from_adb_serial("emulator-5556"), 1)


    def test_mumu_guest_bridge_serials_use_distinct_tor_slots_from_prefs(self):
        with mock.patch.object(
            tor_manager,
            "_phone_idx_from_prefs_serial_list",
            side_effect=lambda s: {"10.0.2.120:5555": 0, "10.0.2.130:5555": 1, "10.0.2.171:5555": 2}.get(s),
        ):
            self.assertEqual(tor_manager.phone_idx_from_adb_serial("10.0.2.120:5555"), 0)
            self.assertEqual(tor_manager.phone_idx_from_adb_serial("10.0.2.130:5555"), 1)
            self.assertEqual(tor_manager.phone_idx_from_adb_serial("10.0.2.171:5555"), 2)

    def test_register_tor_slot_overrides_default(self):
        tor_manager.clear_tor_slots()
        tor_manager.register_tor_slot("10.0.2.171:5555", 2)
        self.assertEqual(tor_manager.phone_idx_from_adb_serial("10.0.2.171:5555"), 2)
        tor_manager.clear_tor_slots()

    def test_mumu_style_tcp_ports(self):
        self.assertEqual(tor_manager.phone_idx_from_adb_serial("127.0.0.1:16384"), 0)
        self.assertEqual(tor_manager.phone_idx_from_adb_serial("127.0.0.1:16416"), 1)

    def test_usb_defaults_zero(self):
        self.assertEqual(tor_manager.phone_idx_from_adb_serial("R58M30ABCDE"), 0)


class DabFlowOpenUrlFloorTests(unittest.TestCase):
    def test_getdabflow_open_url_post_wait_has_named_floor(self):
        rng = mock.Mock(uniform=mock.Mock(return_value=3.5))
        wait = gold_matrix._open_url_post_wait_secs("https://getdabflow.app", rng)
        self.assertGreaterEqual(wait, gold_matrix.PRE_SITE_OPEN_URL_POST_WAIT_MIN_SEC)
        self.assertLessEqual(wait, gold_matrix.PRE_SITE_OPEN_URL_POST_WAIT_MAX_SEC)


class ChromeDefaultGoesLastTests(unittest.TestCase):
    def test_chrome_device_default_placed_last_not_first(self):
        installed = {"com.android.chrome", "com.sec.android.app.sbrowser"}
        with (
            mock.patch.object(browser_adb, "default_view_package", return_value="com.android.chrome"),
            mock.patch.object(browser_adb, "_installed_browser_candidates", return_value=[]),
            mock.patch.object(browser_adb, "package_installed", side_effect=lambda _s, pkg: pkg in installed),
        ):
            pkgs = browser_adb.packages_for_view_url_attempts("serial-1", "")

        self.assertNotEqual(pkgs[0], "com.android.chrome")
        self.assertGreater(pkgs.index("com.android.chrome"), pkgs.index("com.sec.android.app.sbrowser"))


class OpenUrlAttemptsOemBeforeGenericTests(unittest.TestCase):
    def test_oem_package_before_generic_view_when_serial_provided(self):
        oem_pkg = "com.sec.android.app.sbrowser"
        with mock.patch.object(
            browser_adb,
            "packages_for_dabflow_view_url_attempts",
            return_value=[oem_pkg],
        ):
            attempts = dashboard._open_url_attempts("https://example.com", {}, serial="serial-1")

        reasons = [r for r, _ in attempts]
        oem_idx = next((i for i, r in enumerate(reasons) if r.startswith("oem-pkg-")), None)
        generic_idx = next(
            (i for i, r in enumerate(reasons) if r in ("generic-device-default", "step-configured")),
            None,
        )
        self.assertIsNotNone(oem_idx)
        self.assertIsNotNone(generic_idx)
        self.assertLess(oem_idx, generic_idx)


class EnsureTorBootstrapFailureTests(unittest.TestCase):
    def test_ensure_tor_fails_when_bootstrap_not_confirmed(self):
        with (
            mock.patch.object(tor_manager, "start_tor_for_phone", return_value=9050),
            mock.patch.object(tor_manager, "wait_for_tor", return_value=True),
            mock.patch.object(tor_manager, "wait_for_tor_bootstrap", return_value=False),
            mock.patch.object(tor_manager, "wait_for_tor_http_tunnel", return_value=True),
            mock.patch.object(tor_manager, "tor_wait_socks_seconds", return_value=30),
            mock.patch.object(tor_manager, "tor_wait_http_seconds", return_value=30),
            mock.patch.object(tor_manager, "_shell"),
            mock.patch.object(tor_manager, "apply_identity_adb") as apply_mock,
        ):
            with tor_manager._tor_host_ready_lock:
                tor_manager._tor_host_ready_events.clear()
            r = tor_manager.ensure_tor_and_proxy_for_phone("127.0.0.1:16384", 0)
        self.assertFalse(r.get("ok"))
        self.assertIn("bootstrap", r.get("error", "").lower())
        apply_mock.assert_not_called()


class AdbTcpReconnectTests(unittest.TestCase):
    def test_reconnect_skips_connect_when_already_device(self):
        with mock.patch.object(dashboard, "_serial_adb_devices_state", return_value="device"):
            with mock.patch.object(dashboard, "_adb_global") as adb_global:
                res = dashboard._try_adb_tcp_reconnect("127.0.0.1:16384")
        adb_global.assert_not_called()
        self.assertEqual(res.returncode, 0)

    def test_post_tor_grace_blocks_reconnect_when_device_listed(self):
        serial = "127.0.0.1:16384"
        dashboard.note_adb_serial_tor_settled(serial)
        dashboard._device_preflight_ok_at.pop(serial, None)  # force shell attempt; grace remains
        with (
            mock.patch.object(dashboard, "_adb", return_value=dashboard.AdbResult(
                argv=(), returncode=1, stdout="", stderr="device offline",
            )),
            mock.patch.object(dashboard, "_serial_adb_devices_state", return_value="device"),
            mock.patch.object(dashboard, "_serial_listed_as_online_device", return_value=True),
            mock.patch.object(dashboard, "_try_adb_tcp_reconnect") as reconnect_mock,
        ):
            ok = dashboard.ensure_adb_serial_ready(serial)
        reconnect_mock.assert_not_called()
        self.assertFalse(ok)


class TorBootstrapCheckTests(unittest.TestCase):
    def test_bootstrap_returns_true_when_tor_browser_mode(self):
        with mock.patch.object(tor_manager, "_standalone_tor_proc_alive", return_value=False):
            result = tor_manager.wait_for_tor_bootstrap(0, timeout=1)
        self.assertTrue(result)

    def test_bootstrap_returns_false_when_process_exits_early(self):
        with (
            mock.patch.object(tor_manager, "_standalone_tor_proc_alive", return_value=True),
            mock.patch.object(tor_manager, "_poll_standalone_tor_exit_code", return_value=1),
        ):
            result = tor_manager.wait_for_tor_bootstrap(0, timeout=2)
        self.assertFalse(result)

    def test_warm_sets_host_ready_only_after_bootstrap(self):
        with (
            mock.patch.object(tor_manager, "start_tor_for_phone", return_value=9050),
            mock.patch.object(tor_manager, "wait_for_tor", return_value=True),
            mock.patch.object(tor_manager, "wait_for_tor_bootstrap", return_value=False),
            mock.patch.object(tor_manager, "wait_for_tor_http_tunnel") as http_mock,
            mock.patch.object(tor_manager, "tor_wait_socks_seconds", return_value=30),
            mock.patch.object(tor_manager, "tor_wait_http_seconds", return_value=30),
        ):
            with tor_manager._tor_host_ready_lock:
                tor_manager._tor_host_ready_events.clear()
            tor_manager._warm_host_tor_ports_for_index(0)
            ev = tor_manager._get_host_ready_event(0)

        self.assertFalse(ev.is_set())
        http_mock.assert_not_called()

class OrderAdbSerialsByDesktopPrefsTests(unittest.TestCase):
    def test_order_follows_prefs_not_alphabetical(self):
        prefs_path = tor_manager.REC_DIR / "desktop_prefs.json"
        backup = prefs_path.read_text(encoding="utf-8") if prefs_path.is_file() else None
        try:
            prefs_path.write_text(
                json.dumps({"phone_serials": ["10.0.2.244:5555", "10.0.2.124:5555", "10.0.2.53:5555"]}) + "\n",
                encoding="utf-8",
            )
            got = tor_manager.order_adb_serials_by_desktop_prefs(
                {"10.0.2.124:5555", "10.0.2.53:5555", "10.0.2.244:5555"}
            )
            self.assertEqual(got, ["10.0.2.244:5555", "10.0.2.124:5555", "10.0.2.53:5555"])
        finally:
            if backup is None:
                prefs_path.unlink(missing_ok=True)
            else:
                prefs_path.write_text(backup, encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
