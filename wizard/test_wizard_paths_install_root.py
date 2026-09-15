"""Tests for PyInstaller vs dev PharmFlow tree resolution (wizard_paths)."""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from unittest.mock import patch

import wizard_paths as wp


@contextmanager
def _temp_home_dir():
    with tempfile.TemporaryDirectory() as td:
        yield Path(td)


class TestWizardPathsInstallRoot(unittest.TestCase):
    def test_repo_root_has_dashboard_in_dev(self) -> None:
        root = wp.pharmflow_install_root()
        self.assertTrue(
            (root / "automation" / "dashboard.py").is_file(),
            msg=f"expected automation/dashboard.py under {root}",
        )

    def test_frozen_prefers_userprofile_pharmflow(self) -> None:
        with _temp_home_dir() as fake_home:
            dashboard = fake_home / "PharmFlow" / "automation" / "dashboard.py"
            dashboard.parent.mkdir(parents=True, exist_ok=True)
            dashboard.write_text("# stub", encoding="utf-8")

            with patch.object(sys, "frozen", True, create=True):
                with patch.object(sys, "executable", str(fake_home / "Downloads" / "PharmFlow.exe")):
                    with patch.object(Path, "home", return_value=fake_home):
                        with patch.dict(os.environ, {}, clear=True):
                            root = wp.pharmflow_install_root()
            self.assertEqual(root.resolve(), (fake_home / "PharmFlow").resolve())

    def test_frozen_skips_meipass_even_with_dashboard(self) -> None:
        """Bundle extract may carry automation/; it must not win over a real user tree."""
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            fake_home = base / "h"
            fake_home.mkdir()
            meipass = base / "meipass"
            (meipass / "automation").mkdir(parents=True)
            (meipass / "automation" / "dashboard.py").write_text("# m", encoding="utf-8")
            user_pharmflow = fake_home / "PharmFlow"
            (user_pharmflow / "automation").mkdir(parents=True)
            (user_pharmflow / "automation" / "dashboard.py").write_text("# u", encoding="utf-8")

            with patch.object(sys, "frozen", True, create=True):
                with patch.object(sys, "executable", str(fake_home / "Downloads" / "PharmFlow.exe")):
                    with patch.object(sys, "_MEIPASS", str(meipass), create=True):
                        with patch.object(Path, "home", return_value=fake_home):
                            with patch.dict(os.environ, {}, clear=True):
                                root = wp.pharmflow_install_root()
            self.assertEqual(root.resolve(), user_pharmflow.resolve())

    def test_first_existing_subdir_prefers_first_hit(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            a = base / "a"
            b = base / "b"
            seq_a = a / "automation" / "recordings" / "sequences"
            seq_b = b / "automation" / "recordings" / "sequences"
            seq_a.mkdir(parents=True)
            seq_b.mkdir(parents=True)
            (seq_a / "x.json").write_text("[]", encoding="utf-8")
            hit = wp.first_existing_subdir(
                [a, b],
                "automation",
                "recordings",
                "sequences",
            )
            self.assertEqual(hit, seq_a)

    def test_frozen_exe_without_local_tree_falls_back_to_downloads(self) -> None:
        """Exe beside no checkout: no dashboard under exe_dir, MEIPASS skipped, no %USERPROFILE% tree."""
        with _temp_home_dir() as fake_home:
            with patch.object(sys, "frozen", True, create=True):
                with patch.object(sys, "executable", str(fake_home / "Downloads" / "PharmFlow.exe")):
                    with patch.object(Path, "home", return_value=fake_home):
                        with patch.dict(os.environ, {}, clear=True):
                            with patch.object(sys, "_MEIPASS", None, create=True):
                                root = wp.pharmflow_install_root()
            self.assertEqual(root.resolve(), (fake_home / "Downloads").resolve())

    def test_groups_config_finds_legacy_cpharm_when_pharmflow_missing(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            pharm_root = base / "PharmFlow"
            cpharm_file = base / "CPharm" / "automation" / "recordings" / "groups_config.json"
            pharm_file = pharm_root / "automation" / "recordings" / "groups_config.json"
            cpharm_file.parent.mkdir(parents=True)
            cpharm_file.write_text('{"groups":[{"name":"G","phones":{"a":{}}}]}\n', encoding="utf-8")
            with patch.object(wp, "app_data_root", return_value=pharm_root), patch.object(
                wp,
                "_INSTALL_GROUPS_FILES",
                (pharm_file, cpharm_file),
            ), patch.object(wp, "_groups_search_roots", return_value=[base / "CPharm"]), patch.dict(
                os.environ, {"PHARMFLOW_GROUPS_CONFIG": ""}, clear=False
            ):
                os.environ.pop("PHARMFLOW_GROUPS_CONFIG", None)
                found = wp.groups_config_path()
            self.assertEqual(found.resolve(), cpharm_file.resolve())

    def test_persist_groups_mirrors_install_dual_roots(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            pharm_file = base / "PharmFlow" / "automation" / "recordings" / "groups_config.json"
            cpharm_file = base / "CPharm" / "automation" / "recordings" / "groups_config.json"
            payload = '{"groups":[{"name":"G","phones":{"a":{}}}]}\n'
            with patch.object(wp, "_INSTALL_GROUPS_FILES", (pharm_file, cpharm_file)), patch.dict(
                os.environ, {}, clear=False
            ):
                os.environ.pop("PHARMFLOW_GROUPS_CONFIG", None)
                written = wp.persist_groups_config_text(payload, primary=pharm_file)
            self.assertEqual(written.resolve(), pharm_file.resolve())
            self.assertEqual(pharm_file.read_text(encoding="utf-8"), payload)
            self.assertEqual(cpharm_file.read_text(encoding="utf-8"), payload)

    def test_persist_groups_skips_mirror_for_non_install_primary(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            base = Path(td)
            repo_file = base / "repo" / "groups_config.json"
            cpharm_file = base / "CPharm" / "automation" / "recordings" / "groups_config.json"
            pharm_file = base / "PharmFlow" / "automation" / "recordings" / "groups_config.json"
            payload = '{"groups":[]}\n'
            with patch.object(wp, "_INSTALL_GROUPS_FILES", (pharm_file, cpharm_file)):
                wp.persist_groups_config_text(payload, primary=repo_file)
            self.assertTrue(repo_file.is_file())
            self.assertFalse(cpharm_file.is_file())
            self.assertFalse(pharm_file.is_file())


if __name__ == "__main__":
    unittest.main()