"""Tests for wizard/phone_setup_entry.py"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import phone_setup_entry as entry  # noqa: E402


class PhoneSetupEntryTests(unittest.TestCase):
    def test_phone_setup_flag(self) -> None:
        self.assertTrue(entry.is_phone_setup_mode(["CPharm.exe", "--phone-setup"]))
        self.assertFalse(entry.is_phone_setup_mode(["CPharm.exe"]))

    def test_unified_cpharm_frozen(self) -> None:
        with mock.patch.object(sys, "frozen", True, create=True):
            with mock.patch.object(sys, "executable", "C:/CPharm/CPharm.exe"):
                self.assertTrue(entry.is_unified_cpharm(["CPharm.exe"]))
                self.assertTrue(entry.skip_launch_cpharm_after_setup())

    def test_legacy_mumu_setup_stem(self) -> None:
        with mock.patch.object(sys, "frozen", True, create=True):
            with mock.patch.object(sys, "executable", "C:/CPharm/CPharmMuMuSetup.exe"):
                self.assertTrue(entry.is_phone_setup_mode(["CPharmMuMuSetup.exe"]))
                self.assertFalse(entry.is_unified_cpharm(["CPharmMuMuSetup.exe"]))


if __name__ == "__main__":
    unittest.main()
