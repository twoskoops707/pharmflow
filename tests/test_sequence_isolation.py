"""Isolation skip must never fire on a live farm."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from automation.phone_geo_time import GEO_CATALOG, GeoLocale
from automation.sequence_isolation import (
    _last_geo_by_serial,
    _pick_fresh_locale,
    isolation_skip_allowed,
)


class IsolationSkipTests(unittest.TestCase):
    def test_live_farm_ignores_skip_env(self) -> None:
        env = {
            "CPHARM_SKIP_SEQUENCE_ISOLATION": "1",
            "CPHARM_ALLOW_SEQUENCE_RUNS": "1",
        }
        with patch.dict(os.environ, env, clear=False):
            self.assertFalse(isolation_skip_allowed())

    def test_demo_verify_may_skip(self) -> None:
        env = {
            "CPHARM_SKIP_SEQUENCE_ISOLATION": "1",
            "CPHARM_ALLOW_SEQUENCE_RUNS": "0",
        }
        with patch.dict(os.environ, env, clear=False):
            self.assertTrue(isolation_skip_allowed())

    def test_default_does_not_skip(self) -> None:
        env = {
            "CPHARM_SKIP_SEQUENCE_ISOLATION": "0",
            "CPHARM_ALLOW_SEQUENCE_RUNS": "1",
        }
        with patch.dict(os.environ, env, clear=False):
            self.assertFalse(isolation_skip_allowed())


class GeoPickTests(unittest.TestCase):
    def test_does_not_repeat_last_city_when_catalog_has_others(self) -> None:
        serial = "test-geo-serial"
        last = GEO_CATALOG[0]
        _last_geo_by_serial[serial] = last.label
        try:
            with patch(
                "automation.sequence_isolation.locales_in_window",
                return_value=list(GEO_CATALOG[:4]),
            ):
                picked = _pick_fresh_locale(serial)
            self.assertIsInstance(picked, GeoLocale)
            self.assertNotEqual(picked.label, last.label)
        finally:
            _last_geo_by_serial.pop(serial, None)


if __name__ == "__main__":
    unittest.main()
