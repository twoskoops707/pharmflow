"""site_prefs: target URL load order + PharmFlow mirror on save."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wizard import site_prefs as sp  # noqa: E402


def _write_site(path: Path, url: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"target_site_url": url}, indent=2), encoding="utf-8")


class SitePrefsLoadSaveTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.base = Path(self._td.name)
        self.install = self.base / "checkout"
        self.pharm = self.base / "PharmFlow" / "automation" / "recordings" / "wizard_site.json"
        self.cpharm = self.base / "CPharm" / "automation" / "recordings" / "wizard_site.json"
        self._env_patch = patch.dict(os.environ, {}, clear=False)
        self._env_patch.start()
        os.environ.pop("PHARMFLOW_TARGET_SITE_URL", None)

    def tearDown(self) -> None:
        self._env_patch.stop()
        self._td.cleanup()

    def _patched(self):
        return (
            patch.object(sp, "pharmflow_default_install_root", return_value=self.install),
            patch.object(sp, "_INSTALL_SITE_FALLBACKS", (self.pharm, self.cpharm)),
        )

    def test_env_wins_over_saved_files(self) -> None:
        _write_site(self.install / "automation" / "recordings" / "wizard_site.json", "https://from-install.example/")
        _write_site(self.pharm, "https://from-pharm.example/")
        os.environ["PHARMFLOW_TARGET_SITE_URL"] = "https://from-env.example/"
        a, b = self._patched()
        with a, b:
            self.assertEqual(sp.load_target_site_url(), "https://from-env.example/")

    def test_install_root_prefs_before_fallbacks(self) -> None:
        _write_site(
            self.install / "automation" / "recordings" / "wizard_site.json",
            "https://getdabflow.app/",
        )
        _write_site(self.pharm, "https://other.example/")
        a, b = self._patched()
        with a, b:
            self.assertEqual(sp.load_target_site_url(), "https://getdabflow.app/")

    def test_falls_back_to_pharmflow_when_install_missing(self) -> None:
        _write_site(self.pharm, "https://getdabflow.app/")
        a, b = self._patched()
        with a, b:
            self.assertEqual(sp.load_target_site_url(), "https://getdabflow.app/")

    def test_falls_back_to_cpharm_when_pharmflow_missing(self) -> None:
        _write_site(self.cpharm, "https://getdabflow.app/")
        a, b = self._patched()
        with a, b:
            self.assertEqual(sp.load_target_site_url(), "https://getdabflow.app/")

    def test_pharmflow_preferred_over_cpharm(self) -> None:
        _write_site(self.pharm, "https://pharm.example/")
        _write_site(self.cpharm, "https://cpharm.example/")
        a, b = self._patched()
        with a, b:
            self.assertEqual(sp.load_target_site_url(), "https://pharm.example/")

    def test_save_writes_install_and_mirrors_pharmflow(self) -> None:
        a, b = self._patched()
        with a, b:
            out = sp.save_target_site_url("https://getdabflow.app/")
        self.assertEqual(out, "https://getdabflow.app/")
        install_file = self.install / "automation" / "recordings" / "wizard_site.json"
        self.assertTrue(install_file.is_file())
        self.assertEqual(
            json.loads(install_file.read_text(encoding="utf-8"))["target_site_url"],
            "https://getdabflow.app/",
        )
        self.assertTrue(self.pharm.is_file())
        self.assertEqual(
            json.loads(self.pharm.read_text(encoding="utf-8"))["target_site_url"],
            "https://getdabflow.app/",
        )
        # Mirror is PharmFlow only — do not stomp legacy CPharm on save.
        self.assertFalse(self.cpharm.is_file())

    def test_save_skips_mirror_when_primary_is_pharmflow(self) -> None:
        # Install root == PharmFlow tree → one write, no double-write path.
        pharm_root = self.base / "PharmFlow"
        pharm_file = pharm_root / "automation" / "recordings" / "wizard_site.json"
        with patch.object(sp, "pharmflow_default_install_root", return_value=pharm_root), patch.object(
            sp, "_INSTALL_SITE_FALLBACKS", (pharm_file, self.cpharm)
        ):
            sp.save_target_site_url("https://getdabflow.app/")
        self.assertTrue(pharm_file.is_file())
        self.assertFalse(self.cpharm.is_file())

    def test_empty_when_nothing_saved(self) -> None:
        a, b = self._patched()
        with a, b:
            self.assertEqual(sp.load_target_site_url(), "")

if __name__ == "__main__":
    unittest.main()
