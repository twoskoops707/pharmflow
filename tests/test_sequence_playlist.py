"""Tests for automation/sequence_playlist.py."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from automation.sequence_playlist import load_steps_from_filename, resolve_steps


class SequencePlaylistTests(unittest.TestCase):
    def test_resolve_empty_falls_back_to_inline(self) -> None:
        steps, note = resolve_steps({}, 0, "Phone-1", inline_steps=[{"action": "wait", "params": {"seconds": 1}}])
        self.assertIsNone(note)
        self.assertEqual(len(steps), 1)

    def test_ordered_playlist(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.json").write_text(
                json.dumps({"steps": [{"action": "open_url", "params": {"url": "https://a.test"}}]}),
                encoding="utf-8",
            )
            (root / "b.json").write_text(
                json.dumps({"steps": [{"action": "launch_app", "params": {"package": "com.x"}}]}),
                encoding="utf-8",
            )
            ent = {
                "sequence_playlist": ["a.json", "b.json"],
                "sequence_playlist_mode": "ordered",
            }
            with patch("automation.sequence_playlist.sequences_dir", return_value=root):
                steps0, note0 = resolve_steps(ent, 0, "Phone-1", directory=root)
                steps1, note1 = resolve_steps(ent, 1, "Phone-1", directory=root)
            self.assertEqual(note0, "a.json")
            self.assertEqual(steps0[0]["action"], "open_url")
            self.assertEqual(note1, "b.json")
            self.assertEqual(steps1[0]["action"], "launch_app")

    def test_series_concat(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "a.json").write_text(
                json.dumps({"steps": [{"type": "wait", "seconds": 1}]}),
                encoding="utf-8",
            )
            (root / "b.json").write_text(
                json.dumps({"steps": [{"action": "back"}]}),
                encoding="utf-8",
            )
            ent = {
                "sequence_playlist": ["a.json", "b.json"],
                "sequence_playlist_mode": "series",
            }
            steps, note = resolve_steps(ent, 0, "s1", directory=root)
            self.assertTrue(note and note.startswith("series:"))
            self.assertEqual(len(steps), 2)
            self.assertEqual(steps[0]["action"], "wait")

    def test_load_missing_returns_none(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(load_steps_from_filename("nope.json", Path(tmp)))

    def test_path3_hits_budget_skips_ads_when_zero(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "browse.json").write_text(
                json.dumps({"steps": [{"type": "wait", "seconds": 1}]}),
                encoding="utf-8",
            )
            (root / "ad.json").write_text(
                json.dumps({"steps": [{"type": "wait", "seconds": 2}]}),
                encoding="utf-8",
            )
            ent = {
                "sequence_playlist": ["browse.json"],
                "sequence_playlist_secondary": ["ad.json"],
                "sequence_playlist_mode": "random",
                "sequence_playlist_shuffle": "combined",
                "hits_per_day": 40,
                "path3_hits_per_day": 0,
            }
            notes = []
            with patch("automation.sequence_playlist.sequences_dir", return_value=root):
                for i in range(20):
                    _steps, note = resolve_steps(ent, i, "10.0.2.1:5555", directory=root)
                    notes.append(note or "")
            self.assertTrue(all("ad.json" not in n for n in notes))
            self.assertTrue(any("browse.json" in n for n in notes))

    def test_path3_hits_budget_can_pick_ads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "browse.json").write_text(
                json.dumps({"steps": [{"type": "wait", "seconds": 1}]}),
                encoding="utf-8",
            )
            (root / "ad.json").write_text(
                json.dumps({"steps": [{"type": "wait", "seconds": 2}]}),
                encoding="utf-8",
            )
            ent = {
                "sequence_playlist": ["browse.json"],
                "sequence_playlist_secondary": ["ad.json"],
                "sequence_playlist_mode": "random",
                "sequence_playlist_shuffle": "combined",
                "hits_per_day": 2,
                "path3_hits_per_day": 2,
            }
            with patch("automation.sequence_playlist.sequences_dir", return_value=root):
                _steps, note = resolve_steps(ent, 0, "10.0.2.1:5555", directory=root)
            self.assertIn("ad.json", note or "")

    def test_path2_budget_synthesizes_halfway_timer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "browse.json").write_text(
                json.dumps(
                    {
                        "steps": [
                            {"type": "open_url", "url": "https://example.test"},
                            {
                                "type": "wait",
                                "seconds": 90.5,
                                "checkpoint": "timer_complete",
                            },
                            {"type": "tap", "x": 1, "y": 2},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            (root / "ad.json").write_text(
                json.dumps({"steps": [{"type": "wait", "seconds": 2}]}),
                encoding="utf-8",
            )
            ent = {
                "sequence_playlist": ["browse.json"],
                "sequence_playlist_secondary": ["ad.json"],
                "sequence_playlist_mode": "random",
                "sequence_playlist_shuffle": "combined",
                "hits_per_day": 10,
                "path2_hits_per_day": 10,
                "path3_hits_per_day": 0,
            }
            with patch("automation.sequence_playlist.sequences_dir", return_value=root):
                steps, note = resolve_steps(ent, 0, "10.0.2.1:5555", directory=root)
            self.assertIn("#path2", note or "")
            self.assertTrue(steps)
            self.assertEqual(steps[-1].get("checkpoint"), "timer_halfway")
            self.assertGreaterEqual(float(steps[-1].get("seconds") or 0), 45.0)
            self.assertLessEqual(float(steps[-1].get("seconds") or 0), 60.0)
            self.assertEqual(len(steps), 2)


if __name__ == "__main__":
    unittest.main()
