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
        with mock.patch.dict("os.environ", {"CPHARM_SKIP_STARTUP_CLEANUP": "1"}):
            summary = cleanup.run_startup_cleanup()
        self.assertIn("env", summary["skipped"])

    def test_non_windows_skips(self) -> None:
        with mock.patch.object(cleanup.sys, "platform", "linux"):
            summary = cleanup.run_startup_cleanup(first_time=True)
        self.assertIn("platform", summary["skipped"])

    def test_first_time_kills_mumu_not_protected(self) -> None:
        my_pid = 1000
        procs = [
            FakeProc(1000, "CPharmMuMuSetup.exe"),
            FakeProc(2001, "MuMuPlayer.exe", exe=r"C:\Program Files\Netease\MuMuPlayerARM\MuMuPlayer.exe"),
            FakeProc(2002, "adb.exe"),
            FakeProc(2003, "CPharm.exe"),
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
        self.assertIn("cpharm", killed)

    def test_not_first_time_skips_mumu(self) -> None:
        procs = [
            FakeProc(3001, "MuMuPlayer.exe"),
            FakeProc(3002, "CPharm.exe"),
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
        self.assertIn("cpharm", killed)
        self.assertNotIn("mumu", killed)


if __name__ == "__main__":
    unittest.main()
