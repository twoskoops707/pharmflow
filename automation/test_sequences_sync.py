#!/usr/bin/env python3
"""Tests for shipped-sequence sync into ~/CPharm/sequences."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

_AUTOMATION_DIR = Path(__file__).resolve().parent
if str(_AUTOMATION_DIR) not in sys.path:
    sys.path.insert(0, str(_AUTOMATION_DIR))

import sequences_sync as ss  # noqa: E402


class SequencesSyncTests(unittest.TestCase):
    def test_find_shipped_sequences_source_from_repo(self) -> None:
        src = ss.find_shipped_sequences_source()
        self.assertIsNotNone(src)
        assert src is not None
        self.assertTrue((src / "900x1600" / "no-ad" / "dabflow__demo__ONE.json").is_file())

    def test_sync_copies_playlist_refs(self) -> None:
        repo_src = ss.find_shipped_sequences_source()
        self.assertIsNotNone(repo_src)
        assert repo_src is not None
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "sequences"
            result = ss.sync_shipped_sequences(dest=dest, force=True)
            self.assertTrue(result["ok"], result)
            self.assertGreater(result["copied"], 0)
            for ref in ss.DEFAULT_PLAYLIST_REFS:
                self.assertTrue((dest / ref).is_file(), ref)

    def test_sync_skips_up_to_date_files(self) -> None:
        repo_src = ss.find_shipped_sequences_source()
        self.assertIsNotNone(repo_src)
        assert repo_src is not None
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "sequences"
            first = ss.sync_shipped_sequences(dest=dest, force=True)
            second = ss.sync_shipped_sequences(dest=dest, force=False)
            self.assertTrue(first["ok"])
            self.assertTrue(second["ok"])
            self.assertGreater(first["copied"], 0)
            self.assertGreaterEqual(second["skipped"], first["copied"])

    def test_sync_honors_cpharm_sequences_source_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            custom = Path(tmp) / "custom_sequences"
            nested = custom / "900x1600" / "no-ad"
            nested.mkdir(parents=True)
            payload = [{"type": "wait", "seconds": 1.0}]
            (nested / "dabflow__demo__ONE.json").write_text(
                json.dumps(payload), encoding="utf-8"
            )
            old = os.environ.get("CPHARM_SEQUENCES_SOURCE")
            try:
                os.environ["CPHARM_SEQUENCES_SOURCE"] = str(custom)
                found = ss.find_shipped_sequences_source()
                self.assertEqual(found, custom.resolve())
            finally:
                if old is None:
                    os.environ.pop("CPHARM_SEQUENCES_SOURCE", None)
                else:
                    os.environ["CPHARM_SEQUENCES_SOURCE"] = old

    def test_verify_playlist_refs_detects_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            missing = ss.verify_playlist_refs(
                ["900x1600/no-ad/missing.json"],
                sequences_dir=root,
            )
            self.assertEqual(missing, ["900x1600/no-ad/missing.json"])


if __name__ == "__main__":
    unittest.main()
