"""A booted MuMu guest's setting.json must never be rewritten by the heal tick.

Writing a live player's VM config tears the guest down ("every time I spin up
emulators they crash"). Running VMs must be skipped and pick the rails up on
their next cold boot instead.
"""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from automation.mumu_fingerprint import reassert_all_vm_gpu_accel  # noqa: E402


def _seed(vms: Path, idx: int) -> Path:
    vm = vms / f"vm{idx}.gmadoa"
    vm.mkdir(parents=True, exist_ok=True)
    setting = vm / "setting.json"
    setting.write_text(
        json.dumps({"PerformanceType": "low", "GpuProp": {"Mode": "low"}}),
        encoding="utf-8",
    )
    return setting


class RunningGuestRailsTest(unittest.TestCase):
    def test_running_guest_is_skipped(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            vms = Path(td)
            running = _seed(vms, 2)
            stopped = _seed(vms, 3)
            before_running = running.read_bytes()

            fixes = reassert_all_vm_gpu_accel(vms, skip={"vm2.gmadoa"})

            self.assertIn("vm2.gmadoa:skipped_running", fixes)
            self.assertEqual(running.read_bytes(), before_running)
            # The stopped guest still gets the rails applied.
            self.assertTrue(stopped.is_file())

    def test_no_skip_still_processes_every_vm(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            vms = Path(td)
            _seed(vms, 2)
            fixes = reassert_all_vm_gpu_accel(vms)
            self.assertNotIn("vm2.gmadoa:skipped_running", fixes)


if __name__ == "__main__":
    unittest.main()
