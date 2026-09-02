"""Tests for wizard/preflight_core.py"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import preflight_core as pf  # noqa: E402


class PreflightCoreTests(unittest.TestCase):
    def test_build_checklist_has_core_steps(self) -> None:
        items = pf.build_checklist(Path("/nonexistent/cpharm"))
        ids = [x["id"] for x in items]
        self.assertIn("folder", ids)
        self.assertIn("mumu", ids)
        self.assertIn("mumu_profile", ids)
        self.assertIn("adb", ids)
        self.assertIn("phones", ids)
        self.assertIn("browser", ids)
        self.assertGreaterEqual(len(ids), 8)

    def test_folder_passes_in_dev_mode(self) -> None:
        items = pf.build_checklist(Path("/nonexistent/cpharm"))
        folder = next(x for x in items if x["id"] == "folder")
        self.assertEqual(folder["status"], "pass")

    def test_run_check_action_unknown(self) -> None:
        out = pf.run_check_action("not_a_real_action")
        self.assertFalse(out["ok"])


if __name__ == "__main__":
    unittest.main()
