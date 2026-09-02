"""Tests for core phone management — ADB parsing and serial resolution."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from automation.adb_wrapper import AdbDevice, AdbResult, AdbWrapper
from wizard.mumu_farm_ops import ADB_PORT_BASE, ADB_PORT_STRIDE, MuMuFarmOps


class AdbDevicesParseTests(unittest.TestCase):
    def test_devices_detailed_parses_long_format(self) -> None:
        wrapper = AdbWrapper(adb_path="adb")
        sample = (
            "List of devices attached\n"
            "127.0.0.1:16384       device product:Alice model:MuMu device:MuMu transport_id:1\n"
            "emulator-5554         offline product:sdk model:sdk device:emu transport_id:2\n"
        )
        with patch.object(wrapper, "run", return_value=AdbResult(0, sample, "")):
            devices = wrapper.devices_detailed()

        self.assertEqual(len(devices), 2)
        self.assertEqual(devices[0].serial, "127.0.0.1:16384")
        self.assertEqual(devices[0].state, "device")
        self.assertEqual(devices[0].product, "Alice")
        self.assertTrue(devices[0].online)
        self.assertFalse(devices[1].online)

    def test_for_phone_binds_serial(self) -> None:
        base = AdbWrapper(adb_path="/tmp/adb")
        phone = base.for_phone("127.0.0.1:16416")
        self.assertEqual(phone.default_serial, "127.0.0.1:16416")


class SerialResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.farm = MuMuFarmOps(mumu_root=Path("/fake/mumu"))

    def test_resolve_by_port(self) -> None:
        index = 1
        port = ADB_PORT_BASE + index * ADB_PORT_STRIDE
        live = [
            AdbDevice(serial=f"127.0.0.1:{port}", state="device", product="MuMu", model="Phone-02"),
        ]
        serial = self.farm._resolve_adb_serial("Phone-02", index, live)
        self.assertEqual(serial, f"127.0.0.1:{port}")

    def test_resolve_by_name_in_blob(self) -> None:
        live = [
            AdbDevice(
                serial="192.168.1.50:5555",
                state="device",
                product="Phone-03",
                model="MuMu",
                device="generic",
            ),
        ]
        serial = self.farm._resolve_adb_serial("Phone-03", 2, live)
        self.assertEqual(serial, "192.168.1.50:5555")

    def test_resolve_falls_back_to_expected_serial(self) -> None:
        with patch.object(self.farm.adb, "connect", return_value=AdbResult(1, "", "failed")):
            serial = self.farm._resolve_adb_serial("Phone-99", 0, [])
        self.assertEqual(serial, f"127.0.0.1:{ADB_PORT_BASE}")

    def test_arm_mpid_unique_claim(self) -> None:
        self.farm.manager = Path(r"C:\fake\nemux-shell-winui.Manager.exe")
        live = [
            AdbDevice(serial="10.0.2.10:5555", state="device"),
            AdbDevice(serial="10.0.2.20:5555", state="device"),
        ]
        mpid_map = {0: "10.0.2.10:5555", 1: "10.0.2.20:5555"}
        claimed: set[str] = set()
        s0 = self.farm._resolve_adb_serial("vm0.gmadoa", 0, live, claimed=claimed, mpid_map=mpid_map)
        claimed.add(s0)
        s1 = self.farm._resolve_adb_serial("vm1.gmadoa", 1, live, claimed=claimed, mpid_map=mpid_map)
        self.assertEqual(s0, "10.0.2.10:5555")
        self.assertEqual(s1, "10.0.2.20:5555")
        self.assertNotEqual(s0, s1)

    def test_get_phone_legacy_alias(self) -> None:
        from wizard.mumu_farm_ops import MuMuInstance

        self.farm.instances = {
            "vm0.gmadoa": MuMuInstance(
                name="vm0.gmadoa", index=0, vm_path=Path("/vms/vm0.gmadoa"), adb_serial="10.0.2.1:5555"
            ),
            "vm1.gmadoa": MuMuInstance(
                name="vm1.gmadoa", index=1, vm_path=Path("/vms/vm1.gmadoa"), adb_serial="10.0.2.2:5555"
            ),
        }
        with patch.object(self.farm, "list_instances", return_value=list(self.farm.instances.values())):
            self.assertEqual(self.farm.get_phone("Phone-2").name, "vm1.gmadoa")


class MuMuDiscoveryTests(unittest.TestCase):
  @patch("wizard.mumu_farm_ops.validate_mumu_root", return_value=True)
  @patch("wizard.mumu_farm_ops.load_config", return_value={"mumu_root": "C:\\MuMu"})
  def test_discover_returns_saved_root(self, _cfg: MagicMock, _validate: MagicMock) -> None:
        farm = MuMuFarmOps()
        paths = farm.discover_mumu_paths()
        self.assertTrue(any("MuMu" in str(p) for p in paths))


if __name__ == "__main__":
    unittest.main()
