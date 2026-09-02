"""Sequence discovery: base/ only, v2 required."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from automation.config import REQUIRED_SEQUENCE_VERSION
from automation.sequence_paths import discover_sequence_files, list_sequence_ids, resolve_sequence_path


class SequencePathsTests(unittest.TestCase):
    def test_base_only_skips_humanized_and_v1(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "base" / "ceramic"
            humanized = root / "humanized" / "ceramic"
            base.mkdir(parents=True)
            humanized.mkdir(parents=True)

            v2 = {
                "name": "ceramic_test_ad",
                "sequence_version": REQUIRED_SEQUENCE_VERSION,
                "steps": [{"action": "wait", "params": {"seconds": 1}}],
            }
            v1 = {
                "name": "old_seq",
                "sequence_version": 1,
                "steps": [{"action": "wait", "params": {"seconds": 1}}],
            }
            (base / "ceramic_test_ad.json").write_text(json.dumps(v2), encoding="utf-8")
            (humanized / "ceramic_test_ad.json").write_text(json.dumps(v2), encoding="utf-8")
            (root / "old_flat.json").write_text(json.dumps(v1), encoding="utf-8")

            files = discover_sequence_files(root)
            self.assertEqual(len(files), 1)
            self.assertIn("base", files[0].parts)
            self.assertNotIn("humanized", files[0].parts)

            ids = list_sequence_ids(root)
            self.assertEqual(ids, ["base/ceramic/ceramic_test_ad"])

            resolved = resolve_sequence_path(root, "ceramic_test_ad")
            self.assertEqual(resolved, base / "ceramic_test_ad.json")
