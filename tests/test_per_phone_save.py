"""Teams per-phone sequence save persistence."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from automation.group_manager import GroupManager


class PerPhoneSaveTests(unittest.TestCase):
    def test_steps_persist_to_groups_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "groups.json"
            gm = GroupManager(data_path=path)
            gm.create_group("Group 1", ["Phone-1"])
            ent = gm.phone_entry("Group 1", "Phone-1")
            ent["steps"] = [{"action": "wait", "params": {"seconds": 2}}]
            ent["use_default_template"] = False
            ent["explicit_override"] = True
            gm.save()

            reloaded = GroupManager(data_path=path)
            saved = reloaded.phone_entry("Group 1", "Phone-1")
            self.assertEqual(len(saved.get("steps") or []), 1)
            self.assertEqual(saved["steps"][0]["action"], "wait")

            raw = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(len(raw["Group 1"]["phone_entries"]["Phone-1"]["steps"]), 1)


if __name__ == "__main__":
    unittest.main()
