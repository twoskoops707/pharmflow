"""Unit tests for wizard/mumu_farm_ops.py (no adb/MuMu required)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import mumu_farm_ops as farm


class TestMumuFarmOps(unittest.TestCase):
    def test_profile_needs_phone_baseline_tablet(self) -> None:
        prof = {
            "resolution_type": "Tablet",
            "orientation": "Portrait",
            "framebuffer": (900, 1600),
            "dpi": 300,
        }
        self.assertTrue(farm.profile_needs_phone_baseline(prof))

    def test_profile_needs_phone_baseline_ok(self) -> None:
        prof = {
            "resolution_type": "Phone",
            "orientation": "Portrait",
            "framebuffer": (900, 1600),
            "dpi": 300,
        }
        self.assertFalse(farm.profile_needs_phone_baseline(prof))

    def test_phone_playlist_entry_shape(self) -> None:
        entry = farm.phone_playlist_entry(0)
        self.assertEqual(entry["sequence_base_w"], 900)
        self.assertEqual(entry["sequence_base_h"], 1600)
        self.assertIn(farm.CORE_NO_AD, entry["sequence_playlist"])
        self.assertTrue(entry["sequence_playlist_secondary"])
        self.assertEqual(entry["sequence_playlist_shuffle"], "combined")

    def test_write_groups_config_file(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td) / "groups_config.json"
            farm.write_groups_config_file(["10.0.2.15:5555"], out)
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertIn("groups", data)
            self.assertIn("10.0.2.15:5555", data["groups"][0]["phones"])


if __name__ == "__main__":
    unittest.main()
