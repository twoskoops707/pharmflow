"""Tests for automation/dashboard.py — asyncio HTTP API (post-Flask rewrite)."""

from __future__ import annotations

import asyncio
import io
import json
import sys
import unittest
from unittest.mock import MagicMock, patch

import automation.dashboard as dashboard


def _run(coro):
    return asyncio.run(coro)


class DashboardApiTests(unittest.TestCase):
    """Drive the real handlers (handle_get / handle_post) with mocked ADB layer."""

    def test_index_serves_ui(self) -> None:
        resp = _run(dashboard.handle_get("/"))
        self.assertEqual(resp[:12], b"HTTP/1.1 200")
        self.assertIn(b"PharmFlow", resp)
        self.assertIn(b"/api/phones", resp)

    def test_api_phones(self) -> None:
        with patch.object(dashboard, "list_phones", return_value=[{"serial": "127.0.0.1:16384", "status": "device"}]):
            resp = _run(dashboard.handle_get("/api/phones"))
        self.assertEqual(resp[:12], b"HTTP/1.1 200")
        body = json.loads(resp.split(b"\r\n\r\n", 1)[1])
        self.assertIsInstance(body, list)
        self.assertEqual(body[0]["serial"], "127.0.0.1:16384")

    def test_api_config_names_app(self) -> None:
        resp = _run(dashboard.handle_get("/api/config"))
        body = json.loads(resp.split(b"\r\n\r\n", 1)[1])
        self.assertEqual(body.get("appName"), "PharmFlow")
        self.assertIn("httpPort", body)

    def test_api_ip_reports_listen_url(self) -> None:
        with patch.object(dashboard, "get_local_ip", return_value="127.0.0.1"):
            resp = _run(dashboard.handle_get("/api/ip"))
        body = json.loads(resp.split(b"\r\n\r\n", 1)[1])
        self.assertEqual(body["ip"], "127.0.0.1")
        self.assertIn("url", body)

    def test_api_stealth_payload(self) -> None:
        with patch.object(dashboard, "_get_stealth_payload", return_value=[]):
            resp = _run(dashboard.handle_get("/api/stealth"))
        body = json.loads(resp.split(b"\r\n\r\n", 1)[1])
        self.assertTrue(body["ok"])
        self.assertEqual(body["phones"], [])

    def test_unknown_api_404(self) -> None:
        resp = _run(dashboard.handle_get("/api/does_not_exist"))
        self.assertIn(b"404", resp.split(b"\r\n", 1)[0])

    def test_api_money_history(self) -> None:
        with patch("scorecard_api.build_money_history", return_value=[{"day": "2026-09-08", "usd": 0.13}]):
            resp = _run(dashboard.handle_get("/api/money/history"))
        body = json.loads(resp.split(b"\r\n\r\n", 1)[1])
        self.assertTrue(body["ok"])
        self.assertEqual(body["days"][0]["usd"], 0.13)

    def test_post_connect_requires_address(self) -> None:
        resp = _run(dashboard.handle_post("/api/devices/connect", json.dumps({}).encode()))
        self.assertIn(b"400", resp.split(b"\r\n", 1)[0])

    def test_post_connect_calls_adb_and_pushes(self) -> None:
        with (
            patch.object(dashboard, "_adb_global", return_value=MagicMock(text="connected", returncode=0)) as adb,
            patch.object(dashboard, "push_phones", new=MagicMock()) as push_mock,
        ):
            # push_phones is awaited — wrap as coroutine.
            async def _push():
                return None

            push_mock.side_effect = _push
            resp = _run(
                dashboard.handle_post(
                    "/api/devices/connect",
                    json.dumps({"address": "127.0.0.1:16384"}).encode(),
                )
            )
        adb.assert_called_once()
        body = json.loads(resp.split(b"\r\n\r\n", 1)[1])
        self.assertTrue(body["ok"])

    def test_force_utf8_stdio_does_not_close_replaced_stream(self) -> None:
        """Regression: replacing stdout must never orphan-close the previous fd.

        The old code assigned ``io.TextIOWrapper(sys.stdout.buffer, ...)`` which
        let the discarded wrapper close the underlying stream on GC — this
        crashed pytest capture and any embedding host.
        """
        buf = io.BytesIO()
        replaced = io.TextIOWrapper(buf, encoding="cp1252")
        orig = sys.stdout
        sys.stdout = replaced
        try:
            dashboard._force_utf8_stdio()
            new = sys.stdout
            self.assertIsNot(new, replaced)
            self.assertIn("utf-8", (getattr(new, "encoding", "") or "").lower())
            self.assertFalse(buf.closed)
            new.write("probe")
            new.flush()
            self.assertEqual(buf.getvalue(), b"probe")
        finally:
            new = sys.stdout
            try:
                new.detach()  # keep buf open when the temp wrapper is GC'd
            except Exception:
                pass
            sys.stdout = orig


if __name__ == "__main__":
    unittest.main()
