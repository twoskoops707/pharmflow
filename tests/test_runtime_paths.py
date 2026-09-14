"""Portable EXE/helper paths — no developer-PC hardcoding."""

from __future__ import annotations

import unittest
from pathlib import Path

from automation.runtime_paths import code_root, helper_python
from wizard.wizard_paths import MUMU_SEARCH_PATHS


class RuntimePathsTests(unittest.TestCase):
    def test_code_root_is_this_repo(self) -> None:
        root = code_root()
        self.assertTrue((root / "automation").is_dir())
        self.assertTrue((root / "scripts" / "keep_farm_alive.py").is_file())
        self.assertTrue((root / "wizard" / "farm_control.py").is_file())

    def test_helper_python_is_not_pharmflow_exe(self) -> None:
        path = helper_python()
        self.assertIsNotNone(path)
        assert path is not None
        self.assertTrue(Path(path).is_file())
        self.assertNotIn("pharmflow.exe", path.lower())

    def test_mumu_search_prefers_x64_before_arm(self) -> None:
        names = [str(p) for p in MUMU_SEARCH_PATHS if p and str(p) != "."]
        arm_idx = next(i for i, n in enumerate(names) if "MuMuPlayerARM" in n)
        x64_idx = next(i for i, n in enumerate(names) if n.endswith("MuMuPlayer"))
        self.assertLess(x64_idx, arm_idx)


class NoDevMachineHardcodeTests(unittest.TestCase):
    _BANNED = (
        r"C:\Users\jsmil\PharmFlow",
        r"C:\Users\jsmil\OneDrive\Desktop\PHARMFLOW",
        r"C:\Users\jsmil\AppData\Local\Python\pythoncore-3.14-64\pythonw.exe",
    )

    def test_bundled_helpers_have_no_user_home_roots(self) -> None:
        root = code_root()
        files = [
            root / "scripts" / "keep_farm_alive.py",
            root / "scripts" / "watch_bottom_ads.py",
            root / "scripts" / "ntfy_farm_responder.py",
            root / "automation" / "farm_money_monitor.py",
            root / "automation" / "mantis_fetch.py",
            root / "automation" / "mumu_fingerprint.py",
            root / "scripts" / "farm_remediate_loop.py",
        ]
        for path in files:
            text = path.read_text(encoding="utf-8")
            for banned in self._BANNED:
                self.assertNotIn(banned, text, msg=f"{path.name} still hardcodes {banned}")


if __name__ == "__main__":
    unittest.main()
