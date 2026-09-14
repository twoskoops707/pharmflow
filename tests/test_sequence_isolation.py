"""Isolation skip must never fire on a live farm."""

from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from automation.phone_geo_time import GEO_CATALOG, GeoLocale
from automation.sequence_isolation import (
    _last_geo_by_serial,
    _pick_fresh_locale,
    _pin_inject_for_isolate,
    isolation_skip_allowed,
)


class IsolationSkipTests(unittest.TestCase):
    def test_live_farm_ignores_skip_env(self) -> None:
        env = {
            "PHARMFLOW_SKIP_SEQUENCE_ISOLATION": "1",
            "PHARMFLOW_ALLOW_SEQUENCE_RUNS": "1",
        }
        with patch.dict(os.environ, env, clear=False):
            self.assertFalse(isolation_skip_allowed())

    def test_demo_verify_may_skip(self) -> None:
        env = {
            "PHARMFLOW_SKIP_SEQUENCE_ISOLATION": "1",
            "PHARMFLOW_ALLOW_SEQUENCE_RUNS": "0",
        }
        with patch.dict(os.environ, env, clear=False):
            self.assertTrue(isolation_skip_allowed())

    def test_default_does_not_skip(self) -> None:
        env = {
            "PHARMFLOW_SKIP_SEQUENCE_ISOLATION": "0",
            "PHARMFLOW_ALLOW_SEQUENCE_RUNS": "1",
        }
        with patch.dict(os.environ, env, clear=False):
            self.assertFalse(isolation_skip_allowed())


class PinHonestyTests(unittest.TestCase):
    def test_tor_fallback_is_not_a_pin_unless_the_guest_read_matches(self) -> None:
        class _Adb:
            def set_http_proxy(self, host, port, serial=None):
                return None

            def shell(self, cmd, serial=None):
                class _Out:
                    stdout = ":0"
                return _Out()

        farm = type("Farm", (), {"adb": _Adb()})()
        with (
            patch("automation.sequence_isolation.restore_inject_after_identity", return_value=":0"),
            patch("automation.sequence_isolation.phone_http_port", return_value=8118),
            patch("automation.sequence_isolation.get_sequence_browser", return_value=None),
            patch("automation.sequence_isolation.remember_browser_package"),
            patch("automation.sequence_isolation.time.sleep"),
        ):
            with self.assertRaises(RuntimeError):
                _pin_inject_for_isolate(
                    farm,
                    "phone",
                    0,
                    "10.0.2.20:5555",
                    preferred_browser="org.chromium.chrome",
                )

    def test_a_landed_loopback_read_is_the_pin(self) -> None:
        class _Adb:
            def set_http_proxy(self, host, port, serial=None):
                return None

            def shell(self, cmd, serial=None):
                class _Out:
                    stdout = "127.0.0.1:8118"
                return _Out()

        farm = type("Farm", (), {"adb": _Adb()})()
        with (
            patch("automation.sequence_isolation.restore_inject_after_identity", return_value=""),
            patch("automation.sequence_isolation.phone_http_port", return_value=8118),
            patch("automation.sequence_isolation.get_sequence_browser", return_value=None),
            patch("automation.sequence_isolation.remember_browser_package"),
            patch("automation.sequence_isolation.guest_proxy_healthy", return_value=True),
            patch("automation.sequence_isolation.time.sleep"),
        ):
            pinned = _pin_inject_for_isolate(
                farm,
                "phone",
                0,
                "10.0.2.20:5555",
                preferred_browser="org.chromium.chrome",
            )
        self.assertEqual(pinned, "127.0.0.1:8118")


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
