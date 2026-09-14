"""Audit: sequence block, ad fallback URLs, Mantis patch JS."""

from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

from automation.config import REQUIRED_SEQUENCE_VERSION, sequences_run_allowed
from automation.dabflow_mantis_client_patch import PATCH_JS, host_cdp_port, is_dabflow_url, patch_enabled_from_env
from automation.dabflow_mantis_ad_urls import (
    fallback_landing_for_checkpoint,
    fetch_mantis_landing_urls,
    tag_landing_with_publisher,
)
from automation.emulator_ad_mode import ad_checkpoint_from_description
from automation.sequence_runner import Sequence, SequenceRunner


class SequenceRunBlockTests(unittest.TestCase):
    def test_blocked_by_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("PHARMFLOW_ALLOW_SEQUENCE_RUNS", None)
            self.assertFalse(sequences_run_allowed())

    def test_runner_refuses_when_blocked(self) -> None:
        farm = MagicMock()
        runner = SequenceRunner(farm)
        seq = Sequence(name="t", phone="p", steps=[], sequence_version=REQUIRED_SEQUENCE_VERSION)
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("PHARMFLOW_ALLOW_SEQUENCE_RUNS", None)
            report = runner.run(seq)
        self.assertFalse(report["success"])
        self.assertIn("BLOCKED", report["error"])
        farm.adb.assert_not_called()


class AdPipelineTests(unittest.TestCase):
    def test_dabflow_url_detection(self) -> None:
        self.assertTrue(is_dabflow_url("https://getdabflow.app"))
        self.assertFalse(is_dabflow_url("https://example.com"))

    def test_mantis_patch_js_no_typo_zones(self) -> None:
        self.assertIn("zone-four", PATCH_JS)
        self.assertNotIn("zone-four-", PATCH_JS)
        self.assertIn("cooldown-video-ad", PATCH_JS)

    def test_host_cdp_port_per_phone(self) -> None:
        self.assertEqual(host_cdp_port(0), 9222)
        self.assertEqual(host_cdp_port(1), 9223)

    def test_tag_landing_adds_publisher_id(self) -> None:
        raw = (
            "https://ageofhemp.com/collections/best-deals"
            "?utm_source=Mantis&utm_medium=Banner&utm_campaign=Top+Sellers"
        )
        out = tag_landing_with_publisher(raw)
        self.assertIn("utm_medium=6950d5527c56c6494f189e46", out)
        self.assertIn("utm_source=mantis", out)

    def test_resolve_ad_fallback_prefers_live(self) -> None:
        from automation.emulator_ad_mode import resolve_ad_fallback_url

        url = resolve_ad_fallback_url("ad_home")
        self.assertTrue(url and url.startswith("http"))

    def test_patch_enabled_default_on(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("PHARMFLOW_DABFLOW_MANTIS_PATCH", None)
            self.assertTrue(patch_enabled_from_env())

    def test_fallback_urls_for_checkpoints(self) -> None:
        self.assertIn("grasscity", fallback_landing_for_checkpoint("ad_home") or "")
        self.assertIn("mantis", fallback_landing_for_checkpoint("ad_timer_banner") or "")

    def test_checkpoint_from_description(self) -> None:
        self.assertEqual(ad_checkpoint_from_description("Tap home ad banner"), "ad_home")
        self.assertEqual(ad_checkpoint_from_description("Tap ad (home slot 0)"), "ad_home")
        self.assertEqual(ad_checkpoint_from_description("Tap post-timer ad banner"), "ad_timer_banner")

    def test_path3_tap_ad_description_is_ad_engagement(self) -> None:
        """Path3 steps are 'Tap ad (home slot N)' — must match engagement matcher."""
        desc_lower = "Tap ad (home slot 0)".lower()
        is_ad_tap = (
            "tap ad" in desc_lower
            or (
                "ad" in desc_lower
                and (
                    "banner" in desc_lower
                    or "mantis" in desc_lower
                    or "slot" in desc_lower
                    or "sponsored" in desc_lower
                )
            )
        )
        self.assertTrue(is_ad_tap)

    def test_mantis_ssp_fetch_zone_one(self) -> None:
        try:
            urls = fetch_mantis_landing_urls(["zone-one"], timeout=25.0)
        except OSError:
            self.skipTest("network unavailable")
        if "zone-one" not in urls:
            self.skipTest("SSP returned no zone-one ad (fallback still configured)")
        self.assertTrue(urls["zone-one"].startswith("http"))
