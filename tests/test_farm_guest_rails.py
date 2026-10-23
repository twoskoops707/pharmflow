"""Farm guest rails: phone not tablet, root, writable, lean CPU/RAM."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

from automation.mumu_fingerprint import (
    apply_farm_guest_rails,
    apply_farm_guest_rails_file,
    apply_nx_mumu_guest_rails,
)


class FarmGuestRailsTests(unittest.TestCase):
    def test_phone_not_tablet_rooted_writable_lean(self) -> None:
        data = apply_farm_guest_rails({"resolution_width": 1920, "resolution_height": 1080})
        self.assertTrue(data["DeviceRoot"])
        self.assertFalse(data["is_tablet"])
        self.assertEqual(data["phone_type"], "phone")
        self.assertTrue(data["nand_writable"])
        self.assertFalse(data["disk_readonly"])
        self.assertEqual(data["orientation"], 1)
        self.assertLess(data["resolution_width"], data["resolution_height"])
        self.assertLessEqual(data["PerformancePreset"]["Cpu"], 2)
        self.assertLessEqual(data["PerformancePreset"]["MemoryOfMB"], 2048)
        self.assertGreaterEqual(data["PerformancePreset"]["MemoryOfMB"], 1024)

    def test_tablet_sized_resolution_forced_to_phone(self) -> None:
        data = apply_farm_guest_rails({"resolution_width": 1600, "resolution_height": 2560})
        self.assertEqual(data["resolution_width"], 900)
        self.assertEqual(data["resolution_height"], 1600)

    def test_env_cpu_ram_clamped(self) -> None:
        old_c = os.environ.get("PHARMFLOW_MUMU_CPU_CORES")
        old_r = os.environ.get("PHARMFLOW_MUMU_RAM_MB")
        try:
            os.environ["PHARMFLOW_MUMU_CPU_CORES"] = "99"
            os.environ["PHARMFLOW_MUMU_RAM_MB"] = "99"
            data = apply_farm_guest_rails({})
            self.assertEqual(data["PerformancePreset"]["Cpu"], 2)
            self.assertEqual(data["PerformancePreset"]["MemoryOfMB"], 1024)
        finally:
            if old_c is None:
                os.environ.pop("PHARMFLOW_MUMU_CPU_CORES", None)
            else:
                os.environ["PHARMFLOW_MUMU_CPU_CORES"] = old_c
            if old_r is None:
                os.environ.pop("PHARMFLOW_MUMU_RAM_MB", None)
            else:
                os.environ["PHARMFLOW_MUMU_RAM_MB"] = old_r

    def test_file_write(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "setting.json"
            path.write_text("{}", encoding="utf-8")
            self.assertTrue(apply_farm_guest_rails_file(path))
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertTrue(data["DeviceRoot"])
            self.assertEqual(data["phone_type"], "phone")

    def test_nx_mumu15_configs_and_nemu_get_lean_rails(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            vm = Path(tmp) / "MuMuPlayerGlobal-15.0-1"
            cfg = vm / "configs"
            cfg.mkdir(parents=True)
            (cfg / "vm_config.json").write_text(
                json.dumps({"vm": {"cpu": "8", "memory": "8.000000"}}),
                encoding="utf-8",
            )
            (cfg / "customer_config.json").write_text(
                json.dumps(
                    {"setting": {"performance": {"mode": {"custom": {"cpu": "8", "memory": "8"}}}}}
                ),
                encoding="utf-8",
            )
            (cfg / "shell_config.json").write_text(
                json.dumps({"renderer": {"fps_limit": "60", "audio_out_hardware_off": "0"}}),
                encoding="utf-8",
            )
            nemu = vm / "phone.nemu"
            nemu.write_text(
                '<Memory RAMSize="4096"/>\n<CPU count="8">\n'
                '<AudioAdapter driver="DirectSound" enabledIn="true" enabledOut="true"/>\n',
                encoding="utf-8",
            )
            notes = apply_nx_mumu_guest_rails(vm)
            self.assertTrue(any("nx_vm_config" in n for n in notes))
            vmj = json.loads((cfg / "vm_config.json").read_text(encoding="utf-8"))
            self.assertEqual(vmj["vm"]["cpu"], "2")
            self.assertEqual(vmj["vm"]["memory"], "1.000000")
            text = nemu.read_text(encoding="utf-8")
            self.assertIn('RAMSize="1024"', text)
            self.assertIn('CPU count="2"', text)
            self.assertIn('enabledIn="false"', text)
            shell = json.loads((cfg / "shell_config.json").read_text(encoding="utf-8"))
            self.assertEqual(shell["renderer"]["fps_limit"], "15")
            self.assertEqual(shell["renderer"]["audio_out_hardware_off"], "1")
