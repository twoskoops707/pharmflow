"""Operator kill-switch flag: farm must not auto-respawn while set."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from automation import farm_pause


class KillSwitchTests(unittest.TestCase):
    def test_engage_and_clear(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp)
            kill = log / "FARM_KILL.flag"
            with (
                patch.object(farm_pause, "LOG", log),
                patch.object(farm_pause, "KILL_FLAG", kill),
                patch.object(farm_pause, "PAUSE_FILE", log / "FARM_PAUSED_UNTIL.json"),
            ):
                self.assertFalse(farm_pause.is_killed())
                self.assertFalse(farm_pause.farm_halted())
                farm_pause.engage_kill_switch(note="test")
                self.assertTrue(kill.is_file())
                self.assertTrue(farm_pause.is_killed())
                self.assertTrue(farm_pause.farm_halted())
                farm_pause.clear_kill_switch()
                self.assertFalse(farm_pause.is_killed())
                self.assertFalse(farm_pause.farm_halted())


if __name__ == "__main__":
    unittest.main()
