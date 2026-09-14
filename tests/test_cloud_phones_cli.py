"""Cloud setup must not report finish when no instance came online."""
from __future__ import annotations

import argparse
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import cloud_phones.cloud_phones_cli as cli  # noqa: E402


def _args(**extra: object) -> argparse.Namespace:
    base = {
        "host": "10.0.0.8",
        "count": 2,
        "start_port": 5555,
        "output": None,
        "verify": False,
    }
    base.update(extra)
    return argparse.Namespace(**base)


class CloudCountTests(unittest.TestCase):
    def test_omitted_count_is_not_eight(self) -> None:
        args = cli.build_parser().parse_args(["setup", "--host", "10.0.0.8"])
        self.assertIsNone(args.count)

    def test_omitted_count_walks_past_eight_then_stops_on_a_gap(self) -> None:
        answered = set(range(5555, 5565))

        def _answers(_host: str, port: int) -> bool:
            return port in answered

        args = _args(count=None)
        with patch.object(cli, "_port_answers", side_effect=_answers):
            n = cli.resolve_instance_count(args)
        self.assertEqual(n, 10)
        self.assertEqual(args.count, 10)

    def test_explicit_count_is_not_clamped(self) -> None:
        connects: list[str] = []

        def _cmd(cmd: list[str], timeout: float = 30.0) -> tuple[bool, str]:
            if len(cmd) >= 2 and cmd[-2] == "connect":
                connects.append(cmd[-1])
                return True, "connected to " + cmd[-1]
            return True, ""

        def _adb(serial: str, *args: str, timeout: float = 30.0) -> tuple[bool, str]:
            return False, "offline"

        with (
            patch.object(cli, "run_cmd", side_effect=_cmd),
            patch.object(cli, "run_adb", side_effect=_adb),
        ):
            code = cli.cmd_connect(_args(count=9))
        self.assertEqual(len(connects), 9)
        self.assertEqual(code, 1)

    def test_classic_cloud_dialogs_do_not_cap_at_16(self) -> None:
        src = (ROOT / "wizard" / "pharmflow_desktop.py").read_text(encoding="utf-8")
        self.assertNotIn("maxvalue=16", src)


