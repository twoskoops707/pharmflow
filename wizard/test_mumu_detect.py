"""Tests for wizard/mumu_detect.py"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))

import mumu_detect as md  # noqa: E402


class MumuDetectModuleTests(unittest.TestCase):
    def test_netease_subfolder_detection(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td) / "Program Files"
            exe = base / "Netease" / "MuMuPlayerARM" / "nemux-shell-winui.Manager.exe"
            exe.parent.mkdir(parents=True)
            exe.write_text("", encoding="utf-8")
            with mock.patch.object(md, "IS_WIN", True):
                with mock.patch.object(md, "_base_dirs", return_value=[base]):
                    with mock.patch.object(md, "_where_hits", return_value=[]):
                        with mock.patch.object(md, "_registry_install_dirs", return_value=[]):
                            hit = md.find_mumu_install()
            self.assertIsNotNone(hit)
            self.assertEqual(hit.name, "nemux-shell-winui.Manager.exe")


if __name__ == "__main__":
    unittest.main()
