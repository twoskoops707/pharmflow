"""Tests for manual path assignment."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from wizard.path_utils import (
    apply_mumu_path,
    normalize_adb_path,
    normalize_mumu_path,
    normalize_tor_path,
)
from wizard.path_store import PROGRAM_MUMU, load_saved_paths, remember_path, save_saved_paths


class PathStoreTests(unittest.TestCase):
    def test_remember_path_keeps_history(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path_file = Path(tmp) / "saved_paths.json"
            with patch("wizard.path_store.saved_paths_file", return_value=path_file):
                remember_path(PROGRAM_MUMU, r"C:\MuMu1")
                remember_path(PROGRAM_MUMU, r"C:\MuMu2")
                data = load_saved_paths()
            self.assertEqual(data[PROGRAM_MUMU], [r"C:\MuMu1", r"C:\MuMu2"])

    def test_save_and_load_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path_file = Path(tmp) / "saved_paths.json"
            with patch("wizard.path_store.saved_paths_file", return_value=path_file):
                save_saved_paths({PROGRAM_MUMU: ["C:\\a", "C:\\b"]})
                loaded = load_saved_paths()
            self.assertEqual(loaded[PROGRAM_MUMU], ["C:\\a", "C:\\b"])


class PathNormalizeTests(unittest.TestCase):
    def test_normalize_mumu_manager_exe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "MuMu"
            shell = root / "shell"
            shell.mkdir(parents=True)
            mgr = shell / "MuMuManager.exe"
            mgr.write_text("", encoding="utf-8")
            (root / "vms").mkdir()
            got = normalize_mumu_path(mgr)
            self.assertEqual(got, root)

    def test_normalize_tor_exe(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tor = Path(tmp) / "tor.exe"
            tor.write_text("", encoding="utf-8")
            self.assertEqual(normalize_tor_path(tor), tor)

    def test_normalize_adb_folder(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            adb = Path(tmp) / "adb.exe"
            adb.write_text("", encoding="utf-8")
            self.assertEqual(normalize_adb_path(Path(tmp)), adb)


class PathApplyTests(unittest.TestCase):
    def test_apply_mumu_saves_config(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "MuMu"
            shell = root / "shell"
            shell.mkdir(parents=True)
            (shell / "MuMuManager.exe").write_text("", encoding="utf-8")
            (root / "vms").mkdir()
            cfg = Path(tmp) / "pharmflow_config.json"
            with (
                patch("wizard.path_utils.save_config") as mock_save,
                patch("wizard.path_utils.remember_path"),
                patch("wizard.path_utils.mumu_manager_exe", return_value=shell / "MuMuManager.exe"),
            ):
                result = apply_mumu_path(root)
                mock_save.assert_called_once()
            self.assertTrue(result.found)
            self.assertEqual(result.path, str(root))


if __name__ == "__main__":
    unittest.main()
