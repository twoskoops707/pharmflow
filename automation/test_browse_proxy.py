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
        os.environ.pop("CPHARM_BROWSE_PROXY_MODE", None)

    def test_mode_from_prefs_default_scramble(self) -> None:
        self.assertEqual(bp.browse_proxy_mode(), "scramble")

    def test_env_overrides_prefs(self) -> None:
        os.environ["CPHARM_BROWSE_PROXY_MODE"] = "tor"
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
        bp.save_browse_prefs(browse_proxy_mode="upstream")
        data = json.loads(self.prefs.read_text(encoding="utf-8"))
        self.assertEqual(data["browse_proxy_mode"], "upstream")


class BrowseProxySessionTests(unittest.TestCase):
    @patch("automation.emulator_ad_mode.scramble_device_session")
    @patch("automation.tor_manager.TorManager")
    @patch.object(bp, "browse_proxy_mode", return_value="scramble")
    def test_prepare_scramble(self, _mode, tor_cls, scramble) -> None:
        tor = tor_cls.return_value
        tor.clear_all_proxies_on_devices.return_value = []
        scramble.return_value = {"ok": True}
        out = bp.prepare_browse_session(object(), "10.0.2.108:5555", 0)
        self.assertTrue(out.get("ok"))
        scramble.assert_called_once()
        tor.clear_all_proxies_on_devices.assert_called_once()
        tor.kick_default_browser_after_proxy_teardown.assert_called_once()

    @patch.object(bp, "browse_proxy_mode", return_value="tor")
    def test_prepare_tor_skips(self, _mode) -> None:
        out = bp.prepare_browse_session(object(), "10.0.2.108:5555", 0)
        self.assertTrue(out.get("skipped"))


if __name__ == "__main__":
    unittest.main()
