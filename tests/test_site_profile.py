"""Tests for generic SiteProfile + sequence generation (site-agnostic EXE)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from automation.dabflow_site_profile import dabflow_profile, ensure_dabflow_profile
from automation.site_profile import AdClick, SiteProfile, interview_defaults, load_profile, save_profile
from automation.site_sequence_gen import (
    build_sequence_variants,
    validate_sequence_variants,
    write_profile_sequences,
)


class SiteProfileTests(unittest.TestCase):
    def test_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            p = interview_defaults(kind="website", name="Demo Site", url="https://example.com")
            path = save_profile(root, p)
            self.assertTrue(path.is_file())
            loaded = load_profile(root, p.slug)
            self.assertEqual(loaded.url, "https://example.com")
            self.assertEqual(loaded.display_name, "Demo Site")
            # FarmPrefs defaults (SSOT): 4-phone money set with matching CSVs.
            self.assertEqual(loaded.farm.phone_count, 4)
            self.assertEqual(loaded.farm.ntfy_interval_s, 7200)

    def test_generate_variants(self) -> None:
        p = interview_defaults(kind="website", name="Demo", url="https://example.com")
        seqs = build_sequence_variants(p)
        self.assertGreaterEqual(len(seqs), 2)
        names = {s["name"] for s in seqs}
        self.assertTrue(any("path1_complete" in n for n in names))
        self.assertTrue(any(n.endswith("_browse") for n in names))
        self.assertTrue(any(n.endswith("_ad") for n in names))
        self.assertTrue(all(s.get("sequence_version") for s in seqs))
        self.assertTrue(all(s.get("site_slug") == p.slug for s in seqs))
        self.assertTrue(all(s.get("requires_fingerprint") is True for s in seqs))
        for seq in seqs:
            actions = [step["action"] for step in seq["steps"]]
            self.assertEqual(actions[0], "rotate_identity")
            self.assertIn("ensure_fingerprint", actions)
            self.assertIn("clear_cookies", actions)
            self.assertEqual(actions[-1], "close_app")
        audit = validate_sequence_variants(seqs)
        self.assertTrue(audit["ok"], audit["errors"])
        self.assertEqual(audit["unique_bodies"], len(seqs))
        self.assertGreater(audit["unique_start_waits"], 1)

    def test_multiple_ad_targets_generate_distinct_ad_sequences(self) -> None:
        p = interview_defaults(kind="website", name="Ads", url="https://example.com")
        p.ads = [
            AdClick(name="sponsored_0", x=300, y=900),
            AdClick(name="sponsored_1", x=600, y=1100),
        ]
        seqs = build_sequence_variants(p)
        audit = validate_sequence_variants(seqs)
        self.assertTrue(audit["ok"], audit["errors"])
        self.assertEqual(audit["unique_ad_targets"], 2)
        ad_sequences = [seq for seq in seqs if seq["name"].endswith("_ad")]
        self.assertEqual(len(ad_sequences), 2)

    def test_write_sequences(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out = Path(td)
            p = interview_defaults(kind="app", name="DemoApp", package="com.example.app")
            p.url = ""
            n = write_profile_sequences(p, out, clean=True)
            self.assertGreater(n, 0)
            files = list((out / p.slug).glob("*.json"))
            self.assertGreaterEqual(len(files), n)
            sample = json.loads(files[0].read_text(encoding="utf-8"))
            self.assertIn("steps", sample)

    def test_dabflow_reference_adapter_is_seeded_once(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            first = ensure_dabflow_profile(root)
            first.write_text(first.read_text(encoding="utf-8").replace("DabFlow", "Custom"), encoding="utf-8")
            second = ensure_dabflow_profile(root)
            self.assertEqual(first, second)
            self.assertIn("Custom", second.read_text(encoding="utf-8"))
        profile = dabflow_profile()
        self.assertEqual(profile.adapter, "dabflow")
        self.assertEqual(profile.url, "https://getdabflow.app/")


if __name__ == "__main__":
    unittest.main()
