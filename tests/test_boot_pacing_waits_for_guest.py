"""Boots must be paced: settle (and attach) one guest before launching the next.

Measured on the live box: launching guests back-to-back drove free RAM to 43 MB,
MuMu force-terminated the guest (`ExitType: ForcedExit`, `Initiator: Client`)
and its Manager crashed with 0xe0434352, taking the whole fleet with it. The
farm still boots every VM — just one at a time.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from automation import farm_exe_self_heal as heal  # noqa: E402


class BootPacingTest(unittest.TestCase):
    def test_next_boot_waits_for_previous_guest(self) -> None:
        events: list[str] = []

        def fake_boot(idx: int):
            events.append(f"boot:{idx}")
            return True, f"launched idx={idx}"

        def fake_wait(idx: int, budget: float = 90.0) -> str:
            events.append(f"settle:{idx}")
            return f"10.0.2.{idx}:5555"

        with mock.patch("automation.farm_canonical_phones._fleet_from_disk",
                        return_value={"vm2.gmadoa": "", "vm4.gmadoa": ""}), \
                mock.patch.object(heal, "_running_vm_indices", return_value=set()), \
                mock.patch.object(heal, "_boot_lane_disabled", return_value=False), \
                mock.patch.object(heal, "_load_boot_state", return_value={}), \
                mock.patch.object(heal, "_save_boot_state"), \
                mock.patch.object(heal, "_boot_cooldown_ok", return_value=(True, 0.0)), \
                mock.patch.object(heal, "_boot_per_tick", return_value=3), \
                mock.patch.object(heal, "_boot_blocked_by_headroom", return_value=""), \
                mock.patch.object(heal, "_boot_mumu_instance", side_effect=fake_boot), \
                mock.patch.object(heal, "_wait_guest_adb", side_effect=fake_wait):
            fixes = heal.connect_live_fleet(allow_boot=True)

        self.assertEqual(
            events,
            ["boot:2", "settle:2", "boot:4", "settle:4"],
            f"boots were not paced: {events}",
        )
        self.assertTrue(any("boot_settled idx=2 adb=10.0.2.2:5555" in f for f in fixes), fixes)


if __name__ == "__main__":
    unittest.main()
