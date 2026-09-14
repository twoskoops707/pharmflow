"""Dashboard ADB recovery must not drop live phones or clear guest proxies."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from automation.dashboard import AdbResult, _adb_with_optional_daemon_recovery
from automation.tor_manager import TorManager, clear_all_proxies_on_devices


class DashboardAdbRecoveryTests(unittest.TestCase):
    def test_a_timeout_starts_the_server_and_does_not_kill_it(self) -> None:
        calls: list[list[str]] = []

        def _run(argv, timeout):
            calls.append([str(x) for x in argv])
            if "start-server" in calls[-1]:
                return AdbResult(tuple(calls[-1]), 0, "", "")
            if len(calls) == 1:
                return AdbResult(tuple(calls[-1]), 15, "", "timed out")
            return AdbResult(tuple(calls[-1]), 0, "List of devices attached\n", "")

        import automation.dashboard as dash

        dash._adb_server_recover_last = 0
        with (
            patch("automation.dashboard._adb_combine_run", side_effect=_run),
            patch("automation.dashboard._adb_reconnect_known_phones", return_value=None),
            patch.dict("os.environ", {"PHARMFLOW_ADB_START_SERVER": "1"}),
        ):
            _adb_with_optional_daemon_recovery(["adb", "devices"], 5)
        joined = " ".join(" ".join(c) for c in calls)
        self.assertNotIn("kill-server", joined)
        self.assertIn("start-server", joined)


class ProxyClearRefusedTests(unittest.TestCase):
    def test_module_clear_does_not_write_proxy_zero(self) -> None:
        out = clear_all_proxies_on_devices(["10.0.2.15:5555", ""])
        self.assertEqual(out, ["10.0.2.15:5555"])

    def test_manager_clear_does_not_shell(self) -> None:
        class _Adb:
            def shell(self, *args, **kwargs):
                raise AssertionError("clear must not shell")

            def reverse_remove(self, *args, **kwargs):
                raise AssertionError("clear must not drop reverse")

        mgr = TorManager.__new__(TorManager)
        mgr.adb = _Adb()
        out = mgr.clear_all_proxies_on_devices(["10.0.2.16:5555"])
        self.assertEqual(out, ["10.0.2.16:5555"])


class BondKeeperDoesNotKillServerTests(unittest.TestCase):
    def test_repair_starts_the_server_and_reconnects_every_serial(self) -> None:
        import automation.adb_bond_keeper as keeper

        calls: list[list[str]] = []

        def _run(args, timeout):
            calls.append(list(args))
            return "connected"

        missing = [f"10.0.2.{i}:5555" for i in range(30)]
        with (
            patch.object(keeper, "_run_adb", side_effect=_run),
            patch.object(keeper, "_known_candidate_serials", return_value=missing),
            patch.object(keeper, "_adb_online_serials", return_value=set()),
            patch.object(keeper.time, "sleep", return_value=None),
        ):
            keeper._repair_server()
        self.assertNotIn(["kill-server"], calls)
        self.assertIn(["start-server"], calls)
        connected = [c[1] for c in calls if c and c[0] == "connect"]
        self.assertEqual(connected, missing)

    def test_discovery_reconnect_has_no_twenty_four_stop(self) -> None:
        text = (
            __import__("pathlib").Path(__file__).resolve().parents[1]
            / "automation"
            / "farm_phone_discover.py"
        ).read_text(encoding="utf-8")
        body = text.split("def _reconnect_missing")[1].split("\ndef ")[0]
        self.assertNotIn("[:24]", body)
        farm = (
            __import__("pathlib").Path(__file__).resolve().parents[1]
            / "scripts"
            / "run_farm_354.py"
        ).read_text(encoding="utf-8")
        heal = farm.split("start-server + reconnecting fleet")[1].split("SELF-HEAL server restart")[0]
        self.assertNotIn('adb.run("kill-server"', heal)
        self.assertIn('adb.run("start-server"', heal)


class DashboardConnectTargetsTests(unittest.TestCase):
    def test_refresh_does_not_walk_a_fixed_port_list(self) -> None:
        import inspect

        import automation.dashboard as dash

        body = inspect.getsource(dash.auto_connect_emulators)
        targets = inspect.getsource(dash.auto_connect_targets)
        self.assertNotIn("EMULATOR_PORTS", body)
        self.assertNotIn("EMULATOR_PORTS", targets)
        self.assertNotIn("range(32)", targets)
        self.assertNotIn("16384 +", targets)

        with (
            patch(
                "automation.farm_phone_discover._known_candidate_serials",
                return_value=["10.0.2.40:5555", "10.0.2.41:5555"],
            ),
            patch.object(dash, "_published_redroid_serials", return_value=["127.0.0.1:18001"]),
            patch.object(dash, "_mumu_guest_ips_from_arp", return_value=["10.0.2.42"]),
        ):
            found = dash.auto_connect_targets()
        self.assertIn("10.0.2.40:5555", found)
        self.assertIn("10.0.2.41:5555", found)
        self.assertIn("127.0.0.1:18001", found)
        self.assertIn("10.0.2.42:5555", found)


if __name__ == "__main__":
    unittest.main()
