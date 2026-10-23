"""Tests for wizard/setup_startup_cleanup.py."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

_WIZ = Path(__file__).resolve().parent
if str(_WIZ) not in sys.path:
    sys.path.insert(0, str(_WIZ))

import setup_startup_cleanup as cleanup  # noqa: E402


class FakeProc:
    def __init__(
        self,
        pid: int,
        name: str,
        *,
        exe: str = "",
        cmdline: list[str] | None = None,
    ) -> None:
        self.pid = pid
        self._name = name
        self._exe = exe
        self._cmdline = cmdline or []

    def name(self) -> str:
        return self._name

    def exe(self) -> str:
        return self._exe

    def cmdline(self) -> list[str]:
        return self._cmdline

    def create_time(self) -> float:
        return float(self.pid)

    def terminate(self) -> None:
        return None

    def wait(self, timeout: float | None = None) -> int:
        return 0

    def kill(self) -> None:
        return None

    def children(self, recursive: bool = False) -> list:
        return []


class SetupStartupCleanupTests(unittest.TestCase):
    def test_skip_env(self) -> None:
        with mock.patch.dict("os.environ", {"PHARMFLOW_SKIP_STARTUP_CLEANUP": "1"}):
            summary = cleanup.run_startup_cleanup()
        self.assertIn("env", summary["skipped"])

    def test_non_windows_skips(self) -> None:
        with mock.patch.object(cleanup.sys, "platform", "linux"):
            summary = cleanup.run_startup_cleanup(first_time=True)
        self.assertIn("platform", summary["skipped"])

    def test_first_time_kills_mumu_not_protected(self) -> None:
        my_pid = 1000
        procs = [
            FakeProc(1000, "PharmFlow.exe"),
            FakeProc(2001, "MuMuPlayer.exe", exe=r"C:\Program Files\Netease\MuMuPlayerARM\MuMuPlayer.exe"),
            FakeProc(2002, "adb.exe"),
            FakeProc(2003, "PharmFlow.exe"),
        ]

        import types

        fake_psutil = types.ModuleType("psutil")
        fake_psutil.process_iter = lambda attrs=None: procs  # noqa: E731
        fake_psutil.Process = lambda pid: FakeProc(pid, "self")  # noqa: E731

        with mock.patch.object(cleanup, "sys") as mock_sys:
            mock_sys.platform = "win32"
            with mock.patch.object(cleanup, "_adb_kill_server"):
                with mock.patch.object(cleanup, "_protected_pids", return_value={my_pid}):
                    with mock.patch.dict(sys.modules, {"psutil": fake_psutil}):
                        summary = cleanup.run_startup_cleanup(first_time=True, my_pid=my_pid)
        killed = " ".join(summary["killed"])
        self.assertIn("mumu", killed)
        self.assertIn("adb", killed)
        self.assertIn("pharmflow", killed)

    def test_not_first_time_skips_mumu(self) -> None:
        procs = [
            FakeProc(3001, "MuMuPlayer.exe"),
            FakeProc(3002, "PharmFlow.exe"),
        ]

        import types

        fake_psutil = types.ModuleType("psutil")
        fake_psutil.process_iter = lambda attrs=None: procs  # noqa: E731
        fake_psutil.Process = lambda pid: FakeProc(pid, "self")  # noqa: E731

        with mock.patch.object(cleanup, "sys") as mock_sys:
            mock_sys.platform = "win32"
            with mock.patch.object(cleanup, "_adb_kill_server"):
                with mock.patch.object(cleanup, "_protected_pids", return_value={9999}):
                    with mock.patch.dict(sys.modules, {"psutil": fake_psutil}):
                        summary = cleanup.run_startup_cleanup(first_time=False, my_pid=9999)
        killed = " ".join(summary["killed"])
        self.assertIn("pharmflow", killed)
        self.assertNotIn("mumu", killed)

    def test_repeat_open_does_not_kill_adb_or_farm(self) -> None:
        procs = [
            FakeProc(4001, "adb.exe"),
            FakeProc(4002, "PharmFlow.exe", cmdline=[r"C:\PharmFlow\PharmFlow.exe", "--start-farm"]),
            FakeProc(4003, "python.exe", cmdline=["python", "automation/dashboard.py"]),
            FakeProc(4004, "PharmFlow.exe", cmdline=[r"C:\PharmFlow\PharmFlow.exe"]),
        ]

        import types

        fake_psutil = types.ModuleType("psutil")
        fake_psutil.process_iter = lambda attrs=None: procs  # noqa: E731
        fake_psutil.Process = lambda pid: FakeProc(pid, "self")  # noqa: E731

        with mock.patch.object(cleanup, "sys") as mock_sys:
            mock_sys.platform = "win32"
            with mock.patch.object(cleanup, "_adb_kill_server") as kill_server:
                with mock.patch.object(cleanup, "_protected_pids", return_value={9999}):
                    with mock.patch.dict(sys.modules, {"psutil": fake_psutil}):
                        summary = cleanup.run_startup_cleanup(first_time=False, my_pid=9999)
        kill_server.assert_not_called()
        killed = " ".join(summary["killed"])
        skipped = " ".join(summary["skipped"])
        self.assertIn("4004", killed)
        self.assertNotIn("4002", killed)
        self.assertNotIn("4003", killed)
        self.assertIn("farm:4002", skipped)
        self.assertIn("farm:4003", skipped)

    def test_kill_server_skips_when_a_phone_is_answering(self) -> None:
        logs: list[str] = []
        fake_adb = mock.Mock(adb_executable=lambda: r"C:\adb.exe")

        def fake_run(cmd, **_kwargs):
            self.assertEqual(cmd[-1], "devices")
            return mock.Mock(returncode=0, stdout="List of devices attached\n10.0.2.16:5555\tdevice\n", stderr="")

        with mock.patch.dict(sys.modules, {"adb_paths": fake_adb}):
            with mock.patch.object(cleanup.subprocess, "run", side_effect=fake_run) as run:
                with mock.patch.object(cleanup.Path, "is_file", return_value=True):
                    cleanup._adb_kill_server(logs.append)
        self.assertEqual(run.call_count, 1)
        self.assertTrue(any("skipped adb kill-server" in line for line in logs))

    def test_kill_server_runs_only_when_no_phone_is_listed(self) -> None:
        logs: list[str] = []
        calls: list[list[str]] = []
        fake_adb = mock.Mock(adb_executable=lambda: r"C:\adb.exe")

        def fake_run(cmd, **_kwargs):
            calls.append(list(cmd))
            if cmd[-1] == "devices":
                return mock.Mock(returncode=0, stdout="List of devices attached\n", stderr="")
            return mock.Mock(returncode=0, stdout="", stderr="")

        with mock.patch.dict(sys.modules, {"adb_paths": fake_adb}):
            with mock.patch.object(cleanup.subprocess, "run", side_effect=fake_run):
                with mock.patch.object(cleanup.Path, "is_file", return_value=True):
                    cleanup._adb_kill_server(logs.append)
        self.assertEqual(calls[-1][-1], "kill-server")
        self.assertTrue(any(line.strip() == "adb kill-server" for line in logs))


if __name__ == "__main__":
    unittest.main()
