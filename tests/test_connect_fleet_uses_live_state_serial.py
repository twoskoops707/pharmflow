"""connect_live_fleet must dial the guest's live ADB endpoint, not a stale serial.

MuMu Player ARM hands out a new guest IP on every boot and publishes it in
``vms/vmN.gmadoa/misc/state.json``. The fleet map can still hold the previous
session's IP, so a connect against the remembered serial never answers and the
farm reports "no phones" while every emulator is actually running.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from automation import farm_exe_self_heal as heal  # noqa: E402

STALE = "10.0.2.105:5555"
LIVE = "10.0.2.62:5555"


def _write_state(vms: Path, idx: int, host: str, port: int = 5555) -> None:
    misc = vms / f"vm{idx}.gmadoa" / "misc"
    misc.mkdir(parents=True, exist_ok=True)
    (misc / "state.json").write_text(
        json.dumps({"ServerHost": "127.0.0.1", "ServerPort": 20198, "AdbHost": host, "AdbPort": port}),
        encoding="utf-8",
    )


class LiveSerialTest(unittest.TestCase):
    def test_live_serial_reads_state_json(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            vms = Path(td)
            _write_state(vms, 2, "10.0.2.62")
            with mock.patch.object(heal, "mumu_vms_dir", return_value=vms):
                self.assertEqual(heal._live_serial_for_vm(2), LIVE)

    def test_live_serial_empty_when_guest_not_up(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            vms = Path(td)
            _write_state(vms, 3, "")
            with mock.patch.object(heal, "mumu_vms_dir", return_value=vms):
                self.assertEqual(heal._live_serial_for_vm(3), "")

    def test_connect_uses_live_serial_over_remembered_one(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            vms = Path(td)
            _write_state(vms, 2, "10.0.2.62")
            connects: list[list[str]] = []

            def fake_run(cmd, timeout=20.0):
                if cmd[-2] == "connect":
                    connects.append(list(cmd))
                return 0, "connected"

            with mock.patch.object(heal, "mumu_vms_dir", return_value=vms), \
                    mock.patch("automation.farm_canonical_phones._fleet_from_disk",
                               return_value={"vm2.gmadoa": STALE}), \
                    mock.patch.object(heal, "_running_vm_indices", return_value={2}), \
                    mock.patch.object(heal, "_run", side_effect=fake_run):
                fixes = heal.connect_live_fleet(allow_boot=False)

            dialed = [cmd[cmd.index("connect") + 1] for cmd in connects]
            self.assertIn(LIVE, dialed)
            self.assertNotIn(STALE, dialed)
            self.assertTrue(any("ok=1" in f for f in fixes), fixes)


if __name__ == "__main__":
    unittest.main()
