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


class TestRemapGroupsPhonesToLive(unittest.TestCase):
    def test_remaps_stale_serials_by_slot_order(self) -> None:
        """E06: 8 saved dead IPs + 8 live ADB → adopt all live, keep playlists."""
        groups = [
            {
                "name": "Group 1",
                "phones": {
                    "10.0.2.103:5555": {"sequence_playlist": ["a.json"]},
                    "10.0.2.174:5555": {"sequence_playlist": ["b.json"]},
                    "10.0.2.189:5555": {"sequence_playlist": ["c.json"]},
                },
            }
        ]
        live = ["10.0.2.189:5555", "10.0.2.62:5555", "10.0.2.106:5555"]
        n = wp.remap_groups_phones_to_live(groups, live)
        self.assertEqual(n, 1)
        phones = groups[0]["phones"]
        self.assertEqual(
            set(phones),
            {"10.0.2.62:5555", "10.0.2.106:5555", "10.0.2.189:5555"},
        )
        # Slot order: 62, 106, 189 ← playlists from 103, 174, 189
        self.assertEqual(phones["10.0.2.62:5555"]["sequence_playlist"], ["a.json"])
        self.assertEqual(phones["10.0.2.106:5555"]["sequence_playlist"], ["b.json"])
        self.assertEqual(phones["10.0.2.189:5555"]["sequence_playlist"], ["c.json"])

    def test_noop_when_all_serials_already_live(self) -> None:
        groups = [
            {
                "name": "Group 1",
                "phones": {
                    "10.0.2.62:5555": {"hits_per_day": 1},
                    "10.0.2.106:5555": {"hits_per_day": 2},
                },
            }
        ]
        live = ["10.0.2.106:5555", "10.0.2.62:5555"]
        before = dict(groups[0]["phones"])
        n = wp.remap_groups_phones_to_live(groups, live)
        self.assertEqual(n, 0)
        self.assertEqual(groups[0]["phones"], before)

    def test_empty_adb_does_not_wipe_groups(self) -> None:
        groups = [{"name": "G", "phones": {"10.0.2.1:5555": {"steps": []}}}]
        n = wp.remap_groups_phones_to_live(groups, [])
        self.assertEqual(n, 0)
        self.assertEqual(list(groups[0]["phones"]), ["10.0.2.1:5555"])

    def test_does_not_invent_beyond_live_or_configured(self) -> None:
        groups = [
            {
                "name": "G",
                "phones": {
                    "10.0.2.10:5555": {"id": "slot0"},
                    "10.0.2.20:5555": {"id": "slot1"},
                },
            }
        ]
        live = ["10.0.2.1:5555", "10.0.2.2:5555", "10.0.2.3:5555"]
        wp.remap_groups_phones_to_live(groups, live)
        self.assertEqual(len(groups[0]["phones"]), 2)
        self.assertEqual(set(groups[0]["phones"]), {"10.0.2.1:5555", "10.0.2.2:5555"})

    def test_fewer_live_than_configured_keeps_excess_entry_not_dropped(self) -> None:
        """Regression: live count dipping below configured count (routine boot
        churn/offline phones per OPS_NOTES) must never delete a phone's playlist —
        the excess entry stays under its original key instead of being dropped."""
        groups = [
            {
                "name": "G",
                "phones": {
                    "10.0.2.10:5555": {"sequence_playlist": ["a.json"]},
                    "10.0.2.20:5555": {"sequence_playlist": ["b.json"]},
                    "10.0.2.30:5555": {"sequence_playlist": ["c.json"]},
                },
            }
        ]
        live = ["10.0.2.1:5555", "10.0.2.2:5555"]
        n = wp.remap_groups_phones_to_live(groups, live)
        self.assertEqual(n, 1)
        phones = groups[0]["phones"]
        # All 3 playlists must still exist somewhere — none silently dropped.
        self.assertEqual(len(phones), 3)
        all_playlists = {tuple(v.get("sequence_playlist", [])) for v in phones.values()}
        self.assertEqual(all_playlists, {("a.json",), ("b.json",), ("c.json",)})
        # The two live serials got the two lowest-slot configured entries.
        self.assertEqual(phones["10.0.2.1:5555"]["sequence_playlist"], ["a.json"])
        self.assertEqual(phones["10.0.2.2:5555"]["sequence_playlist"], ["b.json"])
        # The excess entry survives under its original (now-stale) key.
        self.assertEqual(phones["10.0.2.30:5555"]["sequence_playlist"], ["c.json"])

    def test_two_stale_groups_never_share_a_live_phone(self) -> None:
        """Regression: two independently-stale groups must not both claim the
        same live serial. Each live phone belongs to exactly one group."""
        groups = [
            {
                "name": "A",
                "phones": {
                    "10.0.2.10:5555": {"sequence_playlist": ["a1.json"]},
                    "10.0.2.11:5555": {"sequence_playlist": ["a2.json"]},
                },
            },
            {
                "name": "B",
                "phones": {
                    "10.0.2.20:5555": {"sequence_playlist": ["b1.json"]},
                    "10.0.2.21:5555": {"sequence_playlist": ["b2.json"]},
                },
            },
        ]
        live = ["10.0.2.1:5555", "10.0.2.2:5555", "10.0.2.3:5555", "10.0.2.4:5555"]
        n = wp.remap_groups_phones_to_live(groups, live)
        self.assertEqual(n, 2)
        a_keys = set(groups[0]["phones"])
        b_keys = set(groups[1]["phones"])
        # No live serial assigned to both groups.
        self.assertEqual(a_keys & b_keys & set(live), set())
        # All 4 live serials were actually handed out (4 configured entries,
        # 4 live phones -- none left unclaimed).
        self.assertEqual(a_keys | b_keys, set(live))

    def test_group_already_fully_live_reserves_its_serials(self) -> None:
        """A group whose keys are all already live keeps them untouched, and
        those serials must not be handed to a second, stale group."""
        groups = [
            {
                "name": "Already live",
                "phones": {"10.0.2.1:5555": {"sequence_playlist": ["keep.json"]}},
            },
            {
                "name": "Stale",
                "phones": {"10.0.2.99:5555": {"sequence_playlist": ["stale.json"]}},
            },
        ]
        live = ["10.0.2.1:5555", "10.0.2.2:5555"]
        n = wp.remap_groups_phones_to_live(groups, live)
        self.assertEqual(n, 1)
        # Untouched group keeps its serial and playlist exactly.
        self.assertEqual(
            groups[0]["phones"], {"10.0.2.1:5555": {"sequence_playlist": ["keep.json"]}}
        )
        # Stale group gets the *other* live serial, not the reserved one.
        self.assertEqual(
            groups[1]["phones"], {"10.0.2.2:5555": {"sequence_playlist": ["stale.json"]}}
        )


if __name__ == "__main__":
    unittest.main()