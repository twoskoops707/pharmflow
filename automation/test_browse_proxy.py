"""Unit tests for browse_proxy modes and prefs."""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from automation import browse_proxy as bp


class BrowseProxyPrefsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._td = tempfile.TemporaryDirectory()
        self.prefs = Path(self._td.name) / "desktop_prefs.json"
        self.prefs.write_text(
            json.dumps(
                {
                    "browse_proxy_mode": "scramble",
                    "phone_upstream_proxies": ["http://u:p@1.2.3.4:8080"],
                }
            ),
            encoding="utf-8",
        )
        self._patch = patch.object(bp, "_prefs_path", return_value=self.prefs)
        self._patch.start()

    def tearDown(self) -> None:
        self._patch.stop()
        self._td.cleanup()
        os.environ.pop("PHARMFLOW_BROWSE_PROXY_MODE", None)

    def test_mode_from_prefs_default_scramble(self) -> None:
        self.assertEqual(bp.browse_proxy_mode(), "scramble")

    def test_env_overrides_prefs(self) -> None:
        os.environ["PHARMFLOW_BROWSE_PROXY_MODE"] = "tor"
        self.assertEqual(bp.browse_proxy_mode(), "tor")

    def test_upstream_url_for_phone(self) -> None:
        self.assertEqual(bp.upstream_proxy_url_for_phone(0), "http://u:p@1.2.3.4:8080")
        self.assertIsNone(bp.upstream_proxy_url_for_phone(1))

    def test_parse_upstream_url(self) -> None:
        host, port, auth = bp._parse_upstream_url("http://user:secret@proxy.example:3128")
        self.assertEqual(host, "proxy.example")
        self.assertEqual(port, 3128)
        self.assertTrue(auth and auth.startswith("Basic "))

    def test_save_browse_prefs(self) -> None:
        saved = bp.save_browse_prefs(browse_proxy_mode="upstream")
        self.assertIsInstance(saved, dict)
        data = json.loads(self.prefs.read_text(encoding="utf-8"))
        self.assertEqual(data["browse_proxy_mode"], "upstream")
        self.assertEqual(data["phone_upstream_proxies"], ["http://u:p@1.2.3.4:8080"])

    def test_corrupt_prefs_are_not_replaced(self) -> None:
        self.prefs.write_text("{not json", encoding="utf-8")
        self.assertIsNone(bp.save_browse_prefs(browse_proxy_mode="direct"))
        self.assertEqual(self.prefs.read_text(encoding="utf-8"), "{not json")


class BrowseProxySessionTests(unittest.TestCase):
    @patch.object(bp, "guest_proxy_healthy", return_value=True)
    @patch("automation.emulator_ad_mode.scramble_device_session")
    @patch.object(bp, "pin_guest_proxy", return_value="127.0.0.1:8257")
    @patch.object(bp, "browse_proxy_mode", return_value="scramble")
    def test_prepare_scramble_pins_inject(self, _mode, pin, scramble, _healthy) -> None:
        scramble.return_value = {"ok": True}
        out = bp.prepare_browse_session(object(), "10.0.2.108:5555", 39)
        self.assertTrue(out.get("ok"))
        self.assertEqual(out.get("http_proxy"), "127.0.0.1:8257")
        pin.assert_called_once()
        scramble.assert_called_once()

    @patch.object(bp, "guest_proxy_healthy", return_value=True)
    @patch.object(bp, "pin_guest_proxy", return_value="127.0.0.1:8257")
    @patch.object(bp, "browse_proxy_mode", return_value="tor")
    def test_prepare_tor_pins_not_clears(self, _mode, pin, _healthy) -> None:
        out = bp.prepare_browse_session(object(), "10.0.2.108:5555", 39, force_clear_tor=True)
        self.assertTrue(out.get("ok"))
        self.assertFalse(out.get("force_clear_tor"))
        pin.assert_called_once()


if __name__ == "__main__":
    unittest.main()