class CloudSetupHonestyTests(unittest.TestCase):
    def test_connect_does_not_count_a_handshake_that_has_not_booted(self) -> None:
        def _cmd(cmd: list[str], timeout: float = 30.0) -> tuple[bool, str]:
            return True, "connected to 10.0.0.8:5555"

        def _adb(serial: str, *args: str, timeout: float = 30.0) -> tuple[bool, str]:
            if args[:2] == ("shell", "getprop"):
                return True, "0"
            return False, "offline"

        with (
            patch.object(cli, "run_cmd", side_effect=_cmd),
            patch.object(cli, "run_adb", side_effect=_adb),
        ):
            code = cli.cmd_connect(_args(count=1))
        self.assertEqual(code, 1)

    def test_connect_counts_only_when_every_instance_booted(self) -> None:
        def _adb(serial: str, *args: str, timeout: float = 30.0) -> tuple[bool, str]:
            if args[:1] == ("wait-for-device",):
                return True, "ok"
            if args[:2] == ("shell", "getprop"):
                return True, "1"
            return False, "offline"

        with patch.object(cli, "run_adb", side_effect=_adb):
            code = cli.cmd_connect(_args(count=2))
        self.assertEqual(code, 0)

    def test_tor_does_not_finish_when_only_some_phones_pin(self) -> None:
        def _adb(serial: str, *args: str, timeout: float = 30.0) -> tuple[bool, str]:
            if args[:1] == ("wait-for-device",):
                return serial.endswith(":5555"), "ok"
            if args[:4] == ("shell", "settings", "get", "global"):
                return True, "127.0.0.1:8118"
            return True, "ok"

        with (
            patch.object(cli, "run_adb", side_effect=_adb),
            patch.object(cli, "_guest_http_tunnel_open", return_value=True),
            patch.object(cli.time, "sleep"),
        ):
            code = cli.cmd_tor(_args(count=2))
        self.assertEqual(code, 1)

    def test_setup_stops_when_no_instance_comes_online(self) -> None:
        with (
            patch.object(cli, "cmd_connect", return_value=1) as connect,
            patch.object(cli, "cmd_stealth") as stealth,
            patch.object(cli, "cmd_tor") as tor,
        ):
            code = cli.cmd_setup(_args())
        self.assertEqual(code, 1)
        connect.assert_called_once()
        stealth.assert_not_called()
        tor.assert_not_called()

    def test_setup_stops_when_stealth_applies_to_nobody(self) -> None:
        with (
            patch.object(cli, "cmd_connect", return_value=0),
            patch.object(cli, "cmd_stealth", return_value=1),
            patch.object(cli, "cmd_tor") as tor,
        ):
            code = cli.cmd_setup(_args())
        self.assertEqual(code, 1)
        tor.assert_not_called()

    def test_tor_fails_when_no_proxy_is_set(self) -> None:
        with patch.object(cli, "run_adb", return_value=(False, "offline")):
            code = cli.cmd_tor(_args())
        self.assertEqual(code, 1)

    def test_tor_does_not_set_proxy_until_http_tunnel_opens(self) -> None:
        calls: list[tuple[str, ...]] = []

        def _adb(serial: str, *args: str, timeout: float = 30.0) -> tuple[bool, str]:
            calls.append(args)
            if args[:1] == ("wait-for-device",):
                return True, "ok"
            return True, ""

        with (
            patch.object(cli, "run_adb", side_effect=_adb),
            patch.object(cli, "_guest_http_tunnel_open", return_value=False),
            patch.object(cli.time, "sleep"),
        ):
            code = cli.cmd_tor(_args(count=1))
        self.assertEqual(code, 1)
        self.assertFalse(any("http_proxy" in args for args in calls))
        self.assertTrue(any("HTTPTunnelPort" in " ".join(args) for args in calls))

    def test_tor_proxy_uses_http_tunnel_not_socks(self) -> None:
        calls: list[tuple[str, ...]] = []

        def _adb(serial: str, *args: str, timeout: float = 30.0) -> tuple[bool, str]:
            calls.append(args)
            if args[:4] == ("shell", "settings", "get", "global"):
                return True, "127.0.0.1:8118"
            return True, "ok"

        with (
            patch.object(cli, "run_adb", side_effect=_adb),
            patch.object(cli, "_guest_http_tunnel_open", return_value=True),
            patch.object(cli.time, "sleep"),
        ):
            code = cli.cmd_tor(_args(count=1))
        self.assertEqual(code, 0)
        puts = [args for args in calls if args[:3] == ("shell", "settings", "put")]
        self.assertEqual(
            puts,
            [("shell", "settings", "put", "global", "http_proxy", "127.0.0.1:8118")],
        )
        gets = [args for args in calls if args[:3] == ("shell", "settings", "get")]
        self.assertEqual(gets, [("shell", "settings", "get", "global", "http_proxy")])
        self.assertFalse(any(args[-1:] == ("127.0.0.1:9050",) for args in puts))

    def test_tor_does_not_count_a_put_whose_readback_is_not_the_loopback(self) -> None:
        def _adb(serial: str, *args: str, timeout: float = 30.0) -> tuple[bool, str]:
            if args[:4] == ("shell", "settings", "get", "global"):
                return True, ":0"
            return True, "ok"

        with (
            patch.object(cli, "run_adb", side_effect=_adb),
            patch.object(cli, "_guest_http_tunnel_open", return_value=True),
            patch.object(cli.time, "sleep"),
        ):
            code = cli.cmd_tor(_args(count=1))
        self.assertEqual(code, 1)

    def test_stealth_does_not_count_a_setprop_the_guest_did_not_keep(self) -> None:
        def _adb(serial: str, *args: str, timeout: float = 30.0) -> tuple[bool, str]:
            if args[:1] == ("wait-for-device",):
                return True, "ok"
            if args[:2] == ("shell", "getprop"):
                return True, "generic/sdk/generic:14/userdebug"
            return True, ""

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "profiles.json"
            with patch.object(cli, "run_adb", side_effect=_adb):
                code = cli.cmd_stealth(_args(count=1, output=str(out)))
        self.assertEqual(code, 1)

    def test_stealth_fails_when_fingerprint_is_not_set(self) -> None:
        def _adb(serial: str, *args: str, timeout: float = 30.0) -> tuple[bool, str]:
            if args[:1] == ("wait-for-device",):
                return True, "ok"
            return False, "setprop failed"

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "profiles.json"
            with patch.object(cli, "run_adb", side_effect=_adb):
                code = cli.cmd_stealth(_args(output=str(out)))
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
