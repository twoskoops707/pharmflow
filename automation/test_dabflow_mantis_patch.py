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

    def test_cdp_abstract_sockets_returns_tuple(self) -> None:
        sockets = patch.cdp_abstract_sockets()
        self.assertIsInstance(sockets, tuple)
        self.assertIn("chrome_devtools_remote", sockets)

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


class LiveTorPortsHaveNoFixedFleetSizeTests(unittest.TestCase):
    """The paying-inventory Tor leg probes the real fleet's lanes. When the live
    lock is unreadable it must ask the fleet-discovery the Tor layer already
    uses (then the lanes actually listening) -- never a guessed roster of eight
    (repo rule: no hardcoded phone-count ceilings)."""

    @staticmethod
    def _lane(idx: int) -> int:
        return 8100 + int(idx)

    def _run(self, *, lock_phones, fleet, listening=()):
        import json
        import os
        import tempfile
        from unittest import mock

        with tempfile.TemporaryDirectory() as tmp:
            if lock_phones is not None:
                (Path(tmp) / "ADB_SERIAL_MAP.lock.json").write_text(
                    json.dumps({"phones": lock_phones}), encoding="utf-8"
                )
            with mock.patch.dict(os.environ, {"PHARMFLOW_LOGS": tmp}), \
                    mock.patch("automation.mantis_inject_proxy.upstream_tor_port", self._lane), \
                    mock.patch("automation.tor_manager.live_fleet_indices", return_value=list(fleet)), \
                    mock.patch(
                        "automation.tor_manager.listening_tor_http_lane_ports",
                        return_value=list(listening),
                    ):
                return patch._live_tor_http_ports()

    def test_live_lock_is_used_first_even_for_high_indexes(self) -> None:
        phones = {f"vm{i}.gmadoa": f"10.0.2.{i}:5555" for i in (39, 40, 41)}
        self.assertEqual(self._run(lock_phones=phones, fleet=[1, 2]), [8139, 8140, 8141])

    def test_a_large_fleet_is_not_cut_to_eight_lanes(self) -> None:
        phones = {f"vm{i}.gmadoa": "x" for i in range(60)}
        self.assertEqual(len(self._run(lock_phones=phones, fleet=[])), 60)

    def test_unreadable_lock_falls_back_to_tor_fleet_discovery_not_range_8(self) -> None:
        ports = self._run(lock_phones=None, fleet=[3, 4, 5])
        self.assertEqual(ports, [8103, 8104, 8105])
        self.assertFalse(set(ports) & {8100, 8101, 8102, 8106, 8107})  # old range(8) guess

    def test_no_roster_anywhere_probes_only_listening_lanes(self) -> None:
        ports = self._run(lock_phones=None, fleet=[], listening=[9001, 9002, 9003])
        self.assertEqual(ports, [9001, 9002, 9003])

    def test_no_roster_and_nothing_listening_yields_no_tor_leg(self) -> None:
        self.assertEqual(self._run(lock_phones=None, fleet=[], listening=[]), [])

    def test_source_has_no_fixed_eight_lane_guess(self) -> None:
        import inspect

        self.assertNotIn("range(8)", inspect.getsource(patch._live_tor_http_ports))
        self.assertNotIn("range(8)", inspect.getsource(patch.prefetch_ssp_ads_prefer_paying))


if __name__ == "__main__":
    unittest.main()
