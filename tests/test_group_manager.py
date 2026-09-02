"""Tests for automation/group_manager.py."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from automation.group_manager import GroupManager, PhoneGroup


class GroupManagerTests(unittest.TestCase):
    def test_phone_group_dataclass(self) -> None:
        group = PhoneGroup(name="default", phones=["Phone-1"])
        self.assertEqual(group.name, "default")
        self.assertEqual(group.phones, ["Phone-1"])

    def test_load_and_list_groups(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "groups.json"
            path.write_text(
                json.dumps(
                    {
                        "alpha": {
                            "phones": ["Phone-1", "Phone-2"],
                            "sequence": "example_browse",
                            "schedule_cron": "0 */6 * * *",
                            "tor_enabled": True,
                            "metadata": {},
                        }
                    }
                ),
                encoding="utf-8",
            )
            mgr = GroupManager(data_path=path)
            groups = mgr.list_groups()
            self.assertEqual(len(groups), 1)
            self.assertEqual(groups[0]["name"], "alpha")
            self.assertEqual(groups[0]["phones"], ["Phone-1", "Phone-2"])

    def test_create_group_persists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "groups.json"
            mgr = GroupManager(data_path=path)
            mgr.create_group("beta", ["Phone-3"])
            reloaded = GroupManager(data_path=path)
            self.assertIn("beta", reloaded.groups)
            self.assertEqual(reloaded.groups["beta"].phones, ["Phone-3"])

    def test_create_group_with_repeat_and_playlist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "groups.json"
            mgr = GroupManager(data_path=path)
            mgr.create_group("gamma", ["Phone-1"])
            mgr.update_group("gamma", repeat=3, repeat_forever=False)
            ent = mgr.phone_entry("gamma", "Phone-1")
            ent["sequence_playlist"] = ["a.json"]
            mgr.save()
            reloaded = GroupManager(data_path=path)
            self.assertEqual(reloaded.groups["gamma"].repeat, 3)
            self.assertEqual(
                reloaded.groups["gamma"].phone_entries["Phone-1"]["sequence_playlist"],
                ["a.json"],
            )


if __name__ == "__main__":
    unittest.main()
