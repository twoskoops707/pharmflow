#!/usr/bin/env python3
"""Tests for resolution/ad-aware sequence playlist resolution."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

_AUTOMATION_DIR = Path(__file__).resolve().parent
if str(_AUTOMATION_DIR) not in sys.path:
    sys.path.insert(0, str(_AUTOMATION_DIR))

import sequence_playlist as sp  # noqa: E402
from sequences_paths import default_sequences_dir, resolve_sequences_dir  # noqa: E402


class SequencePlaylistPathTests(unittest.TestCase):
    def test_default_sequences_dir_under_user_pharmflow(self) -> None:
        self.assertEqual(default_sequences_dir(), Path.home() / "PharmFlow" / "sequences")

    def test_resolve_sequences_dir_honors_env(self) -> None:
        import os

        with tempfile.TemporaryDirectory() as tmp:
            old = os.environ.get("PHARMFLOW_SEQUENCES_DIR")
            try:
                os.environ["PHARMFLOW_SEQUENCES_DIR"] = tmp
                self.assertEqual(resolve_sequences_dir(), Path(tmp).resolve())
            finally:
                if old is None:
                    os.environ.pop("PHARMFLOW_SEQUENCES_DIR", None)
                else:
                    os.environ["PHARMFLOW_SEQUENCES_DIR"] = old

    def test_normalize_playlist_ref_keeps_subpath(self) -> None:
        self.assertEqual(
            sp.normalize_playlist_ref("900x1600/ad/foo.json"),
            "900x1600/ad/foo.json",
        )

    def test_playlist_cycle_length_ordered_and_series(self) -> None:
        ent_ordered = {
            "sequence_playlist": ["a.json", "b.json", "c.json"],
            "sequence_playlist_secondary": ["x.json"],
            "sequence_playlist_mode": "ordered",
        }
        self.assertEqual(sp.playlist_cycle_length(ent_ordered), 3)
        self.assertFalse(sp.is_playlist_cycle_end(ent_ordered, 0))
        self.assertFalse(sp.is_playlist_cycle_end(ent_ordered, 1))
        self.assertTrue(sp.is_playlist_cycle_end(ent_ordered, 2))

        ent_series = dict(ent_ordered)
        ent_series["sequence_playlist_mode"] = "series"
        self.assertEqual(sp.playlist_cycle_length(ent_series), 1)
        self.assertTrue(sp.is_playlist_cycle_end(ent_series, 0))

    def test_playlist_cycle_length_combined_shuffle(self) -> None:
        ent = {
            "sequence_playlist": ["a.json", "b.json"],
            "sequence_playlist_secondary": ["c.json"],
            "sequence_playlist_mode": "ordered",
            "sequence_playlist_shuffle": "combined",
        }
        self.assertEqual(sp.playlist_cycle_length(ent), 3)

    def test_resolve_step_chunks_series_splits_files(self) -> None:
        ent = {
            "sequence_playlist": ["900x1600/no-ad/a.json", "900x1600/no-ad/b.json"],
            "sequence_playlist_mode": "series",
            "sequence_profile_key": "900x1600",
        }
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nested = root / "900x1600" / "no-ad"
            nested.mkdir(parents=True)
            (nested / "a.json").write_text(json.dumps([{"type": "wait", "seconds": 1.0}]), encoding="utf-8")
            (nested / "b.json").write_text(json.dumps([{"type": "wait", "seconds": 2.0}]), encoding="utf-8")
            old = sp.SEQUENCES_DIR
            try:
                sp.SEQUENCES_DIR = root
                chunks = sp.resolve_step_chunks(ent, 0, "serial-1", [])
                self.assertEqual(len(chunks), 2)
                self.assertEqual(chunks[0][1], "900x1600/no-ad/a.json")
                self.assertEqual(chunks[1][0][-1]["type"], "full_reset")
            finally:
                sp.SEQUENCES_DIR = old

    def test_strip_trailing_ip_id_tail(self) -> None:
        steps = [
            {"type": "tap", "x": 1, "y": 2},
            {"type": "close_app"},
            {"type": "rotate_identity"},
            {"type": "wait", "seconds": 2.0},
            {"type": "full_reset"},
        ]
        stripped = sp._strip_trailing_ip_id_tail(steps)
        self.assertEqual(stripped, [{"type": "tap", "x": 1, "y": 2}])

    def test_ordered_resolve_omits_per_file_identity_tail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nested = root / "900x1600" / "no-ad"
            nested.mkdir(parents=True)
            payload = [
                {"type": "wait", "seconds": 1.0},
                {"type": "rotate_identity"},
                {"type": "wait", "seconds": 2.0},
                {"type": "full_reset"},
            ]
            (nested / "one.json").write_text(json.dumps(payload), encoding="utf-8")
            old = sp.SEQUENCES_DIR
            try:
                sp.SEQUENCES_DIR = root
                ent = {
                    "sequence_playlist": ["900x1600/no-ad/one.json"],
                    "sequence_playlist_mode": "ordered",
                    "sequence_profile_key": "900x1600",
                }
                steps, note = sp.resolve_steps(ent, 0, "127.0.0.1:16384", [])
                self.assertEqual(note, "900x1600/no-ad/one.json")
                # load_steps_from_filename preserves "type" and also fills "action"
                # for callers that read the newer field name.
                types = [s.get("type") for s in steps]
                self.assertEqual(types, ["wait", "rotate_identity", "wait", "full_reset"])
                actions = [s.get("action") for s in steps]
                self.assertEqual(actions, ["wait", "rotate_identity", "wait", "full_reset"])
            finally:
                sp.SEQUENCES_DIR = old

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nested = root / "900x1600" / "no-ad"
            nested.mkdir(parents=True)
            # Wrapped with sequence_version so discover_sequence_files' fallback search
            # (used by load_steps_from_filename below) recognizes it as canonical v3+.
            payload = {"sequence_version": 3, "steps": [{"type": "wait", "seconds": 1.0}]}
            (nested / "starter.json").write_text(json.dumps(payload), encoding="utf-8")
            old = sp.SEQUENCES_DIR
            try:
                sp.SEQUENCES_DIR = root
                found = sp.resolve_sequence_file("starter.json", "900x1600")
                self.assertIsNotNone(found)
                self.assertEqual(found.name, "starter.json")
                # load_steps_from_filename's 2nd arg is a directory Path (unlike
                # resolve_sequence_file's profile_key string above) — pass SEQUENCES_DIR
                # so the lookup honors this test's monkeypatched sequences root.
                steps = sp.load_steps_from_filename("starter.json", sp.SEQUENCES_DIR)
                self.assertEqual(len(steps or []), 1)
            finally:
                sp.SEQUENCES_DIR = old


    def test_folder_random_resolves_all_json_as_series(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nested = root / "900x1600" / "no-ad"
            nested.mkdir(parents=True)
            (nested / "a.json").write_text(json.dumps([{"type": "wait", "seconds": 1.0}]), encoding="utf-8")
            (nested / "b.json").write_text(json.dumps([{"type": "wait", "seconds": 2.0}]), encoding="utf-8")
            old = sp.SEQUENCES_DIR
            try:
                sp.SEQUENCES_DIR = root
                ent = {
                    "sequence_playlist_mode": "folder_random",
                    "sequence_folder": "900x1600/no-ad",
                    "sequence_profile_key": "900x1600",
                }
                chunks_a = sp.resolve_step_chunks(ent, 0, "serial-a", [])
                chunks_b = sp.resolve_step_chunks(ent, 0, "serial-b", [])
                self.assertEqual(len(chunks_a), 2)
                self.assertEqual(len(chunks_b), 2)
                order_a = [c[1] for c in chunks_a]
                order_b = [c[1] for c in chunks_b]
                self.assertEqual(sorted(order_a), sorted(order_b))
                self.assertEqual(sp.playlist_cycle_length(ent), 1)
            finally:
                sp.SEQUENCES_DIR = old

    def test_folder_sorted_uses_stable_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            nested = root / "900x1600" / "no-ad"
            nested.mkdir(parents=True)
            (nested / "b.json").write_text(json.dumps([{"type": "wait", "seconds": 1.0}]), encoding="utf-8")
            (nested / "a.json").write_text(json.dumps([{"type": "wait", "seconds": 2.0}]), encoding="utf-8")
            old = sp.SEQUENCES_DIR
            try:
                sp.SEQUENCES_DIR = root
                ent = {
                    "sequence_playlist_mode": "folder",
                    "sequence_folder": "900x1600/no-ad",
                    "sequence_profile_key": "900x1600",
                }
                chunks = sp.resolve_step_chunks(ent, 0, "serial-1", [])
                self.assertEqual([c[1] for c in chunks], ["900x1600/no-ad/a.json", "900x1600/no-ad/b.json"])
            finally:
                sp.SEQUENCES_DIR = old


if __name__ == "__main__":
    unittest.main()
