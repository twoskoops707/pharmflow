#!/usr/bin/env python3
"""Unit tests for dabflow_mantis_client_patch (no device required)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

_AUTOMATION = Path(__file__).resolve().parent
if str(_AUTOMATION) not in sys.path:
    sys.path.insert(0, str(_AUTOMATION))

import dabflow_mantis_client_patch as patch  # noqa: E402
import dabflow_mantis_ad_urls as mantis_urls  # noqa: E402
import mumu_fingerprint as mf  # noqa: E402


class DabflowMantisPatchTests(unittest.TestCase):
    def test_is_dabflow_url(self) -> None:
        self.assertTrue(patch.is_dabflow_url("https://getdabflow.app"))
        self.assertTrue(patch.is_dabflow_url("https://www.getdabflow.app/path"))
        self.assertFalse(patch.is_dabflow_url("https://google.com"))

    def test_patch_js_contains_zone_fixes(self) -> None:
        self.assertIn("zone-four", patch.PATCH_JS)
        self.assertNotIn("zone-four-", patch.PATCH_JS)
        self.assertIn("cooldown-video-ad", patch.PATCH_JS)
        self.assertIn("__pharmflowMantisPatchV1", patch.PATCH_JS)

    def test_host_cdp_port_per_phone(self) -> None:
        self.assertEqual(patch.host_cdp_port(0), 9222)
        self.assertEqual(patch.host_cdp_port(1), 9223)

    def test_device_forward_targets_socket_first(self) -> None:
        targets = patch._device_forward_targets()
        self.assertTrue(targets)
        # Modern Chrome binds DevTools to the abstract socket, not tcp:9222.
        self.assertEqual(targets[0], "localabstract:chrome_devtools_remote")
        self.assertIn(f"tcp:{patch.DEVICE_CDP_PORT}", targets)

    def test_chromium_flags_include_cdp_when_requested(self) -> None:
        prof = mf.profile_for_index(0)
        flags = mf.build_chromium_flags(prof, cdp_port=9222)
        self.assertIn("--remote-debugging-port=9222", flags)

    def test_patch_enabled_env(self) -> None:
        import os

        old = os.environ.get("PHARMFLOW_DABFLOW_MANTIS_PATCH")
        try:
            os.environ["PHARMFLOW_DABFLOW_MANTIS_PATCH"] = "0"
            self.assertFalse(patch.patch_enabled_from_env())
            os.environ["PHARMFLOW_DABFLOW_MANTIS_PATCH"] = "1"
            self.assertTrue(patch.patch_enabled_from_env())
        finally:
            if old is None:
                os.environ.pop("PHARMFLOW_DABFLOW_MANTIS_PATCH", None)
            else:
                os.environ["PHARMFLOW_DABFLOW_MANTIS_PATCH"] = old


class MantisAdUrlPublisherTests(unittest.TestCase):
    def test_tag_landing_adds_publisher_id(self) -> None:
        raw = (
            "https://ageofhemp.com/collections/best-deals"
            "?utm_source=Mantis&utm_medium=Banner&utm_campaign=Top+Sellers"
        )
        out = mantis_urls.tag_landing_with_publisher(raw)
        self.assertIn("utm_medium=6950d5527c56c6494f189e46", out)
        self.assertIn("utm_source=mantis", out)

    def test_tag_landing_preserves_live_campaign(self) -> None:
        raw = (
            "https://www.smokecartel.com/?utm_source=mantis"
            "&utm_medium=6950d5527c56c6494f189e46"
            "&utm_campaign=64f737aa6bde25000fe6a6b1"
            "&utm_content=64f73c1d76e98a0023574ea6"
        )
        out = mantis_urls.tag_landing_with_publisher(raw)
        self.assertIn("utm_campaign=64f737aa6bde25000fe6a6b1", out)
        self.assertIn("utm_content=64f73c1d76e98a0023574ea6", out)


if __name__ == "__main__":
    unittest.main()
